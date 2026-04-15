# Breath-Pause Segmentation Design

**Date:** 2026-04-14  
**Status:** Approved

## Problem

Whisper's default segmentation groups multiple reciter breath-pauses into a single SRT block. The subtitle doesn't change when the reciter pauses mid-verse, leaving the viewer reading text that's behind the audio.

## Goal

Split SRT blocks at every breath pause — every time the reciter stops, even briefly, a new block starts. Granularity: one segment per breath pause.

## Approach: Word Timestamps + Gap Detection

Enable `word_timestamps=True` in the faster-whisper `transcribe()` call. This gives per-word `.start`/`.end` timing. Walk the flattened word list and cut a new SRT block whenever the silence gap between consecutive words meets or exceeds a threshold.

## Implementation

### 1. Transcription call (`app.py`)

Add `word_timestamps=True` to `model.transcribe()`:

```python
segments_iter, info = model.transcribe(
    mp3_path,
    language='ar',
    temperature=0,
    beam_size=5,
    vad_filter=True,
    condition_on_previous_text=False,
    word_timestamps=True,   # <-- new
)
```

### 2. Tuning constant (`app.py`, module level)

```python
BREATH_PAUSE_MS = 0.4  # seconds — gap >= this triggers a new SRT block
```

### 3. SRT-building loop (`app.py`)

Replace the current one-segment-per-block loop with a word-gap splitter:

```python
all_words = []
for seg in segments_iter:
    if seg.words:
        all_words.extend(seg.words)

srt_lines = []
idx = 1
group = []
for i, w in enumerate(all_words):
    group.append(w)
    is_last = (i == len(all_words) - 1)
    gap = (all_words[i + 1].start - w.end) if not is_last else None
    if is_last or gap >= BREATH_PAUSE_MS:
        start = _format_srt_time(group[0].start)
        end = _format_srt_time(group[-1].end)
        text = ' '.join(w.word.strip() for w in group)
        srt_lines.append(f'{idx}\n{start} --> {end}\n{text}\n')
        idx += 1
        group = []
```

## Edge Cases

| Case | Handling |
|------|----------|
| Segment with empty `.words` | Skipped — no block emitted |
| Single-word block | Allowed — valid breath pause boundary |
| Gap between Whisper segments | Real audio gap, naturally triggers a split |
| Last word in stream | Closes the current group, no special case |

## Unchanged

- `match_blocks_to_verses()` — handles any number of blocks
- `build_verse_blocks()` / Arabic + English splitting — unchanged
- `write_ass()` / video generation — unchanged

## Tuning

If splits are too aggressive (splitting where there's no real pause): raise `BREATH_PAUSE_MS` (e.g. 0.5, 0.6).  
If long segments still appear: lower it (e.g. 0.3).
