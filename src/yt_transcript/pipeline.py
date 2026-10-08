"""Turn command-line inputs into transcript files, indexes and combined documents."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from yt_transcript.captions import transcript_paragraphs
from yt_transcript.formatter import render_body, render_combined, render_document, render_index
from yt_transcript.models import CaptionTrack, Playlist, VideoMetadata, VideoResult
from yt_transcript.output import (
    COMBINED_FILENAME,
    INDEX_FILENAME,
    find_existing_transcripts,
    playlist_filename,
    read_transcript,
    sanitize_filename,
    unique_path,
    video_filename,
    write_text,
)
from yt_transcript.youtube import (
    YouTubeError,
    YouTubeURL,
    metadata_from_info,
    parse_youtube_url,
    select_caption_track,
)

log = logging.getLogger("yt_transcript")

BATCH_INDEX_TITLE = "Transcript Collection"
BATCH_COMBINED_TITLE = "YouTube Transcripts"

NameFunction = Callable[[VideoMetadata, int], str]  # (metadata, position) -> filename


class Client(Protocol):
    def fetch_video(self, url: str) -> dict[str, Any]: ...
    def fetch_playlist(self, url: str) -> Playlist: ...
    def download_captions(self, track: CaptionTrack) -> str: ...


@dataclass
class Options:
    output_dir: Path
    timestamp_interval: int | None = 45  # None disables timestamps
    combine: bool = False
    overwrite: bool = False


@dataclass
class Collection:
    """A group of videos written into one directory: a playlist or the loose URLs."""

    title: str
    directory: Path
    playlist_url: str | None = None
    results: list[VideoResult] = field(default_factory=list)
    index_path: Path | None = None
    combined_path: Path | None = None
    error: str | None = None


@dataclass
class RunSummary:
    collections: list[Collection] = field(default_factory=list)
    invalid_inputs: list[str] = field(default_factory=list)

    @property
    def results(self) -> list[VideoResult]:
        return [result for collection in self.collections for result in collection.results]

    def count(self, status: str) -> int:
        return sum(result.status == status for result in self.results)

    @property
    def failed(self) -> bool:
        return bool(
            self.invalid_inputs
            or any(collection.error for collection in self.collections)
            or self.count("failed")
        )


@dataclass
class _VideoJob:
    position: int
    total: int
    video_id: str | None
    url: str | None
    title: str | None = None


def run(inputs: Sequence[str], options: Options, client: Client) -> RunSummary:
    """Process every input URL. Failures are recorded per video and never abort the run."""
    summary = RunSummary()
    videos: list[YouTubeURL] = []
    playlists: list[YouTubeURL] = []
    for raw in inputs:
        parsed = parse_youtube_url(raw)
        if parsed is None:
            log.error("Not a YouTube video or playlist URL: %s", raw)
            summary.invalid_inputs.append(raw)
        elif parsed.kind == "playlist":
            if parsed not in playlists:
                playlists.append(parsed)
        elif parsed not in videos:
            videos.append(parsed)

    if videos:
        summary.collections.append(_process_videos(videos, options, client))
    for playlist in playlists:
        summary.collections.append(_process_playlist(playlist, options, client))
    return summary


def _process_videos(videos: list[YouTubeURL], options: Options, client: Client) -> Collection:
    collection = Collection(BATCH_INDEX_TITLE, options.output_dir)
    jobs = [_VideoJob(i, len(videos), v.id, v.url) for i, v in enumerate(videos, start=1)]
    _process_jobs(collection, jobs, lambda meta, _position: video_filename(meta), options, client)
    if len(collection.results) > 1:
        _write_index(collection)
    if options.combine:
        _write_combined(collection, BATCH_COMBINED_TITLE)
    return collection


def _process_playlist(playlist_url: YouTubeURL, options: Options, client: Client) -> Collection:
    log.info("Fetching playlist %s", playlist_url.url)
    try:
        playlist = client.fetch_playlist(playlist_url.url)
    except YouTubeError as exc:
        log.error("Could not load playlist %s: %s", playlist_url.url, exc)
        return Collection(playlist_url.id, options.output_dir, playlist_url.url, error=str(exc))

    directory = options.output_dir / sanitize_filename(playlist.title, fallback=playlist.playlist_id)
    collection = Collection(playlist.title, directory, playlist_url.url)
    total = len(playlist.entries)
    log.info("Playlist: %s (%d video%s)", playlist.title, total, "" if total == 1 else "s")
    jobs = [
        _VideoJob(i, total, entry.video_id, entry.url, entry.title)
        for i, entry in enumerate(playlist.entries, start=1)
    ]

    def name_for(meta: VideoMetadata, position: int) -> str:
        return playlist_filename(position, total, meta.title)

    _process_jobs(collection, jobs, name_for, options, client)
    _write_index(collection)
    if options.combine:
        _write_combined(collection, playlist.title)
    return collection


def _process_jobs(
    collection: Collection,
    jobs: list[_VideoJob],
    name_for: NameFunction,
    options: Options,
    client: Client,
) -> None:
    existing = find_existing_transcripts(collection.directory)
    taken: set[str] = set()
    for job in jobs:
        label = job.title or job.url or "unknown video"
        log.info("[%d/%d] %s", job.position, job.total, label)
        result = _process_video(job, collection.directory, existing, taken, name_for, options, client)
        collection.results.append(result)
        if result.status == "saved":
            log.info("  saved %s", result.path)
        elif result.status == "existing":
            log.info("  exists %s (use --overwrite to replace)", result.path)
        else:
            log.warning("  skipped: %s", result.error)


def _process_video(
    job: _VideoJob,
    directory: Path,
    existing: dict[str, Path],
    taken: set[str],
    name_for: NameFunction,
    options: Options,
    client: Client,
) -> VideoResult:
    result = VideoResult(job.position, job.video_id, job.title, job.url, "failed")
    if not job.video_id or not job.url:
        result.error = "Video is unavailable"
        return result

    previous = existing.get(job.video_id)
    if previous is not None:
        taken.add(previous.name.casefold())
        if not options.overwrite:
            meta, body = read_transcript(previous)
            if meta is not None:
                result.status, result.path, result.metadata, result.body = "existing", previous, meta, body
                result.title = meta.title
                return result

    try:
        info = client.fetch_video(job.url)
        track = select_caption_track(info)
        meta = metadata_from_info(info, track)
        result.title = meta.title
        log.debug("Selected %s captions (%s, %s)", track.transcript_type, track.language, track.ext)
        paragraphs = transcript_paragraphs(client.download_captions(track))
        if not paragraphs:
            raise YouTubeError("The captions contain no text")
    except YouTubeError as exc:
        result.error = str(exc)
        return result
    except Exception as exc:  # keep going: one bad video must not stop a playlist
        log.debug("Unexpected error processing %s", job.url, exc_info=True)
        result.error = f"Unexpected error: {exc}"
        return result

    duration = meta.duration if meta.duration is not None else int(paragraphs[-1].start)
    body = render_body(paragraphs, options.timestamp_interval, long_timestamps=duration >= 3600)
    if previous is not None:
        path = previous
    else:
        path = unique_path(directory, name_for(meta, job.position), taken)
    try:
        write_text(path, render_document(meta, body))
    except OSError as exc:
        result.error = f"Could not write {path}: {exc.strerror or exc}"
        return result
    existing[job.video_id] = path
    result.status, result.path, result.metadata, result.body = "saved", path, meta, body
    return result


def _write_index(collection: Collection) -> None:
    path = collection.directory / INDEX_FILENAME
    try:
        write_text(path, render_index(collection.title, collection.results, collection.playlist_url))
    except OSError as exc:
        log.error("Could not write %s: %s", path, exc.strerror or exc)
        return
    collection.index_path = path
    log.info("Index: %s", path)


def _write_combined(collection: Collection, title: str) -> None:
    if not any(result.ok for result in collection.results):
        return
    path = collection.directory / COMBINED_FILENAME
    try:
        write_text(path, render_combined(title, collection.results))
    except OSError as exc:
        log.error("Could not write %s: %s", path, exc.strerror or exc)
        return
    collection.combined_path = path
    log.info("Combined: %s", path)
