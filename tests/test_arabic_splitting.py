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
