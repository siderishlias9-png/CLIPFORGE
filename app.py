import os
import re
import json
import math
import tempfile
import subprocess
import shutil
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
import requests

st.set_page_config(page_title="ClipForge AI", page_icon="✂️", layout="wide")

# ---------- Theme ----------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background: radial-gradient(circle at 12% 0%, #20234b 0, #101321 34%, #0b0d16 75%); color: #f5f6ff; }
.block-container { max-width: 1120px; padding-top: 2.2rem; }
.hero { padding: 26px 28px; border: 1px solid #34395e; border-radius: 22px;
background: linear-gradient(120deg, rgba(94,76,220,.25), rgba(27,169,178,.10));
box-shadow: 0 18px 55px rgba(0,0,0,.22); }
.eyebrow { color:#a9a5ff; font-size:12px; font-weight:800; letter-spacing:2px; text-transform:uppercase; }
.hero h1 { font-size: clamp(34px, 5vw, 54px); margin:8px 0 4px; line-height:1.05; }
.hero p { color:#b9bfd6; font-size:16px; margin:8px 0 0; }
.pill { display:inline-block; padding:6px 10px; border-radius:30px; border:1px solid #41476d; color:#c9caff; font-size:12px; margin-right:6px; }
.panel { background:rgba(23,27,45,.86); border:1px solid #303653; padding:18px; border-radius:18px; }
.smallmuted { color:#9ba4c1; font-size:13px; }
.clipcard { border:1px solid #343b5c; background:#171b2d; border-radius:16px; padding:16px; margin:12px 0; }
div[data-testid="stButton"] button { border-radius:12px; font-weight:700; min-height:44px; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <div class="eyebrow">CREATOR TOOLKIT · LOCAL AI</div>
  <h1>ClipForge <span style="color:#9b91ff">AI</span></h1>
  <p>Turn a long video into short, captioned clips — without Vizard or a paid API key.</p>
  <div style="margin-top:16px">
    <span class="pill">✦ Open-source engine</span><span class="pill">9:16 ready</span><span class="pill">No API key</span>
  </div>
</div>
""", unsafe_allow_html=True)

# ---------- Utilities ----------
def ffmpeg_path():
    return shutil.which("ffmpeg")

def run_cmd(args):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout)[-2500:])
    return p

def safe_filename(name):
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    return name[:80] or "video"

def fetch_direct_video(url, dest):
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Enter a valid http(s) video-file URL.")
    # Only fetch direct media files; do not scrape platform pages or bypass access controls.
    r = requests.get(url.strip(), stream=True, timeout=(15, 60), headers={"User-Agent": "ClipForgeAI/1.0"})
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").lower()
    if not (ctype.startswith("video/") or parsed.path.lower().endswith((".mp4", ".mov", ".mkv", ".webm", ".m4v"))):
        raise ValueError("That link does not look like a direct video file. Upload the video instead.")
    total = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            if chunk:
                total += len(chunk)
                if total > 2_000_000_000:
                    raise ValueError("The video is larger than the 2 GB import limit.")
                f.write(chunk)
    if total == 0:
        raise ValueError("The video file was empty.")

def get_duration(path):
    out = run_cmd(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=noprint_wrappers=1:nokey=1", str(path)]).stdout.strip()
    return float(out)

def transcribe(path, model_size="tiny"):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(path), vad_filter=True, word_timestamps=False)
    return [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()} for s in segments if s.text.strip()]

def rank_segments(segments):
    # Lightweight transcript-based highlight ranking; not a claim of perfect virality prediction.
    hooks = ["you won't believe", "the truth", "secret", "mistake", "never", "best", "worst",
             "why", "how", "insane", "crazy", "important", "actually", "finally", "imagine",
             "the problem", "here's", "listen", "wait", "number one"]
    scored = []
    for i, seg in enumerate(segments):
        text = seg["text"].lower()
        words = re.findall(r"\b[\w']+\b", text)
        if not words:
            continue
        score = min(len(words), 28) * 0.7
        score += sum(2.2 for h in hooks if h in text)
        score += 1.5 if "?" in seg["text"] else 0
        score += 1.0 if "!" in seg["text"] else 0
        score += 1.2 if any(w.isupper() and len(w) > 2 for w in seg["text"].split()) else 0
        # Slight preference for complete, conversational sections.
        score += min(2.0, max(0, seg["end"] - seg["start"]) * 0.35)
        scored.append((score, i))
    return scored

def build_windows(segments, duration, clip_seconds, count):
    ranked = rank_segments(segments)
    candidates = []
    for score, idx in ranked:
        s = segments[idx]
        center = (s["start"] + s["end"]) / 2
        start = max(0, center - clip_seconds * 0.42)
        end = min(duration, start + clip_seconds)
        start = max(0, end - clip_seconds)
        if end - start < min(8, clip_seconds * .55):
            continue
        # Expand around neighboring transcript content to preserve context.
        for prev in reversed(segments[:idx]):
            if start - prev["end"] <= 2.5 and start - prev["start"] < clip_seconds * .55:
                start = max(0, prev["start"] - .2)
            else:
                break
        for nxt in segments[idx+1:]:
            if nxt["start"] - end <= 2.5 and nxt["end"] - start <= clip_seconds * 1.25:
                end = min(duration, nxt["end"] + .2)
            else:
                break
        if end - start > clip_seconds * 1.35:
            end = start + clip_seconds * 1.35
        candidates.append((score, start, end, s["text"]))
    candidates.sort(reverse=True)
    chosen = []
    for score, start, end, text in candidates:
        if all(end <= a or start >= b for _, a, b, _ in chosen):
            chosen.append((score, start, end, text))
        if len(chosen) >= count:
            break
    if not chosen:
        chosen = [(1, 0, min(duration, clip_seconds), "")]
    return sorted(chosen, key=lambda x: x[1])

def srt_time(seconds):
    ms = int(max(0, seconds) * 1000)
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def write_srt(segments, start, end, out):
    rows = []
    n = 1
    for seg in segments:
        a, b = max(start, seg["start"]), min(end, seg["end"])
        if b <= a:
            continue
        rows.extend([str(n), f"{srt_time(a-start)} --> {srt_time(b-start)}", seg["text"], ""])
        n += 1
    Path(out).write_text("\n".join(rows), encoding="utf-8")

def make_clip(source, out, start, end, ratio, caption_mode, segments, tempdir):
    dur = max(.5, end-start)
    args = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{dur:.3f}"]
    filters = []
    if ratio == "9:16":
        filters.append("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
    elif ratio == "1:1":
        filters.append("scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080")
    elif ratio == "4:5":
        filters.append("scale=1080:1350:force_original_aspect_ratio=increase,crop=1080:1350")
    else:
        filters.append("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
    if caption_mode == "Burn captions":
        srt = Path(tempdir) / (Path(out).stem + ".srt")
        write_srt(segments, start, end, srt)
        # Escape path for ffmpeg subtitles filter.
        srt_path = str(srt).replace("\\", "/").replace(":", r"\:")
        filters.append(f"subtitles='{srt_path}':force_style='FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginV=90'")
    args += ["-vf", ",".join(filters), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)]
    run_cmd(args)

# ---------- Interface ----------
left, right = st.columns([1.25, .75], gap="large")
with left:
    st.markdown("### ① Add your video")
    upload = st.file_uploader("Upload a video file", type=["mp4", "mov", "mkv", "webm", "m4v"])
    st.markdown("<div class='smallmuted'>Or use a direct, publicly accessible video-file URL (MP4/MOV/WebM). Platform watch-page links are not downloaded.</div>", unsafe_allow_html=True)
    url = st.text_input("Direct video URL", placeholder="https://example.com/video.mp4")
with right:
    st.markdown("### ② Clip settings")
    clip_len = st.select_slider("Target clip length", options=[15, 20, 30, 45, 60, 90], value=30, format_func=lambda x: f"{x} sec")
    clip_count = st.slider("Number of clips", 1, 10, 5)
    ratio = st.selectbox("Video format", ["9:16", "1:1", "4:5", "16:9"], index=0)
    model = st.selectbox("Transcription model", ["tiny", "base", "small"], index=0,
                         help="Tiny is fastest and uses the least memory. Models download automatically on first run.")
    captions = st.selectbox("Captions", ["Burn captions", "No captions"])

st.markdown("")
st.markdown("<div class='panel'><b>How it works</b><br><span class='smallmuted'>ClipForge transcribes the video locally, scores promising moments from the transcript, selects non-overlapping sections, then renders MP4 clips with FFmpeg. The highlight score is a heuristic, not a guaranteed viral score.</span></div>", unsafe_allow_html=True)

if not ffmpeg_path() or not shutil.which("ffprobe"):
    st.error("FFmpeg/FFprobe is missing. Install the system package from packages.txt and redeploy.")
    st.stop()

if st.button("✂️  Generate my clips", type="primary", use_container_width=True):
    if not upload and not url.strip():
        st.warning("Upload a video or paste a direct video-file URL first.")
        st.stop()
    workdir = Path(tempfile.mkdtemp(prefix="clipforge_"))
    source = workdir / "source_video"
    try:
        with st.status("Preparing your video…", expanded=True) as status:
            if upload:
                ext = Path(upload.name).suffix or ".mp4"
                source = source.with_suffix(ext)
                source.write_bytes(upload.getbuffer())
                st.write(f"Loaded **{upload.name}**")
            else:
                st.write("Fetching the direct video file…")
                fetch_direct_video(url, source.with_suffix(".mp4"))
                source = source.with_suffix(".mp4")
            duration = get_duration(source)
            st.write(f"Video duration: **{duration/60:.1f} minutes**")
            st.write("Transcribing speech with the open-source Whisper model…")
            transcript = transcribe(source, model)
            if not transcript:
                raise RuntimeError("No speech was detected. Try another video or use a clearer audio track.")
            st.write(f"Transcribed **{len(transcript)} speech segments**")
            windows = build_windows(transcript, duration, clip_len, clip_count)
            output_dir = workdir / "clips"
            output_dir.mkdir()
            rendered = []
            for i, (score, start, end, hook) in enumerate(windows, 1):
                out = output_dir / f"clipforge_clip_{i:02}.mp4"
                st.write(f"Rendering clip {i}/{len(windows)}…")
                make_clip(source, out, start, end, ratio, captions, transcript, workdir)
                rendered.append((out, start, end, score, hook))
            status.update(label="Your clips are ready!", state="complete", expanded=False)
        st.session_state["clipforge_results"] = [(str(p), a, b, sc, hook) for p,a,b,sc,hook in rendered]
        st.session_state["clipforge_dir"] = str(workdir)
    except Exception as e:
        st.error(f"Couldn't finish processing: {e}")
        st.caption("If this is a deployment memory or FFmpeg error, try a shorter video and the Tiny model.")
        shutil.rmtree(workdir, ignore_errors=True)

if st.session_state.get("clipforge_results"):
    st.markdown("## ③ Your clips")
    results = st.session_state["clipforge_results"]
    cols = st.columns(2)
    for i, (path, start, end, score, hook) in enumerate(results):
        p = Path(path)
        with cols[i % 2]:
            st.markdown(f"<div class='clipcard'><b>Clip {i+1}</b><br><span class='smallmuted'>{start:.1f}s – {end:.1f}s · {end-start:.0f}s</span></div>", unsafe_allow_html=True)
            if p.exists():
                st.video(str(p))
                st.download_button("⬇️ Download MP4", data=p.read_bytes(), file_name=p.name,
                                   mime="video/mp4", key=f"download_{i}", use_container_width=True)
    st.success("Download the clips you want. You can then upload them to your social platforms.")
st.markdown("---")
st.markdown("<div class='smallmuted'>ClipForge Free · No Vizard account, Vizard API key, or paid clipping API required. Video processing happens on the server running this app. Only process videos you have permission to use. Platform links that require login, subscriptions, or access circumvention are not supported.</div>", unsafe_allow_html=True)
