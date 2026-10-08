from __future__ import annotations

from pathlib import Path

import pytest

from yt_transcript.formatter import (
    captions_label,
    escape_heading,
    escape_paragraph,
    format_duration,
    format_long_date,
    format_timestamp,
    format_total_duration,
    language_code,
    language_label,
    metadata_lines,
    parse_clock,
    parse_document,
    render_body,
    render_combined,
    render_document,
    render_frontmatter,
    render_index,
)
from yt_transcript.models import Paragraph, VideoMetadata, VideoResult


@pytest.fixture
def meta() -> VideoMetadata:
    return VideoMetadata(
        video_id="abc123defgh",
        title="How I Built My SaaS",
        url="https://www.youtube.com/watch?v=abc123defgh",
        channel="Example Channel",
        upload_date="2026-09-20",
        duration=5025,
        language="en",
        transcript_type="manual",
    )


# --------------------------------------------------------------------------- values


@pytest.mark.parametrize(
    ("seconds", "hours", "expected"),
    [
        (0, False, "00:00"),
        (47.9, False, "00:47"),
        (95, False, "01:35"),
        (3599, False, "59:59"),
        (3600, False, "01:00:00"),
        (4363, False, "01:12:43"),
        (47, True, "00:00:47"),
        (-5, False, "00:00"),
        (36000 * 3, False, "30:00:00"),
    ],
)
def test_format_timestamp(seconds, hours, expected):
    assert format_timestamp(seconds, hours) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(None, None), (0, "0:00"), (19, "0:19"), (2533, "42:13"), (5025, "1:23:45"), (36000, "10:00:00")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0s"), (45, "45s"), (60, "1m"), (485, "8m 5s"), (3600, "1h 0m"), (52320, "14h 32m")],
)
def test_format_total_duration(seconds, expected):
    assert format_total_duration(seconds) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("01:23:45", 5025), ("42:13", 2533), ("19", 19), ("00:00:00", 0), ("bad", None), ("1:2:3:4", None), ("", None)],
)
def test_parse_clock(value, expected):
    assert parse_clock(value) == expected


@pytest.mark.parametrize(
    ("iso", "expected"),
    [("2026-09-20", "20 September 2026"), ("2005-04-04", "4 April 2005"), (None, None), ("not-a-date", "not-a-date")],
)
def test_format_long_date(iso, expected):
    assert format_long_date(iso) == expected


@pytest.mark.parametrize(
    ("code", "label"),
    [("en", "English"), ("EN", "English"), ("en-GB", "English (en-GB)"), ("fr", "fr"), (None, None)],
)
def test_language_label(code, label):
    assert language_label(code) == label


@pytest.mark.parametrize("code", ["en", "en-GB", "en-US", "en-uYU-mmqFLq8"])
def test_language_label_roundtrip(code):
    assert language_code(language_label(code)) == code


def test_captions_label(meta):
    assert captions_label(meta) == "English, manual"
    meta.transcript_type, meta.language = "automatic", "en-US"
    assert captions_label(meta) == "English (en-US), auto-generated"
    meta.language = None
    assert captions_label(meta) is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Plain title", "Plain title"),
        ("Learn C#", "Learn C#"),
        ("Episode #", "Episode \\#"),
        ("Tags ##", "Tags \\##"),
        ("  extra   spaces\n", "extra spaces"),
    ],
)
def test_escape_heading(title, expected):
    assert escape_heading(title) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain text", "plain text"),
        (">> new speaker here", "\\>> new speaker here"),
        ("# not a heading", "\\# not a heading"),
        ("- not a list", "\\- not a list"),
        ("* not a list", "\\* not a list"),
        ("+ not a list", "\\+ not a list"),
        ("1. not a list", "\\1. not a list"),
        ("2) not a list", "\\2) not a list"),
        ("-5 degrees is cold", "-5 degrees is cold"),
        ("1.5 million people", "1.5 million people"),
        ("| not a table", "\\| not a table"),
        ("[Music] intro", "[Music] intro"),
    ],
)
def test_escape_paragraph(text, expected):
    assert escape_paragraph(text) == expected


# --------------------------------------------------------------------------- body


def test_render_body_with_timestamps():
    paragraphs = [Paragraph(0, "First."), Paragraph(20, "Second."), Paragraph(47, "Third."), Paragraph(95, "Fourth.")]
    assert render_body(paragraphs, 45) == "[00:00]\n\nFirst.\n\nSecond.\n\n[00:47]\n\nThird.\n\n[01:35]\n\nFourth."


def test_render_body_without_timestamps():
    paragraphs = [Paragraph(0, "First."), Paragraph(60, "Second.")]
    assert render_body(paragraphs, None) == "First.\n\nSecond."


def test_render_body_long_video_uses_hours():
    paragraphs = [Paragraph(0, "Start."), Paragraph(4363, "Later.")]
    assert render_body(paragraphs, 45, long_timestamps=True) == "[00:00:00]\n\nStart.\n\n[01:12:43]\n\nLater."


def test_render_body_escapes_paragraph_starts():
    assert render_body([Paragraph(0, ">> Speaker two")], None) == "\\>> Speaker two"


def test_render_body_custom_interval():
    paragraphs = [Paragraph(t, f"p{t}.") for t in range(0, 100, 10)]
    body = render_body(paragraphs, 30)
    assert [line for line in body.split("\n\n") if line.startswith("[")] == ["[00:00]", "[00:30]", "[01:00]", "[01:30]"]


# --------------------------------------------------------------------------- document


def test_render_frontmatter(meta):
    assert render_frontmatter(meta) == (
        "---\n"
        'title: "How I Built My SaaS"\n'
        'channel: "Example Channel"\n'
        'video_id: "abc123defgh"\n'
        'url: "https://www.youtube.com/watch?v=abc123defgh"\n'
        'upload_date: "2026-09-20"\n'
        'duration: "01:23:45"\n'
        'language: "English"\n'
        'transcript_type: "manual"\n'
        "---"
    )


def test_frontmatter_escapes_and_omits(meta):
    meta.title = 'She said "hi": a \\ story — 日本'
    meta.channel = None
    meta.upload_date = None
    front = render_frontmatter(meta)
    assert 'title: "She said \\"hi\\": a \\\\ story — 日本"' in front
    assert "channel" not in front and "upload_date" not in front


def test_frontmatter_is_valid_yaml(meta):
    yaml = pytest.importorskip("yaml")
    meta.title = 'Tricky: "quotes", #hash, [brackets] & {braces}'
    data = yaml.safe_load(render_frontmatter(meta).strip("-\n"))
    assert data["title"] == meta.title
    assert data["duration"] == "01:23:45"


def test_metadata_lines(meta):
    assert metadata_lines(meta) == (
        "**Channel:** Example Channel  \n"
        "**Published:** 20 September 2026  \n"
        "**Duration:** 1:23:45  \n"
        "**Captions:** English, manual  \n"
        "**Source:** https://www.youtube.com/watch?v=abc123defgh"
    )


def test_render_document_layout(meta):
    doc = render_document(meta, "[00:00]\n\nWelcome back.")
    assert doc.startswith("---\ntitle: ")
    assert "\n---\n\n# How I Built My SaaS\n\n**Channel:** Example Channel  \n" in doc
    assert doc.endswith("\n\n## Transcript\n\n[00:00]\n\nWelcome back.\n")


def test_render_document_minimal_metadata():
    meta = VideoMetadata("abcdefghijk", "T", "https://www.youtube.com/watch?v=abcdefghijk")
    doc = render_document(meta, "Text.")
    assert "**Source:** https://www.youtube.com/watch?v=abcdefghijk\n\n## Transcript" in doc
    assert "Channel" not in doc and "duration" not in doc


def test_parse_document_roundtrip(meta):
    meta.title = 'Quotes "and" colons: ok'
    meta.language = "en-GB"
    body = "[00:00]\n\nWelcome back.\n\n## Not a real heading inside text"
    parsed, parsed_body = parse_document(render_document(meta, body))
    assert parsed == meta
    assert parsed_body == body


@pytest.mark.parametrize(
    "text",
    ["", "no frontmatter", "---\ntitle: \"x\"\n---\n\n# x\n", "---\nunclosed: \"x\"\n"],
)
def test_parse_document_rejects_foreign_files(text):
    assert parse_document(text) == (None, None)


def test_parse_document_tolerates_hand_edits():
    text = '---\r\ntitle: Unquoted\r\nvideo_id: "abcdefghijk"\r\nduration: "bogus"\r\nnoise\r\n---\r\n\r\n# T\r\n'
    meta, body = parse_document(text)
    assert meta.title == "Unquoted" and meta.duration is None
    assert body is None


# --------------------------------------------------------------------------- collections


def result(position, meta=None, status="saved", body="Body.", error=None, name=None):
    path = Path(name or f"{position:03d} - {meta.title if meta else 'x'}.md")
    return VideoResult(
        position,
        meta.video_id if meta else None,
        meta.title if meta else None,
        meta.url if meta else None,
        status,
        path=path if status != "failed" else None,
        metadata=meta,
        body=body,
        error=error,
    )


def make_meta(n: int, duration: int | None = 600) -> VideoMetadata:
    vid = f"video{n:06d}"
    return VideoMetadata(vid, f"Video {n}", f"https://www.youtube.com/watch?v={vid}", "Chan", "2026-01-0" + str(n), duration, "en", "automatic")


def test_render_index():
    results = [
        result(1, make_meta(1, 2533)),
        result(2, make_meta(2, 3600), status="existing"),
        VideoResult(3, "deadbeef123", "[Private video]", "https://www.youtube.com/watch?v=deadbeef123", "failed", error="Private video"),
    ]
    index = render_index("Neural networks", results, "https://www.youtube.com/playlist?list=PL1")
    assert index.startswith(
        "# Neural networks\n\n**Videos:** 2  \n**Total duration:** 1h 42m  \n"
        "**Playlist:** https://www.youtube.com/playlist?list=PL1  \n**Unavailable:** 1\n\n## Videos\n\n"
    )
    assert (
        "1. Video 1\n   - Channel: Chan\n   - Duration: 42:13\n   - Published: 2026-01-01\n"
        "   - File: `001 - Video 1.md`\n   - URL: https://www.youtube.com/watch?v=video000001\n\n2. Video 2"
    ) in index
    assert index.endswith(
        "## Unavailable\n\n- [Private video] (https://www.youtube.com/watch?v=deadbeef123): Private video\n"
    )


def test_render_index_batch_without_failures():
    index = render_index("Transcript Collection", [result(1, make_meta(1, None))])
    assert "Playlist" not in index and "Unavailable" not in index and "Total duration" not in index
    assert "Duration:" not in index


def test_render_index_nothing_succeeded():
    failed = VideoResult(1, None, None, None, "failed", error="Video is unavailable")
    index = render_index("Empty", [failed])
    assert "**Videos:** 0" in index
    assert "_No transcripts were created._" in index
    assert "- Unknown video: Video is unavailable" in index


def test_render_combined():
    results = [
        result(1, make_meta(1), body="[00:00]\n\nFirst transcript."),
        VideoResult(2, None, None, None, "failed", error="nope"),
        result(3, make_meta(3), body="Third transcript."),
    ]
    combined = render_combined("YouTube Research Transcripts", results)
    assert combined.startswith("# YouTube Research Transcripts\n\n**Videos:** 2  \n**Total duration:** 20m\n\n---\n\n## 1. Video 1\n\n")
    assert "## 2. Video 3" in combined
    assert "### Transcript\n\n[00:00]\n\nFirst transcript.\n\n---\n\n## 2. Video 3" in combined
    assert combined.endswith("### Transcript\n\nThird transcript.\n")
    assert combined.count("\n---\n") == 2
