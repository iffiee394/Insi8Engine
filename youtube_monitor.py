"""Fetch videos from a YouTube playlist or a single video via Data API v3."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import requests

import config

YOUTUBE_API = "https://www.googleapis.com/youtube/v3/playlistItems"
YOUTUBE_VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "www.youtube.com"}


@dataclass
class PlaylistVideo:
    video_id: str
    title: str
    url: str
    channel_name: str = ""


def parse_video_id(value: str) -> str | None:
    """Extract an 11-character YouTube video id from a URL or a bare id."""
    raw = (value or "").strip()
    if not raw:
        return None
    if _VIDEO_ID_RE.match(raw):
        return raw

    if raw.startswith("http://"):
        raw = "https://" + raw[7:]
    elif "youtube.com" in raw.lower() or "youtu.be" in raw.lower():
        if not raw.lower().startswith("https://"):
            raw = "https://" + raw.lstrip("/")

    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0].split("?")[0]
        return candidate if _VIDEO_ID_RE.match(candidate) else None

    if host in _YT_HOSTS or host.endswith(".youtube.com"):
        qs = parse_qs(parsed.query)
        vid = (qs.get("v") or [""])[0]
        if _VIDEO_ID_RE.match(vid):
            return vid
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live", "v"}:
            candidate = parts[1].split("?")[0]
            if _VIDEO_ID_RE.match(candidate):
                return candidate
    return None


def fetch_video(video_id: str) -> PlaylistVideo:
    """Look up one public video by id. Raises if missing or the API key is unset."""
    api_key = config.YOUTUBE_API_KEY
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not set.")
    if not video_id:
        raise RuntimeError("No video id.")

    response = requests.get(
        YOUTUBE_VIDEOS_API,
        params={"part": "snippet", "id": video_id, "key": api_key},
        timeout=30,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    if not items:
        raise RuntimeError("YouTube video not found or it is not public.")

    snippet = items[0].get("snippet", {})
    title = snippet.get("title") or "Untitled"
    if title == "Deleted video" or title == "Private video":
        raise RuntimeError(f"Cannot ingest this video ({title}).")

    return PlaylistVideo(
        video_id=video_id,
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
        channel_name=(snippet.get("channelTitle") or "").strip(),
    )


def fetch_playlist_videos(playlist_id: str | None = None) -> list[PlaylistVideo]:
    api_key = config.YOUTUBE_API_KEY
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not set.")

    playlist_id = playlist_id or config.PLAYLIST_ID
    if not playlist_id:
        raise RuntimeError("PLAYLIST_ID is not set.")

    videos: list[PlaylistVideo] = []
    page_token: str | None = None

    while True:
        params = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        response = requests.get(YOUTUBE_API, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})
            video_id = content.get("videoId") or snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue
            if snippet.get("title") == "Deleted video":
                continue

            videos.append(
                PlaylistVideo(
                    video_id=video_id,
                    title=snippet.get("title", "Untitled"),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                )
            )

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return videos
