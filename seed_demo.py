"""Load demo fixtures into the database."""

from __future__ import annotations

import json
import sys

import config
import db
from logutil import get_logger

logger = get_logger(__name__)


def seed() -> int:
    """Load all JSON fixtures into the database. Returns count loaded."""
    db.init_db()
    fixtures = sorted(config.FIXTURES_DIR.glob("*.json"))
    if not fixtures:
        logger.error("No fixtures in %s — run export_fixtures.py first.", config.FIXTURES_DIR)
        return 0

    loaded = 0
    for fixture_path in fixtures:
        with open(fixture_path, encoding="utf-8") as f:
            video = json.load(f)
        video_id = video.get("video_id") or fixture_path.stem
        db.upsert_video(
            video_id,
            title=video.get("title", ""),
            url=video.get("url", f"https://www.youtube.com/watch?v={video_id}"),
            status=db.STATUS_DONE,
            summary=video.get("summary", ""),
            key_points=json.loads(video["key_points"]) if isinstance(video.get("key_points"), str) else video.get("key_points", []),
            transcript_source=video.get("transcript_source", "demo"),
            error_message="",
            playlist_type=video.get("playlist_type", db.PLAYLIST_GENERAL),
            user_agenda=video.get("user_agenda", ""),
            research_data=video.get("research_data", ""),
            auto_agenda=video.get("auto_agenda", ""),
            manual_summary=video.get("manual_summary", ""),
            manual_key_points=video.get("manual_key_points"),
            playlist_id=video.get("playlist_id", ""),
            structured_insights=video.get("structured_insights", "{}"),
            usage_data=video.get("usage_data", "{}"),
            channel_name=video.get("channel_name", ""),
        )
        loaded += 1
        logger.info("[seed] Loaded: %s", video.get("title", video_id))

    logger.info("[seed] Seeded %d demo video(s).", loaded)
    return loaded


if __name__ == "__main__":
    count = seed()
    sys.exit(0 if count else 1)
