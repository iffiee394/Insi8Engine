# InsightEngine — Final Engineering Design Specification

This document serves as the high-fidelity source of truth for implementing the **InsightEngine** UI in Streamlit. It consolidates design tokens, layout architecture, and specific logic for new features (Personalized Extractions, Per-Video Token Logs, and Unified Insights).

---

## 1. Visual Foundation (Design Tokens)

### Color Palette (Hex)
- **Background (App):** `#0F0F1A`
- **Surface (Cards/Panels):** `#1A1A2E`
- **Surface (Hover):** `#22223A`
- **Primary Accent:** `#6C5CE7` (Violet)
- **Accent Soft:** `rgba(108, 92, 231, 0.15)`
- **Text (Primary):** `#E8E8F0`
- **Text (Secondary/Muted):** `#94A3B8`
- **Success:** `#22C55E`
- **Warning/Processing:** `#F59E0B`
- **Error:** `#EF4444`

### Typography & Spacing
- **Primary Font:** Inter (Sans-Serif)
- **Metadata/Timestamps:** JetBrains Mono or system monospace
- **Border Radius:** `12px` (Cards), `8px` (Pills)
- **Icon Rail Width:** `56px`
- **Left Pane Width:** `360px - 420px`

---

## 2. Layout Architecture

The app uses a **Three-Column Fixed Layout**:
1. **Column A (Icon Rail):** 56px fixed sidebar with Home, Queue, Search, Settings.
2. **Column B (Context Pane):** Scrollable list (Queue list or Library list).
3. **Column C (Main Panel):** Detail view with top tabs (Insights, Research, Resources, Chat).

---

## 3. Feature-Specific Logic

### 3.1 Personalized Extractions (Profile)
- **Bio-Driven Logic:** Add a `user_bio` text area and a `personalize_extractions` boolean toggle in the DB profile table.
- **Implementation:** When `True`, the LLM prompt in `pipeline.py` should prepend the user's bio to the system instructions to weight entity extraction toward stated interests.

### 3.2 Per-Video Token Logs (Library)
- **Dropdown Component:** Place a "Token Usage & Cost" expander in the video header (Right Pane).
- **Data Source:** Query the `changes_log` or `token_usage` table filtering by `video_id`.
- **UI:** Show a breakdown: `Transcript Tokens`, `Extraction Tokens`, `Research Tokens`, and `Total Cost ($)`.

### 3.3 Unified Insights & Timeline
- **No Tab Switching:** Remove the "Timeline" tab.
- **Top Bar:** Render the `Timeline Density Map` (horizontal bar with color-coded segments) at the top of the **Insights** tab.
- **Insight Cards:** 
    - No category tags.
    - Clickable monospace timestamp in top-right corner.
    - Linked to YouTube URL with `?t=seconds`.

### 3.4 Playlists & Extraction Focus
- **Per-Playlist Instructions:** Every playlist card should have an editable "Extraction Focus" field.
- **Override Logic:** If a video belongs to a playlist with a focus defined, this focus string takes precedence over (or appends to) the global Profile bio during processing.

---

## 4. Screen Reference Library

| Feature | Reference Placeholder | Key Element |
|---------|-----------------------|-------------|
| **Unified Insights** | {{DATA:SCREEN:SCREEN_20}} | Timeline map + Tag-less cards |
| **Profile & Bio** | {{DATA:SCREEN:SCREEN_5}} | Personalization toggle + API keys |
| **Token Dropdown** | {{DATA:SCREEN:SCREEN_19}} | Per-video cost breakdown |
| **Queue & Progress** | {{DATA:SCREEN:SCREEN_14}} | Live step labels & animated bars |
| **Playlists** | {{DATA:SCREEN:SCREEN_12}} | Extraction focus per-card |

---

## 5. Cursor Implementation Instructions

1. **Theme:** Update `.streamlit/config.toml` with the primary/secondary colors listed in Section 1.
2. **Layout:** Use `st.columns([rail, context, main])` or custom HTML/CSS to lock the 56px icon rail.
3. **Routing:** Use `st.session_state` to track `active_page` (Queue/Library/Playlists) and `selected_video_id`.
4. **Fragments:** Apply `@st.fragment(run_every=3)` to the Queue Context Pane to allow live updates without full page refreshes.
