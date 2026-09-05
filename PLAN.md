# YouTube Insight Agent — Project Documentation

**Project folder:** `D:\Cursor Projects\CursorP1`  
**Last updated:** June 14, 2026  
**Current status:** Phase 1 ✅ · Phase 2 ✅ · Phase 3 (V3 hybrid APIs) ✅ · **Phase 4 (V4)** ✅

> See [`IMPLEMENTATION_PLAN_V4.md`](IMPLEMENTATION_PLAN_V4.md) for V4 details.

> **This is the master doc** for vision, phases, features, file inventory, env vars, how to run, and changelog.

---

## Vision

You browse YouTube and add videos to playlists. A background agent detects new videos, transcribes them, extracts insights, and shows them in a local dashboard. No manual URL pasting — playlists are the only input.

Two modes:
- **General playlist** → auto full summary + key points
- **Podcast playlist** → you write a custom **agenda** per video; agent extracts only what you asked for

---

## Phase 1 — Core agent (DONE)

### Features added

| Feature | Description |
|---------|-------------|
| Playlist polling | `poll.py` watches `PLAYLIST_ID` every 15 min (or manual) |
| New video detection | Compares playlist vs SQLite; skips already-processed |
| Transcription | YouTube captions first → Groq Whisper fallback (yt-dlp + ffmpeg) |
| Summarization | Groq LLM → summary + key points |
| SQLite storage | `data/insights.db` — status, dedup, insights |
| Streamlit dashboard | View videos, poll button, thumbnails |
| Reel transcriber reuse | `transcriber.py` adapted from `transcriber_previous.py` |

### Your general playlist

| Field | Value |
|-------|--------|
| Name | **P_AI_tutorials_IMP** |
| ID | `PLFWn41aLEAWnm40MpKbvDSxMkm5LEBDn4` |
| Env var | `PLAYLIST_ID` |

---

## Phase 2 — Podcast playlist + custom agenda (DONE)

### Features added

| Feature | Description |
|---------|-------------|
| Second playlist | `PODCASTS_PLAYLIST_ID` in `.env` |
| Agenda-gated processing | Podcast videos stay **Needs agenda** until you fill in focus areas |
| Agenda text box | Bullet points per video in dashboard (e.g. tech stack, remote job tips, salary) |
| Agenda-focused LLM | Ignores off-topic content; answers only your agenda |
| Knowledge base | Sidebar → `data/knowledge_base.txt` — skip topics you already know |
| Regenerate | Change agenda and re-run insights |
| UI overhaul | Dark theme, General/Podcast filter, stats, purple/indigo badges |
| Dual playlist poll | `poll.py` polls both playlists in one run |

### Podcast workflow

1. Add video to **Podcast playlist** on YouTube
2. Run `python poll.py` or click **Poll playlists**
3. Video appears as **Needs agenda**
4. Open in dashboard → write your agenda:
   ```
   • Focus mainly on the tech stack
   • How to get a remote job
   • Sources for remote jobs
   • What salary they mention
   ```
5. Click **Generate insights**

---

## Phase 3 — Planned (NOT built yet)

- Notion export + Notion knowledge base sync
- Cloud / always-on polling (GitHub Actions, Railway)
- Email/Slack notifications when insights ready
- Better handling for 2+ hour podcasts
- Light theme toggle
- Private playlist support via OAuth

---

## How to run

```powershell
cd "D:\Cursor Projects\CursorP1"
python poll.py
python -m streamlit run app.py
```

### Optional: background polling

Windows Task Scheduler every 15 min:
- Program: `python`
- Arguments: `"D:\Cursor Projects\CursorP1\poll.py"`
- Start in: `D:\Cursor Projects\CursorP1`

---

## How to test

| Test | Steps | Expected |
|------|-------|------------|
| General playlist | Add video → `python poll.py` → open dashboard | Status **Done**, summary + key points |
| Podcast agenda | Add `PODCASTS_PLAYLIST_ID`, add video → poll → write agenda → Generate | Insights match your bullets only |
| Knowledge base | Add text in sidebar → Save → regenerate podcast | Skips topics you listed as known |
| Regenerate | Edit agenda on Done podcast → Regenerate | New key points reflect new agenda |

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Groq Whisper + chat LLM |
| `YOUTUBE_API_KEY` | Yes | YouTube Data API v3 |
| `PLAYLIST_ID` | Yes | General playlist (auto-process) |
| `PODCASTS_PLAYLIST_ID` | For Phase 2 | Podcast playlist (agenda required) |
| `POLL_INTERVAL_MINUTES` | No | Default `15` |
| `GROQ_CHAT_MODEL` | No | Default `llama-3.3-70b-versatile` |

Template: `config.example.env`

---

## File inventory

All paths relative to `D:\Cursor Projects\CursorP1`.

### Core application

| File | Purpose | Phase |
|------|---------|-------|
| `poll.py` | Poll both playlists; process general auto; register podcast | 1, 2 |
| `pipeline.py` | Transcript + LLM; agenda-aware prompts for podcast | 1, 2 |
| `youtube_monitor.py` | YouTube API playlist listing | 1 |
| `transcriber.py` | Groq Whisper + yt-dlp + ffmpeg chunking | 1 |
| `db.py` | SQLite, agenda, playlist_type, knowledge base | 1, 2 |
| `app.py` | Streamlit dashboard + agenda UI | 1, 2 |

### Config & docs

| File | Purpose |
|------|---------|
| `.env` | Your secrets (local only) |
| `config.example.env` | Env template |
| `requirements.txt` | Python dependencies |
| `README.md` | Quick setup guide |
| **`PLAN.md`** | **This file — master documentation** |
| `transcriber_previous.py` | Original Instagram reel transcriber (reference) |

### Generated / runtime

| Path | Purpose |
|------|---------|
| `data/insights.db` | Videos, status, summaries, agendas |
| `data/knowledge_base.txt` | Your “already know” topics (Phase 2) |
| `.cursor/sandbox.json` | Cursor agent write permissions |
| `__pycache__/` | Python cache |

### Safe to delete

| File | Notes |
|------|-------|
| `test.txt` | Leftover test file |

### System dependencies

| Tool | Why |
|------|-----|
| Python 3.x | Runtime |
| ffmpeg | Audio download + Whisper chunking |
| Groq API | Transcription + summarization |
| YouTube Data API v3 | Read playlists |

---

## Architecture

```
YouTube playlists (General + Podcast)
        ↓
    poll.py  ← every 15 min or manual
        ↓
  youtube_monitor.py
        ↓
  pipeline.py  ← captions or Whisper → Groq LLM
        ↓
  data/insights.db
        ↓
    app.py  ← dashboard (+ agenda for podcast)
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `YOUTUBE_API_KEY is not set` | `.env` must be named exactly `.env` next to `poll.py` |
| `.env.env` double extension | Rename to `.env` |
| `403 API_KEY_SERVICE_BLOCKED` | Allow YouTube Data API v3 on API key |
| `ffmpeg not found` | `winget install ffmpeg`, restart terminal |
| `streamlit` not recognized | Use `python -m streamlit run app.py` |
| Podcast not appearing | Add `PODCASTS_PLAYLIST_ID` to `.env` |
| Stuck on Needs agenda | Write agenda in dashboard → Generate insights |

---

## Changelog

| Date | Change |
|------|--------|
| Jun 14, 2026 | **Phase 1** — playlist poll, transcribe, summarize, SQLite, dashboard |
| Jun 14, 2026 | First video processed (*6 AI Agency Offers…*) |
| Jun 14, 2026 | Dashboard UI v1 (dark theme, sidebar, thumbnails) |
| Jun 14, 2026 | Project consolidated to `D:\Cursor Projects\CursorP1` |
| Jun 14, 2026 | Fixed folder read-only permissions + `.cursor/sandbox.json` |
| Jun 14, 2026 | **Phase 2** — second playlist, custom agenda, knowledge base, UI v2 |
| Jun 14, 2026 | `PODCASTS_PLAYLIST_ID` added to config; dual-playlist poll |
| Jun 14, 2026 | `PLAN.md` updated as master documentation |

---

## Other docs (shorter / specific)

| File | Use for |
|------|---------|
| `README.md` | Quick install + run |
| `PLAN.md` | **Everything — phases, features, files, changelog** |
| `config.example.env` | Copy to create `.env` |
