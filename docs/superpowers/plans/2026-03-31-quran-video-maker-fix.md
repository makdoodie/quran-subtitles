# Quran Video Maker Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix verse splitting, video sync, fonts, ayah numbers, and resolution config so the two-step pipeline (add_translation.py -> quran_video.py) produces a correctly synchronized Quran video.

**Architecture:** Two independent scripts. `add_translation.py` matches Whisper SRT blocks to verses and outputs a translated SRT with Arabic + English per block. `quran_video.py` reads that translated SRT + an MP3 and renders an MP4 via FFmpeg with dual-font ASS subtitles.

**Tech Stack:** Python 3.10, FFmpeg (with libass), standard library only (re, sys, os, textwrap, subprocess, difflib, argparse).

---

### Task 1: Fix verse splitting in `add_translation.py`

**Files:**
- Modify: `add_translation.py:184-230` (the `build_verse_blocks` function)

The current `build_verse_blocks` splits only at commas. We need to split at commas AND sentence boundaries, then merge short orphan segments (<5 words) back into the previous segment.

- [ ] **Step 1: Replace the `build_verse_blocks` function**

In `add_translation.py`, replace the `build_verse_blocks` function (lines 184-230) with:

```python
def split_translation(translation):
    """Split translation at commas and sentence boundaries (.!? followed by space/end).

    Returns a list of text segments. Segments that are too short (<5 words)
    are merged into the previous segment to avoid orphans.
    """
    # Split at commas and sentence-ending punctuation, keeping delimiter with preceding text
    # Pattern: split after , or .!? when followed by a space or end-of-string
    raw_parts = re.split(r'(?<=[,.\!\?])\s+', translation)
    raw_parts = [p.strip() for p in raw_parts if p.strip()]

    if not raw_parts:
        return [translation]

    # Merge short segments (<5 words) into the previous segment
    MIN_WORDS = 5
    merged = [raw_parts[0]]
    for part in raw_parts[1:]:
        if len(part.split()) < MIN_WORDS and merged:
            merged[-1] = merged[-1] + ' ' + part
        else:
            merged.append(part)

    return merged if merged else [translation]


def build_verse_blocks(srt_blocks, translation):
    """Given a verse's SRT blocks and its translation, produce output blocks.

    Splits at commas and sentence boundaries, merges short orphan segments,
    then distributes SRT blocks across translation segments.

    Returns list of (start, end, arabic, english).
    """
    if not srt_blocks:
        return []

    segments = split_translation(translation)

    n_blocks = len(srt_blocks)
    n_segs = len(segments)

    # The number of output subtitle blocks = min(srt blocks, translation segments)
    n_out = min(n_blocks, n_segs)
    n_out = max(n_out, 1)

    block_groups = distribute(srt_blocks, n_out)
    seg_groups = distribute(segments, n_out)

    results = []
    for bg, sg in zip(block_groups, seg_groups):
        if not bg:
            continue
        start = ts_start(bg[0]['timestamp'])
        end = ts_end(bg[-1]['timestamp'])
        arabic = ' '.join(b['text'] for b in bg)
        english = ' '.join(sg)
        results.append((start, end, arabic, english))

    return results
```

- [ ] **Step 2: Verify the fix handles the known orphan case**

The problematic verse 12:6 translation is:
```
And so will your Lord choose you ˹O Joseph˺, and teach you the interpretation of dreams, and perfect His favour upon you and the descendants of Jacob—˹just˺ as He once perfected it upon your forefathers, Abraham and Isaac. Surely your Lord is All-Knowing, All-Wise."
```

With the new logic:
- `re.split(r'(?<=[,.\!\?])\s+', text)` splits this into segments at each comma and after "Isaac."
- The segment `'All-Wise."'` has only 1 word — below the 5-word minimum
- It gets merged back into the previous segment: `'All-Knowing, All-Wise."'`
- That combined segment is still only 2 words, so it merges further into `'Surely your Lord is All-Knowing, All-Wise."'`

Run the script to verify:
```bash
python add_translation.py "surah yusuf translation.txt" "surah yusuf.srt" "test_output.srt"
```

Check that the output no longer has a standalone `All-Wise."` block. Look at blocks around timestamp 01:16-01:28 in the output.

- [ ] **Step 3: Commit**

```bash
git add add_translation.py
git commit -m "fix: split translations at sentence boundaries and merge short orphans"
```

---

### Task 2: Add ayah numbers to translated SRT output

**Files:**
- Modify: `add_translation.py:235-262` (the `build_output` function)

Add verse numbers inline: Arabic-Indic numeral prefix on the Arabic line, Western numeral prefix on the English line. Only on the first subtitle block of each verse.

- [ ] **Step 1: Add a helper to convert Western digits to Arabic-Indic digits**

Add this function above `build_output` in `add_translation.py`:

```python
def to_arabic_numeral(n):
    """Convert an integer to Arabic-Indic numeral string (e.g., 4 -> '٤')."""
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    return ''.join(arabic_digits[int(d)] for d in str(n))
```

- [ ] **Step 2: Modify `build_output` to inject ayah numbers**

Replace the `build_output` function with:

```python
def build_output(blocks, verses, assignments):
    """Assemble the final SRT string with ayah numbers on first block of each verse."""
    # Group consecutive SRT blocks by their verse
    verse_block_groups = []
    prev_vi = None
    for i, vi in enumerate(assignments):
        if vi != prev_vi:
            verse_block_groups.append((vi, []))
            prev_vi = vi
        verse_block_groups[-1][1].append(blocks[i])

    # Build output blocks
    all_output = []
    for vi, vblocks in verse_block_groups:
        translation = verses[vi]['translation']
        merged = build_verse_blocks(vblocks, translation)
        # Extract verse number from ref (e.g., "12:4" -> 4)
        verse_num = int(verses[vi]['ref'].split(':')[1])
        for idx_in_verse, (start, end, arabic, english) in enumerate(merged):
            if idx_in_verse == 0:
                # First block of this verse: prepend ayah numbers
                arabic = f"{to_arabic_numeral(verse_num)} {arabic}"
                english = f"{verse_num}. {english}"
            all_output.append((start, end, arabic, english))

    # Format as SRT
    lines = []
    for idx, (start, end, arabic, english) in enumerate(all_output, 1):
        lines.append(str(idx))
        lines.append(f'{start} --> {end}')
        lines.append(arabic)
        lines.append(english)
        lines.append('')

    return '\n'.join(lines)
```

- [ ] **Step 3: Run and verify ayah numbers appear**

```bash
python add_translation.py "surah yusuf translation.txt" "surah yusuf.srt" "test_output.srt"
```

Open `test_output.srt` and verify:
- Block 1 Arabic starts with `١` (Arabic-Indic 1)
- Block 1 English starts with `1.`
- When a verse spans multiple blocks, only the first block has the number
- Block 13 (verse 7) Arabic starts with `٧`, English starts with `7.`

- [ ] **Step 4: Commit**

```bash
git add add_translation.py
git commit -m "feat: add inline ayah numbers to translated SRT output"
```

---

### Task 3: Rewrite `quran_video.py` to consume translated SRT

**Files:**
- Modify: `quran_video.py` (full rewrite of parser and main function, keep time helpers and FFmpeg helpers)

The script currently takes 3 inputs (mp3, translation txt, whisper srt) and pairs them 1:1. Rewrite it to take 2 inputs (mp3, translated srt) and parse Arabic + English from each SRT block.

- [ ] **Step 1: Replace the file parsers section**

Remove the `parse_srt`, `_ARABIC_RE`, `_REF_RE`, and `parse_translations` functions (lines 44-98). Replace with:

```python
def parse_translated_srt(path: str) -> list[tuple[int, int, str, str]]:
    """Parse a translated SRT file with Arabic (line 1) and English (line 2) per block.

    Returns list of (start_ms, end_ms, arabic, english).
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    segments: list[tuple[int, int, str, str]] = []

    for raw in re.split(r"\n\s*\n", text.strip()):
        lines = raw.strip().split("\n")
        if len(lines) < 4:
            continue
        # lines[0] = index, lines[1] = timestamp, lines[2] = arabic, lines[3] = english
        ts_match = re.match(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
            lines[1].strip(),
        )
        if not ts_match:
            continue
        start_ms = srt_to_ms(ts_match.group(1))
        end_ms = srt_to_ms(ts_match.group(2))
        arabic = lines[2].strip()
        english = lines[3].strip()
        segments.append((start_ms, end_ms, arabic, english))

    return segments
```

- [ ] **Step 2: Replace the `write_ass` function with dual-style version**

Replace the entire `write_ass` function and its helpers (`_wrap_ass`, `_esc_ass`) with:

```python
def _wrap_ass(text: str, width: int) -> str:
    r"""Word-wrap text, joining lines with the ASS hard line-break marker \N."""
    return r"\N".join(textwrap.wrap(text, width=width))


def _esc_ass(text: str) -> str:
    """Escape characters that have special meaning inside ASS dialogue text."""
    return text.replace("{", r"\{").replace("}", r"\}")


def write_ass(
    segments: list[tuple[int, int, str, str]],
    out_path: str,
    *,
    res: tuple[int, int] = (1920, 1080),
) -> None:
    """Write an ASS v4+ subtitle file with Arabic (top) and English (bottom) styles.

    segments: list of (start_ms, end_ms, arabic, english)
    """
    W, H = res
    # Scale font sizes proportionally to resolution height
    ar_font_size = round(44 * H / 1080)
    en_font_size = round(40 * H / 1080)
    margin = round(60 * H / 1080)
    en_wrap_width = round(52 * W / 1920)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {W}\n"
        f"PlayResY: {H}\n"
        "WrapStyle: 1\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Arabic style: top-center (Alignment=8), Traditional Arabic font
        f"Style: Arabic,Traditional Arabic,{ar_font_size},"
        "&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,0,0,8,{margin},{margin},{margin},1\n"
        # English style: bottom-center (Alignment=2), Times New Roman font
        f"Style: English,Times New Roman,{en_font_size},"
        "&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,0,0,2,{margin},{margin},{margin},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, "
        "MarginL, MarginR, MarginV, Effect, Text\n"
    )

    event_lines: list[str] = []
    for start_ms, end_ms, arabic, english in segments:
        start = ms_to_ass(start_ms)
        end = ms_to_ass(end_ms)
        ar_text = _esc_ass(arabic)
        en_text = _esc_ass(_wrap_ass(english, en_wrap_width))
        event_lines.append(
            f"Dialogue: 0,{start},{end},Arabic,,0,0,0,,{ar_text}"
        )
        event_lines.append(
            f"Dialogue: 0,{start},{end},English,,0,0,0,,{en_text}"
        )

    Path(out_path).write_text(
        header + "\n".join(event_lines) + "\n",
        encoding="utf-8-sig",
    )
```

- [ ] **Step 3: Replace the `main` function with new CLI**

Replace the entire `main` function with:

```python
def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a Quran recitation MP4 from an MP3 and translated SRT."
    )
    parser.add_argument("mp3", help="Path to the recitation MP3 audio file")
    parser.add_argument("srt", help="Path to the translated SRT file (from add_translation.py)")
    parser.add_argument("output", nargs="?", default="output.mp4", help="Output MP4 path (default: output.mp4)")
    parser.add_argument("--resolution", default="1920x1080", help="Video resolution as WxH (default: 1920x1080)")
    args = parser.parse_args()

    # Parse resolution
    try:
        w, h = args.resolution.lower().split("x")
        res = (int(w), int(h))
    except ValueError:
        print(f"ERROR: Invalid resolution format '{args.resolution}'. Use WxH, e.g. 1920x1080")
        sys.exit(1)

    print("Parsing translated SRT ...")
    segments = parse_translated_srt(args.srt)
    print(f"  Found {len(segments)} subtitle blocks")

    if not segments:
        print("ERROR: No subtitle blocks found in SRT file.")
        sys.exit(1)

    ass_path = str(Path(args.output).with_suffix(".ass"))
    print(f"Writing subtitle file: {ass_path} ...")
    write_ass(segments, ass_path, res=res)

    vf = f"ass={_esc_filter_path(ass_path)}"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={res[0]}x{res[1]}:r=24",
        "-i", args.mp3,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        args.output,
    ]

    print("\nRunning FFmpeg ...")
    print("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    print()

    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"\nDone! Saved to: {args.output}")
    else:
        print("\nFFmpeg failed. See output above for details.")
        sys.exit(1)
```

- [ ] **Step 4: Update the module docstring**

Replace the docstring at the top of `quran_video.py` (lines 2-15) with:

```python
"""
quran_video.py
Generate a Quran recitation MP4 with Arabic and English subtitles on a black background.

Usage:
    python quran_video.py <audio.mp3> <translated.srt> [output.mp4] [--resolution WxH]

  audio.mp3       - the recitation audio
  translated.srt  - translated SRT from add_translation.py (Arabic line + English line per block)
  output.mp4      - output path (default: output.mp4)
  --resolution    - video resolution (default: 1920x1080)

Requires FFmpeg in PATH compiled with libass support (standard in most builds).
"""
```

- [ ] **Step 5: Verify the full rewrite compiles and help works**

```bash
python quran_video.py --help
```

Expected output shows the new argument structure: `mp3`, `srt`, `output`, `--resolution`.

- [ ] **Step 6: Commit**

```bash
git add quran_video.py
git commit -m "feat: rewrite quran_video.py to consume translated SRT with dual-font layout"
```

---

### Task 4: End-to-end test with real data

**Files:**
- No file changes — this is a verification task using the existing sample data.

- [ ] **Step 1: Regenerate the translated SRT**

```bash
python add_translation.py "surah yusuf translation.txt" "surah yusuf.srt" "surah yusuf translated.srt"
```

Expected output:
- `Parsed 111 verses`
- `Parsed N subtitle blocks`
- `Matched to M unique verses`
- Output written to `surah yusuf translated.srt`

- [ ] **Step 2: Inspect the translated SRT for correctness**

Open `surah yusuf translated.srt` and verify:
1. First block Arabic starts with `١` (ayah number 1 in Arabic-Indic)
2. First block English starts with `1.`
3. No standalone orphan blocks like `All-Wise."` — verse 12:6 should keep `Surely your Lord is All-Knowing, All-Wise."` together
4. Verse 7 (first block of that verse) has `٧` prefix on Arabic and `7.` on English
5. Timestamps span the correct audio ranges (not just 4-8 second snippets)

- [ ] **Step 3: Generate the video at default 1080p resolution**

```bash
python quran_video.py "surah yusuf.mp3" "surah yusuf translated.srt" "surah yusuf.mp4"
```

Expected: FFmpeg runs without errors, produces `surah yusuf.mp4`.

- [ ] **Step 4: Verify video playback**

Open `surah yusuf.mp4` in a media player and check:
1. **Sync**: Text changes align with the audio recitation throughout the entire video, not just the beginning
2. **Arabic text**: Appears at top-center in Traditional Arabic font, white on black
3. **English text**: Appears at bottom-center in Times New Roman font, white on black
4. **Ayah numbers**: Arabic-Indic numerals visible at the start of each new verse (Arabic line), Western numerals on English line
5. **No orphans**: Long verses split naturally at sentence/comma boundaries, no tiny fragments
6. **Video length**: Matches the MP3 audio length (not cut short)

- [ ] **Step 5: Test custom resolution**

```bash
python quran_video.py "surah yusuf.mp3" "surah yusuf translated.srt" "test_720p.mp4" --resolution 1280x720
```

Verify the output is 720p and fonts are proportionally smaller but still readable.

- [ ] **Step 6: Clean up test files and commit**

Remove any test output files (`test_output.srt`, `test_720p.mp4`) that are not needed:
```bash
rm -f test_output.srt test_720p.mp4
```

Final commit:
```bash
git add add_translation.py quran_video.py
git commit -m "chore: final verified state after end-to-end testing"
```
