"""Disposable SQLite helpers. Never pointed at the configured personal database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import config
import db
import dbconn


class IsolatedSQLite:
    def __init__(self, tmp: Path) -> None:
        self.tmp = Path(tmp)
        self.db_path = self.tmp / "insights.db"
        self._saved = {
            "DATABASE_URL": config.DATABASE_URL,
            "DB_PATH": config.DB_PATH,
            "DATA_DIR": config.DATA_DIR,
            "PROFILE_PATH": config.PROFILE_PATH,
            "KB_PATH": config.KB_PATH,
            "SCHEMA_READY": db._SCHEMA_READY,
        }

    def __enter__(self) -> "IsolatedSQLite":
        config.DATABASE_URL = ""
        config.DB_PATH = self.db_path
        config.DATA_DIR = self.tmp
        config.PROFILE_PATH = self.tmp / "profile.json"
        config.KB_PATH = self.tmp / "knowledge_base.txt"
        db.DB_PATH = config.DB_PATH
        db.PROFILE_PATH = config.PROFILE_PATH
        db.KB_PATH = config.KB_PATH
        db._SCHEMA_READY = False
        if hasattr(dbconn._local, "conn"):
            dbconn._local.conn = None
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        config.DATABASE_URL = self._saved["DATABASE_URL"]
        config.DB_PATH = self._saved["DB_PATH"]
        config.DATA_DIR = self._saved["DATA_DIR"]
        config.PROFILE_PATH = self._saved["PROFILE_PATH"]
        config.KB_PATH = self._saved["KB_PATH"]
        db.DB_PATH = config.DB_PATH
        db.PROFILE_PATH = config.PROFILE_PATH
        db.KB_PATH = config.KB_PATH
        db._SCHEMA_READY = self._saved["SCHEMA_READY"]
        if hasattr(dbconn._local, "conn"):
            dbconn._local.conn = None


def seed_min_schema(path: Path) -> None:
    """Create a tiny videos/embeddings schema without going through init_db."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE videos (
            video_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            structured_insights TEXT NOT NULL DEFAULT '{}',
            error_message TEXT NOT NULL DEFAULT '',
            playlist_type TEXT NOT NULL DEFAULT 'general',
            playlist_id TEXT NOT NULL DEFAULT '',
            channel_name TEXT NOT NULL DEFAULT '',
            processed_at TEXT NOT NULL DEFAULT '',
            added_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            chunk_title TEXT,
            timestamp_seconds INTEGER,
            embedding BLOB NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE TABLE playlists (playlist_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '')"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()
