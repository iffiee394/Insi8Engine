#!/usr/bin/env python3
"""
transcriber.py -- CCC reel transcriber

Downloads a reel and transcribes it via Groq Whisper (whisper-large-v3-turbo).

TWO MODES:
  1. --reel-url  (default)  — uses instagrapi to resolve the URL, then downloads.
                              Requires IG_USERNAME + IG_PASSWORD in .env.
  2. --video-url (Apify)    — skips instagrapi entirely. Uses a direct CDN video URL
                              already fetched by apify_scraper.py (stored in reel["video_url"]).
                              Does NOT require Instagram credentials.

NOTE: Apify does NOT return transcripts — they must still be generated here.
      Both modes produce the same JSON output format.

Usage:
    # Mode 1 — resolve via Instagram (requires IG creds):
    python transcriber.py --reel-url "https://www.instagram.com/reel/ABC123/"

    # Mode 2 — direct CDN URL from Apify (no IG creds needed):
    python transcriber.py --reel-url "https://www.instagram.com/reel/ABC123/" \
                          --video-url "https://cdn.instagram.com/..."
"""

import argparse
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv
from groq import Groq
from instagrapi import Client as IGClient
from instagrapi.exceptions import ChallengeRequired, TwoFactorRequired


if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


BASE_DIR = Path(__file__).parent
SESSION_FILE = BASE_DIR / "ig_session.json"
TEXT_OVERLAY_MAX_SECONDS = 10
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def ig_login(username, password):
    """Login to Instagram via instagrapi. Reuses the existing project session."""
    cl = IGClient()
    cl.delay_range = [2, 5]

    if SESSION_FILE.exists():
        try:
            cl.load_settings(str(SESSION_FILE))
            cl.login(username, password)
            cl.get_timeline_feed()
            return cl
        except Exception:
            pass

    try:
        cl.login(username, password)
    except TwoFactorRequired:
        code = input("Enter Instagram 2FA code: ").strip()
        cl.login(username, password, verification_code=code)
    except ChallengeRequired:
        raise RuntimeError("Instagram challenge required. Log in manually, then re-run.")

    try:
        cl.dump_settings(str(SESSION_FILE))
    except PermissionError:
        pass
    return cl


def transcribe_file(media_path):
    """Send a local video/audio file to Groq Whisper."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    client = Groq(api_key=api_key)
    with open(media_path, "rb") as media_file:
        return client.audio.transcriptions.create(
            file=(str(media_path), media_file.read()),
            model="whisper-large-v3-turbo",
            response_format="text",
        )


def download_from_media_url(media, output_dir):
    """Fallback download using the signed video URL returned by instagrapi."""
    if not media.video_url:
        raise RuntimeError("instagrapi did not return a downloadable video URL.")

    response = requests.get(
        str(media.video_url),
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()

    output_path = Path(output_dir) / f"{media.pk}.mp4"
    output_path.write_bytes(response.content)
    return output_path


def download_reel(cl, media_pk, media, output_dir):
    """Download reel media through instagrapi, with signed URL fallback."""
    try:
        return Path(cl.clip_download(int(media_pk), folder=Path(output_dir)))
    except Exception:
        return download_from_media_url(media, output_dir)


def download_from_direct_url(video_url, output_dir):
    """
    Download a reel from a direct CDN URL (e.g. from Apify reel['video_url']).
    No Instagram login required.
    """
    response = requests.get(
        video_url,
        headers={"User-Agent": USER_AGENT},
        timeout=120,
    )
    response.raise_for_status()

    filename  = "apify_reel.mp4"
    out_path  = Path(output_dir) / filename
    out_path.write_bytes(response.content)
    return out_path


def process_reel(reel_url, output_dir=None, keep_file=False, video_url=None):
    """
    Download and transcribe a reel.

    If video_url is provided (direct CDN URL from Apify), skip instagrapi entirely.
    Otherwise use instagrapi to resolve reel_url → download → transcribe.
    """
    temp_dir   = None
    media_path = None

    try:
        if output_dir:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            download_dir = output_dir
        else:
            temp_dir     = tempfile.TemporaryDirectory()
            download_dir = temp_dir.name

        # ── Mode 2: Direct CDN URL from Apify ────────────────────────────────
        if video_url:
            media_path = download_from_direct_url(video_url, download_dir)
            transcript = transcribe_file(media_path)
            return {
                "status":         "ok",
                "transcript":     transcript,
                "is_text_overlay": False,
                "caption":        "",
                "duration_s":     0,
                "reel_url":       reel_url,
                "media_pk":       "",
                "source":         "apify_video_url_groq_whisper",
                "media_file":     str(media_path) if keep_file else "",
            }

        # ── Mode 1: Resolve via instagrapi ────────────────────────────────────
        username = os.environ.get("IG_USERNAME")
        password = os.environ.get("IG_PASSWORD")
        if not username or not password:
            raise RuntimeError(
                "IG_USERNAME and IG_PASSWORD must be set in .env "
                "(or pass --video-url to skip Instagram login)."
            )

        cl       = ig_login(username, password)
        media_pk = cl.media_pk_from_url(reel_url)
        media    = cl.media_info(media_pk)

        caption    = media.caption_text or ""
        duration_s = float(media.video_duration or 0)

        if duration_s and duration_s <= TEXT_OVERLAY_MAX_SECONDS:
            return {
                "status":         "ok",
                "transcript":     caption,
                "is_text_overlay": True,
                "caption":        caption,
                "duration_s":     duration_s,
                "reel_url":       reel_url,
                "media_pk":       str(media_pk),
                "source":         "caption_fallback",
            }

        media_path = download_reel(cl, media_pk, media, download_dir)
        transcript = transcribe_file(media_path)

        return {
            "status":         "ok",
            "transcript":     transcript,
            "is_text_overlay": False,
            "caption":        caption,
            "duration_s":     duration_s,
            "reel_url":       reel_url,
            "media_pk":       str(media_pk),
            "source":         "instagrapi_download_groq_whisper",
            "media_file":     str(media_path) if keep_file else "",
        }

    finally:
        if media_path and not keep_file:
            try:
                Path(media_path).unlink(missing_ok=True)
            except OSError:
                pass
        if temp_dir:
            temp_dir.cleanup()
        # Save instagrapi session if it was used
        try:
            from instagrapi import Client as _IGClient
            if 'cl' in dir() and isinstance(cl, _IGClient):
                cl.dump_settings(str(SESSION_FILE))
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Transcribe an Instagram reel via Groq Whisper.")
    parser.add_argument("--reel-url",   required=True,  help="Instagram reel URL.")
    parser.add_argument("--video-url",  default=None,
                        help="Direct CDN video URL from Apify (skips Instagram login).")
    parser.add_argument("--output-dir", default=None,   help="Optional folder for temporary media files.")
    parser.add_argument("--keep-file",  action="store_true", help="Keep downloaded media file for debugging.")
    args = parser.parse_args()

    load_dotenv(BASE_DIR / ".env")
    load_dotenv()

    try:
        print_json(process_reel(args.reel_url, args.output_dir, args.keep_file, args.video_url))
    except Exception as exc:
        print_json(
            {
                "status": "error",
                "error": str(exc),
                "transcript": "",
                "is_text_overlay": False,
                "caption": "",
                "duration_s": 0,
                "reel_url": args.reel_url,
            }
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
