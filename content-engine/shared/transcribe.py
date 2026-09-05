"""
Part D, step 2 — transcription.

Two paths, cheapest first (DECISIONS.md D-14):

  1. youtube-transcript-api  - free, instant, no download, YouTube only.
  2. yt-dlp -> Groq whisper   - downloads audio, transcribes with
                                whisper-large-v3-turbo. Works for anything
                                yt-dlp can reach. Segment timings come back,
                                which is what the caption burner needs later.

Audio is written to out/_audio and kept, so re-running a script does not
re-download or re-transcribe.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from . import llm

from .config import DATA_DIR

AUDIO_DIR = DATA_DIR / "audio"
CACHE_DIR = DATA_DIR / "transcripts"


def _slug(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", url)[-80:].strip("_") or "clip"


def youtube_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def via_youtube_api(url: str) -> dict[str, Any] | None:
    vid = youtube_id(url)
    if not vid:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None

    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(vid, languages=["en", "en-US", "en-GB"])
        raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
    except Exception:  # noqa: BLE001
        # Older API surface, or no transcript available for this video.
        try:
            raw = YouTubeTranscriptApi.get_transcript(vid, languages=["en", "en-US", "en-GB"])
        except Exception:  # noqa: BLE001
            return None

    segments = [
        {
            "start": float(s.get("start", 0.0)),
            "end": float(s.get("start", 0.0)) + float(s.get("duration", 0.0)),
            "text": (s.get("text") or "").strip(),
        }
        for s in raw
    ]
    return {
        "text": " ".join(s["text"] for s in segments).strip(),
        "segments": segments,
        "source": "youtube-transcript-api",
    }


def download_audio(url: str) -> Path | None:
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print("  ! yt-dlp not installed")
        return None

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    target = AUDIO_DIR / f"{_slug(url)}.m4a"
    if target.exists():
        return target

    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": str(target.with_suffix("")) + ".%(ext)s",
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "128"}
        ],
    }
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:  # noqa: BLE001
        print(f"  ! audio download failed: {str(exc)[:200]}")
        return None

    if target.exists():
        return target
    for cand in AUDIO_DIR.glob(f"{_slug(url)}.*"):
        return cand
    return None


def via_whisper(url: str) -> dict[str, Any] | None:
    audio = download_audio(url)
    if audio is None:
        return None
    print(f"  transcribing {audio.name} with Groq whisper")
    try:
        result = llm.transcribe_audio(str(audio))
    except Exception as exc:  # noqa: BLE001
        print(f"  ! whisper failed: {str(exc)[:200]}")
        return None
    result["source"] = "groq-whisper"
    return result


def transcribe(url: str, *, force: bool = False) -> dict[str, Any] | None:
    """Return {"text", "segments", "source"} or None if every path failed."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{_slug(url)}.json"
    if cache.exists() and not force:
        return json.loads(cache.read_text(encoding="utf-8"))

    result = via_youtube_api(url) or via_whisper(url)
    if result is None:
        return None
    cache.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def to_srt(segments: list[dict[str, Any]]) -> str:
    def ts(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    out = []
    for i, seg in enumerate(segments, start=1):
        out.append(f"{i}\n{ts(seg['start'])} --> {ts(seg['end'])}\n{seg['text']}\n")
    return "\n".join(out)


