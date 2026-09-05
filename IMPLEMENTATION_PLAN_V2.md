# Implementation Plan V2: Deep Insight Agent — Auto-Agenda + Research

> **Supersedes IMPLEMENTATION_PLAN.md** — the key change is eliminating mandatory manual agendas. The user's profile drives extraction automatically. Custom agendas become an optional override.

---

## The Problem with V1

V1 required: add video → go to dashboard → write agenda → click generate → wait → read. That's 6 steps. A real background agent should be: **add video to playlist → done. Come back later, insights are ready.**

## New Philosophy

- **Profile IS the default agenda.** It tells the agent who you are, what you care about, what depth you want. That's enough to extract great insights from any podcast.
- **Auto-agenda generation.** Agent reads your profile + does recon on the transcript → generates a tailored agenda automatically.
- **Manual agenda = optional override.** Only used when you want something hyper-specific that your profile doesn't cover.
- **Podcasts auto-process just like general videos.** No more `awaiting_agenda` blocking state.

---

## New User Flow

```
YOU (on YouTube):
    Add video to Podcast playlist
    ↓ (done — close YouTube, go live your life)

AGENT (background, every 15 min):
    poll.py detects new video
    ↓
    Pass 1 — Recon: identify guest, topics, structure
    ↓
    Auto-generate agenda from YOUR PROFILE + recon
    ↓
    Research guest via Tavily (viral things, reddit, discussions)
    ↓
    Pass 2 — Deep extraction (auto-agenda + research + full transcript)
    ↓
    Pass 3 — General sweep (what else matters to YOU)
    ↓
    Save to DB → status: DONE

YOU (whenever you want):
    Open dashboard → read insights
    Optional: tweak agenda → click Regenerate for a different angle
```

---

## Current File Structure (read these before editing)

| File | Lines | Purpose |
|------|-------|---------|
| `db.py` | 234 | SQLite storage, knowledge base (plain text file), video CRUD, status constants |
| `pipeline.py` | 222 | Transcript fetch + LLM summarization. 12K char chunking, single-pass prompts |
| `transcriber.py` | 112 | yt-dlp + ffmpeg + Groq Whisper. **DO NOT MODIFY.** |
| `app.py` | 391 | Streamlit dashboard. Dark theme, sidebar, agenda UI |
| `poll.py` | 147 | Playlist polling + dispatch. Needs minor update for auto-processing. |
| `youtube_monitor.py` | ~50 | YouTube API wrapper. **DO NOT MODIFY.** |
| `requirements.txt` | 6 lines | Current deps |
| `config.example.env` | ~6 lines | Env template |

---

## Change 1: Knowledge Base 2.0 → Personal Profile

### File: `db.py`

**Replace** the plain `knowledge_base.txt` system with `data/profile.json`.

Keep the existing `get_knowledge_base()` and `set_knowledge_base()` working for backward compat — they read/write the `known_topics` field.

**Add these:**

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
    """Format the profile into an LLM instruction block for prompt injection."""
    p = get_profile()
    sections = []
    if p.get("about_me", "").strip():
        sections.append(f"About the user: {p['about_me'].strip()}")
    if p.get("interests", "").strip():
        sections.append(f"User's key interests and passions: {p['interests'].strip()}")
    if p.get("insight_style", "").strip():
        sections.append(f"How the user wants insights delivered: {p['insight_style'].strip()}")
    if p.get("known_topics", "").strip():
        sections.append(f"Topics the user already knows well (skip unless the video adds a genuinely new angle):\n{p['known_topics'].strip()}")
    if not sections:
        return ""
    return "USER PROFILE — use this to shape your extraction, tone, and depth:\n---\n" + "\n\n".join(sections) + "\n---"
```

**Migrate**: In `init_db()`, if `knowledge_base.txt` exists with content and `profile.json` does not, migrate the text into the `known_topics` field of a new profile.

**New columns** (use the existing `_ensure_columns` migration pattern with ALTER TABLE):
- `research_data TEXT NOT NULL DEFAULT ''` — JSON blob: guest profile + topic research findings
- `auto_agenda TEXT NOT NULL DEFAULT ''` — The agent-generated agenda (so user can see what the agent focused on)

**Update `upsert_video()`**: Accept and store these two new fields. Same pattern as existing fields — keep existing values if not provided on update.

### Key change to status flow

**Remove `STATUS_AWAITING_AGENDA` as a blocking state for auto-processing.** Podcast videos should now auto-process just like general videos. The status flow becomes:

```
NEW podcast video detected → status: PENDING → auto-process immediately → DONE
```

Update `should_auto_process()` in db.py:
```python
def should_auto_process(video: dict[str, Any] | None) -> bool:
    if not video:
        return True
    # Both general and podcast videos auto-process when pending or failed
    return video["status"] in (STATUS_PENDING, STATUS_FAILED)
```

Keep `STATUS_AWAITING_AGENDA` as a constant (don't break existing DB rows) but it's no longer the default for new podcast videos. Old videos stuck in `awaiting_agenda` can be manually triggered from the dashboard.

---

## Change 2: Revamped Pipeline — Multi-Pass with Auto-Agenda

### File: `pipeline.py`

**Remove**: `MAX_CHUNK_CHARS = 12000`, `_chunk_text()`, `_summarize_chunk()`, and the old `summarize_transcript()`.

**Keep unchanged**: `_call_groq()`, `_parse_json_response()`, `_fetch_youtube_captions()`, `get_transcript()`.

**New constant:**
```python
MAX_FULL_TRANSCRIPT_CHARS = 320000  # ~80K tokens — safe within 128K context with room for prompts
```

### Pass 1 — Reconnaissance

```python
def _recon_pass(transcript: str, title: str) -> dict:
    """Identify guest, topics, structure from the full transcript."""
    prompt = f"""Analyze this podcast/video transcript and extract structural information.

Video title: "{title}"

Return ONLY valid JSON:
{{
    "guest_name": "name of the main guest/interviewee, or empty string if no clear guest",
    "guest_description": "1-2 sentence description of who they are, based on the transcript",
    "main_topics": ["topic 1", "topic 2", ...],
    "is_interview": true/false,
    "estimated_duration": "short/medium/long based on transcript length"
}}

Transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""
    raw = _call_groq(prompt)
    return _parse_json_response(raw)
```

### NEW: Auto-Agenda Generation

```python
def _generate_auto_agenda(recon: dict, profile_prompt: str) -> str:
    """Generate a tailored agenda based on user profile + video recon."""
    if not profile_prompt.strip():
        # No profile set — use generic deep-extraction agenda
        topics = recon.get("main_topics", [])
        return "\n".join(f"• {t}" for t in topics[:6]) if topics else "• Key insights and takeaways"

    guest_info = ""
    if recon.get("guest_name"):
        guest_info = f"Guest: {recon['guest_name']} — {recon.get('guest_description', '')}"
    
    topics_str = ", ".join(recon.get("main_topics", []))

    prompt = f"""{profile_prompt}

Based on the user profile above, generate a focused agenda for extracting insights from this video.

{guest_info}
Main topics covered: {topics_str}
Interview format: {"Yes" if recon.get("is_interview") else "No"}

Generate 4-7 specific agenda items that this PARTICULAR user would want deep insights on, based on their profile, interests, and what this video covers.

Rules:
- Each agenda item should be specific and actionable, not vague
- Tailor to the user's interests and background
- Include at least one item about the guest as a person (if it's an interview)
- Include items about any technical details the user's profile suggests they'd care about
- Do NOT include agenda items for topics the user already knows well (from their known_topics)

Return ONLY a bullet list, one item per line, starting with •
Example:
• What specific AI tools and frameworks does the guest use daily
• The guest's unconventional career path and pivotal decisions
• Concrete salary/compensation data mentioned for AI roles
"""
    raw = _call_groq(prompt)
    # Clean up — just return the bullet list
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip().startswith("•")]
    return "\n".join(lines) if lines else raw.strip()
```

### Pass 2 — Holistic Deep Extraction

One comprehensive pass that covers the ENTIRE video. Agenda items get priority depth, but nothing important is left out.

```python
def _holistic_extraction(transcript: str, title: str, *, recon: dict, agenda: str, profile_prompt: str, research_summary: str) -> dict:
    """Extract comprehensive insights from the entire video. Agenda items get priority depth, but nothing important is missed."""
    research_block = ""
    if research_summary.strip():
        research_block = f"""
External research context (use this to enrich your insights where relevant):
---
{research_summary}
---
"""

    guest_line = ""
    if recon.get("guest_name"):
        guest_line = f"Guest: {recon.get('guest_name', '')} — {recon.get('guest_description', '')}"

    prompt = f"""{profile_prompt}

You are extracting deep, comprehensive insights from a podcast/video titled "{title}".
{guest_line}
{research_block}
The user has priority focus areas (agenda), but you must also capture EVERY important moment from the entire video — not just the agenda items. Think of the agenda as "go extra deep here" not "only extract this."

Priority focus areas (go deepest on these):
---
{agenda}
---

Return ONLY valid JSON:
{{
    "summary": "4-6 sentence holistic overview of the entire video — the narrative arc, key themes, and why it matters",
    "insights": [
        {{
            "topic": "short label for this insight cluster",
            "is_agenda_item": true/false,
            "points": ["detailed specific point 1", "detailed specific point 2", ...]
        }}
    ]
}}

Rules:
- Start with insight clusters that match the agenda items (is_agenda_item: true) — go DEEP on these: 4-8 points each, with specific names, numbers, tools, steps, URLs, quotes, anecdotes
- Then add clusters for every OTHER important topic from the video (is_agenda_item: false) — 2-4 points each
- Total: aim for 15-30+ insights across all clusters depending on video length and density
- Each point should be 1-3 sentences of SPECIFIC information, not vague summaries
- Include direct quotes when they're powerful or memorable
- Do NOT leave out important, surprising, or emotionally powerful moments just because they're not on the agenda
- The user's profile tells you who they are — use it to judge what's "important" beyond the agenda

Full transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""
    raw = _call_groq(prompt)
    return _parse_json_response(raw)
```

### Updated `process_video` — Unified flow

```python
def process_video(video_id: str, title: str, *, playlist_type: str = db.PLAYLIST_GENERAL, user_agenda: str = "") -> dict:
    transcript, source = get_transcript(video_id)
    if not transcript.strip():
        raise RuntimeError("Empty transcript")

    profile_prompt = db.get_profile_prompt()

    if playlist_type == db.PLAYLIST_PODCAST:
        # === PODCAST: Multi-pass deep processing ===

        # Pass 1: Recon
        recon = _recon_pass(transcript, title)

        # Auto-generate or use manual agenda
        if user_agenda.strip():
            agenda = user_agenda.strip()
            auto_agenda = ""
        else:
            agenda = _generate_auto_agenda(recon, profile_prompt)
            auto_agenda = agenda  # Save so user can see what agent focused on

        # External research on guest AND topics
        research_summary = ""
        research_data = {}
        from researcher import research_guest_and_topics
        research_data = research_guest_and_topics(
            guest_name=recon.get("guest_name", "").strip(),
            topics=recon.get("main_topics", []),
        )
        research_summary = research_data.get("combined_summary", "")

        # Pass 2: Holistic deep extraction (one pass — agenda gets depth, nothing important is missed)
        result = _holistic_extraction(
            transcript, title,
            recon=recon, agenda=agenda,
            profile_prompt=profile_prompt, research_summary=research_summary,
        )

        # Build flat key_points for backward compatibility
        key_points = []
        for cluster in result.get("insights", []):
            prefix = "📌" if cluster.get("is_agenda_item") else "💡"
            key_points.append(f"{prefix} {cluster.get('topic', '')}")
            key_points.extend(cluster.get("points", []))

        return {
            "summary": result.get("summary", ""),
            "key_points": key_points,
            "transcript_source": source,
            "research_data": research_data,
            "auto_agenda": auto_agenda,
        }

    # === GENERAL: Single-pass full-transcript extraction ===
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
    parsed = _parse_json_response(raw)
    return {
        "summary": parsed.get("summary", ""),
        "key_points": parsed.get("key_points", []),
        "transcript_source": source,
    }
```

---

## Change 3: External Research Module

### NEW File: `researcher.py`

```python
"""External research on podcast guests AND topics via Tavily search + Groq LLM synthesis."""

import json
import os
import re

from groq import Groq

SUMMARY_MODEL = os.environ.get("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")


def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Run a single Tavily search query."""
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


def _collect_search_results(queries: list[str], max_per_query: int = 3) -> str:
    """Run multiple searches, deduplicate, format for LLM."""
    all_results = []
    for q in queries:
        all_results.extend(_tavily_search(q, max_results=max_per_query))

    if not all_results:
        return ""

    seen_urls = set()
    unique = []
    for r in all_results:
        if r["url"] not in seen_urls:
            seen_urls.add(r["url"])
            unique.append(r)

    chunks = []
    for i, r in enumerate(unique[:15], 1):
        chunks.append(f"[{i}] {r['title']}\n{r['url']}\n{r['content'][:500]}")
    return "\n\n".join(chunks)


def _call_groq_json(prompt: str) -> dict:
    """Call Groq LLM and parse JSON response."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {}
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=SUMMARY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    raw = (response.choices[0].message.content or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _research_person(name: str) -> dict:
    """Research a person: bio, viral things, discussions."""
    if not name:
        return {}
    search_text = _collect_search_results([
        f'"{name}"',
        f'"{name}" viral OR trending OR famous for',
        f'"{name}" site:reddit.com',
        f'"{name}" interview highlights OR controversial OR hot take',
    ])
    if not search_text:
        return {"name": name}

    result = _call_groq_json(f"""Based on these web search results about "{name}", create a research brief.

Search results:
{search_text}

Return ONLY valid JSON:
{{
    "bio": "1-2 sentence bio of who this person is and why they matter",
    "viral_things": ["most notable/viral thing 1", "thing 2", ...],
    "discussions": ["what people debate about them 1", "topic 2", ...],
    "summary": "2-3 sentence essential context about this person"
}}

Up to 5 items each. Only include things supported by search results — do not invent.""")
    result["name"] = name
    return result


def _research_topics(topics: list[str]) -> list[dict]:
    """Research key topics: notable articles, viral discussions, important context."""
    if not topics:
        return []
    # Pick the top 3 most specific topics (skip generic ones like "career" or "life")
    researched = []
    for topic in topics[:3]:
        if len(topic) < 4:  # skip very short/generic labels
            continue
        search_text = _collect_search_results([
            f'"{topic}" explained OR guide OR overview',
            f'"{topic}" viral OR trending OR most important',
            f'"{topic}" site:reddit.com discussion',
        ], max_per_query=2)
        if not search_text:
            continue

        result = _call_groq_json(f"""Based on these web search results about the topic "{topic}", create a brief.

Search results:
{search_text}

Return ONLY valid JSON:
{{
    "topic": "{topic}",
    "what_it_is": "1 sentence explanation if it's a technology/concept/tool",
    "notable": ["most important/viral thing about this topic 1", "thing 2", ...],
    "hot_takes": ["what people commonly debate or say about it 1", "take 2", ...],
    "summary": "1-2 sentence context that would help someone understand a podcast discussion about this"
}}

Up to 3 items each. Only include things supported by search results.""")
        result["topic"] = topic
        researched.append(result)
    return researched


def research_guest_and_topics(*, guest_name: str = "", topics: list[str] | None = None) -> dict:
    """
    Research both the guest AND the key topics discussed.
    Returns dict with: guest (profile), topics (list of topic briefs), combined_summary.
    Gracefully returns empty results if TAVILY_API_KEY is not set.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return {"guest": {}, "topics": [], "combined_summary": ""}

    guest_data = _research_person(guest_name) if guest_name else {}
    topics_data = _research_topics(topics or [])

    # Build a combined summary for injection into the extraction prompt
    parts = []
    if guest_data.get("summary"):
        parts.append(f"GUEST — {guest_name}: {guest_data['summary']}")
        if guest_data.get("viral_things"):
            parts.append("Notable: " + "; ".join(guest_data["viral_things"][:3]))
    for td in topics_data:
        if td.get("summary"):
            parts.append(f"TOPIC — {td.get('topic', '')}: {td['summary']}")
            if td.get("notable"):
                parts.append("Notable: " + "; ".join(td["notable"][:2]))

    return {
        "guest": guest_data,
        "topics": topics_data,
        "combined_summary": "\n".join(parts),
    }
```

---

## Change 4: Update `poll.py` — Auto-process podcasts

### File: `poll.py`

**Small but critical change.** Podcast videos no longer block on `awaiting_agenda`. They auto-process immediately.

In `_register_video()` — when inserting a new podcast video, set status to `PENDING` (not `AWAITING_AGENDA`).

In `process_one()` — remove the check that blocks processing when a podcast has no agenda. The pipeline now handles missing agendas via auto-generation.

Update lines 43-45 (remove or bypass the agenda gate):
```python
# REMOVE this block:
# if video["playlist_type"] == db.PLAYLIST_PODCAST and not video.get("user_agenda", "").strip():
#     print(f"[poll] Podcast video needs an agenda first: {video['title']}", file=sys.stderr)
#     db.upsert_video(video_id, status=db.STATUS_AWAITING_AGENDA)
#     return 1
```

Update the `upsert_video` call after successful processing (around line 58-65) to also save the new fields:
```python
db.upsert_video(
    video_id,
    status=db.STATUS_DONE,
    summary=result["summary"],
    key_points=result["key_points"],
    transcript_source=result["transcript_source"],
    error_message="",
    research_data=json.dumps(result.get("research_data", {})),
    auto_agenda=result.get("auto_agenda", ""),
)
```

Add `import json` at the top of poll.py if not already there.

---

## Change 5: Updated Dashboard

### File: `app.py`

### 5a. Replace KB sidebar with structured profile editor

Replace the existing knowledge base expander (around lines 190-201) with:

```python
with st.expander("🧠 My Profile", expanded=False):
    st.caption("Your profile shapes how insights are extracted. Be specific — this is your default agenda for every podcast.")
    profile = db.get_profile()

    about = st.text_area(
        "About me",
        value=profile.get("about_me", ""),
        height=80,
        placeholder="e.g. I'm a CS student working in AI, passionate about deep tech and building real things...",
        key="profile_about",
    )
    interests = st.text_area(
        "My interests",
        value=profile.get("interests", ""),
        height=80,
        placeholder="e.g. Deep technical architecture, personality insights from founders, startup strategies, AI/ML internals...",
        key="profile_interests",
    )
    style = st.text_area(
        "Insight style",
        value=profile.get("insight_style", ""),
        height=60,
        placeholder="e.g. Give me specific names, tools, numbers, URLs — not generic advice. I want depth and actionable details.",
        key="profile_style",
    )
    known = st.text_area(
        "Topics I already know",
        value=profile.get("known_topics", ""),
        height=100,
        placeholder="e.g. Python basics, REST APIs, how transformers work, prompt engineering fundamentals...",
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

### 5b. Podcast video detail — show auto-agenda + allow override

For podcast videos, instead of REQUIRING an agenda, show what the agent auto-focused on and allow override:

```python
if is_podcast and video["status"] == db.STATUS_DONE:
    # Show what the agent focused on
    auto_agenda = video.get("auto_agenda", "")
    user_agenda = video.get("user_agenda", "")
    
    if auto_agenda and not user_agenda:
        st.markdown('<div class="section-head">Agent\'s Auto-Generated Focus</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="agenda-display">{_esc(auto_agenda)}</div>', unsafe_allow_html=True)
        st.caption("This was auto-generated from your profile. Override below if you want different focus areas.")
    elif user_agenda:
        st.markdown('<div class="section-head">Your Custom Agenda</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="agenda-display">{_esc(user_agenda)}</div>', unsafe_allow_html=True)

# Optional override — collapsed by default for DONE videos
if is_podcast:
    with st.expander("✏️ Custom agenda override", expanded=(video["status"] != db.STATUS_DONE)):
        st.caption("Write a custom agenda to regenerate with different focus areas.")
        agenda_key = f"agenda_{video['video_id']}"
        if agenda_key not in st.session_state:
            st.session_state[agenda_key] = video.get("user_agenda") or ""

        agenda = st.text_area(
            "Custom agenda",
            height=140,
            placeholder=AGENDA_EXAMPLE,
            label_visibility="collapsed",
            key=agenda_key,
        )
        if st.button("Regenerate with this agenda", type="primary", use_container_width=True):
            if not agenda.strip():
                st.warning("Write your custom agenda first.")
            else:
                db.upsert_video(
                    video["video_id"],
                    user_agenda=agenda.strip(),
                    status=db.STATUS_PENDING,
                    error_message="",
                )
                with st.spinner("Regenerating with your custom agenda…"):
                    process_one(video["video_id"])
                st.rerun()
```

### 5c. Research panel — guest AND topics

For DONE podcast videos, display research findings (after summary, before insights):

```python
import json as _json  # if json not already imported in app.py

# Inside the STATUS_DONE display block:
research_raw = video.get("research_data", "")
research_data = {}
if research_raw:
    try:
        research_data = _json.loads(research_raw) if isinstance(research_raw, str) else research_raw
    except (_json.JSONDecodeError, TypeError):
        pass

# Guest research
guest = research_data.get("guest", {})
if guest and guest.get("bio"):
    st.markdown('<div class="section-head">🔍 Guest research</div>', unsafe_allow_html=True)
    st.markdown(
        f"""<div class="panel" style="border-left: 3px solid #f59e0b;">
            <div class="panel-title" style="font-size: 1.05rem;">{_esc(guest.get('name', 'Guest'))}</div>
            <p style="color: #cbd5e1; margin: 8px 0; font-size: 0.92rem;">{_esc(guest.get('bio', ''))}</p>
        </div>""",
        unsafe_allow_html=True,
    )
    viral = guest.get("viral_things", [])
    if viral:
        for item in viral:
            st.markdown(f'<div class="kp"><span class="num">🔥</span><span>{_esc(item)}</span></div>', unsafe_allow_html=True)
    discussions = guest.get("discussions", [])
    if discussions:
        for item in discussions:
            st.markdown(f'<div class="kp"><span class="num">💬</span><span>{_esc(item)}</span></div>', unsafe_allow_html=True)

# Topic research
topics_researched = research_data.get("topics", [])
if topics_researched:
    st.markdown('<div class="section-head">🔬 Topic research</div>', unsafe_allow_html=True)
    for td in topics_researched:
        topic_name = td.get("topic", "")
        what_it_is = td.get("what_it_is", "")
        if topic_name:
            st.markdown(
                f"""<div class="panel" style="border-left: 3px solid #6366f1;">
                    <div class="panel-title" style="font-size: 1rem;">{_esc(topic_name)}</div>
                    <p style="color: #cbd5e1; margin: 4px 0; font-size: 0.88rem;">{_esc(what_it_is)}</p>
                </div>""",
                unsafe_allow_html=True,
            )
        for item in td.get("notable", []):
            st.markdown(f'<div class="kp"><span class="num">📰</span><span>{_esc(item)}</span></div>', unsafe_allow_html=True)
        for item in td.get("hot_takes", []):
            st.markdown(f'<div class="kp"><span class="num">💬</span><span>{_esc(item)}</span></div>', unsafe_allow_html=True)
```

### 5d. Holistic insights display

The key_points list now contains clustered insights with 📌 (agenda) and 💡 (other) prefixes. Display them directly — they're already structured by process_video. The flat key_points format works for both old and new data.

For podcast videos, the existing key_points display loop works as-is since process_video builds the flat list with topic headers and points. No separate agenda/general split needed.

```python
# Works for both podcast and general videos:
headline = "Deep insights" if is_podcast else "Key points"
st.markdown(f'<div class="section-head">{headline}</div>', unsafe_allow_html=True)
points = db.parse_key_points(video.get("key_points", "[]"))
if points:
    for i, point in enumerate(points, 1):
        # Topic headers (start with 📌 or 💡) get styled differently
        if point.startswith("📌") or point.startswith("💡"):
            kp_style = "kp podcast" if point.startswith("📌") else "kp"
            st.markdown(
                f'<div class="{kp_style}" style="background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1);">'
                f'<span style="font-weight:600;">{_esc(point)}</span></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div class="{kp_class}"><span class="num">{i:02d}</span><span>{_esc(point)}</span></div>',
                unsafe_allow_html=True,
            )
else:
    st.caption("No insights extracted.")
```

---

## Change 6: Config Files

### File: `requirements.txt`
Add:
```
tavily-python>=0.5.0
```

### File: `config.example.env`
Add:
```
# Optional: enables guest research (web search for viral things, reddit discussions, etc.)
# Free tier: 1000 searches/month — sign up at tavily.com
TAVILY_API_KEY=tvly-xxxxxxxxxxxxx
```

---

## Change 7: Chat With This Video

### File: `pipeline.py` — Add chat function

No RAG, no vector DB. The full transcript already fits in context (2hr = ~22K tokens, 5hr = ~55K tokens — well within 128K).

```python
def chat_with_video(video_id: str, user_message: str, chat_history: list[dict] | None = None) -> str:
    """Chat with a video's transcript. Full transcript as context, no RAG needed."""
    video = db.get_video(video_id)
    if not video:
        return "Video not found."

    transcript, _ = get_transcript(video_id)
    if not transcript.strip():
        return "No transcript available for this video."

    profile_prompt = db.get_profile_prompt()

    messages = []

    system_content = f"""{profile_prompt}

You are a helpful assistant that answers questions about a specific video.
Video title: "{video.get('title', '')}"

You have the full transcript below. Answer the user's questions based ONLY on what's in the transcript.
Be specific — quote or paraphrase the exact parts that answer their question.
If the transcript doesn't cover what they're asking, say so honestly.

Full transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""
    messages.append({"role": "system", "content": system_content})

    if chat_history:
        for msg in chat_history[-10:]:  # Keep last 10 messages to stay within context
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=SUMMARY_MODEL,
        messages=messages,
        temperature=0.4,
    )
    return response.choices[0].message.content or ""
```

### File: `app.py` — Chat UI at the bottom of video detail

For DONE videos (both general and podcast), add a chat section after the insights:

```python
# ── Chat with this video ────────────────────────────────────────────────
if video["status"] == db.STATUS_DONE:
    st.markdown('<div class="section-head">💬 Chat with this video</div>', unsafe_allow_html=True)
    st.caption("Ask anything about this video — the full transcript is used as context.")

    # Chat history in session state
    chat_key = f"chat_{video['video_id']}"
    if chat_key not in st.session_state:
        st.session_state[chat_key] = []

    # Display chat history
    for msg in st.session_state[chat_key]:
        if msg["role"] == "user":
            st.markdown(f'<div class="kp" style="border-left: 3px solid #6366f1;"><span>{_esc(msg["content"])}</span></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="summary-card">{_esc(msg["content"])}</div>', unsafe_allow_html=True)

    # Input
    user_q = st.text_input(
        "Ask a question",
        placeholder="e.g. What exactly did they say about remote work salaries?",
        key=f"chat_input_{video['video_id']}",
        label_visibility="collapsed",
    )
    if st.button("Ask", key=f"chat_send_{video['video_id']}"):
        if user_q.strip():
            st.session_state[chat_key].append({"role": "user", "content": user_q.strip()})
            with st.spinner("Thinking…"):
                from pipeline import chat_with_video
                answer = chat_with_video(
                    video["video_id"],
                    user_q.strip(),
                    chat_history=st.session_state[chat_key][:-1],  # history without current question
                )
            st.session_state[chat_key].append({"role": "assistant", "content": answer})
            st.rerun()

    if st.session_state[chat_key] and st.button("Clear chat", key=f"chat_clear_{video['video_id']}"):
        st.session_state[chat_key] = []
        st.rerun()
```

---

## LLM Model Strategy

All tasks use **Groq** with `llama-3.3-70b-versatile` (128K context, fast, free/cheap).

| Task | Model | Provider | Why this model |
|------|-------|----------|----------------|
| Transcription | `whisper-large-v3-turbo` | Groq | Best speed/accuracy for audio |
| Recon (identify guest, topics) | `llama-3.3-70b-versatile` | Groq | Structural analysis — doesn't need top-tier |
| Auto-agenda generation | `llama-3.3-70b-versatile` | Groq | Profile → bullet points — straightforward |
| Research synthesis | `llama-3.3-70b-versatile` | Groq | Summarizing search results — fast is better |
| **Agenda deep-dive** | `llama-3.3-70b-versatile` | Groq | Quality matters most here — upgrade candidate |
| **General sweep** | `llama-3.3-70b-versatile` | Groq | Quality matters here too — upgrade candidate |
| **Chat with video** | `llama-3.3-70b-versatile` | Groq | Conversational — needs to be fast |

**Future upgrade path (optional, not part of this implementation):**
If extraction quality isn't deep enough, swap JUST the agenda deep-dive and general sweep to Claude Sonnet or GPT-4o. The architecture already isolates these calls — just change which API `_call_groq` routes to for those two passes. Add a `DEEP_EXTRACTION_PROVIDER` env var later if needed.

---

## Files Modified — Summary

| File | Changes |
|------|---------|
| `db.py` | Profile system (profile.json), 2 new columns (research_data, auto_agenda), updated `should_auto_process()`, migration |
| `pipeline.py` | Multi-pass processing, auto-agenda generation, remove 12K chunking, new prompts, `chat_with_video()` |
| `researcher.py` | **NEW** — Tavily web search for guests AND topics + Groq LLM synthesis |
| `poll.py` | Remove agenda gate for podcasts, save new fields to DB |
| `app.py` | Profile editor, auto-agenda display, override UX, research panel, grouped insights, chat UI |
| `requirements.txt` | Add `tavily-python` |
| `config.example.env` | Add `TAVILY_API_KEY` |

## LLM Calls per Podcast

| Step | Calls | What it sees |
|------|-------|-------------|
| Recon | 1 | Full transcript |
| Auto-agenda generation | 1 | Profile + recon results |
| Guest research synthesis | 1 | Tavily search results for guest |
| Topic research synthesis | 1-3 | Tavily search results per topic (up to 3 topics) |
| Holistic deep extraction | 1 | Full transcript + agenda + all research + profile |
| **Total (per podcast)** | **5-7** | vs old 9-11 blind chunked calls |
| Chat (per question) | 1 | Full transcript + chat history |

## Important Notes

- **DO NOT modify** `transcriber.py` or `youtube_monitor.py`
- Research gracefully handles missing `TAVILY_API_KEY` — returns empty results, doesn't crash
- Old videos in `awaiting_agenda` status still work — user can manually trigger from dashboard
- General playlist videos keep the simpler single-pass flow (no auto-agenda needed)
- All new DB columns use `_ensure_columns` migration (ALTER TABLE with defaults)
- Keep ALL existing dark theme CSS unchanged
- `import json` is already in db.py; ensure it's in poll.py and app.py too

## Verification

1. **Set up profile**: Fill in all 4 sections in the dashboard sidebar
2. **Test auto-processing**: Add a podcast to the playlist → run `python poll.py` → verify it processes automatically without requiring an agenda
3. **Check auto-agenda**: Open the dashboard → the processed podcast should show "Agent's Auto-Generated Focus" with agenda items tailored to your profile
4. **Check guest research**: If TAVILY_API_KEY is set, the Guest Research panel should show bio, viral things, and discussions
5. **Check topic research**: The Topic Research panel should show context for key topics discussed (e.g. a technology, framework, concept)
6. **Check holistic insights**: Insights should cover the ENTIRE video — agenda items go deep (📌) and other important moments are captured too (💡)
6. **Test override**: Write a custom agenda → click Regenerate → verify insights change to match the custom focus
7. **Test without Tavily key**: Remove TAVILY_API_KEY → process a podcast → should still work, just without research panel
8. **General playlist**: Add a general video → verify it still works with the simpler single-pass flow
9. **Chat**: On any DONE video, type a question in the chat box → verify it answers based on the transcript
10. **Chat follow-up**: Ask a follow-up question → verify it remembers the previous exchange
11. **Chat on general video**: Verify chat also works on general (non-podcast) videos
