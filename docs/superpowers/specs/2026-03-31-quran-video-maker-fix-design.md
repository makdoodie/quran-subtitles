# Quran Video Maker — Fix Design

## Overview

Fix the Quran Video Maker project so it reliably generates an MP4 video from an MP3 recitation, a Whisper-generated SRT, and a quran.com translation file. The video has a black background with white Arabic text (top) and white English text (bottom), synchronized to the audio.

## Current Problems

1. **Video sync is broken**: `quran_video.py` pairs raw SRT timestamps (one per Whisper phrase, ~300+ blocks) with translations (one per verse, ~111 entries) in a 1:1 mapping. All translations get crammed into the first third of the audio.
2. **Verse splitting produces orphans**: `add_translation.py` splits translations only at commas, producing tiny fragments like `"All-Wise."` as standalone subtitle blocks.
3. **Font is generic**: The ASS subtitle file uses Arial. User wants Times New Roman (English) and Traditional Arabic (Arabic).
4. **No ayah numbers**: No visual indicator of where each verse begins.
5. **Resolution is hardcoded**: 1280x720 with no way to change it.

## Pipeline

Two-step pipeline. Each script has a single clear responsibility:

1. **`add_translation.py`** — Takes a Whisper SRT + quran.com translation TXT. Matches SRT blocks to verses via fuzzy Arabic matching. Outputs a translated SRT where each block has Arabic text (line 1) and English text (line 2), with timestamps spanning the correct audio range.
2. **`quran_video.py`** — Takes an MP3 + the translated SRT from step 1. Generates an ASS subtitle file and renders the final MP4 via FFmpeg.

## Fix 1: Verse Splitting (`add_translation.py`)

### Current behavior
- Splits translation text at commas only
- Number of output blocks = min(SRT blocks for that verse, comma-separated segments)
- No minimum segment length enforcement

### New behavior
- Split at commas **and** sentence boundaries (`.` `!` `?` followed by a space or end-of-string)
- After splitting, enforce a **minimum segment length of 5 words**
- If a segment has fewer than 5 words, merge it into the previous segment
- This prevents orphans like `"All-Wise."` from appearing as standalone subtitles

### Ayah numbers in translated SRT output
- The first subtitle block of each verse includes the verse number inline:
  - Arabic line: prefixed with the Arabic-Indic numeral (e.g., `٤` for verse 4)
  - English line: prefixed with the Western numeral and period (e.g., `4.`)
- Subsequent blocks of the same verse have no number prefix
- The verse number is derived from the verse reference (e.g., `12:4` yields verse number `4`)

## Fix 2: Video Sync (`quran_video.py`)

### Current behavior
- Accepts: `<audio.mp3> <translation.txt> <whisper.srt>`
- Parses raw SRT for timestamps and translation TXT for English text
- Pairs them 1:1 — completely broken when counts don't match

### New behavior
- Accepts: `<audio.mp3> <translated.srt> [output.mp4] [--resolution WxH]`
- Parses the translated SRT (output of `add_translation.py`), which already contains:
  - Correct start/end timestamps per block
  - Arabic text (line 1 of each block's text)
  - English text (line 2 of each block's text)
- No verse matching logic needed — just reads and renders

## Fix 3: Font & Layout

### ASS subtitle styles
Two styles in the ASS file:

| Property       | Arabic style          | English style       |
|----------------|-----------------------|---------------------|
| Font           | Traditional Arabic    | Times New Roman     |
| Alignment      | Top-center (8)        | Bottom-center (2)   |
| Color          | White (`&H00FFFFFF`)  | White (`&H00FFFFFF`)|
| Outline/shadow | None                  | None                |

Each translated SRT block produces two ASS dialogue lines with the same start/end time:
- One using the Arabic style (top)
- One using the English style (bottom)

Font sizes will be scaled proportionally to resolution. At 1920x1080: Arabic ~44, English ~40. At 1280x720: Arabic ~30, English ~27.

## Fix 4: Resolution

- Default resolution: **1920x1080**
- Configurable via `--resolution WxH` CLI argument (e.g., `--resolution 1280x720`)
- Resolution affects: FFmpeg video dimensions, ASS PlayResX/PlayResY, font sizes, margins, and wrap width

## CLI Usage After Fix

```bash
# Step 1: Generate translated SRT
python add_translation.py "surah yusuf translation.txt" "surah yusuf.srt"
# Outputs: "surah yusuf translated.srt"

# Step 2: Generate video
python quran_video.py "surah yusuf.mp3" "surah yusuf translated.srt" "surah yusuf.mp4"
# Or with custom resolution:
python quran_video.py "surah yusuf.mp3" "surah yusuf translated.srt" "surah yusuf.mp4" --resolution 1280x720
```

## Out of Scope

- Arabic font selection UI or configuration
- Subtitle color/style customization
- Multiple translation language support
- Progress bar or chapter markers in the video
