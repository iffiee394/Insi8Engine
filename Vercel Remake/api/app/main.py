from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db
from .settings import get_settings
from .youtube import fetch_public_metadata, parse_video_id

settings = get_settings()

app = FastAPI(title="InsightEngine API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class IngestRequest(BaseModel):
    url: str = Field(min_length=1)
    kind: Literal["video", "podcast", "general"] = "video"


class TranscriptRequest(BaseModel):
    transcript: str = Field(min_length=100, max_length=2_000_000)
    enqueue: bool = True


class ProcessRequest(BaseModel):
    reason: str = "manual"


@app.get("/health")
def health() -> dict:
    configured = bool(settings.database_url)
    if configured:
        try:
            db.ensure_job_schema()
        except Exception as exc:
            return {"ok": False, "database": "error", "error": str(exc)[:240]}
    return {
        "ok": configured,
        "database": "configured" if configured else "missing",
        "services": {
            "youtube": bool(settings.youtube_api_key),
            "gemini": bool(settings.gemini_api_key),
            "anthropic": bool(settings.anthropic_api_key),
            "groq": bool(settings.groq_api_key),
            "tavily": bool(settings.tavily_api_key),
        },
    }


@app.get("/videos")
def videos(
    status: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=200),
) -> dict:
    return {"items": db.list_videos(status=status, limit=limit)}


@app.get("/videos/{video_id}")
def video(video_id: str) -> dict:
    item = db.get_video(video_id)
    if not item:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"item": item, "jobs": db.list_jobs(video_id=video_id, limit=10)}


@app.get("/playlists")
def playlists() -> dict:
    return {"items": db.list_playlists()}


@app.get("/jobs")
def jobs(video_id: str | None = None, limit: int = Query(default=50, ge=1, le=100)) -> dict:
    return {"items": db.list_jobs(video_id=video_id, limit=limit)}


@app.get("/jobs/{job_id}")
def job(job_id: str) -> dict:
    item = db.get_job(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"item": item}


@app.post("/ingest")
def ingest(req: IngestRequest) -> dict:
    video_id = parse_video_id(req.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Paste a valid YouTube video URL or video id.")
    meta = fetch_public_metadata(video_id)
    playlist_type = "podcast" if req.kind == "podcast" else "general"
    db.upsert_video_pending(
        video_id=video_id,
        title=meta.title,
        url=meta.url,
        playlist_type=playlist_type,
        channel_name=meta.channel_name,
    )
    job = db.enqueue_process(video_id, {"source": "ingest", "kind": req.kind})
    return {"ok": True, "video": db.get_video(video_id), "job": job}


@app.post("/videos/{video_id}/process")
def process_video(video_id: str, req: ProcessRequest) -> dict:
    if not db.get_video(video_id):
        raise HTTPException(status_code=404, detail="Video not found")
    job = db.enqueue_process(video_id, {"source": req.reason})
    return {"ok": True, "job": job}


@app.post("/videos/{video_id}/transcript")
def save_transcript(video_id: str, req: TranscriptRequest) -> dict:
    if not db.get_video(video_id):
        raise HTTPException(status_code=404, detail="Video not found")
    db.upsert_transcript(video_id, req.transcript.strip())
    job = db.enqueue_process(video_id, {"source": "user_transcript"}) if req.enqueue else None
    return {"ok": True, "video": db.get_video(video_id), "job": job}


@app.get("/search")
def search(q: str = Query(min_length=1), limit: int = Query(default=12, ge=1, le=30)) -> dict:
    return {"items": db.lexical_search(q, limit=limit)}
