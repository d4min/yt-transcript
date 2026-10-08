from __future__ import annotations

import logging

import pytest

from tests.conftest import FakeClient, caption_formats, simple_vtt
from yt_transcript.output import write_text
from yt_transcript.pipeline import Options, run
from yt_transcript.youtube import YouTubeError

A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


def url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


@pytest.fixture
def options(tmp_path) -> Options:
    return Options(output_dir=tmp_path / "transcripts")


def test_single_video(client: FakeClient, options):
    client.add_video(A, "How I Built My SaaS", duration=66)
    summary = run([url(A)], options, client)
    [result] = summary.results
    assert result.status == "saved"
    assert result.path == options.output_dir / f"How I Built My SaaS [{A}].md"
    text = result.path.read_text(encoding="utf-8")
    assert text.startswith('---\ntitle: "How I Built My SaaS"')
    assert "## Transcript\n\n[00:00]\n\nWelcome back." in text
    assert "surprises.\n\n[01:00]\n\nThe first problem" in text
    assert not (options.output_dir / "INDEX.md").exists()
    assert not summary.failed


def test_batch_writes_index_and_skips_duplicates(client, options):
    client.add_video(A, "First")
    client.add_video(B, "Second")
    summary = run([url(A), f"https://youtu.be/{B}", A], options, client)
    assert [r.status for r in summary.results] == ["saved", "saved"]
    assert client.fetched == [A, B]
    index = (options.output_dir / "INDEX.md").read_text(encoding="utf-8")
    assert index.startswith("# Transcript Collection\n\n**Videos:** 2")
    assert f"`First [{A}].md`" in index and f"`Second [{B}].md`" in index


def test_playlist_directory_numbering_and_index(client, options):
    for vid, title in [(A, "Intro"), (B, "Deep: Dive?"), (C, "Wrap up")]:
        client.add_video(vid, title)
    client.add_playlist("PL1", "My Course / 2026", [A, B, C])
    summary = run([playlist_url("PL1")], options, client)
    directory = options.output_dir / "My Course 2026"
    assert sorted(p.name for p in directory.iterdir()) == [
        "001 - Intro.md",
        "002 - Deep Dive.md",
        "003 - Wrap up.md",
        "INDEX.md",
    ]
    index = (directory / "INDEX.md").read_text(encoding="utf-8")
    assert index.startswith("# My Course / 2026\n\n**Videos:** 3")
    assert "**Playlist:** https://www.youtube.com/playlist?list=PL1" in index
    assert summary.collections[0].index_path == directory / "INDEX.md"


def test_playlist_continues_after_failures(client, options, caplog):
    client.add_video(A, "Good one")
    client.add_video(B, "No English", subtitles={"fr": caption_formats()}, automatic_captions={})
    client.add_video(C, "Another good one")
    client.videos["ddddddddddd"] = YouTubeError("Private video. Sign in if you've been granted access")
    client.add_playlist("PL1", "Mixed", [A, B, None, "ddddddddddd", C])
    with caplog.at_level(logging.INFO, logger="yt_transcript"):
        summary = run([playlist_url("PL1")], options, client)
    assert [r.status for r in summary.results] == ["saved", "failed", "failed", "failed", "saved"]
    assert summary.results[1].error.startswith("No English captions are available")
    assert summary.results[2].error == "Video is unavailable"
    assert summary.results[3].error.startswith("Private video")
    # Playlist numbering follows playlist positions even when entries fail.
    assert summary.results[4].path.name == "005 - Another good one.md"
    index = (options.output_dir / "Mixed" / "INDEX.md").read_text(encoding="utf-8")
    assert "**Videos:** 2" in index and "## Unavailable" in index and "Private video" in index
    assert summary.failed
    assert any("skipped: No English captions" in r.getMessage() for r in caplog.records)


def test_caption_download_failure_and_empty_captions(client, options):
    client.add_video(A, "Download fails")
    client.captions[f"https://example.test/{A}?fmt=vtt"] = YouTubeError("Could not download captions: HTTP Error 429")
    client.add_video(B, "Empty captions", captions="WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n \n")
    summary = run([url(A), url(B)], options, client)
    assert [r.error for r in summary.results] == [
        "Could not download captions: HTTP Error 429",
        "The captions contain no text",
    ]


def test_unexpected_errors_do_not_stop_the_run(client, options):
    client.videos[A] = RuntimeError("boom")
    client.add_video(B, "Fine")
    summary = run([url(A), url(B)], options, client)
    assert summary.results[0].error == "Unexpected error: boom"
    assert summary.results[1].status == "saved"


def test_invalid_inputs_are_reported(client, options, caplog):
    client.add_video(A, "Fine")
    summary = run(["https://vimeo.com/1", url(A)], options, client)
    assert summary.invalid_inputs == ["https://vimeo.com/1"]
    assert summary.failed
    assert summary.results[0].status == "saved"
    assert "Not a YouTube video or playlist URL: https://vimeo.com/1" in caplog.text


def test_playlist_that_cannot_be_loaded(client, options):
    summary = run([playlist_url("PLmissing")], options, client)
    assert summary.collections[0].error == "The playlist does not exist"
    assert summary.failed
    assert not options.output_dir.exists()


def test_existing_files_are_kept_and_reused(client, options):
    client.add_video(A, "First")
    client.add_video(B, "Second")
    run([url(A)], options, client)
    path = options.output_dir / f"First [{A}].md"
    path.write_text(path.read_text(encoding="utf-8").replace("Welcome back.", "Edited by hand."))
    client.fetched.clear()

    summary = run([url(A), url(B)], Options(options.output_dir, combine=True), client)
    assert [r.status for r in summary.results] == ["existing", "saved"]
    assert client.fetched == [B]  # the existing video was not fetched again
    assert "Edited by hand." in path.read_text(encoding="utf-8")
    combined = (options.output_dir / "combined-transcripts.md").read_text(encoding="utf-8")
    assert "Edited by hand." in combined and "## 2. Second" in combined
    assert "`First [" in (options.output_dir / "INDEX.md").read_text(encoding="utf-8")


def test_existing_file_found_by_video_id_even_if_renamed(client, options):
    client.add_video(A, "Original title")
    run([url(A)], options, client)
    old = options.output_dir / f"Original title [{A}].md"
    renamed = options.output_dir / "my notes on this talk.md"
    old.rename(renamed)
    summary = run([url(A)], options, client)
    assert summary.results[0].status == "existing"
    assert summary.results[0].path == renamed


def test_overwrite_replaces_in_place(client, options):
    client.add_video(A, "First")
    run([url(A)], options, client)
    path = options.output_dir / f"First [{A}].md"
    path.write_text(path.read_text(encoding="utf-8").replace("Welcome back.", "Edited by hand."))
    client.videos[A]["title"] = "Renamed upstream"

    summary = run([url(A)], Options(options.output_dir, overwrite=True), client)
    assert summary.results[0].status == "saved"
    assert summary.results[0].path == path  # same file, refreshed content
    assert "Edited by hand." not in path.read_text(encoding="utf-8")
    assert 'title: "Renamed upstream"' in path.read_text(encoding="utf-8")
    assert len(list(options.output_dir.iterdir())) == 1


def test_unrelated_file_with_same_name_is_not_overwritten(client, options):
    client.add_video(A, "Clash")
    write_text(options.output_dir / f"Clash [{A}].md", "my own notes\n")
    summary = run([url(A)], options, client)
    assert summary.results[0].path.name == f"Clash [{A}] (2).md"
    assert (options.output_dir / f"Clash [{A}].md").read_text(encoding="utf-8") == "my own notes\n"


def test_duplicate_titles_in_batch_get_distinct_files(client, options):
    client.add_video(A, "Same")
    client.add_video(B, "Same")
    summary = run([url(A), url(B)], options, client)
    assert sorted(r.path.name for r in summary.results) == [f"Same [{A}].md", f"Same [{B}].md"]


def test_playlist_with_repeated_video(client, options):
    client.add_video(A, "Repeated")
    client.add_playlist("PL1", "Loop", [A, A])
    summary = run([playlist_url("PL1")], options, client)
    assert [r.status for r in summary.results] == ["saved", "existing"]
    assert client.fetched == [A]


def test_combine_for_playlist(client, options):
    client.add_video(A, "One")
    client.add_video(B, "Two")
    client.add_playlist("PL1", "Series", [A, B])
    run([playlist_url("PL1")], Options(options.output_dir, combine=True), client)
    combined = (options.output_dir / "Series" / "combined-transcripts.md").read_text(encoding="utf-8")
    assert combined.startswith("# Series\n\n**Videos:** 2")
    assert combined.index("## 1. One") < combined.index("## 2. Two")
    assert combined.count("### Transcript") == 2


def test_combine_skipped_when_nothing_succeeded(client, options):
    run([url(A)], Options(options.output_dir, combine=True), client)
    assert not (options.output_dir / "combined-transcripts.md").exists()


def test_mixed_videos_and_playlists(client, options):
    client.add_video(A, "Loose")
    client.add_video(B, "In list")
    client.add_playlist("PL1", "List", [B])
    summary = run([playlist_url("PL1"), url(A)], options, client)
    assert [c.title for c in summary.collections] == ["Transcript Collection", "List"]
    assert (options.output_dir / f"Loose [{A}].md").exists()
    assert (options.output_dir / "List" / "001 - In list.md").exists()


def test_timestamp_options(client, options):
    long_captions = simple_vtt([(t, t + 5.0, f"Sentence number {t}. " * 12) for t in range(0, 600, 20)])
    client.add_video(A, "Timed", captions=long_captions, duration=600)
    run([url(A)], Options(options.output_dir, timestamp_interval=120), client)
    text = next(options.output_dir.glob("*.md")).read_text(encoding="utf-8")
    stamps = [line for line in text.splitlines() if line.startswith("[") and line.endswith("]")]
    assert stamps[0] == "[00:00]" and 4 <= len(stamps) <= 6

    run([url(A)], Options(options.output_dir, timestamp_interval=None, overwrite=True), client)
    text = next(options.output_dir.glob("*.md")).read_text(encoding="utf-8")
    assert "[00:00]" not in text


def test_long_videos_use_hour_timestamps(client, options):
    client.add_video(A, "Long", duration=4000)
    run([url(A)], options, client)
    text = next(options.output_dir.glob("*.md")).read_text(encoding="utf-8")
    assert "[00:00:00]" in text and "[00:01:00]" in text
    assert 'duration: "01:06:40"' in text


def test_write_failure_is_reported(client, options, monkeypatch):
    client.add_video(A, "Unwritable")

    def fail(path, content):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("yt_transcript.pipeline.write_text", fail)
    summary = run([url(A)], options, client)
    assert summary.results[0].status == "failed"
    assert "Permission denied" in summary.results[0].error
