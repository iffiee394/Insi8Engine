"""
Part C, step 3 — render a slide outline to Instagram-ready PNGs.

Renderer: Jinja2 -> HTML -> headless Chrome/Edge --screenshot.

Why not Playwright, Bannerbear, Placid, Contentdrips or Orshot: Chrome is
already on the machine, costs nothing, has no per-image quota, no vendor
lock-in, and gives full CSS control including real webfonts. The trade is that
you own the templates - which you want anyway, because template fatigue is the
thing that kills carousel performance. See DECISIONS.md D-01 and D-10.

--virtual-time-budget is what makes this reliable: it tells headless Chrome to
fast-forward timers and pending network (webfonts) before capturing, instead of
screenshotting a half-loaded page.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from shared import config  # noqa: E402
from shared.config import ClientProfile  # noqa: E402

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
VIRTUAL_TIME_MS = 4000


class RenderError(RuntimeError):
    pass


def find_browser() -> str:
    for candidate in config.BROWSER_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in ("chrome", "chromium", "msedge", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise RenderError(
        "No Chrome/Edge found for rendering.\n"
        "Fallback: open the generated slide-XX.html files in any browser and use "
        "Print -> Save as PDF, or take a 1080x1350 screenshot. The HTML is the "
        "source of truth; the PNG step is just automation."
    )


def jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_html(
    outline: dict[str, Any],
    client: ClientProfile,
    out_dir: Path,
) -> list[Path]:
    """Write one HTML file per slide. Returns the paths in order."""
    out_dir.mkdir(parents=True, exist_ok=True)
    env = jinja_env()
    template_name = f"{outline.get('template', 'explainer')}.html.j2"
    if not (TEMPLATE_DIR / template_name).exists():
        template_name = "explainer.html.j2"
    tpl = env.get_template(template_name)

    slides = outline.get("slides", []) or []
    paths: list[Path] = []
    total = len(slides)
    for i, slide in enumerate(slides, start=1):
        html = tpl.render(
            slide=slide,
            index=i,
            total=total,
            brand=client.brand,
            client=client,
            identification=client.identification_block,
            outline=outline,
            W=config.CANVAS_W,
            H=config.CANVAS_H,
        )
        p = out_dir / f"slide-{i:02d}.html"
        p.write_text(html, encoding="utf-8")
        paths.append(p)
    return paths


def html_to_png(html_path: Path, png_path: Path, browser: str) -> Path:
    # as_uri() requires an absolute path, and callers legitimately pass relative
    # output directories.
    html_path = html_path.resolve()
    png_path = png_path.resolve()
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        "--force-device-scale-factor=1",
        f"--virtual-time-budget={VIRTUAL_TIME_MS}",
        f"--window-size={config.CANVAS_W},{config.CANVAS_H}",
        f"--screenshot={png_path}",
        html_path.as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not png_path.exists():
        raise RenderError(
            f"Chrome did not produce {png_path.name}.\n"
            f"stderr: {proc.stderr[-800:]}"
        )
    return png_path


def render_carousel(
    outline: dict[str, Any],
    client: ClientProfile,
    out_dir: Path,
    *,
    png: bool = True,
) -> dict[str, Any]:
    html_paths = render_html(outline, client, out_dir)
    png_paths: list[Path] = []

    if png:
        browser = find_browser()
        print(f"  > rendering {len(html_paths)} slides with {Path(browser).name}")
        for hp in html_paths:
            pp = hp.with_suffix(".png")
            html_to_png(hp, pp, browser)
            png_paths.append(pp)
            print(f"    ok {pp.name}")

    review = write_review_page(outline, client, out_dir, png_paths or html_paths)
    return {
        "html": [str(p) for p in html_paths],
        "png": [str(p) for p in png_paths],
        "review": str(review),
    }


REVIEW_TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>Review — {{ outline.title }}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.6 ui-sans-serif, system-ui, sans-serif; margin: 0;
         background: #10171d; color: #e4ebef; }}
  .wrap {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px 80px; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; }}
  .meta {{ color: #9aabb6; margin-bottom: 28px; font-size: 13px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px,1fr));
           gap: 18px; }}
  figure {{ margin: 0; background: #161f26; border: 1px solid #25323b; border-radius: 6px;
            overflow: hidden; }}
  figure img, figure iframe {{ width: 100%; display: block; border: 0; aspect-ratio: 4/5; }}
  figcaption {{ padding: 8px 10px; font-size: 12px; color: #9aabb6;
                font-family: ui-monospace, monospace; }}
  .panel {{ background: #161f26; border: 1px solid #25323b; border-radius: 6px;
            padding: 18px 20px; margin-bottom: 20px; }}
  .block {{ color: #dd8878; }} .warn {{ color: #e3b778; }} .ok {{ color: #77b792; }}
  pre {{ white-space: pre-wrap; font-size: 12.5px; margin: 0; }}
  a {{ color: #4fb0b6; }}
  h2 {{ font-size: 15px; margin: 0 0 10px; text-transform: uppercase;
        letter-spacing: .1em; color: #9aabb6; }}
</style>
<div class="wrap">
  <h1>{{ title }}</h1>
  <div class="meta">{{ template }} · {{ n }} slides · {{ client_name }}</div>

  <div class="panel">
    <h2>Compliance</h2>
    <pre class="{{ compliance_class }}">{{ compliance }}</pre>
  </div>

  <div class="panel">
    <h2>Caption</h2>
    <pre>{{ caption }}</pre>
    <p style="color:#9aabb6;font-size:12.5px">{{ hashtags }}</p>
  </div>

  <div class="panel">
    <h2>Sources cited</h2>
    <pre>{{ sources }}</pre>
  </div>

  <h2>Slides</h2>
  <div class="grid">
    {{ figures }}
  </div>
</div>
"""


def write_review_page(
    outline: dict[str, Any],
    client: ClientProfile,
    out_dir: Path,
    assets: list[Path],
) -> Path:
    figures = []
    for p in assets:
        if p.suffix == ".png":
            figures.append(f'<figure><img src="{p.name}" alt="{p.stem}">'
                           f'<figcaption>{p.name}</figcaption></figure>')
        else:
            figures.append(f'<figure><iframe src="{p.name}" scrolling="no"></iframe>'
                           f'<figcaption>{p.name}</figcaption></figure>')

    claims_lines = []
    for i, s in enumerate(outline.get("slides", []) or [], start=1):
        for c in s.get("claims", []) or []:
            url = c.get("source_url") or "(UNCITED)"
            claims_lines.append(f"slide {i}: {c.get('text','')}\n         {url}")

    compliance = outline.get("_compliance_report", "(not run)")
    cls = "ok"
    if "BLOCK" in compliance:
        cls = "block"
    elif "WARN" in compliance:
        cls = "warn"

    html = (
        REVIEW_TEMPLATE
        .replace("{{ outline.title }}", str(outline.get("title", "")))
        .replace("{{ title }}", str(outline.get("topic", outline.get("title", ""))))
        .replace("{{ template }}", str(outline.get("template", "")))
        .replace("{{ n }}", str(len(outline.get("slides", []) or [])))
        .replace("{{ client_name }}", client.name)
        .replace("{{ compliance_class }}", cls)
        .replace("{{ compliance }}", compliance)
        .replace("{{ caption }}", str(outline.get("caption", "")))
        .replace("{{ hashtags }}", " ".join(outline.get("hashtags", []) or []))
        .replace("{{ sources }}", "\n".join(claims_lines) or "(no cited claims)")
        .replace("{{ figures }}", "\n    ".join(figures))
    )
    p = out_dir / "review.html"
    p.write_text(html, encoding="utf-8")
    return p
