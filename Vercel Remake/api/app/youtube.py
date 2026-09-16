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
