# EH-Clipper

**AI video clipper built for Indian audiences.** Turn long YouTube videos (podcasts, interviews, talks, site walkthroughs) into ready-to-post vertical clips for Reels, Shorts and TikTok, with Hindi and English subtitles that actually render.

Built and maintained by the Evank Homes / Nali Spaces team.

## What it does
1. Downloads the video at source quality.
2. Transcribes it with Faster-Whisper (Hindi, English or mixed Hinglish).
3. Uses Gemini to pick the strongest moments and write the hook.
4. Renders 9:16 clips with face tracking, a hook teaser, karaoke-style subtitles and thumbnails.

## What's different in EH-Clipper
- **Hindi + English subtitles:** `--font-style HINDI` uses Poppins, which covers both Devanagari and Latin, so Hindi text never turns into boxes.
- **Language control:** `--whisper-language hi|en`, or leave it on auto-detect.
- **Transcript cache:** re-running the same video skips transcription.
- **Sharper encode:** tuned for 1080p vertical output (`--video-cq 19`).
- **Colab-ready:** `notebooks/inhouse_colab.ipynb` runs on a free T4 GPU with the compatibility fixes already applied.

## Quick start (Google Colab)
1. Open `notebooks/inhouse_colab.ipynb` in Colab and select a **T4 GPU** runtime.
2. Add `GOOGLE_API_KEY` (Gemini) to Colab Secrets.
3. Run Cells 1, 1b and 2, set the YouTube link in Cell 3, then run Cells 3 and 4.
4. Your clips download as `clips.zip`.

## Command line
```bash
pip install -r requirements.txt
python main.py --url "<youtube-url>" --clips 5 --ratio 9:16 --font-style HINDI --video-cq 19
```
See `python main.py --help` for all options (aspect ratios, hook length, uploaders, B-roll, music).

## Credits and license
EH-Clipper is built on the open-source project [opensource-clipping](https://github.com/NaufalRizqullah/opensource-clipping) by Muhammad Naufal Rizqullah (MIT License). The original README is kept in `docs/UPSTREAM_README.md`. Our changes and additions are © Evank Homes. See `LICENSE`.
