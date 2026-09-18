# InsightEngine Vercel Remake

This folder is a separate rebuild path for InsightEngine. It does not replace or modify
the Streamlit app. The goal is to make the system feel like a normal deployed web app:
fast navigation, a stable API, and video processing handled by a worker.

## Shape

- `web/` - Next.js interface for Vercel.
- `api/` - FastAPI service for reads, ingestion, settings and queue operations.
- `worker/` - Python worker that claims queued jobs and calls the existing processing
  pipeline from the root project.
- `database/` - SQL for the additional durable job table.

The existing Supabase/Postgres database remains the source of truth. The current
Streamlit app can continue running while this remake is developed and deployed.

## First deployment target

Use this arrangement first:

1. Deploy `web/` to Vercel.
2. Deploy `api/` to Vercel, Render, Railway, or Fly.io.
3. Deploy `worker/` as an always-on Python background service.
4. Point `NEXT_PUBLIC_API_BASE_URL` in `web/` to the API service URL.
5. Give `api/` and `worker/` the same `DATABASE_URL`.

The worker is deliberately separate because video processing can exceed ordinary
request/function lifetimes.

## Database setup

Run the SQL in `database/001_jobs.sql` once against Supabase/Postgres. It only adds
the `knowledge_jobs` queue table and indexes.

## Local development

API:

```powershell
cd "Vercel Remake\api"
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DATABASE_URL="postgresql://..."
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Web:

```powershell
cd "Vercel Remake\web"
npm install
$env:NEXT_PUBLIC_API_BASE_URL="http://localhost:8000"
npm run dev
```

Worker:

```powershell
cd "Vercel Remake"
$env:DATABASE_URL="postgresql://..."
$env:LEGACY_APP_ROOT="D:\projS\CursorP1"
..\.venv\Scripts\python.exe worker\worker.py
```

`LEGACY_APP_ROOT` points the worker at the current Streamlit project so it can reuse
the proven `poll.process_one()` and playlist `run_poll()` pipeline without copying or
modifying those files. Locally, run the worker with the root project `.venv` because
that environment already contains the extraction stack (`groq`, `google-genai`,
`anthropic`, `yt-dlp`, `tavily-python`, and related packages).

## Current dashboard flows

- **Add video** queues one YouTube URL with either the generated default agenda or a custom video-specific agenda.
- **Settings -> Profile-driven agenda** stores the user profile used by default agenda generation and custom-agenda extraction.
- **Settings -> Provider API keys** stores local runtime keys in `runtime/provider_keys.json`, which is git-ignored.
- **Queue -> Sync enabled playlists** pulls videos from enabled playlist profiles and queues processing through the same worker. Use `0` to register playlist videos without processing any immediately.

## Deploy notes

Full deployment instructions live in `DEPLOYMENT.md`. A Render-style API + worker
blueprint is included as `render.yaml` inside this folder. It is kept here so the
remake remains isolated from the Streamlit project; copy it to the repository root
only when you are ready to use Render's blueprint importer.

For Vercel `web/`, set:

- `NEXT_PUBLIC_API_BASE_URL=https://your-api-host`

For `api/`, set:

- `DATABASE_URL`
- `APP_ALLOWED_ORIGINS=https://your-vercel-app.vercel.app`

For `worker/`, set:

- `DATABASE_URL`
- `LEGACY_APP_ROOT=/path/to/repo/root`
- the same model/provider keys used by the Streamlit app.

The Streamlit app remains safe to use during the transition.
