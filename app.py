
import os, re, subprocess, tempfile, shutil, unicodedata, zipfile
from pathlib import Path
from urllib.parse import urlparse
import requests
import streamlit as st

st.set_page_config(page_title="ClipForge AI", page_icon="🎬", layout="wide")
st.markdown("""
<style>
.stApp{background:radial-gradient(circle at 10% 0%,#202c4b,#101522 42%,#0b0e16)}
.block-container{max-width:1160px;padding-top:1.7rem}
.hero{padding:25px 28px;border:1px solid #34415f;border-radius:20px;background:linear-gradient(120deg,#26375c,#151c2d);margin-bottom:20px}
.hero h1{font-size:2.3rem;margin:0;letter-spacing:-.04em}
.hero p{color:#c4cde0;margin:8px 0 0}
div[data-testid="stMetric"]{background:#ffffff0a;padding:14px;border:1px solid #303b52;border-radius:14px}
.stButton>button{border-radius:12px;font-weight:700;min-height:2.8rem}
</style>
<div class="hero"><h1>🎬 ClipForge <span style="color:#91adff">AI</span></h1>
<p>Find highlights, create word-synced captions, generate better titles and export ready-to-share clips.</p></div>
""", unsafe_allow_html=True)

def run_cmd(args, timeout=1200):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-3200:])
    return p.stdout.strip()

def video_duration(path):
    return float(run_cmd(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)]))

def has_audio(path):
    return bool(run_cmd(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=codec_type","-of","csv=p=0",str(path)]).strip())

def safe_filename(text):
    text=unicodedata.normalize("NFKC",text)
    text=re.sub(r"[^\w\- ]","",text,flags=re.UNICODE).strip().replace(" ","_")
    return (text[:65] or "clip")

def download_direct(url,dest):
    parsed=urlparse(url)
    if parsed.scheme not in ("http","https") or not parsed.netloc:
        raise ValueError("Enter a valid public http(s) video URL.")
    with requests.get(url,stream=True,timeout=(15,90),headers={"User-Agent":"ClipForge/1.0"}) as r:
        r.raise_for_status()
        if "text/html" in r.headers.get("content-type","").lower():
            raise ValueError("That URL is a webpage, not a direct video file. Choose YouTube link mode or use a direct MP4/MOV/WebM file URL.")
        size=0
        with open(dest,"wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk:
                    size+=len(chunk)
                    if size>1_500_000_000: raise ValueError("Video exceeds the 1.5 GB limit.")
                    f.write(chunk)

def download_youtube(url,dest):
    # yt-dlp only retrieves videos that are publicly accessible without login,
    # DRM circumvention, private access, or other access-control bypasses.
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("YouTube support is missing. Install the requirements.txt included in this project.")
    opts={
        "format":"best[ext=mp4]/best",
        "outtmpl":str(dest.with_suffix(".%(ext)s")),
        "noplaylist":True,
        "quiet":True,
        "no_warnings":True,
        "merge_output_format":"mp4",
        "max_filesize":1_500_000_000,
        "retries":2,
        "fragment_retries":2,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info=ydl.extract_info(url,download=True)
        requested=ydl.prepare_filename(info)
    got=Path(requested)
    if not got.exists():
        mp4=got.with_suffix(".mp4")
        if mp4.exists(): got=mp4
    if not got.exists():
        matches=list(dest.parent.glob(dest.stem+".*"))
        matches=[x for x in matches if x.suffix.lower() in (".mp4",".mkv",".webm")]
        if matches: got=matches[0]
    if not got.exists():
        raise RuntimeError("YouTube download did not produce a video file. The video may be unavailable or YouTube may have changed its delivery system.")
    if got != dest:
        shutil.move(str(got),str(dest))
    return dest

def transcribe(path,model_name,language):
    from faster_whisper import WhisperModel
    model=WhisperModel(model_name,device="cpu",compute_type="int8")
    opts={"vad_filter":True,"word_timestamps":True,"beam_size":5}
    lang_codes={"English":"en","Greek":"el","Spanish":"es","French":"fr","German":"de","Italian":"it","Portuguese":"pt","Japanese":"ja"}
    if language!="Auto detect": opts["language"]=lang_codes.get(language,language)
    segments,info=model.transcribe(str(path),**opts)
    rows=[]
    for seg in segments:
        words=[]
        for w in (getattr(seg,"words",None) or []):
            wt=(w.word or "").strip()
            if wt and w.start is not None and w.end is not None:
                words.append({"start":float(w.start),"end":float(w.end),"text":wt})
        txt=(seg.text or "").strip()
        if txt:
            rows.append({"start":float(seg.start),"end":float(seg.end),"text":txt,"words":words})
    return rows,getattr(info,"language",None)

def flatten_words(segments):
    result=[]
    for seg in segments:
        if seg["words"]:
            result.extend(seg["words"])
        else:
            # Fallback: spread segment text over its duration when word timestamps
            # are unavailable, keeping captions usable rather than omitting them.
            tokens=seg["text"].split()
            if not tokens: continue
            span=max(.1,seg["end"]-seg["start"])
            step=span/len(tokens)
            for i,t in enumerate(tokens):
                result.append({"start":seg["start"]+i*step,"end":seg["start"]+(i+1)*step,"text":t})
    return sorted(result,key=lambda x:x["start"])

def transcript_for(segments,a,b):
    return " ".join(s["text"] for s in segments if s["start"]<b and s["end"]>a).strip()

def score_text(text):
    t=text.lower()
    hooks=("but","because","secret","never","always","why","how","actually","insane","mistake","problem","best","worst","imagine","important","crazy","truth","wait","look","όμως","γιατί","πώς","αλήθεια","ποτέ","πάντα","λάθος")
    return min(len(t)/110,1.4)+sum(.35 for w in hooks if re.search(r"(?<!\w)"+re.escape(w)+r"(?!\w)",t)) + min(text.count("!")*.12,.5)+min(text.count("?")*.1,.4)

def choose_windows(segments,total,wanted,clip_len):
    length=min(float(clip_len),total)
    if total<=length: return [(0.0,total)]
    candidates=[]
    for seg in segments:
        center=(seg["start"]+seg["end"])/2
        start=max(0.0,min(total-length,center-length/2))
        text=transcript_for(segments,start,start+length)
        if text: candidates.append((score_text(text),start,start+length))
    candidates.sort(reverse=True)
    chosen=[]
    min_gap=max(2.0,length*.42)
    for sc,a,b in candidates:
        if all(abs(a-x[0])>=min_gap for x in chosen):
            chosen.append((a,b,sc))
        if len(chosen)>=wanted: break
    # Fill requested slots with evenly distributed windows; overlaps can occur
    # for short sources, but the UI reports that the moments may not be unique.
    missing=wanted-len(chosen)
    for i in range(missing):
        pos=(i+1)/(missing+1)*(total-length)
        chosen.append((pos,pos+length,0))
    chosen.sort(key=lambda x:x[0])
    return [(a,b) for a,b,_ in chosen[:wanted]]

def clean_sentence(s):
    s=re.sub(r"\s+"," ",s).strip(" \t\r\n-–—")
    s=re.sub(r"^(um+|uh+|like|you know|so|well|και|εε+|λοιπόν)\s*[,.:;-]?\s*","",s,flags=re.I)
    return s

def make_title(segments,a,b,index):
    text=transcript_for(segments,a,b)
    if not text: return f"Highlight {index}"
    # Prefer a complete, substantial sentence instead of blindly taking the
    # first eight words. Keep original language/script (including Greek).
    sentences=re.split(r"(?<=[.!?;])\s+",text)
    candidates=[]
    for sentence in sentences:
        s=clean_sentence(sentence)
        words=s.split()
        if len(words)<4: continue
        if len(words)>18: s=" ".join(words[:14]).rstrip(" ,;:") + "…"
        candidates.append(s)
    if candidates:
        chosen=max(candidates,key=lambda s:(min(len(s),115)*.02 + min(len(s.split()),14)*.12 + (0.5 if re.search(r"[.!?]$",s) else 0)))
        return chosen[:95]
    words=text.split()
    if len(words)>=5:
        return (" ".join(words[:9])).rstrip(" ,;:") + ("…" if len(words)>9 else "")
    return text[:70] or f"Highlight {index}"

def ass_time(sec):
    cs=int(max(0.0,sec)*100)
    h,rem=divmod(cs,360000); m,rem=divmod(rem,6000); s,c=divmod(rem,100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"

def ass_escape(s):
    return s.replace("\\","\\\\").replace("{","\\{").replace("}","\\}").replace("\n"," ")

def write_word_ass(segments,clip_start,clip_end,path,width,height,words_per_line=5,font_size=66):
    words=[w for w in flatten_words(segments) if w["end"]>clip_start and w["start"]<clip_end]
    header=[
      "[Script Info]","ScriptType: v4.00+",
      f"PlayResX: {width}",f"PlayResY: {height}","WrapStyle: 2","ScaledBorderAndShadow: yes","",
      "[V4+ Styles]",
      "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
      f"Style: Karaoke,Arial,{font_size},&H0000D7FF,&H00FFFFFF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,5,2,2,70,70,250,1","",
      "[Events]","Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]
    events=[]
    # Each event contains a short phrase; karaoke timing highlights each word
    # as it is spoken instead of displaying long, stale transcript blocks.
    group=[]
    def flush(group):
        if not group: return
        start=max(clip_start,group[0]["start"]); end=min(clip_end,group[-1]["end"])
        if end<=start: return
        pieces=[]
        for w in group:
            dur=max(1,int((min(clip_end,w["end"])-max(clip_start,w["start"]))*100))
            pieces.append(r"{\kf"+str(dur)+"}"+ass_escape(w["text"]))
        # Insert visual word gaps. Keep phrases compact for mobile screens.
        phrase=" ".join(pieces)
        events.append(f"Dialogue: 0,{ass_time(start-clip_start)},{ass_time(end-clip_start)},Karaoke,,0,0,0,,{{\\fad(70,100)}}{phrase}")
    for w in words:
        if group and (len(group)>=words_per_line or w["start"]-group[-1]["end"]>0.65):
            flush(group); group=[]
        group.append(w)
        if re.search(r"[.!?]$",w["text"]):
            flush(group); group=[]
    flush(group)
    Path(path).write_text("\n".join(header+events),encoding="utf-8")

def render_clip(src,a,b,out,ratio,segments,subtitles,whoosh,words_per_line,font_size):
    length=max(.2,b-a)
    if ratio=="9:16":
        vf="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"; w,h=1080,1920
    elif ratio=="1:1":
        vf="scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"; w,h=1080,1080
    else:
        vf="scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2"; w,h=1920,1080
    vf+=f",fps=30,fade=t=in:st=0:d=0.25,fade=t=out:st={max(0,length-.3):.3f}:d=0.3"
    assfile=None
    if subtitles:
        fd,assfile=tempfile.mkstemp(suffix=".ass"); os.close(fd)
        write_word_ass(segments,a,b,assfile,w,h,words_per_line,font_size)
        ap=assfile.replace("\\","/").replace(":","\\:")
        vf+=f",ass='{ap}'"
    try:
        if has_audio(src):
            af=f"afade=t=in:st=0:d=0.2,afade=t=out:st={max(0,length-.3):.3f}:d=0.3"
            if whoosh:
                fc=f"[0:v]{vf}[v];[0:a]{af}[a];anoisesrc=color=white:duration={length}:sample_rate=44100:amplitude=0.012,lowpass=f=1600,afade=t=in:st=0:d=0.03,afade=t=out:st={max(0,length-.4):.3f}:d=0.4[fx];[a][fx]amix=inputs=2:duration=first:weights='1 0.22'[ao]"
                args=["ffmpeg","-y","-ss",str(a),"-i",str(src),"-filter_complex",fc,"-map","[v]","-map","[ao]","-t",str(length),"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","160k","-movflags","+faststart",str(out)]
            else:
                args=["ffmpeg","-y","-ss",str(a),"-i",str(src),"-vf",vf,"-af",af,"-t",str(length),"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","160k","-movflags","+faststart",str(out)]
        else:
            args=["ffmpeg","-y","-ss",str(a),"-i",str(src),"-vf",vf,"-t",str(length),"-an","-c:v","libx264","-preset","veryfast","-crf","23","-movflags","+faststart",str(out)]
        run_cmd(args)
    finally:
        if assfile and os.path.exists(assfile): os.remove(assfile)

# Presets expose sensible defaults immediately; Custom reveals all individual controls.
PRESETS={
 "Quick test — 3 clips × 30 sec":(3,30,"tiny"),
 "Balanced — 5 clips × 45 sec":(5,45,"base"),
 "More clips — 10 clips × 30 sec":(10,30,"tiny"),
 "Long highlights — 5 clips × 60 sec":(5,60,"base"),
 "Higher transcription accuracy — 5 clips × 45 sec":(5,45,"small"),
 "Custom settings":(5,45,"base")
}
with st.sidebar:
    st.header("⚙️ Clip settings")
    preset=st.selectbox("Choose a preset",list(PRESETS.keys()),index=1)
    default_count,default_len,default_model=PRESETS[preset]
    if preset=="Custom settings":
        wanted=st.slider("Number of clips",1,10,5)
        clip_len=st.slider("Clip length (seconds)",15,120,45,5)
        model=st.selectbox("Transcription model",["tiny","base","small"],index=1)
    else:
        wanted,clip_len,model=default_count,default_len,default_model
        st.caption(f"Selected: {wanted} clips · up to {clip_len}s each · {model} model")
    language=st.selectbox("Spoken language",["Auto detect","English","Greek","Spanish","French","German","Italian","Portuguese","Japanese"])
    ratio=st.selectbox("Video format",["9:16 vertical","1:1 square","16:9 landscape"],index=0)
    subtitles=st.checkbox("Word-synced animated subtitles",True)
    words_per_line=st.slider("Words shown at once",2,7,4)
    font_size=st.slider("Subtitle size",42,84,66,2)
    whoosh=st.checkbox("Add subtle generated whoosh",False)
    st.caption("Smooth visual/audio fades are enabled automatically.")

st.subheader("1 · Add your video")
source=st.radio("Video source",["Upload a video","YouTube link","Direct video-file URL"],horizontal=True)
upload=None; url=""
if source=="Upload a video":
    upload=st.file_uploader("Choose MP4, MOV, MKV or WebM",type=["mp4","mov","mkv","webm"])
elif source=="YouTube link":
    url=st.text_input("Paste a public YouTube video URL",placeholder="https://www.youtube.com/watch?v=...")
    st.caption("Works only when the video is publicly accessible without login, DRM or other access-control bypass. Use videos you own or have permission to edit.")
else:
    url=st.text_input("Public direct video URL",placeholder="https://example.com/video.mp4")
    st.caption("Direct file URLs only; this is different from a YouTube watch-page link.")

st.subheader("2 · Create your clips")
if st.button("✨ Generate clips",type="primary",use_container_width=True):
    if not upload and not url:
        st.error("Upload a video or enter a URL first."); st.stop()
    work=Path(tempfile.mkdtemp(prefix="clipforge_")); src=work/"source.mp4"
    try:
        with st.status("Working on your video…",expanded=True) as status:
            if upload:
                src=work/Path(upload.name).name
                src.write_bytes(upload.getvalue())
            elif source=="YouTube link":
                st.write("Fetching the publicly accessible YouTube video…")
                download_youtube(url,src)
            else:
                st.write("Downloading direct video file…")
                download_direct(url,src)
            dur=video_duration(src)
            if dur<2: raise ValueError("Video is too short or could not be read.")
            st.write(f"Transcribing with Whisper {model} (word-level timing enabled)…")
            segments,detected=transcribe(src,model,language)
            st.write("Selecting highlight moments and preparing titles…")
            windows=choose_windows(segments,dur,wanted,clip_len)
            if not windows: raise RuntimeError("No highlight windows could be selected.")
            outdir=work/"clips"; outdir.mkdir()
            results=[]; progress=st.progress(0)
            for i,(a,b) in enumerate(windows,1):
                title=make_title(segments,a,b,i)
                outfile=outdir/f"{i:02d}_{safe_filename(title)}.mp4"
                st.write(f"Rendering clip {i} of {len(windows)}…")
                render_clip(src,a,b,outfile,ratio.split()[0],segments,subtitles,whoosh,words_per_line,font_size)
                results.append((title,outfile,a,b)); progress.progress(i/len(windows))
            status.update(label="Your clips are ready!",state="complete",expanded=False)
        st.success(f"Created {len(results)} clips.")
        st.caption(f"Detected speech language: {detected or 'unknown'}. Titles are transcript-based suggestions; edit them before downloading if needed.")
        for i,(title,path,a,b) in enumerate(results,1):
            with st.expander(f"Clip {i} · {title}",expanded=(i==1)):
                edited=st.text_input("Edit suggested title",value=title,key=f"clip_title_{i}")
                st.video(str(path))
                st.download_button("⬇️ Download MP4",data=path.read_bytes(),file_name=safe_filename(edited)+".mp4",mime="video/mp4",key=f"clip_download_{i}")
                st.caption(f"Selected source moment: {a:.1f}s–{b:.1f}s")
        archive=work/"clipforge-clips.zip"
        with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
            for i,(title,path,a,b) in enumerate(results,1):
                z.write(path,arcname=f"{i:02d}_{safe_filename(title)}.mp4")
        st.download_button("📦 Download all clips as ZIP",data=archive.read_bytes(),file_name="clipforge-clips.zip",mime="application/zip",use_container_width=True)
    except Exception as e:
        st.error(f"Processing failed: {e}")
        st.info("Free hosting may run out of CPU/time on long videos. Try a shorter video and the Tiny model.")
        st.exception(e)

st.divider()
st.caption("ClipForge uses faster-whisper and FFmpeg. YouTube availability can change; it cannot access private/login-only/DRM-restricted videos or bypass access controls. Use content you own or have permission to edit. Highlight selection and title suggestions are automated and may need human review.")
