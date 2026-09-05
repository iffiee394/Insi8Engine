# PLAN-playlist-manager — Wire playlist creation and editing into the new iframe UI

**Rank: 5 of 5.** Playlists are the product's ONLY input; today they can't be created or edited from the new UI.

## Goal

The Playlists page (`components/stitch_pages.py::render_playlists_page`) renders real playlists from the DB, but every control is dead: the "Add Playlist" top-bar button does nothing, the "Create New Playlist" dashed card just navigates to Settings, and the "Extraction Focus" boxes are not editable. The DB layer is complete: `db.upsert_playlist(playlist_id, *, name, description, kind, profile_json, extraction_focus, enabled)`, `db.delete_playlist(playlist_id)`, `db.list_playlists()` (verified in `db.py:218–300`). `poll.py` already polls whatever is in the playlists table. After this plan, users can add a playlist (ID + name + kind), edit its extraction focus, and disable/delete it — all from the Playlists page.

## Architecture context

- Pages are complete HTML documents rendered via `st.components.v1.html()` iframes ("Option D"), built in `components/stitch_pages.py`. No Streamlit widgets.
- The only iframe→Python channel is the parent URL: JS `_nav({...})` (defined in `_NAV_BRIDGE`) sets `window.parent.location.search`; `components/ui_shell.py::_read_query_params()` handles action params on the rerun. Follow the existing `action=save` (settings) handler as the pattern: handle, then `st.query_params.clear()` and re-set `page` — otherwise the action re-fires on every rerun.
- Playlist `kind` values: `db.PLAYLIST_GENERAL` (`"general"`, auto-processes new videos) and `db.PLAYLIST_PODCAST` (`"podcast"`, videos wait for an agenda). Check the exact constant names at the top of `db.py` before use.

## Files to touch, in order

### Step 1 — `components/ui_shell.py`: playlist action handlers

In `_read_query_params()` add:

```python
if page == "playlists":
    action = params.get("action", "")
    pl_id = params.get("pl", "").strip()
    if action == "add_playlist" and pl_id:
        db.upsert_playlist(
            pl_id,
            name=params.get("name", "").strip() or pl_id,
            kind=params.get("kind", db.PLAYLIST_GENERAL),
            extraction_focus=params.get("focus", "").strip(),
        )
        st.query_params.clear(); st.query_params["page"] = "playlists"
        st.toast("Playlist added — it will be picked up on the next poll.")
    elif action == "save_focus" and pl_id:
        db.upsert_playlist(pl_id, extraction_focus=params.get("focus", "").strip())
        st.query_params.clear(); st.query_params["page"] = "playlists"
        st.toast("Extraction focus saved.")
    elif action == "toggle_playlist" and pl_id:
        pl = db.get_playlist(pl_id)
        if pl:
            db.upsert_playlist(pl_id, enabled=not bool(pl.get("enabled", 1)))
        st.query_params.clear(); st.query_params["page"] = "playlists"
    elif action == "delete_playlist" and pl_id:
        db.delete_playlist(pl_id)
        st.query_params.clear(); st.query_params["page"] = "playlists"
        st.toast("Playlist removed. Its videos stay in the library.")
```

**Known trap in `upsert_playlist`:** on UPDATE it uses `COALESCE(NULLIF(?, ''), ...)` for most text columns, meaning **you cannot blank out a name or focus by passing ""** — empty string means "keep existing". For `save_focus` where the user genuinely cleared the box, pass a single space `" "` is WRONG (it stores a space); instead, accept this limitation and document it in the UI placeholder ("leave text to keep focus"), OR add a tiny targeted UPDATE in `db.py` guarded as a new function `set_playlist_focus(playlist_id, focus)` that writes the value unconditionally. Prefer the new small function — do not change `upsert_playlist` semantics (other callers rely on them).

### Step 2 — `components/stitch_pages.py`: Add Playlist modal

In `render_playlists_page`, add a hidden modal (plain HTML/JS, no libraries) at the end of `<body>`:

- Overlay: `position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:100;display:none` with id `add-modal`.
- Panel: centered card (`bg-surface border border-border rounded-xl p-5 w-[420px]`) containing:
  - Input `id="pl-id"` — label "YouTube Playlist ID", placeholder `PLxxxxxxxx...`.
  - Input `id="pl-name"` — label "Display name".
  - Select `id="pl-kind"` — options `general` ("General — process automatically") and `podcast` ("Podcast — wait for my agenda").
  - Textarea `id="pl-focus"` — label "Extraction focus (optional)".
  - Buttons: "Create" → `submitAddPlaylist()`, "Cancel" → hide modal.
- Script (double all literal braces if placed inside an f-string):

```js
function openAddModal() { document.getElementById('add-modal').style.display = 'flex'; }
function closeAddModal() { document.getElementById('add-modal').style.display = 'none'; }
function submitAddPlaylist() {
  var id = document.getElementById('pl-id').value.trim();
  if (!/^[A-Za-z0-9_-]{10,60}$/.test(id)) { alert('That does not look like a playlist ID.'); return; }
  _nav({page:'playlists', action:'add_playlist', pl:id,
        name: document.getElementById('pl-name').value.trim().slice(0,80),
        kind: document.getElementById('pl-kind').value,
        focus: document.getElementById('pl-focus').value.trim().slice(0,800)});
}
```

Wire it: the top-bar "Add Playlist" button gets `onclick="openAddModal()"`, and change the dashed "Create New Playlist" card's `onclick` from `goPage('settings')` to `openAddModal()`.

### Step 3 — `components/stitch_pages.py`: editable extraction focus per card

In `_playlist_card(pl, video_count, is_first)`:

1. Replace the static focus `<p>` with a textarea `id="focus-{playlist_id}"` prefilled with `_e(focus)`, styled like the current box (`bg-[#0F0F1A] border border-border p-3 rounded-lg w-full text-[13px] resize-none`), `rows="3"`.
2. Below it, a small "Save focus" button, initially `opacity-0` and revealed via `oninput` on the textarea (`this.nextElementSibling.style.opacity=1` or a small helper), calling:
   `_nav({page:'playlists', action:'save_focus', pl:'<playlist_id>', focus: document.getElementById('focus-<playlist_id>').value.trim().slice(0,800)})`.
3. Add a small overflow row (top-right of the card, next to the existing expand icon): an `eye`/`visibility_off` toggle calling `toggle_playlist`, and a `delete` icon that calls `if (confirm('Remove this playlist? Videos stay in the library.')) _nav({...action:'delete_playlist'...})`.

Playlist IDs contain only `[A-Za-z0-9_-]`, so they are safe to embed directly in JS single-quoted strings and element IDs — still pass them through `_e()` for consistency.

### Step 4 — show disabled state

`db.list_playlists()` returns all playlists including disabled ones (`enabled` column). In `_playlist_card`, when `pl.get("enabled") in (0, False)`: add `opacity-50` to the card and a small "DISABLED" chip next to the video count. Verify how `poll.py` filters (it uses `list_playlists(enabled_only=True)` — confirm by grepping `enabled_only` in `poll.py`) so users understand disabled = not polled.

## Edge cases a weaker model would miss

1. **`upsert_playlist` cannot blank fields** (COALESCE/NULLIF pattern — see Step 1). Add `set_playlist_focus()` rather than fighting it.
2. **Action params re-fire on every rerun.** Always `st.query_params.clear()` then re-set `page` after handling — the settings-save handler in the same file shows the pattern.
3. **The "first card is active" styling** in `render_playlists_page` (`is_first`) is cosmetic, not data-driven. Adding a playlist reorders nothing meaningful; don't try to preserve "active" semantics.
4. **Playlist ID validation is client-side only.** A junk ID won't crash anything — `poll.py` will log a YouTube API error for it — but the regex gate in `submitAddPlaylist` prevents most typos. Don't add server-side YouTube validation (needs an API call; out of scope).
5. **Deleting a playlist does not delete its videos** (no FK cascade; videos keep their `playlist_id` string). The confirm dialog wording reflects that — keep it accurate.
6. **URL length for focus text.** Cap at 800 chars in JS. Longer focus text should be edited in shorter form; do not raise the cap above ~1500.
7. **f-string brace doubling.** The modal script and inline handlers contain `{}`. Inside f-strings, double them. If the modal HTML is a plain (non-f) string constant, single braces are fine — be deliberate about which you use.

## Do not touch

- `transcriber.py`, `youtube_monitor.py`.
- `poll.py`, `pipeline.py` — they already read playlists from the DB; no changes.
- `db.upsert_playlist` semantics (only ADD a new `set_playlist_focus` function if needed).
- Settings page save flow (separate concern).
- New work must not break or restructure existing files or the working pipeline. Extend, don't rewrite.

## Acceptance criteria

Run `cd "D:\Cursor Projects\CursorP1"; python -m streamlit run app.py`, open http://localhost:8501/?page=playlists.

1. Clicking **Add Playlist** (top bar) or the dashed card opens a modal; entering a real playlist ID + name + kind and clicking Create shows a toast and the new card appears in the grid.
2. Entering an obviously invalid ID (e.g. `hello`) is blocked client-side with an alert.
3. Editing a card's extraction focus reveals a Save button; clicking it persists — verify by refreshing the page and with `python -c "import db; print([p['extraction_focus'] for p in db.list_playlists()])"`.
4. The eye toggle greys out a card with a DISABLED chip; running `python poll.py` skips that playlist (check console/log output lists only enabled playlists).
5. Delete asks for confirmation, removes the card, and the playlist's existing videos still appear in the Library.
6. After every action above, idling 10+ seconds does not repeat the action (no duplicate toasts, no duplicate rows).
7. A newly added playlist gets picked up by **Poll playlists** and its videos appear with the correct behavior for its kind (general → auto-process; podcast → Needs agenda).
