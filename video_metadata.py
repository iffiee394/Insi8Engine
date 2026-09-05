"""Fetch YouTube video metadata and parse description links/resources."""

from __future__ import annotations

import re

import requests

import config
import usage_tracker

YOUTUBE_VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"
URL_PATTERN = re.compile(r"https?://[^\s\]\)<>\"']+")


def fetch_video_snippet(video_id: str) -> dict:
    """Return snippet fields (description, channel) or empty dict on failure."""
    api_key = config.YOUTUBE_API_KEY
    if not api_key or not video_id:
        return {}
    try:
        response = requests.get(
            YOUTUBE_VIDEOS_API,
            params={"part": "snippet", "id": video_id, "key": api_key},
            timeout=30,
        )
        response.raise_for_status()
        usage_tracker.record_youtube(operation="video_description")
        items = response.json().get("items", [])
        if not items:
            return {}
        snippet = items[0].get("snippet", {})
        return {
            "description": (snippet.get("description") or "").strip(),
            "channel_title": (snippet.get("channelTitle") or "").strip(),
        }
    except Exception:
        return {}


def fetch_video_description(video_id: str) -> str:
    """Return the YouTube video description, or empty string on failure."""
    return fetch_video_snippet(video_id).get("description", "")


def _clean_url(url: str) -> str:
    return url.rstrip(".,;)")


def parse_urls_from_text(text: str, *, source: str = "description") -> list[dict]:
    """Extract URLs from text with optional line context."""
    if not text:
        return []
    links: list[dict] = []
    seen: set[str] = set()
    lines = text.splitlines()
    for line in lines:
        for match in URL_PATTERN.finditer(line):
            url = _clean_url(match.group(0))
            if url in seen:
                continue
            seen.add(url)
            context = line.strip()[:200]
            title = context.replace(url, "").strip(" -•\t") or url
            links.append(
                {
                    "title": title or url,
                    "url": url,
                    "context": context,
                    "source": source,
                }
            )
    return links


def parse_description_resources(description: str) -> dict:
    """
    Parse description for URLs and bullet resource lines.
    Returns {urls: [...], resource_lines: [...]}.
    """
    if not description:
        return {"urls": [], "resource_lines": []}

    urls = parse_urls_from_text(description, source="description")
    resource_lines: list[str] = []
    capture = False
    for line in description.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if any(
            token in lower
            for token in ("resources:", "links:", "companies mentioned:", "books:", "tools:")
        ):
            capture = True
            after = stripped.split(":", 1)[-1].strip()
            if after:
                resource_lines.append(after)
            continue
        if capture and stripped.startswith(("-", "•", "*")):
            resource_lines.append(stripped.lstrip("-•* \t"))
        elif capture and stripped and not stripped.startswith("http"):
            if len(stripped) < 120:
                resource_lines.append(stripped)

    return {"urls": urls, "resource_lines": resource_lines}


def analyze_video_description(video_id: str) -> dict:
    """Fetch and parse video description + channel name."""
    snippet = fetch_video_snippet(video_id)
    description = snippet.get("description", "")
    parsed = parse_description_resources(description)
    return {
        "description": description,
        "channel_title": snippet.get("channel_title", ""),
        "urls": parsed["urls"],
        "resource_lines": parsed["resource_lines"],
    }
