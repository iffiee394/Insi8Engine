#!/usr/bin/env python3
"""Bounded auto-index repair. Dry-run by default. Does not re-extract videos."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db
from search import insights_to_chunks, source_hash_for_chunks


def _plan(scope: str, video_id: str | None, limit: int) -> list[dict]:
    db.init_db()
    videos = db.list_videos(status=db.STATUS_DONE)
    if video_id:
        videos = [v for v in videos if v["video_id"] == video_id]
    existing = {}
    for row in db.get_all_embeddings():
        existing.setdefault(row["video_id"], 0)
        existing[row["video_id"]] += 1

    planned = []
    for video in videos:
        structured = db.parse_structured_insights(video.get("structured_insights", "{}"))
        chunks, reason = insights_to_chunks(structured)
        stored = existing.get(video["video_id"], 0)
        expected = len(chunks)
        state = None
        try:
            state = db.get_index_state(video["video_id"])
        except Exception:
            state = None
        source_hash = source_hash_for_chunks(chunks) if chunks else ""
        if expected == 0:
            action = "ineligible"
        elif stored == 0:
            action = "missing"
        elif stored != expected:
            action = "partial"
        elif state and state.get("source_hash") and state.get("source_hash") != source_hash:
            action = "stale"
        elif not state or not state.get("model") or state.get("model") == "unknown":
            action = "unverified"
        else:
            action = "current"
        if scope != "all" and action != scope:
            continue
        if action == "current":
            continue
        planned.append(
            {
                "video_id": video["video_id"],
                "action": action,
                "reason": reason or "",
                "expected": expected,
                "stored": stored,
            }
        )
        if limit and len(planned) >= limit:
            break
    return planned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Repair auto insight indexes. Dry-run default.")
    parser.add_argument("--apply", action="store_true", help="Write replacement indexes")
    parser.add_argument("--limit", type=int, default=5, help="Max videos to consider")
    parser.add_argument("--video-id", dest="video_id", default=None)
    parser.add_argument(
        "--scope",
        choices=("missing", "partial", "stale", "unverified", "ineligible", "all"),
        default="missing",
    )
    args = parser.parse_args(argv)

    planned = _plan(args.scope, args.video_id, args.limit)
    counts: dict[str, int] = {}
    for item in planned:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
        print(f"{item['action']}\t{item['video_id']}\texpected={item['expected']}\tstored={item['stored']}")
    print(f"planned: {len(planned)} {counts}")
    if not args.apply:
        print("dry-run: no embeddings written")
        return 0

    from search import index_saved_auto_insights

    ok = fail = 0
    for item in planned:
        if item["action"] == "ineligible":
            continue
        stored = index_saved_auto_insights(item["video_id"])
        if stored:
            ok += 1
        else:
            fail += 1
    print(f"applied: ok={ok} fail={fail}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
