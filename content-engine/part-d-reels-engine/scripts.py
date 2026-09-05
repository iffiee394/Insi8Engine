"""
Part D, step 3 — structure extraction, then rewrite.

The whole design rests on one separation: we take the STRUCTURE of a video that
worked and throw away its CONTENT. Structure is not ownable and does not carry
the source's clinical claims; phrasing is, and does. Instagram also suppresses
accounts that lean on reposted material, so a close paraphrase loses twice -
legally and algorithmically. See DECISIONS.md D-15.

Two calls, deliberately separated:
  extract_structure()  reads the source, returns an abstract beat sheet with NO
                       verbatim phrasing and NO source claims.
  rewrite_to_client()  never sees the source transcript at all. It only sees the
                       beat sheet plus the client's own knowledge base.

That second call is the guardrail: the model cannot copy what it was not shown.

Scripting target is SENDS - the DM share - because that is the signal Instagram
weights most heavily for Reels. A different target from the carousel lane, which
is scripted for saves. See DECISIONS.md D-09.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared import llm  # noqa: E402
from shared.config import ClientProfile  # noqa: E402

STRUCTURE_PROMPT = """Analyse why this short video held attention. You are extracting
STRUCTURE ONLY.

TRANSCRIPT:
---
{transcript}
---

CONTEXT: {views:,} views against this account's median of {baseline:,} ({multiple}x).

Return JSON:
{{
  "beats": [
    {{"name": "hook" | "tension" | "evidence" | "turn" | "payoff" | "cta",
      "seconds": 0.0,
      "function": "what this beat DOES for the viewer, described abstractly",
      "device": "the technique used, e.g. 'names a fear the viewer has not admitted'"}}
  ],
  "hook_mechanism": "the abstract reason the first 2 seconds worked",
  "retention_device": "what makes someone stay past 5 seconds",
  "share_trigger": "why a viewer would send this to a specific person in their life",
  "format": "short label, e.g. 'direct-to-camera explainer', 'myth correction'",
  "target_seconds": 45,
  "transferable": true,
  "why_not_transferable": ""
}}

CRITICAL RULES:
- Do NOT quote or closely paraphrase any sentence from the transcript.
- Do NOT carry over any factual or medical claim from the source. None.
- Describe FUNCTION and DEVICE only, never wording.
- If the video worked mainly because of the creator's face, fame, a trend audio,
  a stunt, or anything a licensed medical practice could not dignifiedly repeat,
  set transferable=false and explain in why_not_transferable."""


REWRITE_PROMPT = """Write a short-form video script for a dental practice.

You are given a proven STRUCTURE. You have never seen the original video and you
must not try to reconstruct it. Fill this structure entirely from the practice's
own knowledge base below.

STRUCTURE TO FOLLOW:
{structure}

TOPIC THIS SCRIPT SHOULD COVER:
{topic}

PRACTICE KNOWLEDGE BASE (the ONLY source of substance):
{kb}

PRACTICE VOICE:
{voice}

Return JSON:
{{
  "title": "kebab-case internal name",
  "format": "short label matching the structure's format",
  "hook": "the first line, spoken. under 14 words. must work with sound off too.",
  "lines": ["spoken line 1", "spoken line 2", "..."],
  "cta": "closing line. an invitation, never pressure.",
  "caption": "80-150 words for the post. ends with a real question.",
  "hashtags": ["6-10 tags"],
  "target_seconds": 45,
  "setup": "operatory chair" | "reception desk" | "consult room" | "outside signage",
  "b_roll": ["shot the editor should cut to, and roughly when"],
  "on_screen_text": ["short text overlay 1", "..."],
  "share_trigger": "the specific person a viewer would send this to, and why",
  "claims": [{{"text": "any factual statement made", "source_url": "", "is_clinical": true}}],
  "media": []
}}

HARD RULES:
- Total spoken words must fit target_seconds at roughly 2.6 words per second.
- The hook must earn attention with substance. This practice is bound by a
  "dignified manner" advertising rule: no absurdity, no shock, no stunts, no
  trend-audio skits, no pranks.
- NEVER write: "painless", "pain free", "guaranteed", "100%", "best", "#1",
  "top rated", "risk free", or any comparison to another practice.
- NEVER imply specialty status. This is a General Dentist.
- Do NOT mention prices, fees, discounts, offers, financing, or anything "free".
- Any factual claim goes in "claims" so it can be sourced and signed off. If you
  are not certain it is supportable, do not say it.
- Write how a person actually speaks out loud: contractions, short sentences.
- 8th grade reading level."""


def _clean_transcript(text: str, limit: int = 6000) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t[:limit]


def extract_structure(
    transcript: str, *, views: int = 0, baseline: int = 0, multiple: float = 0.0
) -> dict[str, Any]:
    return llm.ask_json(
        STRUCTURE_PROMPT.format(
            transcript=_clean_transcript(transcript),
            views=int(views or 0),
            baseline=int(baseline or 0),
            multiple=multiple or 0.0,
        )
    )


def rewrite_to_client(
    structure: dict[str, Any], topic: str, client: ClientProfile
) -> dict[str, Any]:
    """Note: the source transcript is deliberately NOT passed into this call."""
    import json

    voice = client.voice
    voice_text = (
        f"Persona: {voice.get('persona','')}\n"
        f"Reading level: {voice.get('reading_level','8th grade')}\n"
        f"Do: {'; '.join(voice.get('do', []))}\n"
        f"Avoid: {'; '.join(voice.get('avoid', []))}"
    )
    # Strip anything that could smuggle source phrasing through.
    safe_structure = {
        "beats": structure.get("beats", []),
        "hook_mechanism": structure.get("hook_mechanism", ""),
        "retention_device": structure.get("retention_device", ""),
        "share_trigger": structure.get("share_trigger", ""),
        "format": structure.get("format", ""),
        "target_seconds": structure.get("target_seconds", 45),
    }

    script = llm.ask_json(
        REWRITE_PROMPT.format(
            structure=json.dumps(safe_structure, indent=2),
            topic=topic,
            kb=client.knowledge_base[:7000],
            voice=voice_text,
        )
    )
    script.setdefault("media", [])
    script.setdefault("claims", [])
    script.setdefault("target_seconds", safe_structure.get("target_seconds", 45))

    # Models reliably repeat the hook as lines[0] and the CTA as lines[-1].
    # Left in, the duration estimate inflates and the talent reads it twice.
    def _norm(t: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()

    hook_n, cta_n = _norm(script.get("hook", "")), _norm(script.get("cta", ""))
    script["lines"] = [
        l for l in (script.get("lines") or [])
        if _norm(str(l)) not in {hook_n, cta_n} and _norm(str(l))
    ]
    script["title"] = re.sub(r"[^a-z0-9]+", "-", (script.get("title") or topic).lower()).strip("-")[:60]
    return script


def estimate_seconds(script: dict[str, Any]) -> float:
    words = len((script.get("hook", "") + " " +
                 " ".join(script.get("lines", []) or []) + " " +
                 script.get("cta", "")).split())
    return round(words / 2.6, 1)


def similarity_guard(script: dict[str, Any], transcript: str, *, threshold: int = 7) -> list[str]:
    """Flag any run of `threshold`+ consecutive words shared with the source.

    Cheap n-gram overlap check. The rewrite call never sees the transcript, so
    this should always come back empty - it exists to prove that, and to catch
    the case where someone wires the transcript in by accident.
    """
    def norm(t: str) -> list[str]:
        return re.sub(r"[^a-z0-9 ]", " ", (t or "").lower()).split()

    src = norm(transcript)
    new = norm(
        script.get("hook", "") + " " + " ".join(script.get("lines", []) or [])
        + " " + script.get("cta", "") + " " + script.get("caption", "")
    )
    if len(src) < threshold or len(new) < threshold:
        return []
    src_ngrams = {tuple(src[i:i + threshold]) for i in range(len(src) - threshold + 1)}
    hits = []
    for i in range(len(new) - threshold + 1):
        gram = tuple(new[i:i + threshold])
        if gram in src_ngrams:
            hits.append(" ".join(gram))
    return sorted(set(hits))
