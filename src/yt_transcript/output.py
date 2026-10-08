"""Safe filenames and transcript files on disk."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import unicodedata
from pathlib import Path

from yt_transcript.formatter import parse_document
from yt_transcript.models import VideoMetadata

log = logging.getLogger(__name__)

INDEX_FILENAME = "INDEX.md"
COMBINED_FILENAME = "combined-transcripts.md"
RESERVED_FILENAMES = {INDEX_FILENAME.casefold(), COMBINED_FILENAME.casefold()}

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com\d|lpt\d)(?:\..*)?$", re.IGNORECASE)
MAX_NAME_BYTES = 150  # leaves room for prefixes, suffixes and ".md" within 255 bytes


def sanitize_filename(name: str, max_bytes: int = MAX_NAME_BYTES, fallback: str = "Untitled") -> str:
    """Make ``name`` safe as a file or directory name on macOS, Linux and Windows."""
    name = unicodedata.normalize("NFC", name)
    name = _UNSAFE.sub(" ", name)
    name = " ".join(name.split())
    name = name.strip(" .")
    encoded = name.encode("utf-8")
    if len(encoded) > max_bytes:
        name = encoded[:max_bytes].decode("utf-8", errors="ignore").rstrip(" .")
    if not name:
        name = fallback
    if _WINDOWS_RESERVED.match(name):
        name = f"_{name}"
    return name


def video_filename(meta: VideoMetadata) -> str:
    """``Video Title [VIDEO_ID].md`` for standalone videos."""
    return f"{sanitize_filename(meta.title)} [{meta.video_id}].md"


def playlist_filename(position: int, total: int, title: str) -> str:
    """``001 - Video Title.md`` for playlist entries (wider numbers for 1000+ videos)."""
    width = max(3, len(str(total)))
    return f"{position:0{width}d} - {sanitize_filename(title)}.md"


def unique_path(directory: Path, filename: str, taken: set[str]) -> Path:
    """Return a path in ``directory`` that is not already in ``taken`` and does not exist.

    ``taken`` holds case-folded names already claimed in this run; the chosen name is
    added to it. Case-folding avoids collisions on case-insensitive filesystems.
    """
    stem, suffix = os.path.splitext(filename)
    candidate, counter = filename, 2
    while (
        candidate.casefold() in taken
        or candidate.casefold() in RESERVED_FILENAMES
        or (directory / candidate).exists()
    ):
        candidate = f"{stem} ({counter}){suffix}"
        counter += 1
    taken.add(candidate.casefold())
    return directory / candidate


def find_existing_transcripts(directory: Path) -> dict[str, Path]:
    """Map video IDs to transcript files previously written into ``directory``."""
    found: dict[str, Path] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.md")):
        if path.name.casefold() in RESERVED_FILENAMES:
            continue
        try:
            with path.open(encoding="utf-8") as handle:
                head = handle.read(4096)
        except (OSError, UnicodeDecodeError):
            continue
        meta, _ = parse_document(head)
        if meta and meta.video_id not in found:
            found[meta.video_id] = path
    return found


def read_transcript(path: Path) -> tuple[VideoMetadata | None, str | None]:
    try:
        return parse_document(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        log.debug("Could not read %s: %s", path, exc)
        return None, None


def write_text(path: Path, content: str) -> None:
    """Write a file atomically so an interrupted run never leaves half a transcript."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.chmod(temp_name, 0o666 & ~_umask())  # mkstemp creates files as 0600
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask
