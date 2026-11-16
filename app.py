
import os, re, subprocess, tempfile
from pathlib import Path
from urllib.parse import urlparse
import requests
import streamlit as st

st.set_page_config(page_title="ClipForge AI", page_icon="🎬", layout="wide")
st.markdown("""
<style>
.stApp{background:radial-gradient(circle at 10% 0%,#202c4b,#101522 42%,#0b0e16)}
.block-container{max-width:1150px;padding-top:2rem}
.hero{padding:25px 28px;border:1px solid #34415f;border-radius:20px;background:linear-gradient(120deg,#26375c,#151c2d);margin-bottom:20px}
.hero h1{font-size:2.35rem;margin:0;letter-spacing:-.04em}
.hero p{color:#c4cde0;margin:8px 0 0}
div[data-testid="stMetric"]{background:#ffffff0a;padding:14px;border:1px solid #303b52;border-radius:14px}
.stButton>button{border-radius:12px;font-weight:700;min-height:2.8rem}
</style>
<div class="hero"><h1>🎬 ClipForge <span style="color:#91adff">AI</span></h1>
<p>Automatic highlights, animated subtitles, smooth fades, sound accents and ready-to-share MP4 clips.</p></div>
""", unsafe_allow_html=True)

def cmd(args, timeout=900):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-2800:])
    return p.stdout.strip()

def duration_of(path):
    return float(cmd(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)]))

def has_audio(path):
    s = cmd(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=codec_type","-of","csv=p=0",str(path)])
    return bool(s.strip())

def download_video(url, dest):
    u=urlparse(url)
    if u.scheme not in ("http","https") or not u.netloc:
        raise ValueError("Enter a valid public http(s) video-file URL.")
    with requests.get(url,stream=True,timeout=(15,90),headers={"User-Agent":"ClipForge/1.0"}) as r:
        r.raise_for_status()
        if "text/html" in r.headers.get("content-type","").lower():
            raise ValueError("This is a webpage, not a direct video file. Use a direct MP4/MOV/WebM link or upload a video.")
        total=0
        with open(dest,"wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk:
                    total+=len(chunk)
                    if total>1_500_000_000: raise ValueError("Video exceeds the 1.5 GB limit.")
                    f.write(chunk)

def transcribe(path, model_name, lang):
    from faster_whisper import WhisperModel
    model=WhisperModel(model_name,device="cpu",compute_type="int8")
    opts={"vad_filter":True}
    if lang!="Auto detect": opts["language"]=lang
    segs,info=model.transcribe(str(path),**opts)
    rows=[]
    for s in segs:
        t=(s.text or "").strip()
        if t: rows.append({"start":float(s.start),"end":float(s.end),"text":t})
    return rows,getattr(info,"language",None)

def score(text):
    t=text.lower()
    hooks=("but","because","secret","never","always","why","how","actually","insane","mistake","problem","best","worst","imagine","important","crazy","truth","wait","look")
    return min(len(t)/100,1.5)+sum(.42 for w in hooks if re.search(r"\b"+w+r"\b",t)) + min(text.count("!")*.12,.5)+min(text.count("?")*.1,.4)

def choose_windows(segs,total,wanted,clip_len):
    length=min(float(clip_len),total)
    if total<=length: return [(0.0,total)]
    candidates=[]
    for s in segs:
        center=(s["start"]+s["end"])/2
        start=max(0.0,min(total-length,center-length/2))
        text=" ".join(x["text"] for x in segs if x["start"]<start+length and x["end"]>start)
        candidates.append((score(text),start,start+length))
    candidates.sort(reverse=True)
    chosen=[]
    min_gap=max(2.0,length*.4)
    for sc,a,b in candidates:
        if all(abs(a-x[0])>=min_gap for x in chosen):
            chosen.append((a,b,sc))
        if len(chosen)>=wanted: break
    # Fill remaining slots evenly. Overlap is allowed if the source is too short
    # to provide the requested number of distinct moments.
    missing=wanted-len(chosen)
    for i in range(missing):
        # Always fill the requested count; when the source is short, windows
        # may overlap rather than silently returning fewer clips.
        pos=(i+1)/(missing+1)*(total-length)
        chosen.append((pos,pos+length,0))
    chosen.sort(key=lambda x:x[0])
    return [(a,b) for a,b,_ in chosen[:wanted]]

def ass_time(seconds):
    centis=int(max(0.0,seconds)*100)
    hours,rem=divmod(centis,360000)
    minutes,rem=divmod(rem,6000)
    secs,cs=divmod(rem,100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"

def ass_escape(text):
    return text.replace("\\","\\\\").replace("{","\\{").replace("}","\\}").replace("\n"," ")

def write_ass(segs,clip_start,clip_end,path,width,height):
    out=[
      "[Script Info]","ScriptType: v4.00+",
      f"PlayResX: {width}",f"PlayResY: {height}","WrapStyle: 2","ScaledBorderAndShadow: yes","",
      "[V4+ Styles]",
      "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
      "Style: Pop,Arial,64,&H00FFFFFF,&H0000FFFF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,1,5,2,2,70,70,250,1","",
      "[Events]","Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]
    for s in segs:
        a=max(clip_start,s["start"]); b=min(clip_end,s["end"])
        if b<=a: continue
        txt=ass_escape(s["text"])
        if len(txt)>48:
            words=txt.split()
            mid=max(1,len(words)//2)
            txt=" ".join(words[:mid])+"\\N"+" ".join(words[mid:])
        txt="{\\fad(100,120)\\fscx92\\fscy92\\t(0,160,\\fscx100\\fscy100)}"+txt
        out.append(f"Dialogue: 0,{ass_time(a-clip_start)},{ass_time(b-clip_start)},Pop,,0,0,0,,{txt}")
    Path(path).write_text("\n".join(out),encoding="utf-8")

def safe_name(s):
    s=re.sub(r"[^A-Za-z0-9 _-]","",s).strip().replace(" ","_")
    return (s[:60] or "highlight")

def title_for(segs,a,b,n):
    text=" ".join(s["text"] for s in segs if s["start"]<b and s["end"]>a)
    words=re.findall(r"[A-Za-z0-9']+",text)
    if not words: return f"Highlight {n}"
    title=" ".join(words[:8]).strip()
    if len(title)<12: title=text[:55].strip(" .!?")
    return title[:64].capitalize()

def render_clip(src,a,b,out,ratio,segs,subtitles,whoosh):
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
        write_ass(segs,a,b,assfile,w,h)
        ap=assfile.replace("\\","/").replace(":","\\:")
        vf+=f",ass='{ap}'"
    try:
        if has_audio(src):
            af=f"afade=t=in:st=0:d=0.2,afade=t=out:st={max(0,length-.3):.3f}:d=0.3"
            if whoosh:
                # Generated low-level noise sweep; no third-party/copyrighted audio.
                fc=f"[0:v]{vf}[v];[0:a]{af}[a];anoisesrc=color=white:duration={length}:sample_rate=44100:amplitude=0.012,lowpass=f=1600,afade=t=in:st=0:d=0.03,afade=t=out:st={max(0,length-.4):.3f}:d=0.4[fx];[a][fx]amix=inputs=2:duration=first:weights='1 0.25'[ao]"
                args=["ffmpeg","-y","-ss",str(a),"-i",str(src),"-filter_complex",fc,"-map","[v]","-map","[ao]","-t",str(length),"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","160k","-movflags","+faststart",str(out)]
            else:
                args=["ffmpeg","-y","-ss",str(a),"-i",str(src),"-vf",vf,"-af",af,"-t",str(length),"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","160k","-movflags","+faststart",str(out)]
        else:
            args=["ffmpeg","-y","-ss",str(a),"-i",str(src),"-vf",vf,"-t",str(length),"-an","-c:v","libx264","-preset","veryfast","-crf","23","-movflags","+faststart",str(out)]
        cmd(args)
    finally:
        if assfile and os.path.exists(assfile): os.remove(assfile)

with st.sidebar:
    st.header("⚙️ Clip settings")
    wanted=st.slider("Number of clips",1,10,5)
    clip_len=st.slider("Target clip length",15,90,35,5)
    ratio=st.selectbox("Aspect ratio",["9:16","1:1","16:9"])
    model=st.selectbox("Whisper model",["tiny","base","small"],help="Tiny is fastest on free hosting.")
    lang=st.selectbox("Spoken language",["Auto detect","English","Greek","Spanish","French","German","Italian","Portuguese","Japanese"])
    subtitles=st.checkbox("Animated subtitles",True)
    whoosh=st.checkbox("Add subtle generated whoosh sound",False)
    st.caption("Smooth visual/audio fades are enabled automatically.")

st.subheader("1 · Add your video")
source=st.radio("Video source",["Upload video","Direct video-file URL"],horizontal=True)
upload=None; url=""
if source=="Upload video":
    upload=st.file_uploader("Choose MP4, MOV, MKV or WebM",type=["mp4","mov","mkv","webm"])
else:
    url=st.text_input("Public direct video URL",placeholder="https://example.com/video.mp4")
    st.caption("Direct file URLs only. YouTube/Twitch watch pages and login-protected links are not supported.")
st.subheader("2 · Create your clips")
if st.button("✨ Generate clips",type="primary",use_container_width=True):
    if not upload and not url:
        st.error("Upload a video or enter a direct video-file URL.")
        st.stop()
    work=Path(tempfile.mkdtemp(prefix="clipforge_"))
    try:
        src=work/"input_video"
        with st.status("Working on your video…",expanded=True) as status:
            if upload:
                src=work/Path(upload.name).name
                src.write_bytes(upload.getvalue())
            else:
                st.write("Downloading public video file…")
                download_video(url,src)
            dur=duration_of(src)
            if dur<2: raise ValueError("Video is too short or could not be read.")
            st.write(f"Transcribing speech with Whisper ({model})…")
            segs,detected=transcribe(src,model,lang)
            st.write("Selecting highlight moments…")
            windows=choose_windows(segs,dur,wanted,clip_len)
            if not windows: raise RuntimeError("Could not select clip segments.")
            outdir=work/"clips"; outdir.mkdir()
            done=[]
            bar=st.progress(0)
            for i,(a,b) in enumerate(windows,1):
                title=title_for(segs,a,b,i)
                out=outdir/f"{i:02d}_{safe_name(title)}.mp4"
                st.write(f"Rendering clip {i} of {len(windows)}…")
                render_clip(src,a,b,out,ratio,segs,subtitles,whoosh)
                done.append((title,out,a,b))
                bar.progress(i/len(windows))
            status.update(label="Clips created!",state="complete",expanded=False)
        st.success(f"Created {len(done)} clip(s).")
        if len(done)<wanted:
            st.info("The source was too short to produce that many distinct clip windows.")
        st.caption(f"Detected language: {detected or 'unknown'}")
        for i,(suggested,path,a,b) in enumerate(done,1):
            with st.expander(f"Clip {i}: {suggested}",expanded=(i==1)):
                edited=st.text_input("Clip title",value=suggested,key=f"title_{i}")
                st.video(str(path))
                st.download_button("⬇️ Download MP4",data=path.read_bytes(),file_name=safe_name(edited)+".mp4",mime="video/mp4",key=f"dl_{i}")
                st.caption(f"Source segment: {a:.1f}s – {b:.1f}s")
        archive=work/"clipforge_clips.zip"
        import zipfile
        with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
            for i,(title,path,a,b) in enumerate(done,1):
                z.write(path,arcname=f"{i:02d}_{safe_name(title)}.mp4")
        st.download_button("📦 Download all clips as ZIP",data=archive.read_bytes(),file_name="clipforge-clips.zip",mime="application/zip",use_container_width=True)
    except Exception as e:
        st.error(f"Could not finish processing: {e}")
        st.info("On free hosting, try a shorter video and the Tiny speech model. Ensure FFmpeg is installed.")
        st.exception(e)

st.divider()
st.caption("ClipForge is a free, open-source-style workflow using Whisper and FFmpeg. It cannot fetch arbitrary YouTube/Twitch watch pages or bypass access controls. Highlight selection is transcript-based and is not a guarantee of virality.")
