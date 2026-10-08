from __future__ import annotations

import subprocess
import sys

import pytest

from tests.conftest import FakeClient
from yt_transcript import __version__
from yt_transcript.cli import build_parser, main

A, B = "aaaaaaaaaaa", "bbbbbbbbbbb"
URL_A = f"https://www.youtube.com/watch?v={A}"


def test_defaults():
    args = build_parser().parse_args([URL_A])
    assert args.urls == [URL_A]
    assert str(args.output) == "transcripts"
    assert args.timestamp_interval == 45
    assert not (args.combine or args.no_timestamps or args.overwrite or args.verbose)


def test_all_options():
    args = build_parser().parse_args(
        [URL_A, "x", "-o", "out", "--combine", "--timestamp-interval", "60", "--overwrite", "-v"]
    )
    assert args.urls == [URL_A, "x"]
    assert (str(args.output), args.combine, args.timestamp_interval, args.overwrite, args.verbose) == (
        "out",
        True,
        60,
        True,
        True,
    )


@pytest.mark.parametrize(
    "argv",
    [
        [],
        [URL_A, "--timestamp-interval", "0"],
        [URL_A, "--timestamp-interval", "-5"],
        [URL_A, "--timestamp-interval", "soon"],
        [URL_A, "--no-timestamps", "--timestamp-interval", "30"],
        [URL_A, "--unknown-flag"],
    ],
)
def test_usage_errors_exit_with_status_2(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv, client=FakeClient())
    assert exc.value.code == 2
    assert "usage: yt-transcript" in capsys.readouterr().err


def test_help_lists_every_option(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for option in ["--output", "--combine", "--timestamp-interval", "--no-timestamps", "--overwrite", "--verbose", "--version"]:
        assert option in out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.strip() == f"yt-transcript {__version__}"


def test_successful_run(tmp_path, capsys):
    client = FakeClient()
    client.add_video(A, "My Video")
    code = main([URL_A, "--output", str(tmp_path)], client=client)
    assert code == 0
    err = capsys.readouterr().err
    assert "[1/1] https://www.youtube.com/watch?v=aaaaaaaaaaa" in err
    assert f"saved {tmp_path / f'My Video [{A}].md'}" in err
    assert err.strip().endswith("Done: 1 saved.")
    assert (tmp_path / f"My Video [{A}].md").exists()


def test_partial_failure_exit_code_and_summary(tmp_path, capsys):
    client = FakeClient()
    client.add_video(A, "Works")
    code = main([URL_A, f"https://youtu.be/{B}", "not-a-url", "-o", str(tmp_path)], client=client)
    assert code == 1
    err = capsys.readouterr().err
    assert "error: Not a YouTube video or playlist URL: not-a-url" in err
    assert "skipped: Video unavailable" in err
    assert "Done: 1 saved, 1 skipped, 1 invalid URL." in err


def test_existing_summary(tmp_path, capsys):
    client = FakeClient()
    client.add_video(A, "Works")
    main([URL_A, "-o", str(tmp_path)], client=client)
    capsys.readouterr()
    assert main([URL_A, "-o", str(tmp_path)], client=client) == 0
    err = capsys.readouterr().err
    assert "(use --overwrite to replace)" in err
    assert "Done: 0 saved, 1 already existed." in err


def test_no_timestamps_flag(tmp_path):
    client = FakeClient()
    client.add_video(A, "Plain")
    main([URL_A, "-o", str(tmp_path), "--no-timestamps"], client=client)
    text = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "[00:00]" not in text and "Welcome back." in text


def test_combine_flag(tmp_path):
    client = FakeClient()
    client.add_video(A, "One")
    client.add_video(B, "Two")
    main([URL_A, B, "-o", str(tmp_path), "--combine"], client=client)
    assert (tmp_path / "combined-transcripts.md").exists()
    assert (tmp_path / "INDEX.md").exists()


def test_output_expands_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    client = FakeClient()
    client.add_video(A, "Home")
    main([URL_A, "-o", "~/research"], client=client)
    assert (tmp_path / "research" / f"Home [{A}].md").exists()


def test_default_output_directory_is_relative_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = FakeClient()
    client.add_video(A, "Here")
    main([URL_A], client=client)
    assert (tmp_path / "transcripts" / f"Here [{A}].md").exists()


def test_verbose_shows_debug_details(tmp_path, capsys):
    client = FakeClient()
    client.add_video(A, "Chatty")
    main([URL_A, "-o", str(tmp_path), "--verbose"], client=client)
    err = capsys.readouterr().err
    assert "Selected manual captions (en, vtt)" in err
    assert "Parsed 4 cues" in err


def test_quiet_without_verbose(tmp_path, capsys):
    client = FakeClient()
    client.add_video(A, "Calm")
    main([URL_A, "-o", str(tmp_path)], client=client)
    assert "Selected manual captions" not in capsys.readouterr().err


def test_verbose_shows_tracebacks_for_unexpected_errors(tmp_path, capsys):
    client = FakeClient()
    client.videos[A] = ValueError("bad data")
    main([URL_A, "-o", str(tmp_path), "-v"], client=client)
    err = capsys.readouterr().err
    assert "Traceback" in err and "ValueError: bad data" in err
    assert "skipped: Unexpected error: bad data" in err


def test_keyboard_interrupt(tmp_path, capsys):
    class Interrupting(FakeClient):
        def fetch_video(self, url):
            raise KeyboardInterrupt

    assert main([URL_A, "-o", str(tmp_path)], client=Interrupting()) == 130
    assert "Interrupted." in capsys.readouterr().err


def test_module_entry_point():
    result = subprocess.run([sys.executable, "-m", "yt_transcript", "--version"], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip() == f"yt-transcript {__version__}"
