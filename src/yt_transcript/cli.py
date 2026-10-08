"""Command-line interface for yt-transcript."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from yt_transcript import __version__
from yt_transcript.pipeline import Client, Options, RunSummary, run

DEFAULT_OUTPUT = Path("transcripts")
DEFAULT_TIMESTAMP_INTERVAL = 45

EPILOG = """\
examples:
  yt-transcript "https://www.youtube.com/watch?v=VIDEO_ID"
  yt-transcript URL1 URL2 URL3
  yt-transcript "https://www.youtube.com/playlist?list=PLAYLIST_ID" --combine
  yt-transcript URL --output ~/Documents/research --timestamp-interval 60

Transcripts are written as Markdown to ./transcripts/ by default. Playlists get
their own folder with an INDEX.md. Existing transcripts are kept unless
--overwrite is given.
"""


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number of seconds, got {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1 second")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-transcript",
        description="Convert YouTube videos and playlists into clean, timestamped Markdown transcripts.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("urls", nargs="+", metavar="URL", help="YouTube video or playlist URL(s)")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="PATH",
        help="directory to write transcripts to (default: ./transcripts)",
    )
    parser.add_argument(
        "--combine",
        action="store_true",
        help="also write combined-transcripts.md containing every transcript",
    )
    timestamps = parser.add_mutually_exclusive_group()
    timestamps.add_argument(
        "--timestamp-interval",
        type=_positive_int,
        default=DEFAULT_TIMESTAMP_INTERVAL,
        metavar="SECONDS",
        help=f"approximate seconds between timestamps (default: {DEFAULT_TIMESTAMP_INTERVAL})",
    )
    timestamps.add_argument("--no-timestamps", action="store_true", help="omit timestamps from transcripts")
    parser.add_argument("--overwrite", action="store_true", help="replace transcripts that already exist")
    parser.add_argument("-v", "--verbose", action="store_true", help="show detailed processing output")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


class _ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.levelno >= logging.ERROR:
            message = f"error: {message}"
        if record.exc_info and record.levelno <= logging.DEBUG:
            message += "\n" + self.formatException(record.exc_info)
        return message


def configure_logging(verbose: bool) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_ConsoleFormatter())
    logger = logging.getLogger("yt_transcript")
    logger.handlers[:] = [handler]
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False


def _print_summary(summary: RunSummary) -> None:
    parts = [f"{summary.count('saved')} saved"]
    if summary.count("existing"):
        parts.append(f"{summary.count('existing')} already existed")
    if summary.count("failed"):
        parts.append(f"{summary.count('failed')} skipped")
    if summary.invalid_inputs:
        parts.append(f"{len(summary.invalid_inputs)} invalid URL{'s' if len(summary.invalid_inputs) > 1 else ''}")
    logging.getLogger("yt_transcript").info("Done: %s.", ", ".join(parts))


def main(argv: Sequence[str] | None = None, client: Client | None = None) -> int:
    """Entry point. Returns 0 on success, 1 if any input failed, 130 if interrupted."""
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    options = Options(
        output_dir=args.output.expanduser(),
        timestamp_interval=None if args.no_timestamps else args.timestamp_interval,
        combine=args.combine,
        overwrite=args.overwrite,
    )
    if client is None:
        from yt_transcript.youtube import YouTubeClient

        client = YouTubeClient()
    try:
        summary = run(args.urls, options, client)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    _print_summary(summary)
    return 1 if summary.failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
