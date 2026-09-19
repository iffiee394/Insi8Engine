# Vercel Remake goal plan

The goal is a fast, normal website version of the knowledge system that can run locally now and later deploy with a web app, API service, worker service, and Postgres database. The Streamlit version can keep running while this remake is tested.

## What is already done

1. **Fast dashboard shell**
   - Next.js frontend runs at `http://localhost:3000`.
   - It reads the API instead of doing heavy processing in the browser.
   - Videos show thumbnails, status, summary, expandable insights, research resources, and links.

2. **API service**
   - FastAPI runs at `http://127.0.0.1:8000`.
   - `/health` checks database and provider-key status.
   - `/videos`, `/jobs`, `/playlists`, `/settings/profile`, and `/settings/providers` drive the dashboard.

3. **Background worker**
   - The worker processes jobs outside the UI so the site does not freeze.
   - New videos are queued through `knowledge_jobs`.
   - Playlist sync can register videos only with `max_process=0`, or process a limited number with default agenda.
   - The worker writes a heartbeat so the Queue page can show whether processing is alive.

4. **Provider keys**
   - Settings accepts raw keys, `.env` style blocks, or JSON.
   - Runtime keys are stored in `Vercel Remake/runtime/provider_keys.json`.
   - The API and worker reload those keys for new jobs.

5. **Profile-driven agenda**
   - Settings saves the stable user profile.
   - Default processing uses profile + playlist focus + transcript to create the agenda.
   - Custom agenda is combined with profile + playlist focus + transcript for a specific video.
   - The video detail screen shows the Processing lens so you can verify what guided extraction.
   - Settings can edit playlist extraction focus, so playlist-driven default processing can be tuned from the remake dashboard.
   - Settings includes a starter setup button that fills a practical default profile and playlist focus for fast testing.

6. **Deployment path**
   - `DEPLOYMENT.md` contains the service split and environment variables.
   - `render.yaml` is included for API and worker hosting.
   - The frontend is ready for Vercel/Netlify-style hosting with `NEXT_PUBLIC_API_BASE_URL`.
   - Settings shows a readiness panel for profile, worker, playlist focus, processed videos, and queue state.

## Normal user workflow

1. Open `http://localhost:3000`.
2. Go to **Settings**.
3. Save the profile:
   - About me / background: what you are building and why.
   - What insights matter to me: the subjects and opportunities you care about.
   - Insight style: how detailed, practical, or research-heavy the notes should be.
   - Things I already know: topics to skip unless a video has a new angle.
4. Go to **Add**.
5. Paste a YouTube URL.
6. Choose a playlist profile if one applies.
7. Pick an agenda mode:
   - **Default agenda** for most videos and playlist automation.
   - **Custom agenda** when this video needs a special question or angle.
8. Open **Queue** and wait for the job to reach `done`.
9. Open the video in **Library** and inspect:
   - Processing lens
   - Summary
   - Expandable insights
   - Research resources
   - Links

## Exact local commands

Run these from PowerShell.

```powershell
cd "D:\projS\CursorP1\Vercel Remake\api"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd "D:\projS\CursorP1\Vercel Remake"
npx next dev --port 3000
```

```powershell
cd "D:\projS\CursorP1\Vercel Remake"
..\.venv\Scripts\python.exe worker\worker.py
```

## Verification checklist

Run the smoke check after starting the API, web app, and worker.

```powershell
cd "D:\projS\CursorP1"
.\.venv\Scripts\python.exe "Vercel Remake\scripts\smoke_check.py" --profile-roundtrip
```

Expected result:

- Web responds.
- API health returns `ok: true`.
- Videos load.
- At least one processed video exists.
- Playlists load.
- Profile save/restore works.
- Worker status endpoint loads.
- Readiness report loads.
- Video Processing lens sees an active profile during the temporary roundtrip.
- Jobs load.

For playlist sync without processing a video:

```powershell
.\.venv\Scripts\python.exe "Vercel Remake\scripts\smoke_check.py" --queue-playlist-sync --max-process 0 --wait-job 260
```

To prove playlist agenda focus wiring without permanently changing a playlist:

```powershell
.\.venv\Scripts\python.exe "Vercel Remake\scripts\smoke_check.py" --playlist-roundtrip
```

To prove the one-click starter setup can make readiness pass and then restore the
original profile/playlists:

```powershell
.\.venv\Scripts\python.exe "Vercel Remake\scripts\smoke_check.py" --starter-roundtrip
```

## Cloud deployment shape

1. **Database**
   - Keep using the existing Postgres/Supabase database.
   - Apply `database/001_jobs.sql` if the queue table is missing.

2. **API host**
   - Deploy `Vercel Remake/api`.
   - Set `DATABASE_URL`, provider keys, and `APP_ALLOWED_ORIGINS`.

3. **Worker host**
   - Deploy `Vercel Remake/worker` as an always-on worker.
   - Use the same `DATABASE_URL` and provider keys.
   - Do not run the worker as a serverless function.

4. **Frontend host**
   - Deploy `Vercel Remake/web`.
   - Set `NEXT_PUBLIC_API_BASE_URL` to the hosted API URL.

5. **Smoke test hosted URLs**
   - Run `scripts/smoke_check.py` with `--api-base` and `--web-url`.

## Remaining improvements

1. Add scheduled cloud sync for specific days after the manual playlist sync is proven stable.
2. Add login/auth before public deployment if the dashboard will be exposed beyond personal use.
3. Add a compact chat/retrieval tab only after video ingestion, agendas, and insight rendering feel reliable.
