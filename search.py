"""Semantic search across video insights using Gemini embeddings."""

from __future__ import annotations

import json
import re
import struct
import time
from typing import Any

import numpy as np

import config
import db
from logutil import get_logger

logger = get_logger(__name__)

_TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
_TASK_QUERY = "RETRIEVAL_QUERY"


def _embed_config(task_type: str) -> dict[str, Any]:
    cfg: dict[str, Any] = {"task_type": task_type}
    if config.EMBEDDING_OUTPUT_DIM > 0:
        cfg["output_dimensionality"] = config.EMBEDDING_OUTPUT_DIM
    return cfg


def _values_from_response(response: Any) -> list[list[float]]:
    embeddings = getattr(response, "embeddings", None) or []
    out: list[list[float]] = []
    for item in embeddings:
        values = getattr(item, "values", None)
        if values is not None:
            out.append(list(values))
    return out


def _retry_delay_seconds(exc: Exception) -> float | None:
    msg = str(exc)
    if "429" not in msg and "RESOURCE_EXHAUSTED" not in msg:
        return None
    match = re.search(r"retry in ([\d.]+)s", msg, re.IGNORECASE)
    if match:
        return min(float(match.group(1)) + 1.0, 90.0)
    return 30.0


def _embed_once(client: Any, texts: list[str] | str, embed_cfg: dict[str, Any]) -> list[list[float]]:
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            response = client.models.embed_content(
                model=config.EMBEDDING_MODEL,
                contents=texts,
                config=embed_cfg,
            )
            return _values_from_response(response)
        except Exception as exc:
            last_exc = exc
            delay = _retry_delay_seconds(exc)
            if delay is None or attempt == 4:
                raise
            logger.warning("[search] Embed rate-limited, sleeping %.1fs", delay)
            time.sleep(delay)
    raise last_exc or RuntimeError("Embedding failed")


def _embed_texts(texts: list[str], *, task_type: str = _TASK_DOCUMENT) -> list[list[float]]:
    if not config.GEMINI_API_KEY or not texts:
        return []
    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    embed_cfg = _embed_config(task_type)

    try:
        out = _embed_once(client, texts, embed_cfg)
        if len(out) == len(texts):
            return out
        logger.warning(
            "[search] Batch embedding count mismatch (%s vs %s) — retrying one-by-one",
            len(out),
            len(texts),
        )
    except Exception as exc:
        logger.warning("[search] Batch embed failed (%s) — retrying one-by-one", str(exc)[:160])

    out = []
    for text in texts:
        values = _embed_once(client, text, embed_cfg)
        if not values:
            raise RuntimeError("Empty embedding response")
        out.append(values[0])
    return out


def generate_embeddings_for_video(video_id: str, structured_insights: dict) -> list[dict]:
    """Generate and store embeddings for each insight chunk (non-fatal)."""
    if not config.GEMINI_API_KEY:
        return []

    insights = structured_insights.get("insights", [])
    if not insights:
        return []

    db.delete_embeddings(video_id)
    chunks: list[dict[str, Any]] = []
    for i, ins in enumerate(insights):
        topic = ins.get("topic") or ins.get("title") or ""
        points = ins.get("points") or []
        content = ins.get("content") or ""
        body = content if content else " ".join(str(p) for p in points)
        text = f"{topic}: {body}".strip(": ")
        chunks.append({
            "video_id": video_id,
            "chunk_index": i,
            "chunk_text": text,
            "chunk_title": topic,
            "timestamp_seconds": ins.get("timestamp_seconds"),
        })

    texts = [c["chunk_text"] for c in chunks]
    try:
        vectors = _embed_texts(texts, task_type=_TASK_DOCUMENT)
        if len(vectors) != len(chunks):
            logger.warning("[search] Embedding count mismatch for %s", video_id)
            return []
        for chunk, emb in zip(chunks, vectors):
            # db.store_embeddings serialises this per backend (packed floats on
            # SQLite, a pgvector literal on Postgres).
            chunk["embedding"] = list(emb)
        db.store_embeddings(video_id, chunks)
        logger.info("[search] Stored %d embeddings for %s", len(chunks), video_id)
        return chunks
    except Exception as exc:
        logger.warning("[search] Embedding generation failed: %s", exc)
        return []


def search_insights(query: str, top_k: int = 10) -> list[dict]:
    """Search across all video insights. Returns ranked results."""
    if not config.GEMINI_API_KEY or not query.strip():
        return []

    try:
        vectors = _embed_texts([query.strip()], task_type=_TASK_QUERY)
        if not vectors:
            return []
        query_emb = np.array(vectors[0], dtype=np.float32)
    except Exception as exc:
        logger.warning("[search] Query embedding failed: %s", exc)
        return []

    # Postgres/pgvector ranks with an HNSW index server-side; SQLite falls
    # through to scoring every row here.
    hits = db.search_embeddings([float(x) for x in query_emb], top_k)
    if hits is not None:
        return [
            {
                "video_id": h["video_id"],
                "chunk_title": h.get("chunk_title", ""),
                "chunk_text": h.get("chunk_text", ""),
                "timestamp_seconds": h.get("timestamp_seconds"),
                "score": float(h.get("score") or 0.0),
            }
            for h in hits
        ]

    all_rows = db.get_all_embeddings()
    if not all_rows:
        return []

    results: list[dict] = []
    q_norm = np.linalg.norm(query_emb) + 1e-8
    for row in all_rows:
        stored_emb = np.array(db.decode_embedding(row["embedding"]), dtype=np.float32)
        if stored_emb.size != query_emb.size:
            continue
        s_norm = np.linalg.norm(stored_emb) + 1e-8
        similarity = float(np.dot(query_emb, stored_emb) / (q_norm * s_norm))
        results.append({
            "video_id": row["video_id"],
            "chunk_title": row.get("chunk_title", ""),
            "chunk_text": row.get("chunk_text", ""),
            "timestamp_seconds": row.get("timestamp_seconds"),
            "score": similarity,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def reindex_all_embeddings(*, only_missing: bool = False) -> dict[str, int]:
    """Rebuild embeddings for done videos. Safe to re-run."""
    db.init_db()
    videos = db.list_videos(status=db.STATUS_DONE)
    already: set[str] = set()
    if only_missing:
        already = {row["video_id"] for row in db.get_all_embeddings()}
    ok = skip = fail = chunks = 0
    for video in videos:
        if video["video_id"] in already:
            skip += 1
            continue
        try:
            structured = json.loads(video.get("structured_insights") or "{}")
        except json.JSONDecodeError:
            skip += 1
            continue
        if not structured.get("insights"):
            skip += 1
            continue
        stored = generate_embeddings_for_video(video["video_id"], structured)
        if stored:
            ok += 1
            chunks += len(stored)
            time.sleep(max(2.0, len(stored) * 0.65))
        else:
            fail += 1
    logger.info(
        "[search] Reindex finished: %d videos, %d chunks, skip=%d fail=%d",
        ok,
        chunks,
        skip,
        fail,
    )
    return {"videos": ok, "chunks": chunks, "skip": skip, "fail": fail}


if __name__ == "__main__":
    db.init_db()
    print("model:", config.EMBEDDING_MODEL, "dim:", config.EMBEDDING_OUTPUT_DIM)
    stats = reindex_all_embeddings(only_missing=True)
    print(stats)
    sample = search_insights("remote jobs and AI agents")
    print("sample hits:", len(sample))
    for hit in sample[:3]:
        print(f"  {hit['score']:.3f}  {hit['chunk_title'][:80]}")
