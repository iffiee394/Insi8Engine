"""
Part C, step 2 — turn researched claims into a structured slide outline.

The outline is JSON, not prose, because the renderer, the compliance gate and
the archive all need to read the same object. Free-text "write me a carousel"
output cannot be gated or archived reliably.

Scripting target is SAVES and CAROUSEL COMPLETION, which is what the Feed
algorithm rewards - a different target from the Reels lane, which is scripted
for sends. See DECISIONS.md D-09.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared import llm  # noqa: E402
from shared.config import ClientProfile  # noqa: E402

TEMPLATES = {
    "explainer": "Sequential explanation of how something works or what to expect.",
    "myth": "Myth on one side, what is actually true on the other. Good for corrections.",
    "checklist": "Numbered signs, steps or questions the reader can act on.",
    "question": "Opens on the patient's own question, answers it across the slides.",
}

OUTLINE_PROMPT = """You are writing an Instagram carousel for a dental practice.

TOPIC: {topic}
ANGLE: {angle}
PATIENT FEAR TO DEFUSE: {fear}

RESEARCHED CLAIMS (these are the ONLY external facts you may state; copy
source_url verbatim onto any slide that uses one):
{claims}

PRACTICE VOICE:
{voice}

PRACTICE KNOWLEDGE BASE (positions, services, what the practice will not say):
{kb}

IDENTIFICATION BLOCK (must appear on the final slide exactly as given):
{identification}

Choose the layout template that fits the content:
{templates}

Return JSON with this exact shape:
{{
  "template": "explainer" | "myth" | "checklist" | "question",
  "topic": "{topic}",
  "title": "short internal name for this asset, kebab-case",
  "slides": [
    {{"role": "hook",
      "kicker": "2-4 word category label, uppercase",
      "headline": "the hook. under 12 words. creates a question the reader needs closed.",
      "body": "one supporting line, under 20 words",
      "claims": []}},

    {{"role": "body",
      "kicker": "optional short label or step number",
      "headline": "the single point of this slide, under 10 words",
      "body": "40-55 words. plain English. one idea only.",
      "claims": [{{"text": "the factual statement used here",
                   "source_url": "verbatim URL from the researched claims",
                   "source_title": "...", "is_clinical": true}}]}},

    {{"role": "cta",
      "kicker": "SAVE THIS",
      "headline": "what to do next, under 10 words",
      "body": "one or two lines. no pressure, no urgency, no offer.",
      "identification": "{identification}",
      "claims": []}}
  ],
  "caption": "120-200 words. Opens with the same tension as the hook, delivers a
              little extra the slides did not, ends with a genuine question that
              invites replies. No hashtag stuffing inside the text.",
  "hashtags": ["8-12 relevant tags, mixed local and topical"],
  "save_trigger": "one sentence naming WHY someone saves this post",
  "media": []
}}

HARD RULES:
- 7 to 10 slides total: exactly one hook, one cta, the rest body.
- Every slide that states an external fact MUST carry that claim with its
  source_url. If you cannot cite it, do not state it.
- NEVER write: superlatives ("best", "#1", "top rated"), guarantees, "painless",
  "pain free", "risk free", "100%", or anything comparing this practice to another.
- NEVER imply specialty status. This practice is a General Dentist.
- Do NOT mention prices, fees, discounts, offers, financing or "free" anything.
  That content goes through a separate approval path.
- Do not use patient photos or imply a typical result.
- 8th grade reading level. Short sentences.
- The hook must earn attention through substance, not shock or absurdity - the
  practice is bound by a "dignified manner" advertising rule."""


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "untitled"


def build_outline(
    topic: str,
    angle: str,
    research: dict[str, Any],
    client: ClientProfile,
) -> dict[str, Any]:
    claims_text = "\n".join(
        f"- {c.get('text','')}\n  source: {c.get('source_url','') or '(uncited - do not state as fact)'}"
        f"\n  title: {c.get('source_title','')}"
        for c in research.get("claims", []) or []
    ) or "(none - do not state any external facts)"

    voice = client.voice
    voice_text = (
        f"Persona: {voice.get('persona','')}\n"
        f"Reading level: {voice.get('reading_level','8th grade')}\n"
        f"Do: {'; '.join(voice.get('do', []))}\n"
        f"Avoid: {'; '.join(voice.get('avoid', []))}"
    )
    templates_text = "\n".join(f"  - {k}: {v}" for k, v in TEMPLATES.items())

    outline = llm.ask_json(
        OUTLINE_PROMPT.format(
            topic=topic,
            angle=angle or "general patient education",
            fear=research.get("patient_fear", ""),
            claims=claims_text,
            voice=voice_text,
            kb=client.knowledge_base[:5000],
            identification=client.identification_block,
            templates=templates_text,
        )
    )

    outline.setdefault("template", "explainer")
    if outline["template"] not in TEMPLATES:
        outline["template"] = "explainer"
    outline.setdefault("topic", topic)
    outline["title"] = slugify(outline.get("title") or topic)
    outline.setdefault("media", [])
    outline.setdefault("hashtags", [])
    outline["sources"] = research.get("sources", [])

    # Force the identification block onto the final slide rather than trusting
    # the model to reproduce it verbatim. This is a regulatory field, so it is
    # written by code, not generated. See DECISIONS.md D-08.
    slides = outline.get("slides") or []
    if slides:
        slides[-1]["identification"] = client.identification_block
        slides[-1]["role"] = "cta"
        if slides[0].get("role") != "hook":
            slides[0]["role"] = "hook"
    outline["slides"] = slides
    return outline


def flatten_claims(outline: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, slide in enumerate(outline.get("slides", []) or [], start=1):
        for c in slide.get("claims", []) or []:
            out.append({**c, "slide_no": i})
    return out
