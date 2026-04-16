#!/usr/bin/env python3
"""Quran Video Maker — local web app."""

import re
import json
import uuid
import time
import shutil
import threading
import subprocess
from queue import Queue, Empty
from pathlib import Path

import urllib.request as urlreq

from flask import Flask, request, jsonify, render_template, send_file, Response

app = Flask(__name__)

OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

# In-memory job store: job_id -> {status, queue, result_path, created}
jobs = {}

QURAN_API = 'https://api.quran.com/api/v4'
API_HEADERS = {'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0'}

# Minimum silence gap (seconds) between words that triggers a new SRT block.
BREATH_PAUSE_MS = 0.4


def fetch_translation(chapter, translation_id):
    """Fetch Arabic text + English translation for a chapter from quran.com.

    Returns a list of dicts matching the format of
    add_translation.parse_translation_file():
        [{ref, arabic, translation, norm}, ...]
    """
    from add_translation import normalize_arabic

    # Fetch Arabic text
    url = f'{QURAN_API}/quran/verses/uthmani?chapter_number={chapter}'
    req = urlreq.Request(url, headers=API_HEADERS)
    with urlreq.urlopen(req, timeout=30) as resp:
        ar_data = json.loads(resp.read().decode('utf-8'))

    # Fetch English translation
    url = f'{QURAN_API}/quran/translations/{translation_id}?chapter_number={chapter}'
    req = urlreq.Request(url, headers=API_HEADERS)
    with urlreq.urlopen(req, timeout=30) as resp:
        en_data = json.loads(resp.read().decode('utf-8'))

    ar_verses = ar_data.get('verses', [])
    en_verses = en_data.get('translations', [])

    if len(ar_verses) != len(en_verses):
        raise ValueError(
            f'Verse count mismatch: {len(ar_verses)} Arabic vs {len(en_verses)} English'
        )

    verses = []
    for i, (ar, en) in enumerate(zip(ar_verses, en_verses), 1):
        arabic = ar['text_uthmani'].strip()
        # Strip HTML footnote tags: <sup foot_note=N>X</sup>
        translation = re.sub(r'<sup[^>]*>.*?</sup>', '', en['text'])
        translation = re.sub(r'<[^>]+>', '', translation).strip()
        ref = f'{chapter}:{i}'
        verses.append({
            'ref': ref,
            'arabic': arabic,
            'translation': translation,
            'norm': normalize_arabic(arabic),
        })

    return verses


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/generate', methods=['POST'])
def generate():
    """Accept MP3 upload + settings, start pipeline in background thread."""
    cleanup_old_jobs()
    if 'mp3' not in request.files:
        return jsonify(error='No MP3 file uploaded'), 400

    mp3 = request.files['mp3']
    if not mp3.filename:
        return jsonify(error='No MP3 file selected'), 400

    surah = request.form.get('surah', type=int)
    if not surah or surah < 1 or surah > 114:
        return jsonify(error='Invalid surah number'), 400

    translation_id = request.form.get('translation', '20', type=str)
    resolution = request.form.get('resolution', '1920x1080')

    # Parse resolution
    try:
        w, h = resolution.lower().split('x')
        res = (int(w), int(h))
    except ValueError:
        return jsonify(error=f'Invalid resolution: {resolution}'), 400

    # Save MP3 to job directory
    job_id = uuid.uuid4().hex[:12]
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True)
    mp3_path = job_dir / 'input.mp3'
    mp3.save(str(mp3_path))

    # Optional: save custom translation file
    trans_path = None
    trans_file = request.files.get('translation_file')
    if trans_file and trans_file.filename:
        trans_path = str(job_dir / 'translation.txt')
        trans_file.save(trans_path)

    progress_queue = Queue()
    jobs[job_id] = {
        'status': 'running',
        'queue': progress_queue,
        'result_path': None,
        'created': time.time(),
    }

    # Start pipeline in background
    thread = threading.Thread(
        target=run_pipeline,
        args=(job_id, str(mp3_path), surah, int(translation_id), res,
              trans_path),
        daemon=True,
    )
    thread.start()

    return jsonify(job_id=job_id)


@app.route('/progress/<job_id>')
def progress(job_id):
    """SSE endpoint — streams progress events for a job."""
    job = jobs.get(job_id)
    if not job:
        return jsonify(error='Job not found'), 404

    def stream():
        q = job['queue']
        while True:
            try:
                event = q.get(timeout=30)
            except Empty:
                # Send keepalive
                yield 'data: {"step":"keepalive"}\n\n'
                continue
            yield f'data: {json.dumps(event)}\n\n'
            if event.get('step') in ('done', 'error'):
                break

    return Response(stream(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache',
                             'X-Accel-Buffering': 'no'})


@app.route('/download/<job_id>')
def download(job_id):
    """Serve the completed MP4 file."""
    job = jobs.get(job_id)
    if not job or not job.get('result_path'):
        return jsonify(error='File not ready'), 404
    return send_file(job['result_path'], as_attachment=True,
                     download_name='quran_video.mp4')


def run_pipeline(job_id, mp3_path, surah, translation_id, res,
                 trans_path=None):
    """Run the full pipeline. Sends progress via the job's queue.

    If trans_path is provided, uses the uploaded translation file instead
    of fetching from the quran.com API.
    """
    q = jobs[job_id]['queue']
    job_dir = OUTPUT_DIR / job_id

    try:
        # ── Step 1: Whisper transcription ──────────────────────────────
        q.put({'step': 'whisper', 'status': 'running'})

        from faster_whisper import WhisperModel
        model = WhisperModel('medium', device='auto', compute_type='default')
        segments_iter, info = model.transcribe(
            mp3_path,
            language='ar',
            temperature=0,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
            word_timestamps=True,
        )

        # Flatten words from all segments, skip segments with no word data
        all_words = []
        for seg in segments_iter:
            if seg.words:
                all_words.extend(seg.words)

        # Split into SRT blocks at every breath pause
        srt_lines = _words_to_srt_blocks(all_words)

        srt_path = str(job_dir / 'transcription.srt')
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_lines))

        q.put({'step': 'whisper', 'status': 'done'})

        # ── Step 2: Fetch translation + word-by-word data ──────────────
        q.put({'step': 'translation', 'status': 'running'})

        from add_translation import (
            parse_srt, parse_translation_file, match_blocks_to_verses,
            build_output, load_word_data,
        )
        from quran_video import write_ass

        if trans_path:
            verses = parse_translation_file(trans_path)
        else:
            verses = fetch_translation(surah, translation_id)
        word_data = load_word_data(surah)

        q.put({'step': 'translation', 'status': 'done'})

        # ── Step 3: Match subtitles to verses ──────────────────────────
        q.put({'step': 'matching', 'status': 'running'})

        blocks = parse_srt(srt_path)
        assignments = match_blocks_to_verses(blocks, verses)

        translated_srt, segments = build_output(blocks, verses, assignments,
                                               word_data=word_data,
                                               return_segments=True)

        translated_srt_path = str(job_dir / 'translated.srt')
        with open(translated_srt_path, 'w', encoding='utf-8') as f:
            f.write(translated_srt)

        q.put({'step': 'matching', 'status': 'done'})

        # ── Step 4: Generate ASS + FFmpeg ──────────────────────────────
        # segments comes directly from build_output — no SRT re-parse needed.
        q.put({'step': 'ffmpeg', 'status': 'running'})
        ass_path = str(job_dir / 'subtitles.ass')
        write_ass(segments, ass_path, res=res)

        output_path = str(job_dir / 'output.mp4')
        # Use relative paths + cwd to avoid Windows drive-letter colon escaping
        # issues in FFmpeg filtergraphs (C\: escaping broke in FFmpeg 8.0)
        cmd = [
            'ffmpeg', '-y',
            '-f', 'lavfi', '-i', f'color=c=black:s={res[0]}x{res[1]}:r=24',
            '-i', 'input.mp3',
            '-vf', 'ass=subtitles.ass',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '192k',
            '-shortest',
            '-pix_fmt', 'yuv420p',
            '-progress', 'pipe:1',
            'output.mp4',
        ]

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, cwd=str(job_dir),
        )

        # Drain stderr in a background thread to prevent pipe buffer deadlock
        stderr_lines = []
        def _drain_stderr():
            for line in proc.stderr:
                stderr_lines.append(line)
        t_stderr = threading.Thread(target=_drain_stderr, daemon=True)
        t_stderr.start()

        # Parse FFmpeg progress output from stdout
        duration_s = info.duration if info.duration else 0
        total_frames = int(duration_s * 24) if duration_s else 0

        for line in proc.stdout:
            line = line.strip()
            if line.startswith('frame='):
                try:
                    frame = int(line.split('=')[1])
                    pct = min(99, round(frame / total_frames * 100)) if total_frames else 0
                    q.put({'step': 'ffmpeg', 'status': 'running', 'percent': pct})
                except (ValueError, ZeroDivisionError):
                    pass

        proc.wait()
        t_stderr.join(timeout=5)
        if proc.returncode != 0:
            # Show the tail of stderr — the real error is after the version banner
            stderr = ''.join(stderr_lines)
            raise RuntimeError(f'FFmpeg failed:\n{stderr[-1500:]}')

        q.put({'step': 'ffmpeg', 'status': 'done'})

        # ── Done ───────────────────────────────────────────────────────
        jobs[job_id]['result_path'] = output_path
        jobs[job_id]['status'] = 'done'
        q.put({'step': 'done', 'download_url': f'/download/{job_id}'})

    except Exception as exc:
        jobs[job_id]['status'] = 'error'
        q.put({'step': 'error', 'detail': str(exc)})


def _format_srt_time(seconds):
    """Convert float seconds to SRT timestamp format HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


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


def cleanup_old_jobs(max_age_seconds=3600):
    """Remove job directories older than max_age_seconds."""
    now = time.time()
    for job_id in list(jobs.keys()):
        job = jobs[job_id]
        if now - job['created'] > max_age_seconds:
            job_dir = OUTPUT_DIR / job_id
            if job_dir.exists():
                shutil.rmtree(job_dir, ignore_errors=True)
            del jobs[job_id]


if __name__ == '__main__':
    import webbrowser
    port = 5000
    webbrowser.open(f'http://localhost:{port}')
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)
