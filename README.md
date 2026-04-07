# Quran Video Maker

Generate Quran recitation videos with Arabic and English subtitles on a black background.

## Requirements

- Python 3.9+
- [FFmpeg](https://ffmpeg.org/download.html) in your PATH (must include libass support, which is standard in most builds)

## Input Files

You need three files to get started:

### 1. Audio file (MP3)

An MP3 of the Quran recitation.

### 2. Subtitle file (SRT)

A standard SRT file with the Arabic recitation text (no translations). Each block contains the Arabic text for that time segment:

```
1
00:00:00,000 --> 00:00:04,700
ألف لام را

2
00:00:04,700 --> 00:00:08,980
تلك آيات الكتاب المبين
```

### 3. Translation file (TXT)

A text file with verse references, Arabic text (with diacritics), and English translations. You can copy this format from [quran.com](https://quran.com):

```
Joseph (12:1-111)

12:1
الٓر ۚ تِلْكَ ءَايَـٰتُ ٱلْكِتَـٰبِ ٱلْمُبِينِ ١
Alif-Lam-Ra. These are the verses of the clear Book.

12:2
إِنَّآ أَنزَلْنَـٰهُ قُرْءَٰنًا عَرَبِيًّۭا لَّعَلَّكُمْ تَعْقِلُونَ ٢
Indeed, We have sent it down as an Arabic Quran so that you may understand.
```

Each verse has:
- A reference line (`chapter:verse`)
- The Arabic text with diacritics (and verse number at the end)
- The English translation

## Usage

### Step 1: Add translations to the SRT

```bash
python add_translation.py <translation.txt> <subtitles.srt> [output.srt]
```

This matches each SRT subtitle block to its corresponding Quran verse using fuzzy Arabic text matching, then produces a new SRT with both Arabic and English lines:

```
1
00:00:00,000 --> 00:00:04,700
١ ألف لام را
1. Alif-Lam-Ra.
```

If no output path is given, it defaults to `<input> translated.srt`.

### Step 2: Generate the video

```bash
python quran_video.py <audio.mp3> <translated.srt> [output.mp4] [--resolution WxH]
```

This generates an MP4 with:
- Black background
- Arabic text in Traditional Arabic font (larger)
- English text in Times New Roman (smaller)
- Centered subtitles

Options:
- `output.mp4` — output path (default: `output.mp4`)
- `--resolution WxH` — video resolution (default: `1920x1080`)

## Example

```bash
# Add English translations to the Arabic SRT
python add_translation.py "surah yusuf translation.txt" "surah yusuf.srt"

# Generate the video
python quran_video.py "surah yusuf.mp3" "surah yusuf translated.srt" "surah yusuf.mp4"
```
