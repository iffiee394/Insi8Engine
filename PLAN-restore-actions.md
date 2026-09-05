# PLAN-restore-actions — Restore the core product loop in the new iframe UI

**Rank: 1 of 5 (do this first).** Without it, the product cannot process videos from the UI at all.

## Goal

The app was recently migrated from classic Streamlit widgets to "Option D" pages: each screen is a complete HTML document rendered inside `st.components.v1.html()` iframes (see Architecture below). The migration dropped every **action**: there is no way to poll playlists, process a pending video, retry a failed one, or write a podcast agenda from the new UI. The backend for all of these already exists and works. After this plan, all of those actions are clickable again from the Library page, and the "Queue" tab shows a real queue instead of a copy of the Library.

## Architecture you must understand first (read before coding)

- Entry point: `app.py` calls `render_app(ctx)` in `components/ui_shell.py`.
- `ui_shell.py` reads `st.query_params` in `_read_query_params()`, mutates session state / DB, then routes to a renderer in `components/stitch_pages.py` based on `page`.
- Each renderer builds one giant HTML string and calls `components.html(html, height=900)`. **No Streamlit widgets are used on these pages.**
- The ONLY channel from the iframe back to Python is the parent URL. Inside the iframe, JS calls `_nav({page:'library', ...})` (defined in `_NAV_BRIDGE` in `stitch_pages.py`), which sets `window.parent.location.search`, causing a full Streamlit rerun where `_read_query_params()` sees the new params.
- Existing example of this action pattern: the Settings save (`action=save`) handler in `ui_shell.py::_read_query_params()`. Copy its style.

## Backend functions that already exist (do NOT rewrite them)

| Function | File | What it does |
|---|---|---|
| `start_poll_background()` | `background_jobs.py` | Spawns `poll.py` as a detached subprocess. Returns `(ok, msg)`. Refuses if a worker is already running. |
| `start_process_one_background(video_id, manual=False)` | `background_jobs.py` | Spawns `poll.py --one <vid>` (add `--manual` when `manual=True`). |
| `is_worker_running()` | `background_jobs.py` | True while a worker subprocess runs (flag in DB meta `poll_worker_running`). |
| `db.upsert_video(video_id, status=..., error_message="", user_agenda=...)` | `db.py` | Keyword-only partial update of a video row. |

Status constants in `db.py`: `STATUS_PENDING="pending"`, `STATUS_AWAITING_AGENDA="awaiting_agenda"`, `STATUS_PROCESSING="processing"`, `STATUS_DONE="done"`, `STATUS_FAILED="failed"`, `STATUS_BATCH_QUEUED="batch_queued"`.

The exact action recipes, copied from the legacy code in `app.py` lines ~638–697 (that legacy code is dormant but correct — use it as reference, do not delete it):

- **Process now** (pending or awaiting_agenda): `db.upsert_video(vid, status=db.STATUS_PENDING, error_message="")` then `start_process_one_background(vid)`.
- **Retry** (failed): same as Process now.
- **Re-process** (done): same as Process now.
- **Reset stuck** (processing): `db.upsert_video(vid, status=db.STATUS_PENDING, error_message="")` only — do NOT spawn.
- **Generate custom insights** (podcast, agenda text non-empty): `db.upsert_video(vid, user_agenda=agenda_text, status=db.STATUS_PENDING, error_message="")` then `start_process_one_background(vid, manual=True)`.
- **Poll playlists**: `start_poll_background()`.

## Files to touch, in order

### Step 1 — `components/ui_shell.py`: handle action params

In `_read_query_params()`, after the existing settings-save block, add:

```python
action = params.get("action", "")
vid = params.get("vid", "")
if action == "poll":
    from background_jobs import start_poll_background
    ok, msg = start_poll_background()
    st.query_params.clear()
    if page: st.query_params["page"] = page
    if vid: st.query_params["vid"] = vid
    st.toast(msg)
elif action == "process" and vid:
    db.upsert_video(vid, status=db.STATUS_PENDING, error_message="")
    from background_jobs import start_process_one_background
    ok, msg = start_process_one_background(vid)
    st.query_params.clear()
    st.query_params["page"] = page or "library"
    st.query_params["vid"] = vid
    st.toast(msg)
elif action == "reset" and vid:
    db.upsert_video(vid, status=db.STATUS_PENDING, error_message="")
    st.query_params.clear()
    st.query_params["page"] = page or "library"
    st.query_params["vid"] = vid
elif action == "set_agenda" and vid:
    agenda = params.get("agenda", "").strip()
    if agenda:
        db.upsert_video(vid, user_agenda=agenda, status=db.STATUS_PENDING, error_message="")
        from background_jobs import start_process_one_background
        ok, msg = start_process_one_background(vid, manual=True)
        st.toast(msg)
    st.query_params.clear()
    st.query_params["page"] = page or "library"
    st.query_params["vid"] = vid
```

**Trap:** you MUST clear the action param after handling, otherwise it re-fires on every rerun (including the automatic rerun the queue-tick fragment triggers when the worker finishes). But `st.query_params.clear()` also wipes `page` and `vid`, so re-set them as shown.

### Step 2 — `components/stitch_pages.py`: action buttons in `_detail_pane(video)`

`_detail_pane()` currently shows real content only for `STATUS_DONE`; every other status collapses to one line ("Processing queued."). Replace that `else` branch with status-specific blocks. Add these JS-callable helpers to the page script in `render_library_page` (next to `selectVideoLocal`):

```js
function actProcess(vid) { _nav({page:'library', vid: vid, action:'process'}); }
function actReset(vid)   { _nav({page:'library', vid: vid, action:'reset'}); }
function actAgenda(vid) {
  var t = document.getElementById('agenda-input-' + vid);
  if (!t || !t.value.trim()) { alert('Write your agenda first.'); return; }
  _nav({page:'library', vid: vid, action:'set_agenda', agenda: t.value.trim().slice(0, 1500)});
}
```

Per status render in the detail pane body:

- `pending` → button "Process now" calling `actProcess('{vid_id}')`, styled like the existing Export button (`bg-on-secondary-fixed-variant text-white px-3 py-1.5 rounded-lg`).
- `failed` → show `video.get("error_message")` (escape with `_e()`) in a red-bordered card + "Retry" button calling `actProcess`.
- `processing` → animated spinner note ("Processing — updates automatically") + small "Reset stuck" link calling `actReset`.
- `awaiting_agenda` (podcasts) → a `<textarea id="agenda-input-{vid_id}">` prefilled with `_e(video.get("user_agenda") or "")` + "Generate insights" button calling `actAgenda`. Style the textarea like the chat textarea at the bottom of `_detail_pane`.
- `done` **and** `video.get("playlist_type") == "podcast"` → also add a collapsed `<details>` block "Custom agenda override" containing the same textarea + button (this is regeneration with a new agenda).

**Trap:** these panes are embedded twice — once inline and once inside the `details_json` JSON blob used by `selectVideoLocal`. Element IDs therefore must include the video id (as shown) so they stay unique, and the buttons must work after an `innerHTML` swap — which they do because they use inline `onclick` with global functions. Do NOT use `addEventListener` on load.

**Trap:** the whole page is built with f-strings. Any literal `{` or `}` in JS you add inside an f-string must be doubled (`{{`, `}}`). The JS above goes in the existing `<script>` block of `render_library_page`, which is already inside an f-string.

### Step 3 — `components/stitch_pages.py`: Poll button + worker indicator in the top bar

Change `_topbar_library_html(active_tab)` to `_topbar_library_html(active_tab, worker_running: bool)`. Before the search input, add:

- If `worker_running` is False: button `Poll playlists` with a `sync` material icon, `onclick="_nav({page:'library', action:'poll'})"` — remember `{{ }}` doubling.
- If True: a non-clickable pill with a spinning `sync` icon (`style="animation:spin 1s linear infinite"`) and text "Processing…".

Update both call sites (`render_library_page` builds the topbar; pass a new `worker_running` parameter through from `ui_shell.py`, obtained via `is_worker_running()`). The queue-tick fragment in `ui_shell.py` already triggers `st.rerun()` when the worker finishes, which refreshes statuses automatically.

### Step 4 — `components/stitch_pages.py` + `ui_shell.py`: real Queue tab

In `ui_shell.py`, the `page == "queue"` branch currently passes all videos. Change it to pass only active ones, ordered: processing first, then pending/batch_queued, then awaiting_agenda, then failed:

```python
order = {db.STATUS_PROCESSING: 0, db.STATUS_PENDING: 1, db.STATUS_BATCH_QUEUED: 1,
         db.STATUS_AWAITING_AGENDA: 2, db.STATUS_FAILED: 3}
queue_videos = sorted([v for v in all_videos if v["status"] in order], key=lambda v: order[v["status"]])
```

Pass `queue_videos` to `render_library_page(..., active_tab="queue")`. In `render_library_page`, when `active_tab == "queue"`, change the aside header label from `Library ({count})` to `Queue ({count})`, and when the list is empty render an empty state: "Queue is clear — everything processed." with a link back to Library (`onclick="goPage('library')"`).

### Step 5 — `components/stitch_pages.py`: `_status_badge` coverage

`_status_badge()`'s `cfg` dict is missing `awaiting_agenda` and `batch_queued`. Add:
- `db.STATUS_AWAITING_AGENDA: ("#c6bfff", "edit_note", "Needs agenda", "")`
- `db.STATUS_BATCH_QUEUED: ("#5C5C70", "pending", "Queued", "")`

## Edge cases a weaker model would miss

1. **Action params re-fire.** Every Streamlit rerun re-reads query params. If you forget to clear `action`, clicking "Process now" once will re-enqueue the video on every rerun forever, and `start_poll_background` will spam toasts. Clear + re-set `page`/`vid` exactly as in Step 1.
2. **Worker single-flight.** `_spawn()` refuses to start when `poll_worker_running == "1"`. If a worker crashed hard, the flag can stay stuck at "1"; the "Reset stuck" action covers the video status, and `poll.py` clears the flag on start/finish. Don't add your own flag logic.
3. **`upsert_video` keyword semantics.** `status=None` means "keep existing"; empty string `""` for `error_message` actively clears it. Pass exactly what the recipes above say.
4. **Agenda text through a URL.** The agenda travels as a query param. `URLSearchParams` (used by `_nav`) percent-encodes it correctly, including newlines, and Streamlit decodes it automatically — do NOT decode again in Python. Cap at 1500 chars in JS (`.slice(0,1500)`) to stay under URL length limits.
5. **Two copies of every pane.** Any HTML you add to `_detail_pane` is serialized into the `details_json` blob. That blob already guards against `</script>` breakage via `.replace("</", "<\\/")` — keep that line intact.
6. **`db.PLAYLIST_PODCAST`** is the constant for podcast type (value `"podcast"`); compare with `video.get("playlist_type")`.

## Do not touch

- `transcriber.py`, `youtube_monitor.py` — explicitly off-limits.
- `poll.py`, `pipeline.py`, `background_jobs.py`, `db.py` — no changes needed; only call them.
- Legacy render functions in `app.py` — dormant reference code; leave them.
- New work must not break or restructure existing files or the working pipeline. Extend, don't rewrite.

## Acceptance criteria

Run `cd "D:\Cursor Projects\CursorP1"; python -m streamlit run app.py`, open http://localhost:8501.

1. Top bar shows a **Poll playlists** button; clicking it shows a toast and the button becomes a spinning "Processing…" pill until the worker finishes.
2. Selecting a **failed** video shows its error message and a **Retry** button; clicking Retry flips it to pending and processing starts (list badge changes within ~3 s via the auto-refresh).
3. Selecting a **pending** video shows **Process now**; clicking it starts processing that one video.
4. A podcast video with status **Needs agenda** shows an agenda textarea; typing bullets and clicking **Generate insights** starts processing, and after completion the insights reflect the agenda.
5. A **done** podcast video has a collapsed "Custom agenda override" section that regenerates custom insights without erasing the general ones.
6. The **Queue** tab lists only non-done videos ordered processing → pending → needs-agenda → failed, and shows "Queue is clear" when empty.
7. Clicking any action does not repeat itself on subsequent interactions (check `poll_worker.log` for duplicate "--- worker started ---" lines; there must be exactly one per click).
