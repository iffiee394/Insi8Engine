# BUILD SPEC — YouTube Insight Agent Production Features

> **For Cursor / AI coding assistant.** Each section is a self-contained implementation task.
> Build in the order listed. Each task includes: what to build, which files to touch, the technical approach, and acceptance criteria.
> 
> **Important context:** Read `PROJECT_GUIDE.md` for full architecture. Key files: `app.py` (Streamlit UI), `pipeline.py` (processing pipeline), `llm.py` (LLM calls), `researcher.py` (Tavily research), `db.py` (SQLite), `usage_tracker.py` (cost tracking), `config.example.env` (env template).

---

## Task 0: Config Cleanup & Centralization

### Goal
Replace scattered `os.getenv()` calls with a single `config.py` module. Remove all hardcoded Windows paths. Make all file paths OS-agnostic.

### Files to Create
- `config.py`

### Files to Modify
- `app.py`, `poll.py`, `pipeline.py`, `llm.py`, `researcher.py`, `db.py`, `background_jobs.py`, `batch_process.py`, `usage_tracker.py`, `transcriber.py`, `video_metadata.py`, `youtube_monitor.py`

### Implementation

**config.py:**
```python
"""Centralized configuration — single source of truth for all settings."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths (all relative to project root, OS-agnostic) ──
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
DB_PATH = DATA_DIR / "insights.db"
PROFILE_PATH = DATA_DIR / "profile.json"
LOG_PATH = Path(os.getenv("LOG_PATH", PROJECT_ROOT / "poll_worker.log"))
FIXTURES_DIR = DATA_DIR / "fixtures"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── API Keys ──
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# ── LLM Strategy ──
LLM_PRIMARY = os.getenv("LLM_PRIMARY", "gemini")
FALLBACK_TO_ANTHROPIC = os.getenv("FALLBACK_TO_ANTHROPIC", "true").lower() == "true"
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.0-flash,gemini-2.5-flash-lite").split(",")
]
DEEP_MODEL = os.getenv("DEEP_MODEL", "claude-haiku-4-5-20251001")
DEEP_MAX_OUTPUT_TOKENS = int(os.getenv("DEEP_MAX_OUTPUT_TOKENS", "16384"))

# ── Research ──
TAVILY_CREDITS_PER_SEARCH = int(os.getenv("TAVILY_CREDITS_PER_SEARCH", "2"))
MAX_RESEARCH_TARGETS = int(os.getenv("MAX_RESEARCH_TARGETS", "6"))

# ── Models ──
GROQ_CHAT_MODEL = os.getenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")

# ── Batch ──
BATCH_USE_ANTHROPIC = os.getenv("BATCH_USE_ANTHROPIC", "true").lower() == "true"
BATCH_POLL_SEC = int(os.getenv("BATCH_POLL_SEC", "30"))
BATCH_TIMEOUT_SEC = int(os.getenv("BATCH_TIMEOUT_SEC", "86400"))
POLL_INTERVAL_MINUTES = int(os.getenv("POLL_INTERVAL_MINUTES", "15"))

# ── Embedding (new for semantic search) ──
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-004")


def validate() -> dict:
    """Check config completeness. Returns {status, missing_required, missing_optional, warnings}."""
    required = {
        "GROQ_API_KEY": GROQ_API_KEY,
        "YOUTUBE_API_KEY": YOUTUBE_API_KEY,
    }
    recommended = {
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    }
    optional = {
        "TAVILY_API_KEY": TAVILY_API_KEY,
    }

    missing_required = [k for k, v in required.items() if not v]
    missing_recommended = [k for k, v in recommended.items() if not v]
    missing_optional = [k for k, v in optional.items() if not v]

    warnings = []
    if not GEMINI_API_KEY and not ANTHROPIC_API_KEY:
        warnings.append("No deep LLM configured — need at least GEMINI_API_KEY or ANTHROPIC_API_KEY")
    if LLM_PRIMARY == "gemini" and not GEMINI_API_KEY:
        warnings.append("LLM_PRIMARY=gemini but GEMINI_API_KEY is missing — will fail on deep calls")
    if FALLBACK_TO_ANTHROPIC and not ANTHROPIC_API_KEY:
        warnings.append("FALLBACK_TO_ANTHROPIC=true but ANTHROPIC_API_KEY is missing — no fallback available")

    return {
        "ok": len(missing_required) == 0 and len(warnings) == 0,
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "missing_optional": missing_optional,
        "warnings": warnings,
    }
```

**Then:** Find every `os.getenv(...)` call in all other files and replace with imports from `config`. Find every hardcoded path string (especially `D:\...`, `data/insights.db`, `poll_worker.log`, `data/profile.json`) and replace with `config.DB_PATH`, `config.LOG_PATH`, `config.PROFILE_PATH` etc. Use `pathlib.Path` for all path joins — never string concatenation.

### Acceptance Criteria
- `grep -r "os.getenv" *.py` returns only `config.py`
- `grep -rn "D:\\\\" *.py` returns nothing
- `grep -rn "data/insights" *.py` returns only `config.py`
- App runs identically on Windows and Linux
- `python -c "from config import validate; print(validate())"` prints config status

---

## Task 1: Timestamp-Linked Insights

### Goal
Each insight cluster in the structured output includes an approximate start timestamp. Timestamps render as clickable YouTube links.

### Files to Modify
- `pipeline.py` — update holistic extraction prompt
- `app.py` — render timestamp links in insight display
- `db.py` — no schema change needed (`structured_insights` is already JSON)

### Implementation

**Step 1: Update the holistic extraction prompt in `pipeline.py`**

Find the `_holistic_extraction()` method (or the prompt construction for `operation=holistic_extract`). The prompt already requests structured JSON with insight clusters. Add this to the prompt instructions:

```
For each insight in the "insights" array, include a "timestamp_seconds" field 
with the approximate start time in the video (in seconds) where this topic is 
primarily discussed. Use the transcript timing data to determine this. 
If the transcript has no timing data, set timestamp_seconds to null.

Also include a "timestamp_range_end" field (seconds) for the approximate end 
of the discussion on that topic. This enables the timeline visualization.

Example insight object:
{
  "title": "Why the company pivoted from B2C to B2B",
  "timestamp_seconds": 1423,
  "timestamp_range_end": 1690,
  "content": "...",
  "tags": [...]
}
```

**Step 2: Pass transcript with timing data**

Check how the transcript is currently passed to the holistic extraction prompt. If it's plain text (no timestamps), modify to include timing markers. The transcript from YouTube captions and Whisper both have segment-level timestamps. Format them inline:

```
[00:00] Introduction and welcome
[02:15] Guest background — grew up in Lagos, moved to SF
[05:30] First startup attempt and why it failed
...
```

Find where the transcript is prepared for the prompt (likely in `pipeline.py`'s `process_video()` or `_holistic_extraction()`). If the raw transcript segments have start times, format them as `[MM:SS] text` before passing to the LLM. If the transcript is already plain text at that point, look upstream at `transcriber.py` or the YouTube captions fetch to preserve timing data.

**Step 3: Render in UI (`app.py`)**

Find where insight clusters are rendered (look for `structured_insights` display logic). For each insight that has a non-null `timestamp_seconds`:

```python
def format_timestamp_link(video_id: str, seconds: int) -> str:
    """Create a clickable YouTube timestamp link."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        label = f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        label = f"{minutes}:{secs:02d}"
    url = f"https://www.youtube.com/watch?v={video_id}&t={seconds}s"
    return f"[{label}]({url})"
```

Render this next to each insight title. Use `st.markdown(timestamp_link, unsafe_allow_html=False)` — Streamlit renders Markdown links natively.

### Acceptance Criteria
- Processed videos have `timestamp_seconds` in each insight object within `structured_insights`
- Each insight in the UI shows a clickable timestamp
- Clicking the timestamp opens YouTube at the correct position (±30 seconds tolerance is fine)
- Videos with no timing data (e.g., plain text transcripts) gracefully show insights without timestamps (no crash, no empty links)

---

## Task 2: Visual Timeline Component

### Goal
A horizontal density bar showing where insights cluster across the video duration, rendered above the insights section.

### Files to Create
- `components/timeline.py` (or inline in `app.py` if you prefer no new directory)

### Files to Modify
- `app.py` — add timeline rendering above insights

### Implementation

Create an HTML/CSS component rendered via `st.components.v1.html()`:

```python
def render_timeline(video_id: str, duration_seconds: int, insights: list[dict]) -> None:
    """Render a visual timeline bar showing insight density."""
    
    if not duration_seconds or not insights:
        return
    
    # Build segments from insight timestamps
    segments = []
    for ins in insights:
        start = ins.get("timestamp_seconds")
        end = ins.get("timestamp_range_end")
        if start is not None:
            segments.append({
                "start_pct": (start / duration_seconds) * 100,
                "end_pct": ((end or start + 60) / duration_seconds) * 100,
                "title": ins.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}&t={start}s"
            })
    
    if not segments:
        return
    
    # Generate HTML
    segment_html = ""
    for seg in segments:
        width = max(seg["end_pct"] - seg["start_pct"], 1.5)  # min visible width
        segment_html += f'''
            <a href="{seg['url']}" target="_blank" class="tl-seg" 
               style="left:{seg['start_pct']:.1f}%;width:{width:.1f}%"
               title="{seg['title']}">
            </a>
        '''
    
    html = f'''
    <style>
        .tl-wrap {{ position:relative; height:32px; background:#1a1a2e; 
                    border-radius:6px; overflow:hidden; margin:8px 0 16px; }}
        .tl-seg  {{ position:absolute; top:4px; height:24px; 
                    background:linear-gradient(135deg,#6c5ce7,#a29bfe); 
                    border-radius:4px; opacity:0.85; cursor:pointer;
                    transition:opacity 0.2s; text-decoration:none; }}
        .tl-seg:hover {{ opacity:1; }}
        .tl-labels {{ display:flex; justify-content:space-between; 
                     font-size:11px; color:#888; font-family:monospace; }}
    </style>
    <div class="tl-labels"><span>0:00</span><span>{duration_seconds//60}:{duration_seconds%60:02d}</span></div>
    <div class="tl-wrap">{segment_html}</div>
    '''
    
    st.components.v1.html(html, height=60)
```

Call this in `app.py` right above the insights display section. Get `duration_seconds` from the recon pass data (already stored — check `structured_insights` or `research_data` for duration estimate from the recon pass).

### Acceptance Criteria
- Timeline bar appears above insights for processed videos
- Colored segments correspond to insight positions
- Hovering a segment shows the insight title as a tooltip
- Clicking a segment opens YouTube at that timestamp
- Videos without timestamp data show no timeline (graceful skip, no error)

---

## Task 3: Markdown Export

### Goal
One-click export of a video's insights as a clean, portable Markdown file.

### Files to Create
- `export.py`

### Files to Modify  
- `app.py` — add export button

### Implementation

**export.py:**
```python
"""Export video insights to Markdown."""

import json
from datetime import datetime


def export_video_markdown(video: dict) -> str:
    """Generate a Markdown string from a processed video's data.
    
    Args:
        video: dict with keys from the videos DB row — title, channel_name,
               url, summary, structured_insights, research_data, auto_agenda,
               playlist_type, video_id
    
    Returns:
        Markdown string ready for download.
    """
    lines = []
    title = video.get("title", "Untitled")
    channel = video.get("channel_name", "Unknown channel")
    video_id = video.get("video_id", "")
    playlist_type = video.get("playlist_type", "general")
    yt_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Header
    lines.append(f"# {title}")
    lines.append(f"")
    lines.append(f"**Channel:** {channel}  ")
    lines.append(f"**Type:** {playlist_type.title()}  ")
    lines.append(f"**Source:** [{yt_url}]({yt_url})  ")
    lines.append(f"**Extracted:** {datetime.now().strftime('%Y-%m-%d')}  ")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Summary
    summary = video.get("summary", "")
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")
    
    # Structured insights
    structured = video.get("structured_insights")
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except json.JSONDecodeError:
            structured = None
    
    if structured:
        # Guest profile (podcast)
        guest = structured.get("guest_profile")
        if guest and isinstance(guest, dict):
            lines.append("## Guest")
            lines.append("")
            if guest.get("name"):
                lines.append(f"**{guest['name']}**")
            if guest.get("bio"):
                lines.append(f"  {guest['bio']}")
            lines.append("")
        
        # Insights
        insights = structured.get("insights", [])
        if insights:
            lines.append("## Key Insights")
            lines.append("")
            for i, ins in enumerate(insights, 1):
                ts = ins.get("timestamp_seconds")
                ts_str = ""
                if ts is not None:
                    m, s = divmod(int(ts), 60)
                    h, m = divmod(m, 60)
                    ts_label = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
                    ts_link = f"https://www.youtube.com/watch?v={video_id}&t={ts}s"
                    ts_str = f" ([{ts_label}]({ts_link}))"
                
                ins_title = ins.get("title", f"Insight {i}")
                lines.append(f"### {i}. {ins_title}{ts_str}")
                lines.append("")
                
                content = ins.get("content", "")
                if content:
                    lines.append(content)
                    lines.append("")
                
                tags = ins.get("tags", [])
                if tags:
                    lines.append(f"*Tags: {', '.join(tags)}*")
                    lines.append("")
        
        # Resources
        resources = structured.get("resources", [])
        if resources:
            lines.append("## Resources Mentioned")
            lines.append("")
            for res in resources:
                name = res.get("name", "")
                rtype = res.get("type", "")
                url = res.get("url", "")
                if url:
                    lines.append(f"- **{name}** ({rtype}) — [{url}]({url})")
                else:
                    lines.append(f"- **{name}** ({rtype})")
            lines.append("")
        
        # Links
        links = structured.get("links", {})
        if links:
            lines.append("## Links")
            lines.append("")
            for group_name, group_links in links.items():
                if group_links:
                    lines.append(f"### {group_name.replace('_', ' ').title()}")
                    lines.append("")
                    for link in group_links:
                        if isinstance(link, dict):
                            lines.append(f"- [{link.get('title', link.get('url', ''))}]({link.get('url', '')})")
                        elif isinstance(link, str):
                            lines.append(f"- {link}")
                    lines.append("")
    
    # Agenda
    agenda = video.get("auto_agenda", "")
    if agenda:
        lines.append("## Agenda")
        lines.append("")
        lines.append(agenda)
        lines.append("")
    
    lines.append("---")
    lines.append(f"*Generated by YouTube Insight Agent*")
    
    return "\n".join(lines)
```

**In app.py**, find where the Done video detail is rendered. Add after the header/action buttons:

```python
if video["status"] == "done":
    md_content = export_video_markdown(video)
    safe_title = video["title"].replace(" ", "_")[:50]
    st.download_button(
        label="📥 Export as Markdown",
        data=md_content,
        file_name=f"{safe_title}_insights.md",
        mime="text/markdown",
    )
```

### Acceptance Criteria
- "Export as Markdown" button appears on every Done video
- Downloaded `.md` file opens cleanly in any Markdown viewer
- Includes: title, channel, summary, insights with timestamps, resources, links, agenda
- Handles missing fields gracefully (no KeyError, no empty sections)

---

## Task 4: Semantic Search Across Videos

### Goal
Search bar that finds insights across all processed videos using embedding similarity.

### Files to Create
- `search.py`

### Files to Modify
- `db.py` — new `embeddings` table
- `pipeline.py` — generate embeddings after holistic extraction
- `app.py` — search UI in sidebar or main area

### Implementation

**Step 1: DB schema update (`db.py`)**

Add a new table in the schema migration:

```sql
CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    chunk_title TEXT,
    timestamp_seconds INTEGER,
    embedding BLOB NOT NULL,
    FOREIGN KEY (video_id) REFERENCES videos(video_id),
    UNIQUE(video_id, chunk_index)
);
```

Add CRUD functions:
- `store_embeddings(video_id, chunks)` — bulk insert
- `get_all_embeddings()` — returns all rows for search
- `delete_embeddings(video_id)` — for re-processing

**Step 2: Embedding generation (`search.py`)**

```python
"""Semantic search across video insights using Gemini embeddings."""

import json
import struct
import numpy as np
import google.generativeai as genai
from config import GEMINI_API_KEY, EMBEDDING_MODEL
from db import store_embeddings, get_all_embeddings


def generate_embeddings_for_video(video_id: str, structured_insights: dict) -> list[dict]:
    """Generate embeddings for each insight chunk in a processed video.
    
    Call this after holistic extraction completes successfully.
    """
    if not GEMINI_API_KEY:
        return []
    
    genai.configure(api_key=GEMINI_API_KEY)
    
    insights = structured_insights.get("insights", [])
    if not insights:
        return []
    
    chunks = []
    for i, ins in enumerate(insights):
        text = f"{ins.get('title', '')}: {ins.get('content', '')}"
        chunks.append({
            "video_id": video_id,
            "chunk_index": i,
            "chunk_text": text,
            "chunk_title": ins.get("title", ""),
            "timestamp_seconds": ins.get("timestamp_seconds"),
        })
    
    # Batch embed
    texts = [c["chunk_text"] for c in chunks]
    try:
        result = genai.embed_content(
            model=f"models/{EMBEDDING_MODEL}",
            content=texts,
            task_type="RETRIEVAL_DOCUMENT",
        )
        for chunk, emb in zip(chunks, result["embedding"]):
            # Store as bytes for SQLite
            chunk["embedding"] = struct.pack(f"{len(emb)}f", *emb)
    except Exception as e:
        print(f"[search] Embedding generation failed: {e}")
        return []
    
    store_embeddings(video_id, chunks)
    return chunks


def search_insights(query: str, top_k: int = 10) -> list[dict]:
    """Search across all video insights. Returns ranked results."""
    if not GEMINI_API_KEY:
        return []
    
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Embed query
    try:
        result = genai.embed_content(
            model=f"models/{EMBEDDING_MODEL}",
            content=query,
            task_type="RETRIEVAL_QUERY",
        )
        query_emb = np.array(result["embedding"])
    except Exception as e:
        print(f"[search] Query embedding failed: {e}")
        return []
    
    # Load all stored embeddings
    all_rows = get_all_embeddings()  # Returns list of dicts
    if not all_rows:
        return []
    
    # Cosine similarity
    results = []
    for row in all_rows:
        emb_bytes = row["embedding"]
        n_floats = len(emb_bytes) // 4
        stored_emb = np.array(struct.unpack(f"{n_floats}f", emb_bytes))
        
        similarity = np.dot(query_emb, stored_emb) / (
            np.linalg.norm(query_emb) * np.linalg.norm(stored_emb) + 1e-8
        )
        results.append({
            "video_id": row["video_id"],
            "chunk_title": row["chunk_title"],
            "chunk_text": row["chunk_text"],
            "timestamp_seconds": row["timestamp_seconds"],
            "score": float(similarity),
        })
    
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
```

**Step 3: Hook into pipeline (`pipeline.py`)**

After the `_holistic_extraction()` call succeeds and `_merge_structured_output()` completes, add:

```python
# Generate search embeddings
try:
    from search import generate_embeddings_for_video
    generate_embeddings_for_video(video_id, structured_insights)
except Exception as e:
    logger.warning(f"[pipeline] Embedding generation failed (non-fatal): {e}")
```

Make this non-fatal — search is a bonus feature, not a pipeline blocker.

**Step 4: UI (`app.py`)**

Add a search section. This can go at the top of the main area or as a separate "page" in the sidebar:

```python
# Search bar
search_query = st.text_input("🔍 Search across all videos", placeholder="e.g., pricing strategy, hiring mistakes")
if search_query:
    from search import search_insights
    results = search_insights(search_query)
    if results:
        # Enrich with video titles from DB
        for r in results:
            video = get_video(r["video_id"])  # existing DB function
            r["video_title"] = video["title"] if video else "Unknown"
        
        for r in results:
            score_pct = int(r["score"] * 100)
            ts = r.get("timestamp_seconds")
            ts_str = ""
            if ts:
                m, s = divmod(int(ts), 60)
                ts_str = f" @ {m}:{s:02d}"
            
            st.markdown(f"**{r['video_title']}** — {r['chunk_title']}{ts_str} ({score_pct}% match)")
            st.caption(r["chunk_text"][:200] + "..." if len(r["chunk_text"]) > 200 else r["chunk_text"])
            st.divider()
    else:
        st.info("No matching insights found.")
```

### Acceptance Criteria
- Search bar in the UI returns results ranked by relevance
- Results show video title, insight title, preview text, and score
- Embeddings are generated automatically when a video finishes processing
- Re-processing a video regenerates its embeddings
- Works with 0 videos (shows helpful empty state), 1 video, and 50+ videos
- If GEMINI_API_KEY is missing, search silently degrades (no crash)

### Dependency
Add to `requirements.txt`: `numpy`

---

## Task 5: Demo Seed Mode

### Goal
Pre-load processed example videos so the app is immediately interesting on first run.

### Files to Create
- `seed_demo.py`
- `data/fixtures/` directory with JSON fixture files

### Implementation

**Step 1: Create export script (run locally on your machine with existing processed videos)**

```python
"""Export processed videos as JSON fixtures for demo mode."""

import json
import sqlite3
from pathlib import Path

DB_PATH = "data/insights.db"  # adjust if needed
FIXTURES_DIR = Path("data/fixtures")
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Pick 3-5 good examples — mix of General and Podcast
# Replace these with actual video IDs from your DB
DEMO_VIDEO_IDS = [
    # "VIDEO_ID_1",  # A good general lecture
    # "VIDEO_ID_2",  # A good podcast with research
    # "VIDEO_ID_3",  # Another example
]

for vid in DEMO_VIDEO_IDS:
    row = conn.execute("SELECT * FROM videos WHERE video_id = ?", (vid,)).fetchone()
    if row:
        data = dict(row)
        fixture_path = FIXTURES_DIR / f"{vid}.json"
        with open(fixture_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"Exported {vid}: {row['title']}")

conn.close()
```

**Step 2: Create seed loader**

`seed_demo.py`:
```python
"""Load demo fixtures into a fresh database."""

import json
import sys
from pathlib import Path
from db import init_db, upsert_video  # use existing DB functions

FIXTURES_DIR = Path("data/fixtures")


def seed():
    """Load all fixture files into the database."""
    init_db()
    
    fixtures = list(FIXTURES_DIR.glob("*.json"))
    if not fixtures:
        print("No fixtures found in data/fixtures/. Run the export script first.")
        sys.exit(1)
    
    for fixture_path in fixtures:
        with open(fixture_path) as f:
            video = json.load(f)
        
        upsert_video(video)  # use whatever DB insert function exists
        print(f"  Loaded: {video.get('title', fixture_path.stem)}")
    
    print(f"\nSeeded {len(fixtures)} demo videos. Run the app to see them.")


if __name__ == "__main__":
    seed()
```

Adapt `upsert_video` to match the actual `db.py` interface — it might be `insert_video`, `save_video`, or a raw INSERT. The key is to populate all the fields that the UI reads: `title`, `status` (set to "done"), `summary`, `structured_insights`, `research_data`, `auto_agenda`, `usage_data`, `channel_name`, `playlist_type`, `video_id`.

### Acceptance Criteria
- `python seed_demo.py` populates a fresh DB with 3-5 example videos
- App shows those videos as "Done" with full insights, timestamps, resources
- No API keys needed to view demo data
- Seed script is idempotent (running twice doesn't duplicate)

---

## Task 6: Config Validator UI

### Goal
Show a startup panel in the Streamlit app when config is incomplete or degraded.

### Files to Modify
- `app.py` — add config check on load

### Implementation

At the top of `app.py` (after imports, before main UI logic):

```python
from config import validate as validate_config

config_status = validate_config()
if not config_status["ok"]:
    with st.expander("⚠️ Configuration issues detected", expanded=True):
        if config_status["missing_required"]:
            st.error(f"**Required keys missing:** {', '.join(config_status['missing_required'])}")
            st.caption("These are needed for basic operation. Add them to your .env file.")
        
        if config_status["warnings"]:
            for w in config_status["warnings"]:
                st.warning(w)
        
        if config_status["missing_recommended"]:
            st.info(f"**Recommended:** {', '.join(config_status['missing_recommended'])} — some features will be limited without these.")
        
        if config_status["missing_optional"]:
            st.caption(f"Optional: {', '.join(config_status['missing_optional'])} (podcast web research)")
```

### Acceptance Criteria
- Missing required keys show an error with clear instructions
- Missing optional keys show a non-blocking info message
- Contradictory config (e.g., `LLM_PRIMARY=gemini` without `GEMINI_API_KEY`) shows a warning
- When everything is configured, no banner appears

---

## Task 7: Smart Error States

### Goal
Replace technical error messages with user-friendly explanations and suggested fixes.

### Files to Create
- `errors.py`

### Files to Modify
- `pipeline.py` — wrap error paths
- `app.py` — render friendly error cards

### Implementation

**errors.py:**
```python
"""Map technical errors to user-friendly messages."""

ERROR_MAP = {
    "429": {
        "gemini": {
            "title": "Gemini free tier exhausted",
            "message": "Google's daily free quota has been reached.",
            "fix": "Wait until tomorrow, or set LLM_PRIMARY=anthropic in .env to use paid fallback.",
        },
        "groq": {
            "title": "Groq rate limit hit",
            "message": "Too many requests to Groq in a short period.",
            "fix": "Wait a few minutes and retry. The app will automatically try Gemini/Anthropic as fallback.",
        },
    },
    "no_captions": {
        "title": "No transcript available",
        "message": "This video has no captions, and audio transcription couldn't process it.",
        "fix": "Check that ffmpeg is installed and on PATH. Some videos (live streams, premieres) may not have captions yet.",
    },
    "private_video": {
        "title": "Video is unavailable",
        "message": "This video is private, age-restricted, or has been removed.",
        "fix": "Check if the video is still publicly accessible on YouTube.",
    },
    "json_parse": {
        "title": "AI response couldn't be parsed",
        "message": "The LLM returned malformed output that couldn't be processed.",
        "fix": "Click Retry — this is usually a one-time issue. If it persists, try Re-process.",
    },
    "anthropic_credit": {
        "title": "Anthropic billing issue",
        "message": "No Anthropic credits available for the fallback model.",
        "fix": "Add billing at console.anthropic.com, or ensure Gemini is configured as primary.",
    },
}


def classify_error(error_message: str, provider: str = "") -> dict:
    """Classify a raw error message into a user-friendly error dict.
    
    Returns: {title, message, fix, raw} or a generic fallback.
    """
    msg = str(error_message).lower()
    
    if "429" in msg or "rate limit" in msg or "quota" in msg:
        provider_key = "gemini" if "gemini" in msg else "groq" if "groq" in msg else "gemini"
        return {**ERROR_MAP["429"][provider_key], "raw": error_message}
    
    if "no transcript" in msg or "captions" in msg or "subtitles" in msg:
        return {**ERROR_MAP["no_captions"], "raw": error_message}
    
    if "private" in msg or "unavailable" in msg or "age" in msg:
        return {**ERROR_MAP["private_video"], "raw": error_message}
    
    if "json" in msg and ("parse" in msg or "decode" in msg):
        return {**ERROR_MAP["json_parse"], "raw": error_message}
    
    if "anthropic" in msg and ("credit" in msg or "billing" in msg or "balance" in msg):
        return {**ERROR_MAP["anthropic_credit"], "raw": error_message}
    
    # Generic fallback
    return {
        "title": "Processing failed",
        "message": "An unexpected error occurred during processing.",
        "fix": "Click Retry. If the issue persists, check poll_worker.log for details.",
        "raw": error_message,
    }
```

**In app.py**, where failed videos display `error_message`, replace:

```python
# OLD
st.error(video["error_message"])

# NEW
from errors import classify_error
err = classify_error(video.get("error_message", ""))
st.error(f"**{err['title']}** — {err['message']}")
st.caption(f"💡 {err['fix']}")
with st.expander("Raw error"):
    st.code(err.get("raw", "No details"))
```

### Acceptance Criteria
- Failed videos show a title + explanation + fix suggestion
- Raw error is still accessible in an expander
- All major error types (quota, rate limit, no captions, JSON parse, billing) are classified
- Unknown errors get a reasonable generic message

---

## Task 8: Type Hints & Logging Cleanup

### Goal
Add type hints to core function signatures. Standardize logging. Remove stray `print()` calls.

### Files to Modify
- All `.py` files

### Implementation

**Type hints:** Add to all function signatures in `pipeline.py`, `llm.py`, `researcher.py`, `db.py`, `search.py`, `export.py`. Focus on parameters and return types. Use `from __future__ import annotations` at the top of each file for forward references.

```python
# Example pattern
def process_video(video_id: str, playlist_type: str = "general", manual: bool = False) -> dict | None:
    ...

def call_deep_llm(prompt: str, operation: str, json_mode: bool = True) -> dict | str | None:
    ...
```

**Logging:** Ensure every module uses:

```python
import logging
logger = logging.getLogger(__name__)
```

Replace all `print()` calls with appropriate log levels:
- `logger.info()` — normal flow ("Processing video X", "Extraction complete")
- `logger.warning()` — fallbacks ("Gemini failed, falling back to Anthropic")
- `logger.error()` — failures ("Pipeline failed for video X: ...")
- `logger.debug()` — verbose details (API response bodies, timing data)

Search for all `print(` calls and replace them. Keep the existing `[module]` prefix convention in log messages.

### Acceptance Criteria
- `grep -rn "print(" *.py` returns zero results (excluding `seed_demo.py` CLI output)
- All core functions have type hints on parameters and return values
- Log output uses consistent `[module] message` format
- No changes to actual logic — only annotations and logging

---

## General Notes for All Tasks

### Testing Approach
After each task, verify:
1. Fresh `pip install -r requirements.txt` works
2. `python -m streamlit run app.py` starts without error
3. Process a video end-to-end (both General and Podcast if possible)
4. Check that existing features still work (chat, usage stats, batch mode)

### Dependencies to Add
Add these to `requirements.txt` as needed:
- `numpy` — for semantic search cosine similarity

### Don't Break
- The existing V4 pipeline flow (recon → entities → research → holistic)
- The Gemini → Anthropic fallback chain
- Background subprocess processing
- Per-video usage tracking
- Chat functionality
- Batch mode

### File Encoding
All new files should be UTF-8. All new Python files should have `from __future__ import annotations` as the first import.
