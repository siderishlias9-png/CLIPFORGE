CLIPFORGE AI — FREE BUILD

This version removes the Vizard API dependency. It uses:
- faster-whisper (open-source speech transcription)
- FFmpeg (video editing/rendering)
- Streamlit (mobile-friendly web interface)

SETUP ON STREAMLIT COMMUNITY CLOUD
1. Upload app.py, requirements.txt, and packages.txt to the root of your GitHub repository.
2. Commit the changes and wait for Streamlit to redeploy.
3. No API key or Vizard account is needed.
4. Open the app, upload an MP4/MOV/MKV/WebM video, choose settings, and generate clips.

IMPORTANT
- This version does not scrape YouTube/Twitch watch pages. Use an uploaded video or a direct public video-file URL.
- Videos that require login, cookies, payment, or bypassing platform protections are not supported.
- Whisper model files download on first use. Tiny is selected by default to reduce memory use.
- Free hosting has CPU, memory, and execution limits. Long videos may time out; start with a shorter video.
- The transcript ranking is a lightweight heuristic, not a guarantee of virality.
- The server processes uploaded videos. Do not upload private or sensitive footage to a public deployment.
- Use only material you have permission to process and publish.
