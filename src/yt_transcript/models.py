"""Plain data structures shared across the package."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Cue:
    """A single subtitle event as it appears in the caption file."""

    start: float
    end: float
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Word:
    """A whitespace-delimited token of transcript text with its timing in seconds."""

    text: str
    start: float
    end: float
    cue_end: bool = False  # last word emitted from its cue


@dataclass(frozen=True)
class Paragraph:
    """A reconstructed paragraph of transcript text."""

    start: float
    text: str


@dataclass(frozen=True)
class CaptionTrack:
    """A caption track chosen for download."""

    language: str
    automatic: bool
    url: str
    ext: str
    name: str | None = None

    @property
    def transcript_type(self) -> str:
        return "automatic" if self.automatic else "manual"


@dataclass
class VideoMetadata:
    """Metadata describing a video and the caption track used for its transcript."""

    video_id: str
    title: str
    url: str
    channel: str | None = None
    upload_date: str | None = None  # ISO 8601, YYYY-MM-DD
    duration: int | None = None  # seconds
    language: str | None = None  # caption language code, e.g. "en-GB"
    transcript_type: str | None = None  # "manual" or "automatic"


@dataclass
class PlaylistEntry:
    video_id: str | None
    title: str | None
    url: str | None


@dataclass
class Playlist:
    playlist_id: str
    title: str
    url: str
    entries: list[PlaylistEntry] = field(default_factory=list)
    channel: str | None = None


@dataclass
class VideoResult:
    """The outcome of processing one video."""

    position: int
    video_id: str | None
    title: str | None
    url: str | None
    status: str  # "saved", "existing" or "failed"
    path: Path | None = None
    metadata: VideoMetadata | None = None
    body: str | None = None  # rendered transcript section (timestamps + paragraphs)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status != "failed"
