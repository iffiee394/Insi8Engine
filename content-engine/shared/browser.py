"""
Headless browser rendering primitives, shared by every lane that turns HTML
into an image.

Extracted from Part C so Part E (pillar repurposer) can render photo covers
with the same engine instead of paying an image API. See DECISIONS.md D-01.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config

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
        "Fallback: open the generated .html files in any browser and use "
        "Print -> Save as PDF, or take a screenshot at the target size. The "
        "HTML is the source of truth; the PNG step is only automation."
    )


def jinja_env(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def html_to_png(
    html_path: Path,
    png_path: Path,
    browser: str | None = None,
    *,
    width: int = config.CANVAS_W,
    height: int = config.CANVAS_H,
) -> Path:
    """Screenshot a local HTML file at an exact pixel size.

    --virtual-time-budget is what makes this reliable: it tells headless Chrome
    to fast-forward timers and pending network (webfonts, data: images) before
    capturing, instead of screenshotting a half-loaded page.
    """
    # as_uri() requires an absolute path, and callers legitimately pass
    # relative output directories.
    html_path = html_path.resolve()
    png_path = png_path.resolve()
    exe = browser or find_browser()

    cmd = [
        exe,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-sandbox",
        "--force-device-scale-factor=1",
        f"--virtual-time-budget={VIRTUAL_TIME_MS}",
        f"--window-size={width},{height}",
        f"--screenshot={png_path}",
        html_path.as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not png_path.exists():
        raise RenderError(
            f"Chrome did not produce {png_path.name}.\nstderr: {proc.stderr[-800:]}"
        )
    return png_path


def render_pages(
    template_dir: Path,
    template_name: str,
    contexts: list[dict[str, Any]],
    out_dir: Path,
    *,
    stem: str = "page",
    width: int = config.CANVAS_W,
    height: int = config.CANVAS_H,
    png: bool = True,
    log=print,
) -> tuple[list[Path], list[Path]]:
    """Render a list of contexts through one template to HTML (and PNG)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tpl = jinja_env(template_dir).get_template(template_name)

    html_paths: list[Path] = []
    for i, ctx in enumerate(contexts, start=1):
        p = out_dir / f"{stem}-{i:02d}.html"
        p.write_text(tpl.render(**ctx), encoding="utf-8")
        html_paths.append(p)

    png_paths: list[Path] = []
    if png:
        exe = find_browser()
        for hp in html_paths:
            pp = hp.with_suffix(".png")
            html_to_png(hp, pp, exe, width=width, height=height)
            png_paths.append(pp)
            log(f"    ok {pp.name}")
    return html_paths, png_paths
