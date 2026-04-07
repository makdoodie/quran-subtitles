# Quran Video Maker — Progress

## What We Built

Converted a two-script CLI pipeline into a local Flask web app at `localhost:5000`.

**Original CLI flow:**
1. User manually runs Whisper externally → gets `.srt`
2. `add_translation.py` — matches SRT blocks to verses, splits English
3. `quran_video.py` — generates ASS subtitles, runs FFmpeg → MP4

**New web app flow:**
1. User drags MP3 into browser, picks surah + resolution
2. faster-whisper runs automatically → SRT
3. quran.com API fetches Arabic + Sahih International translation
4. Matching + English splitting runs (same logic, improved)
5. ASS + FFmpeg → MP4 streamed back for download

---

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask app — routes, SSE progress, pipeline orchestration, `fetch_translation()` |
| `templates/index.html` | Single-page UI — drag-drop, dropdowns, progress log |
| `static/style.css` | Dark theme |
| `requirements.txt` | `flask`, `faster-whisper` |
| `add_translation.py` | Core matching + splitting logic (modified throughout) |
| `quran_video.py` | ASS generation + FFmpeg (unchanged) |

---

## Bugs Fixed (in order)

### Web app infrastructure
- **FFmpeg path escaping** — `C\:/path` escaping for Windows drive letters broke in FFmpeg 8.0. Fixed by using relative paths + `cwd=job_dir` so there's no drive letter to escape.
- **FFmpeg stderr hidden** — error was truncated at first 500 chars (FFmpeg version banner), hiding the real error. Fixed: show last 1500 chars + drain stderr in background thread to prevent pipe buffer deadlock on long videos.
- **XSS in `showError()`** — was using `innerHTML` with server error strings. Fixed to use `textContent`.
- **File re-selection broken** — `setFile()` was calling `dropZone.textContent = name` which destroyed the hidden `<input>` child. Fixed to remove only text nodes, preserving the input.

### Subtitle logic
- **Arabic numbers on both ends** — `verse_arabic` from the API/file already has a trailing Arabic-Indic digit (e.g. `١`). Prepending another one gave `١ ... ١`. Fixed: strip trailing `[\u0660-\u0669]` before prepending.
- **Sahih International bracket splitting** — SI uses `[They said],` style where `,` after `]` was creating spurious `punct_breaks`, pulling splits to wrong positions. Fixed: skip punct_breaks where `translation[i-1] == ']'`.
- **ASS grouping (blocks dropped)** — `parse_translated_srt` hard-coded `lines[3]` as English. With full verse Arabic now on each block, any embedded `\n` from the API shifted line indices, causing blocks to be dropped silently. Fixed two ways:
  - **Option C** — sanitize `\n`/`\r` out of arabic/english before writing SRT
  - **Option B** — `build_output(return_segments=True)` returns in-memory `(start_ms, end_ms, arabic, english)` tuples directly; `parse_translated_srt` is never called in the web app pipeline

### Content quality
- **Arabic from Whisper** — Whisper-transcribed Arabic is noisy, missing diacritics, sometimes hallucinated. Fixed: `build_output` now uses `verses[vi]['arabic']` (polished, diacriticized Arabic from the translation source) for every subtitle card. Whisper is used only for timing.
- **Whisper quality** — `base` model + default params produced hallucinations. Changed to `medium` model with `temperature=0`, `vad_filter=True`, `condition_on_previous_text=False`.

---

## Current State

The web app runs end-to-end:
- `python app.py` → browser opens at `localhost:5000`
- Drop MP3, pick surah, click Generate
- Progress log shows: Transcribing → Fetching translation → Matching → Generating video
- Download MP4 when done

Translation is Sahih International (ID 20) by default. Custom `.txt` upload still supported for other translations (e.g. The Clear Quran).

---

## Known Remaining Issues / Next Steps

- **Whisper timing imprecision** — medium model helps but long verses can still produce blocks with misaligned timestamps. No post-processing validation yet for blocks where English is disproportionately long vs block duration.
- **Word-by-word cache** — `wbw_{chapter}.json` is cached beside the scripts. If the app is run from a different working directory the cache might not be found (uses `os.path.abspath(__file__)`). Should be fine for normal usage.
- **No progress bar for Whisper** — faster-whisper doesn't expose per-segment progress easily; the UI shows a spinner with no percentage for the transcription step.
- **Job cleanup only on new generate** — `cleanup_old_jobs()` runs only when `/generate` is called. Files from a session where the user never returned persist until the next job. A background timer thread would be cleaner.
- **Single user / no auth** — by design (local only). Fine as-is.
