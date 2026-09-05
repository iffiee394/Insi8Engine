# Insight Agent — Current Design System

> Documented from the live app (`localhost:8501`) and its source (`app.py`) for use as a baseline when researching other dashboard designs for a visual overhaul. This is a Streamlit app with custom CSS injected via `st.markdown(..., unsafe_allow_html=True)`.

---

## 1. Overall Aesthetic

**Style:** Dark "AI tool" theme — glassy panels, soft purple/indigo glow, rounded corners, low-contrast borders. Feels like a cross between a crypto dashboard and a modern SaaS analytics tool (Linear/Vercel-adjacent).

**Mood words:** dark, moody, glassmorphism, violet-tinted, dense, information-heavy, no whitespace-heavy "airy" feel — this is a data-dense utility dashboard, not a marketing page.

---

## 2. Color Palette

### Backgrounds
| Use | Value |
|-----|-------|
| App background | `radial-gradient(1200px 600px at 10% -10%, #1a1040 0%, #0b0d12 45%, #090a0f 100%)` — deep violet glow top-left fading to near-black |
| Sidebar background | `rgba(12, 14, 22, 0.92)` + `backdrop-filter: blur(12px)` (glass effect) |
| Sidebar border | `rgba(255,255,255,0.06)` (right edge) |
| Card/panel background | `rgba(255,255,255,0.03)` on top of the dark app bg (very subtle lift) |
| Card background (dimmer variant) | `rgba(255,255,255,0.02)` / `rgba(255,255,255,0.025)` |

Nothing uses flat solid colors for surfaces — everything is a translucent white overlay at 2–7% opacity on the dark gradient, which is what creates the "glass" look.

### Borders
All borders are translucent white, varying only in opacity:
- Standard card border: `rgba(255,255,255,0.07)`
- Subtle/inner border: `rgba(255,255,255,0.06)`
- Faint border: `rgba(255,255,255,0.04)`
- Hero panel border: `rgba(255,255,255,0.08)`

### Accent colors (the actual "color" in the palette)
| Color | Hex | Used for |
|-------|-----|----------|
| Indigo | `#6366f1` / `#818cf8` (light) | Primary accent — General playlist pill, summary card left-border, numbered list markers, links hover |
| Purple/violet | `#a855f7` / `#c084fc` (light) | Secondary accent — Podcast playlist pill, "Needs agenda" status, priority/agenda-item clusters, dashed agenda border |
| Amber/orange | `#f59e0b` / `#fcd34d` (light) | "Processing" status, guest-card highlight, "likely match" badge |
| Green | `#22c55e` | "Done" status |
| Red | `#ef4444` | "Failed" status |
| Slate gray | `#94a3b8` | "Pending" status, secondary/muted text |
| Sky blue | `#38bdf8` | "Batch queued" status |
| Light blue | `#93c5fd` | Link text color |

### Text colors
| Role | Value |
|------|-------|
| Primary heading | `#f8fafc` / `#f1f5f9` |
| Body text | `#e2e8f0` / `#cbd5e1` / `#dbe4f0` |
| Muted/secondary | `#94a3b8` |
| Faint/label | `#64748b` |

**Pattern:** the whole palette is drawn from Tailwind's `slate` (neutrals) and `indigo`/`purple`/`amber`/`green`/`red`/`sky` (accents) scales — recognizable if you've used Tailwind/shadcn before.

---

## 3. Typography

- **Font:** Inter (Google Fonts), weights 400/500/600/700. `font-family: 'Inter', sans-serif` applied globally.
- **Hero title (`<h1>`):** 1.75rem, weight 700, `letter-spacing: -0.02em` (tight tracking on large text)
- **Hero subtitle:** 0.95rem, `#94a3b8`, line-height 1.5
- **Section headers:** 0.82rem, weight 700, UPPERCASE, `letter-spacing: 0.08em` (wide tracking on small caps labels — classic dashboard-label style)
- **Stat labels:** 0.68rem, uppercase, `letter-spacing: 0.08em`
- **Stat values:** 1.45rem, weight 700
- **Panel titles (video title):** 1.2rem, weight 700
- **Body/insight text:** 0.9–0.96rem, line-height 1.55–1.7 (generous line-height for readability in dense cards)
- **Pills/badges:** 0.68rem, weight 700

**Pattern:** large numbers/titles are bold and tight-tracked; small labels are uppercase and wide-tracked. This contrast (tight big text vs. wide small text) is a deliberate, common "dashboard" typographic technique.

---

## 4. Shape & Spacing

| Element | Border radius |
|---------|---------------|
| Hero banner | 20px |
| Stat cards, panels | 16–18px |
| Insight cards, resource rows | 8–14px |
| Pills/badges | 999px (full pill) |
| Sidebar buttons | 12px |

- Card padding: mostly `14–22px` vertical/horizontal, generous for a dense UI
- Card gaps: `8–16px` between stacked cards
- Stats grid: 4 equal columns, `12px` gap
- Max content width: `1200px` (`.block-container`)

Everything is rounded — no sharp corners anywhere. Radius scales roughly with card size (bigger container = bigger radius).

---

## 5. Depth & Effects

- **No heavy shadows** except the hero banner: `box-shadow: 0 20px 60px rgba(0,0,0,0.25)` (soft, large, low-opacity — creates "floating" feel without a hard drop shadow)
- **backdrop-filter: blur(12px)** on the sidebar — true glassmorphism, not just a translucent color
- **Left-border accent bars** (3px solid) are used repeatedly instead of background-color changes to indicate category/emphasis:
  - Summary card: indigo (`#6366f1`) for general, purple (`#a855f7`) for podcast
  - Priority/agenda insight clusters: purple border
  - Non-priority clusters: gray (`rgba(148,163,184,0.4)`)
  - Guest card: amber background gradient, not border
- **Dashed border** used once, specifically for the "agenda" display box (`1px dashed rgba(168,85,247,0.35)`) — a nice subtle signal that this is agent-generated/editable content, not a hard fact

---

## 6. Components Inventory

| Component | Description |
|-----------|-------------|
| **Hero banner** | Gradient indigo/purple wash, app title + description, top of page |
| **Stats row** | 4-column grid of glass cards: Ready / In queue / General playlist / Podcast playlist counts |
| **Video thumbnail + panel** | 2-column layout: thumbnail image (left, ~1/3 width) + title/pills/metadata panel (right) |
| **Status pills** | Colored rounded-full badges, dark text on solid color bg (not translucent — pills are the one place with solid saturated color) |
| **Type pills** | Same pill style, indigo=General, purple=Podcast |
| **Section headers** | Uppercase eyebrow-style labels dividing content zones (Auto-generated focus, Deep insights, Resources, Links) |
| **Agenda display box** | Dashed-border box showing the AI-generated or custom agenda as plain preformatted text |
| **Numbered insight cards** | Each point in its own card with a colored number badge (indigo/purple depending on general vs. podcast) |
| **Cluster headers** | Sub-headers within insights, purple-highlighted if "priority" (agenda-matched), gray if general |
| **Guest card** | Amber-tinted gradient card for podcast guest bio |
| **Topic card** | Indigo-tinted card for researched topics |
| **Resource rows** | Flat list rows: name, type/source tag, detail text, optional link |
| **Link rows** | Clickable rows, light-blue text, hover state brightens bg + border |
| **"Likely match" badge** | Small amber pill for unconfirmed research matches |
| **Usage panel** | Gradient indigo card showing API call counts for the current run (Tavily, Gemini, Groq, Anthropic, YouTube) |
| **Chat input + Ask button** | Simple text input + button at bottom of video detail, no chat bubbles styling beyond basic cards |
| **Sidebar nav buttons** | Left-aligned, full-width, glass background, brighten on hover |
| **Tabs** (General vs Custom insights) | Streamlit native tabs, restyled: glass bg, indigo highlight on selected |
| **Expanders** | Native Streamlit expanders for Profile, Playlists, Custom agenda override, Call log, Overnight batch |

---

## 7. Layout Structure

```
┌─────────────┬──────────────────────────────────────────┐
│  SIDEBAR     │  MAIN CONTENT (max-width 1200px)         │
│  (fixed)     │                                            │
│              │  Hero banner                              │
│  Poll now    │  Stats row (4 cols)                       │
│  Search      │  Video thumbnail + info panel (2 cols)    │
│  Profile     │  Export / Re-process actions              │
│  Playlists   │  Auto-generated agenda box                │
│  Video list  │  Custom agenda override (expander)        │
│  Usage/Batch │  Summary card                             │
│  Call log    │  Guest card (podcast only)                │
│              │  Topic cards (podcast only)                │
│              │  Deep insights (clustered, numbered)      │
│              │  Resources list                            │
│              │  Links (grouped: video/description/research)│
│              │  Chat with video                           │
│              │  API usage panel                           │
└─────────────┴──────────────────────────────────────────┘
```

- Single-column detail view (everything stacks vertically after the 2-col header) — this is the biggest structural limitation for long podcasts: a 40-insight video becomes a very long scroll with no in-page navigation/anchor jumping.
- Sidebar owns: global actions, search, config (profile/playlists), video switching, and diagnostics (usage/batch/logs) — a lot of responsibility crammed into one collapsible column.
- No dedicated grid/card view for browsing all videos — video switching happens via a scrollable button list in the sidebar.

---

## 8. Interaction Patterns

- Sidebar video list = list of full-width buttons (icon + status label + truncated title), not a table — simple but not scannable at a glance for large libraries (47+ podcast videos observed)
- Custom agenda editing lives in a collapsed expander to avoid cluttering the default view
- Two insight "copies" (General auto-generated vs. Custom agenda) — implied to be tabs, per `PROJECT_GUIDE.md`, though not directly observed in this pass
- Background processing shows a polling `st.info` banner with progress count + current title (auto-refreshes every 5s via `st.fragment`)
- Hover states only defined for: sidebar buttons, link rows — most cards are static/non-interactive

---

## 9. Known Weak Points (worth targeting in a redesign)

Based on what's visible from the live app, these are the areas most likely to benefit from a visual overhaul:

1. **No visual hierarchy for scanning long insight lists.** 20-40 numbered cards in a single column with near-identical styling makes it hard to skim. Consider: collapsible clusters, a mini table-of-contents/anchor nav, or a two-pane (topic list + detail) layout.
2. **Video switching is a plain button list.** No thumbnails, no grid, no sorting/filtering beyond the General/Podcast radio filter. A card-grid or table view (with thumbnail, status, date) would scale much better than 47+ stacked buttons.
3. **Everything is single-column below the header.** Long-form content (research, resources, links, chat) could use a tabbed or sidebar-anchored layout instead of one long scroll.
4. **Chat UI is minimal** — just an input + button, no visible message-bubble history styling captured. Worth designing a proper chat thread UI if chat becomes a bigger feature.
5. **Status/type pills are the only saturated color in an otherwise all-translucent palette** — could be leveraged more (e.g., colored left-borders on video list items) for faster scanning.
6. **Dense uniform card rhythm** — nearly every content block uses the same card treatment (rounded rect, translucent bg, thin border), so visually distinct content types (summary vs. resource vs. link vs. insight point) don't read as different at a glance beyond color accents.

---

## 10. Reference: Raw CSS (from `app.py`)

For exact reproduction, the full custom CSS block lives in [`app.py`](app.py) starting at line 452 inside the `st.markdown(""" <style> ... """)` call. Key class names to know when comparing against new designs: `.hero`, `.stats`/`.stat`, `.pill`, `.panel`/`.panel-title`, `.summary-card`, `.section-head`, `.kp`, `.link-row`, `.resource-row`, `.guest-card`, `.topic-card`, `.cluster-head`, `.insight-point`, `.agenda-display`, `.usage-panel`.
