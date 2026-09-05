"""
Part E, step 8-9 — self-check, then review.

Reference video 1's pipeline ends "... render -> self-check -> review -> schedule",
and its own summary of the session is the reason this file is split in two:

    "Almost nothing that went wrong was a taste problem. It was mechanical.
     That should decide where you spend agents versus where you spend code."

So:
  self_check()  MECHANICAL. Pixel-level and structural faults that have a right
                answer: text overflowing the canvas, an unreadable contrast
                ratio, a blank render, a missing identification block. Free,
                deterministic, runs always.
  pick_cover()  TASTE. Which of the variants actually stops a scroll. Only this
                step gets a model, and only after the mechanical checks pass.

See DECISIONS.md D-28.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared import llm  # noqa: E402

# WCAG-ish floor for large display text over a scrim.
MIN_CONTRAST = 3.0


# ---------------------------------------------------------------- mechanical


def _luminance(rgb: tuple[int, int, int]) -> float:
    def chan(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (chan(x) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _region_mean(im, box: tuple[int, int, int, int]) -> tuple[int, int, int]:
    crop = im.crop(box).convert("RGB")
    px = list(crop.getdata())
    n = len(px) or 1
    return (sum(p[0] for p in px) // n, sum(p[1] for p in px) // n,
            sum(p[2] for p in px) // n)


def self_check(
    png_path: Path, *, position: str = "bottom", scrim: str = "dark"
) -> list[str]:
    """Mechanical faults in a rendered cover. Empty list means clean."""
    problems: list[str] = []
    try:
        from PIL import Image
    except ImportError:
        return ["Pillow not installed; cannot self-check the render"]

    if not png_path.exists():
        return [f"{png_path.name} was not produced"]

    with Image.open(png_path) as im:
        w, h = im.size
        if (w, h) != (1080, 1350):
            problems.append(f"{png_path.name}: {w}x{h}, expected 1080x1350")

        # A render that is one flat colour means the photo or CSS failed.
        small = im.convert("RGB").resize((32, 40))
        px = list(small.getdata())
        spread = max(max(p) - min(p) for p in px)
        distinct = len(set(px))
        if distinct < 8 or spread < 6:
            problems.append(f"{png_path.name}: render looks blank or flat")

        # Contrast where the text sits, against the text colour the scrim implies.
        if position == "top":
            box = (60, 80, w - 60, 420)
        elif position == "center":
            box = (60, h // 2 - 180, w - 60, h // 2 + 180)
        else:
            box = (60, h - 520, w - 60, h - 120)
        bg = _region_mean(im, box)
        fg = (255, 255, 255) if scrim == "dark" else (21, 32, 42)
        ratio = contrast_ratio(fg, bg)
        if ratio < MIN_CONTRAST:
            problems.append(
                f"{png_path.name}: text contrast {ratio:.1f}:1 in the {position} "
                f"band is below {MIN_CONTRAST}:1 — try the other scrim"
            )
    return problems


def check_text_fit(headline: str, subtext: str) -> list[str]:
    """Copy that will not fit the cover box no matter the type size."""
    problems: list[str] = []
    if len(headline) > 92:
        problems.append(f"cover headline is {len(headline)} chars; over ~92 it "
                        f"will not fit three lines legibly")
    if len(headline.split()) > 12:
        problems.append(f"cover headline is {len(headline.split())} words; "
                        f"4-10 stops a scroll, more does not")
    if len(subtext) > 130:
        problems.append(f"cover subtext is {len(subtext)} chars; keep it under ~130")
    if not headline.strip():
        problems.append("cover headline is empty")
    return problems


# ---------------------------------------------------------------- taste


PICK_PROMPT = """You are choosing which of these Instagram carousel covers is most
likely to stop someone scrolling. They are the same photo and the same words with
different treatments.

The covers are attached in this order: {names}

Judge on, in priority order:
1. Is the headline instantly readable at thumbnail size?
2. Does the text sit in a calm part of the photo rather than fighting it?
3. Does it look like a real practice made it, not a template?
4. Does the photo still read as a photo, rather than being buried by the scrim?

This is for a dental practice bound by a rule requiring advertising be presented
in a dignified manner, so reject anything that reads as gimmicky or shouty.

Return JSON:
{{"winner": "<one of: {names}>",
  "why": "one sentence",
  "runner_up": "<one of: {names}>",
  "fix": "the single most useful change you would make to the winner, or empty"}}"""


def pick_cover(variants: list[dict[str, Any]], *, log=print) -> dict[str, Any]:
    """Model picks the strongest variant by looking at the rendered PNGs."""
    with_png = [v for v in variants if v.get("png") and Path(v["png"]).exists()]
    if not with_png:
        return {"winner": "", "why": "no rendered variants", "fix": ""}
    if len(with_png) == 1:
        return {"winner": with_png[0]["name"], "why": "only variant rendered", "fix": ""}

    names = ", ".join(v["name"] for v in with_png)
    try:
        result = llm.ask_json_with_images(
            PICK_PROMPT.format(names=names), [v["png"] for v in with_png]
        )
    except Exception as exc:  # noqa: BLE001
        log(f"    ! vision review unavailable ({str(exc)[:90]}); "
            f"falling back to the first clean variant")
        return {"winner": with_png[0]["name"],
                "why": "fallback: vision review unavailable", "fix": ""}

    valid = {v["name"] for v in with_png}
    if result.get("winner") not in valid:
        result["winner"] = with_png[0]["name"]
        result["why"] = "fallback: model named an unknown variant"
    return result
