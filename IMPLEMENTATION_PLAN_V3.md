# Implementation Plan V3: Deep Insight Agent

> **Supersedes V1 and V2.** Uses a hybrid API setup: Groq for fast/small LLM calls, Gemini for transcription fallback + heavy extraction, Tavily for web research.

---

## What This Agent Does (Simple Version)

You add a YouTube video to your playlist. The agent automatically:
1. Gets the transcript (YouTube captions or Gemini)
2. Figures out who the guest is and what topics are covered (Groq)
3. Generates a focus agenda from YOUR profile (Groq)
4. Researches the guest and topics on the web (Tavily + Groq)
5. Extracts deep, comprehensive insights (Gemini)
6. Shows everything on a dashboard with a chat feature

**You do nothing except add videos to a playlist. Come back later, insights are ready.**

---

## API Setup — 3 Keys, 3 Companies

| Key | Where to get it | What it does | Cost |
|-----|----------------|-------------|------|
| `GROQ_API_KEY` | console.groq.com | Fast LLM calls (recon, agenda, research, chat) | Free tier |
| `GEMINI_API_KEY` | aistudio.google.com → Get API Key | Transcription fallback + main extraction | Free tier or ~$0.05/podcast |
| `TAVILY_API_KEY` | tavily.com | Web search for guest + topic research | Free (1000 searches/month) |

Your `.env` file:
```
YOUTUBE_API_KEY=...
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AI...
TAVILY_API_KEY=tvly-...
```

**Total cost per podcast: $0.00 to $0.09**

---

## Which API Does What (and Why)

```
Video added to playlist
    |
    v
Step 1: Get transcript
    YouTube captions? --yes--> FREE, done
    No captions? ---------> Gemini audio transcription ($0.04)
    |
    v
Step 2: Recon — who is the guest, what topics? (GROQ — fast, small call)
    |
    v
Step 3: Auto-agenda from your profile (GROQ — fast, small call)
    |
    v
Step 4: Research guest + topics on the web (TAVILY search + GROQ synthesis)
    |
    v
Step 5: Deep extraction — full transcript + everything above (GEMINI — big call, best quality)
    |
    v
Dashboard shows insights. You can chat with the video (GROQ — fast for interactive chat).
```

**Why this split:**
- **Groq** is fast and free — perfect for small calls where speed matters (recon, agenda, chat)
- **Gemini** has a massive 1M token context window — handles even 5-hour podcasts easily. Better extraction quality than LLaMA for the big important call
- **Tavily** is built for AI agent web search — clean results, no HTML parsing

---

## Current Files (read these before editing)

| File | Lines | Purpose |
|------|-------|---------|
| `db.py` | 234 | SQLite storage, knowledge base, video CRUD |
| `pipeline.py` | 222 | Transcript fetch + LLM summarization (currently 12K char chunking) |
| `transcriber.py` | 112 | yt-dlp + Groq Whisper. **DO NOT MODIFY.** |
| `app.py` | 391 | Streamlit dashboard |
| `poll.py` | 147 | Playlist polling + dispatch |
| `youtube_monitor.py` | ~50 | YouTube API wrapper. **DO NOT MODIFY.** |

---

## Change 1: Profile System (replaces knowledge base)

### File: `db.py`

Replace the plain text `knowledge_base.txt` with a structured `data/profile.json`:

```json
{
    "about_me": "I'm a CS student working in AI...",
    "interests": "Deep technical details, personality insights...",
    "insight_style": "Specific names, tools, numbers — not generic advice.",
    "known_topics": "Python basics, REST APIs, how transformers work..."
}
```

**Add these functions:**

```python
import json
from pathlib import Path

PROFILE_PATH = BASE_DIR / "data" / "profile.json"

DEFAULT_PROFILE = {
    "about_me": "",
    "interests": "",
    "insight_style": "",
    "known_topics": "",
}

def get_profile() -> dict:
    """Load user profile from data/profile.json."""
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return dict(DEFAULT_PROFILE)
    return dict(DEFAULT_PROFILE)

def set_profile(profile: dict) -> None:
    """Save user profile."""
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

def get_profile_prompt() -> str:
    """Format profile into a block that goes into every LLM prompt."""
    p = get_profile()
    sections = []
    if p.get("about_me", "").strip():
        sections.append(f"About the user: {p['about_me'].strip()}")
    if p.get("interests", "").strip():
        sections.append(f"User's key interests and passions: {p['interests'].strip()}")
    if p.get("insight_style", "").strip():
        sections.append(f"How the user wants insights delivered: {p['insight_style'].strip()}")
    if p.get("known_topics", "").strip():
        sections.append(f"Topics the user already knows well (skip unless the video adds something new):\n{p['known_topics'].strip()}")
    if not sections:
        return ""
    return "USER PROFILE — use this to shape your extraction, tone, and depth:\n---\n" + "\n\n".join(sections) + "\n---"
```

**Migration:** In `init_db()`, if `knowledge_base.txt` exists and `profile.json` does not, move the text into `known_topics`.

**New DB columns** (use existing `_ensure_columns` pattern):
- `research_data TEXT NOT NULL DEFAULT ''` — stores guest + topic research as JSON
- `auto_agenda TEXT NOT NULL DEFAULT ''` — the agenda the agent auto-generated

**Update `upsert_video()`** to accept and store these two new fields.

**Update `should_auto_process()`** — podcasts now auto-process like general videos:

```python
def should_auto_process(video: dict[str, Any] | None) -> bool:
    if not video:
        return True
    return video["status"] in (STATUS_PENDING, STATUS_FAILED)
```

Keep `STATUS_AWAITING_AGENDA` as a constant (don't break old DB rows) but don't use it for new videos.

---

## Change 2: Pipeline — Multi-Pass with Groq + Gemini

### File: `pipeline.py`

**Remove:** `MAX_CHUNK_CHARS = 12000`, `_chunk_text()`, `_summarize_chunk()`, old `summarize_transcript()`.

**Keep:** `_parse_json_response()`, `_fetch_youtube_captions()`, `get_transcript()`.

**Replace `_call_groq()`** with two separate LLM callers:

```python
import os
import google.generativeai as genai
from groq import Groq

GROQ_MODEL = os.environ.get("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
MAX_FULL_TRANSCRIPT_CHARS = 320000  # ~80K tokens

def _call_groq(prompt: str) -> str:
    """Fast LLM call via Groq. Used for small/quick tasks."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return response.choices[0].message.content or ""

def _call_gemini(prompt: str) -> str:
    """Heavy LLM call via Gemini. Used for big extraction tasks."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(prompt)
    return response.text or ""
```

**Add Gemini transcription fallback** — update `get_transcript()`:

```python
def get_transcript(video_id: str) -> tuple[str, str]:
    """Get transcript: YouTube captions first, then Gemini audio, then Groq Whisper."""
    # 1. Try YouTube captions (free)
    captions = _fetch_youtube_captions(video_id)
    if captions and len(captions.strip()) > 100:
        return captions, "youtube_captions"

    # 2. Try Gemini audio transcription (cheap — $0.04 for 2hrs)
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            transcript = _transcribe_with_gemini(video_id)
            if transcript and len(transcript.strip()) > 100:
                return transcript, "gemini_audio"
        except Exception:
            pass

    # 3. Fall back to Groq Whisper (existing code in transcriber.py)
    from transcriber import transcribe_youtube_audio
    transcript, source = transcribe_youtube_audio(video_id)
    return transcript, source
```

**Gemini audio transcription function:**

```python
import tempfile
from pathlib import Path

def _transcribe_with_gemini(video_id: str) -> str:
    """Download audio and transcribe using Gemini's audio understanding."""
    from transcriber import download_youtube_audio

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return ""

    genai.configure(api_key=api_key)

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = download_youtube_audio(video_id, Path(tmp))
        uploaded_file = genai.upload_file(str(audio_path))

        model = genai.GenerativeModel(GEMINI_MODEL)
        response = model.generate_content([
            "Transcribe this audio completely and accurately. Output ONLY the transcript text, nothing else. "
            "If speakers mix languages (e.g. Urdu and English), transcribe Urdu words in Roman Urdu (Latin script). "
            "Keep all English words in English.",
            uploaded_file,
        ])
        return response.text or ""
```

### Pass 1 — Recon (uses Groq — fast, small call)

```python
def _recon_pass(transcript: str, title: str) -> dict:
    """Identify guest, topics, structure. Quick scan of the transcript."""
    prompt = f"""Analyze this podcast/video transcript and extract structural information.

Video title: "{title}"

Return ONLY valid JSON:
{{
    "guest_name": "name of the main guest/interviewee, or empty string if no clear guest",
    "guest_description": "1-2 sentence description of who they are based on the transcript",
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

### Auto-Agenda Generation (uses Groq — small call)

```python
def _generate_auto_agenda(recon: dict, profile_prompt: str) -> str:
    """Generate a tailored agenda from user profile + video recon."""
    if not profile_prompt.strip():
        topics = recon.get("main_topics", [])
        return "\n".join(f"* {t}" for t in topics[:6]) if topics else "* Key insights and takeaways"

    guest_info = ""
    if recon.get("guest_name"):
        guest_info = f"Guest: {recon['guest_name']} -- {recon.get('guest_description', '')}"

    topics_str = ", ".join(recon.get("main_topics", []))

    prompt = f"""{profile_prompt}

Based on the user profile above, generate a focused agenda for extracting insights from this video.

{guest_info}
Main topics covered: {topics_str}
Interview format: {"Yes" if recon.get("is_interview") else "No"}

Generate 4-7 specific agenda items that this PARTICULAR user would want deep insights on.

Rules:
- Each item should be specific, not vague
- Tailor to the user's interests and background
- If it's an interview, include at least one item about the guest as a person
- Include items about technical details the user would care about
- Skip topics the user already knows well

Return ONLY a bullet list, one item per line, starting with *
"""
    raw = _call_groq(prompt)
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip().startswith("*")]
    return "\n".join(lines) if lines else raw.strip()
```

### Holistic Deep Extraction (uses GEMINI — the big important call)

```python
def _holistic_extraction(transcript: str, title: str, *, recon: dict, agenda: str, profile_prompt: str, research_summary: str) -> dict:
    """The main extraction. Full transcript + all context. Uses Gemini for quality + large context."""
    research_block = ""
    if research_summary.strip():
        research_block = f"""
External research context (use this to enrich your insights):
---
{research_summary}
---
"""

    guest_line = ""
    if recon.get("guest_name"):
        guest_line = f"Guest: {recon.get('guest_name', '')} -- {recon.get('guest_description', '')}"

    prompt = f"""{profile_prompt}

You are extracting deep, comprehensive insights from a podcast/video titled "{title}".
{guest_line}
{research_block}
The user has priority focus areas (agenda), but you must also capture EVERY important moment from the entire video. Think of the agenda as "go extra deep here" not "only extract this."

Priority focus areas (go deepest on these):
---
{agenda}
---

Return ONLY valid JSON:
{{
    "summary": "4-6 sentence holistic overview of the entire video",
    "insights": [
        {{
            "topic": "short label for this insight cluster",
            "is_agenda_item": true/false,
            "points": ["detailed specific point 1", "detailed specific point 2", ...]
        }}
    ]
}}

Rules:
- Agenda item clusters (is_agenda_item: true) go DEEP: 4-8 points each with specific names, numbers, tools, quotes, anecdotes
- Other important clusters (is_agenda_item: false): 2-4 points each
- Total: aim for 15-30+ insights across all clusters depending on video length
- Each point should be 1-3 sentences of SPECIFIC information, not vague summaries
- Include direct quotes when they're powerful or memorable
- Do NOT skip important moments just because they're not on the agenda
- The user's profile tells you who they are — use it to judge what's "important"

Full transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""
    raw = _call_gemini(prompt)
    return _parse_json_response(raw)
```

### Updated `process_video` — Full Flow

```python
def process_video(video_id: str, title: str, *, playlist_type: str = db.PLAYLIST_GENERAL, user_agenda: str = "") -> dict:
    transcript, source = get_transcript(video_id)
    if not transcript.strip():
        raise RuntimeError("Empty transcript")

    profile_prompt = db.get_profile_prompt()

    if playlist_type == db.PLAYLIST_PODCAST:
        # === PODCAST: Multi-pass deep processing ===

        # Pass 1: Recon (Groq — fast)
        recon = _recon_pass(transcript, title)

        # Auto-generate or use manual agenda (Groq — fast)
        if user_agenda.strip():
            agenda = user_agenda.strip()
            auto_agenda = ""
        else:
            agenda = _generate_auto_agenda(recon, profile_prompt)
            auto_agenda = agenda

        # Research guest + topics (Tavily search + Groq synthesis)
        research_summary = ""
        research_data = {}
        from researcher import research_guest_and_topics
        research_data = research_guest_and_topics(
            guest_name=recon.get("guest_name", "").strip(),
            topics=recon.get("main_topics", []),
        )
        research_summary = research_data.get("combined_summary", "")

        # Deep extraction (Gemini — the big call)
        result = _holistic_extraction(
            transcript, title,
            recon=recon, agenda=agenda,
            profile_prompt=profile_prompt, research_summary=research_summary,
        )

        # Build flat key_points for backward compatibility
        key_points = []
        for cluster in result.get("insights", []):
            prefix = "==" if cluster.get("is_agenda_item") else "--"
            key_points.append(f"{prefix} {cluster.get('topic', '')}")
            key_points.extend(cluster.get("points", []))

        return {
            "summary": result.get("summary", ""),
            "key_points": key_points,
            "transcript_source": source,
            "research_data": research_data,
            "auto_agenda": auto_agenda,
        }

    # === GENERAL: Single-pass (Gemini for quality) ===
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
    raw = _call_gemini(prompt)
    parsed = _parse_json_response(raw)
    return {
        "summary": parsed.get("summary", ""),
        "key_points": parsed.get("key_points", []),
        "transcript_source": source,
    }
```

### Chat With Video (uses Groq — needs to be fast for interactive use)

```python
def chat_with_video(video_id: str, user_message: str, chat_history: list[dict] | None = None) -> str:
    """Chat about a video. Full transcript as context, no RAG needed."""
    video = db.get_video(video_id)
    if not video:
        return "Video not found."

    transcript, _ = get_transcript(video_id)
    if not transcript.strip():
        return "No transcript available for this video."

    profile_prompt = db.get_profile_prompt()

    messages = []
    system_content = f"""{profile_prompt}

You are a helpful assistant answering questions about a specific video.
Video title: "{video.get('title', '')}"

Answer based ONLY on what's in the transcript. Be specific — quote or paraphrase exact parts.
If the transcript doesn't cover what they're asking, say so honestly.

Full transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""
    messages.append({"role": "system", "content": system_content})

    if chat_history:
        for msg in chat_history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    response = Groq(api_key=os.environ.get("GROQ_API_KEY")).chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.4,
    )
    return response.choices[0].message.content or ""
```

---

## Change 3: Web Research Module

### NEW File: `researcher.py`

Searches the web for info about the podcast guest AND topics discussed. Uses Tavily for search, Groq for summarizing results.

```python
"""Web research on podcast guests and topics via Tavily search + Groq synthesis."""

import json
import os
import re

from groq import Groq

SUMMARY_MODEL = os.environ.get("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")


def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Run a single web search."""
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
    """Run multiple searches, remove duplicates, format for LLM."""
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
    """Call Groq LLM and parse JSON from response."""
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
    "bio": "1-2 sentence bio",
    "viral_things": ["most notable/viral thing 1", "thing 2", ...],
    "discussions": ["what people debate about them 1", "topic 2", ...],
    "summary": "2-3 sentence essential context about this person"
}}

Up to 5 items each. Only include things supported by search results.""")
    result["name"] = name
    return result


def _research_topics(topics: list[str]) -> list[dict]:
    """Research key topics: notable articles, viral discussions."""
    if not topics:
        return []
    researched = []
    for topic in topics[:3]:
        if len(topic) < 4:
            continue
        search_text = _collect_search_results([
            f'"{topic}" explained OR guide OR overview',
            f'"{topic}" viral OR trending OR most important',
            f'"{topic}" site:reddit.com discussion',
        ], max_per_query=2)
        if not search_text:
            continue

        result = _call_groq_json(f"""Based on these web search results about "{topic}", create a brief.

Search results:
{search_text}

Return ONLY valid JSON:
{{
    "topic": "{topic}",
    "what_it_is": "1 sentence explanation",
    "notable": ["most important thing about this 1", "thing 2", ...],
    "hot_takes": ["what people debate about it 1", "take 2", ...],
    "summary": "1-2 sentence context for understanding a podcast about this"
}}

Up to 3 items each. Only include things supported by search results.""")
        result["topic"] = topic
        researched.append(result)
    return researched


def research_guest_and_topics(*, guest_name: str = "", topics: list[str] | None = None) -> dict:
    """
    Main entry point. Researches the guest AND key topics.
    Returns empty results gracefully if TAVILY_API_KEY is not set.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return {"guest": {}, "topics": [], "combined_summary": ""}

    guest_data = _research_person(guest_name) if guest_name else {}
    topics_data = _research_topics(topics or [])

    parts = []
    if guest_data.get("summary"):
        parts.append(f"GUEST -- {guest_name}: {guest_data['summary']}")
        if guest_data.get("viral_things"):
            parts.append("Notable: " + "; ".join(guest_data["viral_things"][:3]))
    for td in topics_data:
        if td.get("summary"):
            parts.append(f"TOPIC -- {td.get('topic', '')}: {td['summary']}")
            if td.get("notable"):
                parts.append("Notable: " + "; ".join(td["notable"][:2]))

    return {
        "guest": guest_data,
        "topics": topics_data,
        "combined_summary": "\n".join(parts),
    }
```

---

## Change 4: Auto-Process Podcasts

### File: `poll.py`

Two small changes:

**1. Remove the agenda gate.** Delete or comment out the block that prevents podcast processing when there's no agenda (around lines 43-45):

```python
# DELETE THIS:
# if video["playlist_type"] == db.PLAYLIST_PODCAST and not video.get("user_agenda", "").strip():
#     print(f"[poll] Podcast video needs an agenda first: {video['title']}", file=sys.stderr)
#     db.upsert_video(video_id, status=db.STATUS_AWAITING_AGENDA)
#     return 1
```

**2. Save new fields** after processing (update the `upsert_video` call around line 58-65):

```python
import json

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

---

## Change 5: Dashboard Updates

### File: `app.py`

### 5a. Profile editor (replaces old knowledge base sidebar)

Replace the knowledge base expander (around lines 190-201) with:

```python
with st.expander("My Profile", expanded=False):
    st.caption("Your profile shapes how insights are extracted. Be specific.")
    profile = db.get_profile()

    about = st.text_area("About me", value=profile.get("about_me", ""), height=80,
        placeholder="e.g. I'm a CS student working in AI...", key="profile_about")
    interests = st.text_area("My interests", value=profile.get("interests", ""), height=80,
        placeholder="e.g. Deep technical details, personality insights...", key="profile_interests")
    style = st.text_area("Insight style", value=profile.get("insight_style", ""), height=60,
        placeholder="e.g. Specific names, tools, numbers — not generic advice.", key="profile_style")
    known = st.text_area("Topics I already know", value=profile.get("known_topics", ""), height=100,
        placeholder="e.g. Python basics, REST APIs, how transformers work...", key="profile_known")

    if st.button("Save profile", use_container_width=True):
        db.set_profile({"about_me": about, "interests": interests, "insight_style": style, "known_topics": known})
        st.success("Profile saved")
```

### 5b. Show auto-agenda + allow override

For podcast videos, show what the agent focused on and let user override:

```python
if is_podcast and video["status"] == db.STATUS_DONE:
    auto_agenda = video.get("auto_agenda", "")
    user_agenda = video.get("user_agenda", "")

    if auto_agenda and not user_agenda:
        st.markdown('<div class="section-head">Agent\'s Auto-Generated Focus</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="agenda-display">{_esc(auto_agenda)}</div>', unsafe_allow_html=True)
        st.caption("Auto-generated from your profile. Override below if you want different focus.")
    elif user_agenda:
        st.markdown('<div class="section-head">Your Custom Agenda</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="agenda-display">{_esc(user_agenda)}</div>', unsafe_allow_html=True)

if is_podcast:
    with st.expander("Custom agenda override", expanded=(video["status"] != db.STATUS_DONE)):
        st.caption("Write a custom agenda to regenerate with different focus areas.")
        agenda_key = f"agenda_{video['video_id']}"
        if agenda_key not in st.session_state:
            st.session_state[agenda_key] = video.get("user_agenda") or ""

        agenda = st.text_area("Custom agenda", height=140, placeholder=AGENDA_EXAMPLE,
            label_visibility="collapsed", key=agenda_key)
        if st.button("Regenerate with this agenda", type="primary", use_container_width=True):
            if not agenda.strip():
                st.warning("Write your custom agenda first.")
            else:
                db.upsert_video(video["video_id"], user_agenda=agenda.strip(),
                    status=db.STATUS_PENDING, error_message="")
                with st.spinner("Regenerating with your custom agenda..."):
                    process_one(video["video_id"])
                st.rerun()
```

### 5c. Research panel (guest + topics)

For DONE podcast videos, show research findings:

```python
import json as _json

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
    st.markdown('<div class="section-head">Guest Research</div>', unsafe_allow_html=True)
    st.markdown(
        f"""<div class="panel" style="border-left: 3px solid #f59e0b;">
            <div class="panel-title" style="font-size: 1.05rem;">{_esc(guest.get('name', 'Guest'))}</div>
            <p style="color: #cbd5e1; margin: 8px 0; font-size: 0.92rem;">{_esc(guest.get('bio', ''))}</p>
        </div>""", unsafe_allow_html=True)
    for item in guest.get("viral_things", []):
        st.markdown(f'<div class="kp"><span class="num">VIRAL</span><span>{_esc(item)}</span></div>', unsafe_allow_html=True)
    for item in guest.get("discussions", []):
        st.markdown(f'<div class="kp"><span class="num">TALK</span><span>{_esc(item)}</span></div>', unsafe_allow_html=True)

# Topic research
topics_researched = research_data.get("topics", [])
if topics_researched:
    st.markdown('<div class="section-head">Topic Research</div>', unsafe_allow_html=True)
    for td in topics_researched:
        topic_name = td.get("topic", "")
        what_it_is = td.get("what_it_is", "")
        if topic_name:
            st.markdown(
                f"""<div class="panel" style="border-left: 3px solid #6366f1;">
                    <div class="panel-title" style="font-size: 1rem;">{_esc(topic_name)}</div>
                    <p style="color: #cbd5e1; margin: 4px 0; font-size: 0.88rem;">{_esc(what_it_is)}</p>
                </div>""", unsafe_allow_html=True)
        for item in td.get("notable", []):
            st.markdown(f'<div class="kp"><span class="num">KEY</span><span>{_esc(item)}</span></div>', unsafe_allow_html=True)
        for item in td.get("hot_takes", []):
            st.markdown(f'<div class="kp"><span class="num">TALK</span><span>{_esc(item)}</span></div>', unsafe_allow_html=True)
```

### 5d. Insights display

The key_points list has clusters with `==` (agenda) and `--` (other) prefixes. Display them:

```python
headline = "Deep insights" if is_podcast else "Key points"
st.markdown(f'<div class="section-head">{headline}</div>', unsafe_allow_html=True)
points = db.parse_key_points(video.get("key_points", "[]"))
if points:
    for i, point in enumerate(points, 1):
        if point.startswith("==") or point.startswith("--"):
            bg = "rgba(255,255,255,0.04)" if point.startswith("==") else "rgba(255,255,255,0.02)"
            st.markdown(
                f'<div class="kp" style="background:{bg}; border:1px solid rgba(255,255,255,0.1);">'
                f'<span style="font-weight:600;">{_esc(point[3:])}</span></div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<div class="{kp_class}"><span class="num">{i:02d}</span><span>{_esc(point)}</span></div>',
                unsafe_allow_html=True)
else:
    st.caption("No insights extracted.")
```

### 5e. Chat UI

For DONE videos, add a chat section at the bottom:

```python
if video["status"] == db.STATUS_DONE:
    st.markdown('<div class="section-head">Chat with this video</div>', unsafe_allow_html=True)
    st.caption("Ask anything — the full transcript is used as context.")

    chat_key = f"chat_{video['video_id']}"
    if chat_key not in st.session_state:
        st.session_state[chat_key] = []

    for msg in st.session_state[chat_key]:
        if msg["role"] == "user":
            st.markdown(f'<div class="kp" style="border-left: 3px solid #6366f1;"><span>{_esc(msg["content"])}</span></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="summary-card">{_esc(msg["content"])}</div>', unsafe_allow_html=True)

    user_q = st.text_input("Ask a question",
        placeholder="e.g. What exactly did they say about remote work salaries?",
        key=f"chat_input_{video['video_id']}", label_visibility="collapsed")
    if st.button("Ask", key=f"chat_send_{video['video_id']}"):
        if user_q.strip():
            st.session_state[chat_key].append({"role": "user", "content": user_q.strip()})
            with st.spinner("Thinking..."):
                from pipeline import chat_with_video
                answer = chat_with_video(video["video_id"], user_q.strip(),
                    chat_history=st.session_state[chat_key][:-1])
            st.session_state[chat_key].append({"role": "assistant", "content": answer})
            st.rerun()

    if st.session_state[chat_key] and st.button("Clear chat", key=f"chat_clear_{video['video_id']}"):
        st.session_state[chat_key] = []
        st.rerun()
```

---

## Change 6: Config Files

### File: `requirements.txt`

Add:
```
tavily-python>=0.5.0
google-generativeai>=0.8.0
```

### File: `config.example.env`

Add:
```
# Gemini — transcription fallback + main extraction
# Get key at: aistudio.google.com -> Get API Key
GEMINI_API_KEY=AI...

# Tavily — guest + topic web research (optional)
# Free: 1000 searches/month. Sign up at tavily.com
TAVILY_API_KEY=tvly-...
```

---

## Summary: What Each API Does

| Task | API | Why |
|------|-----|-----|
| Transcription (primary) | YouTube captions | Free, works for most videos |
| Transcription (fallback) | **Gemini** audio input | $0.04/2hrs, no separate Whisper API needed |
| Recon scan | **Groq** LLaMA 3.3 | Fast, small call, free tier |
| Auto-agenda | **Groq** LLaMA 3.3 | Fast, small call, free tier |
| Research synthesis | **Groq** LLaMA 3.3 | Fast, small call, free tier |
| **Deep extraction** | **Gemini** 2.5 Flash | Big call, 1M context, best quality for the price |
| General video summary | **Gemini** 2.5 Flash | Same — quality matters |
| Chat with video | **Groq** LLaMA 3.3 | Interactive — needs sub-second response |
| Web search | **Tavily** | Built for AI agents, clean results |

## Cost Per Podcast

| Scenario | Cost |
|----------|------|
| YouTube captions exist (most videos) | **$0.03 - $0.05** |
| No captions, Gemini transcribes | **$0.07 - $0.09** |
| Chat (per question) | **$0.00** (Groq free tier) |

## LLM Calls Per Podcast

| Step | Provider | What it sees |
|------|----------|-------------|
| Recon | Groq | Full transcript |
| Auto-agenda | Groq | Profile + recon |
| Guest research synthesis | Groq | Tavily search results |
| Topic research synthesis (x1-3) | Groq | Tavily search results per topic |
| Deep extraction | Gemini | Full transcript + agenda + research + profile |
| **Total** | | **5-7 calls** |

---

## Files Changed

| File | What changes |
|------|-------------|
| `db.py` | Profile system, 2 new columns, updated auto-process logic |
| `pipeline.py` | Two LLM callers (Groq + Gemini), Gemini transcription, multi-pass, chat |
| `researcher.py` | **NEW** — Tavily search + Groq synthesis |
| `poll.py` | Remove agenda gate, save new fields |
| `app.py` | Profile editor, auto-agenda display, research panel, chat UI |
| `requirements.txt` | Add tavily-python, google-generativeai |
| `config.example.env` | Add GEMINI_API_KEY, TAVILY_API_KEY |
| `transcriber.py` | **DO NOT MODIFY** |
| `youtube_monitor.py` | **DO NOT MODIFY** |

---

## How to Test

1. **Get your keys**: Groq (already have), Gemini (aistudio.google.com), Tavily (tavily.com)
2. **Fill your profile** in the dashboard sidebar — be specific about who you are and what you want
3. **Add a podcast** to your playlist
4. **Run** `python poll.py` — it should auto-process without needing an agenda
5. **Check the dashboard:**
   - Auto-generated agenda shown (tailored to your profile)
   - Guest research panel (bio, viral things, discussions)
   - Topic research panel (context on key topics)
   - Deep insights — agenda items go deep, other important moments captured too
6. **Try chat** — ask a question about the video
7. **Try override** — write a custom agenda, click Regenerate
8. **Test without Tavily** — remove the key, process a video — should still work, just no research panel
9. **Test a general video** — add to general playlist, verify simpler single-pass flow works
