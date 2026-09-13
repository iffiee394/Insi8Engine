"""Transcript fetch + LLM summarization for a single YouTube video."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from groq import Groq
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound
from transcriber import AudioDownloadError

import config
import db
from llm import call_deep_llm, friendly_llm_error
import usage_tracker
from logutil import get_logger

logger = get_logger(__name__)

GROQ_MODEL = config.GROQ_CHAT_MODEL
MAX_FULL_TRANSCRIPT_CHARS = 320000
URL_PATTERN = re.compile(r"https?://[^\s\]\)<>\"']+")


def _friendly_api_error(exc: Exception) -> str:
    return friendly_llm_error(exc)


def _format_timestamp_label(seconds: float) -> str:
    sec = int(seconds)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fetch_caption_segments(video_id: str) -> list[tuple[float, str]] | None:
    """Compatibility wrapper: (start, text) pairs."""
    detailed = _fetch_caption_segment_dicts(video_id)
    if not detailed:
        return None
    return [(float(s["start"]), s["text"]) for s in detailed]


def _fetch_caption_segment_dicts(video_id: str) -> list[dict] | None:
    try:
        api = YouTubeTranscriptApi()
        transcript = None
        try:
            transcript = api.fetch(video_id, languages=("en", "en-US", "en-GB"))
        except NoTranscriptFound:
            # Only retry language selection. An IP block or network error is
            # not evidence that another language request will work.
            transcript_list = api.list(video_id)
            transcript = next(iter(transcript_list)).fetch()

        segments: list[dict] = []
        for seg in transcript:
            text = getattr(seg, "text", None)
            if not text:
                continue
            start = float(getattr(seg, "start", 0) or 0)
            duration = getattr(seg, "duration", None)
            end = None
            if duration is not None:
                try:
                    dur = float(duration)
                    if dur > 0:
                        end = start + dur
                except (TypeError, ValueError):
                    end = None
            segments.append({"start": start, "end": end, "text": text.strip()})
        return segments or None
    except Exception as exc:
        logger.warning("Caption retrieval failed for %s (%s)", video_id, type(exc).__name__)
        return None


def _persist_transcript(video_id: str, data: dict) -> None:
    try:
        import knowledge_store

        knowledge_store.upsert_transcript(
            video_id,
            plain_text=data.get("text") or "",
            timed_segments=data.get("segments") or [],
            source=data.get("source") or "",
            language=data.get("language") or "",
            timing_quality=data.get("timing_quality") or "unknown",
        )
    except Exception as exc:
        logger.warning("[pipeline] Transcript persist failed: %s", exc)


def fetch_transcript_data(video_id: str, *, persist: bool = True, refresh: bool = False) -> dict:
    """Return transcript text, source, timed text, and approximate duration."""
    if persist and not refresh:
        try:
            import knowledge_store

            stored = knowledge_store.get_transcript(video_id)
            if stored and (stored.get("plain_text") or "").strip():
                segments = []
                try:
                    segments = json.loads(stored.get("timed_segments_json") or "[]")
                except json.JSONDecodeError:
                    segments = []
                return {
                    "text": stored["plain_text"],
                    "source": stored.get("source") or "",
                    "timed_text": stored["plain_text"],
                    "duration_seconds": 0,
                    "segments": segments,
                    "timing_quality": stored.get("timing_quality") or "unknown",
                    "from_store": True,
                }
        except Exception:
            pass

    segments = _fetch_caption_segment_dicts(video_id)
    if segments:
        plain = " ".join(s["text"] for s in segments).strip()
        if len(plain) > 100:
            timed = "\n".join(
                f"[{_format_timestamp_label(s['start'])}] {s['text']}" for s in segments
            )
            last_start = segments[-1]["start"]
            duration = int(last_start) + 60
            data = {
                "text": plain,
                "source": "youtube_captions",
                "timed_text": timed,
                "duration_seconds": duration,
                "segments": segments,
                "timing_quality": "exact",
                "from_store": False,
            }
            if persist:
                _persist_transcript(video_id, data)
            return data

    if config.GEMINI_API_KEY:
        try:
            text = _transcribe_with_gemini(video_id)
            if text and len(text.strip()) > 100:
                data = {
                    "text": text.strip(),
                    "source": "gemini_audio",
                    "timed_text": text.strip(),
                    "duration_seconds": 0,
                    "segments": [],
                    "timing_quality": "unknown",
                    "from_store": False,
                }
                if persist:
                    _persist_transcript(video_id, data)
                return data
        except AudioDownloadError:
            # Both providers need the same source audio; do not download twice.
            raise
        except Exception:
            pass

    from transcriber import transcribe_youtube_audio

    text, source = transcribe_youtube_audio(video_id)
    data = {
        "text": text,
        "source": source,
        "timed_text": text,
        "duration_seconds": 0,
        "segments": [],
        "timing_quality": "unknown",
        "from_store": False,
    }
    if persist and (text or "").strip():
        _persist_transcript(video_id, data)
    return data


def get_transcript(video_id: str) -> tuple[str, str]:
    """Get plain transcript text and source label."""
    data = fetch_transcript_data(video_id)
    return data["text"], data["source"]


def _fetch_youtube_captions(video_id: str) -> str | None:
    data = fetch_transcript_data(video_id)
    if data["source"] == "youtube_captions":
        return data["text"]
    return None


def _transcribe_with_gemini(video_id: str) -> str:
    """Optional: transcribe via Gemini when captions are missing."""
    import tempfile
    from google import genai

    from transcriber import download_youtube_audio

    api_key = config.GEMINI_API_KEY
    if not api_key:
        return ""

    client = genai.Client(api_key=api_key)
    prompt = (
        "Transcribe this audio completely. Output ONLY the transcript text. "
        "Urdu in Roman Urdu; keep English in English."
    )
    model = config.GEMINI_CHAT_MODEL

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = download_youtube_audio(video_id, Path(tmp))
        uploaded = client.files.upload(file=str(audio_path))
        response = client.models.generate_content(
            model=model,
            contents=[prompt, uploaded],
        )
        return (response.text or "").strip()


# ── LLM Callers ──────────────────────────────────────────────────────────────

def _call_groq(prompt: str, *, json_mode: bool = False, operation: str = "groq") -> str:
    """Fast LLM call via Groq. Falls back to Gemini/Anthropic on rate limits."""
    api_key = config.GROQ_API_KEY
    if not api_key:
        return call_deep_llm(prompt, json_mode=json_mode, operation=operation)
    client = Groq(api_key=api_key)
    kwargs: dict = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as exc:
        logger.warning("[pipeline] Groq failed (%s) — using deep LLM fallback", str(exc)[:100])
        return call_deep_llm(prompt, json_mode=json_mode, operation=operation)
    text = response.choices[0].message.content or ""
    usage_tracker.record_groq(
        model=GROQ_MODEL,
        operation=operation,
        prompt=prompt,
        response=text,
    )
    return text


# ── JSON Parsing ─────────────────────────────────────────────────────────────

_VALID_ESCAPES = set('"\\/bfnrtu')


def _repair_invalid_escapes(candidate: str) -> str:
    """Double up backslashes that aren't valid JSON escapes.

    LLMs often embed LaTeX (e.g. "$e^{i\\pi}$") in free-text fields; a lone
    backslash there isn't a valid JSON escape and trips json.loads. Since we
    can't tell those from a truly malformed payload, we widen the backslash
    to `\\\\` (a literal backslash) whenever it isn't followed by one of the
    characters JSON actually allows to be escaped.
    """
    out = []
    i = 0
    n = len(candidate)
    while i < n:
        ch = candidate[i]
        if ch == "\\" and i + 1 < n:
            nxt = candidate[i + 1]
            if nxt in _VALID_ESCAPES:
                out.append(ch)
                out.append(nxt)
                i += 2
                continue
            out.append("\\\\")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


_BARE_TIMESTAMP_RE = re.compile(r'(?<=:)(\s*)(\d{1,2}(?::\d{2}){1,2})(\s*)(?=[,}\]])')


def _repair_bare_timestamps(candidate: str) -> str:
    """Convert unquoted `MM:SS`/`H:MM:SS` values into plain seconds.

    Despite the prompt asking for `timestamp_seconds`/`timestamp_range_end` as
    plain integers, the model occasionally reverts to a human timestamp like
    `24:47` written directly as a bare value (`"timestamp_range_end": 24:47,`),
    which isn't valid JSON (a colon can't appear in a bare token). We only
    touch values that immediately follow a `key":` separator and precede a
    `,`/`}`/`]`, so quoted strings containing similar-looking text are left
    alone.
    """

    def convert(m: re.Match) -> str:
        ws1, ts, ws2 = m.groups()
        secs = 0
        for part in ts.split(":"):
            secs = secs * 60 + int(part)
        return f"{ws1}{secs}{ws2}"

    return _BARE_TIMESTAMP_RE.sub(convert, candidate)


def _extract_json_object(text: str) -> dict | None:
    """Extract first balanced {...} object from text."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                for repair in (
                    lambda s: s,
                    _repair_invalid_escapes,
                    _repair_bare_timestamps,
                    lambda s: _repair_bare_timestamps(_repair_invalid_escapes(s)),
                ):
                    try:
                        obj = json.loads(repair(candidate))
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        continue
                return None
    return None


def _parse_json_response(raw: str) -> dict:
    if not raw or not raw.strip():
        raise ValueError("Empty LLM response")

    obj = _extract_json_object(raw)
    if obj:
        return obj

    raise ValueError(f"Could not parse JSON from LLM response: {raw[:300]}...")


def _normalize_key_points(data: dict) -> dict:
    summary = data.get("summary", "")
    if not isinstance(summary, str):
        summary = str(summary)
    points = data.get("key_points", [])
    if isinstance(points, str):
        points = [p.strip("- •\t") for p in points.split("\n") if p.strip()]
    elif not isinstance(points, list):
        points = [str(points)]
    else:
        points = [str(p).strip() for p in points if str(p).strip()]
    return {"summary": summary.strip(), "key_points": points}


# ── Pipeline Passes ──────────────────────────────────────────────────────────

def build_recon_prompt(transcript: str, title: str) -> str:
    return f"""Analyze this podcast/video transcript and extract structural information.

Video title: "{title}"

Return ONLY valid JSON:
{{
    "guest_name": "name of the main guest/interviewee, or empty string if no clear guest",
    "guest_description": "1-2 sentence description of who they are based on the transcript",
    "main_topics": ["topic 1", "topic 2", ...],
    "is_interview": true,
    "estimated_duration": "short/medium/long based on transcript length"
}}

Transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""


def _recon_pass(transcript: str, title: str) -> dict:
    raw = call_deep_llm(build_recon_prompt(transcript, title), operation="recon")
    return _parse_json_response(raw)


def build_entity_prompt(transcript: str, title: str, recon: dict) -> str:
    guest = recon.get("guest_name", "")
    return f"""Analyze this podcast transcript and identify everything worth searching on the web.

Video title: "{title}"
Guest (if known): {guest}

Return ONLY valid JSON:
{{
    "research_targets": [
        {{
            "query": "specific Tavily search query",
            "type": "person_story|company|company_list|tool|other",
            "transcript_context": "what the speaker said",
            "confidence": "confirmed|needs_research|partial_in_transcript"
        }}
    ],
    "urls_in_transcript": ["https://..."],
    "lists_to_expand": [
        {{
            "label": "what the list is about",
            "items_found_in_transcript": ["item1", "item2"],
            "speaker_claimed_count": 0
        }}
    ]
}}

Rules:
- Include unnamed people/stories as needs_research targets
- If speaker claims "50 companies" but only names some, add company_list target + lists_to_expand
- Max 8 research_targets — prioritize the most important/specific

Transcript (first 120k chars):
{transcript[:120000]}
"""


def _generate_auto_agenda(recon: dict, profile_prompt: str) -> str:
    """Generate a tailored agenda from user profile + video recon. Uses Groq."""
    if not profile_prompt.strip():
        topics = recon.get("main_topics", [])
        return "\n".join(f"* {t}" for t in topics[:6]) if topics else "* Key insights and takeaways"

    guest_info = ""
    if recon.get("guest_name"):
        guest_info = f"Guest: {recon['guest_name']} -- {recon.get('guest_description', '')}"

    topics_str = ", ".join(recon.get("main_topics", []))
    interview = "Yes" if recon.get("is_interview") else "No"

    prompt = f"""{profile_prompt}

Based on the user profile above, generate a focused agenda for extracting insights from this video.

{guest_info}
Main topics covered: {topics_str}
Interview format: {interview}

Generate 4-7 specific agenda items that this PARTICULAR user would want deep insights on.

Rules:
- Each item should be specific, not vague
- Tailor to the user's interests and background
- If it's an interview, include at least one item about the guest as a person
- Include items about technical details the user would care about
- Skip topics the user already knows well

Return ONLY a bullet list, one item per line, starting with *
"""
    raw = _call_groq(prompt, json_mode=False, operation="auto_agenda")
    lines = [line.strip() for line in raw.strip().split("\n") if line.strip().startswith("*")]
    return "\n".join(lines) if lines else raw.strip()


def _generate_general_agenda(recon: dict, profile_prompt: str) -> str:
    """Auto agenda for General playlist — holistic coverage of full lecture/video."""
    topics_str = ", ".join(recon.get("main_topics", [])[:8])
    speaker = recon.get("guest_name") or recon.get("guest_description") or ""
    duration = recon.get("estimated_duration", "long")

    prompt = f"""{profile_prompt}

Generate a comprehensive extraction agenda for a YouTube video (lecture, talk, or tutorial).

Speaker/creator context: {speaker or "unknown"}
Main topics detected: {topics_str or "see transcript"}
Estimated length: {duration}

Create 6-10 agenda items that:
1. Cover the FULL video breadth — every major section/theme (not just highlights)
2. Weight heavily toward the user's profile interests and playlist focus above
3. Include frameworks, mental models, step-by-step advice, numbers, and examples
4. For long lectures (40+ min), ensure items map to distinct segments of the content

Return ONLY a bullet list, one item per line, starting with *
"""
    raw = _call_groq(prompt, json_mode=False, operation="general_agenda")
    lines = [line.strip() for line in raw.strip().split("\n") if line.strip().startswith("*")]
    if lines:
        return "\n".join(lines)
    if topics_str:
        return "\n".join(f"* Deep dive: {t}" for t in recon.get("main_topics", [])[:8])
    return "* Key frameworks and mental models\n* Actionable steps and tactics\n* Numbers, examples, and case studies mentioned"


def build_holistic_prompt(
    transcript: str,
    title: str,
    *,
    recon: dict,
    agenda: str,
    profile_prompt: str,
    research_summary: str,
    entity_context: str = "",
    description_context: str = "",
    timed_transcript: str = "",
) -> str:
    research_block = ""
    if research_summary.strip():
        research_block = f"""
External research context (use this to enrich your insights — include names and links when found):
---
{research_summary}
---
"""
    entity_block = ""
    if entity_context.strip():
        entity_block = f"""
Entity/list context from transcript analysis:
---
{entity_context}
---
"""
    desc_block = ""
    if description_context.strip():
        desc_block = f"""
YouTube video description (may contain resource lists and links):
---
{description_context[:8000]}
---
"""

    guest_line = ""
    if recon.get("guest_name"):
        guest_line = f"Guest: {recon.get('guest_name', '')} -- {recon.get('guest_description', '')}"

    return f"""{profile_prompt}

You are extracting deep, comprehensive insights from a podcast/video titled "{title}".
{guest_line}
{research_block}{entity_block}{desc_block}
The user has priority focus areas (agenda), but you must also capture EVERY important moment from the entire video. Think of the agenda as "go extra deep here" not "only extract this."

Priority focus areas (go deepest on these):
---
{agenda}
---

Return ONLY valid JSON:
{{
    "summary": "4-6 sentence holistic overview of the entire video",
    "guest_profile": {{
        "name": "guest name or empty",
        "background": "1-2 sentences",
        "notable_achievements": ["achievement 1"]
    }},
    "resources": [
        {{
            "name": "Relativity Space",
            "type": "company|book|tool|person|paper|other",
            "detail": "how it was mentioned",
            "url": null,
            "source": "transcript|description|research"
        }}
    ],
    "links": {{
        "from_video": [{{"title": "...", "url": "https://...", "context": "..."}}]
    }},
    "insights": [
        {{
            "topic": "short label for this insight cluster",
            "timestamp_seconds": 1423,
            "timestamp_range_end": 1690,
            "is_agenda_item": true,
            "points": ["detailed specific point 1", "detailed specific point 2"]
        }}
    ]
}}

TIMESTAMP RULES:
- For each insight, set timestamp_seconds to the approximate start time (in seconds) where this topic is primarily discussed.
- Use the [MM:SS] or [H:MM:SS] markers in the transcript below to determine timing.
- Set timestamp_range_end to the approximate end of that discussion (seconds). Use null if unknown.
- If the transcript has no timing markers, set timestamp_seconds and timestamp_range_end to null.

STRICT RULES — violations are unacceptable:
- NEVER write "speaker mentioned a list of X" without listing every item found in transcript/description
- If list is partial, show all items found AND note "speaker referenced N total; M captured from transcript"
- NEVER write unnamed people if transcript OR research identified a name — use the name
- Each point must include specific names, numbers, tools, quotes — not vague summaries
- Agenda item clusters (is_agenda_item: true): 4-8 points each
- Other clusters: 2-4 points each
- Total: 15-30+ insight points depending on video length (40+ min lectures: aim for 25-40+ points)
- resources: extract ALL books, companies, tools, frameworks, people mentioned even without URLs

Transcript (with timing markers when available):
{(timed_transcript or transcript)[:MAX_FULL_TRANSCRIPT_CHARS]}
"""


def build_general_prompt(transcript: str, title: str, profile_prompt: str) -> str:
    return f"""{profile_prompt}

You are summarizing a YouTube video titled "{title}".
Write a concise summary and extract the most important, actionable key points.
Be specific: include names, numbers, tools, steps — not generic advice.

Return ONLY valid JSON:
{{"summary": "3-5 sentence overview", "key_points": ["point 1", "point 2", ...]}}

Provide 5-12 key points depending on content density.

Transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
"""


def _extract_urls_from_transcript(transcript: str) -> list[dict]:
    seen: set[str] = set()
    links: list[dict] = []
    for match in URL_PATTERN.finditer(transcript):
        url = match.group(0).rstrip(".,;)")
        if url in seen:
            continue
        seen.add(url)
        host = urlparse(url).netloc or url
        links.append({
            "title": host,
            "url": url,
            "context": "Mentioned in transcript",
            "source": "video",
        })
    return links


def _extract_research_targets(transcript: str, title: str, recon: dict) -> dict:
    raw = call_deep_llm(build_entity_prompt(transcript, title, recon), operation="entities")
    return _parse_json_response(raw)


def _holistic_extraction(
    transcript: str,
    title: str,
    *,
    recon: dict,
    agenda: str,
    profile_prompt: str,
    research_summary: str,
    entity_context: str = "",
    description_context: str = "",
    timed_transcript: str = "",
) -> dict:
    prompt = build_holistic_prompt(
        transcript,
        title,
        recon=recon,
        agenda=agenda,
        profile_prompt=profile_prompt,
        research_summary=research_summary,
        entity_context=entity_context,
        description_context=description_context,
        timed_transcript=timed_transcript,
    )
    raw = call_deep_llm(prompt, operation="holistic_extract")
    return _parse_json_response(raw)


def _format_entity_context(entities: dict) -> str:
    lines = []
    for lst in entities.get("lists_to_expand", []):
        label = lst.get("label", "List")
        items = lst.get("items_found_in_transcript", [])
        claimed = lst.get("speaker_claimed_count")
        if items:
            count_note = f" (speaker claimed ~{claimed})" if claimed else ""
            lines.append(f"{label}{count_note}: {', '.join(items[:30])}")
    for t in entities.get("research_targets", [])[:8]:
        lines.append(f"Research target [{t.get('type')}]: {t.get('query')} — {t.get('transcript_context', '')[:200]}")
    return "\n".join(lines)


def _merge_structured_output(
    result: dict,
    *,
    research_data: dict,
    description_urls: list[dict],
    transcript_urls: list[dict],
    description_resources: list[str],
    duration_seconds: int = 0,
) -> dict:
    links = research_data.get("links") or {}
    grouped = {
        "from_video": _dedupe_link_list(
            (result.get("links") or {}).get("from_video", []) + transcript_urls
        ),
        "from_description": _dedupe_link_list(description_urls),
        "from_research": _dedupe_link_list(links.get("from_research", [])),
    }

    resources = result.get("resources") or []
    if not isinstance(resources, list):
        resources = []
    for line in description_resources:
        if line.strip():
            resources.append({
                "name": line.strip(),
                "type": "other",
                "detail": "From video description",
                "url": None,
                "source": "description",
            })

    return {
        "summary": result.get("summary", ""),
        "guest_profile": result.get("guest_profile") or {},
        "resources": resources,
        "links": grouped,
        "insights": result.get("insights") or [],
        "duration_seconds": duration_seconds,
    }


def _dedupe_link_list(links: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for link in links:
        url = link.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(link)
    return out


# ── Main Processing ──────────────────────────────────────────────────────────

def _build_flat_key_points(result: dict) -> list[str]:
    key_points: list[str] = []
    for cluster in result.get("insights", []):
        prefix = "==" if cluster.get("is_agenda_item") else "--"
        key_points.append(f"{prefix} {cluster.get('topic', '')}")
        key_points.extend(cluster.get("points", []))
    return key_points


def process_video(
    video_id: str,
    title: str,
    *,
    playlist_type: str = db.PLAYLIST_GENERAL,
    playlist_id: str = "",
    user_agenda: str = "",
) -> dict:
    usage_tracker.begin_run(video_id, title)
    try:
        result = _process_video_inner(
            video_id,
            title,
            playlist_type=playlist_type,
            playlist_id=playlist_id,
            user_agenda=user_agenda,
        )
        usage = usage_tracker.finish_run()
        if usage:
            result["usage_data"] = usage
            usage_tracker.add_to_lifetime(usage)
        return result
    except Exception:
        usage_tracker.finish_run()
        raise


def _finalize_video_result(
    video_id: str,
    *,
    structured: dict,
    result: dict,
    source: str,
    research_data: dict,
    auto_agenda: str,
    channel_name: str,
) -> dict:
    return {
        "summary": structured.get("summary") or result.get("summary", ""),
        "key_points": _build_flat_key_points(result),
        "transcript_source": source,
        "research_data": research_data,
        "structured_insights": structured,
        "auto_agenda": auto_agenda,
        "channel_name": channel_name,
    }


def _process_video_inner(
    video_id: str,
    title: str,
    *,
    playlist_type: str = db.PLAYLIST_GENERAL,
    playlist_id: str = "",
    user_agenda: str = "",
) -> dict:
    tdata = fetch_transcript_data(video_id)
    transcript = tdata["text"]
    source = tdata["source"]
    timed_text = tdata.get("timed_text") or transcript
    duration_seconds = int(tdata.get("duration_seconds") or 0)

    if not transcript.strip():
        raise RuntimeError("Empty transcript")

    profile_prompt = db.get_profile_prompt(
        playlist_id=playlist_id if playlist_id else None
    )

    if playlist_type == db.PLAYLIST_PODCAST:
        from researcher import research_all
        from video_metadata import analyze_video_description

        desc_data = analyze_video_description(video_id)
        transcript_urls = _extract_urls_from_transcript(transcript)

        recon = _recon_pass(transcript, title)

        if user_agenda.strip():
            agenda = user_agenda.strip()
            auto_agenda = ""
        else:
            agenda = _generate_auto_agenda(recon, profile_prompt)
            auto_agenda = agenda

        entities = _extract_research_targets(transcript, title, recon)
        entity_context = _format_entity_context(entities)

        research_data = research_all(
            guest_name=recon.get("guest_name", "").strip(),
            topics=recon.get("main_topics", []),
            targets=entities.get("research_targets", []),
            description_urls=desc_data.get("urls", []),
            transcript_urls=transcript_urls,
            video_title=title,
        )
        research_data["channel_title"] = desc_data.get("channel_title", "")

        result = _holistic_extraction(
            transcript,
            title,
            recon=recon,
            agenda=agenda,
            profile_prompt=profile_prompt,
            research_summary=research_data.get("combined_summary", ""),
            entity_context=entity_context,
            description_context=desc_data.get("description", ""),
            timed_transcript=timed_text,
        )

        structured = _merge_structured_output(
            result,
            research_data=research_data,
            description_urls=desc_data.get("urls", []),
            transcript_urls=transcript_urls,
            description_resources=desc_data.get("resource_lines", []),
            duration_seconds=duration_seconds,
        )
        research_data["links"] = structured.get("links", research_data.get("links", {}))
        research_data["entities"] = entities

        return _finalize_video_result(
            video_id,
            structured=structured,
            result=result,
            source=source,
            research_data=research_data,
            auto_agenda=auto_agenda,
            channel_name=desc_data.get("channel_title", ""),
        )

    # === GENERAL: Holistic pipeline (no Tavily) ===
    from researcher import research_links_only
    from video_metadata import analyze_video_description

    desc_data = analyze_video_description(video_id)
    transcript_urls = _extract_urls_from_transcript(transcript)
    recon = _recon_pass(transcript, title)

    if user_agenda.strip():
        agenda = user_agenda.strip()
        auto_agenda = ""
    else:
        agenda = _generate_general_agenda(recon, profile_prompt)
        auto_agenda = agenda

    entities = _extract_research_targets(transcript, title, recon)
    entity_context = _format_entity_context(entities)

    research_data = research_links_only(
        description_urls=desc_data.get("urls", []),
        transcript_urls=transcript_urls,
        description_text=desc_data.get("description", ""),
        channel_title=desc_data.get("channel_title", ""),
    )

    result = _holistic_extraction(
        transcript,
        title,
        recon=recon,
        agenda=agenda,
        profile_prompt=profile_prompt,
        research_summary=research_data.get("combined_summary", ""),
        entity_context=entity_context,
        description_context=desc_data.get("description", ""),
        timed_transcript=timed_text,
    )

    structured = _merge_structured_output(
        result,
        research_data=research_data,
        description_urls=desc_data.get("urls", []),
        transcript_urls=transcript_urls,
        description_resources=desc_data.get("resource_lines", []),
        duration_seconds=duration_seconds,
    )
    research_data["links"] = structured.get("links", research_data.get("links", {}))
    research_data["entities"] = entities

    return _finalize_video_result(
        video_id,
        structured=structured,
        result=result,
        source=source,
        research_data=research_data,
        auto_agenda=auto_agenda,
        channel_name=desc_data.get("channel_title", ""),
    )


# ── Chat ─────────────────────────────────────────────────────────────────────

def chat_with_video(
    video_id: str,
    user_message: str,
    chat_history: list[dict] | None = None,
) -> str:
    """Chat about a video using full transcript context."""
    video = db.get_video(video_id)
    if not video:
        return "Video not found."

    transcript, _ = get_transcript(video_id)
    if not transcript.strip():
        return "No transcript available for this video."

    profile_prompt = db.get_profile_prompt()

    history_block = ""
    if chat_history:
        lines = []
        for msg in chat_history[-10:]:
            role = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"{role}: {msg['content']}")
        history_block = "\n\nPrevious conversation:\n" + "\n".join(lines)

    prompt = f"""{profile_prompt}

You are a helpful assistant answering questions about a specific video.
Video title: "{video.get('title', '')}"

Answer based ONLY on what's in the transcript. Be specific — quote or paraphrase exact parts.
If the transcript doesn't cover what they're asking, say so honestly.

Full transcript:
{transcript[:MAX_FULL_TRANSCRIPT_CHARS]}
{history_block}

User's question: {user_message}
"""
    return call_deep_llm(prompt, json_mode=False, operation="chat")
