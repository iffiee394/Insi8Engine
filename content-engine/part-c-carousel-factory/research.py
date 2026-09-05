"""
Part C, step 1 — research with citations.

Produces a claim set where every clinical statement carries a source URL. The
compliance gate refuses to render an uncited clinical claim, so this step is
load-bearing rather than decorative.

Search backend: Tavily (already keyed in the project .env). If Tavily is
unavailable the step degrades to knowledge-base-only mode, which produces
practice-position claims marked non-clinical and forces a human to attach
sources before rendering. It never silently invents a citation.
See DECISIONS.md D-05.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared import config, llm  # noqa: E402
from shared.config import ClientProfile  # noqa: E402

TRUSTED_DOMAINS = [
    "ada.org", "nidcr.nih.gov", "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov",
    "mouthhealthy.org", "cdc.gov", "nih.gov", "who.int", "cochrane.org",
    "aae.org", "perio.org", "aapd.org", "jada.ada.org", "nhs.uk",
]

RESEARCH_PROMPT = """You are researching a patient-education topic for a dental practice.

TOPIC: {topic}
ANGLE: {angle}

You have these search results. Use ONLY facts supported by them.

SEARCH RESULTS:
{sources}

PRACTICE KNOWLEDGE BASE (for positions and tone, not for external facts):
{kb}

Return JSON with this exact shape:
{{
  "summary": "3-4 sentence plain-English summary of what a patient needs to know",
  "claims": [
    {{"text": "one specific factual statement, plain English, under 25 words",
      "source_url": "the URL from the search results that supports it",
      "source_title": "the title of that source",
      "is_clinical": true}}
  ],
  "patient_fear": "the single fear or misconception this topic should defuse",
  "misconceptions": ["common wrong belief 1", "common wrong belief 2"]
}}

Rules:
- Produce 6 to 10 claims.
- Every claim with is_clinical=true MUST have a source_url copied verbatim from
  the search results. Never invent, guess, or shorten a URL.
- If you cannot support a statement from the search results, either omit it or
  set is_clinical=false and leave source_url empty.
- No superlatives, no guarantees, no comparative claims about providers.
- Write at an 8th grade reading level."""


def tavily_search(query: str, *, max_results: int = 8) -> list[dict[str, Any]]:
    if not config.TAVILY_API_KEY:
        return []
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=config.TAVILY_API_KEY)
        resp = client.search(
            query=query,
            search_depth="advanced",
            max_results=max_results,
            include_answer=False,
        )
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": (r.get("content", "") or "")[:1500],
            }
            for r in resp.get("results", [])
        ]
    except Exception as exc:  # noqa: BLE001
        print(f"  ! Tavily search failed: {exc}")
        return []


def gather_sources(topic: str) -> list[dict[str, Any]]:
    """Two passes: a general pass, then one biased toward authoritative domains."""
    results = tavily_search(f"{topic} dental patient information evidence")
    trusted_query = f"{topic} site:ada.org OR site:nidcr.nih.gov OR site:mouthhealthy.org"
    results += tavily_search(trusted_query, max_results=5)

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for r in results:
        u = r.get("url", "")
        if u and u not in seen:
            seen.add(u)
            deduped.append(r)

    def rank(r: dict[str, Any]) -> int:
        return 0 if any(d in r.get("url", "") for d in TRUSTED_DOMAINS) else 1

    return sorted(deduped, key=rank)


def research_topic(topic: str, angle: str, client: ClientProfile) -> dict[str, Any]:
    print(f"  > researching: {topic}")
    sources = gather_sources(topic)

    if not sources:
        print("  ! no search results; falling back to knowledge-base-only mode")
        return {
            "summary": "",
            "claims": [],
            "patient_fear": "",
            "misconceptions": [],
            "sources": [],
            "degraded": True,
            "note": "No search backend available. Attach sources manually before rendering.",
        }

    src_text = "\n\n".join(
        f"[{i}] {s['title']}\nURL: {s['url']}\n{s['content']}"
        for i, s in enumerate(sources[:10], start=1)
    )
    kb = client.knowledge_base[:6000]

    data = llm.ask_json(
        RESEARCH_PROMPT.format(topic=topic, angle=angle or "general patient education",
                               sources=src_text, kb=kb),
        prefer="claude",  # clinical claim extraction is the step worth the better model
    )

    # Reject any citation the model did not actually see. This is the guard
    # against fabricated sources, which is the main failure mode here.
    valid_urls = {s["url"] for s in sources}
    cleaned: list[dict[str, Any]] = []
    dropped = 0
    for c in data.get("claims", []) or []:
        url = (c.get("source_url") or "").strip()
        if c.get("is_clinical", True):
            if url not in valid_urls:
                dropped += 1
                c["source_url"] = ""
                c["is_clinical"] = False
                c["_note"] = "citation rejected: URL was not in the search results"
        cleaned.append(c)
    if dropped:
        print(f"  ! rejected {dropped} fabricated citation(s); those claims were demoted")

    data["claims"] = cleaned
    data["sources"] = sources[:10]
    data["degraded"] = False
    return data


if __name__ == "__main__":
    import json

    c = config.load_client(config.default_client())
    topic = sys.argv[1] if len(sys.argv) > 1 else "Is a root canal painful"
    print(json.dumps(research_topic(topic, "", c), indent=2)[:3000])
