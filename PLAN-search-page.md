# PLAN-search-page — Build the Search page over the existing semantic search backend

**Rank: 4 of 5.** The nav rail already has a Search button that leads nowhere; the backend is done.

## Goal

Clicking the magnifier icon in the left nav rail navigates to `?page=search`, but `components/ui_shell.py` has no `search` route, so it falls through to the Library. The semantic search backend is complete and battle-tested: `search.py::search_insights(query, top_k=10)` embeds the query with Gemini and ranks stored insight chunks by cosine similarity, returning `[{video_id, chunk_title, chunk_text, timestamp_seconds, score}]`. The top bar's "Search library..." input on the Library page is also dead. After this plan: a real Search page in the Stitch style, reachable from the rail and the top bar, with ranked results that jump to the right video (and YouTube moment).

## Architecture context

- Pages are complete HTML documents rendered via `st.components.v1.html(html, height=900)` in iframes ("Option D"), built in `components/stitch_pages.py`. No Streamlit widgets on pages.
- The only iframe→Python channel is the parent URL: JS `_nav({...})` (in `_NAV_BRIDGE`) sets `window.parent.location.search`; `ui_shell.py::_read_query_params()` + routing handle the rerun.
- Shared building blocks in `stitch_pages.py` you must reuse: `_COMMON_HEAD` (Tailwind config + fonts), `_rail_html(active)` (pass `"search"` so the magnifier is highlighted), `_NAV_BRIDGE`, `_e()` (escape), `_fmt_ts()` (timestamp label), `_yt_url(video_id, seconds)`.

## Files to touch, in order

### Step 1 — `components/ui_shell.py`: route

In `render_app`, add a branch before the final `else`:

```python
elif page == "search":
    from search import search_insights
    query = st.query_params.get("q", "").strip()
    results = search_insights(query) if query else []
    from components.stitch_pages import render_search_page
    render_search_page(query, results, all_videos)
```

`all_videos` already exists in `render_app`. Do NOT clear the `q` param — search is idempotent and keeping it in the URL makes results shareable/refreshable. (Cost note: each rerun with `q` re-embeds the query — one cheap embedding call, acceptable.)

### Step 2 — `components/stitch_pages.py`: `render_search_page(query, results, all_videos)`

Build the page from these parts:

1. `_rail_html("search")`.
2. A top bar modeled on `_topbar_library_html` but with the title "Search" and nav links Queue/Library/Playlists (all inactive, `onclick="goPage('...')"`). No search box in the top bar on this page.
3. Main content, `ml-[56px] pt-14`, centered column `max-w-3xl mx-auto p-6`:
   - **Hero search input**: large input (`text-[15px] py-3 pl-11`), magnifier icon inside, prefilled with `value="{_e(query)}"`, `id="search-q"`, `autofocus`. Submit on Enter:
     `onkeydown="if(event.key==='Enter'){{doSearch();}}"` and a violet "Search" button calling `doSearch()`.
   - Page script (remember: inside an f-string, double every literal JS brace):
     ```js
     function doSearch() {
       var q = document.getElementById('search-q').value.trim();
       if (!q) return;
       _nav({page:'search', q: q.slice(0, 300)});
     }
     ```
   - Include `_NAV_BRIDGE` before this script (it defines `_nav`/`goPage`).
4. **Results list** (when `query` is non-empty): build a title lookup `{v["video_id"]: v for v in all_videos}` in Python. For each result render a card (`bg-surface border border-border rounded-lg p-4 mb-3 hover:border-border-hover`):
   - Header row: chunk title (`font-card-title`, escaped) + relevance badge `f"{int(result['score']*100)}%"` in a `font-metadata-mono text-secondary` chip.
   - Body: `chunk_text` escaped, clamped to ~300 chars with an ellipsis, `text-[13px] text-text-muted`.
   - Footer row: the parent video's title (from the lookup; fall back to the raw `video_id` if the video row is missing) as a link with `onclick="_nav({{page:'library', vid:'<video_id>'}})"` styled `text-secondary text-[12px]`, plus — when `timestamp_seconds` is not None — a mono timestamp chip linking to `_yt_url(video_id, ts)` with `target="_blank"`.
5. **Empty states** (three distinct ones):
   - No query yet: centered hint — "Search across every insight in your library. Try 'salary negotiation' or 'vector databases'."
   - Query but zero results AND `config.GEMINI_API_KEY` is empty (import `config` at module top if not already): "Semantic search needs a Gemini API key (GEMINI_API_KEY in .env)."
   - Query, key present, zero results: "No matches. Only videos processed after semantic search was enabled have embeddings — re-process older videos to index them."
6. Render with `components.html(html, height=900, scrolling=True)`.

### Step 3 — `components/stitch_pages.py`: wire the Library top-bar search box

In `_topbar_library_html`, give the existing "Search library..." input `id="topbar-q"` and `onkeydown="if(event.key==='Enter'&&this.value.trim()){{_nav({{page:'search', q:this.value.trim().slice(0,300)}});}}"`. (This function's HTML is returned into an f-string page — keep the brace doubling consistent with how the file already does it; check whether `_topbar_library_html` itself is an f-string, and single- vs double-brace accordingly. When unsure, run the app and check the rendered HTML for literal `{` characters.)

## Edge cases a weaker model would miss

1. **Score can be ≥ 1.0 or negative.** Cosine similarity is in [-1, 1]; clamp the badge: `max(0, min(100, int(score * 100)))`.
2. **Deleted/unknown videos.** Embeddings can outlive their video row. Always guard the title lookup with `.get(video_id)` and fall back gracefully.
3. **Empty embeddings table.** `search_insights` returns `[]` both for "no key" and "no data" — that's why Step 2.5 distinguishes the states by checking `config.GEMINI_API_KEY` yourself.
4. **Brace doubling in f-strings.** The `doSearch` JS and inline `onclick`/`onkeydown` handlers contain `{}` — inside f-strings every literal brace must be `{{` `}}`. This is the #1 source of silent breakage in this file; a mistake renders literal braces on the page rather than crashing.
5. **Query in URL.** `URLSearchParams` encodes the query; Streamlit auto-decodes. Never `urllib.parse.unquote` it again. Cap at 300 chars in JS.
6. **`search_insights` can raise nothing but log warnings** — it returns `[]` on internal failure. No try/except needed in the route, but don't add one that swallows a real crash silently either; leave exceptions visible.
7. **Height/scrolling.** Long result lists need `scrolling=True` (the Library page uses `False` because it manages its own overflow — do not copy that here).

## Do not touch

- `transcriber.py`, `youtube_monitor.py`.
- `search.py`, `db.py` — call only.
- The Library page's client-side video switching (`selectVideoLocal`); jumping from a result uses the normal `_nav` full-reload path on purpose (the target video must be selected server-side).
- New work must not break or restructure existing files or the working pipeline. Extend, don't rewrite.

## Acceptance criteria

Run `cd "D:\Cursor Projects\CursorP1"; python -m streamlit run app.py`, open http://localhost:8501.

1. Clicking the magnifier in the left rail opens the Search page (rail highlights the magnifier; page shows the hero input and hint text).
2. Typing a topic you know exists (e.g. a phrase from a processed video's insights) and pressing Enter shows ranked result cards with percentage badges, chunk text, and the source video's title.
3. Clicking a result's video title navigates to the Library with that exact video selected in the detail pane.
4. Results with timestamps show a mono chip that opens YouTube at that second in a new tab.
5. Typing a query into the Library top bar's "Search library..." box and pressing Enter lands on the Search page with results for that query, and the query text is preserved in the hero input.
6. With `GEMINI_API_KEY` removed from `.env` (test once, then restore), the page shows the key-missing message instead of a silent empty list.
7. Refreshing the browser on `?page=search&q=...` re-runs the same search (URL is shareable).
