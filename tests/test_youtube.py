from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import caption_formats, video_info
from yt_transcript import youtube
from yt_transcript.models import CaptionTrack
from yt_transcript.youtube import (
    NoCaptionsError,
    YouTubeClient,
    YouTubeError,
    YouTubeURL,
    clean_error,
    metadata_from_info,
    parse_youtube_url,
    playlist_from_info,
    select_caption_track,
)

VID = "dQw4w9WgXcQ"

# --------------------------------------------------------------------------- URLs


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"https://youtube.com/watch?v={VID}",
        f"http://m.youtube.com/watch?v={VID}&t=42s",
        f"https://music.youtube.com/watch?v={VID}",
        f"www.youtube.com/watch?feature=share&v={VID}",
        f"youtube.com/watch?v={VID}",
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?si=abc123&t=10",
        f"youtu.be/{VID}",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/live/{VID}?feature=share",
        f"https://www.youtube.com/embed/{VID}",
        f"https://www.youtube-nocookie.com/embed/{VID}",
        f"https://www.youtube.com/v/{VID}",
        f"https://www.youtube.com/watch?v={VID}&list=PLabcdefghijklmnop",
        f"  https://www.youtube.com/watch?v={VID}  ",
        VID,
    ],
)
def test_parse_video_urls(url):
    assert parse_youtube_url(url) == YouTubeURL("video", VID)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi",
        "https://youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi&si=xyz",
        "youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi",
        "https://music.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi",
    ],
)
def test_parse_playlist_urls(url):
    assert parse_youtube_url(url) == YouTubeURL("playlist", "PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "hello",
        "https://vimeo.com/123456",
        "https://www.youtube.com/",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/@channel/videos",
        "https://www.youtube.com/playlist",
        "https://youtu.be/",
        "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
        "http://[invalid",
    ],
)
def test_parse_rejects_other_urls(url):
    assert parse_youtube_url(url) is None


def test_canonical_urls():
    assert YouTubeURL("video", VID).url == f"https://www.youtube.com/watch?v={VID}"
    assert YouTubeURL("playlist", "PL123").url == "https://www.youtube.com/playlist?list=PL123"


# --------------------------------------------------------------------------- track selection


def tracks(*codes: str) -> dict[str, Any]:
    return {code: caption_formats(f"https://example.test/{code}") for code in codes}


def select(subtitles=None, automatic=None, **extra) -> CaptionTrack:
    return select_caption_track(video_info(subtitles=subtitles or {}, automatic_captions=automatic or {}, **extra))


def test_manual_english_preferred_over_everything():
    track = select(tracks("de", "en-GB", "en"), tracks("en-orig", "en"))
    assert (track.language, track.automatic, track.ext) == ("en", False, "vtt")
    assert track.url == "https://example.test/en?fmt=vtt"
    assert track.transcript_type == "manual"


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        (("en-GB",), "en-GB"),
        (("en-GB", "en-US"), "en-US"),
        (("en-CA", "en-GB"), "en-GB"),
        (("en-CA", "en-AU"), "en-AU"),
        (("en-uYU-mmqFLq8", "en-IE"), "en-IE"),
        (("en-uYU-mmqFLq8",), "en-uYU-mmqFLq8"),
    ],
)
def test_manual_regional_english_order(codes, expected):
    assert select(tracks(*codes), tracks("en-orig")).language == expected


def test_manual_regional_beats_automatic():
    track = select(tracks("en-GB"), tracks("en-orig", "en"))
    assert (track.language, track.automatic) == ("en-GB", False)


def test_automatic_original_track_used_when_no_manual():
    track = select(tracks("fr"), tracks("en-orig", "en", "fr", "de"))
    assert (track.language, track.automatic) == ("en", True)
    assert track.url == "https://example.test/en-orig?fmt=vtt"
    assert track.transcript_type == "automatic"


def test_automatic_regional_original():
    track = select({}, tracks("en-US-orig", "en-US", "fr"), language="en-US")
    assert (track.language, track.automatic) == ("en-US", True)


def test_dubbed_videos_with_several_original_tracks():
    track = select({}, tracks("en-orig", "fr-FR-orig", "de-DE-orig", "en", "fr-FR"))
    assert track.language == "en"


def test_machine_translated_english_is_rejected():
    with pytest.raises(NoCaptionsError, match=r"machine-translated.*original language: de"):
        select({}, tracks("de-orig", "de", "en", "fr"), language="de")


def test_auto_english_without_orig_marker_uses_video_language():
    assert select({}, tracks("en"), language="en").automatic is True
    assert select({}, tracks("en"), language=None).language == "en"
    with pytest.raises(NoCaptionsError, match="machine-translated"):
        select({}, tracks("en", "es"), language="es")


def test_translated_manual_subtitles_are_skipped():
    # yt-dlp names manual subtitles translated from German "en-de".
    with pytest.raises(NoCaptionsError):
        select(tracks("de", "en-de"), {}, language="de")


def test_live_chat_is_ignored():
    with pytest.raises(NoCaptionsError, match="No captions"):
        select({"live_chat": [{"ext": "json", "url": "https://example.test/chat"}]})


def test_no_captions_at_all():
    with pytest.raises(NoCaptionsError, match="No captions are available"):
        select({}, {})


def test_no_english_lists_available_languages():
    with pytest.raises(NoCaptionsError, match=r"No English captions are available \(available: de, fr\)"):
        select(tracks("fr"), tracks("de-orig", "de"), language="de")


def test_srt_used_when_vtt_missing():
    subtitles = {"en": caption_formats("https://example.test/en", exts=("json3", "srt"))}
    track = select(subtitles)
    assert track.ext == "srt"


def test_track_without_usable_format_falls_through():
    subtitles = {"en": caption_formats("https://example.test/en", exts=("json3", "ttml"))}
    track = select(subtitles, tracks("en-orig"))
    assert track.automatic is True
    with pytest.raises(NoCaptionsError):
        select(subtitles)


def test_malformed_track_data_is_tolerated():
    subtitles = {"en": "not-a-list", "en-GB": [None, {"ext": "vtt"}, {"ext": "vtt", "url": "u"}]}
    track = select(subtitles)
    assert (track.language, track.url) == ("en-GB", "u")


def test_missing_caption_keys():
    info = video_info()
    info["subtitles"] = None
    info["automatic_captions"] = None
    with pytest.raises(NoCaptionsError):
        select_caption_track(info)


# --------------------------------------------------------------------------- metadata


def test_metadata_from_info():
    track = CaptionTrack("en-GB", True, "u", "vtt")
    meta = metadata_from_info(video_info(VID, "  A Title  ", duration=125.6), track)
    assert meta.video_id == VID
    assert meta.title == "A Title"
    assert meta.url == f"https://www.youtube.com/watch?v={VID}"
    assert meta.channel == "Example Channel"
    assert meta.upload_date == "2026-09-20"
    assert meta.duration == 126
    assert (meta.language, meta.transcript_type) == ("en-GB", "automatic")


def test_metadata_fallbacks():
    info = {"id": VID, "uploader": "Uploader", "timestamp": 1114313512}
    meta = metadata_from_info(info)
    assert meta.title == VID
    assert meta.channel == "Uploader"
    assert meta.upload_date == "2005-04-24"
    assert meta.duration is None
    assert meta.language is None and meta.transcript_type is None


def test_metadata_bad_date_ignored():
    assert metadata_from_info({"id": VID, "upload_date": "2026"}).upload_date is None


def test_playlist_from_info():
    info = {
        "id": "PL1",
        "title": "My Playlist",
        "uploader": "Someone",
        "entries": [
            {"id": "aaaaaaaaaaa", "title": "One", "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa"},
            None,
            {"id": None, "title": "[Deleted video]", "url": None},
            {"id": "bbbbbbbbbbb", "title": None},
        ],
    }
    playlist = playlist_from_info(info, "https://www.youtube.com/playlist?list=PL1")
    assert (playlist.playlist_id, playlist.title, playlist.channel) == ("PL1", "My Playlist", "Someone")
    assert [(e.video_id, e.title) for e in playlist.entries] == [
        ("aaaaaaaaaaa", "One"),
        (None, None),
        (None, "[Deleted video]"),
        ("bbbbbbbbbbb", None),
    ]
    assert playlist.entries[3].url == "https://www.youtube.com/watch?v=bbbbbbbbbbb"


def test_playlist_title_fallback():
    assert playlist_from_info({"id": "PL1", "entries": []}, "u").title == "PL1"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ERROR: [youtube] dQw4w9WgXcQ: Video unavailable", "Video unavailable"),
        ("\x1b[0;31mERROR:\x1b[0m [youtube:tab] PL1: The playlist does not exist", "The playlist does not exist"),
        ("ERROR: Private video. Sign in\nmore detail", "Private video. Sign in"),
        ("plain message", "plain message"),
        ("", "Unknown error"),
    ],
)
def test_clean_error(raw, expected):
    assert clean_error(raw) == expected


# --------------------------------------------------------------------------- client (yt-dlp mocked)


class FakeYoutubeDL:
    """Minimal stand-in for yt_dlp.YoutubeDL used to test the client wrapper."""

    result: Any = None
    error: Exception | None = None
    payload: bytes = b"WEBVTT\n"
    calls: list[tuple[str, dict[str, Any]]] = []

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = params

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True, process=True):
        assert download is False and process is False
        FakeYoutubeDL.calls.append((url, self.params))
        if FakeYoutubeDL.error:
            raise FakeYoutubeDL.error
        return FakeYoutubeDL.result

    def urlopen(self, url):
        if FakeYoutubeDL.error:
            raise FakeYoutubeDL.error

        class Response:
            def read(self_inner):
                return FakeYoutubeDL.payload

        return Response()


@pytest.fixture
def fake_ytdlp(monkeypatch):
    import yt_dlp

    FakeYoutubeDL.result, FakeYoutubeDL.error, FakeYoutubeDL.calls = None, None, []
    FakeYoutubeDL.payload = b"WEBVTT\n"
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)
    return FakeYoutubeDL


def test_client_fetch_video(fake_ytdlp):
    fake_ytdlp.result = video_info(VID)
    info = YouTubeClient().fetch_video(f"https://www.youtube.com/watch?v={VID}")
    assert info["id"] == VID
    _, params = fake_ytdlp.calls[0]
    assert params["skip_download"] is True and params["noplaylist"] is True
    assert "extract_flat" not in params


def test_client_wraps_download_errors(fake_ytdlp):
    import yt_dlp

    fake_ytdlp.error = yt_dlp.utils.DownloadError("ERROR: [youtube] abc: Private video")
    with pytest.raises(YouTubeError, match=r"^Private video$"):
        YouTubeClient().fetch_video("https://youtu.be/abc")


def test_client_rejects_empty_or_playlist_results(fake_ytdlp):
    fake_ytdlp.result = None
    with pytest.raises(YouTubeError, match="no information"):
        YouTubeClient().fetch_video("u")
    fake_ytdlp.result = {"_type": "playlist", "entries": []}
    with pytest.raises(YouTubeError, match="playlist"):
        YouTubeClient().fetch_video("u")


def test_client_fetch_playlist(fake_ytdlp):
    fake_ytdlp.result = {
        "_type": "playlist",
        "id": "PL1",
        "title": "Course",
        "entries": iter([{"id": VID, "title": "Lesson"}]),
    }
    playlist = YouTubeClient().fetch_playlist("https://www.youtube.com/playlist?list=PL1")
    assert playlist.title == "Course"
    assert [e.video_id for e in playlist.entries] == [VID]
    _, params = fake_ytdlp.calls[0]
    assert params["extract_flat"] == "in_playlist" and params["noplaylist"] is False


def test_client_fetch_playlist_requires_playlist(fake_ytdlp):
    fake_ytdlp.result = video_info(VID)
    with pytest.raises(YouTubeError, match="did not resolve to a playlist"):
        YouTubeClient().fetch_playlist("u")


def test_client_download_captions(fake_ytdlp):
    fake_ytdlp.payload = "WEBVTT\n\nCafé \xff".encode("utf-8") + b"\xff"
    text = YouTubeClient().download_captions(CaptionTrack("en", False, "https://example.test", "vtt"))
    assert text.startswith("WEBVTT") and "Café" in text and "\ufffd" in text


def test_client_download_errors(fake_ytdlp):
    fake_ytdlp.error = OSError("HTTP Error 429: Too Many Requests")
    with pytest.raises(YouTubeError, match="Could not download captions: HTTP Error 429"):
        YouTubeClient().download_captions(CaptionTrack("en", False, "https://example.test", "vtt"))


def test_ytdlp_logger_routes_to_debug(caplog):
    logger = youtube._YtDlpLogger()
    with caplog.at_level("DEBUG", logger="yt_transcript"):
        logger.debug("[debug] noisy")
        logger.debug("[youtube] Extracting URL")
        logger.info("info line")
        logger.warning("careful")
        logger.error("broken")
    messages = [r.getMessage() for r in caplog.records]
    assert "yt-dlp: [youtube] Extracting URL" in messages
    assert "yt-dlp warning: careful" in messages
    assert not any("noisy" in m for m in messages)
    assert all(r.levelname == "DEBUG" for r in caplog.records)
