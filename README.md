# ClipForge AI v5 — upgraded build

## What's new
- Word-level Whisper timestamps and karaoke-style animated captions
- Controls for subtitle size and how many words appear together
- Presets for quick testing, balanced output, 10 clips, longer clips, and higher transcription accuracy
- Custom controls for clip count, duration and Whisper model
- More meaningful transcript-based title suggestions, preserving Greek and other scripts; titles remain editable
- YouTube URL input using yt-dlp for publicly accessible videos
- Direct public video-file URL and upload options
- Smooth video/audio fades, optional generated whoosh accent
- 9:16, 1:1 and 16:9 output
- Individual MP4 downloads and ZIP download for all clips

## Deploy
Upload `app.py`, `requirements.txt`, `packages.txt` to your GitHub repository connected to Streamlit Community Cloud. It should rebuild automatically.

## YouTube note
YouTube link support uses yt-dlp's best-video-plus-best-audio selector with a combined-format fallback, rather than forcing MP4-only formats. It still depends on yt-dlp and YouTube's current delivery behavior, so it is not guaranteed for every video. This project does not use cookies, logins, DRM circumvention or access-control bypasses. Use videos you own or have permission to edit.

## Hosting limitations
Streamlit free hosting has CPU, RAM and execution-time limits. Start with shorter videos and the Tiny model. The Small model can be slow. Subtitle accuracy and title suggestions depend on transcription quality and may need edits.

## Run locally
Install FFmpeg, then:
```bash
pip install -r requirements.txt
streamlit run app.py
```
