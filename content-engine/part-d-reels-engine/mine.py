"""
Part D, step 1 — outlier mining across a creator watchlist.

Finds posts that meaningfully outperformed their own account, which is the only
performance signal available from the outside. A post with 300k views tells you
nothing until you know whether the account normally does 20k or 400k.

STATISTIC: median, not mean. One runaway hit drags a mean upward and then hides
every subsequent outlier behind it. Median stays put. See DECISIONS.md D-11.

SOURCE ADAPTERS (DECISIONS.md D-12):
  ytdlp  - free, no key. Excellent for YouTube/Shorts, works for TikTok, and
           needs browser cookies for Instagram. Default.
  apify  - paid but cheap (~$1.00/1k results) and the reliable path for
           Instagram at volume. Enabled by setting APIFY_TOKEN.
  csv    - manual export or fixture. Always available, zero dependencies.
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared import config  # noqa: E402

DEFAULT_MULTIPLE = 3.0
MIN_POSTS_FOR_BASELINE = 6


@dataclass
class Post:
    creator: str
    platform: str
    url: str
    title: str
    views: int
    posted_at: str = ""
    duration: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- adapters


def fetch_ytdlp(handle: str, *, limit: int = 30) -> list[Post]:
    """Free adapter. `handle` is any yt-dlp-resolvable channel or profile URL."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        print("  ! yt-dlp not installed (pip install yt-dlp)")
        return []

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
        "skip_download": True,
        "ignoreerrors": True,
    }
    posts: list[Post] = []
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(handle, download=False)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! yt-dlp failed for {handle}: {str(exc)[:160]}")
        return []

    entries = (info or {}).get("entries") or []
    for e in entries:
        if not e:
            continue
        views = e.get("view_count")
        if views is None:
            continue
        posts.append(
            Post(
                creator=(info or {}).get("uploader") or handle,
                platform=(e.get("extractor_key") or "unknown").lower(),
                url=e.get("url") or e.get("webpage_url") or "",
                title=e.get("title") or "",
                views=int(views),
                posted_at=str(e.get("upload_date") or e.get("timestamp") or ""),
                duration=float(e.get("duration") or 0),
            )
        )
    return posts


def fetch_apify(handle: str, *, limit: int = 30) -> list[Post]:
    """Paid adapter for Instagram. Set APIFY_TOKEN to enable."""
    token = os.getenv("APIFY_TOKEN", "")
    if not token:
        return []
    import requests

    actor = os.getenv("APIFY_IG_ACTOR", "apify~instagram-reel-scraper")
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={token}"
    payload = {"username": [handle.strip().lstrip("@")], "resultsLimit": limit}
    try:
        r = requests.post(url, json=payload, timeout=300)
        r.raise_for_status()
        items = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! Apify failed for {handle}: {str(exc)[:160]}")
        return []

    posts: list[Post] = []
    for it in items:
        views = it.get("videoPlayCount") or it.get("videoViewCount") or it.get("playCount")
        if not views:
            continue
        posts.append(
            Post(
                creator=it.get("ownerUsername") or handle,
                platform="instagram",
                url=it.get("url") or "",
                title=(it.get("caption") or "")[:200],
                views=int(views),
                posted_at=str(it.get("timestamp") or ""),
                duration=float(it.get("videoDuration") or 0),
                extra={"likes": it.get("likesCount"), "comments": it.get("commentsCount")},
            )
        )
    return posts


def fetch_csv(path: str, **_: Any) -> list[Post]:
    """Manual adapter: a CSV with creator,platform,url,title,views[,posted_at,duration]."""
    p = Path(path)
    if not p.exists():
        print(f"  ! csv not found: {p}")
        return []
    posts: list[Post] = []
    with p.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                posts.append(
                    Post(
                        creator=row.get("creator", "").strip(),
                        platform=row.get("platform", "csv").strip(),
                        url=row.get("url", "").strip(),
                        title=row.get("title", "").strip(),
                        views=int(float(row.get("views") or 0)),
                        posted_at=row.get("posted_at", ""),
                        duration=float(row.get("duration") or 0),
                    )
                )
            except (ValueError, TypeError):
                continue
    return posts


ADAPTERS = {"ytdlp": fetch_ytdlp, "apify": fetch_apify, "csv": fetch_csv}


# ---------------------------------------------------------------- outliers


def find_outliers(
    posts: list[Post], *, multiple: float = DEFAULT_MULTIPLE
) -> list[dict[str, Any]]:
    """Group by creator, compute a median baseline, return posts above the bar."""
    by_creator: dict[str, list[Post]] = {}
    for p in posts:
        by_creator.setdefault(p.creator, []).append(p)

    out: list[dict[str, Any]] = []
    for creator, items in by_creator.items():
        views = [p.views for p in items if p.views > 0]
        if len(views) < MIN_POSTS_FOR_BASELINE:
            print(f"  - {creator}: only {len(views)} posts, need "
                  f"{MIN_POSTS_FOR_BASELINE} for a baseline; skipped")
            continue
        baseline = statistics.median(views)
        if baseline <= 0:
            continue
        for p in items:
            ratio = p.views / baseline
            if ratio >= multiple:
                out.append(
                    {
                        "creator": creator,
                        "platform": p.platform,
                        "url": p.url,
                        "title": p.title,
                        "views": p.views,
                        "baseline_median": baseline,
                        "multiple": round(ratio, 2),
                        "posted_at": p.posted_at,
                        "duration": p.duration,
                    }
                )
        print(f"  - {creator}: baseline {int(baseline):,} views over {len(views)} posts")

    return sorted(out, key=lambda r: r["multiple"], reverse=True)


def load_watchlist(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("creators", []) if isinstance(data, dict) else data


def mine(
    watchlist_path: Path,
    *,
    multiple: float = DEFAULT_MULTIPLE,
    limit: int = 30,
) -> list[dict[str, Any]]:
    creators = load_watchlist(watchlist_path)
    if not creators:
        print(f"  ! empty watchlist: {watchlist_path}")
        return []

    all_posts: list[Post] = []
    for c in creators:
        source = c.get("source", "ytdlp")
        handle = c.get("handle") or c.get("url") or ""
        if not handle:
            continue
        fn = ADAPTERS.get(source)
        if fn is None:
            print(f"  ! unknown source {source!r} for {handle}")
            continue
        print(f"  fetching {handle} via {source}")
        all_posts.extend(fn(handle, limit=limit))

    print(f"\n  {len(all_posts)} posts collected")
    return find_outliers(all_posts, multiple=multiple)
