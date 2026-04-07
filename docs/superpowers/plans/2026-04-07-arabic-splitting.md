# Arabic Subtitle Splitting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Arabic text across subtitle blocks so each block shows only the words being recited, instead of the full verse.

**Architecture:** Modify `load_word_data()` to return raw Arabic alongside normalized, then modify `build_verse_blocks()` to compute per-block Arabic slices using word ranges (with proportional and Whisper fallbacks), and finally stop `build_output()` from overwriting the Arabic.

**Tech Stack:** Python 3.9+, quran.com API (existing)

---

### Task 1: Add tests for Arabic splitting

No test infrastructure exists yet. Create a test file covering the core behavior we're about to change.

**Files:**
- Create: `tests/test_arabic_splitting.py`

- [ ] **Step 1: Create test directory and file**

```bash
mkdir -p tests
```

- [ ] **Step 2: Write tests for `load_word_data` 3-tuple output**

Write `tests/test_arabic_splitting.py`:

```python
"""Tests for Arabic subtitle splitting across multi-block verses."""

import os
import json
import pytest

# Adjust path so imports work
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from add_translation import (
    load_word_data, build_verse_blocks, build_output,
    normalize_arabic, match_blocks_to_verses,
)


# ── Fixtures ──────────────────────────────────────────────────────────

def make_block(index, start, end, arabic_text):
    """Create a fake SRT block dict."""
    return {
        'index': str(index),
        'timestamp': f'{start} --> {end}',
        'text': arabic_text,
        'norm': normalize_arabic(arabic_text),
    }


def make_verse(ref, arabic, translation):
    """Create a fake verse dict."""
    return {
        'ref': ref,
        'arabic': arabic,
        'translation': translation,
        'norm': normalize_arabic(arabic),
    }


# ── load_word_data returns 3-tuples ──────────────────────────────────

class TestLoadWordData:
    def test_returns_3_tuples(self, tmp_path):
        """Each word entry should be (raw_arabic, norm_arabic, english)."""
        # Create a fake cache file with raw text_uthmani data
        cache = {
            "1": [
                ["بِسْمِ", "In the name"],
                ["ٱللَّهِ", "of Allah"],
            ]
        }
        cache_file = tmp_path / "wbw_1.json"
        cache_file.write_text(json.dumps(cache), encoding="utf-8")

        result = load_word_data(1, cache_dir=str(tmp_path))

        assert 1 in result
        words = result[1]
        assert len(words) == 2
        # Each entry is a 3-tuple: (raw, normalized, english)
        for entry in words:
            assert len(entry) == 3
        # First word: raw preserves diacritics
        assert words[0][0] == "بِسْمِ"
        # First word: normalized strips diacritics
        assert words[0][1] == normalize_arabic("بِسْمِ")
        # First word: english
        assert words[0][2] == "In the name"


# ── build_verse_blocks splits Arabic ─────────────────────────────────

class TestBuildVerseBlocksArabicSplit:
    def test_single_block_returns_full_verse_arabic(self):
        """A single-block verse should return the full verse_arabic."""
        block = make_block(1, '00:00:01,000', '00:00:05,000', 'some whisper text')
        verse_arabic = 'بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ'

        result = build_verse_blocks(
            [block], 'In the name of Allah, the Most Gracious, the Most Merciful',
            verse_arabic=verse_arabic,
        )

        assert len(result) == 1
        assert result[0][2] == verse_arabic

    def test_multi_block_splits_arabic_with_word_data(self):
        """Two blocks should get different Arabic slices when word data is available."""
        block1 = make_block(1, '00:00:01,000', '00:00:03,000', 'بسم الله')
        block2 = make_block(2, '00:00:03,000', '00:00:05,000', 'الرحمن الرحيم')

        verse_words = [
            ('بِسْمِ', normalize_arabic('بِسْمِ'), 'In (the) name'),
            ('ٱللَّهِ', normalize_arabic('ٱللَّهِ'), 'of Allah'),
            ('ٱلرَّحْمَـٰنِ', normalize_arabic('ٱلرَّحْمَـٰنِ'), 'the Most Gracious'),
            ('ٱلرَّحِيمِ', normalize_arabic('ٱلرَّحِيمِ'), 'the Most Merciful'),
        ]
        verse_arabic = 'بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ'

        result = build_verse_blocks(
            [block1, block2],
            'In the name of Allah, the Most Gracious, the Most Merciful',
            verse_norm=normalize_arabic(verse_arabic),
            verse_words=verse_words,
            verse_arabic=verse_arabic,
        )

        assert len(result) == 2
        ar1 = result[0][2]
        ar2 = result[1][2]
        # Each block should have different Arabic
        assert ar1 != ar2
        # Neither should be the full verse
        assert ar1 != verse_arabic
        assert ar2 != verse_arabic

    def test_multi_block_proportional_fallback_without_word_data(self):
        """Without word data, Arabic should be split proportionally, not repeated."""
        block1 = make_block(1, '00:00:01,000', '00:00:03,000', 'بسم الله')
        block2 = make_block(2, '00:00:03,000', '00:00:05,000', 'الرحمن الرحيم')

        verse_arabic = 'بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ'

        result = build_verse_blocks(
            [block1, block2],
            'In the name of Allah, the Most Gracious, the Most Merciful',
            verse_norm=normalize_arabic(verse_arabic),
            verse_words=None,
            verse_arabic=verse_arabic,
        )

        assert len(result) == 2
        ar1 = result[0][2]
        ar2 = result[1][2]
        assert ar1 != ar2
        assert ar1 != verse_arabic
        assert ar2 != verse_arabic


# ── build_output uses split Arabic ───────────────────────────────────

class TestBuildOutputArabicSplit:
    def test_multi_block_verse_has_different_arabic(self):
        """build_output should NOT use the same Arabic for every block of a verse."""
        # Two SRT blocks that both match verse 0
        blocks = [
            make_block(1, '00:00:01,000', '00:00:03,000', 'بسم الله'),
            make_block(2, '00:00:03,000', '00:00:05,000', 'الرحمن الرحيم'),
        ]
        verses = [make_verse(
            '1:1',
            'بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ',
            'In the name of Allah, the Most Gracious, the Most Merciful',
        )]
        assignments = [0, 0]

        word_data = {
            1: [
                ('بِسْمِ', normalize_arabic('بِسْمِ'), 'In (the) name'),
                ('ٱللَّهِ', normalize_arabic('ٱللَّهِ'), 'of Allah'),
                ('ٱلرَّحْمَـٰنِ', normalize_arabic('ٱلرَّحْمَـٰنِ'), 'the Most Gracious'),
                ('ٱلرَّحِيمِ', normalize_arabic('ٱلرَّحِيمِ'), 'the Most Merciful'),
            ]
        }

        srt, segments = build_output(blocks, verses, assignments,
                                     word_data=word_data, return_segments=True)

        assert len(segments) == 2
        ar1 = segments[0][2]
        ar2 = segments[1][2]
        # The two blocks should have DIFFERENT Arabic
        assert ar1 != ar2

    def test_verse_number_only_on_first_block(self):
        """Verse number should appear on first block only."""
        blocks = [
            make_block(1, '00:00:01,000', '00:00:03,000', 'بسم الله'),
            make_block(2, '00:00:03,000', '00:00:05,000', 'الرحمن الرحيم'),
        ]
        verses = [make_verse(
            '1:1',
            'بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ',
            'In the name of Allah, the Most Gracious, the Most Merciful',
        )]
        assignments = [0, 0]

        word_data = {
            1: [
                ('بِسْمِ', normalize_arabic('بِسْمِ'), 'In (the) name'),
                ('ٱللَّهِ', normalize_arabic('ٱللَّهِ'), 'of Allah'),
                ('ٱلرَّحْمَـٰنِ', normalize_arabic('ٱلرَّحْمَـٰنِ'), 'the Most Gracious'),
                ('ٱلرَّحِيمِ', normalize_arabic('ٱلرَّحِيمِ'), 'the Most Merciful'),
            ]
        }

        _, segments = build_output(blocks, verses, assignments,
                                   word_data=word_data, return_segments=True)

        # First block Arabic starts with verse number ١
        assert segments[0][2].startswith('١')
        # Second block Arabic does NOT start with verse number
        assert not segments[1][2].startswith('١')
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd C:/Users/Mahmood/Documents/QuranVideoMaker && python -m pytest tests/test_arabic_splitting.py -v
```

Expected: Multiple FAILUREs — `load_word_data` returns 2-tuples not 3, `build_verse_blocks` doesn't accept `verse_arabic`, `build_output` uses full verse Arabic for every block.

- [ ] **Step 4: Commit**

```bash
git add tests/test_arabic_splitting.py
git commit -m "test: add failing tests for Arabic subtitle splitting"
```

---

### Task 2: Update `load_word_data()` to return 3-tuples

**Files:**
- Modify: `add_translation.py:122-128`

- [ ] **Step 1: Change the result-building loop to return `(raw, norm, english)`**

In `add_translation.py`, replace lines 122-128:

```python
    result = {}
    for vnum_str, pairs in raw.items():
        norm_pairs = [(normalize_arabic(ar), en) for ar, en in pairs]
        norm_pairs = [(ar, en) for ar, en in norm_pairs if ar]
        if norm_pairs:
            result[int(vnum_str)] = norm_pairs
    return result
```

With:

```python
    result = {}
    for vnum_str, pairs in raw.items():
        triples = [(ar, normalize_arabic(ar), en) for ar, en in pairs]
        triples = [(raw_ar, norm_ar, en) for raw_ar, norm_ar, en in triples if norm_ar]
        if triples:
            result[int(vnum_str)] = triples
    return result
```

- [ ] **Step 2: Update the docstring**

Replace the docstring at lines 74-78:

```python
    """Fetch/load word-by-word Arabic text and translations for a Quran chapter.

    Results are cached as wbw_<chapter>.json beside this script.  Returns a
    dict mapping verse_number (int) → list of (arabic_norm, en_translation)
    tuples.  Returns {} on network failure when no cache exists.
    """
```

With:

```python
    """Fetch/load word-by-word Arabic text and translations for a Quran chapter.

    Results are cached as wbw_<chapter>.json beside this script.  Returns a
    dict mapping verse_number (int) → list of (raw_arabic, norm_arabic,
    en_translation) tuples.  Returns {} on network failure when no cache exists.
    """
```

- [ ] **Step 3: Run the `TestLoadWordData` test**

```bash
cd C:/Users/Mahmood/Documents/QuranVideoMaker && python -m pytest tests/test_arabic_splitting.py::TestLoadWordData -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add add_translation.py
git commit -m "feat: return raw Arabic from load_word_data for display use"
```

---

### Task 3: Update `build_verse_blocks()` to split Arabic

**Files:**
- Modify: `add_translation.py:411-538` (`build_verse_blocks` function)

- [ ] **Step 1: Update function signature and docstring**

Replace lines 411-420:

```python
def build_verse_blocks(srt_blocks, translation, verse_norm='', verse_words=None):
    """Given a verse's SRT blocks and its translation, produce output blocks.

    Uses word-by-word API data (verse_words) to anchor English split points
    directly to specific words in the polished translation.  Falls back to
    character-level fuzzy matching and then proportional splitting when
    word data is unavailable.

    verse_words: list of (arabic_norm, en_translation) tuples.
    Returns list of (start, end, arabic, english).
    """
```

With:

```python
def build_verse_blocks(srt_blocks, translation, verse_norm='', verse_words=None,
                       verse_arabic='', ayah_num=0):
    """Given a verse's SRT blocks and its translation, produce output blocks.

    Uses word-by-word API data (verse_words) to anchor English split points
    directly to specific words in the polished translation.  Falls back to
    character-level fuzzy matching and then proportional splitting when
    word data is unavailable.

    Also splits the Arabic text across blocks using the same word ranges.
    Fallback chain: word-by-word > proportional split of verse_arabic > Whisper.

    verse_words: list of (raw_arabic, norm_arabic, en_translation) tuples.
    verse_arabic: full polished Arabic text for the verse (for fallbacks).
    ayah_num: verse number (for warning messages).
    Returns list of (start, end, arabic, english).
    """
```

- [ ] **Step 2: Update single-block early return to use `verse_arabic`**

Replace lines 425-429:

```python
    if n == 1:
        b = srt_blocks[0]
        return [(ts_start(b['timestamp']), ts_end(b['timestamp']),
                 b['text'], translation)]
```

With:

```python
    if n == 1:
        b = srt_blocks[0]
        ar = verse_arabic or b['text']
        return [(ts_start(b['timestamp']), ts_end(b['timestamp']),
                 ar, translation)]
```

- [ ] **Step 3: Update word extraction for 3-tuples**

Replace line 477:

```python
    ar_words = [ar for ar, _ in verse_words] if verse_words else []
```

With:

```python
    # verse_words is list of (raw_arabic, norm_arabic, english) 3-tuples
    raw_ar_words = [raw for raw, _, _ in verse_words] if verse_words else []
    ar_words = [norm for _, norm, _ in verse_words] if verse_words else []
```

- [ ] **Step 4: Update the English word-data references for 3-tuples**

Replace line 509:

```python
                last_word_en = verse_words[wr[1] - 1][1]
```

With:

```python
                last_word_en = verse_words[wr[1] - 1][2]
```

- [ ] **Step 5: Add Arabic slicing logic inside the per-block loop**

Replace lines 533-535:

```python
        english = translation[en_start:en_end].strip() or translation.strip()
        results.append((ts_start(b['timestamp']), ts_end(b['timestamp']),
                        b['text'], english))
```

With:

```python
        english = translation[en_start:en_end].strip() or translation.strip()

        # ── Arabic slice ──────────────────────────────────────────────
        if wr is not None and raw_ar_words:
            # Primary: use word-by-word raw Arabic
            arabic = ' '.join(raw_ar_words[wr[0]:wr[1]])
        elif verse_arabic:
            # Fallback: proportional split of verse_arabic at space boundaries
            print(f'WARNING: Using proportional Arabic split for block '
                  f'{i+1}/{n} of verse {ayah_num}')
            ar_words_full = verse_arabic.split()
            total_w = len(ar_words_full)
            start_frac = cum_ar[i] / total_ar
            end_frac = (cum_ar[i] + ar_lens[i]) / total_ar
            w_start = max(0, round(start_frac * total_w))
            w_end = min(total_w, round(end_frac * total_w))
            if w_end <= w_start:
                w_end = min(w_start + 1, total_w)
            arabic = ' '.join(ar_words_full[w_start:w_end]) or verse_arabic
        else:
            # Last resort: Whisper's transcription
            print(f'WARNING: Using Whisper Arabic fallback for block '
                  f'{i+1}/{n} of verse {ayah_num}')
            arabic = b['text']

        results.append((ts_start(b['timestamp']), ts_end(b['timestamp']),
                        arabic, english))
```

- [ ] **Step 6: Run the `TestBuildVerseBlocksArabicSplit` tests**

```bash
cd C:/Users/Mahmood/Documents/QuranVideoMaker && python -m pytest tests/test_arabic_splitting.py::TestBuildVerseBlocksArabicSplit -v
```

Expected: PASS for all 3 tests (single block, word-data split, proportional fallback)

- [ ] **Step 7: Commit**

```bash
git add add_translation.py
git commit -m "feat: split Arabic text across subtitle blocks using word ranges"
```

---

### Task 4: Update `build_output()` to use split Arabic

**Files:**
- Modify: `add_translation.py:556-591` (`build_output` function)

- [ ] **Step 1: Pass `verse_arabic` and `ayah_num` to `build_verse_blocks()`**

Replace lines 581-583:

```python
        merged = build_verse_blocks(vblocks, translation,
                                    verse_norm=verses[vi]['norm'],
                                    verse_words=verse_words)
```

With:

```python
        merged = build_verse_blocks(vblocks, translation,
                                    verse_norm=verses[vi]['norm'],
                                    verse_words=verse_words,
                                    verse_arabic=verse_arabic,
                                    ayah_num=ayah_num)
```

- [ ] **Step 2: Stop overwriting Arabic — use what `build_verse_blocks()` returns**

Replace lines 584-591:

```python
        for idx_in_verse, (start, end, _whisper_arabic, english) in enumerate(merged):
            # Use the polished Arabic from the translation file rather than the
            # Whisper transcription, which may be noisy or missing diacritics.
            arabic = verse_arabic
            if idx_in_verse == 0:
                arabic = to_arabic_numeral(ayah_num) + ' ' + arabic
                english = str(ayah_num) + '. ' + english
            all_output.append((start, end, arabic, english))
```

With:

```python
        for idx_in_verse, (start, end, arabic, english) in enumerate(merged):
            if idx_in_verse == 0:
                arabic = to_arabic_numeral(ayah_num) + ' ' + arabic
                english = str(ayah_num) + '. ' + english
            all_output.append((start, end, arabic, english))
```

- [ ] **Step 3: Run the `TestBuildOutputArabicSplit` tests**

```bash
cd C:/Users/Mahmood/Documents/QuranVideoMaker && python -m pytest tests/test_arabic_splitting.py::TestBuildOutputArabicSplit -v
```

Expected: PASS for both tests

- [ ] **Step 4: Run all tests**

```bash
cd C:/Users/Mahmood/Documents/QuranVideoMaker && python -m pytest tests/test_arabic_splitting.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add add_translation.py
git commit -m "fix: use split Arabic from build_verse_blocks instead of full verse"
```

---

### Task 5: Smoke test with a real run

**Files:** None modified — validation only.

- [ ] **Step 1: Run the web app and generate a test video**

```bash
cd C:/Users/Mahmood/Documents/QuranVideoMaker && python app.py
```

Upload a short Surah 12 (Yusuf) MP3 clip, generate the video, and verify:
- Each subtitle block shows only the Arabic words being recited in that segment
- Verse numbers appear only on the first block of each verse
- English splitting is unchanged
- Any WARNING messages appear in the server console (if fallbacks triggered)

- [ ] **Step 2: Verify the output SRT file**

Check the `translated.srt` in the job output directory. For a multi-block verse, confirm the Arabic text differs between blocks.

- [ ] **Step 3: Final commit with all files**

```bash
git add -A
git commit -m "feat: Arabic subtitle splitting — split Arabic across blocks by recited words"
```
