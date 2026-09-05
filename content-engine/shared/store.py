"""
SQLite store shared by Part C and Part D.

One file, no server, no subscription. The schema exists to serve three jobs:

  1. the idea queue that feeds both lanes
  2. the approval gates (clinical sign-off, consent) that block publishing
  3. the N.J.A.C. 13:30-6.2 three-year advertisement archive

The archive table is append-only, enforced by SQLite triggers rather than by
convention, because "we always remember to log it" is not a retention policy.
See DECISIONS.md D-07.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from . import config

RETENTION_YEARS = 3


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS ideas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client        TEXT NOT NULL,
    lane          TEXT NOT NULL CHECK (lane IN ('carousel','reel')),
    title         TEXT NOT NULL,
    angle         TEXT,
    source        TEXT,              -- 'outlier' | 'manual' | 'objection' | 'seed'
    source_url    TEXT,
    source_handle TEXT,
    score         REAL DEFAULT 0,    -- outlier multiple, or manual priority
    status        TEXT NOT NULL DEFAULT 'queued',
    payload       TEXT,              -- JSON blob (transcript, metrics, notes)
    created_at    TEXT NOT NULL,
    UNIQUE (client, lane, title)
);

CREATE TABLE IF NOT EXISTS assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client      TEXT NOT NULL,
    idea_id     INTEGER REFERENCES ideas(id),
    lane        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft',
        -- draft -> compliance_passed -> rendered -> approved -> published
        -- any gate failure sets 'blocked'
    template    TEXT,
    caption     TEXT,
    dir_path    TEXT,
    payload     TEXT,               -- JSON: outline / script / shotlist
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (client, slug)
);

CREATE TABLE IF NOT EXISTS claims (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id    INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    slide_no    INTEGER,
    text        TEXT NOT NULL,
    source_url  TEXT,
    source_title TEXT,
    is_clinical INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id    INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    gate        TEXT NOT NULL,      -- 'clinical' | 'consent' | 'compliance'
    approver    TEXT NOT NULL,
    decision    TEXT NOT NULL,      -- 'approved' | 'rejected'
    note        TEXT,
    decided_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consent (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client        TEXT NOT NULL,
    subject_ref   TEXT NOT NULL,    -- internal reference, never a patient name
    signed_date   TEXT NOT NULL,
    channels      TEXT NOT NULL,    -- comma list: instagram,facebook,tiktok,website
    expires_on    TEXT,
    doc_path      TEXT,             -- scan of the signed release
    revoked       INTEGER NOT NULL DEFAULT 0,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE (client, subject_ref)
);

-- Append-only. N.J.A.C. 13:30-6.2 requires copies of advertisements be kept for
-- three years with the date and place of publication.
CREATE TABLE IF NOT EXISTS archive (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client        TEXT NOT NULL,
    asset_id      INTEGER,
    slug          TEXT NOT NULL,
    lane          TEXT NOT NULL,
    platform      TEXT NOT NULL,
    published_at  TEXT NOT NULL,
    retain_until  TEXT NOT NULL,
    caption       TEXT,
    identification TEXT,
    asset_paths   TEXT,             -- JSON list of files as published
    sha256        TEXT,             -- hash of the asset bundle
    claims_json   TEXT,
    approvals_json TEXT,
    created_at    TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS archive_no_update
BEFORE UPDATE ON archive
BEGIN
    SELECT RAISE(ABORT, 'archive is append-only: advertisement records cannot be modified');
END;

CREATE TRIGGER IF NOT EXISTS archive_no_delete
BEFORE DELETE ON archive
WHEN (SELECT COUNT(*) FROM archive WHERE id = OLD.id AND retain_until > date('now')) > 0
BEGIN
    SELECT RAISE(ABORT, 'archive record is inside its 3-year retention window');
END;

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    part        TEXT NOT NULL,
    command     TEXT NOT NULL,
    client      TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT,
    detail      TEXT
);

CREATE INDEX IF NOT EXISTS idx_ideas_client_status ON ideas(client, lane, status);
CREATE INDEX IF NOT EXISTS idx_assets_client_status ON assets(client, status);
CREATE INDEX IF NOT EXISTS idx_archive_client ON archive(client, published_at);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------- ideas


def add_idea(
    conn: sqlite3.Connection,
    *,
    client: str,
    lane: str,
    title: str,
    angle: str = "",
    source: str = "manual",
    source_url: str = "",
    source_handle: str = "",
    score: float = 0.0,
    payload: dict[str, Any] | None = None,
) -> int | None:
    """Insert an idea. Returns the id, or None if it was a duplicate title."""
    try:
        cur = conn.execute(
            """INSERT INTO ideas (client, lane, title, angle, source, source_url,
                                  source_handle, score, status, payload, created_at)
               VALUES (?,?,?,?,?,?,?,?, 'queued', ?, ?)""",
            (
                client,
                lane,
                title.strip(),
                angle,
                source,
                source_url,
                source_handle,
                float(score),
                json.dumps(payload or {}),
                utcnow(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None


def next_idea(conn: sqlite3.Connection, client: str, lane: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT * FROM ideas WHERE client=? AND lane=? AND status='queued'
           ORDER BY score DESC, id ASC LIMIT 1""",
        (client, lane),
    ).fetchone()


def list_ideas(
    conn: sqlite3.Connection, client: str, lane: str | None = None, status: str | None = None
) -> list[sqlite3.Row]:
    q = "SELECT * FROM ideas WHERE client=?"
    args: list[Any] = [client]
    if lane:
        q += " AND lane=?"
        args.append(lane)
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY score DESC, id ASC"
    return conn.execute(q, args).fetchall()


def set_idea_status(conn: sqlite3.Connection, idea_id: int, status: str) -> None:
    conn.execute("UPDATE ideas SET status=? WHERE id=?", (status, idea_id))
    conn.commit()


# ---------------------------------------------------------------- assets


def create_asset(
    conn: sqlite3.Connection,
    *,
    client: str,
    lane: str,
    slug: str,
    idea_id: int | None = None,
    template: str = "",
    caption: str = "",
    dir_path: str = "",
    payload: dict[str, Any] | None = None,
) -> int:
    now = utcnow()
    cur = conn.execute(
        """INSERT INTO assets (client, idea_id, lane, slug, status, template, caption,
                               dir_path, payload, created_at, updated_at)
           VALUES (?,?,?,?, 'draft', ?,?,?,?,?,?)
           ON CONFLICT(client, slug) DO UPDATE SET
             payload=excluded.payload, caption=excluded.caption,
             template=excluded.template, dir_path=excluded.dir_path,
             updated_at=excluded.updated_at""",
        (client, idea_id, lane, slug, template, caption, dir_path,
         json.dumps(payload or {}), now, now),
    )
    conn.commit()
    if cur.lastrowid:
        row = conn.execute("SELECT id FROM assets WHERE client=? AND slug=?", (client, slug)).fetchone()
        return int(row["id"])
    row = conn.execute("SELECT id FROM assets WHERE client=? AND slug=?", (client, slug)).fetchone()
    return int(row["id"])


def set_asset_status(conn: sqlite3.Connection, asset_id: int, status: str) -> None:
    conn.execute(
        "UPDATE assets SET status=?, updated_at=? WHERE id=?", (status, utcnow(), asset_id)
    )
    conn.commit()


def get_asset(conn: sqlite3.Connection, client: str, slug: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM assets WHERE client=? AND slug=?", (client, slug)
    ).fetchone()


def list_assets(conn: sqlite3.Connection, client: str, status: str | None = None) -> list[sqlite3.Row]:
    if status:
        return conn.execute(
            "SELECT * FROM assets WHERE client=? AND status=? ORDER BY id DESC", (client, status)
        ).fetchall()
    return conn.execute(
        "SELECT * FROM assets WHERE client=? ORDER BY id DESC", (client,)
    ).fetchall()


# ---------------------------------------------------------------- claims


def record_claims(conn: sqlite3.Connection, asset_id: int, claims: Iterable[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM claims WHERE asset_id=?", (asset_id,))
    conn.executemany(
        """INSERT INTO claims (asset_id, slide_no, text, source_url, source_title,
                               is_clinical, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        [
            (
                asset_id,
                c.get("slide_no"),
                c.get("text", ""),
                c.get("source_url", ""),
                c.get("source_title", ""),
                1 if c.get("is_clinical", True) else 0,
                utcnow(),
            )
            for c in claims
        ],
    )
    conn.commit()


def get_claims(conn: sqlite3.Connection, asset_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM claims WHERE asset_id=? ORDER BY slide_no", (asset_id,)).fetchall()


# ---------------------------------------------------------------- approvals


def record_approval(
    conn: sqlite3.Connection,
    *,
    asset_id: int,
    gate: str,
    approver: str,
    decision: str,
    note: str = "",
) -> None:
    conn.execute(
        """INSERT INTO approvals (asset_id, gate, approver, decision, note, decided_at)
           VALUES (?,?,?,?,?,?)""",
        (asset_id, gate, approver, decision, note, utcnow()),
    )
    conn.commit()


def get_approvals(conn: sqlite3.Connection, asset_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM approvals WHERE asset_id=? ORDER BY decided_at", (asset_id,)
    ).fetchall()


def has_approval(conn: sqlite3.Connection, asset_id: int, gate: str) -> bool:
    row = conn.execute(
        """SELECT 1 FROM approvals WHERE asset_id=? AND gate=? AND decision='approved'
           ORDER BY decided_at DESC LIMIT 1""",
        (asset_id, gate),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------- consent


def add_consent(
    conn: sqlite3.Connection,
    *,
    client: str,
    subject_ref: str,
    signed_date: str,
    channels: str,
    expires_on: str = "",
    doc_path: str = "",
    notes: str = "",
) -> None:
    conn.execute(
        """INSERT INTO consent (client, subject_ref, signed_date, channels, expires_on,
                                doc_path, revoked, notes, created_at)
           VALUES (?,?,?,?,?,?,0,?,?)
           ON CONFLICT(client, subject_ref) DO UPDATE SET
             signed_date=excluded.signed_date, channels=excluded.channels,
             expires_on=excluded.expires_on, doc_path=excluded.doc_path,
             notes=excluded.notes""",
        (client, subject_ref, signed_date, channels, expires_on, doc_path, notes, utcnow()),
    )
    conn.commit()


def consent_ok(
    conn: sqlite3.Connection, client: str, subject_ref: str, channel: str
) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT * FROM consent WHERE client=? AND subject_ref=?", (client, subject_ref)
    ).fetchone()
    if row is None:
        return False, f"no signed release on file for '{subject_ref}'"
    if row["revoked"]:
        return False, f"release for '{subject_ref}' was revoked"
    channels = [c.strip().lower() for c in (row["channels"] or "").split(",")]
    if channel.lower() not in channels:
        return False, f"release for '{subject_ref}' does not cover {channel} (covers: {channels})"
    if row["expires_on"]:
        try:
            if datetime.fromisoformat(row["expires_on"]).date() < datetime.now().date():
                return False, f"release for '{subject_ref}' expired {row['expires_on']}"
        except ValueError:
            pass
    return True, "ok"


# ---------------------------------------------------------------- archive


def sha256_files(paths: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(Path(x) for x in paths):
        if Path(p).exists():
            h.update(Path(p).read_bytes())
    return h.hexdigest()


def archive_publication(
    conn: sqlite3.Connection,
    *,
    client: str,
    asset_id: int | None,
    slug: str,
    lane: str,
    platform: str,
    caption: str,
    identification: str,
    asset_paths: list[str],
    claims: list[dict[str, Any]] | None = None,
    approvals: list[dict[str, Any]] | None = None,
    published_at: str | None = None,
) -> int:
    """Write the immutable advertisement record. Called on every publish."""
    pub = published_at or utcnow()
    retain_until = (
        datetime.fromisoformat(pub.replace("Z", "+00:00")) + timedelta(days=365 * RETENTION_YEARS)
    ).date().isoformat()
    cur = conn.execute(
        """INSERT INTO archive (client, asset_id, slug, lane, platform, published_at,
                                retain_until, caption, identification, asset_paths,
                                sha256, claims_json, approvals_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            client,
            asset_id,
            slug,
            lane,
            platform,
            pub,
            retain_until,
            caption,
            identification,
            json.dumps(asset_paths),
            sha256_files([Path(p) for p in asset_paths]),
            json.dumps(claims or []),
            json.dumps(approvals or []),
            utcnow(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def list_archive(conn: sqlite3.Connection, client: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM archive WHERE client=? ORDER BY published_at DESC", (client,)
    ).fetchall()


# ---------------------------------------------------------------- runs


def start_run(conn: sqlite3.Connection, part: str, command: str, client: str) -> int:
    cur = conn.execute(
        "INSERT INTO runs (part, command, client, started_at) VALUES (?,?,?,?)",
        (part, command, client, utcnow()),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, status: str, detail: str = "") -> None:
    conn.execute(
        "UPDATE runs SET finished_at=?, status=?, detail=? WHERE id=?",
        (utcnow(), status, detail[:4000], run_id),
    )
    conn.commit()
