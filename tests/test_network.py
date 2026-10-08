"""Live tests against YouTube. Deselected by default; run with ``pytest -m network``.

They depend on YouTube, yt-dlp and network conditions, so they are kept out of the
normal test run. Failures here usually mean yt-dlp needs updating.
"""

from __future__ import annotations

import pytest

from yt_transcript.cli import main
from yt_transcript.formatter import parse_document
from yt_transcript.youtube import YouTubeClient, select_caption_track

pytestmark = pytest.mark.network

# "Me at the zoo": the first video uploaded to YouTube, with manual English captions.
ZOO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def test_fetch_and_select_real_captions():
    client = YouTubeClient()
    info = client.fetch_video(ZOO)
    track = select_caption_track(info)
    assert track.language.startswith("en")
    text = client.download_captions(track)
    assert text.lstrip("\ufeff").startswith("WEBVTT")


def test_cli_end_to_end(tmp_path):
    assert main([ZOO, "--output", str(tmp_path)]) == 0
    [path] = tmp_path.glob("*.md")
    meta, body = parse_document(path.read_text(encoding="utf-8"))
    assert meta.video_id == "jNQXAC9IVRw"
    assert meta.title == "Me at the zoo"
    assert "elephants" in body
