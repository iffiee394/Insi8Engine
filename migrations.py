"""Versioned additive schema migrations for the personal knowledge system.

Each version runs in its own connection/transaction. A failed version does not
record a newer schema version. Safe to run twice. Never invoked by the health
command or the three-second queue tick.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Callable

import dbconn

SCHEMA_VERSION_KEY = "knowledge_schema_version"

MigrationFn = Callable[[object], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_schema_version(conn) -> int:
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (SCHEMA_VERSION_KEY,)
        ).fetchone()
    except Exception:
        return 0
    if not row:
        return 0
    try:
        return int(row["value"])
    except (KeyError, TypeError, ValueError):
        return 0


def _set_schema_version(conn, version: int) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SCHEMA_VERSION_KEY, str(version)),
    )


def _migrate_1_personal_knowledge(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS personal_settings (
            id TEXT PRIMARY KEY,
            profile_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collections (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_items (
            id TEXT PRIMARY KEY,
            save_key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            body_snapshot TEXT NOT NULL DEFAULT '',
            sources_json TEXT NOT NULL DEFAULT '[]',
            personal_note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS collection_items (
            collection_id TEXT NOT NULL,
            saved_item_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (collection_id, saved_item_id),
            FOREIGN KEY (collection_id) REFERENCES collections(id),
            FOREIGN KEY (saved_item_id) REFERENCES saved_items(id)
        )
        """
    )


def _migrate_2_index_state(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS index_state (
            video_id TEXT NOT NULL,
            variant TEXT NOT NULL DEFAULT 'auto',
            model TEXT NOT NULL DEFAULT '',
            vector_dim INTEGER NOT NULL DEFAULT 0,
            source_hash TEXT NOT NULL DEFAULT '',
            expected_chunks INTEGER NOT NULL DEFAULT 0,
            stored_chunks INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'unknown',
            last_success_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            generation INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (video_id, variant)
        )
        """
    )
    columns = _existing_columns(conn, "embeddings")
    extras = {
        "insight_variant": "ALTER TABLE embeddings ADD COLUMN insight_variant TEXT NOT NULL DEFAULT 'auto'",
        "generation": "ALTER TABLE embeddings ADD COLUMN generation INTEGER NOT NULL DEFAULT 0",
        "source_hash": "ALTER TABLE embeddings ADD COLUMN source_hash TEXT NOT NULL DEFAULT ''",
        "model": "ALTER TABLE embeddings ADD COLUMN model TEXT NOT NULL DEFAULT ''",
    }
    for name, sql in extras.items():
        if name not in columns:
            conn.execute(sql)


def _uses_sqlite(conn) -> bool:
    return isinstance(conn, sqlite3.Connection)


def _migrate_3_transcripts(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS video_transcripts (
            video_id TEXT PRIMARY KEY,
            plain_text TEXT NOT NULL DEFAULT '',
            timed_segments_json TEXT NOT NULL DEFAULT '[]',
            source TEXT NOT NULL DEFAULT '',
            language TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            fetched_at TEXT NOT NULL,
            timing_quality TEXT NOT NULL DEFAULT 'unknown',
            schema_version INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    if not _uses_sqlite(conn) and dbconn.is_postgres():
        try:
            import config as _config

            blob_type = f"vector({_config.EMBEDDING_OUTPUT_DIM})"
        except Exception:
            blob_type = "TEXT"
        auto_pk = "BIGSERIAL PRIMARY KEY"
    else:
        blob_type = "BLOB"
        auto_pk = "INTEGER PRIMARY KEY AUTOINCREMENT"
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS transcript_chunks (
            id {auto_pk},
            video_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            start_offset INTEGER NOT NULL DEFAULT 0,
            end_offset INTEGER NOT NULL DEFAULT 0,
            start_seconds REAL,
            end_seconds REAL,
            embedding {blob_type},
            generation INTEGER NOT NULL DEFAULT 0,
            source_hash TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            UNIQUE(video_id, chunk_index)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transcript_index_state (
            video_id TEXT PRIMARY KEY,
            model TEXT NOT NULL DEFAULT '',
            vector_dim INTEGER NOT NULL DEFAULT 0,
            source_hash TEXT NOT NULL DEFAULT '',
            expected_chunks INTEGER NOT NULL DEFAULT 0,
            stored_chunks INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'unknown',
            last_success_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            generation INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def _migrate_4_conversations(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            sources_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'ok',
            created_at TEXT NOT NULL,
            usage_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(request_id, role),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
        """
    )


def _existing_columns(conn, table: str) -> set[str]:
    if _uses_sqlite(conn):
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row["name"] for row in rows}
    rows = conn.execute(
        "SELECT column_name AS name FROM information_schema.columns "
        "WHERE table_name = ?",
        (table,),
    ).fetchall()
    return {row["name"] for row in rows}


MIGRATIONS: list[tuple[int, str, MigrationFn]] = [
    (1, "personal_knowledge", _migrate_1_personal_knowledge),
    (2, "index_state", _migrate_2_index_state),
    (3, "transcripts", _migrate_3_transcripts),
    (4, "conversations", _migrate_4_conversations),
]

LATEST_SCHEMA_VERSION = MIGRATIONS[-1][0]


def run_migrations(conn) -> int:
    """Apply pending migrations on an open connection. Caller commits."""
    version = current_schema_version(conn)
    applied = version
    for number, _name, fn in MIGRATIONS:
        if number <= version:
            continue
        fn(conn)
        _set_schema_version(conn, number)
        applied = number
    return applied


def run_pending() -> int:
    """Apply each pending version in its own transaction."""
    import db

    db.init_db()
    final = 0
    for number, _name, fn in MIGRATIONS:
        with dbconn.connect() as conn:
            current = current_schema_version(conn)
            if number <= current:
                final = current
                continue
            fn(conn)
            _set_schema_version(conn, number)
            final = number
    return final
