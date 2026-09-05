# Stitch Handoff — Design Tokens (InsightEngine)

Extracted from `docs/stitch_handoff/DESIGN.md` and `insightengine_handoff_spec.md` for Streamlit implementation.

## Core palette (use these in CSS + config.toml)

| Token | Hex | Use |
|-------|-----|-----|
| Background (app) | `#0F0F1A` | Page shell, icon rail |
| Surface (cards) | `#1A1A2E` | Cards, list panels, inputs |
| Surface hover | `#22223A` | Hover states |
| Surface elevated | `#24243D` | Dropdowns, overlays |
| Border | `#2A2A42` | Pane dividers, card outlines |
| Border hover | `#3A3A5C` | Hover borders |
| Primary accent | `#6C5CE7` | Buttons, active tab, progress, LIVE |
| Accent soft | `rgba(108, 92, 231, 0.15)` | Selected list item background |
| Text primary | `#E8E8F0` | Body, titles |
| Text muted | `#94A3B8` | Meta, captions |
| Tab inactive | `#9494A8` | Inactive nav tabs |
| Success / Done | `#22C55E` | DONE pills, completed steps |
| Warning / Processing | `#F59E0B` | PROCESSING, LIVE pulse |
| Error / Failed | `#EF4444` | FAILED state |

## Status pills (15% bg opacity, 100% text)

| Status | Color |
|--------|-------|
| Pending | `#5C5C70` / `#9494A8` |
| Processing | `#F59E0B` |
| Done | `#22C55E` |
| Failed | `#EF4444` |

## Typography

| Role | Font | Size |
|------|------|------|
| Headline | Inter 600 | 20px |
| Card title | Inter 600 | 15px |
| Body | Inter 400 | 14px |
| Section label (caps) | Inter 600 | 11px, letter-spacing 0.05em |
| Timestamps / metadata | JetBrains Mono | 12px |
| Tab label | Inter 500 | 13px |

## Layout

| Element | Value |
|---------|-------|
| Icon rail width | 56px |
| Left pane (list) | 360–420px (implemented as 380px) |
| Container padding | 24px (1.5rem) |
| Card gap | 12px (0.75rem) |
| Border radius (cards) | 8–12px |
| Thumbnail | 64×64px, 6px radius |

## Handoff decisions (Streamlit)

1. **Unified Insights** — Timeline density map at top of **Insights** tab (no separate Timeline tab).
2. **No tags** on insight cards — title + monospace timestamp + body only.
3. **Top nav** — Queue | Library | Playlists.
4. **Icon rail** — Home (Library), Queue, Search, Settings.
5. **Detail tabs** — Insights | Research | Resources | Chat.

## Files implemented

- `.streamlit/config.toml` — Streamlit theme colors
- `components/ui_styles.py` — CSS variables + component classes
- `components/ui_shell.py` — App shell routing
- `app.py` — Page renderers + backend wiring

## Source zip

`c:\Users\HP\Documents\stitch_insight_agent_ui_system_handoff.zip` → extracted to `docs/stitch_handoff/`
