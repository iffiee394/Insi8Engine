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
- Browser check passed at `http://localhost:3000`: 66 videos load, thumbnails render in the library, the selected video detail renders, Add opens, Queue opens, and Settings shows provider/API status.
- Processed-video insight check passed using `dkyYDGxbBFY`: summary renders, 7 insight sections display as collapsible one-column sections, and research resources/links render from `structured_insights`.
- Settings now includes write-only provider API key fields for YouTube, Gemini, Anthropic, Groq, and Tavily. Saved runtime keys are ignored by git and loaded by the API/worker.
- Profile-driven agenda settings are available in the remake Settings page and are stored in the shared `personal_settings` profile row.
- Queue now supports `sync_playlists` jobs for enabled playlist profiles.

## Current local test URLs

- Frontend: `http://localhost:3000`
- API: `http://127.0.0.1:8000`
- API health: `http://127.0.0.1:8000/health`


## Insight data audit

Checked on 2026-09-16 against the current configured database:

- 66 total videos are available through the remake.
- 65 videos are `done` and have summaries plus key points.
- 47 videos also have structured insight JSON.
- 1 video is `failed` with the known YouTube `HTTP Error 403: Forbidden` processing issue.

The current insight display issue was a frontend formatting problem, not a missing database connection.

## Not done yet

- `database/001_jobs.sql` has not been applied to production Supabase from this folder.
- The hosted FastAPI service has not been deployed yet.
- The worker has processed a newly added video through the remake queue, and playlist sync has been verified with a register-only `sync_playlists` job.
- Chat and semantic search are not rebuilt in the new UI yet. The first version prioritizes fast baseline browsing, adding videos, queue visibility, settings visibility, and transcript fallback.

## Next steps

1. Apply `database/001_jobs.sql` to Supabase.
2. Deploy `api/` with `DATABASE_URL` and provider keys.
3. Deploy `worker/` with `DATABASE_URL`, provider keys, and `LEGACY_APP_ROOT` pointing at the current repo root.
4. Deploy `web/` to Vercel with `NEXT_PUBLIC_API_BASE_URL` pointing at the API.
5. Add one disposable test video and verify: ingest -> queued job -> worker processing -> done/failed state -> transcript fallback if YouTube blocks audio.