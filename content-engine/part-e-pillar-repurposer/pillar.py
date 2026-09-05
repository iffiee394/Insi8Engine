"""
Part E, step 1-2 — pillar content in, slide concept out.

This is the input path reference video 1 is built around: take one long thing
you already made (a YouTube video, a recorded consultation FAQ, a blog post, a
talk) and cut it into a carousel. Its advantage over Part C's topic-and-research
path is that the substance is ALREADY YOURS, so there is nothing to fact-check
against an external source and nothing to attribute.

Accepts:
  - a YouTube URL          -> transcript via shared.transcribe
  - a local .txt / .md     -> read directly
  - a local audio/video    -> Groq Whisper

Produces a slide concept: beats per slide, the same shape Part C's outline step
produces, so everything downstream (compliance gate, render, export, archive) is
unchanged. See DECISIONS.md D-26.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared import llm, transcribe  # noqa: E402
from shared.config import ClientProfile  # noqa: E402

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".vtt", ".srt"}
MEDIA_SUFFIXES = {".mp4", ".mov", ".m4a", ".mp3", ".wav", ".webm", ".mkv"}

CONCEPT_PROMPT = """You are cutting one long piece of content into an Instagram
carousel for a dental practice.

THE PILLAR CONTENT (a transcript of something the practice already published —
this is the ONLY source of substance, and all of it is already theirs):
---
{transcript}
---

PRACTICE VOICE:
{voice}

PRACTICE KNOWLEDGE BASE (for services, positions, and what they will not say):
{kb}

IDENTIFICATION BLOCK (goes on the final slide, written by code — do not edit it):
{identification}

Return JSON:
{{
  "title": "kebab-case internal name",
  "angle": "the single idea this carousel delivers, in one sentence",
  "pillar_summary": "3 sentences on what the source covered",
  "cover": {{
    "kicker": "2-4 word label, MAXIMUM 26 characters, e.g. 'PATIENT GUIDE'",
    "headline": "the scroll-stopping line. 4-10 words. goes over a photo.",
    "subtext": "one supporting line, under 12 words",
    "photo_brief": "what the photo behind this text should show, so the right one is picked"
  }},
  "slides": [
    {{"role": "body",
      "kicker": "2-4 word label, uppercase",
      "headline": "the single point of this slide, under 10 words",
      "body": "40-55 words, plain English, one idea only",
      "quote": "a short line the speaker ACTUALLY said in the transcript, or empty",
      "claims": [{{"text": "any factual statement made",
                   "source_type": "practice_fact" | "clinical_general",
                   "source_url": "", "is_clinical": true}}]}}
  ],
  "cta": {{
    "kicker": "SAVE THIS",
    "headline": "what to do next, under 10 words",
    "body": "one or two lines. no pressure, no offer, no urgency."
  }},
  "caption": "120-200 words. Opens with the same tension as the cover, adds
              something the slides did not, ends on a real question.",
  "hashtags": ["8-12 tags, mixed local and topical"],
  "save_trigger": "one sentence naming WHY someone saves this"
}}

HARD RULES:
- 4 to 8 body slides. The cover and CTA are separate fields, not slides.
- "angle" is the IDEA the carousel delivers, phrased as the practice would say
  it. Never describe the carousel itself ("this carousel explains...").
- EVERYTHING must come from the transcript. The knowledge base is for voice,
  service names and prohibitions ONLY — do not lift facts or clinical positions
  out of it. If it is not in the transcript, it does not go on a slide.
- "quote" must be a real phrase from the transcript or an empty string. Never
  invent a quote.
- Classify every claim in "claims":
    "practice_fact"     a statement about how THIS practice works, said by the
                        speaker in the transcript ("we hold emergency slots every
                        weekday morning"). Leave source_url empty. Most claims
                        here should be this.
    "clinical_general"  a statement about dentistry as a field, true regardless
                        of who says it ("molars have more canals than front
                        teeth"). These need an external source, and you do not
                        have one, so PREFER TO CUT THEM. Only include one if the
                        transcript itself is clearly the practice describing its
                        own experience rather than asserting a general fact.
- NEVER write: superlatives ("best", "#1", "top rated"), "painless", "pain free",
  "guaranteed", "100%", "risk free", or comparisons to another practice.
- NEVER promise how treatment will feel ("you won't feel", "you'll be comfortable").
- NEVER imply specialty status. This is a General Dentist.
- Do NOT mention prices, fees, discounts, offers, financing or anything "free".
- Never use an em dash. 8th grade reading level."""


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "pillar"


def clamp_words(text: str, limit: int) -> str:
    """Trim to `limit` characters on a word boundary. Never cuts mid-word."""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0].strip()
    return cut or t[:limit].strip()


class OwnershipError(RuntimeError):
    """Raised when a pillar source has not been confirmed as the client's own."""


def is_remote(source: str) -> bool:
    return source.strip().lower().startswith(("http://", "https://"))


def assert_ownership(source: str, *, confirmed: bool) -> None:
    """Refuse to repurpose a remote source that has not been claimed as the
    client's own.

    The pillar lane rewrites a transcript into the practice's voice AND lifts
    verbatim pull-quotes from it. That is exactly right for the practice's own
    recorded material and exactly wrong for anyone else's: it puts another
    creator's phrasing and unverified clinical claims into your client's mouth,
    and it is the near-duplicate pattern Instagram demotes.

    Third-party content is not useless — it just belongs in Part D, which
    extracts abstract STRUCTURE and never lets the model see the source when it
    writes. See DECISIONS.md D-32.
    """
    if not is_remote(source) or confirmed:
        return
    raise OwnershipError(
        f"Refusing to repurpose {source}\n\n"
        "  The pillar lane assumes the source is the CLIENT'S OWN content. It\n"
        "  rewrites the transcript in their voice and pulls verbatim quotes out\n"
        "  of it. Doing that to someone else's video attributes their words and\n"
        "  their clinical claims to your client.\n\n"
        "  If this really is the client's own video, re-run with --own-content.\n\n"
        "  If it is someone else's, use Part D instead:\n"
        "      cd ../part-d-reels-engine\n"
        "      python run.py mine   # then: script\n"
        "  Part D extracts the abstract structure only, and the rewrite step\n"
        "  never sees the source transcript at all."
    )


def load_pillar(source: str) -> dict[str, Any]:
    """Resolve a URL or local path into {'text', 'origin', 'source'}."""
    p = Path(source)

    if p.exists() and p.suffix.lower() in TEXT_SUFFIXES:
        raw = p.read_text(encoding="utf-8", errors="replace")
        # Strip SRT/VTT timing lines so the model sees prose.
        raw = re.sub(r"^\d+$", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"^[\d:,.\->\s]+$", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"^WEBVTT.*$", "", raw, flags=re.MULTILINE)
        return {"text": re.sub(r"\n{2,}", "\n", raw).strip(),
                "origin": str(p), "source": "file"}

    if p.exists() and p.suffix.lower() in MEDIA_SUFFIXES:
        result = llm.transcribe_audio(str(p))
        return {"text": result["text"], "origin": str(p), "source": "whisper"}

    if source.startswith("http"):
        result = transcribe.transcribe(source)
        if result is None:
            raise RuntimeError(
                f"No transcript available for {source}. If the video has captions "
                f"disabled, download the audio and pass the local file instead."
            )
        return {"text": result["text"], "origin": source, "source": result["source"]}

    raise FileNotFoundError(
        f"Could not read pillar source {source!r}. Pass a YouTube URL, a .txt/.md "
        f"file, or a local audio/video file."
    )


def build_concept(
    pillar_text: str, client: ClientProfile, *, voice_text: str = ""
) -> dict[str, Any]:
    from shared import voice as voice_mod

    concept = llm.ask_json(
        CONCEPT_PROMPT.format(
            transcript=re.sub(r"\s+", " ", pillar_text)[:14000],
            voice=(voice_text or voice_mod.load_voice(client))[:3000],
            kb=client.knowledge_base[:5000],
            identification=client.identification_block,
        )
    )
    concept["title"] = slugify(concept.get("title") or "pillar-carousel")
    concept.setdefault("slides", [])
    concept.setdefault("hashtags", [])
    concept.setdefault("cover", {})
    concept.setdefault("cta", {})
    return concept


REVISE_PROMPT = """The carousel below failed a compliance gate for a dental
practice in New Jersey. Fix it.

THE COMPLIANCE REPORT:
{report}

THE CURRENT CAROUSEL (JSON):
{outline}

Return the COMPLETE corrected carousel in exactly the same JSON shape. Change
only what is needed to clear every BLOCK. Rules for fixing:

- "general clinical claim has no source": you have no source, so CUT the claim
  and rewrite the slide around what the practice said about ITSELF instead. Do
  not invent a citation. Do not relabel a general fact as a practice_fact.
- "pricing_content": remove every mention of fees, costs, discounts, offers,
  financing or anything "free", including in the caption. Talk about the process
  rather than the price.
- "comfort_promise": never promise how treatment will feel. Say what is done,
  not how it will land.
- "banned_phrase" / "competence_testimonial": remove the superlative or claim.
- Keep the voice, the structure and the slide count. Do not rewrite slides that
  were not flagged.
- Never use an em dash."""


def revise_outline(
    outline: dict[str, Any], report: str, client: ClientProfile
) -> dict[str, Any]:
    """One repair pass over an outline the compliance gate rejected."""
    import json as _json

    payload = {k: v for k, v in outline.items() if not k.startswith("_")}
    fixed = llm.ask_json(
        REVISE_PROMPT.format(report=report, outline=_json.dumps(payload, indent=2)),
        prefer="claude",  # the repair is the step where being careless costs most
    )
    # Regulatory fields are written by code, never by the model.
    slides = fixed.get("slides") or outline.get("slides", [])
    if slides:
        slides[0]["role"] = "hook"
        slides[-1]["role"] = "cta"
        slides[-1]["identification"] = client.identification_block
    fixed["slides"] = slides
    fixed.setdefault("template", "pillar")
    fixed["title"] = outline.get("title", "pillar")
    fixed["_pillar"] = outline.get("_pillar", {})
    return fixed


def to_outline(concept: dict[str, Any], client: ClientProfile) -> dict[str, Any]:
    """Convert a pillar concept into the outline shape the shared gate expects.

    Keeping one outline schema means Part E reuses Part C's compliance gate,
    archive and export untouched.
    """
    cover = concept.get("cover", {}) or {}
    cta = concept.get("cta", {}) or {}

    slides: list[dict[str, Any]] = [{
        "role": "hook",
        # The kicker is one line of small caps on the cover. Truncating an
        # arbitrary sentence to fit it produces clipped words on the rendered
        # image, so clamp on a word boundary and fall back to a fixed label
        # rather than to a chopped-up angle.
        "kicker": clamp_words(cover.get("kicker", ""), 26) or "PATIENT GUIDE",
        "headline": cover.get("headline", ""),
        "body": cover.get("subtext", ""),
        "claims": [],
    }]
    for s in concept.get("slides", []) or []:
        slides.append({
            "role": "body",
            "kicker": s.get("kicker", ""),
            "headline": s.get("headline", ""),
            "body": s.get("body", ""),
            "quote": s.get("quote", ""),
            "claims": s.get("claims", []) or [],
        })
    slides.append({
        "role": "cta",
        "kicker": cta.get("kicker", "SAVE THIS"),
        "headline": cta.get("headline", ""),
        "body": cta.get("body", ""),
        # Regulatory field: written by code, never by the model. See D-08.
        "identification": client.identification_block,
        "claims": [],
    })

    return {
        "template": "pillar",
        "topic": concept.get("angle", ""),
        "title": concept["title"],
        "slides": slides,
        "caption": concept.get("caption", ""),
        "hashtags": concept.get("hashtags", []),
        "save_trigger": concept.get("save_trigger", ""),
        "media": [],
        "sources": [],
        "_pillar": {
            "summary": concept.get("pillar_summary", ""),
            "photo_brief": cover.get("photo_brief", ""),
        },
    }
