"""Read-only health report for the personal knowledge system.

This module must not call db.init_db or create tables. It only issues SELECTs
and, when classifying insights, reads text columns — never embedding vectors.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import dbconn
from errors import classify_error

SCHEMA_VERSION_KEY = "knowledge_schema_version"

_FAILURE_BUCKETS = (
    ("private_or_deleted", ("private", "unavailable", "removed", "deleted", "age-restricted")),
    ("no_captions", ("empty transcript", "no transcript", "captions", "no captions")),
    ("quota", ("429", "rate limit", "quota", "resource_exhausted")),
    ("billing", ("credit", "billing", "balance")),
    ("json_parse", ("json", "parse", "decode")),
)


def backend_kind() -> str:
    return "postgres" if dbconn.is_postgres() else "sqlite"


def sanitized_backend_label() -> str:
    if dbconn.is_postgres():
        return "postgres (configured host hidden)"
    return f"sqlite file present={config.DB_PATH.exists()}"


def connect_readonly(*, sqlite_path: Path | None = None):
    """Open an existing database for reads only. Never creates tables or files."""
    if sqlite_path is not None:
        path = Path(sqlite_path)
        if not path.exists():
            raise FileNotFoundError(f"SQLite file not found: {path}")
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    if dbconn.is_postgres():
        return dbconn.connect()

    if not config.DB_PATH.exists():
        raise FileNotFoundError("Configured SQLite database does not exist")
    conn = sqlite3.connect(f"file:{config.DB_PATH.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn, name: str) -> bool:
    if dbconn.is_postgres() and not isinstance(conn, sqlite3.Connection):
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ?",
            (name,),
        ).fetchone()
        return bool(row)
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _classify_failure(message: str) -> str:
    info = classify_error(message)
    title = (info.get("title") or "").lower()
    raw = (message or "").lower()
    blob = f"{title} {raw}"
    for bucket, needles in _FAILURE_BUCKETS:
        if any(n in blob for n in needles):
            return bucket
    return "other"


def _insight_quality(raw: str | None) -> tuple[str, int]:
    """Return (quality, expected_chunk_count). Quality is ok/empty/malformed."""
    if raw is None or not str(raw).strip() or str(raw).strip() in ("{}", "null"):
        return "empty", 0
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return "malformed", 0
    if not isinstance(data, dict):
        return "malformed", 0
    insights = data.get("insights")
    if insights is None:
        return "empty", 0
    if not isinstance(insights, list):
        return "malformed", 0
    n = 0
    for ins in insights:
        if not isinstance(ins, dict):
            continue
        topic = str(ins.get("topic") or ins.get("title") or "").strip()
        content = str(ins.get("content") or "").strip()
        points = ins.get("points") or []
        body = content if content else " ".join(str(p).strip() for p in points if str(p).strip())
        text = f"{topic}: {body}".strip(": ").strip()
        if text:
            n += 1
    if n == 0:
        return "empty", 0
    return "ok", n


def collect_health(conn) -> dict[str, Any]:
    """Aggregate-only health snapshot. Does not read embedding vectors."""
    report: dict[str, Any] = {
        "backend": backend_kind() if not isinstance(conn, sqlite3.Connection) else "sqlite",
        "backend_label": sanitized_backend_label()
        if not isinstance(conn, sqlite3.Connection)
        else "sqlite (explicit path)",
        "schema_version": None,
        "playlists": 0,
        "video_status": {},
        "videos_total": 0,
        "insights": {"ok": 0, "empty": 0, "malformed": 0},
        "index": {
            "embedding_rows": 0,
            "videos_with_embeddings": 0,
            "missing": 0,
            "partial": 0,
            "stale": 0,
            "unverified": 0,
            "ineligible": 0,
            "current": 0,
            "unknown_model": 0,
        },
        "failures": {},
        "failed_videos": [],
        "index_state_present": False,
        "read_only": True,
    }

    if not _table_exists(conn, "videos"):
        report["error"] = "videos table missing — database has no application schema"
        return report

    if _table_exists(conn, "meta"):
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (SCHEMA_VERSION_KEY,)
        ).fetchone()
        if row:
            report["schema_version"] = _row_get(row, "value")

    if _table_exists(conn, "playlists"):
        prow = conn.execute("SELECT COUNT(*) AS n FROM playlists").fetchone()
        report["playlists"] = int(_row_get(prow, "n") or 0)

    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM videos GROUP BY status"
    ).fetchall()
    status_counts = {
        str(_row_get(r, "status") or ""): int(_row_get(r, "n") or 0) for r in status_rows
    }
    report["video_status"] = status_counts
    report["videos_total"] = sum(status_counts.values())

    fail_rows = conn.execute(
        "SELECT video_id, status, error_message FROM videos WHERE status = 'failed'"
    ).fetchall()
    fail_counts: Counter[str] = Counter()
    failed_out: list[dict[str, str]] = []
    for row in fail_rows:
        category = _classify_failure(str(_row_get(row, "error_message") or ""))
        fail_counts[category] += 1
        failed_out.append(
            {
                "video_id": str(_row_get(row, "video_id") or ""),
                "category": category,
            }
        )
    report["failures"] = dict(fail_counts)
    report["failed_videos"] = failed_out

    embed_counts: dict[str, int] = {}
    if _table_exists(conn, "embeddings"):
        erow = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()
        report["index"]["embedding_rows"] = int(_row_get(erow, "n") or 0)
        vrow = conn.execute(
            "SELECT COUNT(DISTINCT video_id) AS n FROM embeddings"
        ).fetchone()
        report["index"]["videos_with_embeddings"] = int(_row_get(vrow, "n") or 0)
        for row in conn.execute(
            "SELECT video_id, COUNT(*) AS n FROM embeddings GROUP BY video_id"
        ).fetchall():
            embed_counts[str(_row_get(row, "video_id"))] = int(_row_get(row, "n") or 0)

    index_state: dict[str, dict[str, Any]] = {}
    if _table_exists(conn, "index_state"):
        report["index_state_present"] = True
        for row in conn.execute(
            "SELECT video_id, variant, source_hash, expected_chunks, stored_chunks, "
            "status, model FROM index_state WHERE variant = 'auto'"
        ).fetchall():
            index_state[str(_row_get(row, "video_id"))] = {
                "source_hash": _row_get(row, "source_hash") or "",
                "expected_chunks": int(_row_get(row, "expected_chunks") or 0),
                "stored_chunks": int(_row_get(row, "stored_chunks") or 0),
                "status": _row_get(row, "status") or "",
                "model": _row_get(row, "model") or "",
            }

    insight_rows = conn.execute(
        "SELECT video_id, status, structured_insights FROM videos"
    ).fetchall()
    for row in insight_rows:
        video_id = str(_row_get(row, "video_id") or "")
        status = str(_row_get(row, "status") or "")
        quality, expected = _insight_quality(_row_get(row, "structured_insights"))
        report["insights"][quality] = report["insights"].get(quality, 0) + 1
        if status != "done":
            continue
        stored = embed_counts.get(video_id, 0)
        state = index_state.get(video_id)
        if quality != "ok":
            report["index"]["ineligible"] += 1
            continue
        if stored == 0:
            report["index"]["missing"] += 1
            continue
        if stored != expected:
            report["index"]["partial"] += 1
            continue
        if state:
            if state.get("status") == "stale" or (
                state.get("source_hash") and state.get("expected_chunks") != stored
            ):
                report["index"]["stale"] += 1
            elif not state.get("model") or state.get("model") == "unknown":
                report["index"]["unknown_model"] += 1
            else:
                report["index"]["current"] += 1
        else:
            report["index"]["unverified"] += 1
            report["index"]["unknown_model"] += 1

    return report


def format_report(report: dict[str, Any]) -> str:
    lines = [
        "Knowledge system health (read-only)",
        f"backend: {report.get('backend_label')}",
        f"schema_version: {report.get('schema_version')}",
        f"playlists: {report.get('playlists')}",
        f"videos_total: {report.get('videos_total')}",
        "video_status:",
    ]
    for key, value in sorted((report.get("video_status") or {}).items()):
        lines.append(f"  {key}: {value}")
    insights = report.get("insights") or {}
    lines.append(
        "insights: "
        f"ok={insights.get('ok', 0)} empty={insights.get('empty', 0)} "
        f"malformed={insights.get('malformed', 0)}"
    )
    idx = report.get("index") or {}
    lines.append(
        "index: "
        f"rows={idx.get('embedding_rows', 0)} "
        f"videos={idx.get('videos_with_embeddings', 0)} "
        f"current={idx.get('current', 0)} "
        f"missing={idx.get('missing', 0)} "
        f"partial={idx.get('partial', 0)} "
        f"stale={idx.get('stale', 0)} "
        f"unverified={idx.get('unverified', 0)} "
        f"ineligible={idx.get('ineligible', 0)} "
        f"unknown_model={idx.get('unknown_model', 0)}"
    )
    lines.append(f"index_state_present: {report.get('index_state_present')}")
    failures = report.get("failures") or {}
    if failures:
        lines.append("failures:")
        for key, value in sorted(failures.items()):
            lines.append(f"  {key}: {value}")
        for item in report.get("failed_videos") or []:
            lines.append(f"  video {item.get('video_id')} -> {item.get('category')}")
    else:
        lines.append("failures: none")
    if report.get("error"):
        lines.append(f"error: {report['error']}")
    lines.append("read_only: true")
    return "\n".join(lines)


def backup_local_sidecar_files(dest_dir: Path) -> dict[str, str]:
    """Copy local profile/KB/SQLite sidecars. Does not dump hosted Postgres."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    mapping = {
        "profile.json": config.PROFILE_PATH,
        "knowledge_base.txt": config.KB_PATH,
        "insights.db": config.DB_PATH,
    }
    for name, src in mapping.items():
        if src.exists() and src.is_file():
            target = dest_dir / name
            shutil.copy2(src, target)
            copied[name] = str(target)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(copied),
        "note": "Local sidecar copy only. Hosted Postgres is not included.",
    }
    (dest_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return copied


def restore_sqlite_file(backup_db: Path, dest_db: Path) -> Path:
    dest_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_db, dest_db)
    return dest_db


def compare_sqlite_counts(left: Path, right: Path) -> dict[str, Any]:
    def counts(path: Path) -> dict[str, int]:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            out = {}
            for table in ("videos", "playlists", "embeddings"):
                try:
                    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
                    out[table] = int(row["n"] if row else 0)
                except sqlite3.Error:
                    out[table] = -1
            return out
        finally:
            conn.close()

    a, b = counts(left), counts(right)
    return {"left": a, "right": b, "match": a == b}


def default_backup_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return config.DATA_DIR / "backups" / stamp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only knowledge-system health report. Never creates tables."
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        help="Read this SQLite file instead of the configured backend",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON (still contains no secrets or vectors)",
    )
    parser.add_argument(
        "--backup-local",
        type=Path,
        nargs="?",
        const=True,
        help="Copy local profile/KB/SQLite into DATA_DIR/backups/<timestamp> or a path",
    )
    args = parser.parse_args(argv)

    sqlite_path = args.sqlite
    conn = None
    try:
        conn = connect_readonly(sqlite_path=sqlite_path)
        report = collect_health(conn)
    except Exception as exc:
        print(f"health failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if conn is not None and isinstance(conn, sqlite3.Connection):
            conn.close()

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(format_report(report))

    if args.backup_local:
        dest = default_backup_dir() if args.backup_local is True else Path(args.backup_local)
        copied = backup_local_sidecar_files(dest)
        print(f"local_backup_files: {len(copied)}")
        print(f"local_backup_dir: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
