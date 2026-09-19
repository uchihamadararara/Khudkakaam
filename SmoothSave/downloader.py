import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path


# =========================
# Install required packages
# =========================

def ensure_package(module_name, package_name=None):
    try:
        __import__(module_name)
    except ImportError:
        subprocess.check_call([
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            package_name or module_name,
            "--disable-pip-version-check"
        ])


ensure_package("flask")
ensure_package("yt_dlp", "yt-dlp")
ensure_package("imageio_ffmpeg", "imageio-ffmpeg")


# =========================
# Imports
# =========================

from flask import (
    Flask,
    request,
    jsonify,
    send_file,
    send_from_directory
)

import yt_dlp
import imageio_ffmpeg


# =========================
# Configuration
# =========================

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

TEMP_DIR = Path(tempfile.gettempdir()) / "smoothsave"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

PORT = int(os.environ.get("PORT", "10000"))


# =========================
# Flask App
# =========================

app = Flask(
    __name__,
    static_folder=str(FRONTEND_DIR),
    static_url_path=""
)


# =========================
# yt-dlp options
# =========================

def base_options():
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ffmpeg_location": FFMPEG_PATH,

        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
    }


# =========================
# Extract video information
# =========================

def extract_info(url):
    options = base_options()
    options["skip_download"] = True

    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(
            url,
            download=False
        )


# =========================
# Quality selector
# =========================

def get_format_selector(quality):

    quality = str(
        quality or "best"
    ).lower().replace("p", "")

    # Best available
    if quality == "best":
        return (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
            "best[ext=mp4]/"
            "best"
        )

    # Selected resolution
    if quality.isdigit():

        height = int(quality)

        return (
            f"bestvideo[height<={height}][ext=mp4]+"
            f"bestaudio[ext=m4a]/"
            f"best[height<={height}][ext=mp4]/"
            f"best[height<={height}]"
        )

    return (
        "bestvideo[ext=mp4]+"
        "bestaudio[ext=m4a]/"
        "best[ext=mp4]/"
        "best"
    )


# =========================
# Homepage
# =========================

@app.get("/")
def home():

    return send_from_directory(
        FRONTEND_DIR,
        "index.html"
    )


# =========================
# Frontend files
# =========================

@app.get("/<path:path>")
def serve_asset(path):

    requested_file = FRONTEND_DIR / path

    if requested_file.is_file():

        return send_from_directory(
            FRONTEND_DIR,
            path
        )

    # For PWA / SPA fallback
    return send_from_directory(
        FRONTEND_DIR,
        "index.html"
    )


# =========================
# Video information API
# =========================

@app.post("/api/info")
def video_info():

    data = request.get_json(
        silent=True
    ) or {}

    url = str(
        data.get("url", "")
    ).strip()

    if not url:

        return jsonify({
            "error": "URL is required"
        }), 400

    try:

        info = extract_info(url)

        formats = info.get(
            "formats",
            []
        )

        heights = set()

        for fmt in formats:

            height = fmt.get(
                "height"
            )

            video_codec = fmt.get(
                "vcodec"
            )

            if (
                height
                and video_codec
                and video_codec != "none"
            ):
                try:
                    heights.add(
                        int(height)
                    )
                except:
                    pass

        heights = sorted(
            heights,
            reverse=True
        )

        preferred = [
            2160,
            1440,
            1080,
            720,
            480,
            360
        ]

        qualities = [
            q for q in preferred
            if q in heights
        ]

        if not qualities:

            qualities = heights[:6]

        if not qualities:

            qualities = [
                720,
                480,
                360
            ]

        return jsonify({

            "title": (
                info.get("title")
                or "Video"
            ),

            "thumbnail": (
                info.get("thumbnail")
            ),

            "duration": (
                info.get("duration")
            ),

            "uploader": (
                info.get("uploader")
            ),

            "qualities": qualities

        })

    except Exception as error:

        return jsonify({
            "error": str(error)
        }), 400


# =========================
# Download API
# =========================

@app.post("/api/download")
def download_media():

    data = request.get_json(
        silent=True
    ) or {}

    url = str(
        data.get("url", "")
    ).strip()

    media_type = str(
        data.get("type", "mp4")
    ).lower()

    quality = data.get(
        "quality",
        "best"
    )

    if not url:

        return jsonify({
            "error": "URL is required"
        }), 400

    if media_type not in (
        "mp4",
        "mp3"
    ):

        return jsonify({
            "error": "Invalid format"
        }), 400


    # Temporary job directory
    job_directory = Path(
        tempfile.mkdtemp(
            prefix="job_",
            dir=TEMP_DIR
        )
    )


    try:

        # Get metadata
        metadata = extract_info(
            url
        )

        title = (
            metadata.get("title")
            or "video"
        )


        # Output template
        output_template = str(
            job_directory /
            "%(title)s.%(ext)s"
        )


        options = base_options()

        options["outtmpl"] = (
            output_template
        )


        # =====================
        # MP3
        # =====================

        if media_type == "mp3":

            options["format"] = (
                "bestaudio/best"
            )

            options["postprocessors"] = [

                {
                    "key":
                        "FFmpegExtractAudio",

                    "preferredcodec":
                        "mp3",

                    "preferredquality":
                        "192"
                }

            ]


        # =====================
        # MP4
        # =====================

        else:

            options["format"] = (
                get_format_selector(
                    quality
                )
            )

            options[
                "merge_output_format"
            ] = "mp4"


        # =====================
        # Download
        # =====================

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            ydl.download([
                url
            ])


        # Find generated files
        files = [

            file

            for file in
            job_directory.iterdir()

            if (
                file.is_file()
                and file.stat().st_size > 0
            )

        ]


        if not files:

            raise RuntimeError(
                "No output file was created."
            )


        # Requested extension
        extension = (
            ".mp3"
            if media_type == "mp3"
            else ".mp4"
        )


        # Prefer exact extension
        output_file = next(

            (
                file
                for file in files
                if file.suffix.lower()
                == extension
            ),

            files[0]

        )


        # =====================
        # Safe filename
        # =====================

        safe_title = "".join(

            character

            if (
                character.isalnum()
                or character in
                " .-_()"
            )

            else "_"

            for character in title

        )

        safe_title = (
            safe_title
            .strip()
            [:100]
        )


        if not safe_title:

            safe_title = "video"


        download_name = (
            safe_title
            + extension
        )


        # =====================
        # Send file
        # =====================

        response = send_file(

            output_file,

            as_attachment=True,

            download_name=
                download_name,

            mimetype=(
                "audio/mpeg"
                if media_type == "mp3"
                else "video/mp4"
            )

        )


        # Cleanup after response
        @response.call_on_close
        def cleanup():

            shutil.rmtree(
                job_directory,
                ignore_errors=True
            )


        return response


    except Exception as error:

        shutil.rmtree(
            job_directory,
            ignore_errors=True
        )

        return jsonify({
            "error": str(error)
        }), 400


# =========================
# Start server
# =========================

if __name__ == "__main__":

    print(
        f"SmoothSave running on port {PORT}"
    )

    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )
