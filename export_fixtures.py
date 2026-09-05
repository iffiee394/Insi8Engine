"""Export processed videos from DB as JSON fixtures for demo mode."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

import config
import db


def export_videos(video_ids: list[str]) -> int:
    config.FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    count = 0
    for vid in video_ids:
        row = conn.execute("SELECT * FROM videos WHERE video_id = ?", (vid,)).fetchone()
        if not row:
            print(f"Skip (not found): {vid}")
            continue
        data = dict(row)
        path = config.FIXTURES_DIR / f"{vid}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"Exported: {data.get('title', vid)} -> {path}")
        count += 1
    conn.close()
    return count


def export_done(limit: int = 5) -> int:
    videos = [v for v in db.list_videos(status=db.STATUS_DONE)][:limit]
    return export_videos([v["video_id"] for v in videos])


if __name__ == "__main__":
    db.init_db()
    parser = argparse.ArgumentParser(description="Export videos as demo fixtures")
    parser.add_argument("--ids", nargs="*", help="Specific video IDs")
    parser.add_argument("--done", type=int, default=0, help="Export N most recent done videos")
    args = parser.parse_args()
    if args.ids:
        n = export_videos(args.ids)
    elif args.done:
        n = export_done(args.done)
    else:
        print("Usage: python export_fixtures.py --ids ID1 ID2  OR  --done 5")
        sys.exit(1)
    sys.exit(0 if n else 1)
