# ClipForge AI — free upgraded build

## Features
- Upload MP4, MOV, MKV or WebM, or provide a direct public video-file URL
- Automatic speech transcription with faster-whisper
- Transcript-based highlight selection, with fill logic for the requested clip count (up to 10)
- Suggested editable titles for every clip
- Animated ASS subtitles with fade/pop-in animation and two-line wrapping
- Smooth video and audio fade transitions
- Optional generated whoosh-like sound accent
- Vertical 9:16, square 1:1 and landscape 16:9 MP4 export
- Download individual clips or all clips in one ZIP

## Deploy on Streamlit Community Cloud
1. Create a GitHub repository.
2. Upload `app.py`, `requirements.txt`, and `packages.txt`.
3. Create a Streamlit app pointing to `app.py`.

## Important limitations
- URL input must be a direct, publicly accessible video file. YouTube/Twitch watch-page URLs, private videos, login-protected pages and DRM-restricted streams are not supported.
- Free hosting has CPU, RAM and execution-time limits. Start with short videos and the `tiny` Whisper model.
- Highlight selection is transcript-based, not a guaranteed viral-content detector.
- FFmpeg must include the `ass` subtitle filter (normally provided by standard FFmpeg builds).

## Run locally
Install FFmpeg, then:
```bash
pip install -r requirements.txt
streamlit run app.py
```
