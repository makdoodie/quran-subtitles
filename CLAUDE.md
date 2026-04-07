# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Quran Video Maker generates MP4 videos of Quran recitations with Arabic and English subtitles on a black background. It has two interfaces:

- **Web app** (`python app.py`): Flask server at localhost:5000. Drag-drop MP3, pick surah/resolution, get MP4. This is the primary interface.
- **CLI**: Two-step manual pipeline (`add_translation.py` then `quran_video.py`). Mostly superseded by the web app.

## Running

```bash
pip install -r requirements.txt   # flask, faster-whisper
python app.py                     # opens browser to localhost:5000
```

Requires FFmpeg in PATH with libass support and Python 3.9+.

## Architecture

The pipeline has four stages, orchestrated by `run_pipeline()` in `app.py`:

1. **Whisper transcription** (`faster-whisper`, medium model) — transcribes MP3 to SRT. Used only for timing, not Arabic text quality.
2. **Translation fetch** — gets Arabic (Uthmani script) + Sahih International English from quran.com API (`fetch_translation()` in `app.py`). Alternatively accepts a user-uploaded `.txt` file parsed by `parse_translation_file()` in `add_translation.py`.
3. **Matching** (`add_translation.py`) — `match_blocks_to_verses()` fuzzy-matches Whisper SRT blocks to verses using normalized Arabic. `build_output()` assembles final subtitle blocks with polished Arabic from the API (not Whisper) and English split across blocks using word-by-word API data for positioning.
4. **Video generation** (`quran_video.py`) — `write_ass()` creates ASS subtitles (Traditional Arabic + Times New Roman fonts), then FFmpeg composites them over a black background with the audio.

### Key data flow in web app

`app.py:run_pipeline()` calls `build_output(return_segments=True)` which returns `(srt_string, segments)` — the segments list of `(start_ms, end_ms, arabic, english)` tuples goes directly to `write_ass()`, bypassing SRT re-parsing.

### Arabic text processing

`add_translation.py` has extensive Arabic normalization (`normalize_arabic()`) that strips diacritics, normalizes alef variants, removes Quranic markers, etc. This is critical for fuzzy matching between Whisper output and API text.

### Word-by-word data

`load_word_data()` fetches per-word Arabic + English from quran.com API, cached as `wbw_{chapter}.json`. Used by `build_verse_blocks()` to anchor English translation split points to actual Arabic word boundaries rather than proportional character splitting.

### Translation splitting

`build_verse_blocks()` splits English translations across multiple SRT blocks for a single verse. It uses a priority chain: word-by-word anchoring > character-level fuzzy matching > proportional fallback. Punctuation breaks (commas, periods) are preferred split points, with editorial bracket content (`[They said],`) skipped.

## Important conventions

- FFmpeg commands in the web app use **relative paths + `cwd=job_dir`** to avoid Windows drive-letter colon escaping issues (broke in FFmpeg 8.0).
- FFmpeg stderr is drained in a background thread to prevent pipe buffer deadlock on long videos.
- The web app sends progress via **SSE** (Server-Sent Events) to `/progress/<job_id>`.
- Jobs are stored in-memory (`jobs` dict) and cleaned up when a new `/generate` request arrives (max age 1 hour).
- `showError()` in the frontend uses `textContent` (not `innerHTML`) to prevent XSS.
