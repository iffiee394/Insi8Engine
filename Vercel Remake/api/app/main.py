from __future__ import annotations


from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db
from .runtime_settings import provider_status, save_provider_keys
from .settings import get_settings
from .youtube import fetch_playlist_info, fetch_public_metadata, parse_playlist_id, parse_video_id

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
    agenda_mode: Literal["default", "custom"] = "default"
    agenda: str = ""
    playlist_id: str = ""


class TranscriptRequest(BaseModel):
    transcript: str = Field(min_length=100, max_length=2_000_000)
    enqueue: bool = True


class ProcessRequest(BaseModel):
    reason: str = "manual"
    agenda_mode: Literal["default", "custom"] = "default"
    agenda: str = ""


class PlaylistSyncRequest(BaseModel):
    max_process: int | None = Field(default=None, ge=0, le=500)


class AutomationRequest(BaseModel):
    sync_every_hours: float = Field(ge=0, le=168)


class PlaylistUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    kind: Literal["general", "podcast"] | None = None
    extraction_focus: str | None = None
    enabled: bool | None = None
    queue_paused: bool | None = None


class PlaylistCreateRequest(BaseModel):
    url: str
    name: str = ""
    kind: Literal["general", "podcast"] = "general"
    extraction_focus: str = ""
    process_now: int | None = Field(default=None, ge=0, le=500)


class ProviderKeysRequest(BaseModel):
    youtube: str | None = None
    gemini: str | None = None
    anthropic: str | None = None
    groq: str | None = None
    tavily: str | None = None


class ProfileRequest(BaseModel):
    display_name: str = ""
    email: str = ""
    about_me: str = ""
    interests: str = ""
    insight_style: str = ""
    known_topics: str = ""
    personalize_extractions: bool = True


class StarterSetupRequest(BaseModel):
    overwrite: bool = False


@app.get("/health")
def health() -> dict:
    configured = bool(settings.database_url)
    if configured:
        try:
            db.ensure_job_schema()
            db.ensure_worker_schema()
        except Exception as exc:
            return {"ok": False, "database": "error", "error": str(exc)[:240]}
    return {
        "ok": configured,
        "database": "configured" if configured else "missing",
        "services": provider_status(),
    }


@app.get("/settings/profile")
def get_profile_settings() -> dict:
    return {"profile": db.get_profile(), "prompt_preview": db.profile_prompt_preview()}


@app.post("/settings/profile")
def update_profile_settings(req: ProfileRequest) -> dict:
    profile = db.save_profile(req.model_dump())
    return {"ok": True, "profile": profile, "prompt_preview": db.profile_prompt_preview()}


@app.post("/settings/starter-setup")
def apply_starter_setup(req: StarterSetupRequest) -> dict:
    result = db.apply_starter_setup(overwrite=req.overwrite)
    return {"ok": True, **result}


@app.get("/settings/providers")
def get_provider_settings() -> dict:
    return {"services": provider_status()}


@app.post("/settings/providers")
async def update_provider_settings(request: Request) -> dict:
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Send provider keys as a JSON object or .env block.")
    status = save_provider_keys(payload)
    get_settings.cache_clear()
    return {"ok": True, "services": status}


@app.get("/videos")
def videos(
    status: str | None = Query(default=None),
    limit: int = Query(default=80, ge=1, le=200),
) -> dict:
    return {"items": db.list_videos(status=status, limit=limit)}


@app.get("/videos/{video_id}")
def video(video_id: str) -> dict:
    detail = db.get_video_detail(video_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Video not found")
    return detail


@app.get("/playlists")
def playlists() -> dict:
    return {"items": db.list_playlists()}


@app.post("/playlists")
def create_playlist(req: PlaylistCreateRequest) -> dict:
    playlist_id = parse_playlist_id(req.url)
    if not playlist_id:
        raise HTTPException(
            status_code=400,
            detail="That isn't a YouTube playlist link. Open the playlist on YouTube and copy the address — it contains list=PL…",
        )
    existing = next((p for p in db.list_playlists() if p["playlist_id"] == playlist_id), None)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"This playlist is already added as “{existing['name'] or playlist_id}”. Edit it in the list above.",
        )
    api_key = get_settings().youtube_api_key
    title, count = "", None
    if api_key:
        try:
            info = fetch_playlist_info(playlist_id, api_key)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Couldn't reach YouTube to check the playlist: {exc}") from exc
        if not info:
            raise HTTPException(
                status_code=400,
                detail="YouTube can't see this playlist. Set its visibility to Public or Unlisted — private playlists can't be read.",
            )
        title, count = info.title, info.item_count
    item = db.create_playlist(
        playlist_id,
        name=req.name.strip() or title or playlist_id,
        description="",
        kind=req.kind,
        extraction_focus=req.extraction_focus.strip(),
    )
    job = db.enqueue_playlist_sync(req.process_now)
    return {"ok": True, "item": item, "video_count": count, "job": job}


@app.patch("/playlists/{playlist_id}")
def update_playlist(playlist_id: str, req: PlaylistUpdateRequest) -> dict:
    item = db.update_playlist(
        playlist_id,
        name=req.name.strip() if isinstance(req.name, str) else None,
        description=req.description.strip() if isinstance(req.description, str) else None,
        kind=req.kind,
        extraction_focus=req.extraction_focus.strip() if isinstance(req.extraction_focus, str) else None,
        enabled=req.enabled,
        queue_paused=req.queue_paused,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Playlist not found")
    return {"ok": True, "item": item}




@app.post("/playlists/sync")
def sync_playlists(req: PlaylistSyncRequest) -> dict:
    job = db.enqueue_playlist_sync(req.max_process)
    return {"ok": True, "job": job}


@app.get("/usage")
def usage() -> dict:
    return db.usage_report()


@app.get("/settings/automation")
def get_automation() -> dict:
    return db.automation_settings()


@app.post("/settings/automation")
def save_automation(req: AutomationRequest) -> dict:
    db.set_meta("sync_every_hours", str(req.sync_every_hours))
    return db.automation_settings()


@app.get("/worker/status")
def worker_status() -> dict:
    return db.worker_status()


@app.get("/readiness")
def readiness() -> dict:
    return db.readiness_report()


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
    agenda = req.agenda.strip()
    if req.agenda_mode == "custom" and not agenda:
        raise HTTPException(status_code=400, detail="Write a custom agenda or switch agenda mode to default.")
    meta = fetch_public_metadata(video_id)
    playlist_type = "podcast" if req.kind == "podcast" else "general"
    playlist_id = req.playlist_id.strip()
    db.upsert_video_pending(
        video_id=video_id,
        title=meta.title,
        url=meta.url,
        playlist_type=playlist_type,
        playlist_id=playlist_id,
        channel_name=meta.channel_name,
        user_agenda=agenda if req.agenda_mode == "custom" else "",
    )
    job = db.enqueue_process(
        video_id,
        {
            "source": "ingest",
            "kind": req.kind,
            "mode": req.agenda_mode,
            "agenda": agenda if req.agenda_mode == "custom" else "",
            "playlist_id": playlist_id,
        },
    )
    return {"ok": True, "video": db.get_video(video_id), "job": job}


@app.post("/videos/{video_id}/process")
def process_video(video_id: str, req: ProcessRequest) -> dict:
    video = db.get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    agenda = req.agenda.strip()
    if req.agenda_mode == "custom":
        if not agenda:
            raise HTTPException(status_code=400, detail="Write a custom agenda or switch agenda mode to default.")
        video = db.update_video_agenda(video_id, agenda)
    job = db.enqueue_process(
        video_id,
        {
            "source": req.reason,
            "mode": req.agenda_mode,
            "agenda": agenda if req.agenda_mode == "custom" else "",
        },
    )
    return {"ok": True, "video": video or db.get_video(video_id), "job": job}


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
