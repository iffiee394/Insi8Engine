# Build status — personal knowledge system

Updated: 2026-09-12.
Current state: **Release A/B feature code is implemented and deployed to Streamlit at https://insi8engine-33.streamlit.app/. Full release acceptance remains incomplete. The minimal homepage and reading UI have been checked locally, and hosted Home, Library, Saved, Search, Ask library, and Add video load without tracebacks. Live provider search/chat should be retested after the API key is replaced. PostgreSQL recovery remains unverified.**
Baseline commit reviewed: `76f6a63`.

## Evidence already collected

- Live read-only PostgreSQL health (2026-09-12): 66 videos, 65 done, 1 failed, 2 playlists.
- 426 embeddings across 47 videos. 18 done videos are **ineligible** (empty structured insights), not missing embeddings of usable insight text. 47 indexed videos are unverified/unknown-model until bounded repair.
- Failed video `JpaK3F7fLHE` classified as **quota**. Recoverable, but not auto-retried (would spend provider credits).
- Additive migrations applied to the configured PostgreSQL store via normal `db.init_db()`; schema_version 4. Video/playlist/embedding counts unchanged after migration.
- Disposable PostgreSQL target: **blocked** (`TEST_DATABASE_URL` unset). SQLite migration/index/save/chat tests were not substituted as PostgreSQL evidence.
- Hosted Home, Library, Saved, Search, Ask library, and Add video pages loaded on Streamlit after deploy commit `9717276`; access controls, backups, independent scheduling, provider calls after key rotation, and latency were not fully verified.
- Existing unrelated untracked visual assets and content deliverables were left untouched.

## Execution checklist

- [ ] A0 — baseline and health tool done; only local SQLite backup/restore verified, configured PostgreSQL recovery remains unverified.
- [x] A1 — durable profile, collections, saved-item snapshots.
- [x] A2 — atomic indexing, consistent publication, bounded repair.
- [x] A3 — connected Search and Saved pages.
- [x] A4 — actual browser downloads.
- [ ] Release A full acceptance. AppTest/live embeddings and local UI checks exist; PostgreSQL migration/recovery and remaining browser gates are incomplete.
- [x] B1 — durable transcripts and scoped transcript retrieval.
- [x] B2 — cited video/library chat and persistent conversations.
- [ ] Release B full acceptance. AppTest/live Gemini evidence exists; full evidence-quality and hosted acceptance are incomplete.
- [ ] C1 — durable jobs, ownership, retries, queue drain.
- [ ] C2 — independent scheduling, verified backups and hosted operation.
- [ ] Release C acceptance.

## How to run

```
.venv\Scripts\python.exe scripts\knowledge_health.py
.venv\Scripts\python.exe -m unittest discover -s tests
.venv\Scripts\python.exe -m streamlit run app.py
```

The app now opens Home. Search, Library, and Saved use quiet text navigation; Ask library, Queue, Playlists, and Settings are under More. Profile edits are in Settings. Export opens a browser download page. The library rail's IE/Home button returns to Home.

Repair (dry-run default):

```
.venv\Scripts\python.exe scripts\repair_index.py --scope missing --limit 5
.venv\Scripts\python.exe scripts\repair_index.py --apply --scope missing --limit 5
```

## Record each completed task here

### 2026-09-12 — A0 complete (local + live read-only)

- Result: complete for health/backup/sqlite restore; PostgreSQL disposable restore blocked.
- Files: `knowledge_health.py`, `scripts/knowledge_health.py`, `tests/test_knowledge_a0.py`.
- Commands: `python scripts/knowledge_health.py` against configured Postgres; `--backup-local` copied profile.json, knowledge_base.txt, local insights.db to `data/backups/20260912T125805Z` (gitignored). Restore of that SQLite copy compared equal counts.
- Environment: Python 3.14.7, Streamlit 1.58.0, backend postgres (host hidden).
- Next: A1.

### 2026-09-12 — A1 complete (sqlite tests + additive live migration)

- Result: complete on disposable SQLite; live Postgres received additive tables only.
- Files: `migrations.py`, `knowledge_store.py`, `db.py` profile redirect.
- Schema version before/after on configured store: None → 4 (A1–B2 tables shipped together as versions 1–4).
- Tests: profile custom keys survive; stale file cannot overwrite DB; save twice = one item; two collections; remove membership keeps item.
- Next: A2.

### 2026-09-12 — A2 complete (sqlite failure-injection)

- Result: complete on disposable SQLite. No bulk reindex of the personal library.
- Files: `search.py` (`insights_to_chunks`, `replace_auto_index` path), `db.py` atomic replace, `pipeline.py` no longer indexes before save, `poll.py` / `batch_process.py` index after save, `scripts/repair_index.py`.
- Tests: injected insert failure keeps old generation; stale `expected_generation` rejected.
- Next: A3/A4.

### 2026-09-12 — A3/A4 implemented, browser e2e not run

- Result: partial vs acceptance A09/A10 (no browser session).
- Files: `components/knowledge_pages.py`, `components/ui_shell.py`, `components/stitch_pages.py`, `export.py`.
- Library search box relabeled “Filter videos”. Native Search form calls `search_insights_response`. Export action navigates to a download page; Markdown uses `processed_at` for Extracted.
- Next: B1/B2.

### 2026-09-12 — B1/B2 implemented, live chat e2e not run

- Result: partial vs acceptance B01–B09 (mocked LLM/provider in tests).
- Files: `knowledge_chat.py`, transcript persist in `pipeline.fetch_transcript_data`, conversation tables in `knowledge_store.py`.
- Tests: unknown citations dropped; rerun with same request_id does not call the model again; video scope cannot include another video id; YouTube URLs validated; untimed export has no invented `&t=`.
- Tests now force `GEMINI_API_KEY=""` so they do not call live embeddings.

### 2026-09-12 — A09/B09 walkthrough (AppTest, live providers)

- Command: `.venv\Scripts\python.exe scripts\acceptance_walkthrough.py`
- Result: **PASS**
- Search: semantic `ok`, 10 hits, 27.18s (Gemini embeddings HTTP 200). Query kept in session state. Open video + source link widgets present. The iframe library itself was not opened (AppTest crashes on that page’s widget tree).
- Save: collection `Acceptance 2026-09-12` created via form; one item saved with a personal note; note later edited on Saved.
- Download: export page rendered `st.download_button` (1 widget). AppTest could not read the file bytes (`widget_len=0`); the on-page Markdown preview (964 chars) and `export_saved_item_markdown` (965 chars) both contained the personal note. No LLM call on download.
- Chat: library scope form submit; Gemini Flash HTTP 200; assistant status `ok`, 1 validated citation, 38.99s.
- HTTP smoke: Streamlit `http://localhost:8501/?page=search|saved|chat|export` all 200.
- Unit tests still 14 OK after scoping the 3s queue tick to iframe pages only.
- Not verified: hosted URL, CSS at a narrow viewport, clicking Open video inside the Stitch iframe.

## Remaining / next exact action

1. Finish the remaining acceptance gates; hosted core pages load, but a full hosted search/chat/save/download walkthrough remains unverified after API key rotation.
2. Do not bulk-repair the 47 unverified embeddings until you choose a bounded `--apply` batch.
3. Failed video `JpaK3F7fLHE` is a quota error — retry only that video when quota is available.
4. Disposable PostgreSQL migration/index evidence is still blocked.
5. Release C (durable jobs / unattended worker) is not started.

### 2026-09-12 — Current-state review and minimal interface

- Added Home: one search field, a link to Ask library, four recent completed videos. No detail fetch or worker polling on Home; failed videos are not auto-selected when opening Library.
- Replaced seven native navigation buttons with text navigation and More. Added a compact native Add video page and moved profile editing to Settings.
- Collapsed filters, full search excerpts, save forms, saved-item editing, conversation history, and download preview. Removed similarity scores and backend explanations from normal search results while retaining failure states and source labels.
- Library insights now open individually; processing focus/cost is behind Processing details. Repeated Done badges removed from library rows. Underlying content remains available.
- Files: `components/knowledge_pages.py`, `components/ui_shell.py`, `components/stitch_pages.py`, `tests/test_minimal_home.py`.
- Verification: 17 unit/AppTest tests passed; `git diff --check` passed. New tests prove Home does not retrieve heavy details or poll workers, search submits once and retains results on rerun, and Saved does not load the profile editor. Provider search is mocked in these new tests; no new live generation performed.
- Local browser: homepage desktop and 390×844 layout inspected; no horizontal overflow at 390px. Recent-video link opened the correct selected video. Browser verification is local, not hosted deployment evidence.
- Read-only PostgreSQL health unchanged: 66 videos (65 done/1 quota failure); 47 eligible structured sources, all 47 embedding models unverified; 18 completed videos ineligible because structured insights are empty. No database repair or provider model change in this UI task.
- Corrected top-level completion claims: PostgreSQL restore was never proven by the SQLite restore. Full Release A/B gates remain open; Release C is not started.

### 2026-09-12 — Streamlit deployment

- Commit `9717276` pushed to `origin/main`; Streamlit app woke successfully at `https://insi8engine-33.streamlit.app/`.
- Hosted pages checked without tracebacks: Home, Library, Saved, Search, Ask library, Add video.
- Hosted Library read live PostgreSQL data: 66 videos, 65 processed, 1 failed, and the collapsed reading interface rendered.
- Not retested yet: live hosted provider calls after API key rotation, download bytes, private access restrictions, backups/recovery, and unattended worker behavior.
