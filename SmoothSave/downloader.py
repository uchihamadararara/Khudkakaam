import os, sys, subprocess, tempfile, shutil
from pathlib import Path

def ensure(mod, package=None):
    try: __import__(mod)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", package or mod, "--disable-pip-version-check"])

ensure("flask")
ensure("yt_dlp", "yt-dlp")
ensure("imageio_ffmpeg", "imageio-ffmpeg")

from flask import Flask, request, jsonify, send_file, send_from_directory
import yt_dlp, imageio_ffmpeg

BASE = Path(__file__).parent
FRONT = BASE / "frontend"
TMP = Path(tempfile.gettempdir()) / "smoothsave"
TMP.mkdir(parents=True, exist_ok=True)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
PORT = int(os.getenv("PORT", "10000"))

app = Flask(__name__, static_folder=str(FRONT), static_url_path="")

def base_opts():
    return {"quiet": True, "no_warnings": True, "noplaylist": True,
            "ffmpeg_location": FFMPEG, "socket_timeout": 20,
            "retries": 2, "fragment_retries": 2}

def extract(url):
    o = base_opts(); o["skip_download"] = True
    with yt_dlp.YoutubeDL(o) as y: return y.extract_info(url, download=False)

def selector(q):
    q = str(q or "best").replace("p","")
    if q == "best":
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    if q.isdigit():
        n = int(q)
        return f"bestvideo[height<={n}][ext=mp4]+bestaudio[ext=m4a]/best[height<={n}][ext=mp4]/best[height<={n}]"
    return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

@app.get("/")
def home(): return send_from_directory(FRONT, "index.html")

@app.get("/<path:path>")
def static(path):
    p = FRONT / path
    return send_from_directory(FRONT, path) if p.is_file() else send_from_directory(FRONT, "index.html")

@app.post("/api/info")
def api_info():
    url = str((request.get_json(silent=True) or {}).get("url","")).strip()
    if not url: return jsonify(error="URL is required"), 400
    try:
        x = extract(url)
        heights = sorted({int(f["height"]) for f in x.get("formats", [])
                          if f.get("height") and f.get("vcodec") != "none"}, reverse=True)
        qs = [h for h in heights if h in (2160,1440,1080,720,480,360)] or heights[:6] or [720,480,360]
        return jsonify(title=x.get("title","Video"), thumbnail=x.get("thumbnail"),
                       duration=x.get("duration"), uploader=x.get("uploader"), qualities=qs)
    except Exception as e: return jsonify(error=str(e)), 400

@app.post("/api/download")
def api_download():
    d = request.get_json(silent=True) or {}
    url, media, quality = str(d.get("url","")).strip(), str(d.get("type","mp4")).lower(), d.get("quality","best")
    if not url: return jsonify(error="URL is required"), 400
    if media not in ("mp4","mp3"): return jsonify(error="Invalid format"), 400
    job = Path(tempfile.mkdtemp(prefix="job_", dir=TMP))
    try:
        meta = extract(url); title = meta.get("title") or "video"
        o = base_opts(); o["outtmpl"] = str(job / "%(title)s.%(ext)s")
        if media == "mp3":
            o["format"] = "bestaudio/best"
            o["postprocessors"] = [{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}]
        else:
            o["format"] = selector(quality); o["merge_output_format"] = "mp4"
        with yt_dlp.YoutubeDL(o) as y: y.download([url])
        files = [p for p in job.iterdir() if p.is_file() and p.stat().st_size]
        if not files: raise RuntimeError("No output file was created")
        ext = ".mp3" if media == "mp3" else ".mp4"
        output = next((p for p in files if p.suffix.lower()==ext), files[0])
        safe = "".join(c if c.isalnum() or c in " .-_()" else "_" for c in title).strip()[:100] or "video"
        response = send_file(output, as_attachment=True, download_name=safe+ext,
                             mimetype="audio/mpeg" if media=="mp3" else "video/mp4")
        @response.call_on_close
        def cleanup(): shutil.rmtree(job, ignore_errors=True)
        return response
    except Exception as e:
        shutil.rmtree(job, ignore_errors=True)
        return jsonify(error=str(e)), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
