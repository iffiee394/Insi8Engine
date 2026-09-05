# InsightEngine — Design Brief for Google Stitch

Copy sections below into Stitch when generating or refining screens.

---

## Product

**InsightEngine** — turns YouTube playlists (lectures + podcasts) into timestamped insight cards with web research, resources, and chat. Dark professional dashboard, not consumer social.

---

## Users

Technical learners who watch long YouTube content and want searchable, clickable insights without watching entire videos again.

---

## Visual language

- **Mood:** Focused, premium, dark control room — not playful, not corporate gray
- **Primary accent:** `#6C5CE7` (purple) — buttons, active states, progress bars, LIVE badge
- **Background:** `#0F0F1A` app, `#1A1A2E` cards
- **Text:** `#E8E8F0` primary, `#94A3B8` secondary
- **Font:** Inter or similar geometric sans
- **Corners:** 12px cards, 8px pills
- **Density:** Comfortable — not cramped tables; card-based lists

---

## Layout system

- **Left icon rail:** 64px fixed — Home, Search, Library, Settings (icons only + tooltip)
- **Top bar:** Logo “InsightEngine”, tabs **Queue | Library | Playlists**, right: search field + avatar
- **Content:** Two columns — context list (~30%) + main detail (~70%)
- **Breakpoints:** Desktop first; mobile stacks list above detail

---

## Components

### Video card (library list)
- Thumbnail 16:9 left
- Title (2 lines max), channel name, duration
- Status pill: DONE (green), PENDING (gray), PROCESSING (amber), FAILED (red)
- Selected state: purple left border + soft purple background

### Insight card (insights tab)
- Title (semibold)
- Timestamp right-aligned or inline link style “12:34” in accent color
- Body: 2–4 sentences or bullet list
- **Do NOT show category tags** (no STRATEGY/HIRING pills)

### Queue — Now Processing card
- Thumbnail + title
- LIVE badge (pulsing dot)
- Progress bar (purple gradient)
- Subtext: current step e.g. “Researching guest background…”

### Queue — Up Next / Recently Completed
- Compact rows, thumbnail small
- Recently completed: green check + “2m ago”

### Tab bar (detail)
Insights | Timeline | Research | Resources | Chat — underline active tab in purple

### Empty state (processing)
- Centered illustration (subtle purple glow)
- “Video is being analyzed…”
- Step pills: Transcription ✓ | Entities ✓ | Research (spinner) | Insights (pending)

### Buttons
- Primary: filled purple
- Secondary: outline on dark card
- Export: primary with chevron dropdown

---

## Screens to generate

1. Queue (active processing)
2. Queue (empty — CTA poll)
3. Library (list + insights tab open)
4. Library — Timeline tab
5. Library — Research tab (podcast guest card)
6. Library — Resources tab
7. Library — Chat tab
8. Library — failed video
9. Playlists management
10. Global search results dropdown
11. Empty library first-run

---

## Reference

Attach user mockup: Queue view (left) + Library view (right) with InsightEngine branding.

Iterate command examples:
- “Remove all tags from insight cards”
- “Make the left rail icon-only 64px”
- “Add Export dropdown with Markdown option”
- “Show all five detail tabs with realistic podcast content”
