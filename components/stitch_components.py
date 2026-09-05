"""HTML builders matching Stitch code.html exports."""

from __future__ import annotations

import html as html_mod

ACCENT = "#6C5CE7"
SECONDARY = "#c6bfff"
BG_SURFACE = "#1A1A2E"
BORDER = "#2A2A42"
TEXT = "#E8E8F0"
TEXT_MUTED = "#94A3B8"
DONE = "#2ECC71"
PROCESSING = "#F5A623"
PENDING = "#5C5C70"
FAILED = "#E74C3C"


def esc(text: str) -> str:
    return html_mod.escape(text or "")


def label_caps(text: str) -> str:
    return (
        f'<span class="stitch-label-caps">{esc(text)}</span>'
    )


def status_badge(status: str, label: str) -> str:
    colors = {
        "done": (DONE, "check_circle"),
        "processing": (PROCESSING, "sync"),
        "pending": (PENDING, "schedule"),
        "failed": (FAILED, "error"),
    }
    css, icon = colors.get(status, (PENDING, "schedule"))
    spin = ' style="animation:spin 1s linear infinite"' if status == "processing" else ""
    return (
        f'<span class="stitch-status-badge" style="color:{css};background:{css}1a">'
        f'<span class="material-symbols-outlined"{spin}>{icon}</span>{esc(label)}</span>'
    )


def library_row(
    *,
    title: str,
    meta: str,
    thumb_url: str,
    status: str,
    status_label: str,
    selected: bool = False,
    processing: bool = False,
) -> str:
    sel = " stitch-lib-row-selected" if selected else ""
    proc = " stitch-lib-row-processing" if processing else ""
    opacity = ' style="opacity:0.5"' if status == "pending" and not processing else ""
    bar = '<div class="stitch-lib-progress"></div>' if processing else ""
    return f"""
<div class="stitch-lib-row{sel}{proc}">
  <div class="stitch-lib-thumb"{opacity}>{bar}
    <img src="{esc(thumb_url)}" alt="" />
  </div>
  <div class="stitch-lib-body">
    <div class="stitch-lib-title">{esc(title)}</div>
    <div class="stitch-lib-meta">{esc(meta)}</div>
    {status_badge(status, status_label)}
  </div>
</div>"""


def insight_card_stitch(
    *,
    index: int,
    title: str,
    body: str,
    timestamp_label: str,
    timestamp_url: str,
    tags: list[str],
) -> str:
    ts = ""
    if timestamp_label and timestamp_url:
        ts = (
            f'<a class="stitch-ts-btn" href="{esc(timestamp_url)}" target="_blank" rel="noopener">'
            f"{esc(timestamp_label)}</a>"
        )
    tag_html = "".join(
        f'<span class="stitch-insight-tag">{esc(t)}</span>' for t in tags[:4]
    )
    return f"""
<div class="stitch-insight-card">
  <div class="stitch-insight-top">
    <span class="stitch-insight-idx">{index:02d}</span>
    {ts}
  </div>
  <h4 class="stitch-insight-title">{esc(title)}</h4>
  <p class="stitch-insight-body">{esc(body)}</p>
  <div class="stitch-insight-tags">{tag_html}</div>
</div>"""


def infer_tags(topic: str) -> list[str]:
    """Lightweight tags for Stitch-style chips when none in data."""
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "from", "how", "what"}
    words = [w.strip(".,!?\"'") for w in topic.split() if len(w) > 3]
    tags = [w for w in words if w.lower() not in stop][:3]
    return tags or [topic.split()[0][:12]] if topic else []


def token_usage_panel(total_cost: str, rows: list[tuple[str, str]], *, open_default: bool = False) -> str:
    rows_html = "".join(
        f'<div class="stitch-token-row"><span>{esc(label)}</span>'
        f'<span class="stitch-mono">{esc(val)}</span></div>'
        for label, val in rows
    )
    open_attr = " open" if open_default else ""
    return f"""
<details class="stitch-token-details"{open_attr}>
  <summary class="stitch-token-summary">
    <div class="stitch-token-summary-left">
      <span class="material-symbols-outlined">database</span>
      <span class="stitch-label-caps">Token Usage &amp; Cost</span>
    </div>
    <div class="stitch-token-summary-right">
      <span class="stitch-mono stitch-accent">Total: {esc(total_cost)}</span>
      <span class="material-symbols-outlined stitch-chevron">expand_more</span>
    </div>
  </summary>
  <div class="stitch-token-body">{rows_html}
    <div class="stitch-token-total">
      <span>TOTAL VIDEO COST</span><span class="stitch-mono stitch-accent">{esc(total_cost)}</span>
    </div>
  </div>
</details>"""


def playlist_card(
    *,
    name: str,
    video_count: int,
    focus: str,
    active: bool = False,
    thumb_gradient: str = "linear-gradient(135deg,#4029ba,#1A1A2E)",
    updated_label: str = "",
) -> str:
    border = f"2px solid {ACCENT}" if active else f"1px solid {BORDER}"
    active_badge = (
        '<span class="stitch-pl-badge-active">Active</span>' if active else ""
    )
    focus_cls = "stitch-pl-focus-active" if active else "stitch-pl-focus-idle"
    focus_text = esc(focus) if focus.strip() else "No instructions set."
    italic = "" if active else " font-style:italic;"
    dots = (
        '<div class="stitch-pl-dots">'
        '<span class="stitch-pl-dot active"></span>'
        '<span class="stitch-pl-dot"></span>'
        '<span class="stitch-pl-dot"></span></div>'
        if active else ""
    )
    name_icon = (
        '<span class="material-symbols-outlined" '
        f'style="font-size:16px;color:{PENDING};margin-left:auto;cursor:pointer">schedule</span>'
    )
    updated_row = ""
    if updated_label:
        updated_row = (
            f'<div class="stitch-pl-updated">'
            f'<span class="material-symbols-outlined" style="font-size:14px">schedule</span>'
            f'{esc(updated_label)}</div>'
        )
    return f"""
<div class="stitch-pl-card" style="border:{border}">
  <div class="stitch-pl-hero" style="background:{thumb_gradient}">
    <div class="stitch-pl-hero-badges">{active_badge}
      <span class="stitch-pl-count">{video_count} Videos</span>
    </div>
  </div>
  <div class="stitch-pl-body">
    <div style="display:flex;align-items:center;gap:6px">
      <span class="stitch-pl-name" style="margin-bottom:0">{esc(name)}</span>
      {name_icon}
    </div>
    <div class="stitch-pl-focus-label">Extraction Focus</div>
    <div class="{focus_cls}"><p style="{italic}">{focus_text}</p></div>
    {updated_row}
    {dots}
  </div>
</div>"""


def usage_meter(used_label: str, total_label: str, pct: int, cost: str) -> str:
    return f"""
<div class="stitch-glass-panel">
  <p class="stitch-label-caps">Current Month Usage</p>
  <div class="stitch-usage-big"><span>{esc(used_label)}</span>
    <span class="stitch-usage-of">/ {esc(total_label)} Tokens</span></div>
  <div class="stitch-meter"><div class="stitch-meter-fill" style="width:{pct}%"></div></div>
  <div class="stitch-meter-meta"><span>{pct}% Consumed</span><span>Est. {esc(cost)}</span></div>
</div>"""
