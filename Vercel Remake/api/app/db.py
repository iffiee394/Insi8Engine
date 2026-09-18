from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from psycopg2.extras import RealDictCursor

from .pgconnect import connect_postgres
from .settings import get_settings


class DatabaseNotConfigured(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[Any]:
    url = get_settings().database_url
    if not url:
        raise DatabaseNotConfigured("DATABASE_URL is not configured.")
    conn = connect_postgres(url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _rows(cur: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in cur.fetchall()]


def ensure_job_schema() -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL DEFAULT 'process_video',
                video_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                locked_at TIMESTAMPTZ,
                locked_by TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS knowledge_jobs_status_created_idx "
            "ON knowledge_jobs(status, created_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS knowledge_jobs_video_idx "
            "ON knowledge_jobs(video_id, created_at DESC)"
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS knowledge_jobs_one_active_process_per_video_idx "
            "ON knowledge_jobs(video_id, kind) "
            "WHERE status IN ('queued', 'running') AND kind = 'process_video'"
        )


def list_videos(status: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    with connect() as conn:
        cur = conn.cursor()
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = %s"
            params.append(status)
        cur.execute(
            f"""
            SELECT video_id, title, url, status, channel_name, playlist_type,
                   playlist_id, added_at, processed_at, error_message,
                   transcript_source, user_agenda
            FROM videos
            {where}
            ORDER BY added_at DESC
            LIMIT %s
            """,
            [*params, limit],
        )
        return _rows(cur)


def get_video(video_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM videos WHERE video_id = %s", (video_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_playlists() -> list[dict[str, Any]]:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT playlist_id, name, description, kind, extraction_focus, enabled, created_at
            FROM playlists
            ORDER BY name
            """
        )
        return _rows(cur)


def list_jobs(video_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    ensure_job_schema()
    limit = max(1, min(limit, 100))
    with connect() as conn:
        cur = conn.cursor()
        if video_id:
            cur.execute(
                """
                SELECT * FROM knowledge_jobs
                WHERE video_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (video_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM knowledge_jobs
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
        return _rows(cur)


def get_job(job_id: str) -> dict[str, Any] | None:
    ensure_job_schema()
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM knowledge_jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def enqueue_process(video_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_job_schema()
    job_id = str(uuid.uuid4())
    body = json.dumps(payload or {})
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO knowledge_jobs (id, kind, video_id, status, payload)
            VALUES (%s, 'process_video', %s, 'queued', %s::jsonb)
            ON CONFLICT (video_id, kind)
            WHERE status IN ('queued', 'running') AND kind = 'process_video'
            DO UPDATE SET
                payload = CASE
                    WHEN knowledge_jobs.status = 'queued' THEN EXCLUDED.payload
                    ELSE knowledge_jobs.payload
                END,
                updated_at = now()
            RETURNING *
            """,
            (job_id, video_id, body),
        )
        return dict(cur.fetchone())


def upsert_video_pending(
    *,
    video_id: str,
    title: str,
    url: str,
    playlist_type: str,
    playlist_id: str = "",
    channel_name: str = "",
    user_agenda: str = "",
) -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO videos (
                video_id, title, url, status, summary, key_points,
                transcript_source, error_message, added_at, processed_at,
                playlist_type, user_agenda, research_data, auto_agenda,
                manual_summary, manual_key_points, playlist_id, structured_insights,
                usage_data, channel_name
            ) VALUES (
                %s, %s, %s, 'pending', '', '[]', '', '', %s, '',
                %s, %s, '', '', '', '[]', %s, '{}', '{}', %s
            )
            ON CONFLICT (video_id) DO UPDATE SET
                title = COALESCE(NULLIF(EXCLUDED.title, ''), videos.title),
                url = COALESCE(NULLIF(EXCLUDED.url, ''), videos.url),
                playlist_type = EXCLUDED.playlist_type,
                playlist_id = EXCLUDED.playlist_id,
                channel_name = COALESCE(NULLIF(EXCLUDED.channel_name, ''), videos.channel_name),
                user_agenda = CASE
                    WHEN EXCLUDED.user_agenda <> '' THEN EXCLUDED.user_agenda
                    ELSE videos.user_agenda
                END,
                status = CASE
                    WHEN EXCLUDED.user_agenda <> '' THEN 'pending'
                    WHEN videos.status = 'done' THEN videos.status
                    ELSE 'pending'
                END,
                error_message = CASE
                    WHEN videos.status = 'done' THEN videos.error_message
                    ELSE ''
                END
            """,
            (video_id, title, url, utcnow(), playlist_type, user_agenda.strip(), playlist_id, channel_name),
        )


def update_video_agenda(video_id: str, user_agenda: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE videos
            SET user_agenda = %s,
                status = 'pending',
                error_message = ''
            WHERE video_id = %s
            RETURNING *
            """,
            (user_agenda.strip(), video_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def upsert_transcript(video_id: str, transcript: str) -> None:
    now = utcnow()
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO video_transcripts (
                video_id, plain_text, timed_segments_json, source,
                timing_quality, created_at, updated_at
            ) VALUES (%s, %s, '[]', 'user_transcript', 'unknown', %s, %s)
            ON CONFLICT (video_id) DO UPDATE SET
                plain_text = EXCLUDED.plain_text,
                timed_segments_json = '[]',
                source = 'user_transcript',
                timing_quality = 'unknown',
                updated_at = EXCLUDED.updated_at
            """,
            (video_id, transcript, now, now),
        )
        cur.execute(
            """
            UPDATE videos
            SET transcript_source = 'user_transcript',
                status = CASE WHEN status = 'done' THEN status ELSE 'pending' END,
                error_message = ''
            WHERE video_id = %s
            """,
            (video_id,),
        )


def lexical_search(query: str, limit: int = 12) -> list[dict[str, Any]]:
    needle = f"%{query.strip()}%"
    if not query.strip():
        return []
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT video_id, title, status, channel_name, summary, added_at, processed_at
            FROM videos
            WHERE title ILIKE %s OR summary ILIKE %s OR key_points ILIKE %s
            ORDER BY processed_at DESC NULLS LAST, added_at DESC
            LIMIT %s
            """,
            (needle, needle, needle, max(1, min(limit, 30))),
        )
        return _rows(cur)
