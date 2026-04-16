"""Tests for global word-level matcher and verse-boundary splitter."""

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from add_translation import (
    match_blocks_to_verses,
    split_blocks_at_verse_boundaries,
    normalize_arabic,
)


def make_block(index, start, end, arabic_text):
    return {
        'index': str(index),
        'timestamp': f'{start} --> {end}',
        'text': arabic_text,
        'norm': normalize_arabic(arabic_text),
    }


def make_verse(ref, arabic):
    return {
        'ref': ref,
        'arabic': arabic,
        'translation': 'translation of ' + ref,
        'norm': normalize_arabic(arabic),
    }


def make_word(text, start, end):
    w = types.SimpleNamespace()
    w.word = text
    w.start = start
    w.end = end
    return w


# Ten synthetic verses, each with a distinctive unique word so alignment
# can unambiguously identify which verse a block belongs to.
VERSES_10 = [
    make_verse(f'1:{i+1}', f'المقدمة_{i} كلمة_{i} النهاية_{i}')
    for i in range(10)
]


class TestMatcherGlobalAlignment:

    def test_does_not_get_stuck_on_long_verse(self):
        """Each short block contains a word from verses 0..9 — assignments
        must reach all ten verses, not get stuck on the first one."""
        blocks = [
            make_block(i + 1, '00:00:00,000', '00:00:01,000',
                       f'كلمة_{i}')
            for i in range(10)
        ]
        assignments = match_blocks_to_verses(blocks, VERSES_10)
        assert assignments == list(range(10))

    def test_assignments_are_monotonic_non_decreasing(self):
        """Even if alignment is noisy, assignments should never go
        backwards."""
        # Intentionally scramble: block 0 → v0, block 1 → v3, block 2 → v2
        # (v2 would normally go backwards, but monotonic clamps to v3).
        blocks = [
            make_block(1, '00:00:00,000', '00:00:01,000', 'كلمة_0'),
            make_block(2, '00:00:01,000', '00:00:02,000', 'كلمة_3'),
            make_block(3, '00:00:02,000', '00:00:03,000', 'كلمة_2'),
            make_block(4, '00:00:03,000', '00:00:04,000', 'كلمة_5'),
        ]
        assignments = match_blocks_to_verses(blocks, VERSES_10)
        assert assignments == sorted(assignments)
        assert assignments[0] == 0
        assert assignments[1] == 3
        # Block 3 aligned to v2 but clamped up to running_max = 3
        assert assignments[2] == 3
        assert assignments[3] == 5

    def test_multi_verse_block_picks_a_verse(self):
        """A single giant block containing words from multiple verses is
        assigned to one of them (majority vote)."""
        # Block has 3 distinct words from verse 1, 1 from verse 0, 1 from
        # verse 2. SequenceMatcher aligns each distinct word once, so
        # majority = verse 1.
        giant = 'كلمة_0 المقدمة_1 كلمة_1 النهاية_1 كلمة_2'
        blocks = [make_block(1, '00:00:00,000', '00:00:10,000', giant)]
        assignments = match_blocks_to_verses(blocks, VERSES_10)
        assert assignments == [1]

    def test_unaligned_block_inherits_previous_assignment(self):
        """A block whose text doesn't align to any verse inherits the
        previous block's assignment rather than staying at 0."""
        blocks = [
            make_block(1, '00:00:00,000', '00:00:01,000', 'كلمة_4'),
            make_block(2, '00:00:01,000', '00:00:02,000', 'garbage_no_match'),
            make_block(3, '00:00:02,000', '00:00:03,000', 'كلمة_7'),
        ]
        assignments = match_blocks_to_verses(blocks, VERSES_10)
        assert assignments[0] == 4
        # Block 1 inherits from block 0 → 4
        assert assignments[1] == 4
        assert assignments[2] == 7

    def test_empty_inputs(self):
        assert match_blocks_to_verses([], VERSES_10) == []
        blocks = [make_block(1, '00:00:00,000', '00:00:01,000', 'x')]
        assert match_blocks_to_verses(blocks, []) == [0]


class TestSplitBlocksAtVerseBoundaries:

    def test_single_verse_block_passes_through(self):
        """A block whose words all align to one verse is unchanged."""
        words = [
            make_word('كلمة_3', 0.0, 0.5),
            make_word('النهاية_3', 0.6, 1.0),
        ]
        text = ' '.join(w.word for w in words)
        blocks = [make_block(1, '00:00:00,000', '00:00:01,000', text)]
        new_blocks, new_assignments = split_blocks_at_verse_boundaries(
            blocks, [words], VERSES_10, [3])
        assert len(new_blocks) == 1
        assert new_assignments == [3]

    def test_multi_verse_block_is_split(self):
        """A block with words spanning three verses is split into three
        sub-blocks with timestamps from the Word objects."""
        words = [
            make_word('كلمة_1', 0.0, 0.5),
            make_word('النهاية_1', 0.6, 1.0),
            make_word('كلمة_2', 1.1, 1.5),
            make_word('النهاية_2', 1.6, 2.0),
            make_word('كلمة_3', 2.1, 2.5),
            make_word('النهاية_3', 2.6, 3.0),
        ]
        text = ' '.join(w.word for w in words)
        blocks = [make_block(1, '00:00:00,000', '00:00:03,000', text)]
        new_blocks, new_assignments = split_blocks_at_verse_boundaries(
            blocks, [words], VERSES_10, [1])

        assert len(new_blocks) == 3
        assert new_assignments == [1, 2, 3]
        # First sub-block starts at word 0 (0.0s)
        assert new_blocks[0]['timestamp'].startswith('00:00:00,000')
        # First sub-block ends at word 1 (1.0s)
        assert '00:00:01,000' in new_blocks[0]['timestamp']
        # Second sub-block: 1.1s → 2.0s
        assert new_blocks[1]['timestamp'].startswith('00:00:01,100')
        assert '00:00:02,000' in new_blocks[1]['timestamp']
        # Third sub-block: 2.1s → 3.0s
        assert new_blocks[2]['timestamp'].startswith('00:00:02,100')
        assert '00:00:03,000' in new_blocks[2]['timestamp']

    def test_preserves_whisper_text_in_sub_blocks(self):
        """Sub-block text should come from the Word objects for that run."""
        words = [
            make_word('كلمة_4', 0.0, 0.5),
            make_word('كلمة_5', 1.0, 1.5),
        ]
        text = ' '.join(w.word for w in words)
        blocks = [make_block(1, '00:00:00,000', '00:00:02,000', text)]
        new_blocks, _ = split_blocks_at_verse_boundaries(
            blocks, [words], VERSES_10, [4])

        assert len(new_blocks) == 2
        assert 'كلمة_4' in new_blocks[0]['text']
        assert 'كلمة_5' in new_blocks[1]['text']
        assert 'كلمة_5' not in new_blocks[0]['text']

    def test_missing_word_groups_returns_inputs_unchanged(self):
        blocks = [make_block(1, '00:00:00,000', '00:00:01,000', 'x')]
        assignments = [0]
        nb, na = split_blocks_at_verse_boundaries(
            blocks, None, VERSES_10, assignments)
        assert nb is blocks and na is assignments

    def test_shape_mismatch_returns_inputs_unchanged(self):
        blocks = [
            make_block(1, '00:00:00,000', '00:00:01,000', 'x'),
            make_block(2, '00:00:01,000', '00:00:02,000', 'y'),
        ]
        nb, na = split_blocks_at_verse_boundaries(
            blocks, [[make_word('x', 0, 1)]], VERSES_10, [0, 0])
        assert nb is blocks
