# Breath-Pause Segmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Whisper SRT blocks at every breath pause so subtitles change each time the reciter stops, not once per long segment.

**Architecture:** Enable `word_timestamps=True` in the faster-whisper call, extract a helper `_words_to_srt_blocks()` that groups words into blocks wherever the inter-word gap meets a threshold, then swap out the old SRT-building loop for the new helper.

**Tech Stack:** Python 3.9+, faster-whisper, pytest

---

## File Map

| File | Change |
|------|--------|
| `app.py` | Add `BREATH_PAUSE_MS` constant; add `_words_to_srt_blocks()` helper; add `word_timestamps=True` to `transcribe()`; replace SRT-building loop |
| `tests/test_breath_pause.py` | New — unit tests for `_words_to_srt_blocks()` |

---

### Task 1: Add constant and extract helper function

**Files:**
- Modify: `app.py` (module level + new helper near `_format_srt_time` at line 314)

- [ ] **Step 1: Add `BREATH_PAUSE_MS` constant**

Open `app.py`. After line 27 (`API_HEADERS = ...`), add:

```python
# Minimum silence gap (seconds) between words that triggers a new SRT block.
BREATH_PAUSE_MS = 0.4
```

- [ ] **Step 2: Add `_words_to_srt_blocks()` helper**

After the `_format_srt_time` function (line 314 area), add:

```python
def _words_to_srt_blocks(all_words, threshold=BREATH_PAUSE_MS):
    """Split a flat list of faster-whisper Word objects into SRT block strings.

    A new block starts whenever the gap between consecutive words is >= threshold
    (seconds).  Words with no .start/.end are skipped.

    Returns a list of raw SRT block strings (index + timestamp + text), not yet
    joined — caller does '\n'.join(blocks).
    """
    blocks = []
    idx = 1
    group = []
    for i, w in enumerate(all_words):
        group.append(w)
        is_last = (i == len(all_words) - 1)
        gap = (all_words[i + 1].start - w.end) if not is_last else None
        if is_last or gap >= threshold:
            start = _format_srt_time(group[0].start)
            end = _format_srt_time(group[-1].end)
            text = ' '.join(word.word.strip() for word in group)
            blocks.append(f'{idx}\n{start} --> {end}\n{text}\n')
            idx += 1
            group = []
    return blocks
```

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: add BREATH_PAUSE_MS constant and _words_to_srt_blocks helper"
```

---

### Task 2: Write and run tests for the helper

**Files:**
- Create: `tests/test_breath_pause.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_breath_pause.py`:

```python
"""Tests for _words_to_srt_blocks() breath-pause segmentation."""

import os
import sys
import types
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import _words_to_srt_blocks


def make_word(text, start, end):
    """Create a minimal fake faster-whisper Word object."""
    w = types.SimpleNamespace()
    w.word = text
    w.start = start
    w.end = end
    return w


class TestWordsToSrtBlocks:

    def test_empty_input_returns_empty(self):
        assert _words_to_srt_blocks([]) == []

    def test_single_word_produces_one_block(self):
        words = [make_word('كَلِمَة', 0.0, 0.5)]
        blocks = _words_to_srt_blocks(words, threshold=0.4)
        assert len(blocks) == 1
        assert 'كَلِمَة' in blocks[0]

    def test_no_gap_produces_one_block(self):
        # 0.1s gap < 0.4s threshold → stay in same block
        words = [
            make_word('الْحَمْدُ', 0.0, 0.5),
            make_word('لِلَّهِ',   0.6, 1.1),
        ]
        blocks = _words_to_srt_blocks(words, threshold=0.4)
        assert len(blocks) == 1
        assert 'الْحَمْدُ' in blocks[0]
        assert 'لِلَّهِ' in blocks[0]

    def test_gap_at_threshold_splits(self):
        # 0.4s gap == 0.4s threshold → split
        words = [
            make_word('الْحَمْدُ', 0.0, 0.5),
            make_word('لِلَّهِ',   0.9, 1.4),
        ]
        blocks = _words_to_srt_blocks(words, threshold=0.4)
        assert len(blocks) == 2
        assert 'الْحَمْدُ' in blocks[0]
        assert 'لِلَّهِ' in blocks[1]

    def test_gap_below_threshold_does_not_split(self):
        # 0.39s gap < 0.4s threshold → no split
        words = [
            make_word('الْحَمْدُ', 0.0,  0.50),
            make_word('لِلَّهِ',   0.89, 1.40),
        ]
        blocks = _words_to_srt_blocks(words, threshold=0.4)
        assert len(blocks) == 1

    def test_multiple_breath_pauses_produce_multiple_blocks(self):
        words = [
            make_word('الر',      0.0,  0.3),   # block 1
            make_word('تِلْكَ',  0.7,  1.0),   # gap 0.4 → split
            make_word('آيَاتُ',  1.5,  1.9),   # gap 0.5 → split
        ]
        blocks = _words_to_srt_blocks(words, threshold=0.4)
        assert len(blocks) == 3

    def test_block_timestamps_are_correct(self):
        words = [
            make_word('بِسْمِ',    1.0,  1.5),
            make_word('اللَّهِ',   2.0,  2.5),  # gap 0.5 → split
        ]
        blocks = _words_to_srt_blocks(words, threshold=0.4)
        assert len(blocks) == 2
        # First block: 00:00:01,000 --> 00:00:01,500
        assert '00:00:01,000' in blocks[0]
        assert '00:00:01,500' in blocks[0]
        # Second block: 00:00:02,000 --> 00:00:02,500
        assert '00:00:02,000' in blocks[1]
        assert '00:00:02,500' in blocks[1]

    def test_block_indices_are_sequential(self):
        words = [
            make_word('a', 0.0, 0.3),
            make_word('b', 0.8, 1.1),  # gap 0.5 → split
            make_word('c', 1.6, 1.9),  # gap 0.5 → split
        ]
        blocks = _words_to_srt_blocks(words, threshold=0.4)
        assert blocks[0].startswith('1\n')
        assert blocks[1].startswith('2\n')
        assert blocks[2].startswith('3\n')
```

- [ ] **Step 2: Run tests — expect FAIL (helper not yet wired into transcription)**

```bash
python -m pytest tests/test_breath_pause.py -v
```

Expected: All tests **PASS** — the helper is already added and pure, so it's testable without touching the transcription call.

If any test fails, fix `_words_to_srt_blocks()` in `app.py` before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_breath_pause.py
git commit -m "test: add unit tests for _words_to_srt_blocks"
```

---

### Task 3: Wire helper into the transcription pipeline

**Files:**
- Modify: `app.py` lines ~191–205 (transcribe call + SRT-building loop)

- [ ] **Step 1: Add `word_timestamps=True` to transcribe call**

In `app.py`, find:

```python
        segments_iter, info = model.transcribe(
            mp3_path,
            language='ar',
            temperature=0,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
```

Replace with:

```python
        segments_iter, info = model.transcribe(
            mp3_path,
            language='ar',
            temperature=0,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            word_timestamps=True,
        )
```

- [ ] **Step 2: Replace SRT-building loop**

Find:

```python
        # Build SRT content from Whisper segments
        srt_lines = []
        for idx, seg in enumerate(segments_iter, 1):
            start = _format_srt_time(seg.start)
            end = _format_srt_time(seg.end)
            srt_lines.append(f'{idx}\n{start} --> {end}\n{seg.text.strip()}\n')
```

Replace with:

```python
        # Flatten words from all segments, skip segments with no word data
        all_words = []
        for seg in segments_iter:
            if seg.words:
                all_words.extend(seg.words)

        # Split into SRT blocks at every breath pause
        srt_lines = _words_to_srt_blocks(all_words)
```

- [ ] **Step 3: Run full test suite to confirm nothing broken**

```bash
python -m pytest tests/ -v
```

Expected: All tests **PASS**.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: split SRT blocks at breath pauses using word timestamps"
```

---

## Tuning Reference

After running the app on a real recitation, if segmentation feels wrong:

| Symptom | Fix |
|---------|-----|
| Still grouping two phrases | Lower `BREATH_PAUSE_MS` (try `0.3`) |
| Splitting mid-phrase (too aggressive) | Raise `BREATH_PAUSE_MS` (try `0.5` or `0.6`) |

Edit the constant at the top of `app.py` — no other changes needed.
