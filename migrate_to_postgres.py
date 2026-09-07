"""One-way copy of the local SQLite library into Postgres (Supabase).

Reads the SQLite file at config.DB_PATH directly and writes through db.py's
normal connection layer, which points at Postgres whenever DATABASE_URL is set.

    # .env or environment
    DATABASE_URL=postgresql://postgres.xxx:PASSWORD@...pooler.supabase.com:5432/postgres
    python migrate_to_postgres.py

Safe to re-run: every row is upserted on its primary key, so a repeat run
refreshes the target instead of duplicating it.
"""

from __future__ import annotations

import sqlite3
import sys

import config
import db
import dbconn

TABLES = {
    "videos": "video_id",
    "playlists": "playlist_id",
    "meta": "key",
}


def _sqlite_rows(table: str) -> list[dict]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _upsert(conn, table: str, key: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    written = 0
    for row in rows:
        cols = list(row.keys())
        collist = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != key)
        sql = (
            f"INSERT INTO {table} ({collist}) VALUES ({marks}) "
            f"ON CONFLICT ({key}) DO UPDATE SET {updates}"
            if updates
            else f"INSERT INTO {table} ({collist}) VALUES ({marks}) ON CONFLICT ({key}) DO NOTHING"
        )
        conn.execute(sql, tuple(row[c] for c in cols))
        written += 1
    return written


def _copy_embeddings(conn) -> int:
    rows = _sqlite_rows("embeddings")
    if not rows:
        return 0
    # id is a fresh BIGSERIAL on the target; (video_id, chunk_index) is the
    # real identity, so drop the source id and let Postgres assign its own.
    written = 0
    for row in rows:
        row.pop("id", None)
        cols = list(row.keys())
        collist = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}" for c in cols if c not in ("video_id", "chunk_index")
        )
        # SQLite stores packed floats; Postgres wants a pgvector literal.
        values = tuple(
            db.encode_embedding(row[c]) if c == "embedding" else row[c] for c in cols
        )
        conn.execute(
            f"INSERT INTO embeddings ({collist}) VALUES ({marks}) "
            f"ON CONFLICT (video_id, chunk_index) DO UPDATE SET {updates}",
            values,
        )
        written += 1
    return written


def main() -> int:
    if not dbconn.is_postgres():
        print("DATABASE_URL is not set — nothing to migrate into.", file=sys.stderr)
        print("Set it in .env, then re-run.", file=sys.stderr)
        return 1
    if not config.DB_PATH.exists():
        print(f"No local SQLite database at {config.DB_PATH}", file=sys.stderr)
        return 1

    print(f"source: sqlite://{config.DB_PATH}")
    print(f"target: {dbconn.describe()}\n")

    print("Creating schema on the target…")
    db.init_db()

    conn = dbconn.connect()
    total = 0
    for table, key in TABLES.items():
        rows = _sqlite_rows(table)
        n = _upsert(conn, table, key, rows)
        conn.commit()
        print(f"  {table:<10} {n:>5} rows")
        total += n

    n = _copy_embeddings(conn)
    conn.commit()
    print(f"  {'embeddings':<10} {n:>5} rows")
    total += n

    print("\nVerifying target counts…")
    for table in list(TABLES) + ["embeddings"]:
        got = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        print(f"  {table:<10} {got:>5}")

    print(f"\nMigrated {total} rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
