"""Caption parsing, cleanup, rolling-caption deduplication and paragraph reconstruction.

The pipeline is deliberately deterministic and conservative:

1. ``parse_subtitles`` turns WebVTT (or SRT) text into a list of :class:`Cue` objects.
2. ``cue_words`` strips markup, decodes entities and splits each cue into timed words.
3. ``deduplicate`` removes text that is repeated *because of the caption format* —
   YouTube's rolling two-line captions, zero-length "transition" cues and duplicated
   events — and nothing else.
4. ``build_paragraphs`` groups the resulting word stream into readable paragraphs
   using punctuation, pauses and length. Words are never changed, added or reordered.
"""

from __future__ import annotations

import html
import logging
import re
import string
import unicodedata
from collections.abc import Sequence
from itertools import pairwise

from yt_transcript.models import Cue, Paragraph, Word

log = logging.getLogger(__name__)

_TS = r"(?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3}"
_TIMING_LINE = re.compile(rf"^\s*({_TS})\s*-->\s*({_TS})")
_INLINE_TIMESTAMP = re.compile(rf"<\s*({_TS})\s*>")
_TAG = re.compile(r"</?[A-Za-z][^<>\n]*>")
_SSA_OVERRIDE = re.compile(r"\{\\[^{}]*\}")
_INVISIBLE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
_WHITESPACE = re.compile(r"\s+")
_ANNOTATION = re.compile(r"^\[[^\[\]]*[A-Za-z][^\[\]]*\]$")  # e.g. "[Music]", "[Applause]"

# Characters ignored when comparing words, so that "going" and "going," match.
_COMPARE_STRIP = string.punctuation + "\u2018\u2019\u201c\u201d\u00ab\u00bb\u2026\u2013\u2014\u00bf\u00a1"
_CLOSERS = "\"')]}\u2019\u201d\u00bb"
_SENTENCE_END = ".!?\u2026"
_ABBREVIATIONS = frozenset(
    "mr. mrs. ms. dr. prof. sr. jr. st. vs. e.g. i.e. approx. dept. inc. ltd. co. fig. al.".split()
)
_INITIALISM = re.compile(r"^(?:[A-Za-z]\.)+$")

# Deduplication tuning (seconds / words).
TOUCH_GAP = 0.05  # cues closer than this are treated as continuous on screen
NEAR_GAP = 1.0  # rolling overlap is only considered between cues this close
MIN_OVERLAP_WORDS = 3  # overlap length accepted between any two near cues
MAX_OVERLAP_WORDS = 60
ROLLING_RATIO = 0.3  # share of overlapping neighbours that marks a track as rolling
MAX_WORD_DURATION = 0.5  # assumed length of a word timed by an inline timestamp

# Paragraph tuning.
MIN_WORDS = 50
TARGET_WORDS = 90
MAX_WORDS = 150
MAX_SENTENCES = 6
STRONG_BREAK_MIN_WORDS = 20
FORCED_BREAK_PAUSE = 10.0  # seconds of silence that always start a new paragraph
LENGTH_TOLERANCE = 30


# --------------------------------------------------------------------------- parsing


def parse_timestamp(value: str) -> float:
    """Parse ``HH:MM:SS.mmm``, ``MM:SS.mmm`` or SRT-style ``HH:MM:SS,mmm`` into seconds."""
    parts = value.strip().replace(",", ".").split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) >= 3 else 0
    return hours * 3600 + minutes * 60 + seconds


def parse_subtitles(text: str) -> list[Cue]:
    """Parse WebVTT or SRT content into cues, ignoring headers, notes, styles and IDs.

    Parsing is line based rather than block based because YouTube emits
    whitespace-only lines *inside* cue payloads.
    """
    lines = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: list[Cue] = []
    start = end = 0.0
    payload: list[tuple[int, str]] | None = None

    def finish() -> None:
        if payload is not None:
            cues.append(Cue(start, end, tuple(line for _, line in payload)))

    for index, line in enumerate(lines):
        match = _TIMING_LINE.match(line)
        if match:
            if payload:
                # Without a blank separator, a cue identifier ends up in the previous
                # payload. It sits directly above this timing line, after a blank-ish line.
                last_index, _ = payload[-1]
                if last_index == index - 1 and index >= 2 and not lines[index - 2].strip():
                    payload.pop()
            finish()
            start = parse_timestamp(match.group(1))
            end = max(start, parse_timestamp(match.group(2)))
            payload = []
        elif payload is not None:
            if line == "":
                finish()
                payload = None
            else:
                payload.append((index, line))
    finish()
    cues.sort(key=lambda cue: cue.start)
    return cues


# --------------------------------------------------------------------------- cleanup


def _strip_markup(text: str) -> str:
    """Remove tags and decode entities, keeping whitespace so word boundaries survive."""
    text = _INLINE_TIMESTAMP.sub("", text)
    text = _TAG.sub("", text)
    text = _SSA_OVERRIDE.sub("", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFC", text)
    text = _INVISIBLE.sub("", text)
    return "".join(" " if unicodedata.category(ch) in ("Zs", "Cc") else ch for ch in text)


def clean_text(text: str) -> str:
    """Return caption text without markup, entities or redundant whitespace."""
    return _WHITESPACE.sub(" ", _strip_markup(text)).strip()


def _line_words(raw: str, cue: Cue) -> list[Word]:
    parts = _INLINE_TIMESTAMP.split(raw)
    timed = len(parts) > 1
    segments: list[tuple[float, str]] = [(cue.start, parts[0])]
    for i in range(1, len(parts), 2):
        moment = min(max(parse_timestamp(parts[i]), cue.start), cue.end)
        segments.append((moment, parts[i + 1]))

    words: list[Word] = []
    previous_ended_with_space = True
    for i, (seg_start, seg_text) in enumerate(segments):
        text = _strip_markup(seg_text)
        if not text:
            continue
        seg_end = segments[i + 1][0] if i + 1 < len(segments) else cue.end
        end = min(seg_end, seg_start + MAX_WORD_DURATION) if timed else cue.end
        tokens = text.split()
        if tokens and words and not previous_ended_with_space and not text[0].isspace():
            # A timestamp landed inside a word: glue the pieces back together.
            last = words.pop()
            words.append(Word(last.text + tokens.pop(0), last.start, max(last.end, end)))
        words.extend(Word(token, seg_start, max(end, seg_start)) for token in tokens)
        previous_ended_with_space = text[-1].isspace()
    return words


def cue_words(cue: Cue) -> list[list[Word]]:
    """Split a cue into lines of timed words, dropping lines that are empty after cleanup."""
    return [words for words in (_line_words(line, cue) for line in cue.lines) if words]


def _key(text: str) -> str:
    """Comparison key for a word: case-insensitive and ignoring surrounding punctuation."""
    folded = text.casefold().replace("\u2019", "'").replace("\u2018", "'")
    return folded.strip(_COMPARE_STRIP) or folded


def _keys(words: Sequence[Word]) -> list[str]:
    return [_key(word.text) for word in words]


# --------------------------------------------------------------------------- dedup


def _suffix_prefix_overlap(tail: Sequence[str], head: Sequence[str]) -> int:
    """Length of the longest suffix of ``tail`` that equals a prefix of ``head``."""
    limit = min(len(tail), len(head), MAX_OVERLAP_WORDS)
    for k in range(limit, 0, -1):
        if list(tail[-k:]) == list(head[:k]):
            return k
    return 0


def _carried_lines(previous: list[list[str]], current: list[list[str]]) -> int:
    """Number of leading lines of ``current`` that repeat the trailing lines of ``previous``."""
    for j in range(min(len(previous), len(current)), 0, -1):
        if current[:j] == previous[-j:]:
            return j
    return 0


def is_rolling(cues: Sequence[tuple[Cue, list[list[Word]]]]) -> bool:
    """Decide whether a track uses rolling (overlapping) captions.

    A track counts as rolling when a meaningful share of neighbouring cues repeat
    the end of the previous cue at their start. Ordinary subtitle tracks almost never
    do this, so overlap removal stays switched off for them.
    """
    pairs = hits = 0
    for (prev_cue, prev_lines), (cue, lines) in pairwise(cues):
        if cue.start - prev_cue.end > NEAR_GAP:
            continue
        prev_keys = [_keys(line) for line in prev_lines]
        keys = [_keys(line) for line in lines]
        if prev_keys == keys:
            continue
        pairs += 1
        flat_prev = [k for line in prev_keys for k in line]
        flat = [k for line in keys for k in line]
        if prev_keys[-1] == keys[0] or _suffix_prefix_overlap(flat_prev, flat) >= 2:
            hits += 1
    return hits > 0 and hits / max(pairs, 1) >= ROLLING_RATIO


def deduplicate(cues: Sequence[Cue]) -> list[Word]:
    """Flatten cues into a word stream, removing caption-format duplication only.

    Removed:
      * duplicated events (identical text shown at overlapping times);
      * in rolling tracks, lines carried over from the previous cue and word overlaps
        between the end of the emitted text and the start of the next cue;
      * consecutive repeats of the same sound annotation such as ``[Music]``.

    Single-word overlaps and overlaps made of one repeated word ("no no") are never
    removed, nor is anything between cues separated by a pause, so genuine
    repetition in speech is preserved.
    """
    tokenized = [(cue, lines) for cue in cues if (lines := cue_words(cue))]
    rolling = is_rolling(tokenized)
    out: list[Word] = []
    removed = 0
    prev_keys: list[list[str]] | None = None
    prev_start = prev_end = 0.0
    last_annotation: str | None = None

    for cue, lines in tokenized:
        keys = [_keys(line) for line in lines]
        words = [word for line in lines for word in line]
        total = len(words)

        if prev_keys is not None:
            gap = cue.start - prev_end
            if keys == prev_keys and (
                cue.start < prev_end or cue.start == prev_start or (rolling and gap <= TOUCH_GAP)
            ):
                removed += total
                prev_end = max(prev_end, cue.end)
                continue
            if rolling and gap <= NEAR_GAP:
                j = _carried_lines(prev_keys, keys) if gap <= TOUCH_GAP else 0
                carried = [k for line in keys[:j] for k in line]
                if j and _keys(out[-len(carried):]) == carried:
                    # Whole lines carried over from the previous cue (YouTube's layout).
                    # That is the complete overlap; the remaining lines are new speech.
                    words = [word for line in lines[j:] for word in line]
                else:
                    tail = _keys(out[-MAX_OVERLAP_WORDS:])
                    k = _suffix_prefix_overlap(tail, _keys(words))
                    distinct = len(set(tail[len(tail) - k :])) if k else 0
                    if distinct >= 2 and (k >= MIN_OVERLAP_WORDS or gap <= TOUCH_GAP):
                        words = words[k:]

        text = " ".join(word.text for word in words)
        if _ANNOTATION.match(text):
            if last_annotation is not None and _key(text) == last_annotation:
                words = []
            last_annotation = _key(text)
        elif words:
            last_annotation = None

        removed += total - len(words)
        if words:
            last = words[-1]
            words[-1] = Word(last.text, last.start, last.end, cue_end=True)
        out.extend(words)
        prev_keys, prev_start, prev_end = keys, cue.start, cue.end

    log.debug(
        "Deduplicated %d cues (rolling=%s): kept %d words, removed %d",
        len(tokenized),
        rolling,
        len(out),
        removed,
    )
    return out


# --------------------------------------------------------------------------- paragraphs


def ends_sentence(text: str) -> bool:
    """True when a word ends a sentence (ignoring common abbreviations and initials)."""
    stripped = text.rstrip(_CLOSERS)
    if not stripped or stripped[-1] not in _SENTENCE_END:
        return False
    lowered = stripped.casefold()
    if lowered in _ABBREVIATIONS or _INITIALISM.match(stripped):
        return False
    return True


def _break_score(word: Word, following: Word) -> float:
    """How good a paragraph break between ``word`` and ``following`` would be."""
    score = 0.0
    if ends_sentence(word.text):
        score += 3
    elif word.text[-1] in ",;:":
        score += 0.5
    if word.cue_end:
        score += 0.5
    pause = following.start - word.end
    if pause >= 2.0:
        score += 3
    elif pause >= 1.0:
        score += 2
    elif pause >= 0.5:
        score += 1
    if following.text.startswith(">>"):  # speaker change marker used in captions
        score += 3
    return score


def build_paragraphs(
    words: Sequence[Word],
    min_words: int = MIN_WORDS,
    target_words: int = TARGET_WORDS,
    max_words: int = MAX_WORDS,
) -> list[Paragraph]:
    """Group words into paragraphs of roughly ``min_words``–``max_words`` words.

    Breaks prefer sentence ends and pauses. Unpunctuated automatic captions fall back
    to pauses, then to the length target. Word text is joined with single spaces.
    """
    n = len(words)
    scores = [_break_score(words[i], words[i + 1]) for i in range(n - 1)]
    paragraphs: list[Paragraph] = []
    start = 0
    while start < n:
        end = _choose_end(words, scores, start, min_words, target_words, max_words)
        chunk = words[start : end + 1]
        paragraphs.append(Paragraph(chunk[0].start, " ".join(word.text for word in chunk)))
        start = end + 1
    return paragraphs


def _choose_end(
    words: Sequence[Word],
    scores: Sequence[float],
    start: int,
    min_words: int,
    target_words: int,
    max_words: int,
) -> int:
    last = len(words) - 1
    remaining = len(words) - start
    take_rest = remaining <= target_words + min_words // 2
    if remaining - target_words < min_words:
        # Two paragraphs' worth left: aim for an even split rather than a short tail.
        target_words = max(min_words, remaining // 2)
    if not take_rest:
        # Leave enough words that the next paragraph is not a tiny fragment.
        hi = min(start + max_words - 1, last - min_words // 2)
    else:
        hi = last
    best_index, best_rank = None, None
    sentences = 0
    for i in range(start, hi + 1):
        if i == last:
            return last
        if words[i + 1].start - words[i].end >= FORCED_BREAK_PAUSE:
            return i  # keep timestamps honest across long silences
        count = i - start + 1
        score = scores[i]
        sentence = ends_sentence(words[i].text)
        sentences += sentence
        if count >= STRONG_BREAK_MIN_WORDS and score >= 6:
            return i
        if sentence and sentences >= MAX_SENTENCES and count >= min_words * 0.6 and last - i >= min_words // 2:
            return i
        if count < min_words or last - i < min_words // 2:
            continue
        # Trade break strength against distance from the target length: one tier of
        # strength is worth LENGTH_TOLERANCE words.
        tier = 3 if score >= 5 else 2 if score >= 3 else 1 if score >= 1 else 0
        rank = (tier - abs(count - target_words) / LENGTH_TOLERANCE, score)
        if best_rank is None or rank > best_rank:
            best_index, best_rank = i, rank
    return best_index if best_index is not None else hi


# --------------------------------------------------------------------------- timestamps


def timestamp_positions(paragraphs: Sequence[Paragraph], interval: float) -> set[int]:
    """Choose which paragraphs get a timestamp, roughly every ``interval`` seconds.

    The first paragraph is always stamped. After that, once ``interval`` seconds have
    passed, the paragraph starting nearest to the target time is stamped.
    """
    if not paragraphs:
        return set()
    stamped = {0}
    last_index, last_time = 0, paragraphs[0].start
    i = 1
    while i < len(paragraphs):
        target = last_time + interval
        if paragraphs[i].start >= target:
            chosen = i
            before = paragraphs[i - 1].start
            if (
                i - 1 > last_index
                and before - last_time >= interval / 2
                and target - before < paragraphs[i].start - target
            ):
                chosen = i - 1
            stamped.add(chosen)
            last_index, last_time = chosen, paragraphs[chosen].start
            i = chosen + 1
        else:
            i += 1
    return stamped


def transcript_paragraphs(caption_text: str) -> list[Paragraph]:
    """Run the full caption pipeline on raw WebVTT/SRT text."""
    cues = parse_subtitles(caption_text)
    words = deduplicate(cues)
    paragraphs = build_paragraphs(words)
    log.debug("Parsed %d cues into %d words and %d paragraphs", len(cues), len(words), len(paragraphs))
    return paragraphs
