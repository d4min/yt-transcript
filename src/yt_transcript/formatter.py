"""Markdown rendering for transcripts, collection indexes and combined documents."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date

from yt_transcript.captions import timestamp_positions
from yt_transcript.models import Paragraph, VideoMetadata, VideoResult

TRANSCRIPT_HEADING = "## Transcript"
_LINE_BREAK = "  \n"  # Markdown hard line break
_BLOCK_START = re.compile(r"^(?:[#>|]|[-+*](?:\s|$)|\d+[.)](?:\s|$)|=+$|-+$)")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_REGIONAL_LANGUAGE = re.compile(r"^English \((.+)\)$")


# --------------------------------------------------------------------------- values


def format_timestamp(seconds: float, hours: bool = False) -> str:
    """``[MM:SS]`` style clock, or ``HH:MM:SS`` when ``hours`` is true or needed."""
    total = max(0, int(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    if hours or h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_duration(seconds: int | None) -> str | None:
    """Human duration such as ``42:13`` or ``1:23:45``."""
    if seconds is None:
        return None
    h, rest = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_total_duration(seconds: int) -> str:
    """Coarse duration for collections such as ``14h 32m`` or ``8m 5s``."""
    h, rest = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s" if s else f"{m}m"
    return f"{s}s"


def parse_clock(value: str) -> int | None:
    """Parse ``HH:MM:SS`` / ``MM:SS`` back into seconds."""
    try:
        parts = [int(part) for part in value.split(":")]
    except ValueError:
        return None
    if not 1 <= len(parts) <= 3:
        return None
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


def format_long_date(iso: str | None) -> str | None:
    """``2026-09-20`` -> ``20 September 2026``."""
    if not iso:
        return None
    try:
        day = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{day.day} {day:%B %Y}"


def language_label(code: str | None) -> str | None:
    if not code:
        return None
    if code.lower() == "en":
        return "English"
    if code.split("-")[0].lower() == "en":
        return f"English ({code})"
    return code


def language_code(label: str | None) -> str | None:
    if not label:
        return None
    if label == "English":
        return "en"
    match = _REGIONAL_LANGUAGE.match(label)
    return match.group(1) if match else label


def captions_label(meta: VideoMetadata) -> str | None:
    language = language_label(meta.language)
    if not language:
        return None
    if meta.transcript_type == "automatic":
        return f"{language}, auto-generated"
    if meta.transcript_type == "manual":
        return f"{language}, manual"
    return language


def escape_heading(text: str) -> str:
    """Keep a title intact inside an ATX heading (a trailing ``#`` run would be dropped)."""
    text = " ".join(text.split())
    return re.sub(r"(\s)(#+)$", r"\1\\\2", text)


def escape_paragraph(text: str) -> str:
    """Stop a paragraph's first characters being read as Markdown block syntax."""
    return "\\" + text if _BLOCK_START.match(text) else text


# --------------------------------------------------------------------------- transcript


def render_body(
    paragraphs: Sequence[Paragraph],
    timestamp_interval: float | None = 45,
    long_timestamps: bool = False,
) -> str:
    """Render paragraphs, with ``[MM:SS]`` markers roughly every ``timestamp_interval`` s.

    ``timestamp_interval=None`` disables timestamps. ``long_timestamps`` forces the
    ``HH:MM:SS`` form, used for videos of an hour or more.
    """
    stamped = timestamp_positions(paragraphs, timestamp_interval) if timestamp_interval else set()
    blocks: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        if index in stamped:
            blocks.append(f"[{format_timestamp(paragraph.start, long_timestamps)}]")
        blocks.append(escape_paragraph(paragraph.text))
    return "\n\n".join(blocks)


def _yaml_string(value: str) -> str:
    # A JSON string is a valid YAML double-quoted scalar.
    return json.dumps(value, ensure_ascii=False)


def render_frontmatter(meta: VideoMetadata) -> str:
    fields = {
        "title": meta.title,
        "channel": meta.channel,
        "video_id": meta.video_id,
        "url": meta.url,
        "upload_date": meta.upload_date,
        "duration": format_timestamp(meta.duration, hours=True) if meta.duration is not None else None,
        "language": language_label(meta.language),
        "transcript_type": meta.transcript_type,
    }
    lines = [f"{key}: {_yaml_string(value)}" for key, value in fields.items() if value is not None]
    return "---\n" + "\n".join(lines) + "\n---"


def metadata_lines(meta: VideoMetadata) -> str:
    """The human-readable metadata block shown under a video's heading."""
    rows = [
        ("Channel", meta.channel),
        ("Published", format_long_date(meta.upload_date)),
        ("Duration", format_duration(meta.duration)),
        ("Captions", captions_label(meta)),
        ("Source", meta.url),
    ]
    return _LINE_BREAK.join(f"**{label}:** {value}" for label, value in rows if value)


def render_document(meta: VideoMetadata, body: str) -> str:
    """A complete Markdown transcript file for one video."""
    parts = [
        render_frontmatter(meta),
        f"# {escape_heading(meta.title)}",
        metadata_lines(meta),
        TRANSCRIPT_HEADING,
        body,
    ]
    return "\n\n".join(part for part in parts if part) + "\n"


def parse_document(text: str) -> tuple[VideoMetadata | None, str | None]:
    """Read metadata and transcript body back from a file written by :func:`render_document`."""
    text = text.replace("\r\n", "\n")
    match = _FRONTMATTER.match(text)
    if not match:
        return None, None
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, raw = line.partition(":")
        if not sep:
            continue
        raw = raw.strip()
        try:
            value = json.loads(raw) if raw.startswith('"') else raw
        except json.JSONDecodeError:
            value = raw.strip('"')
        if isinstance(value, str):
            fields[key.strip()] = value
    video_id = fields.get("video_id")
    if not video_id:
        return None, None
    meta = VideoMetadata(
        video_id=video_id,
        title=fields.get("title") or video_id,
        url=fields.get("url") or f"https://www.youtube.com/watch?v={video_id}",
        channel=fields.get("channel"),
        upload_date=fields.get("upload_date"),
        duration=parse_clock(fields["duration"]) if "duration" in fields else None,
        language=language_code(fields.get("language")),
        transcript_type=fields.get("transcript_type"),
    )
    body = None
    marker = f"\n{TRANSCRIPT_HEADING}\n"
    position = text.find(marker, match.end() - 1)
    if position != -1:
        body = text[position + len(marker) :].strip()
    return meta, body


# --------------------------------------------------------------------------- collections


def _summary_lines(results: Sequence[VideoResult], extra: Sequence[tuple[str, str]] = ()) -> str:
    durations = [r.metadata.duration for r in results if r.metadata and r.metadata.duration]
    rows = [("Videos", str(len(results)))]
    if durations:
        rows.append(("Total duration", format_total_duration(sum(durations))))
    rows.extend(extra)
    return _LINE_BREAK.join(f"**{label}:** {value}" for label, value in rows)


def render_index(
    title: str,
    results: Sequence[VideoResult],
    playlist_url: str | None = None,
) -> str:
    """``INDEX.md`` for a playlist or batch: what is in the folder, without summaries."""
    available = [r for r in results if r.ok and r.metadata and r.path]
    failed = [r for r in results if not r.ok]
    extra = [("Playlist", playlist_url)] if playlist_url else []
    if failed:
        extra.append(("Unavailable", str(len(failed))))
    parts = [f"# {escape_heading(title)}", _summary_lines(available, extra), "## Videos"]

    items = []
    for number, result in enumerate(available, start=1):
        meta = result.metadata
        assert meta is not None and result.path is not None
        lines = [f"{number}. {' '.join(meta.title.split())}"]
        if meta.channel:
            lines.append(f"   - Channel: {meta.channel}")
        if meta.duration is not None:
            lines.append(f"   - Duration: {format_duration(meta.duration)}")
        if meta.upload_date:
            lines.append(f"   - Published: {meta.upload_date}")
        lines.append(f"   - File: `{result.path.name}`")
        lines.append(f"   - URL: {meta.url}")
        items.append("\n".join(lines))
    parts.append("\n\n".join(items) if items else "_No transcripts were created._")

    if failed:
        parts.append("## Unavailable")
        rows = []
        for result in failed:
            name = " ".join((result.title or result.video_id or "Unknown video").split())
            where = f" ({result.url})" if result.url else ""
            rows.append(f"- {name}{where}: {result.error or 'unknown error'}")
        parts.append("\n".join(rows))
    return "\n\n".join(parts) + "\n"


def render_combined(title: str, results: Sequence[VideoResult]) -> str:
    """One document containing every transcript, with clear per-video boundaries."""
    available = [r for r in results if r.ok and r.metadata and r.body is not None]
    parts = [f"# {escape_heading(title)}", _summary_lines(available)]
    for number, result in enumerate(available, start=1):
        meta = result.metadata
        assert meta is not None
        parts.append("---")
        parts.append(f"## {number}. {escape_heading(meta.title)}")
        parts.append(metadata_lines(meta))
        parts.append("### Transcript")
        parts.append(result.body or "_Empty transcript._")
    return "\n\n".join(part for part in parts if part) + "\n"
