"""Backend-agnostic database connections.

db.py speaks the sqlite3 dialect: `conn.execute(sql, params)` with `?`
placeholders and rows addressed by column name. This module keeps that surface
intact while allowing Postgres (Supabase) underneath, so switching backends is
a config change rather than a rewrite.

    DATABASE_URL unset -> SQLite file at config.DB_PATH  (local default)
    DATABASE_URL set   -> Postgres via psycopg2

Connections are thread-local: Streamlit reruns and the background poll workers
each get their own, which keeps a single psycopg2 connection from being shared
across threads (it is not thread-safe) while avoiding a fresh TCP+TLS handshake
on every query — that handshake is free on local SQLite but costs ~100-200ms
against a hosted database, and a page render issues several queries.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

import config

_local = threading.local()


def is_postgres() -> bool:
    return bool(config.DATABASE_URL)


def placeholder_to_pg(sql: str) -> str:
    """Rewrite sqlite `?` placeholders as psycopg `%s`, ignoring string literals.

    A bare str.replace would also rewrite any `?` inside a quoted literal, and
    would leave literal `%` (which psycopg treats as the start of a parameter)
    unescaped.
    """
    out: list[str] = []
    in_string = False
    for ch in sql:
        if ch == "'":
            in_string = not in_string
            out.append(ch)
        elif ch == "%":
            # psycopg2 interpolates the whole query, literals included, so every
            # literal percent must be doubled regardless of where it appears.
            out.append("%%")
        elif ch == "?" and not in_string:
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


class _PgConnection:
    """sqlite3.Connection-shaped wrapper over a psycopg2 connection."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def execute(self, sql: str, params: tuple | list = ()) -> Any:
        from psycopg2.extras import RealDictCursor

        cur = self._raw.cursor(cursor_factory=RealDictCursor)
        cur.execute(placeholder_to_pg(sql), tuple(params))
        return cur

    def executemany(self, sql: str, seq: list) -> Any:
        from psycopg2.extras import RealDictCursor

        cur = self._raw.cursor(cursor_factory=RealDictCursor)
        cur.executemany(placeholder_to_pg(sql), [tuple(p) for p in seq])
        return cur

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        # Connections are pooled per thread; closing here would defeat that.
        pass

    def __enter__(self) -> "_PgConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Mirrors sqlite3's context manager: commit on success, roll back on error.
        if exc_type is None:
            self._raw.commit()
        else:
            self._raw.rollback()
        return False


def _new_postgres_connection() -> _PgConnection:
    import psycopg2

    raw = psycopg2.connect(config.DATABASE_URL, connect_timeout=15)
    raw.autocommit = False
    return _PgConnection(raw)


def _new_sqlite_connection() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def connect():
    """Return a live connection for this thread, reconnecting if it dropped."""
    if not is_postgres():
        # SQLite connections are cheap and bound to the creating thread; make a
        # fresh one per call exactly as before.
        return _new_sqlite_connection()

    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1").fetchone()
            return conn
        except Exception:
            try:
                conn._raw.close()
            except Exception:
                pass
            _local.conn = None

    conn = _new_postgres_connection()
    _local.conn = conn
    return conn


def describe() -> str:
    if is_postgres():
        tail = config.DATABASE_URL.rsplit("@", 1)[-1]
        return f"postgres://…@{tail}"
    return f"sqlite://{config.DB_PATH}"
