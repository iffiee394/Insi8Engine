#!/usr/bin/env python3
"""Overnight batch processing via Anthropic Message Batches API (~50% off)."""

from __future__ import annotations

import json
import sys

import config
import db
from llm import batch_uses_anthropic, friendly_llm_error, run_batch_phase
from pipeline import (
    _build_flat_key_points,
    _extract_urls_from_transcript,
    _format_entity_context,
    _generate_auto_agenda,
    _generate_general_agenda,
    _merge_structured_output,
    _parse_json_response,
    build_entity_prompt,
    build_holistic_prompt,
    build_recon_prompt,
    get_transcript,
)
from usage_tracker import add_to_lifetime, begin_run, extend_calls, finish_run, record_llm, record_youtube, stash_run
from video_metadata import analyze_video_description

from logutil import get_logger

logger = get_logger(__name__)


def queue_pending_for_batch(*, include_failed: bool = True) -> int:
    """Mark pending (and optionally failed) videos for batch processing."""
    db.init_db()
    count = 0
    statuses = {db.STATUS_PENDING}
    if include_failed:
        statuses.add(db.STATUS_FAILED)
    for video in db.list_videos():
        if video["status"] in statuses:
            db.upsert_video(
                video["video_id"],
                status=db.STATUS_BATCH_QUEUED,
                error_message="",
            )
            count += 1
    return count


def _save_result(video: dict, result: dict, *, usage_data: dict | None = None) -> None:
    structured_json = json.dumps(result.get("structured_insights", {}), ensure_ascii=False)
    usage_json = json.dumps(usage_data or result.get("usage_data", {}), ensure_ascii=False)
    db.upsert_video(
        video["video_id"],
        status=db.STATUS_DONE,
        summary=result["summary"],
        key_points=result["key_points"],
        transcript_source=result["transcript_source"],
        error_message="",
        research_data=json.dumps(result.get("research_data", {}), ensure_ascii=False),
        structured_insights=structured_json,
        auto_agenda=result.get("auto_agenda", ""),
        usage_data=usage_json,
        channel_name=result.get("channel_name", ""),
    )
    if usage_data:
        add_to_lifetime(usage_data)
    try:
        from search import index_saved_auto_insights

        indexed = index_saved_auto_insights(video["video_id"])
        if not indexed:
            db.record_index_error(video["video_id"], "auto index not written after batch save")
    except Exception as exc:
        logger.warning("[batch] Indexing failed after save: %s", exc)
        db.record_index_error(video["video_id"], str(exc)[:300])


def run_batch(*, max_videos: int | None = None) -> dict:
    """Process batch-queued videos using Anthropic Batch API (~50% off)."""
    db.init_db()

    queued = db.list_videos(status=db.STATUS_BATCH_QUEUED)
    if max_videos is not None:
        queued = queued[:max_videos]
    if not queued:
        return {"queued": 0, "done": 0, "failed": 0, "message": "No videos in batch queue."}

    logger.info("[batch] Processing %d video(s) via Anthropic Batch API", len(queued))
    db.set_meta("batch_status", f"preparing:{len(queued)}")

    prepared: list[dict] = []
    failed = 0

    for video in queued:
        db.upsert_video(video["video_id"], status=db.STATUS_PROCESSING, error_message="")
        try:
            transcript, source = get_transcript(video["video_id"])
            if not transcript.strip():
                raise RuntimeError("Empty transcript")
            desc_data = analyze_video_description(video["video_id"])
            prepared.append({
                "video": video,
                "transcript": transcript,
                "source": source,
                "desc_data": desc_data,
                "transcript_urls": _extract_urls_from_transcript(transcript),
                "playlist_type": video.get("playlist_type", db.PLAYLIST_GENERAL),
                "playlist_id": video.get("playlist_id", ""),
            })
        except Exception as exc:
            failed += 1
            err = friendly_llm_error(exc)
            logger.error("[batch] Prep failed %s: %s", video["title"], err)
            db.upsert_video(video["video_id"], status=db.STATUS_FAILED, error_message=err)

    if not prepared:
        db.set_meta("batch_status", "failed:prep")
        return {"queued": len(queued), "done": 0, "failed": failed, "message": "All prep failed."}

    db.set_meta("batch_status", "recon")
    recon_items = [
        (f"{p['video']['video_id']}-recon", build_recon_prompt(p["transcript"], p["video"]["title"]))
        for p in prepared
    ]
    recon_texts = run_batch_phase("recon", recon_items)
    for p in prepared:
        vid = p["video"]["video_id"]
        raw = recon_texts.get(f"{vid}-recon", "")
        try:
            p["recon"] = _parse_json_response(raw) if raw else {}
        except ValueError:
            p["recon"] = {}

    entity_texts: dict[str, str] = {}
    if prepared:
        db.set_meta("batch_status", "entities")
        entity_items = [
            (
                f"{p['video']['video_id']}-entity",
                build_entity_prompt(p["transcript"], p["video"]["title"], p["recon"]),
            )
            for p in prepared
        ]
        entity_texts = run_batch_phase("entities", entity_items)
        for p in prepared:
            vid = p["video"]["video_id"]
            raw = entity_texts.get(f"{vid}-entity", "")
            try:
                p["entities"] = _parse_json_response(raw) if raw else {}
            except ValueError:
                p["entities"] = {}

    from researcher import research_all, research_links_only

    for p in prepared:
        profile_prompt = db.get_profile_prompt(
            playlist_id=p["playlist_id"] if p["playlist_id"] else None
        )
        p["profile_prompt"] = profile_prompt
        is_podcast = p["playlist_type"] == db.PLAYLIST_PODCAST
        if is_podcast:
            p["agenda"] = _generate_auto_agenda(p["recon"], profile_prompt)
        else:
            p["agenda"] = _generate_general_agenda(p["recon"], profile_prompt)
        p["auto_agenda"] = p["agenda"]

        if is_podcast:
            entities = p.get("entities", {})
            p["entity_context"] = _format_entity_context(entities)
        else:
            p["entity_context"] = _format_entity_context(p.get("entities", {}))

        vid = p["video"]["video_id"]
        begin_run(vid, p["video"]["title"])
        record_youtube()
        if is_podcast:
            entities = p.get("entities", {})
            p["research_data"] = research_all(
                guest_name=p["recon"].get("guest_name", "").strip(),
                topics=p["recon"].get("main_topics", []),
                targets=entities.get("research_targets", []),
                description_urls=p["desc_data"].get("urls", []),
                transcript_urls=p["transcript_urls"],
            )
        else:
            p["research_data"] = research_links_only(
                description_urls=p["desc_data"].get("urls", []),
                transcript_urls=p["transcript_urls"],
                description_text=p["desc_data"].get("description", ""),
                channel_title=p["desc_data"].get("channel_title", ""),
            )
        p["research_data"]["channel_title"] = p["desc_data"].get("channel_title", "")
        p["research_usage_calls"] = stash_run()

    db.set_meta("batch_status", "extract")
    extract_items: list[tuple[str, str]] = []
    for p in prepared:
        vid = p["video"]["video_id"]
        extract_items.append((
            f"{vid}-extract",
            build_holistic_prompt(
                p["transcript"],
                p["video"]["title"],
                recon=p["recon"],
                agenda=p.get("agenda", ""),
                profile_prompt=p.get("profile_prompt", db.get_profile_prompt()),
                research_summary=p.get("research_data", {}).get("combined_summary", ""),
                entity_context=p.get("entity_context", ""),
                description_context=p["desc_data"].get("description", ""),
            ),
        ))

    extract_texts = run_batch_phase("extract", extract_items)
    done = 0
    anthropic_batch = batch_uses_anthropic()

    for p in prepared:
        video = p["video"]
        vid = video["video_id"]
        raw = extract_texts.get(f"{vid}-extract", "")
        try:
            begin_run(vid, video["title"])
            extend_calls(p.get("research_usage_calls", []))
            if not p.get("research_usage_calls"):
                record_youtube()
            recon_prompt = build_recon_prompt(p["transcript"], video["title"])
            recon_raw = recon_texts.get(f"{vid}-recon", "")
            if recon_raw:
                record_llm(
                    provider="anthropic" if anthropic_batch else "gemini",
                    model=_deep_model() if anthropic_batch else _gemini_model(),
                    operation="batch:recon",
                    prompt=recon_prompt,
                    response=recon_raw,
                    batch=anthropic_batch,
                )
            if p["playlist_type"] == db.PLAYLIST_PODCAST:
                entity_raw = entity_texts.get(f"{vid}-entity", "")
            else:
                entity_raw = entity_texts.get(f"{vid}-entity", "")
            if entity_raw:
                record_llm(
                    provider="anthropic" if anthropic_batch else "gemini",
                    model=_deep_model() if anthropic_batch else _gemini_model(),
                    operation="batch:entities",
                    prompt=build_entity_prompt(p["transcript"], video["title"], p["recon"]),
                    response=entity_raw,
                    batch=anthropic_batch,
                )
            if raw:
                extract_prompt = build_holistic_prompt(
                    p["transcript"],
                    video["title"],
                    recon=p["recon"],
                    agenda=p.get("agenda", ""),
                    profile_prompt=p.get("profile_prompt", db.get_profile_prompt()),
                    research_summary=p.get("research_data", {}).get("combined_summary", ""),
                    entity_context=p.get("entity_context", ""),
                    description_context=p["desc_data"].get("description", ""),
                )
                record_llm(
                    provider="anthropic" if anthropic_batch else "gemini",
                    model=_deep_model() if anthropic_batch else _gemini_model(),
                    operation="batch:extract",
                    prompt=extract_prompt,
                    response=raw,
                    batch=anthropic_batch,
                )
            usage_data = finish_run()

            if not raw:
                raise RuntimeError("Empty batch extraction result")
            result_json = _parse_json_response(raw)
            structured = _merge_structured_output(
                result_json,
                research_data=p.get("research_data", {}),
                description_urls=p["desc_data"].get("urls", []),
                transcript_urls=p["transcript_urls"],
                description_resources=p["desc_data"].get("resource_lines", []),
            )
            research_data = p.get("research_data", {})
            research_data["links"] = structured.get("links", research_data.get("links", {}))
            research_data["entities"] = p.get("entities", {})
            result = {
                "summary": structured.get("summary") or result_json.get("summary", ""),
                "key_points": _build_flat_key_points(result_json),
                "transcript_source": p["source"],
                "research_data": research_data,
                "structured_insights": structured,
                "auto_agenda": p.get("auto_agenda", ""),
                "channel_name": p["desc_data"].get("channel_title", ""),
            }
            _save_result(video, result, usage_data=usage_data)
            done += 1
            logger.info("[batch] Done: %s", video["title"])
        except Exception as exc:
            finish_run()
            failed += 1
            err = friendly_llm_error(exc)
            logger.error("[batch] Save failed %s: %s", video["title"], err)
            db.upsert_video(vid, status=db.STATUS_FAILED, error_message=err)

    msg = f"Batch complete: {done} done, {failed} failed."
    db.set_meta("batch_status", f"done:{done}:{failed}")
    logger.info("[batch] %s", msg)
    return {"queued": len(queued), "done": done, "failed": failed, "message": msg}


if __name__ == "__main__":
    if "--queue" in sys.argv:
        n = queue_pending_for_batch()
        logger.info("[batch] Queued %d video(s)", n)
    raise SystemExit(0 if run_batch().get("failed", 1) == 0 else 1)
