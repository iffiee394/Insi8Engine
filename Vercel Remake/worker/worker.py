from __future__ import annotations

import json
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
from app.pgconnect import connect_postgres
from app.runtime_settings import apply_runtime_provider_keys

apply_runtime_provider_keys(override=True)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "5"))
LEGACY_APP_ROOT = os.getenv("LEGACY_APP_ROOT", str(LEGACY_ROOT)).strip()


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
                WHERE status = 'queued'
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE knowledge_jobs j
            SET status = 'running',
                attempts = attempts + 1,
                locked_at = now(),
                locked_by = %s,
                updated_at = now(),
                error = ''
            FROM next_job
            WHERE j.id = next_job.id
            RETURNING j.*
            """,
            (WORKER_ID,),
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
                updated_at = now(),
                finished_at = now(),
                locked_by = '',
                locked_at = NULL
            WHERE id = %s
            """,
            (job_id,),
        )


def fail_job(job: dict[str, Any], error: str) -> None:
    next_status = "failed" if job["attempts"] >= job["max_attempts"] else "queued"
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE knowledge_jobs
            SET status = %s,
                error = %s,
                updated_at = now(),
                finished_at = CASE WHEN %s = 'failed' THEN now() ELSE finished_at END,
                locked_by = '',
                locked_at = NULL
            WHERE id = %s
            """,
            (next_status, error[:1000], next_status, job["id"]),
        )


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


def handle_job(job: dict[str, Any]) -> None:
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
        raise RuntimeError(f"process_one exited with code {code}")


def main() -> None:
    print(f"InsightEngine worker started as {WORKER_ID}", flush=True)
    while True:
        job = claim_job()
        if not job:
            time.sleep(POLL_SECONDS)
            continue
        print(f"Claimed {job['id']} for {job['video_id']}", flush=True)
        try:
            handle_job(job)
        except Exception as exc:
            print(f"Job failed: {job['id']} {exc}", flush=True)
            fail_job(job, str(exc))
        else:
            finish_job(job["id"])
            print(f"Job done: {job['id']}", flush=True)


if __name__ == "__main__":
    main()
