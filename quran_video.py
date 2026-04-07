#!/usr/bin/env python3
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
from __future__ import annotations

import re
import sys
import textwrap
import subprocess
from pathlib import Path


# ── Time helpers ──────────────────────────────────────────────────────────────

def srt_to_ms(s: str) -> int:
    """'HH:MM:SS,mmm' → total milliseconds"""
    h, m, rest = s.split(":")
    sec, ms = rest.split(",")
    return int(h) * 3_600_000 + int(m) * 60_000 + int(sec) * 1_000 + int(ms)


def ms_to_ass(ms: int) -> str:
    """Total milliseconds → ASS timestamp 'H:MM:SS.cc'"""
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h}:{m:02d}:{s:02d}.{ms // 10:02d}"


# ── File parsers ──────────────────────────────────────────────────────────────

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


# ── ASS subtitle generation ───────────────────────────────────────────────────

def _wrap_ass(text: str, width: int) -> str:
    r"""Word-wrap text, joining lines with the ASS hard line-break marker \N."""
    return r"\N".join(textwrap.wrap(text, width=width))


def _esc_ass(text: str) -> str:
    """Escape characters that have special meaning inside ASS dialogue text."""
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def write_ass(
    segments: list[tuple[int, int, str, str]],
    out_path: str,
    *,
    res: tuple[int, int] = (1920, 1080),
    timing_offset_ms: int = 300,
) -> None:
    """Write an ASS v4+ subtitle file with centered Arabic + English text.

    segments: list of (start_ms, end_ms, arabic, english)
    timing_offset_ms: delay subtitle appearance by this many ms (default 200)
    """
    W, H = res
    # Scale font sizes proportionally to resolution height
    ar_font_size = round(56 * H / 1080)
    en_font_size = round(48 * H / 1080)
    margin = round(40 * H / 1080)
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
        # Centered style (Alignment=5), base font is Times New Roman for English
        f"Style: Default,Times New Roman,{en_font_size},"
        "&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,0,0,5,{margin},{margin},{margin},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, "
        "MarginL, MarginR, MarginV, Effect, Text\n"
    )

    event_lines: list[str] = []
    for start_ms, end_ms, arabic, english in segments:
        start = ms_to_ass(max(0, start_ms + timing_offset_ms))
        end = ms_to_ass(end_ms)
        ar_text = _esc_ass(arabic)
        # Escape first, then wrap — so \N line breaks don't get escaped
        en_text = _wrap_ass(_esc_ass(english), en_wrap_width)
        # Combine: Arabic in Traditional Arabic font, blank line, then English
        combined = (
            r"{\fnTraditional Arabic\fs"
            + str(ar_font_size)
            + r"}"
            + ar_text
            + r"\N\N"
            + r"{\fnTimes New Roman\fs"
            + str(en_font_size)
            + r"}"
            + en_text
        )
        event_lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{combined}"
        )

    Path(out_path).write_text(
        header + "\n".join(event_lines) + "\n",
        encoding="utf-8-sig",
    )


# ── FFmpeg helpers ────────────────────────────────────────────────────────────

def _esc_filter_path(path: str) -> str:
    """
    Escape a file path for embedding in an FFmpeg filtergraph string.
    Converts backslashes → forward slashes, then escapes the Windows
    drive-letter colon (C: → C\\:) so FFmpeg doesn't treat it as an
    option separator.
    """
    p = path.replace("\\", "/")
    if len(p) >= 2 and p[1] == ":":          # Windows drive letter colon
        p = p[0] + "\\:" + p[2:]
    return p


# ── Main ──────────────────────────────────────────────────────────────────────

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


if __name__ == "__main__":
    main()
