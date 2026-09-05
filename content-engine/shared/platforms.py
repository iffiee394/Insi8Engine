"""
Per-platform tailoring.

Adopted from reference build 2, which produces a different caption per network
from one brand voice - Instagram gets a shorter, warmer caption with a handful
of hashtags, LinkedIn gets a longer narrative, TikTok gets almost nothing.

Kept OUT of the voice file on purpose (see voice.py and DECISIONS.md D-21):
voice answers "who is speaking", this file answers "what shape does this network
want". They change for different reasons and on different schedules.

The numbers here are format conventions, not API hard limits, except where noted.
Verify anything you depend on against current platform docs. See D-24.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import llm
from .config import ClientProfile


@dataclass
class PlatformSpec:
    key: str
    label: str
    caption_words: tuple[int, int]
    hashtags: tuple[int, int]
    hard_caption_limit: int          # platform-enforced character ceiling
    carousel_max: int
    video_seconds: tuple[int, int]
    first_line_chars: int            # visible before "more"
    notes: str
    guidance: str
    extras: dict[str, Any] = field(default_factory=dict)


SPECS: dict[str, PlatformSpec] = {
    "instagram": PlatformSpec(
        key="instagram", label="Instagram",
        caption_words=(90, 160), hashtags=(5, 10), hard_caption_limit=2200,
        carousel_max=20, video_seconds=(15, 90), first_line_chars=125,
        notes="Feed ranks carousels on saves and completion; Reels rank on sends and watch time.",
        guidance=(
            "Warm and direct. Open with the same tension as the hook so the first "
            "line earns the tap on 'more'. End on a real question that invites a "
            "reply. Hashtags go at the end, not sprinkled through the text."
        ),
    ),
    "facebook": PlatformSpec(
        key="facebook", label="Facebook",
        caption_words=(60, 120), hashtags=(0, 3), hard_caption_limit=63206,
        carousel_max=10, video_seconds=(15, 90), first_line_chars=250,
        notes="Skews older and more local; the practice's actual catchment.",
        guidance=(
            "Plainer and more local than Instagram. Name the town. Hashtags are "
            "close to useless here, so use almost none. A practical, neighbourly "
            "register works better than a punchy one."
        ),
    ),
    "tiktok": PlatformSpec(
        key="tiktok", label="TikTok",
        caption_words=(12, 30), hashtags=(3, 5), hard_caption_limit=2200,
        carousel_max=35, video_seconds=(15, 60), first_line_chars=100,
        notes="Caption is a label, not an essay. On-screen text carries the message.",
        guidance=(
            "Very short. The caption is a label for the video, not a summary of "
            "it. No paragraphs. The work happens in the first two seconds of the "
            "video and in the on-screen text."
        ),
    ),
    "linkedin": PlatformSpec(
        key="linkedin", label="LinkedIn",
        caption_words=(180, 320), hashtags=(3, 5), hard_caption_limit=3000,
        carousel_max=20, video_seconds=(30, 180), first_line_chars=210,
        notes="Only relevant for B2B or practice-owner audiences, not patients.",
        guidance=(
            "Longer, first person, one idea developed properly. Short paragraphs "
            "with line breaks. Ends on a lesson rather than a call to book."
        ),
    ),
}


def spec(platform: str) -> PlatformSpec:
    return SPECS.get(platform.lower(), SPECS["instagram"])


TAILOR_PROMPT = """Rewrite this caption for {label}.

SOURCE CAPTION:
{caption}

PLATFORM RULES:
- Length: {lo}-{hi} words (hard ceiling {hard} characters)
- Hashtags: {htlo}-{hthi}
- First {firstline} characters are visible before "more" - they must carry weight
- {guidance}
- Context: {notes}

VOICE:
{voice}

HARD RULES (unchanged across platforms):
- Never write: superlatives ("best", "#1", "top rated"), "painless", "pain free",
  "guaranteed", "100%", "risk free", or any comparison to another practice.
- Never imply specialty status. This is a General Dentist.
- Never mention prices, fees, discounts, offers, financing or anything "free".
- Never use an em dash.
- Do not invent any fact that is not in the source caption.

Return JSON: {{"caption": "...", "hashtags": ["..."], "first_line": "..."}}"""


def tailor_caption(
    caption: str,
    platform: str,
    client: ClientProfile,
    *,
    voice_text: str | None = None,
) -> dict[str, Any]:
    """Produce one platform's variant of a caption."""
    from . import voice as voice_mod

    s = spec(platform)
    result = llm.ask_json(
        TAILOR_PROMPT.format(
            label=s.label, caption=caption,
            lo=s.caption_words[0], hi=s.caption_words[1], hard=s.hard_caption_limit,
            htlo=s.hashtags[0], hthi=s.hashtags[1],
            firstline=s.first_line_chars, guidance=s.guidance, notes=s.notes,
            voice=(voice_text or voice_mod.load_voice(client))[:3000],
        )
    )
    text = (result.get("caption") or "").strip()
    if len(text) > s.hard_caption_limit:
        text = text[: s.hard_caption_limit - 1].rsplit(" ", 1)[0] + "…"
        result["_truncated"] = True
    result["caption"] = text
    result["platform"] = s.key
    result.setdefault("hashtags", [])
    result["hashtags"] = result["hashtags"][: s.hashtags[1]]
    return result


def tailor_all(
    caption: str, client: ClientProfile, platforms: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    targets = platforms or client.channels.get("publish_to", ["instagram"])
    out: dict[str, dict[str, Any]] = {}
    for p in targets:
        try:
            out[p] = tailor_caption(caption, p, client)
        except Exception as exc:  # noqa: BLE001
            out[p] = {"caption": caption, "hashtags": [], "platform": p,
                      "_error": str(exc)[:200]}
    return out


def validate(caption: str, platform: str) -> list[str]:
    """Cheap structural checks, no model call."""
    s = spec(platform)
    problems: list[str] = []
    if len(caption) > s.hard_caption_limit:
        problems.append(
            f"{s.label}: caption is {len(caption)} chars, ceiling is {s.hard_caption_limit}"
        )
    words = len(caption.split())
    if words > s.caption_words[1] * 1.5:
        problems.append(f"{s.label}: {words} words is well over the {s.caption_words[1]} target")
    if words < s.caption_words[0] * 0.5:
        problems.append(f"{s.label}: {words} words is well under the {s.caption_words[0]} target")
    return problems
