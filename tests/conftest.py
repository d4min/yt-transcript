from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from yt_transcript.models import CaptionTrack, Playlist, PlaylistEntry
from yt_transcript.youtube import YouTubeError

FIXTURES = Path(__file__).parent / "fixtures"


def vtt_time(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def rolling_vtt(lines: list[list[tuple[str, float]]], end: float) -> str:
    """Build a WebVTT file in the exact layout YouTube uses for automatic captions.

    Each caption line is shown twice: first as the bottom row of a two-row cue with
    word-level inline timestamps (the row above repeats the previous line), then in a
    10 ms "transition" cue on its own.
    """
    out = ["WEBVTT", "Kind: captions", "Language: en", ""]
    previous = " "
    for index, line in enumerate(lines):
        start = line[0][1]
        next_start = lines[index + 1][0][1] if index + 1 < len(lines) else end
        timed = line[0][0] + "".join(f"<{vtt_time(t)}><c> {w}</c>" for w, t in line[1:])
        plain = " ".join(w for w, _ in line)
        out += [f"{vtt_time(start)} --> {vtt_time(next_start - 0.01)} align:start position:0%", previous, timed, ""]
        out += [f"{vtt_time(next_start - 0.01)} --> {vtt_time(next_start)} align:start position:0%", plain, " ", ""]
        previous = plain
    return "\n".join(out)


def timed_line(text: str, start: float, step: float = 0.3) -> list[tuple[str, float]]:
    return [(word, round(start + i * step, 3)) for i, word in enumerate(text.split())]


def simple_vtt(cues: list[tuple[float, float, str]]) -> str:
    blocks = ["WEBVTT", ""]
    for start, end, text in cues:
        blocks += [f"{vtt_time(start)} --> {vtt_time(end)}", text, ""]
    return "\n".join(blocks)


def caption_formats(url: str = "https://example.test/captions", exts: tuple[str, ...] = ("json3", "srv1", "vtt")):
    return [{"ext": ext, "url": f"{url}?fmt={ext}", "name": "English"} for ext in exts]


def video_info(
    video_id: str = "abcdefghijk",
    title: str = "How I Built My SaaS",
    *,
    subtitles: dict[str, Any] | None = None,
    automatic_captions: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    info = {
        "id": video_id,
        "title": title,
        "channel": "Example Channel",
        "uploader": "Example Uploader",
        "upload_date": "20260920",
        "duration": 5025,
        "language": "en",
        "subtitles": subtitles if subtitles is not None else {"en": caption_formats(f"https://example.test/{video_id}")},
        "automatic_captions": automatic_captions or {},
    }
    info.update(extra)
    return info


SAMPLE_VTT = simple_vtt(
    [
        (0.0, 3.0, "Welcome back. Today we're going to talk about caption files."),
        (3.0, 6.0, "They are simple, but they hide a few surprises."),
        (60.0, 63.0, "The first problem we found was duplication."),
        (63.0, 66.0, "We fixed it by comparing neighbouring cues."),
    ]
)


class FakeClient:
    """Stands in for :class:`yt_transcript.youtube.YouTubeClient` without network access."""

    def __init__(self) -> None:
        self.videos: dict[str, dict[str, Any] | Exception] = {}
        self.captions: dict[str, str | Exception] = {}
        self.playlists: dict[str, Playlist | Exception] = {}
        self.fetched: list[str] = []

    def add_video(self, video_id: str, title: str = "Video", captions: str = SAMPLE_VTT, **info: Any) -> None:
        self.videos[video_id] = video_info(video_id, title, **info)
        self.captions[f"https://example.test/{video_id}?fmt=vtt"] = captions

    def add_playlist(self, playlist_id: str, title: str, video_ids: list[str | None]) -> None:
        entries = [
            PlaylistEntry(vid, self._title(vid), f"https://www.youtube.com/watch?v={vid}" if vid else None)
            for vid in video_ids
        ]
        self.playlists[playlist_id] = Playlist(
            playlist_id, title, f"https://www.youtube.com/playlist?list={playlist_id}", entries
        )

    def _title(self, video_id: str | None) -> str | None:
        info = self.videos.get(video_id) if video_id else None
        return info.get("title") if isinstance(info, dict) else None

    def fetch_video(self, url: str) -> dict[str, Any]:
        video_id = url.rsplit("=", 1)[-1]
        self.fetched.append(video_id)
        value = self.videos.get(video_id, YouTubeError("Video unavailable"))
        if isinstance(value, Exception):
            raise value
        return value

    def fetch_playlist(self, url: str) -> Playlist:
        value = self.playlists.get(url.rsplit("=", 1)[-1], YouTubeError("The playlist does not exist"))
        if isinstance(value, Exception):
            raise value
        return value

    def download_captions(self, track: CaptionTrack) -> str:
        value = self.captions.get(track.url, YouTubeError("HTTP Error 404"))
        if isinstance(value, Exception):
            raise value
        return value


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def reset_package_logger():
    """The CLI reconfigures the package logger; undo that so caplog keeps working."""
    logger = logging.getLogger("yt_transcript")
    saved = (logger.handlers[:], logger.level, logger.propagate)
    yield
    logger.handlers[:], logger.level, logger.propagate = saved
