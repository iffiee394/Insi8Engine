"""YouTube audio download and Groq Whisper transcription."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import yt_dlp
from groq import Groq

import config

CHUNK_SECONDS = 600  # 10-minute chunks for long audio


def transcribe_file(media_path: Path | str) -> str:
    """Send a local video/audio file to Groq Whisper."""
    api_key = config.GROQ_API_KEY
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    media_path = Path(media_path)
    client = Groq(api_key=api_key)
    with open(media_path, "rb") as media_file:
        result = client.audio.transcriptions.create(
            file=(media_path.name, media_file.read()),
            model="whisper-large-v3-turbo",
            response_format="text",
        )
    return str(result).strip()


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _split_audio(audio_path: Path, output_dir: Path) -> list[Path]:
    """Split audio into CHUNK_SECONDS segments using ffmpeg."""
    pattern = output_dir / "chunk_%03d.mp3"
    cmd = [
        "ffmpeg",
        "-i",
        str(audio_path),
        "-f",
        "segment",
        "-segment_time",
        str(CHUNK_SECONDS),
        "-c",
        "copy",
        str(pattern),
        "-y",
        "-loglevel",
        "error",
    ]
    subprocess.run(cmd, check=True)
    chunks = sorted(output_dir.glob("chunk_*.mp3"))
    if not chunks:
        return [audio_path]
    return chunks


def download_youtube_audio(video_id: str, output_dir: Path) -> Path:
    """Download best audio for a YouTube video via yt-dlp."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(output_dir / f"{video_id}.%(ext)s")
    url = f"https://www.youtube.com/watch?v={video_id}"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    mp3_path = output_dir / f"{video_id}.mp3"
    if mp3_path.exists():
        return mp3_path

    for f in output_dir.glob(f"{video_id}.*"):
        return f

    raise RuntimeError(f"yt-dlp did not produce an audio file for {video_id}")


def transcribe_youtube_audio(video_id: str) -> tuple[str, str]:
    """
    Download YouTube audio and transcribe via Groq Whisper.
    Returns (transcript, source_label).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        audio_path = download_youtube_audio(video_id, tmp_path)

        if _ffmpeg_available() and audio_path.stat().st_size > 20 * 1024 * 1024:
            chunk_dir = tmp_path / "chunks"
            chunk_dir.mkdir()
            chunks = _split_audio(audio_path, chunk_dir)
            parts = [transcribe_file(chunk) for chunk in chunks]
            return "\n".join(p for p in parts if p.strip()), "groq_whisper_chunked"

        transcript = transcribe_file(audio_path)
        return transcript, "groq_whisper"
