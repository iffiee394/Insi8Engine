# UI Overhaul Build Spec — InsightEngine

> **For:** Google Stitch mockups → Streamlit implementation  
> **Reference mockup:** Queue view + Library view (dark navy, purple accent, left rail)  
> **Prerequisite:** Read [PROJECT_GUIDE.md](../PROJECT_GUIDE.md) for backend behavior  
> **Phase:** 1 of [FINAL_SHIP_PLAN.md](FINAL_SHIP_PLAN.md) — UI before auth/deploy  

---

## 0. Google Stitch — yes, use it

**[Google Stitch](https://stitch.withgoogle.com/)** (Google Labs) is an AI UI design canvas: text/voice/image → high-fidelity screens, multi-screen prototypes, exports **DESIGN.md** + optional code.

**Why it fits this project:**
- You already have a visual target (your mockup) — upload it to Stitch and iterate with prompts
- Generate **all screens** (Queue, Library, Settings, empty states) as a connected prototype before touching `app.py`
- Export **design tokens** (colors, spacing, typography) into `.streamlit/config.toml` + CSS
- Stitch is **UI-only** — our backend stays Streamlit + Python; we match the look, not rewrite to React

**Stitch workflow for this app:**

1. **Upload your mockup image** (Queue + Library composite) as context on the canvas  
2. **Paste the Design Brief** (Section 2 below) into Stitch chat  
3. **Generate missing screens:** Playlists, Settings (future), Failed video, Empty library, Search results, Processing empty state  
4. **Iterate:** “Remove tags from insight cards”, “flatten sidebar to icon rail”, etc.  
5. **Export:** Screenshot each screen + copy DESIGN.md / color hex values  
6. **Hand to Cursor:** Implement in `app.py` using this spec + Stitch exports  

**Stitch prompt starter (copy-paste):**

```
Design a dark SaaS dashboard called "InsightEngine" for a YouTube insight extraction app.

Layout: fixed left icon rail (64px), top bar with tabs Queue | Library | Playlists and global search, main content area.

Theme: background #0F0F1A, cards #1A1A2E, primary accent #6C5CE7, text #E8E8F0, muted #94A3B8. Rounded cards 12px. Inter font.

Queue screen: left column shows Now Processing (LIVE badge, progress bar, current step label), Up Next list, Recently Completed. Main area shows empty state "Video is being analyzed" with step pills (Transcription ✓, Knowledge Graph spinner).

Library screen: left column scrollable video cards (thumbnail, title, channel, duration, DONE/PENDING pill). Main area: video header, Watch on YouTube + Export dropdown, tabs Insights | Timeline | Research | Resources | Chat. Insights tab: vertical cards with title, clickable timestamp (12:34), body text — NO category tags.

Mobile: stack columns, keep rail as bottom nav optional.
```

---

## 1. Design decisions (locked from your mockup)

| Decision | Choice |
|----------|--------|
| Product name in UI | **InsightEngine** (rename from “Insight Agent” in UI only) |
| Insight card **tags** | **Removed** — no STRATEGY/HIRING/CULTURE pills |
| Primary accent | Purple `#6C5CE7` (buttons, active tab, progress, LIVE) |
| Background | Deep navy `#0F0F1A` / cards `#1A1A2E` |
| Navigation | Top tabs: **Queue · Library · Playlists** + icon rail (Home, Search, Library, Settings) |
| Library detail tabs | **Insights · Timeline · Research · Resources · Chat** |
| Queue main empty state | Illustration + “Video is being analyzed…” + step pills |

---

## 2. Design tokens (for Stitch + Streamlit)

### `.streamlit/config.toml` (target)

```toml
[theme]
base = "dark"
primaryColor = "#6C5CE7"
backgroundColor = "#0F0F1A"
secondaryBackgroundColor = "#1A1A2E"
textColor = "#E8E8F0"
font = "sans serif"

[server]
headless = true
```

### CSS variables (inject in `app.py`)

| Token | Value | Use |
|-------|-------|-----|
| `--bg-app` | `#0F0F1A` | Page background |
| `--bg-card` | `#1A1A2E` | Cards, sidebar panels |
| `--accent` | `#6C5CE7` | Primary buttons, active tab, progress |
| `--accent-soft` | `rgba(108,92,231,0.15)` | Selected list item |
| `--text` | `#E8E8F0` | Body |
| `--text-muted` | `#94A3B8` | Meta, captions |
| `--success` | `#22C55E` | DONE, completed steps |
| `--warning` | `#F59E0B` | PROCESSING, LIVE pulse |
| `--error` | `#EF4444` | FAILED |
| `--radius` | `12px` | Cards |
| `--radius-sm` | `8px` | Pills, tags |

---

## 3. Screen inventory (mock ALL in Stitch)

| # | Screen | When shown | Mock priority |
|---|--------|------------|---------------|
| 1 | **Queue** | Default when worker running or items pending | ✅ Done in your mock |
| 2 | **Queue — idle** | No jobs; CTA “Poll playlists” | High |
| 3 | **Library** | Browse processed videos | ✅ Done in your mock |
| 4 | **Library — Insights tab** | Done video, insight cards | ✅ Done (no tags) |
| 5 | **Library — Timeline tab** | Horizontal density bar + segments | High |
| 6 | **Library — Research tab** | Guest bio, topic briefs (podcast) | Medium |
| 7 | **Library — Resources tab** | Books, tools, companies list | Medium |
| 8 | **Library — Chat tab** | Q&A thread + input | Medium |
| 9 | **Library — Processing** | Selected video still running | High |
| 10 | **Library — Failed** | Error card + Retry | High |
| 11 | **Library — Pending** | Queued, Process now | Medium |
| 12 | **Playlists** | Manage playlists + extraction focus | Medium |
| 13 | **Global search** | Search overlay or top-bar results dropdown | High |
| 14 | **Settings** | Profile + API keys (Phase 2 — mock shell now) | Low |
| 15 | **Empty library** | First-run, no videos | High |
| 16 | **Demo mode** | Read-only seeded insights (Phase 3) | Low |

---

## 4. Layout architecture (target)

```
┌──┬──────────────────────────────────────────────────────────────┐
│🏠│  InsightEngine          [Queue] [Library] [Playlists]  🔍 👤 │
│🔍├──────────────────────────────────────────────────────────────┤
│📚│ ┌─ Context column (280–320px) ─┐ ┌─ Main panel ─────────────┐ │
│⚙️│ │ Queue: Now / Up Next / Done   │ │ Video header + actions   │ │
│  │ │ Library: video cards list     │ │ Tab bar                  │ │
│  │ │                               │ │ Tab content              │ │
│  └─┴───────────────────────────────┴─┴──────────────────────────┘ │
└──┴──────────────────────────────────────────────────────────────┘
  Icon rail (64px)     Top nav                         Content
```

**Streamlit mapping (implementation):**

| Mockup region | Streamlit approach |
|---------------|-------------------|
| Icon rail | Custom HTML/CSS fixed column OR `st.navigation` + minimal sidebar |
| Top tabs Queue/Library/Playlists | `st.session_state.page` + `st.radio` styled as tabs OR `st.tabs` at top of main |
| Context column | Left `st.column(0.28)` — queue list OR library list |
| Main panel | Right `st.column(0.72)` — detail / empty state |
| Global search | Top bar `st.text_input` → results dropdown panel |

---

## 5. Current app vs target (what moves where)

### Today (`app.py`)

| UI element | Current location | Target location |
|------------|------------------|-----------------|
| Poll now | Sidebar top | Queue tab — primary CTA + top bar |
| Background banner | Sidebar fragment | Queue tab — “Now Processing” card |
| Video list + filters | Sidebar expander | Library — left column cards |
| Search all videos | Sidebar text input | Top bar 🔍 + Search results panel |
| Profile | Sidebar expander | Settings (icon rail) |
| Playlists | Sidebar expander | **Playlists** top tab |
| Usage / batch / call log | Sidebar expanders | Settings → Advanced (collapsed) |
| Hero + stats row | Main top | **Remove** or shrink to Queue tab header |
| Video header + thumbnail | Main columns | Library main — top of detail |
| Export Markdown | Button below header | **Export** dropdown (Markdown, future JSON) |
| Insights | Main body stacked sections | **Insights tab** only |
| Timeline | Inline above insights | **Timeline tab** |
| Web research | Expandable section | **Research tab** (podcast) |
| Resources + Links | Two sections stacked | **Resources tab** (links grouped inside) |
| Chat | Bottom of main | **Chat tab** |
| API usage | Bottom panel | Settings → Usage OR footer expander |

---

## 6. Features → implementation map

How each feature works **today** (backend unchanged in UI phase):

### 6.1 Queue & processing

| Feature | User action | Code path | Data |
|---------|-------------|-----------|------|
| Poll all pending | Poll now | `background_jobs.start_poll_background()` → `poll.py` | `videos.status = pending` |
| Process one | Process now / Retry | `start_process_one_background(video_id)` | Same |
| Background worker | Automatic | `poll_worker.log`, meta `poll_worker_running` | |
| Progress text | Sidebar banner | `poll_progress_done/total`, `poll_current_title` | meta table |
| Live step labels | **Not built yet** | Phase 2: `processing_queue.current_step` | Future |
| **UI mock shows** | Transcription ✓, Knowledge Graph… | Map to pipeline stages: transcript → recon → entities → research → holistic | |

**Queue tab UI (Phase 1 — mock real data):**

- **Now Processing:** first `status=processing` video OR meta `poll_current_title`
- **Up Next:** `pending` videos, oldest first
- **Recently Completed:** last N `done` videos by `processed_at`
- **Main empty state:** when processing selected video — show step pills (static labels until Phase 2)

### 6.2 Library & video detail

| Feature | Code | DB fields |
|---------|------|-----------|
| Video list | `db.list_videos()` | `title`, `status`, `playlist_type`, `channel_name` |
| Thumbnail | `_thumbnail(video_id)` | YouTube CDN |
| Status pill | `STATUS_META` | `status` |
| Select video | `st.session_state.selected_id` | `video_id` |
| Watch on YouTube | `st.link_button` | `url` |
| Export Markdown | `export.export_video_markdown()` | all row fields |
| Re-process | Sets `pending` + background job | |

### 6.3 Insights tab

| Feature | Code | Notes |
|---------|------|-------|
| Structured insight cards | `_render_structured_insights()` | `structured_insights.insights[]` |
| Timestamp link | `_format_timestamp_link()` | `timestamp_seconds` → YouTube `?t=` |
| **No tags** | Remove any tag rendering | Mock: title + time + body only |
| Summary block | `structured.summary` | Card above insight list |
| Dual agenda (podcast) | Sub-toggle or nested tab | `manual_summary` vs auto |
| Flat key points fallback | `_render_insights()` | Old videos without structured JSON |

**Insight card schema (render, don’t show tags):**

```json
{
  "topic": "The 'Zero to One' Recruitment Strategy",
  "timestamp_seconds": 754,
  "timestamp_range_end": 920,
  "is_agenda_item": true,
  "points": ["bullet 1", "bullet 2"]
}
```

### 6.4 Timeline tab

| Feature | Code |
|---------|------|
| Density bar | `components/timeline.render_timeline()` |
| Duration | `structured_insights.duration_seconds` |

### 6.5 Research tab

| Feature | Code | Visible |
|---------|------|---------|
| Guest bio, viral, topics | `_render_web_research()` | Podcast only |
| Description notes | `_render_description_notes()` | General only |

### 6.6 Resources tab

| Feature | Code |
|---------|------|
| Resources list | `_get_resources()` → `_render_resources()` |
| Grouped links | `_get_links_bundle()` → `_render_links_grouped()` |

### 6.7 Chat tab

| Feature | Code |
|---------|------|
| Transcript Q&A | `pipeline.chat_with_video()` |
| History | `st.session_state[f"chat_{video_id}"]` |

### 6.8 Search (v2 — UI phase)

| Feature | Current | Target UI |
|---------|---------|-----------|
| Semantic search | `search.search_insights()` | Top bar search |
| Filters | None | Dropdowns: All / General / Podcast, min score slider |
| Jump to video | Open video button | Click result → Library + select video + optional timestamp |
| Search in playlist | None | Checkbox when playlist selected |

**Backend:** `search.py` + `embeddings` table — filters are client-side in Phase 1.

### 6.9 Playlists tab

| Feature | Code |
|---------|------|
| List/add/edit | `db.list_playlists()`, sidebar expander today |
| Extraction focus | Per-playlist text area |
| Sync | Happens on Poll |

### 6.10 Settings (shell in UI phase, full in Phase 2)

| Feature | Phase |
|---------|-------|
| Profile (about, interests, style) | UI shell now — `db.get_profile()` |
| API keys encrypted | Phase 2 deploy |
| Usage / batch / call log | Move from sidebar |

---

## 7. UI implementation tasks (Streamlit, after Stitch)

Build in order:

### Task UI-1: Theme foundation
- [ ] Add `.streamlit/config.toml`
- [ ] Replace inline CSS in `app.py` with token-based stylesheet
- [ ] Rename visible branding to **InsightEngine**

### Task UI-2: App shell
- [ ] Icon rail + top nav (Queue / Library / Playlists)
- [ ] `st.session_state.active_page` routing
- [ ] Remove hero stats row (or move counts to Queue header)

### Task UI-3: Queue page
- [ ] Three-section left column: Now / Up Next / Recently Completed
- [ ] Main panel: processing empty state + step pills
- [ ] Wire to existing poll/worker meta
- [ ] `@st.fragment(run_every=3)` on queue panel only

### Task UI-4: Library page
- [ ] Left: scrollable video cards (thumbnail, title, channel, duration, status pill)
- [ ] Filters: status dropdown, type dropdown, sort dropdown
- [ ] Right: video header + Export dropdown + tabs

### Task UI-5: Detail tabs
- [ ] **Insights** — card list, timestamp links, **no tags**
- [ ] **Timeline** — move `render_timeline` here
- [ ] **Research** — podcast web research OR general description
- [ ] **Resources** — resources + grouped links
- [ ] **Chat** — move chat UI here

### Task UI-6: Search v2 UI
- [ ] Top-bar search input
- [ ] Filter row (type, min score, playlist scope)
- [ ] Results panel with jump-to-video

### Task UI-7: Empty & error states
- [ ] Empty library illustration + “Add playlist / Poll now”
- [ ] Failed video — use `errors.classify_error()` in Library detail
- [ ] Processing / pending states per mock

### Task UI-8: Playlists page
- [ ] Move playlist manager from sidebar to dedicated tab

### Task UI-9: Polish
- [ ] Mobile: stack columns < 768px
- [ ] Loading skeletons on queue refresh
- [ ] Toast on export / retry

**Files to touch:** `app.py` (primary), `components/` (queue_card, library_card, insight_card HTML), `.streamlit/config.toml`

**Do not touch in UI phase:** `pipeline.py`, `llm.py`, `db.py` schema (except read-only queries)

---

## 8. Acceptance criteria

- [ ] All 16 screens exist as Stitch mocks (or exported PNGs) before coding
- [ ] Queue and Library match mockup hierarchy (icon rail, top tabs, two-column)
- [ ] Insight cards show **title + timestamp + body only** — no tags
- [ ] All existing features reachable without sidebar expanders
- [ ] Search works from top bar with at least type filter
- [ ] Export still downloads valid Markdown
- [ ] Timestamp links open YouTube at correct second
- [ ] No regression: poll, re-process, chat, batch (in Settings advanced)

---

## 9. Stitch → Streamlit handoff checklist

When mocks are final in Stitch:

1. Export PNG per screen (1x and 2x)
2. Copy hex colors into Section 2 of this doc
3. Note spacing: card padding, column widths, font sizes
4. Share `DESIGN.md` from Stitch if generated
5. Tell Cursor: **“Implement UI-1 through UI-9 per UI_BUILD_SPEC.md”**

---

## Related docs

- [FINAL_SHIP_PLAN.md](FINAL_SHIP_PLAN.md) — phases after UI
- [BUILD_SPEC.md](BUILD_SPEC.md) — production features (timestamps, search v1, export)
- [PROJECT_GUIDE.md](../PROJECT_GUIDE.md) — full backend reference
