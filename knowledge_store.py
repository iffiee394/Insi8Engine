"""Personal settings, collections, saved items, transcripts, and conversations."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import config
import dbconn

SETTINGS_ID = "default"
KIND_INSIGHT = "insight"
KIND_ANSWER = "answer"
KIND_NOTE = "note"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect():
    return dbconn.connect()


def _row(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def parse_profile_json(raw: str | dict | None, fallback: dict | None = None) -> dict:
    """Pure JSON parse used by profile I/O so old file behavior can be tested."""
    base = dict(fallback or {})
    if raw is None or raw == "":
        return base
    if isinstance(raw, dict):
        base.update(raw)
        return base
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return base
    if isinstance(data, dict):
        base.update(data)
    return base


def load_profile_file(path=None) -> dict:
    target = path or config.PROFILE_PATH
    if not target.exists():
        return {}
    try:
        return parse_profile_json(target.read_text(encoding="utf-8"), {})
    except OSError:
        return {}


def get_personal_settings() -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT profile_json, updated_at FROM personal_settings WHERE id = ?",
            (SETTINGS_ID,),
        ).fetchone()
    return _row(row)


def set_personal_settings(profile: dict) -> dict:
    payload = json.dumps(profile, ensure_ascii=False)
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO personal_settings (id, profile_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET profile_json = excluded.profile_json, "
            "updated_at = excluded.updated_at",
            (SETTINGS_ID, payload, now),
        )
        conn.commit()
    return profile


def import_profile_once(*, default_profile: dict) -> dict:
    """Import the local JSON profile only when the database row is missing."""
    existing = None
    try:
        existing = get_personal_settings()
    except Exception:
        existing = None
    if existing and (existing.get("profile_json") or "").strip() not in ("", "{}"):
        return parse_profile_json(existing.get("profile_json"), default_profile)

    file_profile = load_profile_file()
    merged = dict(default_profile)
    merged.update(file_profile)
    if config.KB_PATH.exists():
        known = config.KB_PATH.read_text(encoding="utf-8").strip()
        if known and not merged.get("known_topics"):
            merged["known_topics"] = known
    set_personal_settings(merged)
    return merged


def get_profile(default_profile: dict) -> dict:
    try:
        row = get_personal_settings()
    except Exception:
        row = None
    if row:
        parsed = parse_profile_json(row.get("profile_json"), default_profile)
        if parsed:
            return parsed
    return dict(default_profile)


def list_collections(*, include_archived: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM collections"
    if not include_archived:
        sql += " WHERE archived_at IS NULL"
    sql += " ORDER BY name"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def create_collection(name: str, description: str = "") -> dict[str, Any]:
    item = {
        "id": str(uuid.uuid4()),
        "name": name.strip() or "Untitled collection",
        "description": description,
        "created_at": _now(),
        "updated_at": _now(),
        "archived_at": None,
    }
    with _connect() as conn:
        conn.execute(
            "INSERT INTO collections (id, name, description, created_at, updated_at, archived_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                item["id"],
                item["name"],
                item["description"],
                item["created_at"],
                item["updated_at"],
                item["archived_at"],
            ),
        )
        conn.commit()
    return item


def rename_collection(collection_id: str, name: str, description: str | None = None) -> None:
    with _connect() as conn:
        if description is None:
            conn.execute(
                "UPDATE collections SET name = ?, updated_at = ? WHERE id = ?",
                (name.strip(), _now(), collection_id),
            )
        else:
            conn.execute(
                "UPDATE collections SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                (name.strip(), description, _now(), collection_id),
            )
        conn.commit()


def archive_collection(collection_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE collections SET archived_at = ?, updated_at = ? WHERE id = ?",
            (_now(), _now(), collection_id),
        )
        conn.commit()


def insight_save_key(video_id: str, body: str) -> str:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]
    return f"insight:{video_id}:{digest}"


def answer_save_key(answer_id: str) -> str:
    return f"answer:{answer_id}"


def note_save_key(note_id: str | None = None) -> str:
    return f"note:{note_id or uuid.uuid4()}"


def save_item(
    *,
    kind: str,
    title: str,
    body_snapshot: str,
    sources: list[dict] | None = None,
    personal_note: str = "",
    save_key: str | None = None,
    collection_ids: list[str] | None = None,
) -> dict[str, Any]:
    if kind == KIND_INSIGHT:
        key = save_key or insight_save_key(
            (sources or [{}])[0].get("video_id", "unknown"),
            body_snapshot,
        )
    elif kind == KIND_ANSWER:
        key = save_key or answer_save_key(str(uuid.uuid4()))
    else:
        key = save_key or note_save_key()

    now = _now()
    sources_json = json.dumps(sources or [], ensure_ascii=False)
    with _connect() as conn:
        existing = conn.execute(
            "SELECT * FROM saved_items WHERE save_key = ?", (key,)
        ).fetchone()
        if existing:
            item_id = existing["id"]
            conn.execute(
                """
                UPDATE saved_items SET
                    title = ?, body_snapshot = ?, sources_json = ?,
                    personal_note = COALESCE(NULLIF(?, ''), personal_note),
                    updated_at = ?
                WHERE id = ?
                """,
                (title, body_snapshot, sources_json, personal_note, now, item_id),
            )
        else:
            item_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO saved_items (
                    id, save_key, kind, title, body_snapshot, sources_json,
                    personal_note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    key,
                    kind,
                    title,
                    body_snapshot,
                    sources_json,
                    personal_note,
                    now,
                    now,
                ),
            )
        for collection_id in collection_ids or []:
            conn.execute(
                """
                INSERT INTO collection_items (collection_id, saved_item_id, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(collection_id, saved_item_id) DO NOTHING
                """,
                (collection_id, item_id, now),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM saved_items WHERE id = ?", (item_id,)).fetchone()
    return dict(row)


def update_saved_item_note(item_id: str, personal_note: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE saved_items SET personal_note = ?, updated_at = ? WHERE id = ?",
            (personal_note, _now(), item_id),
        )
        conn.commit()


def add_item_to_collection(item_id: str, collection_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO collection_items (collection_id, saved_item_id, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(collection_id, saved_item_id) DO NOTHING
            """,
            (collection_id, item_id, _now()),
        )
        conn.commit()


def remove_item_from_collection(item_id: str, collection_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM collection_items WHERE collection_id = ? AND saved_item_id = ?",
            (collection_id, item_id),
        )
        conn.commit()


def get_saved_item(item_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM saved_items WHERE id = ?", (item_id,)).fetchone()
    return _row(row)


def list_saved_items(*, collection_id: str | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        if collection_id:
            rows = conn.execute(
                """
                SELECT s.* FROM saved_items s
                JOIN collection_items c ON c.saved_item_id = s.id
                WHERE c.collection_id = ?
                ORDER BY s.updated_at DESC
                """,
                (collection_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM saved_items ORDER BY updated_at DESC"
            ).fetchall()
        items = [dict(r) for r in rows]
        for item in items:
            memberships = conn.execute(
                "SELECT collection_id FROM collection_items WHERE saved_item_id = ?",
                (item["id"],),
            ).fetchall()
            item["collection_ids"] = [m["collection_id"] for m in memberships]
    return items


def get_transcript(video_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM video_transcripts WHERE video_id = ?", (video_id,)
        ).fetchone()
    return _row(row)


def upsert_transcript(
    video_id: str,
    *,
    plain_text: str,
    timed_segments: list[dict] | None = None,
    source: str = "",
    language: str = "",
    timing_quality: str = "unknown",
    schema_version: int = 1,
) -> dict[str, Any]:
    segments = timed_segments or []
    content_hash = hashlib.sha256(plain_text.encode("utf-8")).hexdigest()
    payload = {
        "video_id": video_id,
        "plain_text": plain_text,
        "timed_segments_json": json.dumps(segments, ensure_ascii=False),
        "source": source,
        "language": language,
        "content_hash": content_hash,
        "fetched_at": _now(),
        "timing_quality": timing_quality,
        "schema_version": schema_version,
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO video_transcripts (
                video_id, plain_text, timed_segments_json, source, language,
                content_hash, fetched_at, timing_quality, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                plain_text = excluded.plain_text,
                timed_segments_json = excluded.timed_segments_json,
                source = excluded.source,
                language = excluded.language,
                content_hash = excluded.content_hash,
                fetched_at = excluded.fetched_at,
                timing_quality = excluded.timing_quality,
                schema_version = excluded.schema_version
            """,
            (
                payload["video_id"],
                payload["plain_text"],
                payload["timed_segments_json"],
                payload["source"],
                payload["language"],
                payload["content_hash"],
                payload["fetched_at"],
                payload["timing_quality"],
                payload["schema_version"],
            ),
        )
        conn.commit()
    return payload


def list_transcript_chunks(video_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM transcript_chunks WHERE video_id = ? ORDER BY chunk_index",
            (video_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def create_conversation(*, title: str, scope_type: str, scope_id: str = "") -> dict[str, Any]:
    item = {
        "id": str(uuid.uuid4()),
        "title": title[:120] or "Conversation",
        "scope_type": scope_type,
        "scope_id": scope_id,
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO conversations (id, title, scope_type, scope_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["title"],
                item["scope_type"],
                item["scope_id"],
                item["created_at"],
                item["updated_at"],
            ),
        )
        conn.commit()
    return item


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return _row(row)


def list_conversations(*, scope_type: str | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        if scope_type:
            rows = conn.execute(
                "SELECT * FROM conversations WHERE scope_type = ? ORDER BY updated_at DESC",
                (scope_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_message_by_request(request_id: str, role: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM chat_messages WHERE request_id = ? AND role = ?",
            (request_id, role),
        ).fetchone()
    return _row(row)


def insert_chat_message(
    *,
    conversation_id: str,
    request_id: str,
    role: str,
    content: str = "",
    sources: list[dict] | None = None,
    status: str = "pending",
    usage: dict | None = None,
) -> dict[str, Any]:
    existing = get_message_by_request(request_id, role)
    if existing:
        return existing
    item = {
        "id": str(uuid.uuid4()),
        "conversation_id": conversation_id,
        "request_id": request_id,
        "role": role,
        "content": content,
        "sources_json": json.dumps(sources or [], ensure_ascii=False),
        "status": status,
        "created_at": _now(),
        "usage_json": json.dumps(usage or {}, ensure_ascii=False),
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (
                id, conversation_id, request_id, role, content, sources_json,
                status, created_at, usage_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["conversation_id"],
                item["request_id"],
                item["role"],
                item["content"],
                item["sources_json"],
                item["status"],
                item["created_at"],
                item["usage_json"],
            ),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (_now(), conversation_id),
        )
        conn.commit()
    return item


def update_chat_message(
    message_id: str,
    *,
    content: str | None = None,
    sources: list[dict] | None = None,
    status: str | None = None,
    usage: dict | None = None,
) -> None:
    fields: list[str] = []
    params: list[Any] = []
    if content is not None:
        fields.append("content = ?")
        params.append(content)
    if sources is not None:
        fields.append("sources_json = ?")
        params.append(json.dumps(sources, ensure_ascii=False))
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if usage is not None:
        fields.append("usage_json = ?")
        params.append(json.dumps(usage, ensure_ascii=False))
    if not fields:
        return
    params.append(message_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE chat_messages SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()


def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        ).fetchall()
        return [dict(r) for r in rows]
