from __future__ import annotations

import os
import stat

import pytest

from yt_transcript.formatter import render_document
from yt_transcript.models import VideoMetadata
from yt_transcript.output import (
    find_existing_transcripts,
    playlist_filename,
    read_transcript,
    sanitize_filename,
    unique_path,
    video_filename,
    write_text,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("How I Built My SaaS", "How I Built My SaaS"),
        ('What/is\\this: a "test"?', "What is this a test"),
        ("pipes | stars * <angles>", "pipes stars angles"),
        ("tabs\tand\nnewlines", "tabs and newlines"),
        ("  ...leading dots and spaces...  ", "leading dots and spaces"),
        ("", "Untitled"),
        ("???", "Untitled"),
        ("CON", "_CON"),
        ("nul.txt", "_nul.txt"),
        ("Console wars", "Console wars"),
        ("Émojis 🎉 and 日本語", "Émojis 🎉 and 日本語"),
        ("cafe\u0301", "café"),
    ],
)
def test_sanitize_filename(name, expected):
    assert sanitize_filename(name) == expected


def test_sanitize_filename_truncates_by_bytes_without_splitting_characters():
    name = "日本語" * 100  # 3 bytes per character
    safe = sanitize_filename(name, max_bytes=50)
    assert len(safe.encode("utf-8")) <= 50
    assert safe == "日本語" * 5 + "日"


def test_sanitize_filename_custom_fallback():
    assert sanitize_filename("///", fallback="PL123") == "PL123"


def meta(title="My Video", video_id="abcdefghijk") -> VideoMetadata:
    return VideoMetadata(video_id, title, f"https://www.youtube.com/watch?v={video_id}")


def test_video_filename():
    assert video_filename(meta("How I Built: My SaaS?")) == "How I Built My SaaS [abcdefghijk].md"


@pytest.mark.parametrize(
    ("position", "total", "expected"),
    [(1, 25, "001 - Title.md"), (42, 999, "042 - Title.md"), (7, 1200, "0007 - Title.md"), (1000, 1000, "1000 - Title.md")],
)
def test_playlist_filename(position, total, expected):
    assert playlist_filename(position, total, "Title") == expected


def test_unique_path_handles_collisions(tmp_path):
    taken: set[str] = set()
    first = unique_path(tmp_path, "Video.md", taken)
    second = unique_path(tmp_path, "video.md", taken)  # case-insensitive filesystems
    (tmp_path / "Other.md").write_text("x")
    third = unique_path(tmp_path, "Other.md", taken)
    assert [first.name, second.name, third.name] == ["Video.md", "video (2).md", "Other (2).md"]


def test_unique_path_avoids_reserved_names(tmp_path):
    assert unique_path(tmp_path, "INDEX.md", set()).name == "INDEX (2).md"
    assert unique_path(tmp_path, "combined-transcripts.md", set()).name == "combined-transcripts (2).md"


def test_write_text_creates_directories_and_is_atomic(tmp_path):
    target = tmp_path / "a" / "b" / "file.md"
    write_text(target, "héllo\n")
    assert target.read_text(encoding="utf-8") == "héllo\n"
    write_text(target, "replaced\n")
    assert target.read_text(encoding="utf-8") == "replaced\n"
    assert [p.name for p in target.parent.iterdir()] == ["file.md"]  # no temp files left


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_write_text_uses_normal_permissions(tmp_path):
    target = tmp_path / "file.md"
    write_text(target, "x")
    umask = os.umask(0)
    os.umask(umask)
    # mkstemp would leave 0600; the file should get the same mode as any new file.
    assert stat.S_IMODE(target.stat().st_mode) == 0o666 & ~umask


def test_write_text_cleans_up_on_failure(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_text(tmp_path / "file.md", "x")
    assert list(tmp_path.iterdir()) == []


def test_find_existing_transcripts(tmp_path):
    write_text(tmp_path / "001 - One.md", render_document(meta("One", "aaaaaaaaaaa"), "Text."))
    write_text(tmp_path / "Two [bbbbbbbbbbb].md", render_document(meta("Two", "bbbbbbbbbbb"), "Text."))
    write_text(tmp_path / "copy.md", render_document(meta("One again", "aaaaaaaaaaa"), "Text."))
    write_text(tmp_path / "notes.md", "# My own notes\n")
    write_text(tmp_path / "INDEX.md", render_document(meta("Index", "ccccccccccc"), "x"))
    (tmp_path / "binary.md").write_bytes(b"\xff\xfe\x00")
    (tmp_path / "folder.md").mkdir()
    found = find_existing_transcripts(tmp_path)
    assert {k: v.name for k, v in found.items()} == {"aaaaaaaaaaa": "001 - One.md", "bbbbbbbbbbb": "Two [bbbbbbbbbbb].md"}


def test_find_existing_transcripts_missing_directory(tmp_path):
    assert find_existing_transcripts(tmp_path / "nope") == {}


def test_read_transcript(tmp_path):
    path = tmp_path / "x.md"
    write_text(path, render_document(meta(), "[00:00]\n\nHello."))
    loaded, body = read_transcript(path)
    assert loaded.video_id == "abcdefghijk" and body == "[00:00]\n\nHello."
    assert read_transcript(tmp_path / "missing.md") == (None, None)
