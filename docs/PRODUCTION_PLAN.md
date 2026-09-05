# YouTube Insight Agent — Production Plan

> Goal: Take the V4 agent from "works locally" to "publishable, demo-ready portfolio project" before hosting.
> This document covers **what** to build and **why**. The companion `BUILD_SPEC.md` covers **how** (hand that to Cursor).

---

## Current State (V4 — What's Already Strong)

The core pipeline is solid and doesn't need rework:

- Multi-pass AI extraction (recon → entities → research → holistic) is genuinely deep
- LLM fallback chain (Gemini → Anthropic Haiku) with quota-aware skipping
- Dual playlist modes (General vs Podcast) with appropriate cost/depth tradeoffs
- Tavily web research for podcast guest/topic enrichment
- Background subprocess processing with queue drain
- Usage tracking per-video and lifetime
- Chat with full transcript context
- Overnight batch mode for 50% Anthropic savings

None of the above needs changes. Everything below is additive.

---

## Tier 1 — High-Impact Features (Build These First)

These are the features that turn a working tool into something people remember when they see the demo.

### 1.1 Timestamp-Linked Insights

**Why this matters:** This is the single biggest differentiator. When an insight says "Guest explains why their first startup failed," a clickable timestamp that opens YouTube at that exact moment *proves* the AI understood the video — it's not just summarizing, it's navigating. Every other YouTube summarizer skips this.

**What it does:**
- Each insight cluster in the structured output gets an approximate start timestamp
- Timestamps render as clickable `?t=XXs` links to YouTube
- The holistic extraction prompt gets updated to request timestamp mapping
- Transcript already has timing data from captions/whisper — this is about surfacing it

**Complexity:** Medium. The transcript timing data exists. The main work is prompt engineering for the holistic pass and UI rendering.

### 1.2 Visual Timeline / Density Map

**Why this matters:** A horizontal bar showing where insight-dense sections fall in the video gives instant visual understanding of the content's shape. "The interesting stuff is in the middle third" is immediately obvious. This is a small component with outsized visual impact in demos.

**What it does:**
- Horizontal bar rendered via `st.html()` or `st.components.v1.html()`
- Colored segments based on insight cluster timestamps (from 1.1)
- Hover shows the insight topic at that position
- Click jumps to the YouTube timestamp

**Complexity:** Low-medium. Depends on 1.1 for timestamp data. The rendering is a simple HTML/CSS component.

### 1.3 Cross-Video Semantic Search

**Why this matters:** This is the "compound value" hook — the tool gets more useful the more videos you process. Searching "what did anyone say about hiring" across 50 processed videos is something no individual video summarizer offers.

**What it does:**
- Embed each insight chunk using Gemini's free embedding API (`text-embedding-004`)
- Store embeddings alongside insights (new DB column or separate table)
- Search bar in the UI — query gets embedded, cosine similarity finds matches
- Results show video title + matched insight + timestamp link
- Embeddings generated as a post-processing step after holistic extraction

**Complexity:** Medium. New dependency (embedding model), new DB table, new UI component. But the logic is straightforward — it's a standard semantic search pattern.

### 1.4 Export to Markdown

**Why this matters:** People who watch long-form content are note-takers. If they can't get the insights out of the tool, they'll screenshot instead of sharing. A clean export makes the tool fit into real workflows (Obsidian, Notion paste, blog post drafts).

**What it does:**
- "Export" button on each processed video
- Generates a clean Markdown file with: title, channel, date, summary, insight clusters (with timestamps), resources, links
- Download via `st.download_button()`
- Optional: batch export for all videos in a playlist

**Complexity:** Low. Structured insights are already JSON — this is just templating.

---

## Tier 2 — Polish Features (Build After Tier 1)

These make the experience feel complete but aren't the demo headline.

### 2.1 Demo / Seed Mode

**Why this matters:** When someone hits the live demo or clones the repo, they need to see results immediately — not set up 4 API keys and wait 5 minutes for processing. Pre-loaded examples are the difference between "cool" and "closed tab."

**What it does:**
- 3-5 pre-processed videos bundled as JSON fixtures (not the DB itself)
- `seed_demo.py` script that loads fixtures into a fresh DB
- Covers both General and Podcast types
- Includes research data, structured insights, timestamps, usage stats
- README says: "Run `python seed_demo.py` to see example results immediately"

**Complexity:** Low. Export existing processed videos as JSON, write a loader script.

### 2.2 Onboarding Config Validator

**Why this matters:** First-run experience. Right now if you miss a key, you get a runtime error deep in the pipeline. A startup check that says "GROQ_API_KEY missing — agenda generation won't work" saves 30 minutes of debugging.

**What it does:**
- `validate_config()` runs on app startup
- Checks all env vars, groups them: required / recommended / optional
- Shows a Streamlit info panel if anything is missing
- Tests API connectivity for each configured provider (quick ping)
- Shows which features are available vs degraded based on current config

**Complexity:** Low.

### 2.3 Smart Error States

**Why this matters:** Current error messages are technical (traceback-level). For a portfolio piece, errors should be user-friendly and actionable.

**What it does:**
- Map common failures to friendly messages:
  - "This video has no captions and audio transcription is unavailable" (not a raw API error)
  - "Gemini free tier exhausted for today — retrying with Anthropic" (not HTTP 429)
  - "This video is private or age-restricted" (not a yt-dlp crash)
- Error cards in the UI with a "What happened" explanation and "Try this" suggestion
- Failed videos show the friendly error, with raw error in an expander for debugging

**Complexity:** Low-medium. Mostly mapping error types to messages and updating the UI.

### 2.4 Keyboard Shortcuts & Navigation

**Why this matters:** Power users (your target audience — podcast-heavy learners) want to move fast. j/k to navigate videos, Enter to open, Esc to go back.

**What it does:**
- `streamlit-shortcuts` or custom JS injection
- j/k for video list navigation
- / to focus search (if semantic search is built)
- e for export

**Complexity:** Low. Streamlit's JS injection can handle this.

---

## Tier 3 — Stretch Features (If Time Allows)

### 3.1 Knowledge Graph Visualization

Connect entities across videos. If "Sam Altman" appears in 5 different podcasts, show the network of connected topics and people. Visually impressive for demos, shows cross-video intelligence.

Uses: NetworkX for graph computation, a simple D3/vis.js component embedded via `st.components.v1.html()`.

### 3.2 Notion Integration

Push insights directly to a Notion database. Uses Notion API. Each video becomes a page with properties (channel, date, type) and content blocks (insights, resources, links).

### 3.3 RSS/Newsletter Digest

Weekly email with new insights from processed videos. Uses a simple Jinja template + SMTP. Low priority but high "this is a real product" signal.

### 3.4 Comparative Analysis

"Compare what these 3 videos say about pricing strategy." Select multiple videos, run a synthesis prompt across their insights. Powerful but complex — needs a new LLM pass and UI flow.

---

## Code Quality Improvements (Do Alongside Features)

These aren't features but they make the codebase presentable for GitHub.

### Path Cleanup
- Remove all hardcoded Windows paths (`D:\Cursor Projects\CursorP1`)
- Use `pathlib.Path` throughout
- Make DB path, log path, data dir configurable via env vars with sensible defaults (`./data/`, `./logs/`)

### Type Hints
- Add type hints to all function signatures in `pipeline.py`, `llm.py`, `researcher.py`, `db.py`
- Not full mypy strictness — just enough that someone reading the code knows what flows where

### Logging Cleanup
- Consistent log format across all modules: `[module] message`
- Log levels: INFO for normal flow, WARNING for fallbacks, ERROR for failures
- Remove any print() statements still in the codebase

### Config as a Module
- Move env loading logic into a `config.py` that validates and exposes typed config
- Other modules import from config instead of calling `os.getenv()` everywhere

---

## GitHub Packaging (Pre-Launch Checklist)

### README.md Structure
1. **Hero line:** "Stop watching 3-hour podcasts. Extract every insight in 2 minutes."
2. **Demo GIF:** 15-second screen recording: paste playlist → poll → see insights → click timestamp → YouTube opens at that moment
3. **Feature highlights:** 4-5 bullets with emoji, not a feature matrix
4. **Quickstart:** Docker one-liner or 4-step local setup
5. **Architecture diagram:** Cleaned-up version of the V4 pipeline diagram (as SVG or Mermaid)
6. **Cost transparency:** "Runs on free tiers. Typical cost: $0 for lectures, ~$0.35 for podcasts."
7. **Screenshots:** Insight view, timeline, search results, chat

### Repository Structure
```
youtube-insight-agent/
├── README.md                    # Public-facing (short, punchy)
├── docs/
│   ├── ARCHITECTURE.md          # Current PROJECT_GUIDE.md, cleaned up
│   ├── CONFIGURATION.md         # Full env reference
│   └── CONTRIBUTING.md          # Even if solo — signals maturity
├── app.py
├── pipeline.py
├── llm.py
├── researcher.py
├── db.py
├── config.py                    # New: centralized config
├── search.py                    # New: semantic search
├── export.py                    # New: markdown export
├── seed_demo.py                 # New: demo fixtures loader
├── data/
│   └── fixtures/                # Pre-processed demo videos
├── requirements.txt
├── Dockerfile                   # For later hosting
├── docker-compose.yml
├── .env.example
└── .gitignore
```

### Pinned Repo Strategy
- Pin this repo on GitHub profile
- README opens with the problem, not the tech
- Include "Built with" badges: Streamlit, Gemini, Anthropic, Tavily
- Add a "Live Demo" badge linking to the hosted version (once deployed)

---

## Execution Priority (Build Order)

| Priority | Feature | Why This Order |
|----------|---------|----------------|
| 1 | Path cleanup + config.py | Foundation — everything else builds on clean config |
| 2 | Timestamp-linked insights | The #1 demo differentiator |
| 3 | Visual timeline | Depends on timestamps, small effort, big visual payoff |
| 4 | Export to Markdown | Quick win, real utility |
| 5 | Semantic search | The compound-value story |
| 6 | Demo seed mode | Needed before anyone else tries it |
| 7 | Config validator | First-run experience |
| 8 | Smart error states | Polish |
| 9 | README + GitHub packaging | Final step before launch |
| 10 | Stretch features | Only if time allows |

---

## What NOT to Do Yet

- **Don't switch to PostgreSQL** until you're actually deploying. SQLite is fine for dev and demo.
- **Don't add auth** until hosting. Adds complexity with no local benefit.
- **Don't Dockerize** until the features are done. It's a deployment concern.
- **Don't build multi-user** — this is a personal tool / portfolio piece, not a SaaS (yet).
- **Don't rewrite the pipeline** — V4 is solid. All changes are additive.
