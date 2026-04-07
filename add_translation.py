#!/usr/bin/env python3
"""
Quran Subtitle Translator

Matches SRT subtitle blocks with Quran verse translations using fuzzy
Arabic text matching, then creates a new SRT with English translations.
Merges subtitle blocks when there is no comma in the translation to
justify a break.

Usage:
    python add_translation.py <translation.txt> <subtitles.srt> [output.srt]

The translation file should have this format (e.g. from quran.com):
    Header line
    <blank>
    12:1
    <Arabic with diacritics> <verse number>
    <English translation>
    <blank>
    12:2
    ...

The SRT file is a standard subtitle file with Arabic recitation text.
"""

import re
import sys
import os
import json
import urllib.request
from difflib import SequenceMatcher


# ── Arabic text processing ──────────────────────────────────────────

def strip_diacritics(text):
    """Remove Arabic diacritical marks (tashkeel) and Quranic notation."""
    # Core diacritics (fathah, dammah, kasrah, shadda, sukun, tanween, etc.)
    text = re.sub(r'[\u0610-\u061A\u064B-\u065F\u0670]', '', text)
    # Quranic annotation marks (stop signs, sajda, etc.)
    text = re.sub(r'[\u06D6-\u06ED]', '', text)
    return text


def normalize_arabic(text):
    """Normalize Arabic text for fuzzy comparison."""
    text = strip_diacritics(text)
    # Remove Quran ornamental markers
    text = text.replace('\u06DE', '')  # ۞
    text = text.replace('\u06E9', '')  # ۩
    # Normalize alef variants → bare alef
    text = re.sub(r'[آأإٱ]', 'ا', text)
    # Superscript alef → alef
    text = text.replace('\u0670', 'ا')
    text = text.replace('\u0649', 'ي')   # alef maqsura → yeh
    text = text.replace('\u0629', '\u0647')  # teh marbuta → heh
    text = text.replace('\u0640', '')    # tatweel
    # Small letter markers used in Quran text
    text = re.sub(r'[\u06D0-\u06D5\u06E5\u06E6]', '', text)
    # Small high/low waw, yeh, etc.
    text = re.sub(r'[\u06DC\u06DF\u06E0\u06E1\u06E2\u06E3\u06E4]', '', text)
    # Zero-width and formatting chars
    text = re.sub(r'[\u200B-\u200F\u202A-\u202E\u2060-\u2064\uFEFF]', '', text)
    # Remove verse numbers at end (Arabic-Indic digits ٠-٩)
    text = re.sub(r'[\u0660-\u0669]+\s*$', '', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── Word-by-word data (quran.com API) ───────────────────────────────

def load_word_data(chapter, cache_dir=None):
    """Fetch/load word-by-word Arabic text and translations for a Quran chapter.

    Results are cached as wbw_<chapter>.json beside this script.  Returns a
    dict mapping verse_number (int) → list of (raw_arabic, norm_arabic,
    en_translation) tuples.  Returns {} on network failure when no cache exists.
    """
    if cache_dir is None:
        cache_dir = os.path.dirname(os.path.abspath(__file__)) or '.'

    cache_file = os.path.join(cache_dir, f'wbw_{chapter}.json')

    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as fh:
            raw = json.load(fh)
    else:
        raw = {}
        page = 1
        while True:
            url = (f'https://api.quran.com/api/v4/verses/by_chapter/{chapter}'
                   f'?words=true&word_fields=text_uthmani&per_page=50&page={page}')
            try:
                req = urllib.request.Request(url, headers={
                    'Accept': 'application/json',
                    'User-Agent': 'Mozilla/5.0',
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
            except Exception as exc:
                print(f'WARNING: Could not fetch word data (page {page}): {exc}')
                return {}

            for verse in data.get('verses', []):
                vnum = verse['verse_number']
                pairs = [
                    [w['text_uthmani'], w.get('translation', {}).get('text', '')]
                    for w in verse.get('words', [])
                    if w.get('char_type_name') == 'word'
                ]
                raw[str(vnum)] = pairs

            total_pages = data.get('pagination', {}).get('total_pages', 1)
            if page >= total_pages:
                break
            page += 1

        with open(cache_file, 'w', encoding='utf-8') as fh:
            json.dump(raw, fh, ensure_ascii=False, indent=2)

    result = {}
    for vnum_str, pairs in raw.items():
        triples = [(ar, normalize_arabic(ar), en) for ar, en in pairs]
        triples = [(raw_ar, norm_ar, en) for raw_ar, norm_ar, en in triples if norm_ar]
        if triples:
            result[int(vnum_str)] = triples
    return result


# ── Parsing ─────────────────────────────────────────────────────────

def parse_translation_file(filepath):
    """Parse a Quran translation text file.

    Returns list of dicts: {ref, arabic, translation, norm}
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Match verse references like "12:1", "2:255", etc.
    ref_pattern = re.compile(r'^(\d+:\d+)\s*$', re.MULTILINE)
    parts = ref_pattern.split(content)
    # parts = [header, "12:1", block1, "12:2", block2, ...]

    verses = []
    for i in range(1, len(parts), 2):
        ref = parts[i]
        lines = [l.strip() for l in parts[i + 1].strip().split('\n') if l.strip()]
        arabic = lines[0] if lines else ''
        translation = ' '.join(lines[1:]) if len(lines) > 1 else ''
        verses.append({
            'ref': ref,
            'arabic': arabic,
            'translation': translation,
            'norm': normalize_arabic(arabic),
        })

    return verses


def parse_srt(filepath):
    """Parse a standard SRT subtitle file.

    Returns list of dicts: {index, timestamp, text, norm}
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = []
    for raw in re.split(r'\n\s*\n', content.strip()):
        lines = raw.strip().split('\n')
        if len(lines) >= 3:
            blocks.append({
                'index': lines[0].strip(),
                'timestamp': lines[1].strip(),
                'text': '\n'.join(lines[2:]).strip(),
                'norm': normalize_arabic('\n'.join(lines[2:])),
            })

    return blocks


# ── Matching ────────────────────────────────────────────────────────

def containment_score(needle, haystack):
    """Fraction of needle's characters that appear (in order) in haystack."""
    if not needle or not haystack:
        return 0.0
    sm = SequenceMatcher(None, needle, haystack, autojunk=False)
    matched = sum(block.size for block in sm.get_matching_blocks())
    return matched / len(needle)


def match_blocks_to_verses(blocks, verses):
    """Assign each SRT block a verse index using sequential fuzzy matching.

    Returns a list of verse indices, one per block.
    """
    vi = 0
    assignments = []

    for block in blocks:
        if vi >= len(verses):
            assignments.append(len(verses) - 1)
            continue

        cur = containment_score(block['norm'], verses[vi]['norm'])

        nxt = 0.0
        if vi + 1 < len(verses):
            nxt = containment_score(block['norm'], verses[vi + 1]['norm'])

        # Advance to next verse if it is a clearly better match
        if nxt > cur and nxt > 0.3:
            vi += 1

        assignments.append(vi)

    return assignments


# ── Translation splitting and subtitle block assembly ──────────────

def ts_start(timestamp):
    return timestamp.split('-->')[0].strip()


def ts_end(timestamp):
    return timestamp.split('-->')[1].strip()


def distribute(items, n):
    """Split a list into n groups as evenly as possible."""
    if n <= 0 or not items:
        return [items] if items else [[]]
    k, r = divmod(len(items), n)
    groups, idx = [], 0
    for i in range(n):
        size = k + (1 if i < r else 0)
        groups.append(items[idx:idx + size])
        idx += size
    return groups


def split_translation(translation, min_words=5):
    """Split a translation string at commas and sentence-ending punctuation.

    Splits at commas and sentence-ending punctuation (.!?) when followed by a
    space or end-of-string.  Any resulting segment with fewer than min_words
    words is merged back into the preceding segment to avoid orphan fragments.

    Returns a list of non-empty segment strings.
    """
    raw_segs = re.split(r'(?<=[,.\!\?])\s+', translation)
    segments = [s.strip() for s in raw_segs if s.strip()]

    if not segments:
        return [translation]

    merged = [segments[0]]
    for seg in segments[1:]:
        if len(seg.split()) < min_words:
            merged[-1] = merged[-1] + ' ' + seg
        else:
            merged.append(seg)

    return merged


def _verse_position(block_norm, verse_norm):
    """Find where block_norm appears within verse_norm using fuzzy matching.

    Returns (start_frac, end_frac) as fractions of verse_norm length,
    or None if no meaningful match is found.
    """
    if not verse_norm or not block_norm:
        return None
    sm = SequenceMatcher(None, verse_norm, block_norm, autojunk=False)
    matches = [(m.a, m.b, m.size) for m in sm.get_matching_blocks() if m.size > 0]
    if not matches:
        return None
    # Overall span of matching regions within the verse
    verse_start = matches[0][0]
    verse_end = matches[-1][0] + matches[-1][2]
    # Extend span to account for unmatched chars at the edges of the block
    unmatched_before = matches[0][1]
    unmatched_after = len(block_norm) - (matches[-1][1] + matches[-1][2])
    verse_start = max(0, verse_start - unmatched_before)
    verse_end = min(len(verse_norm), verse_end + unmatched_after)
    n = len(verse_norm)
    return verse_start / n, verse_end / n


def _match_word_range(block_norm, ar_words):
    """Find the span of verse word-indices that best matches a block's Arabic.

    block_norm  – normalized Arabic text of one SRT block
    ar_words    – list of normalized Arabic word strings for the full verse

    Returns (start_idx, end_idx) as a half-open range into ar_words,
    or None when matching is unreliable.
    """
    if not ar_words or not block_norm:
        return None

    block_words = block_norm.split()
    if not block_words:
        return None

    n = len(ar_words)
    sm = SequenceMatcher(None, ar_words, block_words, autojunk=False)
    matches = [(m.a, m.b, m.size) for m in sm.get_matching_blocks() if m.size > 0]

    if not matches:
        return None

    verse_start = matches[0][0]
    verse_end   = matches[-1][0] + matches[-1][2]

    # Extend span to cover unmatched block words at the edges
    unmatched_before = matches[0][1]
    unmatched_after  = len(block_words) - (matches[-1][1] + matches[-1][2])
    verse_start = max(0, verse_start - unmatched_before)
    verse_end   = min(n, verse_end + unmatched_after)

    if verse_start >= verse_end:
        return None

    return verse_start, verse_end


_STOPWORDS = frozenset({
    'a', 'an', 'the', 'and', 'or', 'but', 'of', 'to', 'in', 'on', 'at',
    'by', 'for', 'with', 'from', 'into', 'upon', 'as', 'is', 'are', 'was',
    'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
    'will', 'would', 'could', 'should', 'may', 'might', 'shall', 'can',
    'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she',
    'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his',
    'our', 'their', 'who', 'which', 'what', 'when', 'where', 'how', 'not',
    'no', 'nor', 'if', 'so', 'yet', 'then', 'also', 'just', 'very', 'more',
    'most', 'than', 'all', 'any', 'each', 'every', 'some', 'such', 'out',
    'up', 'over', 'about', 'after', 'before', 'through', 'while', 'although',
    'even', 'only', 'both', 'either', 'neither', 'said', 'says', 'say',
    'surely', 'indeed', 'truly', 'verily',
})


def _content_words(text):
    """Return lowercase content words, stripping punctuation and stopwords."""
    return [w for w in re.findall(r'[a-z]+', text.lower())
            if w not in _STOPWORDS]


def _anchor_end(word_en, translation, hint_pos, punct_breaks, word_breaks):
    """Find where a word-by-word boundary phrase ends in the polished translation.

    Searches for content words of word_en in translation near hint_pos, then
    snaps to the next punctuation break (if within 35 chars) or word boundary.

    word_en      – word-by-word English for the last Arabic word of a block
    translation  – full polished English for the verse
    hint_pos     – expected position (from word-count fraction × en_len)
    punct_breaks – positions right after punctuation + space
    word_breaks  – positions at the start of each word

    Returns a break position, or None if no reliable anchor is found.
    """
    content = _content_words(word_en)
    if not content:
        return None

    trans_lower = translation.lower()

    # Try from the last content word backwards (most specific first)
    for anchor in reversed(content):
        positions = []
        start = 0
        while True:
            idx = trans_lower.find(anchor, start)
            if idx == -1:
                break
            # Require whole-word match
            pre_ok = idx == 0 or not trans_lower[idx - 1].isalpha()
            suf_ok = (idx + len(anchor) >= len(trans_lower)
                      or not trans_lower[idx + len(anchor)].isalpha())
            if pre_ok and suf_ok:
                positions.append(idx + len(anchor))  # position after matched word
            start = idx + 1

        if not positions:
            continue

        # Prefer occurrences at or after hint_pos; fall back to closest overall
        after = [p for p in positions if p >= hint_pos]
        best = (min(after, key=lambda p: p - hint_pos) if after
                else min(positions, key=lambda p: abs(p - hint_pos)))

        # Snap to next punctuation break within 35 chars
        near_punct = [b for b in punct_breaks if best <= b <= best + 35]
        if near_punct:
            return near_punct[0]

        # No nearby punctuation — use the next word boundary
        next_wb = [b for b in word_breaks if b > best]
        return next_wb[0] if next_wb else best

    return None


def build_verse_blocks(srt_blocks, translation, verse_norm='', verse_words=None,
                       verse_arabic='', ayah_num=0):
    """Given a verse's SRT blocks and its translation, produce output blocks.

    Uses word-by-word API data (verse_words) to anchor English split points
    directly to specific words in the polished translation.  Falls back to
    character-level fuzzy matching and then proportional splitting when
    word data is unavailable.

    verse_words:  list of (raw_arabic, norm_arabic, en_translation) tuples.
    verse_arabic: full polished Arabic text for the verse (for fallbacks).
    ayah_num:     verse number for warning messages.

    Arabic splitting priority: word-by-word > proportional > Whisper.
    Returns list of (start, end, arabic, english).
    """
    if not srt_blocks:
        return []

    n = len(srt_blocks)
    if n == 1:
        b = srt_blocks[0]
        ar = verse_arabic or b['text']
        return [(ts_start(b['timestamp']), ts_end(b['timestamp']),
                 ar, translation)]

    en_len = len(translation)

    # Preferred break points: right after punctuation + space.
    # Skip punctuation that immediately follows a closing bracket (] or ˺) —
    # these are editorial insertions like "[The brothers said]," that aren't
    # semantic clause boundaries.
    punct_breaks = [0]
    for i in range(en_len - 1):
        if translation[i] in ',.!?;:' and translation[i + 1] == ' ':
            if i > 0 and translation[i - 1] == ']':
                continue
            punct_breaks.append(i + 2)
    punct_breaks.append(en_len)

    # Fallback break points: start of each word
    word_breaks = [0]
    for i in range(1, en_len):
        if translation[i - 1] == ' ':
            word_breaks.append(i)
    word_breaks.append(en_len)

    all_breaks = sorted(set(punct_breaks + word_breaks))

    def snap(pos):
        before = [b for b in punct_breaks if b <= pos]
        after  = [b for b in punct_breaks if b > pos]
        if not before:
            nearest_punct = min(after)
        elif not after:
            nearest_punct = max(before)
        else:
            bb, fa = max(before), min(after)
            bd, fd = pos - bb, fa - pos
            nearest_punct = bb if 2 * bd < fd else fa
        pd = abs(nearest_punct - pos)
        nearest_word = min(word_breaks, key=lambda b: abs(b - pos))
        wd = abs(nearest_word - pos)
        threshold = max(2 * wd + 30, 45)
        return nearest_punct if pd <= threshold else nearest_word

    # Proportional fallback using Arabic character lengths
    ar_lens = [max(len(b['norm']), 1) for b in srt_blocks]
    total_ar = sum(ar_lens)
    cum_ar = [sum(ar_lens[:i]) for i in range(n)]

    # Extract Arabic word list and pre-compute word ranges for all blocks
    # verse_words is list of (raw_arabic, norm_arabic, english) 3-tuples
    raw_ar_words = [raw for raw, _, _ in verse_words] if verse_words else []
    ar_words = [norm for _, norm, _ in verse_words] if verse_words else []
    # Pre-split verse_arabic for proportional fallback (used if word data unavailable)
    ar_words_full = verse_arabic.split() if verse_arabic else []
    nw = len(ar_words)
    word_ranges = [
        _match_word_range(b['norm'], ar_words) if ar_words else None
        for b in srt_blocks
    ]

    results = []
    cursor = 0  # current position in the English translation

    for i, b in enumerate(srt_blocks):
        wr = word_ranges[i]
        is_last = (i == n - 1)
        prev_wr = word_ranges[i - 1] if i > 0 else None
        is_repetition = (wr is not None and prev_wr is not None
                         and wr[0] < prev_wr[1])

        # ── en_start ──────────────────────────────────────────────────
        if i == 0:
            en_start = 0
        elif is_repetition and wr is not None and nw:
            # Reciter went back — derive start from Arabic word fraction
            en_start = snap(round(wr[0] / nw * en_len))
        else:
            en_start = cursor

        # ── en_end ────────────────────────────────────────────────────
        if is_last:
            en_end = en_len
        else:
            anchor = None
            if wr is not None and verse_words and nw:
                last_word_en = verse_words[wr[1] - 1][2]
                hint = round(wr[1] / nw * en_len)
                anchor = _anchor_end(last_word_en, translation, hint,
                                     punct_breaks, word_breaks)

            if anchor is not None:
                en_end = max(en_start + 1, anchor)
            else:
                # Fallback: fraction-based snap
                if wr is not None and nw:
                    end_frac = wr[1] / nw
                elif verse_norm:
                    pos = _verse_position(b['norm'], verse_norm)
                    end_frac = (pos[1] if pos is not None
                                else (cum_ar[i] + ar_lens[i]) / total_ar)
                else:
                    end_frac = (cum_ar[i] + ar_lens[i]) / total_ar
                en_end = snap(round(end_frac * en_len))

        # Ensure non-empty slice
        if en_start >= en_end:
            later = [bp for bp in all_breaks if bp > en_start]
            en_end = later[0] if later else en_len

        english = translation[en_start:en_end].strip() or translation.strip()

        # ── Arabic slice ──────────────────────────────────────────────
        if wr is not None and raw_ar_words:
            # Primary: use word-by-word raw Arabic
            arabic = ' '.join(raw_ar_words[wr[0]:wr[1]])
        elif verse_arabic:
            # Fallback: proportional split of verse_arabic at space boundaries
            print(f'WARNING: Using proportional Arabic split for block '
                  f'{i+1}/{n} of verse {ayah_num}')
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
        cursor = en_end

    return results


# ── Output ──────────────────────────────────────────────────────────

def _srt_to_ms(s: str) -> int:
    """'HH:MM:SS,mmm' → total milliseconds."""
    h, m, rest = s.split(':')
    sec, ms = rest.split(',')
    return int(h) * 3_600_000 + int(m) * 60_000 + int(sec) * 1_000 + int(ms)


def to_arabic_numeral(n):
    """Convert an integer to Arabic-Indic numeral string (e.g., 4 -> '٤')."""
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    return ''.join(arabic_digits[int(d)] for d in str(n))


def build_output(blocks, verses, assignments, word_data=None, return_segments=False):
    """Assemble the final SRT string.

    If return_segments=True, returns (srt_string, segments) where segments is a
    list of (start_ms, end_ms, arabic, english) tuples ready for write_ass(),
    bypassing the need to re-parse the SRT file.
    """
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
        ayah_num = int(verses[vi]['ref'].split(':')[1])
        # Strip trailing Arabic-Indic verse number (already embedded in source Arabic)
        # so we don't end up with the number on both ends after prepending our own.
        verse_arabic = re.sub(r'[\u0660-\u0669]+\s*$', '', verses[vi]['arabic']).strip()
        verse_words = word_data.get(ayah_num) if word_data else None
        merged = build_verse_blocks(vblocks, translation,
                                    verse_norm=verses[vi]['norm'],
                                    verse_words=verse_words,
                                    verse_arabic=verse_arabic,
                                    ayah_num=ayah_num)
        for idx_in_verse, (start, end, arabic, english) in enumerate(merged):
            if idx_in_verse == 0:
                arabic = to_arabic_numeral(ayah_num) + ' ' + arabic
                english = str(ayah_num) + '. ' + english
            all_output.append((start, end, arabic, english))

    # Format as SRT — sanitize fields so embedded newlines can't corrupt the
    # block structure if the file is re-parsed later (option C).
    lines = []
    for idx, (start, end, arabic, english) in enumerate(all_output, 1):
        lines.append(str(idx))
        lines.append(f'{start} --> {end}')
        lines.append(arabic.replace('\r', '').replace('\n', ' '))
        lines.append(english.replace('\r', '').replace('\n', ' '))
        lines.append('')

    srt = '\n'.join(lines)

    if return_segments:
        segments = [
            (_srt_to_ms(s), _srt_to_ms(e), ar, en)
            for s, e, ar, en in all_output
        ]
        return srt, segments
    return srt


# ── Main ────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print('Usage: python add_translation.py <translation.txt> <subtitles.srt> [output.srt]')
        print()
        print('  translation.txt  Quran translation file (chapter:verse format)')
        print('  subtitles.srt    SRT subtitle file with Arabic recitation')
        print('  output.srt       Output file (default: <input> translated.srt)')
        sys.exit(1)

    trans_file = sys.argv[1]
    srt_file = sys.argv[2]
    out_file = sys.argv[3] if len(sys.argv) >= 4 else None

    if not out_file:
        base, ext = os.path.splitext(srt_file)
        out_file = f'{base} translated{ext}'

    # Parse inputs
    verses = parse_translation_file(trans_file)
    print(f'Parsed {len(verses)} verses from: {trans_file}')

    blocks = parse_srt(srt_file)
    print(f'Parsed {len(blocks)} subtitle blocks from: {srt_file}')

    # Match SRT blocks to verses
    assignments = match_blocks_to_verses(blocks, verses)
    matched_verses = set(assignments)
    print(f'Matched to {len(matched_verses)} unique verses')

    # Report any unmatched verses
    all_vi = set(range(len(verses)))
    missing = all_vi - matched_verses
    if missing:
        print(f'\nWARNING: {len(missing)} verse(s) had no matching subtitle block:')
        for vi in sorted(missing):
            print(f'  - {verses[vi]["ref"]}')

    # Load word-by-word Arabic data for accurate English positioning
    word_data = {}
    if verses:
        try:
            chapter = int(verses[0]['ref'].split(':')[0])
            print(f'Fetching word-by-word data for chapter {chapter} ...')
            word_data = load_word_data(chapter)
            if word_data:
                print(f'  Loaded word data for {len(word_data)} verses')
            else:
                print('  Word-by-word data unavailable; falling back to character matching')
        except (ValueError, IndexError):
            pass

    # Build and write output
    output = build_output(blocks, verses, assignments, word_data=word_data)

    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(output)

    print(f'\nOutput written to: {out_file}')


if __name__ == '__main__':
    main()
