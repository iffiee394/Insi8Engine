# Implementation Plan: Deep Insight Agent — Enhanced Pipeline + External Research

> **For Cursor Composer**: Implement all changes described below across the listed files. Read each existing file fully before modifying it. Do NOT delete existing functionality for general playlist videos — only enhance the podcast pipeline.

---

## Context

The YouTube Insight Agent (Phases 1-2) works but produces shallow insights from long podcasts because:
1. **Artificial chunking** — pipeline.py splits transcripts at 12K chars (~3K tokens), even though Groq's LLaMA 3.3 70B supports 128K context. A 2-hour podcast (~22K tokens) fits in ONE call. Chunking destroys narrative context.
2. **Knowledge base is a filter, not a lens** — Currently just says "don't repeat these topics." User wants a personal profile (CS student, AI focus, personality insights passion) that SHAPES what gets extracted.
3. **No external research** — No ability to research the podcast guest beyond the transcript.
4. **Single-pass extraction** — One generic prompt tries to do everything. Agenda items don't get the focused depth they deserve.

---

## Current File Structure (read these before editing)

| File | Lines | Purpose |
|------|-------|---------|
| `db.py` | 234 | SQLite storage, knowledge base (plain text file), video CRUD, status constants |
| `pipeline.py` | 222 | Transcript fetch + LLM summarization. 12K char chunking, single-pass prompts |
| `transcriber.py` | 112 | yt-dlp + ffmpeg + Groq Whisper. DO NOT MODIFY. |
| `app.py` | 391 | Streamlit dashboard. Dark theme, sidebar, agenda UI |
| `poll.py` | 147 | Playlist polling + dispatch. DO NOT MODIFY. |
| `youtube_monitor.py` | ~50 | YouTube API wrapper. DO NOT MODIFY. |
| `requirements.txt` | 6 lines | Current deps |
| `config.example.env` | ~6 lines | Env template |

---

## Change 1: Knowledge Base 2.0 → Personal Profile

### File: `db.py`

**Replace** the plain `knowledge_base.txt` system with `data/profile.json`.

Keep the existing `get_knowledge_base()` and `set_knowledge_base()` functions working (they're called from pipeline.py) but have them read from the new profile's `known_topics` field for backward compatibility.

Add these new functions:

```python
PROFILE_PATH = BASE_DIR / "data" / "profile.json"

DEFAULT_PROFILE = {
    "about_me": "",
    "interests": "",
    "insight_style": "",
    "known_topics": "",
}

def get_profile() -> dict:
    """Load the user profile from data/profile.json."""
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return dict(DEFAULT_PROFILE)
    return dict(DEFAULT_PROFILE)

def set_profile(profile: dict) -> None:
    """Save the user profile to data/profile.json."""
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

def get_profile_prompt() -> str:
    """Format the profile into an LLM instruction block."""
    p = get_profile()
    sections = []
    if p.get("about_me", "").strip():
        sections.append(f"About the user: {p['about_me'].strip()}")
    if p.get("interests", "").strip():
        sections.append(f"User's key interests: {p['interests'].strip()}")
    if p.get("insight_style", "").strip():
        sections.append(f"How the user wants insights: {p['insight_style'].strip()}")
    if p.get("known_topics", "").strip():
        sections.append(f"Topics the user already knows (skip unless the video adds a genuinely new angle):\n{p['known_topics'].strip()}")
    if not sections:
        return ""
    return "USER PROFILE — use this to shape your extraction:\n---\n" + "\n\n".join(sections) + "\n---"
```

**Migrate**: In `init_db()`, if `knowledge_base.txt` exists and `profile.json` does not, migrate the text into the `known_topics` field of a new profile.

**Add column**: Add `research_data TEXT NOT NULL DEFAULT ''` to the videos table (use the same `_ensure_columns` migration pattern already in the file).

---

## Change 2: Revamped Pipeline — Multi-Pass Deep Processing

### File: `pipeline.py`

**Remove** `MAX_CHUNK_CHARS = 12000`, `_chunk_text()`, `_summarize_chunk()`, and the old `summarize_transcript()`.

**Replace** with a multi-pass system. Keep `_call_groq()`, `_parse_json_response()`, `_fetch_youtube_captions()`, `get_transcript()` unchanged.

**New constant:**
```python
MAX_FULL_TRANSCRIPT_CHARS = 320000  # ~80K tokens, safe for 128K context with room for prompts
```

**New functions:**

### Pass 1 — Reconnaissance
```python
def _recon_pass(transcript: str, title: str) -> dict:
    """Identify guest, topics, structure from the full transcript."""
    prompt = f"""Analyze this podcast/video transcript and extract structural information.

Video title: "{title}"

Return ONLY valid JSON:
{{
    "guest_name": "name of the main guest/interviewee or empty string if none",
    "guest_description": "brief description of who they are based on the transcript",
    "main_topics": ["topic 1", "topic 2", ...],
    "is_interview": true/false
}}

Transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""
    raw = _call_groq(prompt)
    return _parse_json_response(raw)
```

### Pass 2 — Agenda Deep-Dive
```python
def _agenda_deep_dive(transcript: str, title: str, *, recon: dict, user_agenda: str, profile_prompt: str, research_summary: str) -> dict:
    """Extract deep, specific insights for each agenda item."""
    research_block = ""
    if research_summary.strip():
        research_block = f"\nExternal research on the guest:\n---\n{research_summary}\n---\nUse this context to enrich your insights where relevant.\n"

    prompt = f"""{profile_prompt}

You are extracting deep, detailed insights from a podcast titled "{title}".
Guest: {recon.get('guest_name', 'Unknown')} — {recon.get('guest_description', '')}
{research_block}
The user added this video with a specific agenda. For EACH agenda item, extract every relevant detail — names, numbers, tools, steps, URLs, quotes, anecdotes. Be thorough and specific, not surface-level.

User agenda (each line is a priority focus area):
---
{user_agenda.strip()}
---

Return ONLY valid JSON:
{{
    "agenda_insights": [
        {{
            "agenda_item": "the user's agenda item",
            "insights": ["detailed insight 1", "detailed insight 2", ...]
        }}
    ]
}}

Provide 3-8 detailed insights per agenda item depending on how much the video covers it. If the video doesn't cover an agenda item, include it with an empty insights array.

Full transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""
    raw = _call_groq(prompt)
    return _parse_json_response(raw)
```

### Pass 3 — General Sweep
```python
def _general_sweep(transcript: str, title: str, *, recon: dict, user_agenda: str, profile_prompt: str) -> dict:
    """Capture important things the agenda didn't cover."""
    prompt = f"""{profile_prompt}

You are reviewing a podcast titled "{title}" for important content that was NOT covered by the user's agenda.
Guest: {recon.get('guest_name', 'Unknown')} — {recon.get('guest_description', '')}

The user's agenda focused on:
---
{user_agenda.strip()}
---

Your job: find the most important, interesting, or surprising things from this podcast that fall OUTSIDE the agenda above. Focus on things the user profile suggests they'd care about.

Return ONLY valid JSON:
{{
    "summary": "3-5 sentence overview of the ENTIRE podcast (not just the agenda items)",
    "general_highlights": ["important point not covered by agenda 1", "point 2", ...]
}}

Provide 5-10 general highlights. Skip anything already covered by the agenda items.

Full transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""
    raw = _call_groq(prompt)
    return _parse_json_response(raw)
```

### Updated process_video for podcasts
```python
def process_video(video_id, title, *, playlist_type, user_agenda=""):
    transcript, source = get_transcript(video_id)
    if not transcript.strip():
        raise RuntimeError("Empty transcript")

    profile_prompt = db.get_profile_prompt()

    if playlist_type == db.PLAYLIST_PODCAST and user_agenda.strip():
        # Pass 1: Recon
        recon = _recon_pass(transcript, title)

        # Research (if Tavily key is set)
        research_summary = ""
        research_data = {}
        guest_name = recon.get("guest_name", "").strip()
        if guest_name:
            from researcher import research_guest
            research_data = research_guest(guest_name)
            research_summary = research_data.get("summary", "")

        # Pass 2: Agenda deep-dive
        agenda_result = _agenda_deep_dive(
            transcript, title,
            recon=recon, user_agenda=user_agenda,
            profile_prompt=profile_prompt, research_summary=research_summary,
        )

        # Pass 3: General sweep
        general_result = _general_sweep(
            transcript, title,
            recon=recon, user_agenda=user_agenda,
            profile_prompt=profile_prompt,
        )

        # Flatten agenda insights into key_points for backward compat
        key_points = []
        for item in agenda_result.get("agenda_insights", []):
            key_points.append(f"📌 {item['agenda_item']}")
            key_points.extend(item.get("insights", []))

        if general_result.get("general_highlights"):
            key_points.append("── General Highlights ──")
            key_points.extend(general_result["general_highlights"])

        return {
            "summary": general_result.get("summary", ""),
            "key_points": key_points,
            "transcript_source": source,
            "research_data": research_data,
            "agenda_insights": agenda_result.get("agenda_insights", []),
            "general_highlights": general_result.get("general_highlights", []),
        }

    # General playlist — simple single-pass (no chunking, full transcript)
    prompt = f"""{profile_prompt}

You are summarizing a YouTube video titled "{title}".
Write a concise summary and extract the most important, actionable key points.
Be specific: include names, numbers, tools, steps — not generic advice.

Return ONLY valid JSON:
{{"summary": "3-5 sentence overview", "key_points": ["point 1", "point 2", ...]}}

Provide 5-12 key points depending on content density.

Transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""
    raw = _call_groq(prompt)
    result = _parse_json_response(raw)
    return {
        "summary": result.get("summary", ""),
        "key_points": result.get("key_points", []),
        "transcript_source": source,
    }
```

---

## Change 3: External Research Module

### NEW File: `researcher.py`

```python
"""External research on podcast guests via Tavily search + Groq LLM synthesis."""

import json
import os
import re

from groq import Groq

SUMMARY_MODEL = os.environ.get("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")


def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Run a single Tavily search query. Returns list of {title, url, content}."""
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        response = client.search(query, max_results=max_results, search_depth="advanced")
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in response.get("results", [])
        ]
    except Exception:
        return []


def _search_guest(guest_name: str) -> str:
    """Run multiple targeted searches and combine results."""
    queries = [
        f'"{guest_name}"',
        f'"{guest_name}" viral OR trending OR famous for',
        f'"{guest_name}" reddit discussion OR opinion',
        f'"{guest_name}" interview highlights OR controversial',
    ]
    all_results = []
    for q in queries:
        results = _tavily_search(q, max_results=3)
        all_results.extend(results)

    if not all_results:
        return ""

    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for r in all_results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique.append(r)

    # Format for LLM
    chunks = []
    for i, r in enumerate(unique[:12], 1):
        chunks.append(f"[{i}] {r['title']}\n{r['url']}\n{r['content'][:500]}")
    return "\n\n".join(chunks)


def research_guest(guest_name: str) -> dict:
    """
    Research a podcast guest using web search + LLM synthesis.
    Returns dict with: guest_name, bio, viral_things, discussions, summary.
    """
    search_text = _search_guest(guest_name)
    if not search_text:
        return {"guest_name": guest_name, "summary": "", "bio": "", "viral_things": [], "discussions": []}

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"guest_name": guest_name, "summary": "", "bio": "", "viral_things": [], "discussions": []}

    prompt = f"""Based on these web search results about "{guest_name}", synthesize a research brief.

Search results:
{search_text}

Return ONLY valid JSON:
{{
    "bio": "1-2 sentence bio of who this person is",
    "viral_things": ["top viral/notable thing 1", "thing 2", ...],
    "discussions": ["what people say/debate about them 1", "discussion 2", ...],
    "summary": "A 2-3 sentence synthesis of the most important context about this person that would help someone get more out of a podcast interview with them"
}}

Provide up to 5 items each for viral_things and discussions. Only include things supported by the search results — do not invent.
"""
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=SUMMARY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    raw = response.choices[0].message.content or ""

    # Parse JSON
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {}

    result["guest_name"] = guest_name
    return result
```

---

## Change 4: Updated Dashboard

### File: `app.py`

### 4a. Replace KB sidebar with structured profile editor

Replace the existing knowledge base expander (lines ~190-201) with:

```python
with st.expander("🧠 My Profile", expanded=False):
    st.caption("Your profile shapes how insights are extracted — be specific.")
    profile = db.get_profile()

    about = st.text_area(
        "About me",
        value=profile.get("about_me", ""),
        height=80,
        placeholder="e.g. I'm a CS student working in AI, passionate about deep tech and building things...",
        key="profile_about",
    )
    interests = st.text_area(
        "My interests",
        value=profile.get("interests", ""),
        height=80,
        placeholder="e.g. Deep technical details, personality insights, industry trends, startup strategies...",
        key="profile_interests",
    )
    style = st.text_area(
        "Insight style",
        value=profile.get("insight_style", ""),
        height=60,
        placeholder="e.g. Specific names, tools, numbers — not generic advice. I want depth, not surface-level.",
        key="profile_style",
    )
    known = st.text_area(
        "Topics I already know",
        value=profile.get("known_topics", ""),
        height=100,
        placeholder="e.g. Python basics, REST APIs, how transformers work, basics of prompt engineering...",
        key="profile_known",
    )
    if st.button("Save profile", use_container_width=True):
        db.set_profile({
            "about_me": about,
            "interests": interests,
            "insight_style": style,
            "known_topics": known,
        })
        st.success("Profile saved")
```

### 4b. Guest Research panel (for podcast videos with status DONE)

After the summary card and before the key points, add a research panel when `research_data` exists:

```python
# Parse research data
research_data = {}
if video.get("research_data"):
    try:
        research_data = json.loads(video["research_data"]) if isinstance(video["research_data"], str) else video["research_data"]
    except json.JSONDecodeError:
        pass

if research_data and research_data.get("bio"):
    st.markdown('<div class="section-head">Guest Research</div>', unsafe_allow_html=True)
    st.markdown(
        f"""<div class="panel" style="border-left: 3px solid #f59e0b;">
            <div class="panel-title" style="font-size: 1rem;">🔍 {_esc(research_data.get('guest_name', 'Guest'))}</div>
            <p style="color: #cbd5e1; margin: 8px 0;">{_esc(research_data.get('bio', ''))}</p>
        </div>""",
        unsafe_allow_html=True,
    )
    viral = research_data.get("viral_things", [])
    if viral:
        st.markdown('<div class="section-head">Notable & Viral</div>', unsafe_allow_html=True)
        for item in viral:
            st.markdown(f'<div class="kp"><span class="num">🔥</span><span>{_esc(item)}</span></div>', unsafe_allow_html=True)

    discussions = research_data.get("discussions", [])
    if discussions:
        st.markdown('<div class="section-head">What People Say</div>', unsafe_allow_html=True)
        for item in discussions:
            st.markdown(f'<div class="kp"><span class="num">💬</span><span>{_esc(item)}</span></div>', unsafe_allow_html=True)
```

### 4c. Grouped agenda insights display

Replace the flat key_points loop for podcast videos with grouped display:

```python
# For podcast DONE videos, try to show grouped agenda insights
agenda_insights_raw = video.get("agenda_insights", "")
if is_podcast and agenda_insights_raw:
    try:
        agenda_items = json.loads(agenda_insights_raw) if isinstance(agenda_insights_raw, str) else agenda_insights_raw
    except (json.JSONDecodeError, TypeError):
        agenda_items = []

    if agenda_items:
        st.markdown('<div class="section-head">Agenda-Focused Insights</div>', unsafe_allow_html=True)
        for item in agenda_items:
            agenda_label = item.get("agenda_item", "")
            insights = item.get("insights", [])
            if agenda_label:
                st.markdown(f'<div class="kp podcast" style="background:rgba(168,85,247,0.1); border: 1px solid rgba(168,85,247,0.25);"><span class="num">📌</span><span style="font-weight:600;">{_esc(agenda_label)}</span></div>', unsafe_allow_html=True)
            for i, ins in enumerate(insights, 1):
                st.markdown(f'<div class="kp podcast"><span class="num">{i:02d}</span><span>{_esc(ins)}</span></div>', unsafe_allow_html=True)

        # General highlights
        general_raw = video.get("general_highlights", "")
        try:
            general_highlights = json.loads(general_raw) if isinstance(general_raw, str) else general_raw
        except (json.JSONDecodeError, TypeError):
            general_highlights = []

        if general_highlights:
            st.markdown('<div class="section-head">General Highlights</div>', unsafe_allow_html=True)
            for i, point in enumerate(general_highlights, 1):
                st.markdown(f'<div class="kp"><span class="num">{i:02d}</span><span>{_esc(point)}</span></div>', unsafe_allow_html=True)
    else:
        # Fallback to flat key_points
        # (keep existing key_points display code as fallback)
```

### 4d. Store new fields from pipeline

In `poll.py`'s `process_one()`, the pipeline returns `research_data`, `agenda_insights`, `general_highlights`. These need to be saved to the DB. Update the `upsert_video` call in `poll.py` (lines 58-65) to also pass:
- `research_data=json.dumps(result.get("research_data", {}))` 

And in `db.py`, add `agenda_insights` and `general_highlights` columns (same pattern as `research_data`).

Update `upsert_video()` to accept and store these new fields.

---

## Change 5: Config Files

### File: `requirements.txt`
Add:
```
tavily-python>=0.5.0
```

### File: `config.example.env`
Add:
```
TAVILY_API_KEY=tvly-xxxxxxxxxxxxx
```

---

## Important Notes

- **DO NOT modify** `transcriber.py`, `youtube_monitor.py`, or the core logic in `poll.py`
- Keep backward compatibility: general playlist videos should still work with the simpler single-pass flow
- The research module should gracefully handle missing `TAVILY_API_KEY` — just skip research, don't crash
- All new DB columns must use the `_ensure_columns` migration pattern (ALTER TABLE ADD COLUMN with defaults)
- Keep the dark theme CSS unchanged
- The `import json` is already in db.py and app.py; add it to any file that needs it
