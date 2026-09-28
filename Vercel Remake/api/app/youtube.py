from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import requests


VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass
class VideoMeta:
    video_id: str
    title: str
    url: str
    channel_name: str = ""


def parse_video_id(value: str) -> str:
    raw = (value or "").strip()
    if VIDEO_ID_RE.match(raw):
        return raw
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate if VIDEO_ID_RE.match(candidate) else ""
    if "youtube.com" in host:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
            return candidate if VIDEO_ID_RE.match(candidate) else ""
        parts = [p for p in parsed.path.split("/") if p]
        for marker in ("shorts", "embed", "live"):
            if marker in parts:
                idx = parts.index(marker)
                if idx + 1 < len(parts) and VIDEO_ID_RE.match(parts[idx + 1]):
                    return parts[idx + 1]
    return ""


def fetch_public_metadata(video_id: str) -> VideoMeta:
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        response = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=8,
        )
        if response.ok:
            data = response.json()
            return VideoMeta(
                video_id=video_id,
                title=data.get("title") or video_id,
                url=url,
                channel_name=data.get("author_name") or "",
            )
    except Exception:
        pass
    return VideoMeta(video_id=video_id, title=video_id, url=url)


PLAYLIST_ID_RE = re.compile(r"^(PL|UU|FL|OL|LL|RD)[A-Za-z0-9_-]{10,}$")


def parse_playlist_id(value: str) -> str:
    raw = (value or "").strip()
    if PLAYLIST_ID_RE.match(raw):
        return raw
    candidate = parse_qs(urlparse(raw).query).get("list", [""])[0]
    return candidate if PLAYLIST_ID_RE.match(candidate) else ""


@dataclass
class PlaylistInfo:
    playlist_id: str
    title: str
    channel_name: str
    item_count: int


def fetch_playlist_info(playlist_id: str, api_key: str) -> PlaylistInfo | None:
    """Look the playlist up on YouTube. None means YouTube can't see it (missing or private)."""
    response = requests.get(
        "https://www.googleapis.com/youtube/v3/playlists",
        params={"part": "snippet,contentDetails", "id": playlist_id, "key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("items") or []
    if not items:
        return None
    item = items[0]
    return PlaylistInfo(
        playlist_id=playlist_id,
        title=item["snippet"].get("title") or playlist_id,
        channel_name=item["snippet"].get("channelTitle") or "",
        item_count=int(item.get("contentDetails", {}).get("itemCount") or 0),
    )
