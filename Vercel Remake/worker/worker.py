from __future__ import annotations

import json
import re
import os
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor


REMAKE_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = REMAKE_ROOT.parent
load_dotenv()
load_dotenv(LEGACY_ROOT / ".env", override=False)
API_APP_ROOT = REMAKE_ROOT / "api"
sys.path.insert(0, str(API_APP_ROOT))
from app import db as api_db
from app.pgconnect import connect_postgres
from app.runtime_settings import apply_runtime_provider_keys

apply_runtime_provider_keys(override=True)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "5"))
LEGACY_APP_ROOT = os.getenv("LEGACY_APP_ROOT", str(LEGACY_ROOT)).strip()

# Minutes to wait before each automatic retry; a job gets len + 1 tries in total.
RETRY_DELAYS_MIN = [2, 10, 60, 360, 1440]
MAX_ATTEMPTS = len(RETRY_DELAYS_MIN) + 1
STALE_RUNNING_MIN = 45
HEAL_EVERY_SEC = 30 * 60
HEAL_AFTER_HOURS = 12
HEAL_MAX_RUNS_PER_VIDEO = 10
PERMANENT_ERRORS = (
    "video is unavailable",
    "private video",
    "has been removed",
    "unknown video",
    "missing an agenda",
    "unsupported job kind",
)


@contextmanager
def connect() -> Iterator[Any]:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured.")
    conn = connect_postgres(url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_job() -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            WITH next_job AS (
                SELECT id
                FROM knowledge_jobs
                WHERE (status = 'queued' AND (run_after IS NULL OR run_after <= now()))
                   OR (status = 'running' AND locked_at < now() - make_interval(mins => %s))
                ORDER BY COALESCE(run_after, created_at)
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE knowledge_jobs j
            SET status = 'running',
                attempts = attempts + 1,
                locked_at = now(),
                locked_by = %s,
                updated_at = now(),
                run_after = NULL,
                progress = 'Starting',
                max_attempts = %s
            FROM next_job
            WHERE j.id = next_job.id
            RETURNING j.*
            """,
            (STALE_RUNNING_MIN, WORKER_ID, MAX_ATTEMPTS),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def finish_job(job_id: str) -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE knowledge_jobs
            SET status = 'done',
                error = '',
                progress = '',
                updated_at = now(),
                finished_at = now(),
                locked_by = '',
                locked_at = NULL
            WHERE id = %s
            """,
            (job_id,),
        )


def _is_permanent(error: str) -> bool:
    lower = error.lower()
    return any(marker in lower for marker in PERMANENT_ERRORS)


def fail_job(job: dict[str, Any], error: str) -> str:
    """Schedule the next automatic retry, or give up. Returns the message stored on the job."""
    attempts = int(job.get("attempts") or 1)
    permanent = _is_permanent(error)
    retry = attempts < MAX_ATTEMPTS and not permanent
    delay = 0
    if retry:
        delay = RETRY_DELAYS_MIN[min(attempts - 1, len(RETRY_DELAYS_MIN) - 1)]
        quota_reset = re.search(r"resets in about (\d+) h", error)
        if quota_reset:
            delay = max(delay, int(quota_reset.group(1)) * 60 + 10)
        when = f"{delay} min" if delay < 60 else f"{delay // 60} h"
        stored = f"{error} — automatic retry in {when} (attempt {attempts + 1} of {MAX_ATTEMPTS})"
    elif permanent:
        stored = f"{error} — not retrying: this needs a manual fix"
    else:
        stored = f"{error} — gave up after {attempts} attempts; the worker will try again in {HEAL_AFTER_HOURS} h"
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE knowledge_jobs
            SET status = %s,
                error = %s,
                progress = '',
                run_after = CASE WHEN %s THEN now() + make_interval(mins => %s) ELSE NULL END,
                updated_at = now(),
                finished_at = CASE WHEN %s THEN finished_at ELSE now() END,
                locked_by = '',
                locked_at = NULL
            WHERE id = %s
            """,
            ("queued" if retry else "failed", stored[:2000], retry, delay, retry, job["id"]),
        )
    if job.get("kind") == "process_video":
        _set_video_error(job["video_id"], stored)
    return stored


def _set_video_error(video_id: str, message: str) -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE videos SET status = 'failed', error_message = %s WHERE video_id = %s AND status <> 'done'",
            (message[:2000], video_id),
        )


def _set_progress(job_id: str, step: str) -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE knowledge_jobs SET progress = %s, updated_at = now() WHERE id = %s",
            (step[:300], job_id),
        )


def heal_failed_videos() -> int:
    """Re-queue failed videos whose last attempt is old, so failures resolve without a click."""
    with connect() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT v.video_id,
                   (SELECT j.payload FROM knowledge_jobs j
                     WHERE j.video_id = v.video_id AND j.kind = 'process_video'
                     ORDER BY j.created_at DESC LIMIT 1) AS last_payload
            FROM videos v
            WHERE v.status = 'failed'
              AND NOT EXISTS (
                  SELECT 1 FROM knowledge_jobs j
                  WHERE j.video_id = v.video_id AND j.status IN ('queued', 'running'))
              AND NOT EXISTS (
                  SELECT 1 FROM knowledge_jobs j
                  WHERE j.video_id = v.video_id AND j.kind = 'process_video'
                    AND COALESCE(j.finished_at, j.updated_at) > now() - make_interval(hours => %s))
              AND (SELECT COUNT(*) FROM knowledge_jobs j
                   WHERE j.video_id = v.video_id AND j.kind = 'process_video') < %s
              AND position('not retrying' in COALESCE(v.error_message, '')) = 0
            LIMIT 3
            """,
            (HEAL_AFTER_HOURS, HEAL_MAX_RUNS_PER_VIDEO),
        )
        rows = [dict(row) for row in cur.fetchall()]
    for row in rows:
        payload = row.get("last_payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        payload = {**(payload if isinstance(payload, dict) else {}), "source": "auto-heal"}
        api_db.enqueue_process(row["video_id"], payload)
        print(f"Auto-heal queued {row['video_id']}", flush=True)
    return len(rows)


def refresh_legacy_provider_config() -> None:
    status = apply_runtime_provider_keys(override=True)
    config_module = sys.modules.get("config")
    if config_module is not None:
        mapping = {
            "YOUTUBE_API_KEY": os.getenv("YOUTUBE_API_KEY", ""),
            "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
            "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
            "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
            "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", ""),
        }
        for name, value in mapping.items():
            setattr(config_module, name, value)


def load_legacy_processor():
    if not LEGACY_APP_ROOT:
        raise RuntimeError("LEGACY_APP_ROOT must point to the current Streamlit project root.")
    root = Path(LEGACY_APP_ROOT)
    if not (root / "poll.py").exists():
        raise RuntimeError(f"LEGACY_APP_ROOT does not contain poll.py: {root}")
    sys.path.insert(0, str(root))
    from poll import process_one

    return process_one


def _payload(job: dict[str, Any]) -> dict[str, Any]:
    raw = job.get("payload") or {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _process_custom_agenda(video_id: str, agenda: str) -> None:
    if not agenda.strip():
        raise RuntimeError("Custom agenda job is missing an agenda.")
    refresh_legacy_provider_config()
    load_legacy_processor()
    import db as legacy_db
    from pipeline import _friendly_api_error, process_video

    legacy_db.init_db()
    video = legacy_db.get_video(video_id)
    if not video:
        raise RuntimeError(f"Unknown video: {video_id}")

    legacy_db.upsert_video(video_id, user_agenda=agenda.strip(), status=legacy_db.STATUS_PROCESSING, error_message="")
    try:
        result = process_video(
            video_id,
            video.get("title") or video_id,
            playlist_type=video.get("playlist_type", legacy_db.PLAYLIST_GENERAL),
            playlist_id=video.get("playlist_id", "") or "",
            user_agenda=agenda.strip(),
        )
        legacy_db.upsert_video(
            video_id,
            status=legacy_db.STATUS_DONE,
            summary=result["summary"],
            key_points=result["key_points"],
            transcript_source=result["transcript_source"],
            error_message="",
            user_agenda=agenda.strip(),
            research_data=json.dumps(result.get("research_data", {}), ensure_ascii=False),
            structured_insights=json.dumps(result.get("structured_insights", {}), ensure_ascii=False),
            auto_agenda="",
            usage_data=json.dumps(result.get("usage_data", {}), ensure_ascii=False),
            channel_name=result.get("channel_name", ""),
        )
        try:
            from search import index_saved_auto_insights

            indexed = index_saved_auto_insights(video_id)
            if not indexed:
                legacy_db.record_index_error(video_id, "custom agenda index not written after extraction")
        except Exception as exc:
            legacy_db.record_index_error(video_id, str(exc)[:300])
    except Exception as exc:
        err = _friendly_api_error(exc)
        legacy_db.upsert_video(video_id, status=legacy_db.STATUS_FAILED, error_message=err)
        raise RuntimeError(err) from exc


def _sync_playlists(job: dict[str, Any]) -> None:
    payload = _payload(job)
    max_process_raw = payload.get("max_process", 3)
    try:
        max_process = int(max_process_raw) if max_process_raw is not None else None
    except (TypeError, ValueError):
        max_process = 3
    if max_process is not None:
        max_process = max(0, min(max_process, 50))

    refresh_legacy_provider_config()
    load_legacy_processor()
    from poll import run_poll

    code = run_poll(max_process=max_process)
    if code != 0:
        raise RuntimeError(f"playlist sync exited with code {code}")


def handle_job(job: dict[str, Any]) -> None:
    if job["kind"] == "sync_playlists":
        _sync_playlists(job)
        return
    if job["kind"] != "process_video":
        raise RuntimeError(f"Unsupported job kind: {job['kind']}")
    refresh_legacy_provider_config()
    payload = _payload(job)
    if payload.get("mode") == "custom":
        agenda = str(payload.get("agenda") or "").strip()
        if not agenda:
            load_legacy_processor()
            import db as legacy_db

            video = legacy_db.get_video(job["video_id"])
            agenda = str((video or {}).get("user_agenda") or "").strip()
        _process_custom_agenda(job["video_id"], agenda)
        return

    process_one = load_legacy_processor()
    refresh_legacy_provider_config()
    code = process_one(job["video_id"], manual_regenerate=False)
    if code != 0:
        import db as legacy_db

        video = legacy_db.get_video(job["video_id"]) or {}
        raise RuntimeError(video.get("error_message") or f"processing stopped (exit code {code})")


def heartbeat(status: str, job: dict[str, Any] | None = None, note: str = "") -> None:
    try:
        api_db.record_worker_heartbeat(
            WORKER_ID,
            status=status,
            current_job_id=str((job or {}).get("id") or ""),
            current_video_id=str((job or {}).get("video_id") or ""),
            note=note,
        )
    except Exception as exc:
        print(f"Heartbeat failed: {exc}", flush=True)


def _start_reporting(job: dict[str, Any]) -> None:
    import progress

    def report(step: str) -> None:
        _set_progress(job["id"], step)
        heartbeat("running", job, step)

    progress.set_reporter(report)


def _stop_reporting() -> None:
    import progress

    progress.set_reporter(None)


def _prepare_legacy() -> None:
    try:
        load_legacy_processor()
        refresh_legacy_provider_config()
        import llm
        import provider_state

        provider_state.publish_slots(models=llm._gemini_model_chain())
    except Exception as exc:
        print(f"Could not publish AI key list: {exc}", flush=True)


def requeue_interrupted_jobs() -> None:
    """Jobs this machine was running when it restarted go straight back to the queue."""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE knowledge_jobs
            SET status = 'queued', run_after = NULL, locked_by = '', locked_at = NULL,
                progress = '', error = 'Worker restarted during this job — resuming', updated_at = now()
            WHERE status = 'running' AND locked_by LIKE %s
            """,
            (f"{socket.gethostname()}:%",),
        )


def main() -> None:
    print(f"InsightEngine worker started as {WORKER_ID}", flush=True)
    api_db.ensure_job_schema()
    requeue_interrupted_jobs()
    _prepare_legacy()
    heartbeat("starting", note="worker booted")
    last_heal = 0.0
    while True:
        if time.time() - last_heal > HEAL_EVERY_SEC:
            last_heal = time.time()
            try:
                heal_failed_videos()
            except Exception as exc:
                print(f"Auto-heal sweep failed: {exc}", flush=True)
        job = claim_job()
        if not job:
            heartbeat("idle")
            time.sleep(POLL_SECONDS)
            continue
        print(f"Claimed {job['id']} for {job['video_id']} (attempt {job['attempts']})", flush=True)
        heartbeat("running", job, f"handling {job['kind']}")
        _start_reporting(job)
        try:
            handle_job(job)
        except Exception as exc:
            stored = fail_job(job, str(exc))
            print(f"Job failed: {job['id']} {stored}", flush=True)
            heartbeat("idle", note=f"last failure: {stored[:300]}")
        else:
            finish_job(job["id"])
            print(f"Job done: {job['id']}", flush=True)
            heartbeat("idle", note=f"finished {job['kind']} for {job['video_id']}")
        finally:
            _stop_reporting()


if __name__ == "__main__":
    main()
