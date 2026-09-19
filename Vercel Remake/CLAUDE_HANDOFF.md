# Claude handoff — Vercel Remake knowledge system

Date: 2026-09-19
Workspace: `D:\projS\CursorP1`
Project folder: `D:\projS\CursorP1\Vercel Remake`

## Goal

Make the Vercel Remake a fast, deployable replacement for the Streamlit knowledge-system workflow while preserving the important behavior:

- videos load from the database
- new videos can be added and processed
- provider keys work from the dashboard/runtime file
- playlist sync can drive default processing
- a saved profile influences default agendas
- a custom agenda combines with the profile for one video
- insights, research, and links render clearly
- local verification proves the system before cloud deployment

## Current status

This is now working locally.

Live local URLs:

- Web dashboard: `http://localhost:3000`
- API: `http://127.0.0.1:8000`
- API health: `http://127.0.0.1:8000/health`
- Readiness: `http://127.0.0.1:8000/readiness`

Latest code checkpoint:

- `bf9a134 Add starter setup for readiness`

The latest real end-to-end processing test succeeded:

- Video: `KebgB_cgDgM`
- Title: `GPT 6 Astra AI Full COURSE 1 HOUR (Build & Automate Anything)`
- Job: `2ff763e5-44dc-43d2-bff6-f9d02ebe37ca`
- Final job status: `done`
- Final video status: `done`
- Attempts: `1`
- Verified fields present: summary, key points, structured insights, research data, generated default agenda
- Processing lens verified: default mode, profile active, playlist focus active

Final smoke check passed with:

```powershell
.\.venv\Scripts\python.exe "Vercel Remake\scripts\smoke_check.py" --profile-roundtrip --playlist-roundtrip --starter-roundtrip
```

Final smoke evidence included:

- web responds: HTTP 200
- API health: database configured and provider flags true
- videos load: latest `KebgB_cgDgM:done`
- processed video present: 4 done videos in first page
- playlists load: 2 playlists
- worker status: 1 active worker, 0 queued, 0 running
- readiness report: `ok=True`, 19 done, 0 pending
- profile endpoint: profile text present
- profile roundtrip passed and restored
- playlist focus roundtrip passed and restored
- starter setup readiness roundtrip passed and restored
- jobs load passed

## Architecture

The remake is isolated in `Vercel Remake` so the old Streamlit app is not touched.

### Web

Path: `Vercel Remake/web`

- Next.js dashboard
- Main page: `web/app/page.tsx`
- Styles: `web/app/globals.css`
- API client: `web/lib/api.ts`

Dashboard tabs:

- Library: videos, thumbnails, summaries, expandable insights, research, links, processing lens
- Add: add a YouTube video with default or custom agenda
- Queue: worker status, active queue state, playlist sync
- Settings: provider keys, readiness panel, starter setup, profile-driven agenda, playlist agenda profiles, deployment variables

### API

Path: `Vercel Remake/api`

- FastAPI app: `api/app/main.py`
- Database helpers: `api/app/db.py`
- Runtime provider keys: `api/app/runtime_settings.py`
- Supabase/Postgres connection fallback: `api/app/pgconnect.py`

Important endpoints:

- `GET /health`
- `GET /readiness`
- `GET /videos`
- `GET /videos/{video_id}`
- `POST /videos/{video_id}/process`
- `POST /videos/{video_id}/transcript`
- `POST /ingest`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `GET /playlists`
- `PATCH /playlists/{playlist_id}`
- `POST /playlists/sync`
- `GET /worker/status`
- `GET /settings/profile`
- `POST /settings/profile`
- `POST /settings/starter-setup`
- `GET /settings/providers`
- `POST /settings/providers`

### Worker

Path: `Vercel Remake/worker/worker.py`

- Always-on Python worker
- Claims jobs from `knowledge_jobs` with `FOR UPDATE SKIP LOCKED`
- Runs the legacy pipeline from the root project
- Writes `worker_heartbeats` so Queue/Readiness can show whether processing is alive
- Handles:
  - `process_video`
  - `sync_playlists`
  - custom agenda processing

### Database additions

Migration file: `Vercel Remake/database/001_jobs.sql`

Tables/indexes added:

- `knowledge_jobs`
- active process unique index for one active process per video
- `worker_heartbeats`

The API also creates these tables if missing.

## Runtime commands

Run in three terminals.

API:

```powershell
cd "D:\projS\CursorP1\Vercel Remake\api"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Web:

```powershell
cd "D:\projS\CursorP1\Vercel Remake\web"
npx next dev --port 3000
```

Worker:

```powershell
cd "D:\projS\CursorP1\Vercel Remake"
..\.venv\Scripts\python.exe worker\worker.py
```

Use the root venv for the worker because it needs the legacy pipeline dependencies.

## Verification commands

Frontend/API build checks:

```powershell
cd "D:\projS\CursorP1\Vercel Remake"
..\.venv\Scripts\python.exe -m compileall -q api worker scripts
cd "D:\projS\CursorP1\Vercel Remake\web"
npm run typecheck
npm run build
```

Full local smoke check:

```powershell
cd "D:\projS\CursorP1"
.\.venv\Scripts\python.exe "Vercel Remake\scripts\smoke_check.py" --profile-roundtrip --playlist-roundtrip --starter-roundtrip
```

Safe playlist sync check:

```powershell
cd "D:\projS\CursorP1"
.\.venv\Scripts\python.exe "Vercel Remake\scripts\smoke_check.py" --queue-playlist-sync --max-process 0 --wait-job 260
```

## Provider keys

Dashboard path:

- Settings -> Provider API keys

Supported providers:

- YouTube
- Gemini
- Anthropic
- Groq
- Tavily

Runtime key file:

- `Vercel Remake/runtime/provider_keys.json`

This file is intentionally not committed. The dashboard accepts raw keys, `.env` blocks, and JSON. New worker jobs use updated keys.

## Readiness and starter setup

Settings has a readiness panel. It checks:

- profile text
- worker heartbeat
- playlist extraction focus
- processed video count
- queue state

Settings also has **Apply starter setup**. It fills a practical default profile and playlist extraction focus when those fields are empty. It preserves name/email and does not overwrite existing profile/focus unless the API is called with `overwrite=true`.

Current live readiness is green after applying starter setup and processing the pending video.

## Deployment shape

Deployment notes are in:

- `Vercel Remake/DEPLOYMENT.md`
- `Vercel Remake/render.yaml`

Recommended cloud split:

1. Postgres/Supabase database
2. FastAPI API service
3. Always-on worker service
4. Vercel/Netlify web frontend

Required hosted environment variables include:

- `DATABASE_URL`
- `NEXT_PUBLIC_API_BASE_URL`
- `APP_ALLOWED_ORIGINS`
- `YOUTUBE_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GROQ_API_KEY`
- `TAVILY_API_KEY`

The worker must not be deployed as a serverless function.

## Remaining optional improvements

The core local goal is now verified. Reasonable next improvements before public/cloud use:

1. Add authentication before exposing the dashboard publicly.
2. Add scheduled cloud playlist sync for specific days.
3. Add a compact chat/retrieval tab after the ingestion/dashboard path stays stable.
4. Add a button to hide/clear old failed jobs from the Queue UI.
5. Add hosted deployment smoke check after API/worker/web are deployed.

## Cautions for the next model

- Keep new work inside `Vercel Remake` unless explicitly asked otherwise.
- Do not kill worker “duplicate” processes casually on Windows. The root venv worker often appears as two process entries.
- Do not expose provider keys in logs or final answers.
- If processing a video, monitor `/jobs/{job_id}`, `/worker/status`, and `/videos/{video_id}`.
- If readiness becomes false, check profile, playlist focus, and worker heartbeat first.
