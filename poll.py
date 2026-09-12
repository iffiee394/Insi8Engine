#!/usr/bin/env python3
"""Poll YouTube playlists and process new videos."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import config
import db
from llm import _fallback_to_anthropic, _has_anthropic, _has_gemini
from logutil import get_logger
from pipeline import _friendly_api_error, process_video
from youtube_monitor import PlaylistVideo, fetch_playlist_videos

logger = get_logger(__name__)


def _playlist_configs() -> list[tuple[str, str, str]]:
    configs: list[tuple[str, str, str]] = []
    playlists = db.list_playlists(enabled_only=True)
    if playlists:
        for pl in playlists:
            configs.append((pl["playlist_id"], pl.get("kind", db.PLAYLIST_GENERAL), pl["playlist_id"]))
        return configs

    if config.PLAYLIST_ID:
        configs.append((config.PLAYLIST_ID, db.PLAYLIST_GENERAL, config.PLAYLIST_ID))
    if config.PODCASTS_PLAYLIST_ID:
        configs.append((config.PODCASTS_PLAYLIST_ID, db.PLAYLIST_PODCAST, config.PODCASTS_PLAYLIST_ID))
    return configs


def process_one(video_id: str, *, manual_regenerate: bool = False) -> int:
    db.init_db()

    video = db.get_video(video_id)
    if not video:
        logger.error("[poll] Unknown video: %s", video_id)
        return 1

    user_agenda = video.get("user_agenda", "").strip()
    if manual_regenerate and not user_agenda:
        logger.error("[poll] Manual regenerate requires a custom agenda: %s", video["title"])
        return 1

    mode_label = "manual agenda" if manual_regenerate else "auto"
    logger.info("[poll] Processing (%s): %s (%s)", mode_label, video["title"], video_id)
    logger.info(
        "[poll] Providers: gemini=%s anthropic=%s fallback=%s groq=%s",
        _has_gemini(),
        _has_anthropic(),
        _fallback_to_anthropic(),
        bool(config.GROQ_API_KEY),
    )
    db.upsert_video(video_id, status=db.STATUS_PROCESSING, error_message="")

    playlist_id = video.get("playlist_id", "") or ""
    try:
        result = process_video(
            video_id,
            video["title"],
            playlist_type=video.get("playlist_type", db.PLAYLIST_GENERAL),
            playlist_id=playlist_id,
            user_agenda=user_agenda if manual_regenerate else "",
        )

        structured_json = json.dumps(result.get("structured_insights", {}), ensure_ascii=False)
        usage_json = json.dumps(result.get("usage_data", {}), ensure_ascii=False)
        channel = result.get("channel_name", "")

        if manual_regenerate:
            db.upsert_video(
                video_id,
                status=db.STATUS_DONE,
                manual_summary=result["summary"],
                manual_key_points=result["key_points"],
                transcript_source=result["transcript_source"],
                error_message="",
                user_agenda=user_agenda,
                usage_data=usage_json,
                channel_name=channel,
            )
        else:
            db.upsert_video(
                video_id,
                status=db.STATUS_DONE,
                summary=result["summary"],
                key_points=result["key_points"],
                transcript_source=result["transcript_source"],
                error_message="",
                research_data=json.dumps(result.get("research_data", {}), ensure_ascii=False),
                structured_insights=structured_json,
                auto_agenda=result.get("auto_agenda", ""),
                usage_data=usage_json,
                channel_name=channel,
            )
        if not manual_regenerate:
            try:
                from search import index_saved_auto_insights

                indexed = index_saved_auto_insights(video_id)
                if not indexed:
                    db.record_index_error(video_id, "auto index not written after extraction")
            except Exception as exc:
                logger.warning("[poll] Indexing failed after save: %s", exc)
                db.record_index_error(video_id, str(exc)[:300])
        logger.info("[poll] Done: %s", video["title"])
        return 0
    except Exception as exc:
        err = _friendly_api_error(exc)
        logger.error("[poll] Failed: %s — %s", video["title"], err)
        db.upsert_video(video_id, status=db.STATUS_FAILED, error_message=err)
        return 1


def _register_video(
    item: PlaylistVideo,
    playlist_type: str,
    youtube_playlist_id: str,
) -> dict | None:
    existing = db.get_video(item.video_id)
    if existing:
        db.upsert_video(
            item.video_id,
            title=item.title,
            url=item.url,
            playlist_type=playlist_type,
            playlist_id=youtube_playlist_id,
        )
        return existing

    db.upsert_video(
        item.video_id,
        title=item.title,
        url=item.url,
        playlist_type=playlist_type,
        playlist_id=youtube_playlist_id,
    )
    return db.get_video(item.video_id)


def _set_poll_progress(*, done: int, total: int, title: str = "") -> None:
    db.set_meta("poll_progress_done", str(done))
    db.set_meta("poll_progress_total", str(total))
    db.set_meta("poll_current_title", title[:200])


def _clear_poll_progress() -> None:
    db.set_meta("poll_progress_done", "")
    db.set_meta("poll_progress_total", "")
    db.set_meta("poll_current_title", "")


def run_poll(*, max_process: int | None = None) -> int:
    db.init_db()
    db.set_meta("poll_worker_running", "1")
    try:
        return _run_poll_inner(max_process=max_process)
    finally:
        db.set_meta("poll_worker_running", "0")
        _clear_poll_progress()


def _run_poll_inner(*, max_process: int | None = None) -> int:
    db.init_db()
    now = datetime.now(timezone.utc).isoformat()
    db.set_meta("last_poll_at", now)

    configs = _playlist_configs()
    if not configs:
        msg = "No playlists configured. Add playlists in the dashboard or set PLAYLIST_ID in .env"
        logger.error("[poll] %s", msg)
        db.set_meta("last_poll_error", msg)
        return 1

    total_found = 0
    processed = 0
    errors: list[str] = []

    for youtube_id, playlist_type, db_id in configs:
        pl = db.get_playlist(db_id)
        label = pl.get("name", playlist_type) if pl else playlist_type
        try:
            items = fetch_playlist_videos(youtube_id)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            continue

        total_found += len(items)
        db.set_meta(f"playlist_count_{playlist_type}", str(len(items)))

        for item in items:
            _register_video(item, playlist_type, db_id)

    pending = sorted(
        [v for v in db.list_videos(status=db.STATUS_PENDING)],
        key=lambda v: v.get("added_at", ""),
    )
    if pending:
        limit_label = str(max_process) if max_process is not None else "all"
        logger.info("[poll] %d video(s) in queue — processing %s", len(pending), limit_label)
    _set_poll_progress(done=0, total=len(pending))
    for video in pending:
        if max_process is not None and processed >= max_process:
            logger.info("[poll] Reached max_process=%s, stopping early.", max_process)
            break
        _set_poll_progress(done=processed, total=len(pending), title=video.get("title", ""))
        if process_one(video["video_id"], manual_regenerate=False) == 0:
            processed += 1
        _set_poll_progress(done=processed, total=len(pending))

    if errors:
        db.set_meta("last_poll_error", " | ".join(errors))
    else:
        db.set_meta("last_poll_error", "")

    db.set_meta("playlist_video_count", str(total_found))
    logger.info("[poll] Finished. %d video(s) processed.", processed)
    return 0 if not errors else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Poll playlists and process videos")
    parser.add_argument("--one", metavar="VIDEO_ID", help="Process a single video")
    parser.add_argument("--manual", action="store_true", help="Manual agenda regenerate (with --one)")
    parser.add_argument("--url", help="Ingest a pasted YouTube URL (use with --folder)")
    parser.add_argument(
        "--folder",
        choices=["video", "podcast", "general"],
        default="video",
        help="Video (general) or Podcast folder for --url",
    )
    args = parser.parse_args()

    if args.url:
        from ingest import ingest_pasted_url

        result = ingest_pasted_url(args.url, args.folder)
        print(result.message)
        if not result.ok:
            raise SystemExit(1)
        if result.already_done:
            raise SystemExit(0)
        db.set_meta("poll_worker_running", "1")
        _set_poll_progress(done=0, total=1, title="")
        try:
            vid = db.get_video(result.video_id)
            if vid:
                _set_poll_progress(done=0, total=1, title=vid.get("title", ""))
            code = process_one(result.video_id, manual_regenerate=False)
            _set_poll_progress(done=1, total=1)
            raise SystemExit(code)
        finally:
            db.set_meta("poll_worker_running", "0")
            _clear_poll_progress()

    if args.one:
        db.init_db()
        db.set_meta("poll_worker_running", "1")
        _set_poll_progress(done=0, total=1, title="")
        try:
            vid = db.get_video(args.one)
            if vid:
                _set_poll_progress(done=0, total=1, title=vid.get("title", ""))
            code = process_one(args.one, manual_regenerate=args.manual)
            _set_poll_progress(done=1, total=1)
            raise SystemExit(code)
        finally:
            db.set_meta("poll_worker_running", "0")
            _clear_poll_progress()

    raise SystemExit(run_poll())
