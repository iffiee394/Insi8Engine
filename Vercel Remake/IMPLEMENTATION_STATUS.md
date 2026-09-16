# Vercel remake status

Updated: 2026-09-16.

## Built

- Next.js dashboard app in `web/`, styled to match the dark dashboard direction from the Streamlit version and shared screenshot: compact rail navigation, persistent library pane, minimal detail area, and small status chips instead of chunky Streamlit blocks.
- FastAPI service in `api/`.
- Python queue worker in `worker/`.
- Postgres job queue SQL in `database/001_jobs.sql`.

The Streamlit app is untouched. This remake reads the existing `videos`, `playlists`,
`video_transcripts`, and related tables, then adds only `knowledge_jobs` for durable
processing.

## Verified locally

- API Python files compile.
- API loads the existing local `.env` without copying secrets into the remake folder.
- API `/health` reports database and provider-key status.
- API `/videos`, `/videos/{id}`, and `/jobs` return real existing data from the current database.
- Worker dependencies installed and `worker.py` starts successfully with the existing local `.env` and legacy processor root.
- Web dependencies installed.
- `npm audit --omit=dev` reports zero vulnerabilities after moving to Next 16.3.5.
- `npm run typecheck` passes.
- `npm run build` passes.
- Browser check passed at `http://localhost:3000`: 66 videos load, the selected video detail renders, Add opens, Queue opens, and Settings shows provider/API status.

## Current local test URLs

- Frontend: `http://localhost:3000`
- API: `http://127.0.0.1:8000`
- API health: `http://127.0.0.1:8000/health`

## Not done yet

- `database/001_jobs.sql` has not been applied to production Supabase from this folder.
- The hosted FastAPI service has not been deployed yet.
- The worker is running locally, but it has not processed a new live test job in this remake yet.
- Chat and semantic search are not rebuilt in the new UI yet. The first version prioritizes fast baseline browsing, adding videos, queue visibility, settings visibility, and transcript fallback.

## Next steps

1. Apply `database/001_jobs.sql` to Supabase.
2. Deploy `api/` with `DATABASE_URL` and provider keys.
3. Deploy `worker/` with `DATABASE_URL`, provider keys, and `LEGACY_APP_ROOT` pointing at the current repo root.
4. Deploy `web/` to Vercel with `NEXT_PUBLIC_API_BASE_URL` pointing at the API.
5. Add one disposable test video and verify: ingest -> queued job -> worker processing -> done/failed state -> transcript fallback if YouTube blocks audio.