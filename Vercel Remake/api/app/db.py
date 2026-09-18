from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from psycopg2.extras import RealDictCursor

from .pgconnect import connect_postgres
from .settings import get_settings




DEFAULT_PROFILE: dict[str, Any] = {
    "display_name": "",
    "email": "",
    "about_me": "",
    "interests": "",
    "insight_style": "",
    "known_topics": "",
    "personalize_extractions": True,
}


def _merge_profile(raw: Any) -> dict[str, Any]:
    merged = dict(DEFAULT_PROFILE)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            merged.update(parsed)
    elif isinstance(raw, dict):
        merged.update(raw)
    has_profile_text = any(str(merged.get(key, "")).strip() for key in ("about_me", "interests", "insight_style", "known_topics"))
    merged["personalize_extractions"] = True if not has_profile_text else bool(merged.get("personalize_extractions", True))
    return merged


def _format_profile_sections(profile: dict[str, Any], *, prefix: str = "User") -> str:
    if profile.get("personalize_extractions") is False:
        return ""
    sections: list[str] = []
    if str(profile.get("about_me", "")).strip():
        sections.append(f"{prefix} background: {str(profile.get('about_me', '')).strip()}")
    if str(profile.get("interests", "")).strip():
        sections.append(f"{prefix} interests: {str(profile.get('interests', '')).strip()}")
    if str(profile.get("insight_style", "")).strip():
        sections.append(f"Insight style: {str(profile.get('insight_style', '')).strip()}")
    if str(profile.get("known_topics", "")).strip():
        sections.append("Topics already known (skip unless new angle):\n" + str(profile.get("known_topics", "")).strip())
    return "\n\n".join(sections)


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


def ensure_profile_schema() -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS personal_settings (
                id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL DEFAULT '{}',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


def ensure_worker_schema() -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS worker_heartbeats (
                worker_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'idle',
                current_job_id TEXT NOT NULL DEFAULT '',
                current_video_id TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS worker_heartbeats_updated_idx "
            "ON worker_heartbeats(updated_at DESC)"
        )


def get_profile() -> dict[str, Any]:
    ensure_profile_schema()
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT profile_json FROM personal_settings WHERE id = %s", ("default",))
        row = cur.fetchone()
    if not row:
        return dict(DEFAULT_PROFILE)
    return _merge_profile(row.get("profile_json"))


def save_profile(updates: dict[str, Any]) -> dict[str, Any]:
    current = get_profile()
    for key in DEFAULT_PROFILE:
        if key in updates:
            current[key] = updates[key]
    current["personalize_extractions"] = bool(current.get("personalize_extractions", True))
    payload = json.dumps(current, ensure_ascii=False)
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO personal_settings (id, profile_json, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (id) DO UPDATE SET
                profile_json = EXCLUDED.profile_json,
                updated_at = EXCLUDED.updated_at
            """,
            ("default", payload),
        )
    return current


def _format_playlist_sections(playlist: dict[str, Any] | None) -> str:
    if not playlist:
        return ""

    sections: list[str] = []
    try:
        playlist_profile = json.loads(playlist.get("profile_json") or "{}")
    except json.JSONDecodeError:
        playlist_profile = {}
    if isinstance(playlist_profile, dict):
        playlist_block = _format_profile_sections(playlist_profile, prefix="Playlist focus")
        if playlist_block:
            sections.append(playlist_block)

    playlist_focus = str(playlist.get("extraction_focus") or "").strip()
    if playlist_focus:
        sections.append(f"Playlist extraction focus:\n{playlist_focus}")

    return "\n\n".join(sections)


def _playlist_profile_sections(playlist_id: str) -> tuple[str, dict[str, Any] | None]:
    playlist_id = playlist_id.strip()
    if not playlist_id:
        return "", None

    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT playlist_id, name, description, kind, extraction_focus, profile_json
            FROM playlists
            WHERE playlist_id = %s
            """,
            (playlist_id,),
        )
        row = cur.fetchone()

    if not row:
        return "", None

    playlist = dict(row)
    return _format_playlist_sections(playlist), playlist


def profile_prompt_preview(
    *,
    playlist_id: str = "",
    profile: dict[str, Any] | None = None,
    playlist: dict[str, Any] | None = None,
) -> str:
    sections: list[str] = []
    profile_block = _format_profile_sections(profile if profile is not None else get_profile())
    if profile_block:
        sections.append(profile_block)
    playlist_block = _format_playlist_sections(playlist)
    if not playlist_block and playlist_id:
        playlist_block, _playlist = _playlist_profile_sections(playlist_id)
    if playlist_block:
        sections.append(playlist_block)

    if not sections:
        return ""
    return "USER PROFILE — used to shape agenda, tone, and depth:\n---\n" + "\n\n".join(sections) + "\n---"


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


def get_video_detail(video_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM videos WHERE video_id = %s", (video_id,))
        video_row = cur.fetchone()
        if not video_row:
            return None

        video = dict(video_row)
        cur.execute(
            """
            SELECT * FROM knowledge_jobs
            WHERE video_id = %s
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (video_id,),
        )
        jobs = _rows(cur)

        cur.execute("SELECT profile_json FROM personal_settings WHERE id = %s", ("default",))
        profile_row = cur.fetchone()
        profile = _merge_profile(profile_row.get("profile_json") if profile_row else {})

        playlist = None
        playlist_id = str(video.get("playlist_id") or "").strip()
        if playlist_id:
            cur.execute(
                """
                SELECT playlist_id, name, description, kind, extraction_focus, profile_json
                FROM playlists
                WHERE playlist_id = %s
                """,
                (playlist_id,),
            )
            playlist_row = cur.fetchone()
            playlist = dict(playlist_row) if playlist_row else None

    return {
        "item": video,
        "jobs": jobs,
        "agenda_lens": agenda_lens_for_video(video, profile=profile, playlist=playlist),
    }


def agenda_lens_for_video(
    video: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    playlist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = profile if profile is not None else get_profile()
    profile_sections = _format_profile_sections(profile)
    playlist_id = str(video.get("playlist_id") or "").strip()
    playlist_focus = ""
    if playlist_id and playlist is None:
        _playlist_block, playlist = _playlist_profile_sections(playlist_id)
    if playlist:
        playlist_focus = str(playlist.get("extraction_focus") or "").strip()

    user_agenda = str(video.get("user_agenda") or "").strip()
    auto_agenda = str(video.get("auto_agenda") or "").strip()
    mode = "custom" if user_agenda else "default"

    if mode == "custom":
        agenda_text = user_agenda
        status = "custom agenda will be combined with the saved profile, playlist focus, and transcript during processing"
    elif auto_agenda:
        agenda_text = auto_agenda
        status = "default agenda generated during processing"
    else:
        agenda_text = ""
        status = "default agenda will be generated from profile, playlist focus, and transcript during processing"

    return {
        "mode": mode,
        "status": status,
        "agenda_text": agenda_text,
        "profile_active": bool(profile_sections),
        "profile_has_text": any(str(profile.get(key, "")).strip() for key in ("about_me", "interests", "insight_style", "known_topics")),
        "profile_prompt_preview": profile_prompt_preview(playlist_id=playlist_id, profile=profile, playlist=playlist),
        "playlist_id": playlist_id,
        "playlist_name": (playlist or {}).get("name", "") if playlist else "",
        "playlist_kind": (playlist or {}).get("kind", "") if playlist else str(video.get("playlist_type") or ""),
        "playlist_focus": playlist_focus,
    }


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


def update_playlist(
    playlist_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    kind: str | None = None,
    extraction_focus: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any] | None:
    fields: list[str] = []
    values: list[Any] = []
    updates = {
        "name": name,
        "description": description,
        "kind": kind,
        "extraction_focus": extraction_focus,
        "enabled": None if enabled is None else int(bool(enabled)),
    }
    for key, value in updates.items():
        if value is not None:
            fields.append(f"{key} = %s")
            values.append(value)
    if not fields:
        with connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT playlist_id, name, description, kind, extraction_focus, enabled, created_at
                FROM playlists
                WHERE playlist_id = %s
                """,
                (playlist_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    values.append(playlist_id)
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE playlists
            SET {", ".join(fields)}
            WHERE playlist_id = %s
            RETURNING playlist_id, name, description, kind, extraction_focus, enabled, created_at
            """,
            values,
        )
        row = cur.fetchone()
        return dict(row) if row else None


def record_worker_heartbeat(
    worker_id: str,
    *,
    status: str = "idle",
    current_job_id: str = "",
    current_video_id: str = "",
    note: str = "",
) -> None:
    ensure_worker_schema()
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO worker_heartbeats (
                worker_id, status, current_job_id, current_video_id, note, updated_at
            ) VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (worker_id) DO UPDATE SET
                status = EXCLUDED.status,
                current_job_id = EXCLUDED.current_job_id,
                current_video_id = EXCLUDED.current_video_id,
                note = EXCLUDED.note,
                updated_at = EXCLUDED.updated_at
            """,
            (worker_id, status[:40], current_job_id[:120], current_video_id[:120], note[:500]),
        )


def worker_status() -> dict[str, Any]:
    ensure_worker_schema()
    ensure_job_schema()
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT worker_id, status, current_job_id, current_video_id, note,
                   updated_at,
                   EXTRACT(EPOCH FROM (now() - updated_at))::INTEGER AS seconds_since_seen
            FROM worker_heartbeats
            ORDER BY updated_at DESC
            LIMIT 5
            """
        )
        workers = _rows(cur)
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'queued') AS queued,
                COUNT(*) FILTER (WHERE status = 'running') AS running,
                COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                COUNT(*) FILTER (WHERE status = 'done') AS done
            FROM knowledge_jobs
            """
        )
        counts = dict(cur.fetchone() or {})

    active = [
        worker for worker in workers
        if int(worker.get("seconds_since_seen") or 999999) <= 30
    ]
    return {
        "ok": bool(active),
        "workers": workers,
        "active_workers": len(active),
        "queue": {
            "queued": int(counts.get("queued") or 0),
            "running": int(counts.get("running") or 0),
            "failed": int(counts.get("failed") or 0),
            "done": int(counts.get("done") or 0),
        },
    }


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


def enqueue_job(
    *,
    kind: str,
    video_id: str = "__system__",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ensure_job_schema()
    job_id = str(uuid.uuid4())
    body = json.dumps(payload or {})
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO knowledge_jobs (id, kind, video_id, status, payload)
            VALUES (%s, %s, %s, 'queued', %s::jsonb)
            RETURNING *
            """,
            (job_id, kind, video_id, body),
        )
        return dict(cur.fetchone())


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


def enqueue_playlist_sync(max_process: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"source": "dashboard"}
    if max_process is not None:
        payload["max_process"] = max(0, min(int(max_process), 50))
    return enqueue_job(kind="sync_playlists", video_id="__playlist_sync__", payload=payload)


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
