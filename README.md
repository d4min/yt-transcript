# yt-transcript

[![tests](https://github.com/d4min/yt-transcript/actions/workflows/tests.yml/badge.svg)](https://github.com/d4min/yt-transcript/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Convert YouTube videos and playlists into clean, timestamped Markdown transcripts.

`yt-transcript` downloads a video's existing English captions, removes the
formatting noise that caption files are full of, and writes a readable Markdown
document with metadata, paragraphs and periodic timestamps. The output is meant
to be used as source material: for LLM prompts, research and note-taking,
full-text search, RAG pipelines, or any other text-processing workflow.

It preserves the transcript rather than rewriting it. Nothing is summarised,
paraphrased or "cleaned up" with a language model. The words in the output are
the words in the captions, minus the duplication that the caption format itself
introduces.

```console
$ yt-transcript "https://www.youtube.com/watch?v=VIDEO_ID"
[1/1] https://www.youtube.com/watch?v=VIDEO_ID
  saved transcripts/How I Built My SaaS [VIDEO_ID].md
Done: 1 saved.
```

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Usage](#usage)
- [Examples](#examples)
- [Example output](#example-output)
- [How it works](#how-it-works)
- [Output structure](#output-structure)
- [Development](#development)
- [Testing](#testing)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Individual videos.** Standard `watch` links, `youtu.be` short links, Shorts,
  live and embed URLs, or a bare 11-character video ID.
- **Playlists.** Each playlist gets its own folder with numbered transcripts and
  an `INDEX.md`.
- **Batch URLs.** Pass any number of videos and playlists in one command.
- **Automatic subtitle selection.** The best available English track is chosen
  for you.
- **Manual captions preferred.** Human-made subtitles (`en`, then regional
  variants such as `en-US` and `en-GB`) always win over automatic ones.
- **Automatic caption fallback.** When no manual subtitles exist, YouTube's
  speech-recognition captions are used. Machine-*translated* "English" captions
  of non-English videos are rejected rather than passed off as a transcript.
- **Rolling-caption deduplication.** YouTube's overlapping auto-captions are
  reassembled into a single continuous text without repeated phrases.
- **Paragraph reconstruction.** Hundreds of caption fragments become readable
  paragraphs, split at sentence ends and pauses.
- **Timestamps.** A `[MM:SS]` marker roughly every 45 seconds (configurable),
  placed at paragraph starts. Videos of an hour or more use `[HH:MM:SS]`.
- **Markdown metadata.** YAML frontmatter plus a human-readable header: title,
  channel, upload date, duration, caption language and type, and source URL.
- **Playlist indexes.** `INDEX.md` lists every video with its duration, file
  name and URL, plus any videos that could not be transcribed and why.
- **Combined transcripts.** Optionally merge a whole collection into one
  document with clear boundaries between videos.
- **Configurable output.** Choose the output folder. Existing transcripts are
  never overwritten unless you ask.
- **Safe for large batches.** A private, deleted or caption-less video is
  reported and skipped; the rest of the playlist carries on.

## Requirements

- **Python 3.10 or newer**
- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)**, installed automatically as a
  Python dependency. You do not need a separate `yt-dlp` binary.
- **[pipx](https://pipx.pypa.io/)** (recommended) to install the command in its
  own isolated environment.

No API keys or accounts are needed. The tool only downloads metadata and caption
files, never the video itself.

## Installation

### With pipx (recommended)

pipx installs command-line tools into isolated environments and puts them on
your `PATH`.

**macOS**

```bash
brew install pipx
pipx ensurepath          # then open a new terminal

git clone https://github.com/d4min/yt-transcript.git
cd yt-transcript
pipx install .
```

**Linux / Windows**

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath   # then open a new terminal

git clone https://github.com/d4min/yt-transcript.git
cd yt-transcript
pipx install .
```

Check that it works:

```bash
yt-transcript --version
```

You can also install straight from GitHub without cloning:

```bash
pipx install git+https://github.com/d4min/yt-transcript.git
```

### With a virtual environment

```bash
git clone https://github.com/d4min/yt-transcript.git
cd yt-transcript
python3 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install .
```

The `yt-transcript` command is available while the virtual environment is
active. You can also run the tool as a module with `python -m yt_transcript`.

### Keeping yt-dlp up to date

YouTube changes often, and yt-dlp releases fixes frequently. If downloads start
failing, upgrade the yt-dlp copy inside the tool's environment:

```bash
pipx runpip yt-transcript install --upgrade yt-dlp   # pipx install
pip install --upgrade yt-dlp                         # virtualenv install
```

### Uninstalling

```bash
pipx uninstall yt-transcript
```

## Quick start

```bash
yt-transcript "https://www.youtube.com/watch?v=VIDEO_ID"
```

This creates a `transcripts/` folder in the directory you ran the command from,
containing one file named after the video:

```
transcripts/
└── How I Built My SaaS [VIDEO_ID].md
```

Quote URLs in the shell. Characters such as `?` and `&` otherwise get
interpreted by `zsh` and `bash`.

## Usage

```
yt-transcript [options] URL [URL ...]
```

| Option | Description |
|---|---|
| `URL` | One or more YouTube video or playlist URLs, or bare video IDs. |
| `-o PATH`, `--output PATH` | Directory to write transcripts to. Default: `./transcripts`. `~` is expanded. |
| `--combine` | Also write `combined-transcripts.md`, containing every transcript in the collection. |
| `--timestamp-interval SECONDS` | Approximate number of seconds between timestamps. Default: `45`. |
| `--no-timestamps` | Leave timestamps out entirely. Cannot be combined with `--timestamp-interval`. |
| `--overwrite` | Re-download and replace transcripts that already exist. |
| `-v`, `--verbose` | Show detailed output: chosen caption track, deduplication statistics, yt-dlp messages and full error tracebacks. |
| `--version` | Print the version and exit. |
| `-h`, `--help` | Show help and exit. |

### Supported URLs

| Kind | Examples |
|---|---|
| Video | `https://www.youtube.com/watch?v=ID`, `https://youtu.be/ID`, `https://www.youtube.com/shorts/ID`, `https://www.youtube.com/live/ID`, `https://www.youtube.com/embed/ID`, `https://music.youtube.com/watch?v=ID`, `ID` |
| Playlist | `https://www.youtube.com/playlist?list=PLAYLIST_ID` |

A watch URL that also contains `&list=` is treated as **that single video**. To
transcribe the whole playlist, use the `playlist?list=` form. Channel pages are
not supported.

### Existing files and re-runs

Transcripts are matched to videos by the `video_id` in their frontmatter, not by
file name. Running the same command again therefore skips videos that are
already done, even if you renamed their files, and only fetches what's missing.
Pass `--overwrite` to re-download and replace them in place.

`INDEX.md` and `combined-transcripts.md` are regenerated on every run, so they
always reflect the current collection, including transcripts that were skipped
because they already existed.

### Exit status

| Code | Meaning |
|---|---|
| `0` | Every input was processed (saved, or already existed). |
| `1` | At least one URL was invalid, or a video or playlist could not be processed. Everything else was still written. |
| `2` | Invalid command-line usage. |
| `130` | Interrupted with Ctrl+C. |

## Examples

**A single video**

```bash
yt-transcript "https://www.youtube.com/watch?v=VIDEO_ID"
yt-transcript "https://youtu.be/VIDEO_ID"
```

**A playlist**

```bash
yt-transcript "https://www.youtube.com/playlist?list=PLAYLIST_ID"
```

**Several videos at once** (an `INDEX.md` is written for the batch)

```bash
yt-transcript "https://youtu.be/VIDEO_ID_1" "https://youtu.be/VIDEO_ID_2" "https://youtu.be/VIDEO_ID_3"
```

**A custom output directory**

```bash
yt-transcript "https://youtu.be/VIDEO_ID" --output ~/Documents/research
```

**A combined document for a whole playlist**

```bash
yt-transcript "https://www.youtube.com/playlist?list=PLAYLIST_ID" --combine
```

**Fewer timestamps, or none**

```bash
yt-transcript "https://youtu.be/VIDEO_ID" --timestamp-interval 120
yt-transcript "https://youtu.be/VIDEO_ID" --no-timestamps
```

**Refresh everything and see what's happening**

```bash
yt-transcript "https://www.youtube.com/playlist?list=PLAYLIST_ID" --overwrite --verbose
```

**Videos and playlists together**

```bash
yt-transcript "https://youtu.be/VIDEO_ID" "https://www.youtube.com/playlist?list=PLAYLIST_ID" -o research --combine
```

## Example output

A complete file generated by the tool is in
[`examples/example-transcript.md`](examples/example-transcript.md). The video
behind it is fictional; it was produced from a synthetic auto-caption test
fixture. A transcript made from manual captions looks like this:

```markdown
---
title: "How I Built My SaaS"
channel: "Example Channel"
video_id: "abc123defgh"
url: "https://www.youtube.com/watch?v=abc123defgh"
upload_date: "2026-09-20"
duration: "01:23:45"
language: "English"
transcript_type: "manual"
---

# How I Built My SaaS

**Channel:** Example Channel  
**Published:** 20 September 2026  
**Duration:** 1:23:45  
**Captions:** English, manual  
**Source:** https://www.youtube.com/watch?v=abc123defgh

## Transcript

[00:00:00]

Welcome back. Today we're going to talk about how we built our first product,
what went wrong, and what we would do differently. It took three attempts.

[00:00:46]

The first thing we discovered was that nobody wanted the product we had planned.
So we spent a month talking to customers before writing any more code.
```

### Frontmatter fields

| Field | Description |
|---|---|
| `title` | Video title. |
| `channel` | Channel or uploader name. |
| `video_id` | YouTube video ID, also used to recognise existing transcripts. |
| `url` | Canonical `https://www.youtube.com/watch?v=` URL. |
| `upload_date` | Upload date, `YYYY-MM-DD`. |
| `duration` | Video length, `HH:MM:SS`. |
| `language` | Caption language: `English`, or e.g. `English (en-GB)` for a regional track. |
| `transcript_type` | `manual` for human-made subtitles, `automatic` for YouTube's speech recognition. |

Fields that YouTube doesn't provide are left out rather than filled with
placeholders. Values are double-quoted, so any YAML parser reads them back
exactly.

## How it works

```
YouTube
   ↓
yt-dlp                    metadata and caption track list (no video download)
   ↓
subtitle selection        manual en → manual en-* → automatic en → automatic en-*
   ↓
caption cleanup           WebVTT/SRT parsing, tags, entities, whitespace, Unicode
   ↓
overlap removal           rolling captions, duplicate events, repeated [Music]
   ↓
paragraph reconstruction  sentence ends, pauses and length
   ↓
Markdown                  frontmatter, metadata, timestamps, paragraphs
```

### Subtitle selection

yt-dlp reports every caption track a video has. `yt-transcript` picks, in order:

1. Human-made English subtitles (`en`)
2. Human-made regional English subtitles (`en-US`, then `en-GB`, then others)
3. Automatic English captions
4. Automatic regional English captions

YouTube also offers automatic captions machine-translated into English from
other languages. These are translations, not transcripts, so they are never
used. If a video has no genuine English captions, it is skipped with a message
listing the languages that are available.

### Caption cleanup

Caption files carry a lot that isn't speech: WebVTT headers, `NOTE` and `STYLE`
blocks, cue identifiers and positioning settings, styling tags such as `<c>`,
`<i>` and `<v Speaker>`, per-word timing tags, HTML entities (`&amp;`,
`&nbsp;`), zero-width characters and irregular whitespace. All of it is
removed. Text is Unicode-normalised (NFC), and empty or markup-only cues are
dropped.

### Why rolling captions need deduplication

YouTube's automatic captions are displayed as a two-line "roll-up": each new
cue repeats the previous line, then adds a new one underneath. The raw file
looks like this:

```
00:00:10.000 --> 00:00:12.000
so today we're going to

00:00:12.000 --> 00:00:14.000
so today we're going to
talk about how

00:00:14.000 --> 00:00:16.000
talk about how
to build a business
```

Taken at face value, every phrase appears twice, which doubles the token count
and confuses anything reading the text. `yt-transcript` turns it back into:

```
so today we're going to talk about how to build a business
```

Deduplication is deliberately conservative, because transcript fidelity matters
more than aggressive cleaning:

- A track is only treated as rolling if a substantial share of neighbouring
  cues overlap. Ordinary subtitle tracks are never trimmed this way.
- Whole lines carried over from the previous cue are removed only when they
  match what was just emitted.
- Other overlaps are removed only between cues that follow each other without a
  pause, and only for multi-word overlaps (three or more words, or two when the
  cues touch).
- A single repeated word, or a run of one repeated word ("no no no"), is never
  treated as overlap. Real repetition in speech is kept.
- Text is compared case-insensitively and ignoring punctuation, but it is never
  rewritten. Nothing is removed just because two sentences look similar.

The same pass drops exact duplicate cues shown at overlapping times, and
collapses runs of identical sound annotations such as `[Music] [Music]`.

### Paragraphs and timestamps

The cleaned word stream is grouped into paragraphs of roughly 50–150 words
(about 90 by default). Break points are scored using sentence-ending
punctuation, pauses in the caption timing, speaker-change markers (`>>`) and
cue boundaries, and the best-scoring break near the target length is chosen.
Silences of ten seconds or more always start a new paragraph, so timestamps
stay faithful. Words are joined with single spaces and are never altered.

Manual subtitles usually have punctuation, so their paragraphs end on sentence
boundaries. YouTube's automatic captions often have no punctuation or
capitalisation at all. Those paragraphs are split at pauses instead, and the
text is left unpunctuated rather than having punctuation invented for it.

A timestamp is placed at the start of the first paragraph, and then at the
paragraph starting nearest to every `--timestamp-interval` seconds. Each one is
the actual caption time of that paragraph's first word.

## Output structure

**Individual videos** go straight into the output directory:

```
transcripts/
├── How I Built My SaaS [abc123defgh].md
└── Another Talk [xyz987uvwts].md
```

Passing two or more video URLs together also writes an `INDEX.md` for the
batch (and `combined-transcripts.md` with `--combine`).

**Playlists** get a folder named after the playlist, with files numbered by
playlist position:

```
transcripts/
└── Playlist Name/
    ├── 001 - Video One.md
    ├── 002 - Video Two.md
    ├── 003 - Video Three.md
    ├── INDEX.md
    └── combined-transcripts.md      (with --combine)
```

File names are made safe for macOS, Linux and Windows. Characters such as
`/ \ : * ? " < > |` are removed, overly long titles are shortened, and a
clash with a file that belongs to a different video gets a ` (2)` suffix
rather than overwriting it.

### INDEX.md

```markdown
# Playlist Name

**Videos:** 25  
**Total duration:** 14h 32m  
**Playlist:** https://www.youtube.com/playlist?list=PLAYLIST_ID

## Videos

1. Video One
   - Channel: Example
   - Duration: 42:13
   - Published: 2026-09-20
   - File: `001 - Video One.md`
   - URL: https://www.youtube.com/watch?v=...

2. Video Two
   ...
```

Videos that couldn't be transcribed are listed in an `## Unavailable` section
with the reason. The index never summarises content.

### combined-transcripts.md

```markdown
# Playlist Name

**Videos:** 2  
**Total duration:** 1h 2m

---

## 1. Video One

**Channel:** Example  
**Published:** 20 September 2026  
**Duration:** 42:13  
**Captions:** English, auto-generated  
**Source:** https://www.youtube.com/watch?v=...

### Transcript

[00:00]

...

---

## 2. Video Two

...
```

Each video is a numbered `##` section with its own metadata, separated by
horizontal rules, so it's always clear which source a passage came from.
Individual transcript files are still written as well.

## Development

```bash
git clone https://github.com/d4min/yt-transcript.git
cd yt-transcript
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs the package in editable mode with `pytest`, `pytest-cov` and
`pyyaml` (used to check that generated frontmatter is valid YAML).

Project layout:

```
src/yt_transcript/
├── cli.py         argument parsing, logging, exit codes
├── pipeline.py    turns inputs into files; per-video error handling
├── youtube.py     URL parsing, caption track selection, yt-dlp wrapper
├── captions.py    WebVTT/SRT parsing, cleanup, deduplication, paragraphs
├── formatter.py   Markdown rendering for transcripts, indexes and combined files
├── output.py      safe file names, existing-file detection, atomic writes
└── models.py      shared dataclasses
tests/
├── fixtures/      synthetic WebVTT/SRT caption files
└── test_*.py
```

## Testing

```bash
pytest
```

The default test run is fully offline. yt-dlp and the network are replaced with
fakes, so it is fast and deterministic.

With coverage:

```bash
pytest --cov --cov-report=term-missing
pytest --cov --cov-report=html      # writes htmlcov/index.html
```

A small set of live tests downloads a real video from YouTube. They are
deselected by default; run them explicitly:

```bash
pytest -m network
```

## Limitations

- **Captions must already exist.** The tool reads YouTube's captions. There is
  no speech-to-text fallback, so videos without English captions are skipped.
- **Automatic captions contain recognition errors.** Misheard words, missing
  punctuation and odd capitalisation are passed through unchanged. This tool
  does not improve the accuracy of the underlying transcription.
- **English only** for now.
- **Private, members-only, age-restricted or region-locked videos** may fail,
  because no login or cookies are used.
- **Speaker names are not identified.** Voice tags in caption files are removed,
  and `>>` speaker-change markers are kept as they appear.
- **Paragraphs are a best effort.** Breaks follow deterministic rules rather
  than meaning, and are especially approximate for unpunctuated auto-captions.
- **YouTube changes.** Retrieval depends on yt-dlp keeping up with YouTube. See
  [Keeping yt-dlp up to date](#keeping-yt-dlp-up-to-date).

## Troubleshooting

**`No English captions are available (available: de, fr)`**
The video has no human-made or speech-recognised English captions. Translated
captions are deliberately not used.

**`Sign in to confirm you're not a bot`, HTTP 403 or 429 errors**
YouTube is rate-limiting or blocking requests. Wait a while, try a smaller
batch, and make sure yt-dlp is up to date.

**Warnings about a missing JavaScript runtime** (shown with `--verbose`)
Recent yt-dlp versions recommend a JavaScript runtime such as
[Deno](https://deno.com/) for full YouTube support. Caption downloads usually
work without one, but installing Deno (`brew install deno` on macOS) can help
if videos start failing.

**`zsh: no matches found`**
Put the URL in quotes.

Use `--verbose` to see which caption track was chosen, how much text was
deduplicated, yt-dlp's own messages, and full tracebacks for unexpected errors.

## Contributing

Bug reports and pull requests are welcome.

- For caption-processing problems, please include the video URL (or a small
  excerpt of the caption file) and the output you expected.
- Run `pytest` before opening a pull request, and add tests for behaviour you
  change. Caption-processing changes should come with a fixture showing the
  case they handle.
- Keep changes conservative. The project's guiding rule is that the transcript
  is never rewritten, only cleaned.

## License

[MIT](LICENSE)
