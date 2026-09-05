"""
Part E, steps 4-5 — pick a photo, then render cover variants.

Reference video 1 generates three cover options with a paid image model and
picks one by eye. This does the same thing with CSS over a real photograph:
free, deterministic, and it cannot invent a sixth finger or a misspelled word,
which is the failure mode of generated text-on-image.

The variants differ in the ways that actually change stop-rate — treatment,
where the text sits, and how hard the scrim works — not in decoration.
See DECISIONS.md D-25 and D-29.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared import browser, config  # noqa: E402
from shared.config import ClientProfile  # noqa: E402

import assets  # noqa: E402

HERE = Path(__file__).resolve().parent
TEMPLATE_DIR = HERE / "templates"

# Longer headlines need smaller type. Chosen so a 10-word headline still fits
# three lines inside the text box at 1080x1350.
def headline_size(text: str, base: int = 96) -> int:
    n = len(text or "")
    if n <= 26:
        return base + 8
    if n <= 40:
        return base
    if n <= 58:
        return base - 14
    if n <= 76:
        return base - 26
    return base - 34


# Three variants worth comparing. Each changes something that matters.
VARIANT_SPECS = [
    {"name": "editorial-bottom", "treatment": "editorial", "position": "bottom",
     "vignette": 0.40, "grain": 0.13},
    {"name": "editorial-top", "treatment": "editorial", "position": "top",
     "vignette": 0.34, "grain": 0.11},
    {"name": "band", "treatment": "band", "position": "bottom",
     "vignette": 0.30, "grain": 0.10},
]

GRADE_WARM = {"saturate": 1.08, "contrast": 1.06, "brightness": 1.02, "sepia": 0.12}
GRADE_NEUTRAL = {"saturate": 1.02, "contrast": 1.04, "brightness": 1.0, "sepia": 0.02}


def build_contexts(
    outline: dict[str, Any],
    client: ClientProfile,
    photo_choice: dict[str, Any],
    *,
    warm: bool = True,
) -> list[dict[str, Any]]:
    hook = (outline.get("slides") or [{}])[0]
    headline = hook.get("headline", "")
    photo = photo_choice["photo"]
    photo_path = assets.PHOTO_DIR / photo["file"]
    photo_uri = assets.as_data_uri(photo_path)

    contexts: list[dict[str, Any]] = []
    for spec in VARIANT_SPECS:
        position = spec["position"]
        # The picker's suggestion wins for the primary variant; the others exist
        # to give a real alternative to compare against.
        if spec["name"] == "editorial-bottom":
            position = photo_choice.get("text_position", "bottom")
        contexts.append({
            "variant": spec["name"],
            "treatment": spec["treatment"],
            "position": position,
            "scrim": photo_choice.get("scrim", "dark"),
            "vignette": spec["vignette"],
            "grain": spec["grain"],
            "grade": GRADE_WARM if warm else GRADE_NEUTRAL,
            "focal": photo.get("focal", "center"),
            "photo_uri": photo_uri,
            "kicker": hook.get("kicker", ""),
            "headline": headline,
            "subtext": hook.get("body", ""),
            "headline_size": headline_size(headline),
            "brand": client.brand,
            "client_name": client.name,
            "show_logo": True,
            "W": config.CANVAS_W,
            "H": config.CANVAS_H,
        })
    return contexts


def render_variants(
    outline: dict[str, Any],
    client: ClientProfile,
    photo_choice: dict[str, Any],
    out_dir: Path,
    *,
    png: bool = True,
    log=print,
) -> list[dict[str, Any]]:
    """Render each cover variant. Returns [{name, html, png}, ...]."""
    out_dir.mkdir(parents=True, exist_ok=True)
    contexts = build_contexts(outline, client, photo_choice)
    env = browser.jinja_env(TEMPLATE_DIR)
    tpl = env.get_template("cover.html.j2")

    results: list[dict[str, Any]] = []
    exe = browser.find_browser() if png else None
    for ctx in contexts:
        name = ctx["variant"]
        hp = out_dir / f"cover-{name}.html"
        hp.write_text(tpl.render(**ctx), encoding="utf-8")
        entry: dict[str, Any] = {"name": name, "html": str(hp),
                                 "treatment": ctx["treatment"],
                                 "position": ctx["position"], "scrim": ctx["scrim"]}
        if png:
            pp = hp.with_suffix(".png")
            browser.html_to_png(hp, pp, exe)
            entry["png"] = str(pp)
            log(f"    ok {pp.name}")
        results.append(entry)
    return results


def render_plates(
    outline: dict[str, Any],
    client: ClientProfile,
    out_dir: Path,
    *,
    png: bool = True,
    log=print,
) -> tuple[list[Path], list[Path]]:
    """Render the interior slides and the CTA as HTML plates."""
    slides = outline.get("slides", []) or []
    body_and_cta = slides[1:]          # slide 1 is the photographic cover
    total = len(slides)

    contexts = [{
        "slide": s,
        "index": i,
        "total": total,
        "brand": client.brand,
        "client_name": client.name,
        "identification": client.identification_block,
        "W": config.CANVAS_W,
        "H": config.CANVAS_H,
    } for i, s in enumerate(body_and_cta, start=2)]

    return browser.render_pages(
        TEMPLATE_DIR, "plate.html.j2", contexts, out_dir,
        stem="plate", png=png, log=log,
    )


def assemble(
    cover_png: Path, plate_pngs: list[Path], out_dir: Path, *, log=print
) -> list[Path]:
    """Copy the winning cover and the plates into final posting order."""
    import shutil

    final_dir = out_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    for old in final_dir.glob("slide-*"):
        old.unlink()

    ordered: list[Path] = []
    dst = final_dir / f"slide-01{cover_png.suffix}"
    shutil.copy2(cover_png, dst)
    ordered.append(dst)
    for i, p in enumerate(plate_pngs, start=2):
        d = final_dir / f"slide-{i:02d}{p.suffix}"
        shutil.copy2(p, d)
        ordered.append(d)
    log(f"    assembled {len(ordered)} slides into {final_dir.name}/")
    return ordered
