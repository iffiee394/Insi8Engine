"""Semantic search across video insights using Gemini embeddings."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
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


def normalize_insight_text(ins: dict) -> str:
    topic = str(ins.get("topic") or ins.get("title") or "").strip()
    content = str(ins.get("content") or "").strip()
    points = ins.get("points") or []
    if not content:
        content = " ".join(str(p).strip() for p in points if str(p).strip())
    return f"{topic}: {content}".strip(": ").strip()


def insights_to_chunks(structured_insights: dict) -> tuple[list[dict[str, Any]], str | None]:
    """Convert structured insights into nonempty deterministic chunks."""
    if not isinstance(structured_insights, dict):
        return [], "malformed_insights"
    insights = structured_insights.get("insights")
    if not insights:
        return [], "no_insights"
    if not isinstance(insights, list):
        return [], "malformed_insights"
    chunks: list[dict[str, Any]] = []
    for ins in insights:
        if not isinstance(ins, dict):
            continue
        text = normalize_insight_text(ins)
        if not text:
            continue
        topic = str(ins.get("topic") or ins.get("title") or "").strip()
        chunks.append(
            {
                "chunk_index": len(chunks),
                "chunk_text": text,
                "chunk_title": topic,
                "timestamp_seconds": ins.get("timestamp_seconds"),
            }
        )
    if not chunks:
        return [], "empty_chunks"
    return chunks, None


def source_hash_for_chunks(chunks: list[dict[str, Any]]) -> str:
    payload = [
        (
            c.get("chunk_title") or "",
            c.get("chunk_text") or "",
            c.get("timestamp_seconds"),
        )
        for c in chunks
    ]
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def validate_vectors(
    vectors: list[list[float]],
    *,
    expected_count: int,
    expected_dim: int,
) -> None:
    if len(vectors) != expected_count:
        raise ValueError(f"vector count {len(vectors)} != {expected_count}")
    for i, vec in enumerate(vectors):
        if len(vec) != expected_dim:
            raise ValueError(f"vector {i} dim {len(vec)} != {expected_dim}")
        if any(not math.isfinite(float(x)) for x in vec):
            raise ValueError(f"vector {i} has non-finite values")
        norm = math.sqrt(sum(float(x) * float(x) for x in vec))
        if norm <= 0:
            raise ValueError(f"vector {i} has zero norm")


@dataclass
class SearchHit:
    source_id: str
    video_id: str
    video_title: str
    channel: str
    chunk_title: str
    chunk_text: str
    timestamp_seconds: int | float | None
    insight_variant: str
    source_kind: str
    generation: int | None
    source_hash: str
    score: float


@dataclass
class SearchResponse:
    status: str
    hits: list[SearchHit] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    retrieval: str = "semantic"


def _hit_from_row(row: dict[str, Any], score: float) -> SearchHit:
    video_id = str(row.get("video_id") or "")
    chunk_index = row.get("chunk_index", 0)
    return SearchHit(
        source_id=f"insight:{video_id}:{chunk_index}",
        video_id=video_id,
        video_title=str(row.get("video_title") or ""),
        channel=str(row.get("channel_name") or ""),
        chunk_title=str(row.get("chunk_title") or ""),
        chunk_text=str(row.get("chunk_text") or ""),
        timestamp_seconds=row.get("timestamp_seconds"),
        insight_variant="auto",
        source_kind="insight",
        generation=row.get("generation"),
        source_hash=str(row.get("source_hash") or ""),
        score=float(score),
    )


def generate_embeddings_for_video(video_id: str, structured_insights: dict) -> list[dict]:
    """Generate all replacement vectors, then atomically replace the auto index."""
    chunks, reason = insights_to_chunks(structured_insights)
    if not chunks:
        logger.info("[search] Skip index for %s (%s)", video_id, reason)
        return []
    if not config.GEMINI_API_KEY:
        return []

    texts = [c["chunk_text"] for c in chunks]
    source_hash = source_hash_for_chunks(chunks)
    try:
        vectors = _embed_texts(texts, task_type=_TASK_DOCUMENT)
        validate_vectors(
            vectors,
            expected_count=len(chunks),
            expected_dim=config.EMBEDDING_OUTPUT_DIM,
        )
        for chunk, emb in zip(chunks, vectors):
            chunk["embedding"] = [float(x) for x in emb]
            chunk["video_id"] = video_id
        db.replace_auto_index(
            video_id,
            chunks,
            model=config.EMBEDDING_MODEL,
            source_hash=source_hash,
            vector_dim=config.EMBEDDING_OUTPUT_DIM,
        )
        logger.info("[search] Stored %d embeddings for %s", len(chunks), video_id)
        return chunks
    except db.IndexConflict as exc:
        logger.warning("[search] %s", exc)
        return []
    except Exception as exc:
        logger.warning("[search] Embedding generation failed: %s", exc)
        return []


def index_saved_auto_insights(video_id: str) -> list[dict]:
    """Index the structured insights already saved on the video row."""
    video = db.get_video(video_id)
    if not video:
        return []
    structured = db.parse_structured_insights(video.get("structured_insights", "{}"))
    return generate_embeddings_for_video(video_id, structured)


def _score_sqlite_rows(
    query_emb: np.ndarray,
    rows: list[dict[str, Any]],
    top_k: int,
) -> list[SearchHit]:
    results: list[SearchHit] = []
    q_norm = np.linalg.norm(query_emb) + 1e-8
    for row in rows:
        try:
            stored_emb = np.array(db.decode_embedding(row["embedding"]), dtype=np.float32)
        except Exception:
            continue
        if stored_emb.size != query_emb.size:
            continue
        if not np.isfinite(stored_emb).all():
            continue
        s_norm = float(np.linalg.norm(stored_emb))
        if s_norm <= 0:
            continue
        similarity = float(np.dot(query_emb, stored_emb) / (q_norm * s_norm))
        results.append(_hit_from_row(row, similarity))
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:top_k]


def _lexical_hits(
    query: str,
    top_k: int,
    *,
    playlist_id: str | None,
    playlist_type: str | None,
    video_id: str | None,
) -> list[SearchHit]:
    rows = db.lexical_search_embeddings(
        query,
        top_k,
        playlist_id=playlist_id,
        playlist_type=playlist_type,
        video_id=video_id,
    )
    hits = []
    q = query.strip().lower()
    for row in rows:
        text = f"{row.get('chunk_title', '')} {row.get('chunk_text', '')}".lower()
        score = 1.0 if q and q in text else 0.2
        hits.append(_hit_from_row(row, score))
    return hits


def search_insights_response(
    query: str,
    top_k: int = 10,
    *,
    playlist_id: str | None = None,
    playlist_type: str | None = None,
    video_id: str | None = None,
) -> SearchResponse:
    """Shared retrieval contract for the Search page and chat."""
    coverage = {
        "playlist_id": playlist_id or "",
        "playlist_type": playlist_type or "",
        "video_id": video_id or "",
        "top_k": top_k,
    }
    if not query.strip():
        return SearchResponse(status="empty", coverage=coverage, warnings=["empty query"])

    if not config.GEMINI_API_KEY:
        hits = _lexical_hits(
            query, top_k,
            playlist_id=playlist_id, playlist_type=playlist_type, video_id=video_id,
        )
        if hits:
            return SearchResponse(
                status="degraded",
                hits=hits,
                coverage=coverage,
                warnings=["Gemini key missing — lexical fallback"],
                retrieval="lexical",
            )
        return SearchResponse(
            status="error",
            coverage=coverage,
            warnings=["Gemini key missing and no lexical matches"],
            retrieval="lexical",
        )

    try:
        vectors = _embed_texts([query.strip()], task_type=_TASK_QUERY)
        if not vectors:
            raise RuntimeError("empty query embedding")
        validate_vectors(
            vectors,
            expected_count=1,
            expected_dim=config.EMBEDDING_OUTPUT_DIM,
        )
        query_emb = np.array(vectors[0], dtype=np.float32)
    except Exception as exc:
        msg = str(exc)
        kind = "quota" if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) else "provider"
        hits = _lexical_hits(
            query, top_k,
            playlist_id=playlist_id, playlist_type=playlist_type, video_id=video_id,
        )
        if hits:
            return SearchResponse(
                status="degraded",
                hits=hits,
                coverage=coverage,
                warnings=[f"{kind} embedding failure — lexical fallback"],
                retrieval="lexical",
            )
        return SearchResponse(
            status="error",
            coverage=coverage,
            warnings=[f"{kind} embedding failure and no lexical matches"],
            retrieval="semantic",
        )

    scoped = db.count_scoped_embeddings(
        playlist_id=playlist_id, playlist_type=playlist_type, video_id=video_id
    )
    coverage["scoped_embeddings"] = scoped
    use_exact = scoped <= 2000

    hits: list[SearchHit] = []
    if use_exact:
        rows = db.get_all_embeddings(
            playlist_id=playlist_id, playlist_type=playlist_type, video_id=video_id
        )
        hits = _score_sqlite_rows(query_emb, rows, top_k)
    else:
        ranked = db.search_embeddings(
            [float(x) for x in query_emb],
            top_k,
            playlist_id=playlist_id,
            playlist_type=playlist_type,
            video_id=video_id,
        )
        if ranked is None:
            rows = db.get_all_embeddings(
                playlist_id=playlist_id, playlist_type=playlist_type, video_id=video_id
            )
            hits = _score_sqlite_rows(query_emb, rows, top_k)
        else:
            hits = [_hit_from_row(h, float(h.get("score") or 0.0)) for h in ranked]

    if hits:
        return SearchResponse(status="ok", hits=hits, coverage=coverage, retrieval="semantic")
    return SearchResponse(status="empty", hits=[], coverage=coverage, retrieval="semantic")


def search_insights(query: str, top_k: int = 10) -> list[dict]:
    """Compatibility wrapper used by older callers."""
    response = search_insights_response(query, top_k)
    return [
        {
            "video_id": h.video_id,
            "chunk_title": h.chunk_title,
            "chunk_text": h.chunk_text,
            "timestamp_seconds": h.timestamp_seconds,
            "score": h.score,
        }
        for h in response.hits
    ]


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
