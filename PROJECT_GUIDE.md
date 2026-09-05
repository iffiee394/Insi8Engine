# YouTube Insight Agent — Complete Project Guide

> **Last updated:** June 2026  
> A Streamlit dashboard that watches YouTube playlists, transcribes videos, runs multi-pass AI extraction with optional web research, and presents deep insights, links, resources, and chat.

---

## Table of contents

1. [What this app does](#1-what-this-app-does)
2. [Quick start](#2-quick-start)
3. [Architecture overview](#3-architecture-overview)
4. [Feature list (everything built)](#4-feature-list-everything-built)
5. [Playlist modes: General vs Podcast](#5-playlist-modes-general-vs-podcast)
6. [Processing pipeline (step by step)](#6-processing-pipeline-step-by-step)
7. [LLM strategy & fallbacks](#7-llm-strategy--fallbacks)
8. [API providers, usage & pricing](#8-api-providers-usage--pricing)
9. [Dashboard UI guide](#9-dashboard-ui-guide)
10. [Configuration reference (`.env`)](#10-configuration-reference-env)
11. [Background jobs & logging](#11-background-jobs--logging)
12. [Overnight batch mode](#12-overnight-batch-mode)
13. [Database & data model](#13-database--data-model)
14. [Source file map](#14-source-file-map)
15. [Version history & changelog](#15-version-history--changelog)
16. [Troubleshooting](#16-troubleshooting)
17. [Typical cost per video (estimates)](#17-typical-cost-per-video-estimates)

---

## 1. What this app does

The **YouTube Insight Agent** automates learning from YouTube content:

| Step | What happens |
|------|----------------|
| **Watch** | Polls one or more YouTube playlists you configure |
| **Transcribe** | YouTube captions → optional Gemini audio → Groq Whisper fallback |
| **Understand** | Multi-pass AI: structure → entities → research → holistic extraction |
| **Present** | Streamlit UI with insights, links, resources, usage stats, and chat |

Two playlist **kinds** behave differently:

- **General** — lectures, tutorials, talks: full holistic extraction, **no Tavily** (free research from description + transcript URLs only).
- **Podcast** — interview-style: profile-tailored agenda, **Tavily web research**, entity-targeted searches, richer “Deep insights.”

---

## 2. Quick start

### Prerequisites

- Python 3.10+
- **ffmpeg** on PATH (for yt-dlp audio / long-video chunking)
- API keys (see [Configuration](#10-configuration-reference-env))

### Install (Windows PowerShell)

```powershell
cd "D:\Cursor Projects\CursorP1"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy `config.example.env` → `.env` and fill in keys.

### Run

```powershell
# Dashboard
python -m streamlit run app.py

# Manual poll (CLI — same logic as sidebar “Poll now”)
python poll.py

# Process one video
python poll.py --one VIDEO_ID

# Manual agenda regenerate
python poll.py --one VIDEO_ID --manual
```

### Scheduled polling (optional)

Use **Windows Task Scheduler** to run `python poll.py` every 15 minutes (or set `POLL_INTERVAL_MINUTES` for display only in the UI).

---

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Streamlit UI (app.py)                                          │
│  Poll now · Playlists · Profile · Video list · Usage · Batch    │
└───────────────────────────┬─────────────────────────────────────┘
                            │ start_poll_background() / start_process_one_background()
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  background_jobs.py → subprocess: poll.py                       │
│  Logs → poll_worker.log · Lock via meta poll_worker_running     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  poll.py                                                        │
│  Phase 1: sync playlists (YouTube API)                          │
│  Phase 2: process ALL pending videos (oldest first)             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  pipeline.py → process_video()                                  │
│  transcript · recon · agenda · entities · research · extract    │
└──────┬──────────────┬──────────────┬────────────────────────────┘
       │              │              │
       ▼              ▼              ▼
   llm.py        researcher.py   video_metadata.py
 Gemini/Anthropic  Tavily+Groq    YouTube description
       │              │
       ▼              ▼
 usage_tracker.py   db.py (SQLite data/insights.db)
```

**Design principles:**

- **Gemini first** for heavy JSON extraction (free daily tier when available).
- **Anthropic Haiku fallback** when Gemini quota/errors exhaust all models in a call.
- **Groq** for fast cheap tasks (agenda, research synthesis); **falls back to deep LLM** on rate limits.
- **Tavily** only for **Podcast** playlists (General skips it entirely).
- **Background subprocess** so you can browse Done videos while the queue runs.

---

## 4. Feature list (everything built)

### Core ingestion & processing

| Feature | Description |
|---------|-------------|
| Multi-playlist support | Dashboard-managed playlists table; General + Podcast kinds |
| Per-playlist profile | `extraction_focus` + optional profile JSON per playlist |
| Global user profile | About me, interests, insight style, known topics |
| Full queue processing | **Poll now** processes **all** pending videos, not one per click |
| Background worker | Subprocess via `background_jobs.py`; UI auto-refreshes every ~5s |
| Single-video process / retry | Process now, Retry, Re-process buttons |
| Transcript cascade | YouTube captions → Gemini audio (optional) → Groq Whisper |
| Channel name in header | From DB, research data, or live YouTube API |
| Video URL hidden from header | **Watch on YouTube** button only |

### AI extraction (V4 pipeline)

| Feature | Description |
|---------|-------------|
| **Recon pass** | Guest, topics, interview format, duration estimate |
| **Auto agenda** | Profile-tailored bullet agenda (Groq → Anthropic/Gemini fallback) |
| **Entity extraction** | Research targets, lists to expand, transcript URLs |
| **Targeted Tavily research** | Per-entity searches (Podcast only) |
| **Guest + topic research** | Person bio, viral context, topic briefs |
| **Holistic extraction** | Summary, guest profile, insights clusters, resources, links |
| **Anti-vague rules** | Prompts forbid “speaker mentions 50 companies” without naming them |
| **Structured output** | `structured_insights` JSON stored in DB |
| **Grouped links** | From video / From description / From research |
| **Resources panel** | Books, tools, companies, people — with or without URLs |
| **Description parsing** | URLs + resource lines from YouTube description (`video_metadata.py`) |

### Podcast-specific

| Feature | Description |
|---------|-------------|
| Deep insights layout | Richer insight cards for podcast content |
| Web research panel | Guest bio, viral things, topic research (collapsible) |
| Custom agenda override | Write agenda → **Generate custom insights** (manual pass) |
| **Dual insight copies** | **General insights** tab (auto) + **Custom agenda insights** tab (manual) — auto copy always preserved |
| Tavily-powered research | Guest (~4 searches) + topics (~9) + entities (~6) typical |

### General playlist

| Feature | Description |
|---------|-------------|
| Holistic lecture extraction | 6–10 agenda items covering full video breadth |
| `research_links_only()` | No Tavily — description text + parsed URLs only |
| Description notes panel | Parsed description excerpt in UI |

### LLM & cost optimization

| Feature | Description |
|---------|-------------|
| Gemini model chain | Primary → `GEMINI_FALLBACK_MODELS` (e.g. 2.0-flash, 2.5-flash-lite) |
| Anthropic Haiku fallback | Automatic when Gemini fails (`FALLBACK_TO_ANTHROPIC=true`) |
| Groq → deep LLM fallback | Agenda + research synthesis fall back on Groq rate limits |
| Quota skip within run | After Gemini quota hit, later steps skip Gemini retries → Anthropic directly |
| `LLM_PRIMARY=anthropic` | Optional: skip Gemini entirely for deep calls |
| Overnight Anthropic batch | Message Batches API ~50% off (`batch_process.py`) |

### Usage tracking

| Feature | Description |
|---------|-------------|
| Per-run call log | Every Gemini, Anthropic, Groq, Tavily, YouTube call recorded |
| Per-video usage panel | Bottom of Done video page — metrics + expandable call log |
| Sidebar: Last run | Always visible after processing |
| Sidebar: Lifetime totals | Collapsed expander — cumulative stats |
| Sidebar: Call log · last run | Full operation-level log |
| Stored in DB | `videos.usage_data` + meta `usage_lifetime` |

### UI / UX

| Feature | Description |
|---------|-------------|
| Dark theme custom CSS | Hero, stats, panels, insight cards |
| Video list filters | All / General / Podcast |
| Status pills | Pending, Processing, Done, Failed, Batch queued |
| Chat with video | Full-transcript Q&A on Done videos |
| Stuck processing reset | Button to return Processing → Pending |
| Background banner | Shows when worker is running |

### Removed / reverted

| Change | Notes |
|--------|-------|
| Social link filter | **Reverted** — all transcript URLs are kept (user request) |

---

## 5. Playlist modes: General vs Podcast

| | **General** | **Podcast** |
|---|-------------|-------------|
| **Typical content** | Lectures, tutorials, talks | Interviews, long conversations |
| **Auto agenda** | 6–10 items, full breadth | 4–7 items, profile-tailored |
| **Web research (Tavily)** | ❌ None | ✅ Guest + topics + entities |
| **Research helper** | `research_links_only()` | `research_all()` |
| **UI headline** | “Insights” | “Deep insights” |
| **Custom agenda** | N/A (same pipeline) | Optional second insight copy |
| **Web research panel** | Description notes only | Full guest/topic research |
| **Typical API cost** | Low (mostly free tier) | Higher (Tavily + more LLM tokens) |

---

## 6. Processing pipeline (step by step)

### Shared steps (both kinds)

```
1. get_transcript(video_id)
      youtube_captions → gemini_audio → groq_whisper

2. analyze_video_description(video_id)     [needs YOUTUBE_API_KEY]
      channel title, description text, URLs, resource lines

3. _extract_urls_from_transcript(transcript)

4. _recon_pass()                           [call_deep_llm · operation=recon]
      guest, topics, is_interview, duration

5. Auto agenda
      Podcast: _generate_auto_agenda()     [Groq → deep LLM fallback]
      General: _generate_general_agenda()  [Groq → deep LLM fallback]

6. _extract_research_targets()             [call_deep_llm · operation=entities]
      research_targets[], lists_to_expand[], urls_in_transcript[]
```

### Podcast-only continuation

```
7. research_all()
      ├── _research_person(guest)         ~4 Tavily searches + Groq JSON
      ├── _research_topics(top 3 topics)  ~6 Tavily searches + Groq JSON each
      └── research_targets(≤MAX_RESEARCH_TARGETS)  ~1 Tavily + Groq JSON each

8. _holistic_extraction()                  [call_deep_llm · operation=holistic_extract]
      Full JSON: summary, guest_profile, resources, links, insights[]

9. _merge_structured_output()
      Merge research links + description + transcript URLs
```

### General-only continuation

```
7. research_links_only()                   [no Tavily — description + URLs only]

8. _holistic_extraction()                  [same as podcast]

9. _merge_structured_output()
```

### Manual agenda pass (Podcast, `--manual`)

Same pipeline but:

- Uses `user_agenda` from DB instead of auto agenda
- Saves to `manual_summary` + `manual_key_points` (auto copy untouched)
- Requires non-empty custom agenda

### Chat (on-demand, UI only)

```
chat_with_video() → call_deep_llm(json_mode=False, operation=chat)
Uses full transcript + last 10 chat turns + profile prompt
```

---

## 7. LLM strategy & fallbacks

### Deep LLM (`llm.py` → `call_deep_llm`)

Used for: **recon**, **entities**, **holistic_extract**, **chat**, and Groq fallbacks.

```
┌─────────────────────────────────────────────────────────────┐
│  LLM_PRIMARY=gemini (default)                               │
│                                                             │
│  1. Try Gemini model chain:                                 │
│     GEMINI_CHAT_MODEL → GEMINI_FALLBACK_MODELS              │
│     (retries with backoff on 429/503)                       │
│                                                             │
│  2. If all Gemini models fail AND quota flag set:           │
│     Skip Gemini for rest of this worker run                 │
│                                                             │
│  3. If FALLBACK_TO_ANTHROPIC=true + ANTHROPIC_API_KEY:      │
│     → Claude Haiku (DEEP_MODEL)                             │
│                                                             │
│  4. If LLM_PRIMARY=anthropic:                               │
│     Anthropic first, optional Gemini fallback               │
└─────────────────────────────────────────────────────────────┘
```

**Env loaded at runtime** in `poll.py` and `pipeline.py` (before imports) so background workers see keys.

### Fast LLM (`pipeline._call_groq` + `researcher._call_groq_json`)

Used for: **auto agenda**, **research synthesis** (after Tavily).

```
Groq (llama-3.3-70b-versatile, free tier)
    ↓ on any error (incl. 429 rate limit)
call_deep_llm (Gemini → Anthropic)
```

### Important: misleading errors (fixed)

Previously, **any** HTTP 429 (including **Groq** during podcast research) was shown as *“Gemini daily quota used up.”* The app now:

- Labels Groq vs Gemini vs Anthropic errors separately
- Falls back automatically instead of failing silently

### Log lines to watch in `poll_worker.log`

| Log line | Meaning |
|----------|---------|
| `[poll] Providers: gemini=True anthropic=True ...` | Keys visible to worker |
| `[llm] Gemini fallback model succeeded: gemini-2.5-flash-lite` | Lite model used |
| `[llm] Gemini failed — ...` | Full Gemini chain failed |
| `[llm] Falling back to Anthropic Haiku` | Anthropic attempt starting |
| `[llm] Anthropic fallback succeeded` | Paid fallback worked |
| `[pipeline] Groq failed ... — using deep LLM fallback` | Agenda step switched |
| `[research] Groq failed ... — using deep LLM fallback` | Research synthesis switched |

---

## 8. API providers, usage & pricing

> Prices below are **indicative** (June 2026). Always check official pricing pages before budgeting.  
> The app **estimates** tokens as `len(text) // 4` and Anthropic cost in `usage_tracker.py`.

### Gemini (Google AI Studio)

| Item | Details |
|------|---------|
| **Role** | Primary deep LLM (recon, entities, holistic, chat) |
| **Default model** | `gemini-2.5-flash` |
| **Fallbacks** | `gemini-2.0-flash`, `gemini-2.5-flash-lite` |
| **Pricing in app** | Treated as **$0** (free tier / AI Studio credits) |
| **Typical limits** | Daily quota on flash; lite often still works when flash is exhausted |
| **Get key** | [aistudio.google.com](https://aistudio.google.com) |

### Anthropic Claude Haiku 4.5

| Item | Details |
|------|---------|
| **Role** | Fallback deep LLM + overnight batch |
| **Default model ID** | `claude-haiku-4-5-20251001` |
| **Standard API** | **$1.00 / 1M input tokens**, **$5.00 / 1M output tokens** |
| **Batch API (50% off)** | **$0.50 / 1M input**, **$2.50 / 1M output** |
| **Get key** | [console.anthropic.com](https://console.anthropic.com) |

### Groq

| Item | Details |
|------|---------|
| **Role** | Fast agenda generation; JSON synthesis after Tavily searches |
| **Default model** | `llama-3.3-70b-versatile` |
| **Pricing in app** | **$0** (free tier tracked) |
| **Limits** | Rate limits (429) — app falls back to deep LLM |
| **Also used for** | Whisper transcription fallback (`transcriber.py`) |
| **Get key** | [console.groq.com](https://console.groq.com) |

### Tavily

| Item | Details |
|------|---------|
| **Role** | Web search for **Podcast** research only |
| **Search depth** | `advanced` |
| **Credits in app** | `TAVILY_CREDITS_PER_SEARCH=2` per search (configurable) |
| **Typical podcast video** | ~19–20 searches (guest 4 + topics 9 + entities 6 at default cap) |
| **Example cost** | 700 credits × $0.008/credit ≈ **$5.60** (user-reported over 2 days) |
| **General playlist** | **0 Tavily credits** |
| **Get key** | [tavily.com](https://tavily.com) |

### YouTube Data API v3

| Item | Details |
|------|---------|
| **Role** | Playlist sync, video descriptions, channel titles |
| **Usage in app** | ~1 unit per playlist page + ~1 per video description fetch |
| **Default quota** | 10,000 units/day (Google Cloud project) |
| **Get key** | Google Cloud Console → YouTube Data API v3 |

### Cost tracking in the app

`usage_tracker.py` records each call and computes:

- `gemini_calls`, `anthropic_calls`, `groq_calls`
- `tavily_searches`, `tavily_credits_est`
- `youtube_api_calls`
- `total_input_tokens_est`, `total_output_tokens_est`
- `cost_usd_est` (Anthropic only; Gemini/Groq shown as free tier)

---

## 9. Dashboard UI guide

### Sidebar (top → bottom)

1. **🔄 Poll now** — sync playlists + process entire pending queue in background
2. **Background processing banner** — auto-refreshes while worker runs
3. **🧠 My Profile** — global extraction preferences
4. **📋 Playlists** — add/edit/disable playlists, per-playlist extraction focus
5. **Videos** — filter All / General / Podcast; click to select
6. **Last run usage** — metrics from most recent processed video
7. **Lifetime totals** — cumulative usage (collapsed)
8. **🌙 Overnight batch** — queue pending for Anthropic batch; run batch now
9. **📋 Call log · last run** — operation-level detail

### Main area (Done video)

| Section | Content |
|---------|---------|
| Header | Thumbnail, title, type/status pills, channel, Watch on YouTube |
| Actions | Re-process / Process now / Retry |
| Auto agenda | Bullet list used for extraction |
| Custom agenda (podcast) | Override + Generate custom insights |
| Insights | General tab + Custom tab (podcast with manual pass) |
| Resources | Books, tools, companies, people |
| Links | Grouped: from video / description / research |
| Web research (podcast) | Guest + topic background |
| Description notes (general) | Parsed description |
| Chat | Q&A over full transcript |
| API usage | Per-video metrics + call log |

### Video statuses

| Status | Meaning |
|--------|---------|
| `pending` | Queued, not started |
| `processing` | Worker is running on this video |
| `done` | Successfully processed |
| `failed` | Error stored in `error_message` — use Retry |
| `batch_queued` | Waiting for overnight Anthropic batch |
| `awaiting_agenda` | Legacy; use Process now |

---

## 10. Configuration reference (`.env`)

Copy from `config.example.env`:

```env
# ── Required for basic operation ──
GROQ_API_KEY=              # Agenda + research synthesis + Whisper
YOUTUBE_API_KEY=           # Playlists + descriptions (links need this)
PLAYLIST_ID=               # Legacy fallback if no DB playlists
PODCASTS_PLAYLIST_ID=      # Legacy fallback

# ── LLM strategy ──
LLM_PRIMARY=gemini         # gemini | anthropic
FALLBACK_TO_ANTHROPIC=true

GEMINI_API_KEY=
GEMINI_CHAT_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODELS=gemini-2.0-flash,gemini-2.5-flash-lite

ANTHROPIC_API_KEY=
DEEP_MODEL=claude-haiku-4-5-20251001
DEEP_MAX_OUTPUT_TOKENS=16384

BATCH_USE_ANTHROPIC=true   # Overnight batch uses Anthropic

# ── Research (Podcast only) ──
TAVILY_API_KEY=
TAVILY_CREDITS_PER_SEARCH=2
MAX_RESEARCH_TARGETS=6     # Lower = fewer Tavily/Groq calls

# ── Models ──
GROQ_CHAT_MODEL=llama-3.3-70b-versatile

# ── Batch timing ──
BATCH_POLL_SEC=30
BATCH_TIMEOUT_SEC=86400
POLL_INTERVAL_MINUTES=15   # Display hint in sidebar
```

### Recommended when Gemini quota is exhausted

```env
LLM_PRIMARY=anthropic
FALLBACK_TO_ANTHROPIC=true
MAX_RESEARCH_TARGETS=3
```

---

## 11. Background jobs & logging

### How background processing works

1. UI calls `background_jobs.start_poll_background()` or `start_process_one_background()`
2. Spawns `python poll.py` (or `--one VIDEO_ID`) as subprocess
3. stdout/stderr → **`poll_worker.log`** (append)
4. Meta flag `poll_worker_running=1` prevents duplicate workers
5. On exit, flag cleared and progress meta reset

### Poll behavior (`poll.py`)

- **Phase 1:** Fetch all enabled playlists from YouTube; register new videos as `pending`
- **Phase 2:** Process **all** pending videos oldest-first (not limited to 1)
- Logs provider status at start of each video

### Log file location

```
D:\Cursor Projects\CursorP1\poll_worker.log
```

### Database location

```
D:\Cursor Projects\CursorP1\data\insights.db
D:\Cursor Projects\CursorP1\data\profile.json
```

---

## 12. Overnight batch mode

For large backlogs when you want **50% off** Anthropic token pricing:

1. Sidebar → **Queue pending for batch** (optional: includes failed)
2. **Run batch queue now** (or run `python batch_process.py` from CLI)
3. Uses Anthropic **Message Batches API** for recon + entities + holistic phases
4. Tavily/Groq research still runs sequentially during prep (not batched)

Set `BATCH_USE_ANTHROPIC=false` to use sequential Gemini → Anthropic instead.

---

## 13. Database & data model

### `videos` table (key columns)

| Column | Purpose |
|--------|---------|
| `video_id` | YouTube ID (PK) |
| `title`, `url` | Video metadata |
| `status` | pending / processing / done / failed / batch_queued |
| `playlist_type` | `general` or `podcast` |
| `playlist_id` | FK to playlists table |
| `summary`, `key_points` | Auto-generated insights |
| `manual_summary`, `manual_key_points` | Custom agenda insights |
| `auto_agenda` | Generated agenda bullets |
| `user_agenda` | User-written custom agenda |
| `research_data` | JSON: guest, topics, targeted, links |
| `structured_insights` | JSON: full V4 structured output |
| `usage_data` | JSON: per-video API call log |
| `channel_name` | YouTube channel |
| `transcript_source` | youtube_captions / gemini_audio / groq_whisper |
| `error_message` | User-facing failure reason |

### `playlists` table

| Column | Purpose |
|--------|---------|
| `playlist_id` | YouTube playlist ID (PK) |
| `name`, `description` | Display |
| `kind` | `general` or `podcast` |
| `profile_json` | Per-playlist profile overrides |
| `extraction_focus` | Free-text focus for this playlist |
| `enabled` | 1/0 |

### `meta` table

| Key | Purpose |
|-----|---------|
| `last_poll_at` | Last successful poll timestamp |
| `poll_worker_running` | Background lock |
| `poll_progress_done/total` | Queue progress |
| `usage_lifetime` | Cumulative usage JSON |
| `batch_status` | Last batch run result |

---

## 14. Source file map

| File | Responsibility |
|------|----------------|
| `app.py` | Streamlit dashboard — UI, sidebar, chat, usage panels |
| `poll.py` | CLI poll + `--one` processing; loads `.env` first |
| `background_jobs.py` | Subprocess spawn, worker lock, log file |
| `pipeline.py` | Full video pipeline, transcript, agenda, extraction, chat |
| `llm.py` | Gemini / Anthropic / batch API, fallbacks, error messages |
| `researcher.py` | Tavily search + Groq synthesis; `research_all`, `research_links_only` |
| `video_metadata.py` | YouTube description + URL parsing |
| `usage_tracker.py` | Per-run API accounting, lifetime totals |
| `db.py` | SQLite schema, migrations, CRUD |
| `batch_process.py` | Anthropic overnight batch queue |
| `youtube_monitor.py` | Playlist fetching via YouTube API |
| `transcriber.py` | yt-dlp audio + Groq Whisper |
| `config.example.env` | Environment template |

### Dependencies (`requirements.txt`)

```
python-dotenv, groq, google-genai, anthropic, requests,
streamlit, youtube-transcript-api, yt-dlp, tavily-python
```

---

## 15. Version history & changelog

### V1 — Original (README baseline)

- Single playlist, Groq summary + key points
- YouTube captions + Groq Whisper
- Basic Streamlit list
- SQLite storage

### V2 — Dual playlists

- General vs Podcast playlist types
- User agenda for podcasts (awaiting_agenda flow)
- Profile / knowledge base

### V3 — Research & profiles

- Tavily guest + topic research
- Auto agenda from profile
- Manual regenerate
- Multi-pass pipeline (recon → research → extract)
- Anthropic batch groundwork

### V4 — Exhaustive extraction (current)

- **Multi-playlist manager** in dashboard
- **Entity extraction pass** + targeted Tavily searches
- **Structured insights** (guest profile, resources, insight clusters)
- **Grouped links** (video / description / research)
- **General playlist upgrade** — same holistic pipeline, no Tavily
- **Anti-vague prompt rules**
- **Channel name** in header; URL removed from header
- **Usage tracking** — per-run + lifetime + call logs
- **Sidebar overhaul** — Poll at top, background banner
- **Background subprocess** processing
- **Poll processes full queue**
- **Dual insight copies** — auto vs manual agenda tabs
- **Chat with video**

### LLM strategy update

- Gemini primary (free credits)
- Anthropic Haiku fallback
- Optional overnight batch (50% off)
- Runtime env reads in workers
- Groq → deep LLM fallback (June 2026 fix)
- Clearer error messages (Groq vs Gemini vs Anthropic)
- Gemini quota skip flag within worker run

### Reverted

- Social/profile URL filter on transcript links (user requested all URLs kept)

---

## 16. Troubleshooting

### “Gemini daily quota used up — Anthropic fallback…”

**Check `poll_worker.log` first.**

| If you see… | Likely cause | Fix |
|-------------|--------------|-----|
| `Gemini fallback model succeeded: flash-lite` then failure | Groq rate limit during research | Retry — Groq now falls back to Anthropic |
| No `Falling back to Anthropic` lines | Failure before deep LLM needed | Check Groq/Tavily/JSON parse errors in log |
| `Anthropic failed — credit balance` | No Anthropic credits | Add billing at console.anthropic.com |
| `Anthropic failed — 404 model` | Wrong `DEEP_MODEL` | Try `claude-3-5-haiku-latest` or verify model ID |

**Quick workaround:**

```env
LLM_PRIMARY=anthropic
```

Restart Streamlit, click **Retry**.

### Failed videos not retrying

1. Restart Streamlit (pick up code changes)
2. Click **Retry** (sets status → pending → background process)
3. Or **Poll now** to drain full queue

### Missing links / resources

- Set `YOUTUBE_API_KEY` (description fetch)
- Click **Re-process video** on Done videos processed before V4

### Stuck on “Processing”

- Click **Reset stuck processing**
- Check if `poll_worker.log` still updating
- Delete meta lock manually only if no python worker running: `poll_worker_running` in DB

### Background worker not starting

- Another worker may be running (`poll_worker_running=1`)
- Wait for prior run to finish or restart app

### Install issues

```powershell
cd "D:\Cursor Projects\CursorP1"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Ensure **ffmpeg** is on PATH for audio transcription.

---

## 17. Typical cost per video (estimates)

> Rough orders of magnitude; actual usage shown per video in the dashboard.

### General playlist (~45 min lecture)

| Provider | Typical usage | Est. cost |
|----------|---------------|-----------|
| Gemini | 3 deep calls (recon, entities, holistic) | $0 (free tier) |
| Groq | 1 agenda call | $0 |
| Tavily | 0 | $0 |
| YouTube API | 1–2 units | $0 |
| Anthropic | Only if Gemini fails | ~$0.01–0.15/video depending on transcript size |

### Podcast (~60 min interview, default settings)

| Provider | Typical usage | Est. cost |
|----------|---------------|-----------|
| Gemini | 3 deep calls | $0 (or lite fallback) |
| Groq | 1 agenda + ~10 research syntheses | $0 (unless rate limited → Anthropic) |
| Tavily | ~19–20 advanced searches ≈ 38–40 credits | ~$0.30–0.32 at $0.008/credit |
| Anthropic fallback | Holistic + possible Groq replacements | ~$0.05–0.25 |
| **Typical total** | | **~$0.35–0.60/video** if Tavily + some Anthropic |

### Reducing cost

- `MAX_RESEARCH_TARGETS=3` — fewer entity searches
- General playlist for non-interview content — **zero Tavily**
- `LLM_PRIMARY=anthropic` + `BATCH_USE_ANTHROPIC=true` — batch overnight at 50% off
- Process during Gemini free tier hours; lite model absorbs quota pressure

---

## Related docs in this repo

| File | Contents |
|------|----------|
| `README.md` | Short setup (outdated in places — this guide supersedes it) |
| `PLAN.md` | Original project plan |
| `IMPLEMENTATION_PLAN_V4.md` | V4 design spec (implemented) |
| `IMPLEMENTATION_PLAN_V3.md` | Prior version spec |
| `URDU_LANGUAGE_SUPPORT.md` | Roman Urdu / transcription notes |
| `config.example.env` | Environment template |

---

*For questions about a specific failed video, attach the relevant section of `poll_worker.log` starting from `[poll] Providers:` through `[poll] Failed:` or `[poll] Done:`.*
