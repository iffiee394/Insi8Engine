from __future__ import annotations

import os
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor


REMAKE_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = REMAKE_ROOT.parent
load_dotenv()
load_dotenv(LEGACY_ROOT / ".env", override=False)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "5"))
LEGACY_APP_ROOT = os.getenv("LEGACY_APP_ROOT", str(LEGACY_ROOT)).strip()


@contextmanager
def connect() -> Iterator[Any]:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured.")
    conn = psycopg2.connect(url, connect_timeout=15, cursor_factory=RealDictCursor)
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


def load_legacy_processor():
    if not LEGACY_APP_ROOT:
        raise RuntimeError("LEGACY_APP_ROOT must point to the current Streamlit project root.")
    root = Path(LEGACY_APP_ROOT)
    if not (root / "poll.py").exists():
        raise RuntimeError(f"LEGACY_APP_ROOT does not contain poll.py: {root}")
    sys.path.insert(0, str(root))
    from poll import process_one

    return process_one


def handle_job(job: dict[str, Any]) -> None:
    if job["kind"] != "process_video":
        raise RuntimeError(f"Unsupported job kind: {job['kind']}")
    process_one = load_legacy_processor()
    code = process_one(job["video_id"])
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
