"""External research via Tavily search + Groq LLM synthesis."""

from __future__ import annotations

import json
import re

from groq import Groq

import config
import usage_tracker
from logutil import get_logger

logger = get_logger(__name__)

SUMMARY_MODEL = config.GROQ_CHAT_MODEL
MAX_RESEARCH_TARGETS = config.MAX_RESEARCH_TARGETS


def _tavily_search(query: str, max_results: int = 5, *, operation: str = "search") -> list[dict]:
    if not config.TAVILY_API_KEY:
        return []
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=config.TAVILY_API_KEY)
        response = client.search(query, max_results=max_results, search_depth="advanced")
        usage_tracker.record_tavily(query, operation=operation)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            }
            for r in response.get("results", [])
        ]
    except Exception:
        return []


def _collect_search_results(
    queries: list[str],
    max_per_query: int = 3,
    *,
    operation: str = "search",
) -> tuple[str, list[dict]]:
    all_results = []
    for q in queries:
        all_results.extend(_tavily_search(q, max_results=max_per_query, operation=operation))

    if not all_results:
        return "", []

    seen_urls: set[str] = set()
    unique = []
    for r in all_results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(r)

    chunks = []
    for i, r in enumerate(unique[:15], 1):
        chunks.append(f"[{i}] {r['title']}\n{r['url']}\n{r['content'][:500]}")
    sources = [{"title": r["title"], "url": r["url"]} for r in unique[:12] if r.get("url")]
    return "\n\n".join(chunks), sources


def _call_groq_json(prompt: str) -> dict:
    from llm import call_deep_llm

    api_key = config.GROQ_API_KEY
    raw = ""
    if api_key:
        try:
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model=SUMMARY_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            raw = (response.choices[0].message.content or "").strip()
            usage_tracker.record_groq(
                model=SUMMARY_MODEL,
                operation="research_synthesis",
                prompt=prompt,
                response=raw,
            )
        except Exception as exc:
            logger.warning("[research] Groq failed (%s) — using deep LLM fallback", str(exc)[:100])
            raw = call_deep_llm(prompt, json_mode=True, operation="research_synthesis")
    else:
        raw = call_deep_llm(prompt, json_mode=True, operation="research_synthesis")

    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _research_person(name: str, video_context: str = "") -> dict:
    if not name:
        return {}
    disambiguator = f' "{video_context}"' if video_context else ""
    search_text, sources = _collect_search_results([
        f'"{name}"{disambiguator}',
        f'"{name}" viral OR trending OR famous for',
        f'"{name}" site:reddit.com',
        f'"{name}" interview highlights OR controversial OR hot take',
    ], operation="guest")
    if not search_text:
        return {"name": name}

    context_line = (
        f'This person appears in a video about: "{video_context}". '
        "Only use search results that plausibly describe this same person in that "
        "context — a shared first/last name is not enough.\n\n"
        if video_context
        else ""
    )
    result = _call_groq_json(f"""Based on these web search results, create a research brief about "{name}".

{context_line}Search results:
{search_text}

Return ONLY valid JSON:
{{
    "bio": "1-2 sentence bio of who this person is and why they matter",
    "viral_things": ["most notable/viral thing 1", "thing 2"],
    "discussions": ["what people debate about them 1", "topic 2"],
    "summary": "2-3 sentence essential context about this person",
    "match_confidence": "confirmed" or "uncertain" or "no_match"
}}

Up to 5 items each. Only include things supported by search results — do not invent.
If the search results are clearly about a different, more famous person who happens to
share the name (e.g. a celebrity or brand unrelated to the video's context), set
match_confidence to "no_match" and leave bio/viral_things/discussions/summary empty.""")
    if result.get("match_confidence") == "no_match":
        return {"name": name}
    result["name"] = name
    result["sources"] = sources
    return result


def _research_topics(topics: list[str]) -> list[dict]:
    if not topics:
        return []
    researched = []
    for topic in topics[:3]:
        if len(topic) < 4:
            continue
        search_text, sources = _collect_search_results([
            f'"{topic}" explained OR guide OR overview',
            f'"{topic}" viral OR trending OR most important',
            f'"{topic}" site:reddit.com discussion',
        ], max_per_query=2, operation="topic")
        if not search_text:
            continue

        result = _call_groq_json(f"""Based on these web search results about the topic "{topic}", create a brief.

Search results:
{search_text}

Return ONLY valid JSON:
{{
    "topic": "{topic}",
    "what_it_is": "1 sentence explanation if it's a technology/concept/tool",
    "notable": ["most important/viral thing about this topic 1", "thing 2"],
    "hot_takes": ["what people commonly debate or say about it 1", "take 2"],
    "summary": "1-2 sentence context that would help someone understand a podcast discussion about this"
}}

Up to 3 items each. Only include things supported by search results.""")
        result["topic"] = topic
        result["sources"] = sources
        researched.append(result)
    return researched


def research_targets(targets: list[dict], *, max_targets: int | None = None) -> list[dict]:
    """Run targeted Tavily searches for entity extraction targets."""
    cap = max_targets if max_targets is not None else MAX_RESEARCH_TARGETS
    results: list[dict] = []
    for target in targets[:cap]:
        query = (target.get("query") or target.get("name") or "").strip()
        if not query:
            continue
        context = (target.get("transcript_context") or "")[:300]
        search_text, sources = _collect_search_results([query], max_per_query=4, operation="entity")
        if not search_text:
            results.append({
                "target": query,
                "type": target.get("type", "unknown"),
                "status": "not_found",
                "summary": "",
                "matches": [],
            })
            continue

        parsed = _call_groq_json(f"""Based on web search results, answer this research target from a podcast.

Target query: {query}
Type: {target.get("type", "unknown")}
Transcript context: {context}

Search results:
{search_text}

Return ONLY valid JSON:
{{
    "status": "confirmed" or "likely_match" or "not_found",
    "summary": "1-3 sentences — who/what was found, be specific with names",
    "matches": [
        {{
            "title": "article/page title",
            "url": "https://...",
            "snippet": "relevant excerpt",
            "confidence": "confirmed" or "likely"
        }}
    ]
}}

Rules:
- confirmed = name/details clearly match transcript context
- likely = plausible match from partial description
- not_found = nothing useful
- Include up to 3 matches with real URLs from the search results""")
        matches = parsed.get("matches") or []
        if not matches and sources:
            matches = [
                {
                    "title": s.get("title", ""),
                    "url": s.get("url", ""),
                    "snippet": "",
                    "confidence": "likely",
                }
                for s in sources[:3]
            ]
        results.append({
            "target": query,
            "type": target.get("type", "unknown"),
            "status": parsed.get("status", "likely_match" if matches else "not_found"),
            "summary": parsed.get("summary", ""),
            "matches": matches,
            "sources": sources,
        })
    return results


def _dedupe_links(links: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for link in links:
        url = link.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(link)
    return out


def _merge_grouped_links(
    *,
    from_video: list[dict] | None = None,
    from_description: list[dict] | None = None,
    from_research: list[dict] | None = None,
) -> dict:
    return {
        "from_video": _dedupe_links(from_video or []),
        "from_description": _dedupe_links(from_description or []),
        "from_research": _dedupe_links(from_research or []),
    }


def research_all(
    *,
    guest_name: str = "",
    topics: list[str] | None = None,
    targets: list[dict] | None = None,
    description_urls: list[dict] | None = None,
    transcript_urls: list[dict] | None = None,
    video_title: str = "",
) -> dict:
    """
    Full research pass: guest, topics, entity targets.
    Returns guest, topics, targeted, combined_summary, links (grouped).
    """
    api_key = config.TAVILY_API_KEY
    guest_data: dict = {}
    topics_data: list[dict] = []
    targeted_data: list[dict] = []

    if api_key:
        guest_data = _research_person(guest_name, video_title) if guest_name else {}
        topics_data = _research_topics(topics or [])
        targeted_data = research_targets(targets or [])

    parts = []
    if guest_data.get("summary"):
        parts.append(f"GUEST — {guest_name}: {guest_data['summary']}")
    for td in topics_data:
        if td.get("summary"):
            parts.append(f"TOPIC — {td.get('topic', '')}: {td['summary']}")
    for tr in targeted_data:
        if tr.get("summary"):
            parts.append(f"TARGET — {tr.get('target', '')}: {tr['summary']}")

    from_research: list[dict] = []
    for block in [guest_data] + topics_data:
        for src in block.get("sources", []):
            from_research.append({
                "title": src.get("title", ""),
                "url": src.get("url", ""),
                "context": "Web research",
                "confidence": "confirmed",
            })
    for tr in targeted_data:
        for match in tr.get("matches", []):
            from_research.append({
                "title": match.get("title") or tr.get("target", "Research"),
                "url": match.get("url", ""),
                "context": tr.get("summary", "")[:200],
                "confidence": match.get("confidence", "likely"),
            })

    grouped = _merge_grouped_links(
        from_video=transcript_urls or [],
        from_description=description_urls or [],
        from_research=from_research,
    )

    return {
        "guest": guest_data,
        "topics": topics_data,
        "targeted": targeted_data,
        "combined_summary": "\n".join(parts),
        "links": grouped,
    }


def research_guest_and_topics(*, guest_name: str = "", topics: list[str] | None = None) -> dict:
    """Backward-compatible wrapper."""
    return research_all(guest_name=guest_name, topics=topics)


def research_links_only(
    *,
    description_urls: list[dict] | None = None,
    transcript_urls: list[dict] | None = None,
    description_text: str = "",
    channel_title: str = "",
) -> dict:
    """
    Free research pass for General playlist videos — no Tavily.
    Uses description text + parsed URLs only.
    """
    grouped = _merge_grouped_links(
        from_video=transcript_urls or [],
        from_description=description_urls or [],
        from_research=[],
    )
    parts = []
    if channel_title:
        parts.append(f"CHANNEL: {channel_title}")
    if description_text.strip():
        parts.append(f"VIDEO DESCRIPTION:\n{description_text[:6000]}")
    return {
        "guest": {},
        "topics": [],
        "targeted": [],
        "combined_summary": "\n\n".join(parts),
        "description_excerpt": description_text[:4000],
        "channel_title": channel_title,
        "links": grouped,
        "tavily_used": False,
    }
