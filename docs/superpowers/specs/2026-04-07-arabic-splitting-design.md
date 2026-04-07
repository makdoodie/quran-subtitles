# Arabic Subtitle Splitting Design

## Problem

When a Quran verse spans multiple SRT time segments, the video displays the **full verse Arabic** for every segment instead of showing only the Arabic words being recited in that segment. The English translation is correctly split across segments, but the Arabic is not.

**Root cause:** `build_output()` in `add_translation.py` (line 587) unconditionally replaces the per-block Arabic with the full `verse_arabic` for every block in a verse group.

## Solution

Split the Arabic text across blocks using the same word-range data already computed for English splitting, with a fallback chain when word-by-word data is unavailable.

## Changes

### 1. `load_word_data()` — return raw Arabic alongside normalized

**Current:** Returns `dict[int, list[tuple[str, str]]]` — `verse_num -> [(norm_arabic, english)]`

**New:** Returns `dict[int, list[tuple[str, str, str]]]` — `verse_num -> [(raw_arabic, norm_arabic, english)]`

The raw Arabic (`text_uthmani`) is already stored in the JSON cache. The only change is to stop discarding it when building the result dict. The `raw_arabic` preserves full diacritics needed for display.

All consumers of `verse_words` tuples must be updated for the new 3-tuple shape.

### 2. `build_verse_blocks()` — compute Arabic slice per block

**New parameter:** `verse_arabic: str` — the full polished Arabic text for the verse (used in proportional fallback).

**New parameter:** `ayah_num: int` — for warning messages.

**Arabic splitting priority chain:**

1. **Word-by-word (primary):** If `word_ranges[i]` is not None and `verse_words` has raw Arabic, join `raw_arabic_words[start:end]` with spaces. This gives exact word-boundary splitting with full diacritics.

2. **Proportional fallback:** If word ranges are unavailable, split `verse_arabic` at space boundaries using the existing Arabic character-length fractions (`ar_lens`, `cum_ar`, `total_ar`). Find the nearest space to the computed character position. Print: `WARNING: Using proportional Arabic split for block {i+1}/{n} of verse {ayah_num}`

3. **Whisper fallback:** If proportional splitting fails (e.g., `verse_arabic` is empty), use `b['text']` (Whisper's transcription). Print: `WARNING: Using Whisper Arabic fallback for block {i+1}/{n} of verse {ayah_num}`

**Return type unchanged:** `list[tuple[str, str, str, str]]` — `(start, end, arabic, english)`, but `arabic` is now the correct slice rather than Whisper's raw transcription.

**Single-block verses:** No splitting needed. Return `verse_arabic` (or the full word-by-word joined text) as-is. This is the existing behavior and requires no fallback.

### 3. `build_output()` — use Arabic from `build_verse_blocks()`

**Current behavior (broken):**
```python
for idx_in_verse, (start, end, _whisper_arabic, english) in enumerate(merged):
    arabic = verse_arabic  # always full verse
```

**New behavior:**
```python
for idx_in_verse, (start, end, arabic, english) in enumerate(merged):
    # arabic is already the correct slice from build_verse_blocks()
```

- Pass `verse_arabic` and `ayah_num` into `build_verse_blocks()` so it can use them for splitting and fallback warnings
- Stop overwriting the Arabic returned by `build_verse_blocks()`
- Still prepend verse number (Arabic-Indic numeral) to the first block only
- Still prepend English verse number to first block's English only

### 4. Callers of `build_verse_blocks()` — updated signatures

The function gains two new parameters (`verse_arabic`, `ayah_num`). Both call sites in `build_output()` already have these values available. No other callers exist.

## What stays the same

- **English splitting logic** — completely untouched
- **`match_blocks_to_verses()`** — untouched
- **`normalize_arabic()` and all Arabic text processing** — untouched
- **`write_ass()` / `quran_video.py`** — untouched (consumes the same `(start_ms, end_ms, arabic, english)` tuples)
- **Web app routing, SSE progress, FFmpeg pipeline** — untouched
- **Cache format** — the JSON files already store raw `text_uthmani`; no migration needed

## Affected files

- `add_translation.py` — `load_word_data()`, `build_verse_blocks()`, `build_output()`
- No other files need changes

## Warning behavior

Warnings are printed to stdout/stderr so they appear in:
- CLI: terminal output
- Web app: server console logs (visible to the developer running the server)

No user-facing error in the web UI — the fallbacks produce reasonable output. The warnings are for the developer to know when word-by-word data quality degrades.
