# Baseline speed plan

Updated: 2026-09-13. This implementation plan supersedes the feature-first release
order in `specs plan.md`. Finish a dependable, responsive baseline before expanding chat.

## 1. What must work first

The owner can open the site, browse existing notes, add a video, see its processing
state, recover a failed import, and find the API configuration instructions. Navigation
must preserve the page shell and must not depend on an AI provider responding.

“Fast” needs separate measurements:

- Browser interaction: changing screens, expanding controls, choosing a video.
- Data access: fetching metadata or one video's saved notes.
- Ingestion: acquiring captions/audio and generating notes. This can take substantially
  longer, but it must never hold the interface hostage.

Do not promise zero failures from YouTube or AI services. Provide bounded failures,
specific recovery actions, and preserved progress instead.

## 2. Confirmed defects and repair status

Code inspection found that `components/stitch_pages.py` injects JavaScript into the
parent page and assigns `window.location.search`. This reloads the complete document.
The supposedly native homepage also used ordinary `?page=` anchors, which reload it.
These reloads recreate the page/session rather than simply changing the visible view.

The repair replaces active iframe routes with `components/baseline_pages.py` and
uses Streamlit callbacks in `components/navigation.py`. Query parameters are updated
through Streamlit while keeping the session alive. Legacy iframe source is retained
for reference but is no longer routed to by the app shell.

The shell also fetched the library on Settings, Add, Chat and export screens. The repair
limits that query to Home, Library, Queue and Playlists. Idle pages no longer schedule
the worker polling fragment; a processing page can still refresh when its worker ends.

On 2026-09-13, a read-only local-to-production PostgreSQL check measured 1.183 seconds
for the first light-library read and 0.478 seconds for the next read. These are two
diagnostic samples, not hosted browser timings or p95 results. There are still 66 videos,
65 completed and 1 failed. Full-page reloads amplify these costs.

The current failed record is `JpaK3F7fLHE`, with a YouTube audio download HTTP 403.
This supersedes the earlier quota diagnosis for that record. The screenshot alone
does not prove whether the underlying cause is a cloud IP block, an expired media URL,
or an unsolved YouTube challenge.

Local inspection also found no `yt_dlp_ejs` package. The repair pins the downloader
with its default dependencies and supplies Deno, enables installed runtimes explicitly,
keeps downloader warnings visible in logs, bounds network retries, rejects partial
downloads, and stops switching AI providers after a source-download failure.

When automatic acquisition fails, the owner can save a transcript on the failed
video page. The existing pipeline reads that stored transcript first, skipping both
YouTube retrieval and audio transcription. It still needs a working extraction API key.

## 3. Immediate test sequence

1. Install `requirements.txt` and run `python -m unittest discover -s tests`.
2. Start `streamlit run app.py`. Use a fresh browser session.
3. Home → Add video → More → Playlists → More → Settings → Library. Repeat 20 times.
   Confirm no document reload, duplicate tabs, lost search state, blank document,
   or iframe navigation error. Browser back/forward behavior must also be checked.
4. Open several completed videos. Verify summaries, insight points, source timestamps,
   resources and note downloads remain available. Test a narrow mobile viewport.
5. Open the failed video. Confirm the error says YouTube blocked the download and
   provides a transcript recovery action, rather than recommending a new Gemini key.
6. Test transcript saving on disposable data. Confirm the next processing attempt
   uses `user_transcript` and performs no caption/audio retrieval.
7. In Settings → Connected services, verify the exact key-change instructions.
   “Configured” must only mean present, not verified valid or within quota.
8. Deploy. Repeat the browser checks against the actual hosted service. Local success
   is not a hosted speed or YouTube-access guarantee.

The following full-system checks remain necessary: successful ingestion after the
owner rotates the key, hosted YouTube retrieval, persisted-job crash recovery,
production latency percentiles and database restore testing.

## 4. Recommended permanent implementation

Use a small React/TypeScript client with a persistent navigation shell, a Python
FastAPI service, the existing PostgreSQL database, and an independently supervised
Python worker. Serve the client and API under one origin initially to simplify login,
cookies and deployment. Keep the existing extraction and export functions behind
service functions. Do not rewrite the whole pipeline simply to change frameworks.

Native Streamlit is the immediate repair. The separate client is the better permanent
fit for this requirement because local tabs and menus need no Python round trip, and
loading one screen's data need not replace the entire interface.

Run the API and worker on always-on compute in the database's region. A free service
that sleeps would reintroduce the opening delay. Render is a viable initial host with
an always-on web service and background worker; choose its region only after checking
the database region. An equivalent always-on container platform is also suitable.
No new hosting purchase or account migration has been performed by this repair.

## 5. Build order and completion gates

### Step A — Define measurements and preserve existing data

Record click-to-visible-content, API duration, database query duration, payload bytes,
and processing stage durations separately. Report median and p95 over at least 30
warm interactions; report first-open measurements separately. Use real representative
videos and both desktop/mobile conditions. Keep production inputs out of committed fixtures.

Take a database backup and prove restoration into a disposable database before migrations.
Compare video, transcript, embedding and saved-item counts before and after.

### Step B — Build only the reading experience

Create the client shell with Home, Library, Add, Queue and Settings. Keep advanced
features under More. Add API endpoints for paginated video metadata and one video detail.
Return lightweight list records; never send every transcript or embedding on opening.
Keep fetched video details in a client cache. Preserve filters and selection when navigating.

Use a bounded connection pool; the current thread-local DB wrapper performs a `SELECT 1`
on each checkout and is not a proper bounded pool. Profile it before changing it. Move
migrations to deployment startup. Use a query timeout and close cursors/transactions.

Gate: menus and local tabs react within 100 ms; warm navigation with cached data is
visible within 200 ms; warm metadata/detail API p95 is below 500 ms in the chosen region.
These are engineering targets, not measurements already achieved.

### Step C — Make adding work immediate and durable

`POST /videos` validates a YouTube URL and atomically creates/returns the video and job.
It returns HTTP 202 after committing the job, without waiting for YouTube metadata,
captions, downloads or AI requests. Deduplicate by video ID plus requested processing
revision. Fetch the title in the worker; show “Fetching title…” until it arrives.

Create a jobs table with job ID, video ID, state, stage, attempt count, next attempt,
lease owner, lease expiry, last heartbeat, error category and timestamps. Enforce a
unique active job per video. The worker claims using a transaction and
`FOR UPDATE SKIP LOCKED`, renews its lease, and reclaims expired leases after crashes.
Do not use a shared boolean as a lock. Do not use FastAPI BackgroundTasks as the
durability mechanism for long media jobs.

Gate: Add returns within one second at p95; closing the browser does not stop the job;
a worker restart resumes/retries without duplicate active work or lost records.

### Step D — Stabilize acquisition and extraction

Acquisition order: stored transcript → public captions → one audio download → speech
transcription → user-supplied transcript/media when retrieval is unavailable. Reuse the
same local audio if switching transcription providers. Do not redownload it per provider.
Keep sources/timing quality explicit. Never invent timestamps for pasted plain text.

Record separate error categories: unavailable video, YouTube access blocked, missing
runtime, timeout, provider quota, authentication, invalid model output and database failure.
Retry only transient errors with bounded backoff; respect retry-after for rate limits.
An access-blocked job should wait for recovery input, not loop indefinitely.

Save the transcript before extraction, then checkpoint completed extraction/index stages.
Make core extraction a single structured-output request where feasible. Put optional
web research after core notes are available. Verify output completeness before deleting
the current multi-pass prompts: speed must not silently remove useful content.

Gate: a representative captioned video completes on the production host; a supplied
transcript works independently of YouTube; an access block and a quota error each show
the right recovery path. No processing stage blocks browsing.

### Step E — Deploy and run the owner workflow

Provide an owner-authenticated site, a health endpoint, a separately supervised worker,
environment secrets, database backups and a rollback to the Streamlit release. Keep
credentials server-side. Settings shows presence/validation results without exposing keys.
Rotate the key in the host dashboard first; an in-app secrets editor is unnecessary
for the initial baseline release.

Run: open → add → leave page → check queue → read notes → restart worker → return.
Test duplicate submission, API 401/429, YouTube 403, missing captions and an interrupted job.
Only switch the main link after the workflow and latency gates pass on the host.

### Step F — Resume knowledge features

Reconnect existing Search, Saved and Ask after Steps A–E pass. Start search with a fast
lexical result, then add semantic retrieval and streaming answers with citations.
Preserve the prior release's data and tests. Do not add agents, graphs, extra dashboards,
or new content sources until the baseline remains stable during normal owner use.

## 6. Primary references checked

- [Streamlit navigation and session state](https://docs.streamlit.io/develop/concepts/multipage-apps/overview)
- [yt-dlp supported runtimes and challenge solver](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- [Deno's Python distribution](https://pypi.org/project/deno/)
- [Transcript library cloud IP limitation](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception)
- [FastAPI background-task caveat](https://fastapi.tiangolo.com/tutorial/background-tasks/#caveat)
- [Render service types](https://render.com/docs/service-types)
- [Render free-service sleep limitations](https://render.com/docs/free)
