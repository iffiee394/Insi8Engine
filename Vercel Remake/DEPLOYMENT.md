# Deployment plan for the Vercel Remake

This remake is three services that share one Postgres/Supabase database:

1. **Web**: Next.js dashboard in `Vercel Remake/web`.
2. **API**: FastAPI service in `Vercel Remake/api`.
3. **Worker**: always-on Python queue worker in `Vercel Remake/worker` that reuses the root legacy processing pipeline.

The Streamlit app can stay running during migration. The remake reads the same `videos`, `playlists`, transcripts, profile, and provider-key state, and adds the `knowledge_jobs` queue table.

## Required database setup

Run `Vercel Remake/database/001_jobs.sql` once against Supabase/Postgres before using the worker in production.

The API also creates `knowledge_jobs` and `personal_settings` defensively at runtime, but applying the SQL explicitly keeps production setup predictable.

## Environment variables

Set these on the API and worker:

```env
DATABASE_URL=postgresql://...
YOUTUBE_API_KEY=...
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
GROQ_API_KEY=...
TAVILY_API_KEY=...
```

Set this on the API:

```env
APP_ALLOWED_ORIGINS=https://your-vercel-app.vercel.app
```

Set this on the web app:

```env
NEXT_PUBLIC_API_BASE_URL=https://your-api-host
```

Set this on the worker only when the service starts outside the repository root:

```env
LEGACY_APP_ROOT=/path/to/repo/root
WORKER_POLL_SECONDS=5
```

## Local commands

Run the API:

```powershell
cd "D:\projS\CursorP1\Vercel Remake\api"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run the web app:

```powershell
cd "D:\projS\CursorP1\Vercel Remake\web"
npx next dev --port 3000
```

Run the worker locally with the root environment, because that environment already has the legacy extraction stack:

```powershell
cd "D:\projS\CursorP1\Vercel Remake"
..\.venv\Scripts\python.exe worker\worker.py
```

## Render/Railway style API service

Build command from the repository root:

```bash
pip install -r "Vercel Remake/api/requirements.txt"
```

Start command from the repository root:

```bash
cd "Vercel Remake/api" && python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
```

## Render/Railway style worker service

Build command from the repository root:

```bash
pip install -r requirements.txt -r "Vercel Remake/worker/requirements.txt"
```

Start command from the repository root:

```bash
cd "Vercel Remake" && python worker/worker.py
```

The worker must be an always-on background service. Do not deploy it as a serverless function; processing videos and syncing playlists can exceed request time limits.

## Vercel web app

Set the Vercel project root to:

```text
Vercel Remake/web
```

Build command:

```bash
npm run build
```

Output is handled by Next.js. Set `NEXT_PUBLIC_API_BASE_URL` to the hosted API URL.

## Smoke test after deploy

You can run the repeatable smoke checker from the repository root:

```bash
python "Vercel Remake/scripts/smoke_check.py" \
  --api-base https://your-api-host \
  --web-url https://your-vercel-app.vercel.app
```

For local testing with the dashboard already running:

```powershell
cd "D:\projS\CursorP1"
.\.venv\Scripts\python.exe "Vercel Remake\scripts\smoke_check.py"
```

To include a safe register-only playlist sync job, add `--queue-playlist-sync --max-process 0`.

To prove profile-driven agenda wiring without permanently changing the profile, add
`--profile-roundtrip`. The script saves a temporary marked profile, verifies the
profile prompt and video processing lens see it, then restores the original profile.

To prove playlist extraction focus wiring without permanently changing a playlist, add
`--playlist-roundtrip`. The script saves a temporary marked playlist focus, verifies
the API accepts it and the agenda lens can see it when applicable, then restores the
original playlist.

1. Open `/health` on the API. It should return `ok: true` and provider service flags.
2. Open the web dashboard. Videos should load from `/videos`.
3. Save a profile in Settings and confirm `/settings/profile` returns a prompt preview.
4. Open Queue and confirm `/worker/status` reports the worker heartbeat after the worker starts.
5. Open Settings and confirm `/readiness` reports profile, worker, playlist focus, processed videos, and queue state.
6. Save playlist extraction focus in Settings and confirm the selected video's Processing lens can show playlist focus.
7. Add one disposable YouTube video with default agenda. Confirm it appears in Queue.
8. Confirm the worker marks the job `done` or records a clear error.
9. Use Queue -> Sync enabled playlists with `0` first. Confirm a `sync_playlists` job reaches `done`.
10. Use Queue -> Sync enabled playlists with `1` only after the register-only sync works.
