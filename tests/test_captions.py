from __future__ import annotations

import pytest

from tests.conftest import rolling_vtt, simple_vtt, timed_line
from yt_transcript.captions import (
    build_paragraphs,
    clean_text,
    cue_words,
    deduplicate,
    ends_sentence,
    is_rolling,
    parse_subtitles,
    parse_timestamp,
    timestamp_positions,
    transcript_paragraphs,
)
from yt_transcript.models import Cue, Paragraph, Word


def text_of(words: list[Word]) -> str:
    return " ".join(word.text for word in words)


def dedup_text(vtt: str) -> str:
    return text_of(deduplicate(parse_subtitles(vtt)))


def make_words(text: str, start: float = 0.0, step: float = 0.3) -> list[Word]:
    return [Word(token, start + i * step, start + i * step + step) for i, token in enumerate(text.split())]


# --------------------------------------------------------------------------- timestamps


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("00:00:00.000", 0.0),
        ("00:00:01.500", 1.5),
        ("00:01:02.250", 62.25),
        ("01:02:03.004", 3723.004),
        ("02:03.500", 123.5),
        ("00:00:01,250", 1.25),  # SRT
        ("100:00:00.000", 360000.0),
        (" 00:00:05.000 ", 5.0),
    ],
)
def test_parse_timestamp(value, expected):
    assert parse_timestamp(value) == pytest.approx(expected)


# --------------------------------------------------------------------------- parsing


def test_parse_ignores_header_style_note_and_identifiers():
    vtt = """WEBVTT - with a title
Kind: captions
Language: en

STYLE
::cue { color: yellow }

NOTE This is a comment
spanning two lines

intro
00:00:01.000 --> 00:00:02.000 align:start position:0%
Hello there.

2
00:00:02.000 --> 00:00:03.500
General Kenobi.
"""
    cues = parse_subtitles(vtt)
    assert [(c.start, c.end, c.lines) for c in cues] == [
        (1.0, 2.0, ("Hello there.",)),
        (2.0, 3.5, ("General Kenobi.",)),
    ]


def test_parse_srt():
    srt = "1\r\n00:00:01,000 --> 00:00:02,500\r\nFirst line\r\nsecond line\r\n\r\n2\r\n00:00:03,000 --> 00:00:04,000\r\nNext\r\n"
    cues = parse_subtitles(srt)
    assert cues == [
        Cue(1.0, 2.5, ("First line", "second line")),
        Cue(3.0, 4.0, ("Next",)),
    ]


def test_parse_keeps_whitespace_only_lines_inside_youtube_cues():
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n \nhello<00:00:00.500><c> world</c>\n\n00:00:02.000 --> 00:00:02.010\nhello world\n \n"
    cues = parse_subtitles(vtt)
    assert len(cues) == 2
    assert cues[0].lines == (" ", "hello<00:00:00.500><c> world</c>")
    assert cues[1].lines == ("hello world", " ")


def test_parse_handles_bom_cr_and_missing_final_newline():
    vtt = "\ufeffWEBVTT\r\r00:00:01.000 --> 00:00:02.000\rText"
    assert parse_subtitles(vtt) == [Cue(1.0, 2.0, ("Text",))]


def test_parse_drops_identifier_when_blank_separator_is_whitespace():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nOne\n  \n7\n00:00:02.000 --> 00:00:03.000\nTwo\n"
    cues = parse_subtitles(vtt)
    assert [c.lines for c in cues] == [("One", "  "), ("Two",)]
    assert text_of(deduplicate(cues)) == "One Two"


def test_parse_sorts_cues_and_clamps_inverted_times():
    vtt = simple_vtt([(5.0, 6.0, "later"), (1.0, 2.0, "earlier")]) + "\n00:00:09.000 --> 00:00:08.000\nbackwards\n"
    cues = parse_subtitles(vtt)
    assert [c.lines[0] for c in cues] == ["earlier", "later", "backwards"]
    assert cues[-1].start == cues[-1].end == 9.0


def test_parse_ignores_text_outside_cues_and_malformed_timing():
    vtt = "WEBVTT\n\nstray text\n\n00:00:01 --> 00:00:02\nbad timing\n\n00:00:03.000 --> 00:00:04.000\ngood\n"
    assert [c.lines for c in parse_subtitles(vtt)] == [("good",)]


def test_parse_empty_input():
    assert parse_subtitles("") == []
    assert parse_subtitles("WEBVTT\n\n") == []


# --------------------------------------------------------------------------- cleanup


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<c>hello</c> <c.colorE5E5E5>world</c>", "hello world"),
        ("<i>italic</i> and <b>bold</b> and <u>under</u>", "italic and bold and under"),
        ("<v Roger Bingham>We are in New York City", "We are in New York City"),
        ('<font color="#ffffff">white</font>', "white"),
        ("Q&amp;A &lt;tags&gt; &quot;quoted&quot; it&#39;s", 'Q&A <tags> "quoted" it\'s'),
        ("non\u00a0breaking&nbsp;space", "non breaking space"),
        ("zero\u200bwidth\ufeff", "zerowidth"),
        ("  lots   of\t\twhitespace  ", "lots of whitespace"),
        ("{\\an8}top of screen", "top of screen"),
        ("cafe\u0301", "caf\u00e9"),  # NFC normalisation
        ("x < y and y > z", "x < y and y > z"),  # not tags
        ("<00:00:01.000><c> timed</c>", "timed"),
        ("emoji \U0001f600 stays", "emoji \U0001f600 stays"),
        ("[ __ ] censored", "[ __ ] censored"),
    ],
)
def test_clean_text(raw, expected):
    assert clean_text(raw) == expected


def test_cue_words_assigns_inline_timestamps():
    cue = Cue(10.0, 12.0, (" ", "so<00:00:10.400><c> today</c><00:00:11.000><c> we</c>"))
    [line] = cue_words(cue)
    assert [(w.text, w.start) for w in line] == [("so", 10.0), ("today", 10.4), ("we", 11.0)]
    assert line[0].end == pytest.approx(10.4)
    assert line[1].end == pytest.approx(10.9)  # capped at MAX_WORD_DURATION
    assert line[2].end == pytest.approx(11.5)


def test_cue_words_untimed_words_span_the_cue():
    [line] = cue_words(Cue(1.0, 4.0, ("plain words",)))
    assert [(w.start, w.end) for w in line] == [(1.0, 4.0), (1.0, 4.0)]


def test_cue_words_rejoins_word_split_by_timestamp():
    [line] = cue_words(Cue(0.0, 2.0, ("some<00:00:00.500>thing<00:00:01.000> else",)))
    assert [w.text for w in line] == ["something", "else"]


def test_cue_words_clamps_inline_timestamps_into_cue():
    [line] = cue_words(Cue(5.0, 6.0, ("a<00:00:01.000><c> b</c><00:00:09.000><c> c</c>",)))
    assert [w.start for w in line] == [5.0, 5.0, 6.0]


def test_cue_words_drops_empty_and_markup_only_lines():
    assert cue_words(Cue(0, 1, (" ", "<c></c>", "&nbsp;"))) == []


# --------------------------------------------------------------------------- dedup


def test_rolling_example_from_overlapping_cues():
    vtt = simple_vtt(
        [
            (10.0, 12.0, "so today we're going to"),
            (12.0, 14.0, "so today we're going to talk about how"),
            (14.0, 16.0, "talk about how to build a business"),
        ]
    )
    assert dedup_text(vtt) == "so today we're going to talk about how to build a business"


def test_youtube_rolling_layout_is_reconstructed_exactly():
    lines = [
        timed_line("so today we're going to talk about how", 0.0),
        timed_line("to build a business from scratch", 2.4),
        timed_line("and what we learned", 4.4),
    ]
    vtt = rolling_vtt(lines, end=6.0)
    assert dedup_text(vtt) == (
        "so today we're going to talk about how to build a business from scratch and what we learned"
    )


def test_youtube_fixture_matches_expected_words(fixtures_dir):
    vtt = (fixtures_dir / "youtube_auto.vtt").read_text(encoding="utf-8")
    expected = (fixtures_dir / "youtube_auto.expected.txt").read_text(encoding="utf-8").strip()
    assert dedup_text(vtt) == expected


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        # Repeated words spoken across a caption-line boundary must survive.
        ("they just go chunk chunk", "chunk chunk chunk and then", "they just go chunk chunk chunk chunk chunk and then"),
        ("the answer was no no", "no no and that hurt", "the answer was no no no no and that hurt"),
        ("again and again and again", "and again we tried", "again and again and again and again we tried"),
        ("it was very", "very good indeed", "it was very very good indeed"),
    ],
)
def test_genuine_repetition_in_rolling_captions_is_preserved(first, second, expected):
    vtt = rolling_vtt([timed_line(first, 0.0), timed_line(second, 3.0), timed_line("end of the talk", 6.0)], 9.0)
    assert dedup_text(vtt) == expected + " end of the talk"


def test_single_word_overlap_is_never_removed():
    vtt = simple_vtt(
        [
            (0.0, 2.0, "we went to the shop and the shop"),
            (2.0, 4.0, "shop was closed so we left"),
            (4.0, 6.0, "so we left and went home again"),
        ]
    )
    # "shop" (one word) stays; "so we left" (three words) is rolling overlap.
    assert dedup_text(vtt) == "we went to the shop and the shop shop was closed so we left and went home again"


def test_overlap_after_a_pause_is_kept():
    vtt = simple_vtt(
        [
            (0.0, 2.0, "this is the most important point"),
            (2.0, 4.0, "the most important point is this one"),
            (8.0, 10.0, "is this one clear to everyone"),
        ]
    )
    # The track is rolling, but the third cue starts four seconds later: keep it whole.
    assert dedup_text(vtt) == (
        "this is the most important point is this one is this one clear to everyone"
    )


def test_manual_track_repetition_is_not_treated_as_overlap():
    vtt = simple_vtt(
        [
            (0.0, 2.0, "Never give up."),
            (2.0, 4.0, "Never give up."),  # touching duplicate in a manual track: kept
            (4.0, 6.0, "That is what I keep saying to the team."),
            (6.0, 8.0, "I keep saying it because it matters."),
            (8.0, 10.0, "Every single day."),
        ]
    )
    cues = parse_subtitles(vtt)
    assert not is_rolling([(c, cue_words(c)) for c in cues])
    assert dedup_text(vtt) == (
        "Never give up. Never give up. That is what I keep saying to the team. "
        "I keep saying it because it matters. Every single day."
    )


def test_duplicate_events_with_overlapping_times_are_removed():
    vtt = simple_vtt(
        [
            (0.0, 3.0, "First line."),
            (0.0, 3.0, "First line."),  # identical event
            (2.5, 4.0, "first line"),  # overlapping duplicate, different case/punctuation
            (4.0, 6.0, "Second line."),
        ]
    )
    assert dedup_text(vtt) == "First line. Second line."


def test_overlap_comparison_ignores_case_and_punctuation():
    vtt = simple_vtt(
        [
            (0.0, 2.0, "So, today we're going"),
            (2.0, 4.0, "so today we're going to start."),
            (4.0, 6.0, "We're going to start with the basics."),
            (6.0, 8.0, "with the basics, then move on"),
        ]
    )
    # The first copy of overlapping words is kept, including its punctuation.
    assert dedup_text(vtt) == "So, today we're going to start. with the basics. then move on"


def test_repeated_sound_annotations_are_collapsed():
    vtt = simple_vtt(
        [
            (0.0, 2.0, "[Music]"),
            (2.0, 4.0, "[Music]"),
            (6.0, 8.0, "[music]"),
            (8.0, 10.0, "hello everyone"),
            (10.0, 12.0, "[Music]"),
            (12.0, 14.0, "[Applause]"),
            (14.0, 16.0, "[ __ ] that was loud"),
        ]
    )
    assert dedup_text(vtt) == "[Music] hello everyone [Music] [Applause] [ __ ] that was loud"


def test_empty_cues_are_ignored():
    vtt = simple_vtt([(0.0, 1.0, " "), (1.0, 2.0, "<c></c>"), (2.0, 3.0, "words")])
    assert dedup_text(vtt) == "words"


def test_dedup_marks_cue_ends():
    words = deduplicate(parse_subtitles(simple_vtt([(0, 1, "a b"), (1, 2, "c")])))
    assert [w.cue_end for w in words] == [False, True, True]


def test_is_rolling_detection():
    rolling = parse_subtitles(rolling_vtt([timed_line("a b c d", 0), timed_line("e f g h", 2), timed_line("i j", 4)], 6))
    manual = parse_subtitles(simple_vtt([(0, 2, "One sentence."), (2, 4, "Another one."), (4, 6, "A third.")]))
    assert is_rolling([(c, cue_words(c)) for c in rolling if cue_words(c)])
    assert not is_rolling([(c, cue_words(c)) for c in manual])
    assert not is_rolling([])


def test_long_rolling_track_keeps_every_word():
    phrases = [f"phrase number {i} has unique words alpha{i} beta{i}" for i in range(200)]
    lines = [timed_line(p, i * 2.0, 0.2) for i, p in enumerate(phrases)]
    assert dedup_text(rolling_vtt(lines, 401.0)) == " ".join(phrases)


# --------------------------------------------------------------------------- sentences


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("end.", True),
        ("really?", True),
        ("wow!", True),
        ("so…", True),
        ('said."', True),
        ("(aside.)", True),
        ("etc.", True),
        ("comma,", False),
        ("word", False),
        ("Mr.", False),
        ("Dr.", False),
        ("e.g.", False),
        ("U.S.", False),
        ("J.", False),
        ("vs.", False),
    ],
)
def test_ends_sentence(word, expected):
    assert ends_sentence(word) is expected


# --------------------------------------------------------------------------- paragraphs


def sentences(count: int, words_each: int = 10) -> str:
    return " ".join(" ".join(["word"] * (words_each - 1) + ["end."]) for _ in range(count))


def test_build_paragraphs_empty_and_short():
    assert build_paragraphs([]) == []
    paragraphs = build_paragraphs(make_words("Just a short clip.", start=3.0))
    assert paragraphs == [Paragraph(3.0, "Just a short clip.")]


def test_paragraphs_preserve_every_word_in_order():
    words = make_words(sentences(40, 13))
    paragraphs = build_paragraphs(words)
    assert " ".join(p.text for p in paragraphs) == text_of(words)
    assert len(paragraphs) > 3


def test_punctuated_text_breaks_at_sentence_ends_within_bounds():
    words = make_words(sentences(60, 12))
    paragraphs = build_paragraphs(words)
    for paragraph in paragraphs:
        count = len(paragraph.text.split())
        assert paragraph.text.endswith("end.")
        assert count <= 150
    assert all(len(p.text.split()) >= 30 for p in paragraphs[:-1])


def test_paragraph_start_is_first_word_time():
    words = make_words(sentences(30, 10), start=100.0)
    paragraphs = build_paragraphs(words)
    assert paragraphs[0].start == 100.0
    offset = len(paragraphs[0].text.split())
    assert paragraphs[1].start == pytest.approx(words[offset].start)


def test_unpunctuated_text_breaks_at_pauses():
    first = make_words(" ".join(["alpha"] * 70), start=0.0)
    second = make_words(" ".join(["beta"] * 70), start=first[-1].end + 3.0)
    paragraphs = build_paragraphs(first + second)
    assert [p.text.split()[0] for p in paragraphs] == ["alpha", "beta"]
    assert len(paragraphs[0].text.split()) == 70


def test_text_without_any_signal_is_split_near_target_length():
    words = make_words(" ".join(f"w{i}" for i in range(400)), step=0.2)
    paragraphs = build_paragraphs(words)
    counts = [len(p.text.split()) for p in paragraphs]
    assert sum(counts) == 400
    assert all(50 <= c <= 150 for c in counts)


def test_paragraphs_never_exceed_max_words():
    words = make_words(" ".join(["x"] * 1000), step=0.2)
    assert max(len(p.text.split()) for p in build_paragraphs(words)) <= 150


def test_strong_break_starts_new_paragraph_early():
    words = make_words(sentences(3, 10))  # 30 words
    later = make_words(sentences(3, 10), start=words[-1].end + 5.0)
    paragraphs = build_paragraphs(words + later)
    assert len(paragraphs) == 2


def test_long_silence_always_breaks_even_short_paragraphs():
    words = make_words("Hello there.") + make_words("Back again after a break.", start=60.0)
    paragraphs = build_paragraphs(words)
    assert [(p.start, p.text) for p in paragraphs] == [(0.0, "Hello there."), (60.0, "Back again after a break.")]


@pytest.mark.parametrize("count", [1, 40, 50, 115, 116, 140, 200, 260, 400, 1000])
def test_paragraph_lengths_stay_in_range_without_signals(count):
    words = make_words(" ".join(f"w{i}" for i in range(count)), step=0.2)
    counts = [len(p.text.split()) for p in build_paragraphs(words)]
    assert sum(counts) == count
    if count < 50:
        assert counts == [count]
    else:
        assert all(50 <= c <= 150 for c in counts)


def test_speaker_change_marker_is_a_break_signal():
    first = make_words(sentences(5, 10))
    second = make_words(">> " + sentences(5, 10), start=first[-1].end)
    paragraphs = build_paragraphs(first + second)
    assert paragraphs[1].text.startswith(">>")


def test_no_tiny_trailing_paragraph_from_weak_breaks():
    words = make_words(sentences(9, 10) + " and one more.")
    paragraphs = build_paragraphs(words)
    assert len(paragraphs[-1].text.split()) >= 25


def test_custom_paragraph_sizes():
    words = make_words(sentences(20, 5))
    paragraphs = build_paragraphs(words, min_words=10, target_words=15, max_words=20)
    assert all(len(p.text.split()) <= 20 for p in paragraphs)
    assert len(paragraphs) >= 5


# --------------------------------------------------------------------------- timestamp choice


def paras_at(*starts: float) -> list[Paragraph]:
    return [Paragraph(s, f"p{s}") for s in starts]


def test_timestamp_positions_first_always_stamped():
    assert timestamp_positions(paras_at(5), 45) == {0}
    assert timestamp_positions([], 45) == set()


def test_timestamp_positions_follow_interval():
    paragraphs = paras_at(*range(0, 300, 15))  # every 15 s
    stamped = sorted(timestamp_positions(paragraphs, 45))
    times = [paragraphs[i].start for i in stamped]
    assert times == [0, 45, 90, 135, 180, 225, 270]


def test_timestamp_positions_prefer_nearest_paragraph():
    # Target 45: the paragraph at 40 is closer than the one at 80.
    # Then target 85: 80 is closer than 100.
    assert timestamp_positions(paras_at(0, 20, 40, 80, 100), 45) == {0, 2, 3}


def test_timestamp_positions_do_not_pick_paragraph_too_close_to_previous():
    # 5 s is nearer the target than 200 s, but far too close to the previous stamp.
    assert timestamp_positions(paras_at(0, 5, 200), 45) == {0, 2}


def test_timestamp_positions_long_paragraphs_each_stamped():
    assert timestamp_positions(paras_at(0, 60, 130, 200), 45) == {0, 1, 2, 3}


@pytest.mark.parametrize("interval", [10, 30, 45, 60, 120])
def test_timestamp_gaps_are_reasonable(interval):
    paragraphs = paras_at(*[i * 7.0 for i in range(200)])
    times = [paragraphs[i].start for i in sorted(timestamp_positions(paragraphs, interval))]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(interval / 2 <= gap <= interval + 7 for gap in gaps)


# --------------------------------------------------------------------------- end to end


def test_transcript_paragraphs_on_youtube_fixture(fixtures_dir):
    vtt = (fixtures_dir / "youtube_auto.vtt").read_text(encoding="utf-8")
    expected = (fixtures_dir / "youtube_auto.expected.txt").read_text(encoding="utf-8").strip()
    paragraphs = transcript_paragraphs(vtt)
    assert " ".join(p.text for p in paragraphs) == expected
    assert len(paragraphs) >= 2
    # Paragraphs start at the long pauses that separate the talk's sections.
    assert paragraphs[1].text.startswith("the second thing is pricing")
    assert paragraphs[0].start == 0.0


def test_transcript_paragraphs_on_manual_fixture(fixtures_dir):
    vtt = (fixtures_dir / "manual.vtt").read_text(encoding="utf-8")
    paragraphs = transcript_paragraphs(vtt)
    text = " ".join(p.text for p in paragraphs)
    assert "Kind:" not in text and "NOTE" not in text and "<" not in text
    assert "Q&A" in text
    assert text.count("Welcome back to the workshop.") == 1
    assert text.startswith("Welcome back to the workshop.")
    assert text.endswith("See you next time.")


def test_transcript_paragraphs_on_srt_fixture(fixtures_dir):
    paragraphs = transcript_paragraphs((fixtures_dir / "sample.srt").read_text(encoding="utf-8"))
    assert " ".join(p.text for p in paragraphs) == (
        "This is a subtitle file in SubRip format. It has italic text and two lines in one cue. "
        "Café, naïve and 東京 survive intact."
    )
