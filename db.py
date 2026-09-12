"""SQLite storage for video insights."""

from __future__ import annotations

import json
import sqlite3
import struct
from datetime import datetime, timezone
from typing import Any

import config
import dbconn

def _db_path():
    return config.DB_PATH


def _kb_path():
    return config.KB_PATH


def _profile_path():
    return config.PROFILE_PATH


# Compatibility aliases — tests may redirect config.DB_PATH.
DB_PATH = config.DB_PATH
KB_PATH = config.KB_PATH
PROFILE_PATH = config.PROFILE_PATH

PLAYLIST_GENERAL = "general"
PLAYLIST_PODCAST = "podcast"

STATUS_PENDING = "pending"
STATUS_AWAITING_AGENDA = "awaiting_agenda"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_BATCH_QUEUED = "batch_queued"

DEFAULT_PROFILE = {
    "about_me": "",
    "interests": "",
    "insight_style": "",
    "known_topics": "",
}

DEFAULT_PLAYLIST_PROFILE = {
    "about_me": "",
    "interests": "",
    "insight_style": "",
    "known_topics": "",
}


def _connect():
    """SQLite locally, Postgres when DATABASE_URL is set (see dbconn)."""
    return dbconn.connect()


def _ensure_columns(conn) -> None:
    if dbconn.is_postgres():
        rows = conn.execute(
            "SELECT column_name AS name FROM information_schema.columns "
            "WHERE table_name = 'videos'"
        ).fetchall()
    else:
        rows = conn.execute("PRAGMA table_info(videos)").fetchall()
    existing = {row["name"] for row in rows}
    migrations = {
        "playlist_type": f"ALTER TABLE videos ADD COLUMN playlist_type TEXT NOT NULL DEFAULT '{PLAYLIST_GENERAL}'",
        "user_agenda": "ALTER TABLE videos ADD COLUMN user_agenda TEXT NOT NULL DEFAULT ''",
        "research_data": "ALTER TABLE videos ADD COLUMN research_data TEXT NOT NULL DEFAULT ''",
        "auto_agenda": "ALTER TABLE videos ADD COLUMN auto_agenda TEXT NOT NULL DEFAULT ''",
        "manual_summary": "ALTER TABLE videos ADD COLUMN manual_summary TEXT NOT NULL DEFAULT ''",
        "manual_key_points": "ALTER TABLE videos ADD COLUMN manual_key_points TEXT NOT NULL DEFAULT '[]'",
        "playlist_id": "ALTER TABLE videos ADD COLUMN playlist_id TEXT NOT NULL DEFAULT ''",
        "structured_insights": "ALTER TABLE videos ADD COLUMN structured_insights TEXT NOT NULL DEFAULT '{}'",
        "usage_data": "ALTER TABLE videos ADD COLUMN usage_data TEXT NOT NULL DEFAULT '{}'",
        "channel_name": "ALTER TABLE videos ADD COLUMN channel_name TEXT NOT NULL DEFAULT ''",
    }
    for column, sql in migrations.items():
        if column not in existing:
            conn.execute(sql)


def _migrate_knowledge_base_to_profile() -> None:
    """Legacy file import. Durable import is knowledge_store.import_profile_once."""
    if _profile_path().exists():
        return
    known = ""
    if _kb_path().exists():
        known = _kb_path().read_text(encoding="utf-8").strip()
    if known:
        profile = dict(DEFAULT_PROFILE)
        profile["known_topics"] = known
        _profile_path().parent.mkdir(parents=True, exist_ok=True)
        _profile_path().write_text(
            json.dumps(profile, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


_SCHEMA_READY = False


def init_db(*, force: bool = False) -> None:
    """Create/patch the schema. Runs once per process unless forced.

    Every statement here is IF NOT EXISTS, so repeat calls were harmless on a
    local SQLite file. Against hosted Postgres the same calls cost ~1.5s of
    round-trips, and the queue-tick fragment invokes this every 3 seconds via
    is_worker_running() — so the guard matters.
    """
    global _SCHEMA_READY
    if _SCHEMA_READY and not force:
        return
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                summary TEXT NOT NULL DEFAULT '',
                key_points TEXT NOT NULL DEFAULT '[]',
                transcript_source TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                added_at TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT '',
                playlist_type TEXT NOT NULL DEFAULT 'general',
                user_agenda TEXT NOT NULL DEFAULT '',
                research_data TEXT NOT NULL DEFAULT '',
                auto_agenda TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        _ensure_columns(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS playlists (
                playlist_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'general',
                profile_json TEXT NOT NULL DEFAULT '{}',
                extraction_focus TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        if dbconn.is_postgres():
            # pgvector turns similarity search into an indexed query instead of
            # pulling every row over the wire to score in Python.
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            auto_pk = "BIGSERIAL PRIMARY KEY"
            blob_type = f"vector({config.EMBEDDING_OUTPUT_DIM})"
        else:
            auto_pk = "INTEGER PRIMARY KEY AUTOINCREMENT"
            blob_type = "BLOB"
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS embeddings (
                id {auto_pk},
                video_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                chunk_title TEXT,
                timestamp_seconds INTEGER,
                embedding {blob_type} NOT NULL,
                FOREIGN KEY (video_id) REFERENCES videos(video_id),
                UNIQUE(video_id, chunk_index)
            )
            """
        )
        if dbconn.is_postgres():
            # HNSW + cosine matches how search.py ranks results.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS embeddings_vec_idx "
                "ON embeddings USING hnsw (embedding vector_cosine_ops)"
            )
        from migrations import run_migrations

        run_migrations(conn)
        conn.commit()

    _migrate_env_playlists()
    _migrate_knowledge_base_to_profile()
    try:
        import knowledge_store

        knowledge_store.import_profile_once(default_profile=DEFAULT_PROFILE)
    except Exception:
        pass

    _SCHEMA_READY = True


def get_profile() -> dict:
    """Load the durable profile; fall back to the local JSON file."""
    try:
        import knowledge_store

        row = knowledge_store.get_personal_settings()
        if row:
            parsed = knowledge_store.parse_profile_json(
                row.get("profile_json"), DEFAULT_PROFILE
            )
            if parsed:
                return parsed
    except Exception:
        pass
    path = _profile_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return dict(DEFAULT_PROFILE)
    return dict(DEFAULT_PROFILE)


def set_profile(profile: dict) -> None:
    """Save the profile to the database. The original JSON file is left intact."""
    merged = dict(DEFAULT_PROFILE)
    merged.update(profile)
    import knowledge_store

    knowledge_store.set_personal_settings(merged)


def get_profile_prompt(*, playlist_id: str | None = None) -> str:
    """Format global + optional playlist profile into an LLM instruction block."""
    sections = []
    global_block = _format_profile_sections(get_profile())
    if global_block:
        sections.append(global_block)

    if playlist_id:
        pl = get_playlist(playlist_id)
        if pl:
            try:
                pl_profile = json.loads(pl.get("profile_json") or "{}")
            except json.JSONDecodeError:
                pl_profile = {}
            pl_block = _format_profile_sections(pl_profile, prefix="Playlist focus")
            if pl_block:
                sections.append(pl_block)
            focus = (pl.get("extraction_focus") or "").strip()
            if focus:
                sections.append(f"Playlist extraction focus:\n{focus}")

    if not sections:
        return ""
    return (
        "USER PROFILE — use this to shape your extraction, tone, and depth:\n---\n"
        + "\n\n".join(sections)
        + "\n---"
    )


def _format_profile_sections(profile: dict, *, prefix: str = "User") -> str:
    sections = []
    if profile.get("about_me", "").strip():
        sections.append(f"{prefix} background: {profile['about_me'].strip()}")
    if profile.get("interests", "").strip():
        sections.append(f"{prefix} interests: {profile['interests'].strip()}")
    if profile.get("insight_style", "").strip():
        sections.append(f"Insight style: {profile['insight_style'].strip()}")
    if profile.get("known_topics", "").strip():
        sections.append(
            "Topics already known (skip unless new angle):\n"
            f"{profile['known_topics'].strip()}"
        )
    return "\n\n".join(sections)



def list_playlists(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    with _connect() as conn:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM playlists WHERE enabled = 1 ORDER BY name"
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM playlists ORDER BY name").fetchall()
        return [dict(row) for row in rows]


def get_playlist(playlist_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM playlists WHERE playlist_id = ?", (playlist_id,)
        ).fetchone()
        return dict(row) if row else None


def upsert_playlist(
    playlist_id: str,
    *,
    name: str = "",
    description: str = "",
    kind: str = PLAYLIST_GENERAL,
    profile_json: dict | None = None,
    extraction_focus: str = "",
    enabled: bool = True,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    profile_str = json.dumps(profile_json or DEFAULT_PLAYLIST_PROFILE, ensure_ascii=False)
    with _connect() as conn:
        existing = conn.execute(
            "SELECT playlist_id FROM playlists WHERE playlist_id = ?", (playlist_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE playlists SET
                    name = COALESCE(NULLIF(?, ''), name),
                    description = COALESCE(NULLIF(?, ''), description),
                    kind = COALESCE(NULLIF(?, ''), kind),
                    profile_json = COALESCE(NULLIF(?, ''), profile_json),
                    extraction_focus = COALESCE(NULLIF(?, ''), extraction_focus),
                    enabled = ?
                WHERE playlist_id = ?
                """,
                (
                    name,
                    description,
                    kind,
                    profile_str if profile_json is not None else "",
                    extraction_focus,
                    1 if enabled else 0,
                    playlist_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO playlists (
                    playlist_id, name, description, kind, profile_json,
                    extraction_focus, enabled, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    playlist_id,
                    name or playlist_id,
                    description,
                    kind,
                    profile_str,
                    extraction_focus,
                    1 if enabled else 0,
                    now,
                ),
            )
        conn.commit()


def delete_playlist(playlist_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM playlists WHERE playlist_id = ?", (playlist_id,))
        conn.commit()


def _migrate_env_playlists() -> None:
    """Seed playlists table from .env on first run."""
    existing = list_playlists()
    if existing:
        return
    general = config.PLAYLIST_ID
    podcast = config.PODCASTS_PLAYLIST_ID
    if general:
        upsert_playlist(
            general,
            name="General",
            kind=PLAYLIST_GENERAL,
            description="General YouTube playlist",
        )
    if podcast:
        upsert_playlist(
            podcast,
            name="Podcast",
            kind=PLAYLIST_PODCAST,
            description="Podcast / long-form playlist",
        )


def parse_structured_insights(raw: str) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def get_knowledge_base() -> str:
    profile = get_profile()
    if profile.get("known_topics", "").strip():
        return profile["known_topics"].strip()
    path = _kb_path()
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def set_knowledge_base(text: str) -> None:
    profile = get_profile()
    profile["known_topics"] = text.strip()
    set_profile(profile)


def set_meta(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def get_meta(key: str, default: str = "") -> str:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def get_video(video_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        return dict(row) if row else None


def should_auto_process(video: dict[str, Any] | None) -> bool:
    if not video:
        return True
    # Only auto-process pending videos — failed videos need manual Retry
    return video["status"] == STATUS_PENDING


def upsert_video(
    video_id: str,
    *,
    title: str = "",
    url: str = "",
    status: str | None = None,
    summary: str = "",
    key_points: list[str] | None = None,
    transcript_source: str = "",
    error_message: str = "",
    playlist_type: str | None = None,
    user_agenda: str | None = None,
    research_data: str | None = None,
    auto_agenda: str | None = None,
    manual_summary: str | None = None,
    manual_key_points: list[str] | None = None,
    playlist_id: str | None = None,
    structured_insights: str | None = None,
    usage_data: str | None = None,
    channel_name: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    points_json = json.dumps(key_points or [], ensure_ascii=False)
    manual_points_json = (
        json.dumps(manual_key_points or [], ensure_ascii=False)
        if manual_key_points is not None
        else None
    )

    with _connect() as conn:
        existing = conn.execute(
            "SELECT * FROM videos WHERE video_id = ?", (video_id,)
        ).fetchone()

        if existing:
            existing = dict(existing)
            new_status = status if status is not None else existing["status"]
            new_type = playlist_type if playlist_type else existing["playlist_type"]
            new_agenda = user_agenda if user_agenda is not None else existing["user_agenda"]
            new_summary = summary if summary else existing["summary"]
            new_points = points_json if key_points is not None else existing["key_points"]
            new_research = research_data if research_data is not None else existing["research_data"]
            new_auto_agenda = auto_agenda if auto_agenda is not None else existing["auto_agenda"]
            new_manual_summary = (
                manual_summary if manual_summary is not None else existing.get("manual_summary", "")
            )
            new_manual_points = (
                manual_points_json
                if manual_key_points is not None
                else existing.get("manual_key_points", "[]")
            )
            new_playlist_id = (
                playlist_id if playlist_id is not None else existing.get("playlist_id", "")
            )
            new_structured = (
                structured_insights
                if structured_insights is not None
                else existing.get("structured_insights", "{}")
            )
            new_usage = (
                usage_data if usage_data is not None else existing.get("usage_data", "{}")
            )
            new_channel = (
                channel_name if channel_name is not None else existing.get("channel_name", "")
            )
            new_error = error_message if error_message != "" or status == STATUS_FAILED else existing["error_message"]
            if status == STATUS_PROCESSING:
                new_error = ""
            conn.execute(
                """
                UPDATE videos SET
                    title = COALESCE(NULLIF(?, ''), title),
                    url = COALESCE(NULLIF(?, ''), url),
                    status = ?,
                    summary = ?,
                    key_points = ?,
                    transcript_source = COALESCE(NULLIF(?, ''), transcript_source),
                    error_message = ?,
                    playlist_type = ?,
                    user_agenda = ?,
                    research_data = ?,
                    auto_agenda = ?,
                    manual_summary = ?,
                    manual_key_points = ?,
                    playlist_id = ?,
                    structured_insights = ?,
                    usage_data = ?,
                    channel_name = ?,
                    processed_at = CASE WHEN ? IN ('done', 'failed') THEN ? ELSE processed_at END
                WHERE video_id = ?
                """,
                (
                    title,
                    url,
                    new_status,
                    new_summary,
                    new_points,
                    transcript_source,
                    new_error,
                    new_type,
                    new_agenda,
                    new_research,
                    new_auto_agenda,
                    new_manual_summary,
                    new_manual_points,
                    new_playlist_id,
                    new_structured,
                    new_usage,
                    new_channel,
                    new_status,
                    now,
                    video_id,
                ),
            )
        else:
            ptype = playlist_type or PLAYLIST_GENERAL
            agenda = user_agenda or ""
            initial_status = status or STATUS_PENDING

            conn.execute(
                """
                INSERT INTO videos (
                    video_id, title, url, status, summary, key_points,
                    transcript_source, error_message, added_at, processed_at,
                    playlist_type, user_agenda, research_data, auto_agenda,
                    manual_summary, manual_key_points, playlist_id, structured_insights,
                    usage_data, channel_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    video_id,
                    title,
                    url,
                    initial_status,
                    summary,
                    points_json,
                    transcript_source,
                    error_message,
                    now,
                    now if initial_status in (STATUS_DONE, STATUS_FAILED) else "",
                    ptype,
                    agenda,
                    research_data or "",
                    auto_agenda or "",
                    (manual_summary if manual_summary is not None else ""),
                    (manual_points_json if manual_key_points is not None else "[]"),
                    playlist_id or "",
                    structured_insights or "{}",
                    usage_data or "{}",
                    channel_name or "",
                ),
            )
        conn.commit()


# Everything the library/queue rows render from. The excluded columns
# (structured_insights, research_data, key_points, usage_data, summary,
# transcript-ish blobs) are ~3MB across the library and are only needed once a
# single video is opened.
LIGHT_VIDEO_COLUMNS = (
    "video_id, title, url, status, channel_name, playlist_type, playlist_id, "
    "added_at, processed_at, error_message, transcript_source, user_agenda"
)


def list_videos(
    playlist_type: str | None = None,
    *,
    status: str | None = None,
    light: bool = False,
) -> list[dict[str, Any]]:
    """List videos. `light=True` omits the large JSON columns."""
    with _connect() as conn:
        query = f"SELECT {LIGHT_VIDEO_COLUMNS} FROM videos" if light else "SELECT * FROM videos"
        params: list[str] = []
        clauses = []
        if playlist_type:
            clauses.append("playlist_type = ?")
            params.append(playlist_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY added_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def parse_key_points(raw: str) -> list[str]:
    try:
        points = json.loads(raw or "[]")
        return points if isinstance(points, list) else []
    except json.JSONDecodeError:
        return []


def delete_embeddings(video_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM embeddings WHERE video_id = ?", (video_id,))
        conn.commit()


def encode_embedding(values: Any) -> Any:
    """Serialise one embedding for the active backend.

    Callers hand over a plain list of floats. SQLite keeps the packed-float
    BLOB the existing rows already use; Postgres gets a pgvector literal.
    """
    if isinstance(values, (bytes, bytearray, memoryview)):
        # Already packed (legacy caller / SQLite round-trip).
        if not dbconn.is_postgres():
            return values
        raw = bytes(values)
        values = list(struct.unpack(f"{len(raw) // 4}f", raw))
    floats = [float(v) for v in values]
    if dbconn.is_postgres():
        return "[" + ",".join(repr(f) for f in floats) + "]"
    return struct.pack(f"{len(floats)}f", *floats)


def decode_embedding(stored: Any) -> list[float]:
    """Inverse of encode_embedding, for the in-Python scoring path."""
    if isinstance(stored, str):
        return [float(x) for x in stored.strip("[]").split(",") if x.strip()]
    raw = bytes(stored)
    return list(struct.unpack(f"{len(raw) // 4}f", raw))


def _embedding_scope_sql(
    *,
    playlist_id: str | None = None,
    playlist_type: str | None = None,
    video_id: str | None = None,
) -> tuple[str, list[Any]]:
    clauses = ["1=1"]
    params: list[Any] = []
    if video_id:
        clauses.append("e.video_id = ?")
        params.append(video_id)
    if playlist_id:
        clauses.append("v.playlist_id = ?")
        params.append(playlist_id)
    if playlist_type:
        clauses.append("v.playlist_type = ?")
        params.append(playlist_type)
    return " AND ".join(clauses), params


def count_scoped_embeddings(
    *,
    playlist_id: str | None = None,
    playlist_type: str | None = None,
    video_id: str | None = None,
) -> int:
    where, params = _embedding_scope_sql(
        playlist_id=playlist_id, playlist_type=playlist_type, video_id=video_id
    )
    with _connect() as conn:
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM embeddings e
            JOIN videos v ON v.video_id = e.video_id
            WHERE {where}
            """,
            params,
        ).fetchone()
        return int(row["n"] if row else 0)


def search_embeddings(
    query_vector: list[float],
    top_k: int = 10,
    *,
    playlist_id: str | None = None,
    playlist_type: str | None = None,
    video_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """Rank chunks by cosine similarity inside the database.

    Postgres only — returns None on SQLite so the caller keeps its numpy path.
    Scope filters are applied before LIMIT.
    """
    if not dbconn.is_postgres():
        return None
    literal = encode_embedding(query_vector)
    where, params = _embedding_scope_sql(
        playlist_id=playlist_id, playlist_type=playlist_type, video_id=video_id
    )
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT e.video_id, e.chunk_index, e.chunk_text, e.chunk_title,
                   e.timestamp_seconds, v.title AS video_title, v.channel_name,
                   v.playlist_id, v.playlist_type,
                   1 - (e.embedding <=> ?::vector) AS score
            FROM embeddings e
            JOIN videos v ON v.video_id = e.video_id
            WHERE {where}
            ORDER BY e.embedding <=> ?::vector
            LIMIT ?
            """,
            [literal, *params, literal, top_k],
        ).fetchall()
        return [dict(row) for row in rows]


def lexical_search_embeddings(
    query: str,
    top_k: int = 10,
    *,
    playlist_id: str | None = None,
    playlist_type: str | None = None,
    video_id: str | None = None,
) -> list[dict[str, Any]]:
    """Parameterized substring search over saved insight chunk text."""
    needle = f"%{query.strip()}%"
    where, params = _embedding_scope_sql(
        playlist_id=playlist_id, playlist_type=playlist_type, video_id=video_id
    )
    sql = f"""
        SELECT e.video_id, e.chunk_index, e.chunk_text, e.chunk_title,
               e.timestamp_seconds, v.title AS video_title, v.channel_name,
               v.playlist_id, v.playlist_type
        FROM embeddings e
        JOIN videos v ON v.video_id = e.video_id
        WHERE {where}
          AND (e.chunk_text LIKE ? OR e.chunk_title LIKE ?)
        LIMIT ?
    """
    with _connect() as conn:
        rows = conn.execute(sql, [*params, needle, needle, top_k]).fetchall()
        return [dict(row) for row in rows]


def store_embeddings(video_id: str, chunks: list[dict]) -> None:
    """Compatibility wrapper — atomic replace of the auto index."""
    replace_auto_index(
        video_id,
        chunks,
        model=chunks[0].get("model", "") if chunks else "",
        source_hash=chunks[0].get("source_hash", "") if chunks else "",
        vector_dim=0,
    )


class IndexConflict(RuntimeError):
    """A newer index generation already exists for this video."""


def get_index_state(video_id: str, variant: str = "auto") -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM index_state WHERE video_id = ? AND variant = ?",
            (video_id, variant),
        ).fetchone()
        return dict(row) if row else None


def record_index_error(video_id: str, error: str, variant: str = "auto") -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT generation FROM index_state WHERE video_id = ? AND variant = ?",
            (video_id, variant),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE index_state SET last_error = ?, status = CASE "
                "WHEN status = 'current' THEN status ELSE 'error' END "
                "WHERE video_id = ? AND variant = ?",
                (error[:500], video_id, variant),
            )
        else:
            conn.execute(
                """
                INSERT INTO index_state (
                    video_id, variant, model, vector_dim, source_hash,
                    expected_chunks, stored_chunks, status, last_success_at,
                    last_error, generation
                ) VALUES (?, ?, '', 0, '', 0, 0, 'error', '', ?, 0)
                """,
                (video_id, variant, error[:500]),
            )
        conn.commit()


def replace_auto_index(
    video_id: str,
    chunks: list[dict],
    *,
    model: str,
    source_hash: str,
    vector_dim: int,
    expected_generation: int | None = None,
) -> int:
    """Delete + insert auto embeddings and index_state in one transaction."""
    if not chunks:
        raise ValueError("replace_auto_index requires a complete chunk list")
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        if dbconn.is_postgres():
            conn.execute(
                "SELECT video_id FROM videos WHERE video_id = ? FOR UPDATE",
                (video_id,),
            )
        state = conn.execute(
            "SELECT generation, source_hash FROM index_state "
            "WHERE video_id = ? AND variant = 'auto'",
            (video_id,),
        ).fetchone()
        current_gen = int(state["generation"]) if state else 0
        if expected_generation is not None and current_gen != expected_generation:
            raise IndexConflict(
                f"stale promotion rejected for {video_id}: "
                f"expected {expected_generation}, have {current_gen}"
            )
        new_gen = current_gen + 1
        conn.execute("DELETE FROM embeddings WHERE video_id = ?", (video_id,))
        for chunk in chunks:
            conn.execute(
                """
                INSERT INTO embeddings
                    (video_id, chunk_index, chunk_text, chunk_title,
                     timestamp_seconds, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    video_id,
                    chunk["chunk_index"],
                    chunk["chunk_text"],
                    chunk.get("chunk_title", ""),
                    chunk.get("timestamp_seconds"),
                    encode_embedding(chunk["embedding"]),
                ),
            )
        conn.execute(
            """
            INSERT INTO index_state (
                video_id, variant, model, vector_dim, source_hash,
                expected_chunks, stored_chunks, status, last_success_at,
                last_error, generation
            ) VALUES (?, 'auto', ?, ?, ?, ?, ?, 'current', ?, '', ?)
            ON CONFLICT(video_id, variant) DO UPDATE SET
                model = excluded.model,
                vector_dim = excluded.vector_dim,
                source_hash = excluded.source_hash,
                expected_chunks = excluded.expected_chunks,
                stored_chunks = excluded.stored_chunks,
                status = excluded.status,
                last_success_at = excluded.last_success_at,
                last_error = '',
                generation = excluded.generation
            """,
            (
                video_id,
                model,
                vector_dim,
                source_hash,
                len(chunks),
                len(chunks),
                now,
                new_gen,
            ),
        )
        conn.commit()
    return new_gen


def get_all_embeddings(
    *,
    playlist_id: str | None = None,
    playlist_type: str | None = None,
    video_id: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _embedding_scope_sql(
        playlist_id=playlist_id, playlist_type=playlist_type, video_id=video_id
    )
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT e.video_id, e.chunk_index, e.chunk_text, e.chunk_title,
                   e.timestamp_seconds, e.embedding, v.title AS video_title,
                   v.channel_name, v.playlist_id, v.playlist_type
            FROM embeddings e
            JOIN videos v ON v.video_id = e.video_id
            WHERE {where}
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]
