# Quran Video Maker — Web App Design

## Overview

Turn the existing two-script CLI pipeline into a single-page local web app. The user drags in an MP3, picks a surah and translation, and gets back an MP4 with Arabic + English subtitles.

**Scope:** Local-only Flask app running at `localhost:5000`. Single user.

## Current Pipeline

1. User manually creates an SRT (via Whisper externally)
2. `add_translation.py` — matches SRT blocks to verses, produces a translated SRT with Arabic + English lines
3. `quran_video.py` — takes MP3 + translated SRT, generates ASS subtitles, runs FFmpeg to produce MP4

## New Pipeline

All steps automated. User provides only an MP3 file and a surah number.

```
MP3 + surah number + settings
    │
    ▼
1. Upload MP3 → save to output/<job_id>/
    │
    ▼
2. Run faster-whisper on MP3 → generate SRT
    │
    ▼
3. Fetch translation from quran.com API         ─┐
   GET /api/v4/verses/by_chapter/{chapter}       │ can run
     ?translations={id}&per_page=300             │ in parallel
    │                                             │
4. Fetch word-by-word data from quran.com API   ─┘
   (reuses existing load_word_data, cached)
    │
    ▼
5. Match SRT blocks → verses → build translated SRT
   (existing add_translation.py logic)
    │
    ▼
6. Generate ASS subtitles + run FFmpeg → MP4
   (existing quran_video.py logic)
    │
    ▼
7. Stream MP4 back to browser for download
```

## Architecture

### File Structure

```
QuranVideoMaker/
├── app.py                  # Flask app — routes, SSE, pipeline orchestration
├── add_translation.py      # existing, no changes
├── quran_video.py          # existing, no changes
├── templates/
│   └── index.html          # single-page UI
├── static/
│   └── style.css           # dark theme styling
└── output/                 # temp dir for job files (auto-cleaned)
```

### Key Principle

No changes to existing scripts. `app.py` imports their public functions directly and orchestrates the pipeline.

### Dependencies

New pip dependencies:

- `flask` — web framework
- `faster-whisper` — Whisper STT (uses CTranslate2, CUDA if available)

Everything else is stdlib (`json`, `urllib`, `re`, `threading`, `uuid`, `queue`) or already required (FFmpeg in PATH).

## Translation Fetching

New code in `app.py` replaces the manual `translation.txt` file. Uses the quran.com v4 API:

```
GET /api/v4/verses/by_chapter/{chapter}?translations={id}&language=en&per_page=300
```

Translation IDs:
- Sahih International: 20
- M.A.S. Abdel Haleem: 85

Note: The Clear Quran (Khattab, ID 131) is not available via the quran.com API.

The response provides Arabic text + English translation per verse — the same data `parse_translation_file` currently reads from disk. `app.py` transforms the API response into the same list-of-dicts format that the existing code expects.

Word-by-word data reuses the existing `load_word_data()` function (cached as `wbw_{chapter}.json`).

## UI Design

Single page, dark theme. Minimal layout:

```
┌─────────────────────────────────────────────┐
│           Quran Video Maker                 │
│                                             │
│  ┌───────────────────────────────────┐      │
│  │                                   │      │
│  │     Drop MP3 here or click        │      │
│  │         to browse                 │      │
│  │                                   │      │
│  └───────────────────────────────────┘      │
│                                             │
│  Surah:  [ 12 - Yusuf          ▼ ]         │
│  Translation: [ The Clear Quran ▼ ]         │
│  Resolution:  [ 1920x1080      ▼ ]         │
│                                             │
│  [ Generate Video ]                         │
│                                             │
│  ┌───────────────────────────────────┐      │
│  │ ✓ Transcribing audio...     done  │      │
│  │ ✓ Fetching translation...   done  │      │
│  │ ● Generating video...       72%   │      │
│  └───────────────────────────────────┘      │
│                                             │
│  [ Download MP4 ]  (appears when done)      │
└─────────────────────────────────────────────┘
```

### Controls

- **Surah dropdown:** All 114 surahs with number + Arabic/English name (hardcoded list)
- **Translation dropdown:** "Sahih International" (default), "Abdel Haleem"
- **Translation file upload (optional):** Upload a custom translation.txt file to override the API dropdown (e.g. The Clear Quran). Uses the same format as the CLI tool.
- **Resolution dropdown:** 1280x720, 1920x1080 (default), 3840x2160
- **Generate button:** Disabled while processing
- **Download button:** Appears only when MP4 is ready

## Progress & Error Handling

### SSE (Server-Sent Events)

- Client opens `EventSource` to `/progress/<job_id>` after submitting the form
- Backend sends JSON events:
  - `{"step": "whisper", "status": "running", "detail": "Transcribing audio..."}`
  - `{"step": "ffmpeg", "status": "running", "detail": "Encoding video...", "percent": 45}`
  - `{"step": "done", "download_url": "/download/<job_id>"}`
  - `{"step": "error", "detail": "FFmpeg failed: ..."}`
- UI shows each step with a spinner (running) or checkmark (done)
- FFmpeg progress: parse stderr for frame count to show percentage

### Error Cases

| Error | User sees |
|-------|-----------|
| Bad/unsupported audio | "Whisper failed: unsupported audio format" |
| quran.com API unreachable | "Could not fetch translation — check internet connection" |
| FFmpeg fails | FFmpeg's stderr shown in progress log |
| Invalid surah | Prevented by dropdown (can't pick invalid) |

### Threading

- Pipeline runs in a background thread so Flask stays responsive
- Progress updates go through a `queue.Queue` that the SSE route reads from

### Cleanup

- All job files go into `output/<job_id>/` (MP3 upload, SRT, ASS, MP4)
- Files cleaned up after download, or after 1 hour if never downloaded
- Job ID is a UUID

## Startup

```bash
python app.py
```

Opens the browser to `http://localhost:5000`.
