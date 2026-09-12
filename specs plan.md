# Specs plan — InsightEngine personal knowledge system

Prepared: 2026-09-12. Baseline commit: `76f6a63`.
Status: implementation specification; application changes have not been built by this document.

## 1. Outcome and fastest route

Make the existing library useful for actual work: find relevant evidence, ask questions, save what matters to a project, and record what you tried.

The first usable release must let the owner:

1. Search the content of completed videos, including ideas phrased differently from the query.
2. Open the relevant source video and available timestamp.
3. Ask a question about one video or the library and see cited evidence.
4. Save an insight or answer with a personal note into a project collection.
5. Return after an application restart and find their profile, notes, and conversations intact.
6. Download useful Markdown onto their own computer.

Deliver in small working releases. **Release A: Search and save** is the first checkpoint; **Release B: Ask and remember** completes the minimum useful knowledge system. **Release C: Dependable unattended processing** follows. Release A should be shown as soon as it passes its checks; continue to B when implementing the full minimum system.

Keep Python, Streamlit, PostgreSQL/Supabase, pgvector, and the existing extraction pipeline. Use native Streamlit forms for the new interactive pages. Preserve the current library presentation. A frontend rewrite, graph visualization, multi-user SaaS, external integrations, or a new agent framework is outside these releases.

No fixed completion-time promise: provider availability and deployment access vary. Order tasks by dependency and verify each slice before expanding it. Prefer one complete interaction over several unfinished screens.

## 2. Evidence and limits

Read-only database snapshot on 2026-09-12:

- PostgreSQL connected; 2 playlists; 66 videos: 65 done, 1 failed.
- 426 embedding rows covering 47 videos; 18 done videos have no embeddings.
- This measures index presence, not completeness or retrieval quality.
- The hosted browser, hosting access controls, backup settings, and scheduled worker were not verified in this assessment.

Current implementation facts:

- `components/ui_shell.py:render_app` routes only library, queue, playlists, and settings. Its `ctx` argument receives old renderers from `app.py` but does not use them.
- `components/stitch_pages.py:_chat_pane` renders a disabled preview. `_library_js/onSearch` filters displayed list metadata rather than invoking `search.search_insights`.
- `search.py` already embeds insight clusters; `db.search_embeddings` ranks in PostgreSQL. SQLite uses NumPy scoring.
- `generate_embeddings_for_video` deletes old embeddings before making the provider call. `store_embeddings` also deletes separately from the insert transaction. Both must change before bulk repair.
- `pipeline._finalize_video_result` indexes results before `poll.process_one` saves the final structured insight record. Failure or manual agenda regeneration can make the searchable version differ from the displayed version.
- `pipeline.fetch_transcript_data` fetches captions/audio each time. `chat_with_video` calls it again and truncates the full transcript to a character limit. Transcript bodies are not durably stored in the database.
- `db.get_profile/set_profile` read/write `data/profile.json`; PostgreSQL does not currently make profile storage durable.
- The current export route writes `exports/<video_id>.md` on the server. The renderer exists, but the browser download is unfinished.
- Background processing uses a subprocess plus a shared `poll_worker_running` flag. That is not a durable job queue or an independently scheduled service.
- September 7 commits added light list records, lazy detail rendering, database connection reuse, and Streamlit read caching. Preserve these improvements.

The older production and shipping plans are historical context. For this work, follow this specification's personal-use scope and priorities. Verify function locations against the checkout before editing; line numbers can move.

## 3. Working rules for the implementing model

1. Read this file, the handoff, and the acceptance checklist. Inspect the checkout and resume the first unchecked task in `docs/knowledge-system/BUILD_STATUS.md`.
2. Preserve unrelated untracked files, existing video records, playlists, provider settings, and the separate content-engine work. Do not reprocess the whole library as a shortcut.
3. Make additive, repeatable schema migrations; exercise them on a disposable database before applying them to the configured data store. Never print connection strings, keys, profile contents, or private conversations into build logs.
4. Keep database work out of unconditional page rendering. Run embedding/LLM calls only on explicit submission or worker execution, not every rerun.
5. Ship simple native widgets before spending time replicating the iframe design. Navigation may use route IDs; new questions, notes, profiles, and mutation payloads must use form submission rather than URL query parameters.
6. Every task ends with observable acceptance evidence. A function that exists but cannot be reached from the active UI is unfinished.
7. Treat model names, prices, and provider limits as configuration. Do not upgrade unrelated dependencies or claim free usage from a missing price entry.
8. Keep application build, hosted rollout, and actual unattended operation as separately reported states. Do not claim a deployment from a local test. Follow the user's existing authorization for each action; this document adds no separate permission gate.

## 4. Release A — Search and save

### A0. Establish a recoverable baseline

Touch: existing configuration and connection helpers; new `scripts/knowledge_health.py`; acceptance evidence.

1. Record current commit, dirty files, Python/Streamlit versions, backend type, and counts without logging credentials.
2. Implement a read-only health command reporting video status counts, index coverage, stale indexes, and sanitized failure categories. It must not call `init_db` or create tables on a read-only run.
3. Count empty/malformed structured insights separately from missing, partial, or stale embeddings. Query aggregates rather than transferring every vector.
4. Before schema changes or repair against real data, create a recoverable database backup and verify restore into a disposable target. Include local profile/knowledge-base files because their migration has not happened yet. Keep backups outside Git and record their location privately.
5. Establish a disposable SQLite test database. Exercise database-specific operations against a disposable PostgreSQL database when available; record a PostgreSQL check as blocked if none is available rather than substituting SQLite evidence.

Done: baseline recorded, recovery verified before real mutations, health command demonstrably read-only. Diagnose the one failed video; retry only that video if its cause is recoverable. Private/deleted videos may remain failed with a clear explanation.

### A1. Persist personal settings and saved knowledge

Touch: `db.py`, `dbcache.py`; new `knowledge_store.py` and migration module; settings UI.

Use application-generated UUID text identifiers, parameterized SQL, and UTC timestamps. JSON stored as text is acceptable for compatibility with the existing code. Add only these structures for Release A:

- `personal_settings`: singleton key, `profile_json`, `updated_at`. Preserve all existing profile keys, including unknown/custom ones.
- `collections`: `id`, `name`, `description`, `created_at`, `updated_at`, optional `archived_at`.
- `saved_items`: `id`, unique `save_key`, `kind` (insight/answer/note), `title`, `body_snapshot`, `sources_json`, `personal_note`, `created_at`, `updated_at`.
- `collection_items`: `collection_id`, `saved_item_id`, `created_at`; unique pair with foreign keys.

Steps:

1. Add a versioned, idempotent migration entry point. Run migrations at startup once per process, never on the three-second fragment tick.
2. If the database profile does not exist, import the existing local profile once. Existing database settings win on later starts; a stale file must never overwrite them. Preserve the original file as a recovery source.
3. Redirect profile reads and writes to the database. Remove request-time reliance on `knowledge_base.txt`; keep compatibility helpers returning the database profile's known-topics field. Separate JSON parsing from I/O so old behavior can be tested.
4. Implement collection create/rename/archive and save/update/remove operations. An item can belong to several collections. Removing a membership must not delete the saved item or its source video.
5. Save a content snapshot and citation metadata. Do not rely on `(video_id, chunk_index)` alone: re-extraction may reorder chunks. Build a stable `save_key` from source identity plus content hash for insights, answer ID for answers, UUID for standalone notes.
6. Invalidate only affected read caches after successful commits. Verify settings and saved items persist with a fresh process.

Done: a changed profile and a saved note survive restart; repeat save creates one item; an item can belong to two collections; schema migration can run twice without data loss.

### A2. Repair indexing safely and expose coverage

Touch: `search.py`, `db.py`, `pipeline.py`, `poll.py`, `batch_process.py`; new repair CLI.

Add an `index_state` record per video and insight variant: model, vector dimension, normalized source hash, expected/stored chunk counts, status, last success time, last error, and index generation. Release A indexes the auto insight variant only. Manual agenda results must not silently overwrite that index.

1. Extract a pure function that converts structured insights into nonempty, deterministic chunks. Normalize title/content/points before hashing. Exclude empty chunks and record why a video is ineligible.
2. Generate and validate all replacement vectors before changing database rows. Require matching counts, expected dimension, finite numbers, and nonzero norms.
3. In ONE transaction, delete the old auto index, insert the full replacement, and update successful index metadata. A failed provider call or insert must preserve the last successful generation. Never commit a delete separately.
4. Save completed extraction results first, then index that exact saved version. Apply this ordering to live, single-video, and batch paths. On index failure, keep the extraction done and surface a separate indexing error.
5. Prevent out-of-order workers from replacing a newer index: compare the source hash/version before promotion, serialize promotion per video, and retry/report a conflict. Saved insight snapshots must remain stable.
6. Existing embeddings have unverified metadata. Determine whether their chunk text/count matches the saved auto insights; mark model provenance unknown unless verified. Do not guess the model merely from dimension. Rebuild incompatible/unknown generations in bounded batches.
7. Add `scripts/repair_index.py` with dry-run default; explicit apply; `--limit`; optional video ID; missing/stale scopes. Print proposed counts without vectors or private text. Do not launch full video extraction to repair embeddings.
8. Separate interactive query retry limits from background embedding retries. Interactive searches should return a clear degraded state promptly; bulk repair can back off longer and resume later.
9. Repair the missing completed videos in bounded batches. Recheck coverage, including partial indexes and malformed source records. Report indexed/eligible and exceptions instead of claiming all 65 are searchable solely from a row count.

Done: injected embedding/insert failure leaves the old index usable; repeated repair is idempotent; auto/manual results stay distinct; every eligible video is current or has a visible actionable exception.

### A3. Connect an actual Search page

Touch: `components/ui_shell.py`, `components/stitch_pages.py`, `components/ui_styles.py`, `search.py`, `db.py`; new `components/knowledge_pages.py`.

1. Add a Search navigation entry and native Streamlit page with a form: query, optional playlist, General/Podcast type, and Search submit. Keep the library filter and label it “Filter videos.”
2. Use a shared `SearchResponse` contract: status (`ok`, `empty`, `degraded`, `error`), hits, coverage, warnings. Empty results and provider failure must look different.
3. Each hit returns source ID, video ID/title/channel, chunk title/text, nullable timestamp, insight variant, source kind, generation/hash, and internal ranking score. UI displays content and provenance; similarity is not a probability or confidence percentage.
4. Apply scope inside retrieval before the final top-k selection. Handle filtered pgvector searches explicitly; small scoped datasets can use exact ranking. Never retrieve ten global hits and then filter them down.
5. Start with semantic retrieval plus a simple parameterized lexical fallback over saved insight text for provider outages and exact names. Label the fallback. Add full hybrid fusion only if evaluation shows a retrieval gap.
6. Fetch titles/metadata in one join or bounded batch. Show up to ten hits, excerpt, source link, Open video, and Save. Preserve query/results when opening a video and returning.
7. Add a native Saved page with collection filter, item detail, personal note editor, and collection membership controls. Suggested collection names are examples, not assumptions about the user's business.
8. Escape retrieved content and restrict rendered links to valid HTTP(S) URLs; build YouTube links server-side from validated video IDs. Unknown timing produces a normal source link.

Done: paraphrase search finds insight text rather than just a title; scope works; missing Gemini configuration produces usable lexical fallback and a visible explanation; save/reopen works in the active UI.

### A4. Make export a real browser download

Touch: `export.py`, `components/ui_shell.py`, new native export view.

1. Change the existing iframe Export action into navigation to an export view, not a server-file mutation.
2. Generate Markdown in memory with `export_video_markdown`; provide a native `st.download_button` with a safe filename and `text/markdown` MIME type.
3. Use the stored `processed_at` for “Extracted”; add a separate export time if useful. The current renderer incorrectly labels the current date as extraction date.
4. Support saved-item and collection Markdown export with source links and personal notes. Export snapshots exactly as saved; do not regenerate them with an LLM.
5. Keep static site export read-only and clearly separate from interactive live features.

Done: a real `.md` file downloads to the browser and contains the expected content, source timestamps when available, and dates. No API call occurs on download.

Release A exit: complete A0–A4 and tests A01–A10 in the acceptance checklist. Demonstrate search → open source → save → add note → reload → download before continuing.

## 5. Release B — Ask and remember

### B1. Persist transcripts without a costly full-library rerun

Touch: `pipeline.py`, `db.py`, `batch_process.py`; new transcript repository helpers.

Add `video_transcripts`: video ID primary key, plain text, timed segments JSON, source, language when known, content hash, fetched timestamp, timing quality, and schema version.

1. Persist transcript data immediately after a successful acquisition, before extraction. Reuse it in normal processing and chat; provide explicit refresh for changed sources.
2. Preserve actual caption segment start/end times when available. The current helper only returns start and text and estimates duration from the last start; update the internal shape carefully and keep compatibility wrappers.
3. For untimed audio transcripts, store unknown timing. Do not invent precise timestamps. Label existing AI-assigned insight timestamps approximate unless verified against real segments.
4. For existing videos, hydrate transcripts on demand or with a bounded worker task. A chat request should show “Transcript not saved yet” and allow acquisition. Avoid repeated transcription on each message.
5. While transcript acquisition is pending/unavailable, allow explicit “Answer from saved insights” mode. Label the evidence scope. Do not imply complete transcript coverage.
6. Add transcript chunk retrieval using a separate table/index so insight `(video_id, chunk_index)` keys cannot collide. Start around 400–700 tokens with roughly 10–15% overlap; preserve source offsets and real timing. These are tuning defaults, not accuracy claims.
7. Index only requested/backfilled transcripts initially. Maintain separate transcript index coverage, source hashes, model/dimension, and atomic replacement semantics from A2.

Done: second chat request uses persisted text; application restart does not require reacquisition; missing captions remain a visible recoverable condition; text from late in a long video can be retrieved.

### B2. Shared cited answering service and persistent conversations

Touch: new `knowledge_chat.py`, `knowledge_store.py`, new native chat UI; reuse `llm.call_deep_llm` and usage tracking.

Add `conversations` (ID, title, scope type/ID, created/updated times) and `chat_messages` (ID, conversation ID, unique request ID with role, role, content, source snapshots JSON, status, created time, usage JSON). Store errors as failed attempts, not invented assistant answers. Preserve message order explicitly.

1. Implement one service for video and library questions. Scope comes from the stored conversation and validated server-side selectors. Never let retrieved text change scope or instructions.
2. Retrieve up to about 30 candidates, deduplicate overlaps, and select a bounded evidence set (starting at 8–12 chunks). Diversify library evidence across relevant videos; do not impose diversity on a single-video question.
3. Prefer original transcript evidence when available. Saved insights may mix transcript material with web research, so label them “saved AI insight”; do not present them as direct transcript quotations. Web research and personal notes must retain their distinct provenance.
4. Build a bounded prompt with the question, a small recent-history window, user preferences, and numbered evidence blocks. Prefer token-aware budgeting; never silently chop the first portion of a long transcript and claim full coverage.
5. Ask for a direct answer, evidence references, material disagreements, and explicit missing evidence. Personal application suggestions must be labeled suggestions, not statements from the videos. Treat source text as untrusted quoted data, including text that attempts to instruct the assistant.
6. Generate citation IDs in code. Have the model return structured answer blocks with citation IDs, then validate IDs against the supplied evidence and render URLs from stored metadata. Unknown citations are not rendered as valid; one bounded repair attempt is acceptable, followed by a clear failure if validation still fails.
7. Validate direct quotes against source text where quotes are produced. Citation existence alone does not prove support; acceptance evaluation must inspect whether the cited passage supports each factual claim.
8. Distinguish zero evidence, weak/partial evidence, and provider failure. Avoid one universal cosine threshold as a claim of truth. Calibrate relevance using the evaluation set and show sources when an answer cannot be supported.
9. Persist a request ID before generation. Duplicate form submission/rerun must reuse the existing request and not create another normal provider call. If a process crashes after a provider response but before save, mark the outcome uncertain and require an explicit retry; exactly-once billing cannot be guaranteed without provider support.
10. Wrap answer generation in the existing usage-tracking lifecycle. Record actual known usage where available; unknown provider cost displays as unknown, never automatically $0. Avoid repeatedly adding the same request to lifetime totals.
11. Add Chat navigation from each video and Ask library from Search. Replace the disabled Chat preview with a working link. Native forms must remain visible and scrollable under the current full-viewport iframe CSS; scope that CSS by page as needed.
12. Show source cards under the answer, allow reopening conversations, and Save answer to a collection. Persist the answer and its exact evidence snapshots even if the source is later reindexed.

Done: both scopes work; answers have inspectable sources; conversations survive restart; unsupported questions get honest limits; repeated rerenders do not trigger another generation. No live web search is added to library chat in this release.

Release B exit: all Release A checks plus B01–B09 pass. This is the minimum useful personal knowledge system. Show it working and identify transcript/index coverage limits honestly.

## 6. Release C — Dependable daily operation

### C1. Durable work queue and truthful progress

Touch: `background_jobs.py`, `poll.py`, `pipeline.py`, `batch_process.py`, queue UI; new `jobs.py` and `worker.py`.

1. Add a jobs table with UUID, job kind, video ID, variant, unique idempotency key, payload, status, attempt count, availability time, lease owner/token, lease expiry, heartbeat time, current stage, error category, and created/updated times.
2. Start with one serial worker. Enqueue idempotently, claim atomically using PostgreSQL row locking or an equivalent SQLite transaction, and process until the queue is empty. Replace the global running flag as the source of truth.
3. Distinguish attempts and stages. A provider call with a long timeout needs a heartbeat independent of that call or a lease longer than its enforced timeout. Never reclaim a healthy long-running transcription.
4. After lease expiry, a new worker may retry safely. Require the current lease token on completion and on publishing results so a stale worker cannot overwrite newer output.
5. Retry transient failures with bounded backoff; make permanent errors actionable. Persist checkpoints needed to reuse a transcript and completed extraction. Batch submissions must persist provider batch IDs and resume collection without duplicate submission.
6. Ensure pasted videos queued during an active job are eventually processed automatically. A “queued” toast without a worker that drains the queue is not success.
7. Refresh queue stage/progress while work is active, not only when the final worker flag clears. Keep status queries small and invalidate affected caches when jobs change.

Done: two workers cannot own the same job; duplicate enqueue makes one active job; interrupted processing resumes safely; a second pasted video is not stranded; progress reflects stored stages.

### C2. Independent scheduling, backups, and release operation

1. Verify the actual hosting URL, deployed commit, access restrictions, and backend. Preserve the intended single-owner access; verify personal data is not exposed to anonymous visitors before entering private notes. Multi-user registration is deferred.
2. Keep Streamlit as the UI. If always-on ingestion is required, configure an independent scheduled worker using the existing deployment resources when possible. A local Windows scheduled task is acceptable if its dependency on the PC being on is explicit.
3. Streamlit Community Cloud hibernates after 12 hours without traffic; browser polling is not proof of unattended execution. See [official hosting documentation](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app).
4. Define a daily backup procedure appropriate to the actual Supabase plan, plus backup before migration. Include database records and any external files separately. Restore a sample into an isolated target and verify saved items/conversations/index counts. See [Supabase backup documentation](https://supabase.com/docs/guides/platform/backups).
5. Add a small health panel: last successful processing, queued/failed counts, insight/transcript index coverage, last worker heartbeat, and last verified backup when known. No made-up healthy status when a check is absent.
6. Pin a tested dependency set, document migrations and startup/worker commands, and run a hosted smoke test on the deployed commit. Record what was tested locally versus on the host.
7. Preserve additive migration compatibility for code rollback. Do not drop new tables during rollback; take recovery actions from the verified backup only when needed.

Done: close the browser, submit/schedule a bounded test job through an authorized entry point, and verify independent worker completion; restore verified; hosted search/chat/save/download checks pass.

## 7. Later improvements, with entry criteria

These are follow-up work, not dependencies of Releases A/B:

- **Apply and review:** extend saved items with `saved`, `to_try`, `tried`, `useful`, optional review date, and outcome note. Add a weekly in-app review of selected items. No automatic messages or schedules unless requested.
- **Standalone personal notes:** make saved notes optionally searchable with explicit “my notes” provenance. A source-derived answer must never silently treat personal opinion as a video claim.
- **Articles and PDFs:** introduce a general sources model only when adding the first non-video input. Preserve author/URL/date, extraction provenance, page numbers, and supported file limits. Reuse retrieval/citation contracts.
- **Cross-video comparisons:** provide a guided comparison after Ask library reliably retrieves diverse evidence and surfaces disagreements.
- **Hybrid search and reranking:** add after failed evaluation cases justify it; measure improvement on the same questions before adopting it.
- **Knowledge graph, external Notion/Obsidian sync, automatic digests, frontend rewrite:** consider only after regular personal use exposes a concrete need.

## 8. Implementation order and suggested file ownership

Execute sequentially unless the user separately requests parallel work:

1. A0: baseline, health command, recovery evidence.
2. A1: migrations, profile, collections, saved items.
3. A2: atomic index promotion, correct extraction ordering, bounded repair.
4. A3 and A4: usable Search/Saved pages and real downloads. Show Release A.
5. B1: persistent transcripts and bounded transcript retrieval.
6. B2: shared answer service, conversations, citations, working chat. Show Release B.
7. C1 and C2: durable jobs, independent scheduling, hosted reliability.

Keep modules small enough to understand:

- `db.py` / `dbconn.py`: existing low-level connection and video/embedding interfaces.
- `knowledge_store.py`: new settings, collection, saved-item, transcript and conversation persistence; split only if it becomes unwieldy.
- `migrations.py`: versioned additive migrations, called once at startup or explicitly by CLI.
- `search.py`: shared retrieval contracts and safe indexing; preserve compatibility wrappers for old callers.
- `knowledge_chat.py`: evidence selection, prompting, citation validation, answer orchestration.
- `components/knowledge_pages.py`: native Search, Saved, Chat and export pages.
- `jobs.py` / `worker.py`: Release C only.
- `scripts/knowledge_health.py` / `scripts/repair_index.py`: safe operational commands with `--help` and clear exit codes.
- `tests/`: focused persistence, retrieval, citation, failure-recovery, and rerun tests.

These filenames are proposed implementation targets, not files already created by this plan. Reuse equivalent existing helpers if present; do not leave duplicate active implementations.

## 9. Verification and performance

Use [ACCEPTANCE.md](docs/knowledge-system/ACCEPTANCE.md) as the release gate. Record pass/fail/block with evidence in [BUILD_STATUS.md](docs/knowledge-system/BUILD_STATUS.md).

Proposed targets, to measure rather than claim in advance:

- Warm list navigation: under 1 second in the target environment; record cold starts separately.
- Search: median under 3 seconds across ten submitted queries, excluding cold startup; separately report provider wait, database work, and rendering.
- Answer generation: visible progress promptly and completion typically within 20 seconds; configure bounded provider timeouts and report actual distribution. Provider failure must leave a retryable saved request.
- Profile/save operations: no provider call; one successful commit per submission.
- New routes must retain light list queries, avoid loading all transcript bodies/vectors, and avoid rendering every detail pane.

Do not block a useful release on cosmetic polish. Do block it on lost saved data, destructive index replacement, broken main navigation, falsely cited answers, hidden provider failures, or unverified data migrations.

## 10. Documentation and next-model handoff

After each task, update the status file with changed files, commands/checks run, results, remaining limitations, and the exact next task. Record schema versions and relevant commit IDs. Never mark planned work complete from code inspection alone.

The next implementation model starts with [IMPLEMENTATION_HANDOFF.md](docs/knowledge-system/IMPLEMENTATION_HANDOFF.md). The later stronger-model review should examine actual changes and evidence, not repeat the entire planning exercise. Its prompt is included there.

Implementation references consulted for this plan:

- Use [Streamlit forms](https://docs.streamlit.io/develop/concepts/architecture/forms) to submit groups of widget values together and avoid generation during ordinary input changes.
- Use the [native download widget](https://docs.streamlit.io/knowledge-base/using-streamlit/how-download-file-streamlit) for browser downloads.
- Check installed extension/version behavior against [pgvector's official filtering documentation](https://github.com/pgvector/pgvector#filtering); approximate indexes can underfill filtered results. Verify scoped retrieval with real tests rather than assuming a WHERE clause guarantees full recall.

This plan specifies product and engineering choices; it does not create a schedule, deploy code, change models, or spend provider credits.
