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
        # Use gaps clearly above threshold to avoid floating-point precision traps
        # (e.g. 0.7 - 0.3 = 0.3999... in IEEE 754, which is < 0.4)
        words = [
            make_word('الر',      0.0,  0.3),   # block 1
            make_word('تِلْكَ',  0.71, 1.01),  # gap 0.41 → split
            make_word('آيَاتُ',  1.52, 1.90),  # gap 0.51 → split
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
