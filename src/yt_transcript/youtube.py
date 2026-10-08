"""YouTube URL handling, caption track selection and the yt-dlp wrapper."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from yt_transcript.models import CaptionTrack, Playlist, PlaylistEntry, VideoMetadata

log = logging.getLogger(__name__)

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{2,}$")
_YOUTUBE_HOSTS = {"youtube.com", "youtube-nocookie.com"}
_VIDEO_PATH_PREFIXES = ("shorts", "live", "embed", "v", "e")
_REGION = re.compile(r"^(?:[A-Z]{2}|\d{3})$")  # en-GB, en-US, es-419
_PREFERRED_REGIONS = ("US", "GB")
_SUBTITLE_FORMATS = ("vtt", "srt")


class YouTubeError(Exception):
    """A video or playlist could not be retrieved."""


class NoCaptionsError(YouTubeError):
    """A video has no usable English captions."""


@dataclass(frozen=True)
class YouTubeURL:
    kind: str  # "video" or "playlist"
    id: str

    @property
    def url(self) -> str:
        if self.kind == "playlist":
            return f"https://www.youtube.com/playlist?list={self.id}"
        return video_url(self.id)


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_youtube_url(raw: str) -> YouTubeURL | None:
    """Recognise a YouTube video or playlist URL (or a bare 11-character video ID).

    A watch URL that also carries ``list=`` is treated as the single video, matching
    yt-dlp's ``--no-playlist`` behaviour. Returns ``None`` for anything else.
    """
    text = raw.strip()
    if _VIDEO_ID.match(text):
        return YouTubeURL("video", text)
    if "://" not in text:
        text = "https://" + text
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    for prefix in ("www.", "m.", "music."):
        host = host.removeprefix(prefix)
    query = parse_qs(parsed.query)
    segments = [part for part in parsed.path.split("/") if part]

    if host == "youtu.be":
        if segments and _VIDEO_ID.match(segments[0]):
            return YouTubeURL("video", segments[0])
        return None
    if host not in _YOUTUBE_HOSTS:
        return None
    if segments[:1] == ["watch"]:
        video_id = query.get("v", [""])[0]
        return YouTubeURL("video", video_id) if _VIDEO_ID.match(video_id) else None
    if segments[:1] == ["playlist"]:
        playlist_id = query.get("list", [""])[0]
        return YouTubeURL("playlist", playlist_id) if _PLAYLIST_ID.match(playlist_id) else None
    if len(segments) >= 2 and segments[0] in _VIDEO_PATH_PREFIXES and _VIDEO_ID.match(segments[1]):
        return YouTubeURL("video", segments[1])
    return None


# --------------------------------------------------------------------------- tracks


def _is_english(code: str) -> bool:
    return code.split("-")[0].lower() == "en"


def _variant_rank(code: str) -> tuple[int, int, str]:
    """Order English codes: plain "en", then regions (US, GB first), then anything else."""
    parts = code.split("-", 1)
    if len(parts) == 1:
        return (0, 0, code)
    region = parts[1]
    if _REGION.match(region):
        preferred = _PREFERRED_REGIONS.index(region) if region in _PREFERRED_REGIONS else len(_PREFERRED_REGIONS)
        return (1, preferred, code)
    return (2, 0, code)


def _pick_format(formats: Any) -> dict[str, Any] | None:
    if not isinstance(formats, list):
        return None
    for ext in _SUBTITLE_FORMATS:
        for fmt in formats:
            if isinstance(fmt, dict) and fmt.get("ext") == ext and fmt.get("url"):
                return fmt
    return None


def _manual_candidates(subtitles: dict[str, Any]) -> list[str]:
    codes = [code for code in subtitles if _is_english(code)]
    # "en-de"-style keys are machine translations from another language; skip them.
    codes = [code for code in codes if "-" not in code or not re.match(r"^[a-z]{2,3}$", code.split("-", 1)[1])]
    return sorted(codes, key=_variant_rank)


def _automatic_candidates(captions: dict[str, Any], video_language: str | None) -> list[str]:
    """English automatic caption keys that are genuine speech recognition, best first.

    yt-dlp marks the original-language ASR track with an ``-orig`` suffix. Every other
    automatic track is machine-translated from it, so when an ``-orig`` track exists
    only English ``-orig`` tracks are acceptable.
    """
    originals = [code for code in captions if code.endswith("-orig")]
    if originals:
        english = [code for code in originals if _is_english(code.removesuffix("-orig"))]
        return sorted(english, key=lambda code: _variant_rank(code.removesuffix("-orig")))
    if video_language and not _is_english(video_language):
        return []
    return sorted((code for code in captions if _is_english(code)), key=_variant_rank)


def select_caption_track(info: dict[str, Any]) -> CaptionTrack:
    """Choose the best English caption track for a video.

    Priority: manual ``en``; manual regional English; automatic ``en``; automatic
    regional English. Raises :class:`NoCaptionsError` with a readable reason otherwise.
    """
    subtitles = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    automatic = info.get("automatic_captions") or {}

    for code in _manual_candidates(subtitles):
        fmt = _pick_format(subtitles[code])
        if fmt:
            return CaptionTrack(code, False, fmt["url"], fmt["ext"], fmt.get("name"))
    for code in _automatic_candidates(automatic, info.get("language")):
        fmt = _pick_format(automatic[code])
        if fmt:
            return CaptionTrack(code.removesuffix("-orig"), True, fmt["url"], fmt["ext"], fmt.get("name"))

    if not subtitles and not automatic:
        raise NoCaptionsError("No captions are available for this video")
    if any(_is_english(code) for code in automatic):
        raise NoCaptionsError(
            "Only machine-translated English captions are available "
            f"(original language: {_original_language(info, automatic)})"
        )
    available = sorted(set(subtitles) | {code.removesuffix("-orig") for code in automatic if code.endswith("-orig")})
    detail = f" (available: {', '.join(available[:8])}{', ...' if len(available) > 8 else ''})" if available else ""
    raise NoCaptionsError(f"No English captions are available{detail}")


def _original_language(info: dict[str, Any], automatic: dict[str, Any]) -> str:
    originals = [code.removesuffix("-orig") for code in automatic if code.endswith("-orig")]
    return info.get("language") or (originals[0] if originals else "unknown")


# --------------------------------------------------------------------------- metadata


def _iso_date(value: Any, timestamp: Any = None) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
    return None


def metadata_from_info(info: dict[str, Any], track: CaptionTrack | None = None) -> VideoMetadata:
    video_id = info.get("id") or ""
    duration = info.get("duration")
    return VideoMetadata(
        video_id=video_id,
        title=(info.get("title") or video_id or "Untitled").strip(),
        url=video_url(video_id),
        channel=info.get("channel") or info.get("uploader"),
        upload_date=_iso_date(info.get("upload_date"), info.get("timestamp")),
        duration=round(duration) if isinstance(duration, (int, float)) else None,
        language=track.language if track else None,
        transcript_type=track.transcript_type if track else None,
    )


def playlist_from_info(info: dict[str, Any], url: str) -> Playlist:
    entries = []
    for entry in info.get("entries") or []:
        if not isinstance(entry, dict):
            entries.append(PlaylistEntry(None, None, None))
            continue
        video_id = entry.get("id")
        entries.append(
            PlaylistEntry(
                video_id=video_id,
                title=entry.get("title"),
                url=video_url(video_id) if video_id else entry.get("url"),
            )
        )
    playlist_id = info.get("id") or ""
    return Playlist(
        playlist_id=playlist_id,
        title=(info.get("title") or playlist_id or "Playlist").strip(),
        url=url,
        entries=entries,
        channel=info.get("channel") or info.get("uploader"),
    )


# --------------------------------------------------------------------------- yt-dlp


def clean_error(message: str) -> str:
    """Strip yt-dlp's ``ERROR: [youtube] abc123:`` prefixes and colour codes."""
    message = re.sub(r"\x1b\[[0-9;]*m", "", str(message)).strip()
    message = re.sub(r"^ERROR:\s*", "", message)
    message = re.sub(r"^\[[\w:]+\]\s*[\w-]+:\s*", "", message)
    return message.splitlines()[0] if message else "Unknown error"


class _YtDlpLogger:
    """Route yt-dlp's console output into this package's logger."""

    def debug(self, message: str) -> None:
        if not message.startswith("[debug] "):
            log.debug("yt-dlp: %s", message)

    def info(self, message: str) -> None:
        log.debug("yt-dlp: %s", message)

    def warning(self, message: str) -> None:
        log.debug("yt-dlp warning: %s", message)

    def error(self, message: str) -> None:
        log.debug("yt-dlp error: %s", message)


class YouTubeClient:
    """Thin wrapper around yt-dlp. Never downloads media, only metadata and captions."""

    def __init__(self) -> None:
        import yt_dlp

        self._yt_dlp = yt_dlp
        self._options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "skip_download": True,
            "noplaylist": True,
            "logger": _YtDlpLogger(),
        }

    def _extract(self, url: str, **extra: Any) -> dict[str, Any]:
        try:
            with self._yt_dlp.YoutubeDL({**self._options, **extra}) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
        except self._yt_dlp.utils.DownloadError as exc:
            raise YouTubeError(clean_error(str(exc))) from exc
        if not isinstance(info, dict):
            raise YouTubeError("yt-dlp returned no information")
        return info

    def fetch_video(self, url: str) -> dict[str, Any]:
        """Return yt-dlp's info dictionary for a single video."""
        info = self._extract(url)
        if info.get("_type") == "playlist":
            raise YouTubeError("Expected a video but found a playlist")
        return info

    def fetch_playlist(self, url: str) -> Playlist:
        """Return a playlist's title and entries without visiting each video."""
        info = self._extract(url, extract_flat="in_playlist", noplaylist=False)
        if info.get("_type") != "playlist":
            raise YouTubeError("URL did not resolve to a playlist")
        info["entries"] = list(info.get("entries") or [])
        return playlist_from_info(info, url)

    def download_captions(self, track: CaptionTrack) -> str:
        """Download a caption file and return it as text."""
        try:
            with self._yt_dlp.YoutubeDL(self._options) as ydl:
                data = ydl.urlopen(track.url).read()
        except Exception as exc:  # network layer raises a variety of exception types
            raise YouTubeError(f"Could not download captions: {clean_error(str(exc))}") from exc
        return data.decode("utf-8", errors="replace")
