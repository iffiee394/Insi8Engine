# PLAN-detail-tabs — Fill the Timeline, Research, and Resources tabs with real data

**Rank: 2 of 5.** Pure rendering work; every byte of data already exists in the DB. Lowest risk, high visible payoff.

## Goal

The video detail pane in the Library page (`components/stitch_pages.py::_detail_pane`) has five tabs: Insights, Timeline, Research, Resources, Chat. Only Insights renders content; Timeline/Research/Resources show hardcoded placeholder text, even though the V4 pipeline already stores everything they need in `structured_insights` and `research_data`. After this plan, those three tabs render the stored data. (Chat is a separate plan — leave its placeholder alone.)

## Architecture context

- Pages are complete HTML documents rendered via `st.components.v1.html()` iframes ("Option D"); no Streamlit widgets. All content is built as HTML strings inside `components/stitch_pages.py`.
- `_detail_pane(video)` builds one video's right-hand pane. It is called for EVERY video and the results are embedded in a JSON blob (`details_json`) for instant client-side switching — so keep each pane's HTML lean and always escape text with the module's `_e()` helper.
- Tab switching is already implemented client-side (`switchTab()` in `render_library_page`'s script; tab content divs are `#tab-timeline`, `#tab-research`, `#tab-resources`).

## The data (verified field names — use these exactly)

`structured = db.parse_structured_insights(video.get("structured_insights", "{}"))` gives:

- `structured["duration_seconds"]` — int, may be 0 (older videos / no timed captions).
- `structured["insights"]` — list of clusters; each may have `timestamp_seconds` (float or None) and `timestamp_range_end` (may be missing → assume start + 60 s).
- `structured["guest_profile"]` — dict with keys like `name`, `background`, `current_work`, `notable_achievements` (any may be missing/empty).
- `structured["resources"]` — list of dicts: `{"name", "type", "detail", "url" (may be null), "source"}`.
- `structured["links"]` — dict with keys `from_video`, `from_description`, `from_research`; each a list of `{"title", "url", "context"}`; `from_research` items may also carry `"confidence": "likely"|"confirmed"`.

`research = json.loads(video.get("research_data") or "{}")` (wrap in try/except, fall back to `{}`) gives:

- `research["combined_summary"]` — the synthesized web-research text.
- `research.get("links")` — same grouped shape (already merged into structured, prefer structured's copy).

Reference implementations for reading this data live in the dormant legacy code in `app.py` (`_render_structured_insights` around line 442, timeline usage at lines 451–453) and `components/timeline.py` (density-bar math). Read both before coding.

## Files to touch, in order

All changes are inside `components/stitch_pages.py` unless noted.

### Step 1 — Timeline tab

Add a helper `_timeline_html(video_id: str, structured: dict) -> str`:

1. `duration = int(structured.get("duration_seconds") or 0)`; `insights = structured.get("insights") or []`. If either is falsy, return an empty-state paragraph: "No timeline available — this video has no timed insight data."
2. Port the span math from `components/timeline.py::render_timeline` (lines 15–39): for each insight with a non-None `timestamp_seconds`, compute `start_pct` and `width_pct` against `duration`; skip zero-width spans; sort by start; insert gap divs.
3. Emit pure HTML (NOT `st.markdown` — this runs inside the iframe): a full-width bar, height 8px, `background:#1A1A2E;border-radius:4px;display:flex;overflow:hidden`, violet segments `background:#6C5CE7`, transparent gaps.
4. Below the bar, list each timestamped insight as a row: clickable mono timestamp (`_fmt_ts(ts)` linking to `_yt_url(video_id, ts)`, `target="_blank"`) + the cluster topic. Reuse the visual style of the timestamp chips in `_insight_card`.

In `_detail_pane`, replace the `tab-timeline` placeholder div content with `_timeline_html(vid_id, structured)` — but ONLY in the `status == db.STATUS_DONE` branch; other statuses keep placeholders.

### Step 2 — Research tab

Add `_research_html(video: dict, structured: dict) -> str`:

1. **Guest profile card** (if `structured.get("guest_profile")` has a truthy `name`): surface card (`bg-surface border border-border rounded-lg p-4`) with the name as `font-card-title`, then `background`, `current_work`, `notable_achievements` as labeled rows (label in `font-label-caps text-text-muted uppercase`, value in `text-[13px] text-text-primary`). Skip empty fields.
2. **Web research summary**: parse `research_data` as described above; if `combined_summary` is non-empty, render it in a card. It's plain text with newlines — convert `\n\n` to paragraph breaks after escaping with `_e()` (escape FIRST, then split).
3. **Research links**: for `structured["links"]["from_research"]`, render each as a row: link title as `<a href target="_blank" rel="noopener">`, context as muted small text, and a "LIKELY MATCH" badge (amber `#F5A623`, style of `_status_badge`) when `confidence == "likely"`.
4. If none of the three sections has content, return "No research data — this video was processed without web research."

### Step 3 — Resources tab

Add `_resources_html(video: dict, structured: dict) -> str`:

1. **Links section**, grouped with `font-label-caps` headers "FROM VIDEO", "FROM DESCRIPTION", "FROM RESEARCH", in that order, from `structured["links"]`. Skip empty groups. Each link: icon (`link` material symbol), title as anchor, context muted.
2. **Resources section** (items without URLs) from `structured["resources"]`: each row shows `name` (primary text), a small uppercase type chip (`type` field: company/book/tool/person/etc — style like the tag chips in `_insight_card`), and `detail` muted. If a resource has a `url`, make the name an anchor.
3. Empty state: "No links or resources were extracted from this video."

### Step 4 — Wire into `_detail_pane`

In the `STATUS_DONE` branch, compute the three HTML strings and substitute them into the existing `tab-timeline` / `tab-research` / `tab-resources` divs. Keep the `hidden` class on those divs — `switchTab()` handles visibility. Also update the tab labels: append a count bubble (same style as the Insights count) to Resources when links+resources total > 0.

## Edge cases a weaker model would miss

1. **Escape-then-format.** All titles/contexts/details come from LLM output and the web. Escape with `_e()` BEFORE inserting into HTML. For URLs, escape with `_e()` too and only render as an anchor when the value starts with `http://` or `https://` — otherwise render as plain text (Tavily occasionally returns junk in url fields).
2. **`</script>` inside data.** These panes are embedded in the `details_json` JSON blob. The existing `.replace("</", "<\\/")` guard in `render_library_page` protects everything — do not remove it, and don't add your own `<script>` tags inside pane HTML (inline `onclick` only).
3. **`timestamp_range_end` missing.** Legacy videos have insights with only `timestamp_seconds`. Follow `timeline.py`: `end = ins.get("timestamp_range_end") or (int(start) + 60)`.
4. **`duration_seconds == 0`.** Videos transcribed via Whisper fallback (no timed captions) have duration 0 — the timeline math would divide by zero. The Step 1 guard must run before any division.
5. **`research_data` may be the empty string**, not JSON — `json.loads("")` raises. Use `try/except (ValueError, TypeError)` returning `{}`.
6. **Dict-shaped link lists.** Occasionally the LLM emits a link entry as a bare string instead of a dict. Guard each item: `if isinstance(item, dict)` else render the string as plain text.
7. **f-string braces.** Any CSS/JS braces inside f-strings must be doubled (`{{`, `}}`). Prefer building these helpers with regular string concatenation or `.format`-free f-strings that only contain interpolations.

## Do not touch

- `transcriber.py`, `youtube_monitor.py`.
- `pipeline.py`, `researcher.py`, `db.py` — read-only for this plan.
- The Chat tab placeholder (separate plan) and the Insights tab (already working).
- `components/timeline.py` — copy its math, don't import it (it calls `st.markdown`, which doesn't work inside the iframe HTML).
- New work must not break or restructure existing files or the working pipeline. Extend, don't rewrite.

## Acceptance criteria

Run `cd "D:\Cursor Projects\CursorP1"; python -m streamlit run app.py`, open http://localhost:8501, select a **done** video that has research (most podcast videos do).

1. **Timeline tab** shows a horizontal density bar with violet segments plus a clickable list of timestamps; clicking one opens YouTube at that second in a new tab.
2. **Research tab** shows the guest profile (when the video has one), the web-research summary paragraphs, and research links with "LIKELY MATCH" badges where applicable.
3. **Resources tab** shows grouped links (From video / From description / From research) and the no-URL resources list with type chips.
4. A video with no timed data (older/Whisper-transcribed) shows the graceful empty state on the Timeline tab — no blank pane, no console errors.
5. Switching videos via the left list and re-opening the tabs still works (i.e., the client-side `selectVideoLocal` swap did not break — check the browser console for JS errors).
6. Non-done videos still show placeholder text in all three tabs.
