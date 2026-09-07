"""
Stitch page renderers.

Each function builds a complete, self-contained HTML document and hands it to
st.components.v1.html() so it runs in an isolated iframe that is 100%
independent of Streamlit's own CSS and widget system.

Navigation bridge: clicks inside the iframe call
    window.parent.location.search = '?page=X&vid=Y'
which triggers a Streamlit rerun; st.query_params picks up the new state.
Anything that does *not* need the server (tab switching, video switching,
search, filtering) is handled entirely client-side so it stays instant.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

import db
import dbcache
from usage_tracker import get_last_run, get_lifetime, parse_usage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _e(text) -> str:
    return _html.escape(str(text or ""))


def _fmt_ts(seconds) -> str:
    if seconds is None:
        return ""
    s = max(int(seconds), 0)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_duration(seconds) -> str:
    """Human duration for metadata rows: 29m, 1h 14m."""
    if not seconds:
        return ""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m" if m else f"{total}s"


def _fmt_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%d %b %Y")
    except (ValueError, AttributeError):
        return str(raw)[:10]


def _yt_url(video_id: str, seconds=None) -> str:
    base = f"https://www.youtube.com/watch?v={video_id}"
    return f"{base}&t={int(seconds)}s" if seconds is not None else base


def _thumb_url(video: dict) -> str:
    """YouTube always serves a thumbnail off the video id — no DB column needed."""
    stored = (video.get("thumbnail_url") or "").strip()
    if stored:
        return stored
    vid = (video.get("video_id") or "").strip()
    return f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else ""


def _duration_of(video: dict) -> int:
    structured = db.parse_structured_insights(video.get("structured_insights", "{}"))
    try:
        return int(structured.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        return 0


# Resource `type` is free text from the LLM (45+ observed values). Fold it into
# a handful of families so the badges stay a readable, finite vocabulary.
_RESOURCE_FAMILIES = (
    ("ai", ("ai", "llm", "model", "gpt", "agent")),
    ("content", ("book", "paper", "course", "film", "video", "certification", "program", "game")),
    ("person", ("person", "guest", "author")),
    ("company", ("company", "carrier", "provider", "brand")),
    ("platform", ("platform", "saas", "service", "website", "builder", "community", "social")),
    ("tool", ("tool", "software", "framework", "language", "database", "container", "deployment")),
    ("concept", ("technique", "algorithm", "protocol", "standard", "method", "system", "license")),
)


def _resource_family(kind: str) -> str:
    low = str(kind or "").lower()
    for family, needles in _RESOURCE_FAMILIES:
        if any(n in low for n in needles):
            return family
    return "other"


# ---------------------------------------------------------------------------
# Design system
# ---------------------------------------------------------------------------
# Hand-authored rather than utility classes: pages are rendered as strings on
# the server and every video's detail pane is pre-rendered into the document,
# so semantic classes keep that payload small and let states, focus rings and
# hover live in the cascade instead of in class soup.

_CSS = """
:root {
  /* surfaces — a real elevation ladder, deepest to nearest */
  --bg:      #0B0C15;
  --bg-1:    #111220;
  --bg-2:    #171A28;
  --bg-3:    #1F2233;
  --line:    #242840;
  --line-2:  #343A5C;

  /* text — four rungs; body copy never uses the faint ones */
  --t1: #F2F3F9;   /* headings   ~16:1 */
  --t2: #B7BACE;   /* body copy   ~9:1 */
  --t3: #858AA6;   /* metadata    ~5:1 */
  --t4: #5A5F7C;   /* decorative only  */

  /* accent */
  --acc:   #7C6CF5;
  --acc-2: #A99BFF;
  --acc-t: #CBC4FF;
  --acc-s: rgba(124,108,245,0.13);
  --acc-b: rgba(124,108,245,0.32);

  /* semantic */
  --ok:   #35D08A;
  --warn: #F3B23F;
  --err:  #F0616A;
  --info: #5AA9F5;

  --r1: 6px; --r2: 10px; --r3: 14px;
  --rail: 56px; --side: 356px; --top: 52px;
  --ease: cubic-bezier(.4,0,.2,1);
}

*, *::before, *::after { box-sizing: border-box; }
/* Components below set display:flex/grid, which would otherwise win over the
   hidden attribute the filter and tab code toggles. */
[hidden] { display: none !important; }
html, body { height: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--t2);
  font: 400 13.5px/1.6 'Inter', system-ui, -apple-system, sans-serif;
  letter-spacing: -0.006em;
  -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
  overflow: hidden;
}
h1, h2, h3, h4 { margin: 0; color: var(--t1); font-weight: 600; letter-spacing: -0.018em; }
p { margin: 0; }
a { color: inherit; text-decoration: none; }
button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; }
input, textarea, select { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--acc-2); outline-offset: 2px; border-radius: var(--r1); }

.material-symbols-outlined {
  font-family: 'Material Symbols Outlined';
  font-variation-settings: 'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 24;
  display: inline-block; line-height: 1; text-transform: none;
  letter-spacing: normal; white-space: nowrap; direction: ltr; user-select: none;
}
.fill { font-variation-settings: 'FILL' 1; }

::-webkit-scrollbar { width: 9px; height: 9px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: #272C47; border-radius: 9px;
  border: 2px solid transparent; background-clip: content-box;
}
::-webkit-scrollbar-thumb:hover { background: #3B4168; background-clip: content-box; }

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes rise { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
.spin { animation: spin 1.4s linear infinite; }

/* ── Typography helpers ─────────────────────────────────────────── */
.caps  { font-size: 10.5px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--t3); }
.mono  { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11.5px; letter-spacing: 0; }
.muted { color: var(--t3); }
.dim   { color: var(--t4); }

/* ── App frame ──────────────────────────────────────────────────── */
.app  { display: flex; height: 100%; }
.rail {
  width: var(--rail); flex: 0 0 var(--rail); background: var(--bg-1);
  border-right: 1px solid var(--line);
  display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 12px 0;
}
.mark {
  width: 30px; height: 30px; border-radius: 9px; margin-bottom: 14px;
  background: linear-gradient(140deg, var(--acc) 0%, #4B36C9 100%);
  color: #fff; font-size: 12px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 4px 14px rgba(124,108,245,.35);
}
.rail-btn {
  width: 38px; height: 38px; border-radius: var(--r2); color: var(--t3);
  display: flex; align-items: center; justify-content: center; position: relative;
  transition: background .15s var(--ease), color .15s var(--ease);
}
.rail-btn .material-symbols-outlined { font-size: 21px; }
.rail-btn:hover { background: var(--bg-3); color: var(--t1); }
.rail-btn.on { background: var(--acc-s); color: var(--acc-t); }
.rail-btn.on::before {
  content: ""; position: absolute; left: -12px; top: 9px; bottom: 9px;
  width: 2px; border-radius: 0 2px 2px 0; background: var(--acc);
}
.rail-sp { flex: 1; }

.shell { flex: 1; display: flex; flex-direction: column; min-width: 0; }

.topbar {
  height: var(--top); flex: 0 0 var(--top); background: var(--bg-1);
  border-bottom: 1px solid var(--line);
  display: flex; align-items: center; gap: 18px; padding: 0 14px 0 16px;
}
.topbar h1 { font-size: 15px; white-space: nowrap; }
.tabs-top { display: flex; align-items: center; gap: 2px; }
.tab-top {
  padding: 6px 11px; border-radius: var(--r1); font-size: 13px; font-weight: 500;
  color: var(--t3); transition: color .15s var(--ease), background .15s var(--ease);
}
.tab-top:hover { color: var(--t1); background: var(--bg-3); }
.tab-top.on { color: var(--t1); background: var(--bg-3); font-weight: 600; }
.tab-top .n { color: var(--t4); margin-left: 5px; font-size: 11px; font-weight: 600; }
.tab-top.on .n { color: var(--acc-t); }
.top-sp { flex: 1; }

/* ── Buttons ────────────────────────────────────────────────────── */
.btn {
  display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
  padding: 7px 12px; border-radius: var(--r2); font-size: 12.5px; font-weight: 550;
  background: var(--bg-2); border: 1px solid var(--line); color: var(--t2);
  transition: background .15s var(--ease), border-color .15s var(--ease), color .15s var(--ease);
}
.btn:hover { background: var(--bg-3); border-color: var(--line-2); color: var(--t1); }
.btn:active { transform: translateY(.5px); }
.btn .material-symbols-outlined { font-size: 17px; }
.btn-primary {
  background: var(--acc); border-color: transparent; color: #fff; font-weight: 600;
  box-shadow: 0 2px 10px rgba(124,108,245,.3);
}
.btn-primary:hover { background: #8A7BFF; border-color: transparent; color: #fff; }
.btn-icon { padding: 7px; border-radius: var(--r2); color: var(--t3); border: 0; background: none; }
.btn-icon:hover { background: var(--bg-3); color: var(--t1); }
.btn-sm { padding: 5px 9px; font-size: 11.5px; }

/* ── Inputs ─────────────────────────────────────────────────────── */
.input, .textarea {
  width: 100%; background: var(--bg); border: 1px solid var(--line);
  border-radius: var(--r2); padding: 8px 11px; font-size: 13px; color: var(--t1);
  transition: border-color .15s var(--ease), background .15s var(--ease);
}
.input::placeholder, .textarea::placeholder { color: var(--t4); }
.input:focus, .textarea:focus { outline: none; border-color: var(--acc); background: var(--bg-1); }
.textarea { resize: vertical; min-height: 76px; line-height: 1.6; }
.search { position: relative; }
.search > .material-symbols-outlined {
  position: absolute; left: 9px; top: 50%; transform: translateY(-50%);
  font-size: 17px; color: var(--t4); pointer-events: none;
}
.search .input { padding-left: 31px; padding-right: 28px; }

/* ── Badges & chips ─────────────────────────────────────────────── */
.badge {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px;
  border-radius: 999px; font-size: 10.5px; font-weight: 650; letter-spacing: .04em;
  text-transform: uppercase; white-space: nowrap;
}
.badge .material-symbols-outlined { font-size: 12px; }
.b-done { color: var(--ok);    background: rgba(53,208,138,.12); }
.b-proc { color: var(--warn);  background: rgba(243,178,63,.13); }
.b-wait { color: var(--t3);    background: rgba(133,138,166,.13); }
.b-fail { color: var(--err);   background: rgba(240,97,106,.13); }
.b-acc  { color: var(--acc-t); background: var(--acc-s); }

.kind {
  display: inline-flex; align-items: center; padding: 1px 7px; border-radius: 999px;
  font-size: 10.5px; font-weight: 650; letter-spacing: .05em; text-transform: uppercase;
  border: 1px solid var(--line-2); color: var(--t3);
}
.kind.podcast { color: var(--acc-t); border-color: var(--acc-b); }

.chip {
  padding: 4px 10px; border-radius: 999px; font-size: 11.5px; font-weight: 550;
  color: var(--t3); background: var(--bg-2); border: 1px solid var(--line);
  transition: color .14s var(--ease), background .14s var(--ease), border-color .14s var(--ease);
}
.chip:hover { color: var(--t1); border-color: var(--line-2); }
.chip.on { color: var(--acc-t); background: var(--acc-s); border-color: var(--acc-b); }
.chip .n { opacity: .6; margin-left: 4px; font-size: 10.5px; }

.seg {
  display: inline-flex; background: var(--bg); border: 1px solid var(--line);
  border-radius: var(--r2); padding: 2px; gap: 2px;
}
.seg button { padding: 4px 11px; border-radius: 7px; font-size: 11.5px; font-weight: 600; color: var(--t3); }
.seg button.on { background: var(--acc); color: #fff; }
.seg button:not(.on):hover { color: var(--t1); background: var(--bg-3); }

.ts {
  display: inline-flex; align-items: center; gap: 3px; padding: 2px 7px;
  border-radius: var(--r1); font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 11px; color: var(--acc-t); background: var(--acc-s);
  border: 1px solid transparent; transition: border-color .15s var(--ease);
}
a.ts:hover { border-color: var(--acc-b); }
.ts .material-symbols-outlined { font-size: 12px; }

/* ── Cards & sections ───────────────────────────────────────────── */
.card {
  background: var(--bg-2); border: 1px solid var(--line);
  border-radius: var(--r3); padding: 16px;
}
.sec-h { display: flex; align-items: center; gap: 10px; margin: 26px 0 12px; }
.sec-h:first-child { margin-top: 0; }
.sec-h .rule { flex: 1; height: 1px; background: var(--line); }

.empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 56px 24px; text-align: center; height: 100%;
}
.empty .material-symbols-outlined { font-size: 34px; color: var(--t4); }
.empty h3 { font-size: 14px; color: var(--t2); }
.empty p { font-size: 12.5px; max-width: 340px; color: var(--t3); }
"""

_CSS += """
/* ── Library sidebar ────────────────────────────────────────────── */
.side {
  width: var(--side); flex: 0 0 var(--side); min-width: 0;
  background: var(--bg-1); border-right: 1px solid var(--line);
  display: flex; flex-direction: column;
}
.side-h { padding: 12px 12px 10px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; }
.side-h .row { display: flex; align-items: center; gap: 8px; }
.filters { display: flex; flex-wrap: wrap; gap: 5px; }
.side-list { flex: 1; overflow-y: auto; padding: 6px; }
.group-h {
  position: sticky; top: -6px; z-index: 2; margin: 8px 4px 4px;
  padding: 6px 6px 5px; background: var(--bg-1);
  border-bottom: 1px solid var(--line); display: flex; align-items: center; gap: 6px;
}
.group-h:first-child { margin-top: 0; }

.vrow {
  display: flex; gap: 10px; padding: 8px; margin-bottom: 2px;
  border-radius: var(--r2); border: 1px solid transparent;
  cursor: pointer; position: relative; text-align: left; width: 100%;
  transition: background .14s var(--ease), border-color .14s var(--ease);
}
.vrow:hover { background: var(--bg-2); }
.vrow.on { background: var(--acc-s); border-color: var(--acc-b); }
.vrow.on::before {
  content: ""; position: absolute; left: 0; top: 10px; bottom: 10px;
  width: 2px; border-radius: 2px; background: var(--acc);
}
.vthumb {
  width: 76px; height: 43px; flex: 0 0 76px; border-radius: var(--r1);
  overflow: hidden; position: relative;
  background: linear-gradient(135deg, #2C2560, #171A28);
}
.vthumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.vthumb .dur {
  position: absolute; right: 3px; bottom: 3px; padding: 0 4px; border-radius: 3px;
  background: rgba(6,7,14,.82); color: #E9EAF4; font-size: 9.5px; font-weight: 600;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.vthumb .bar {
  position: absolute; left: 0; bottom: 0; height: 2px; width: 100%;
  background: linear-gradient(90deg, transparent, var(--warn), transparent);
  background-size: 200% 100%; animation: sweep 1.6s linear infinite;
}
@keyframes sweep { from { background-position: 100% 0; } to { background-position: -100% 0; } }
.vrow.pending .vthumb { opacity: .55; }
.vmeta { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 3px; justify-content: center; }
.vtitle {
  font-size: 13px; font-weight: 550; color: var(--t2); line-height: 1.35;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.vrow.on .vtitle, .vrow:hover .vtitle { color: var(--t1); }
.vsub { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--t3); min-width: 0; }
.vsub .ch { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vsub .dot { color: var(--t4); }
.no-results { padding: 40px 20px; text-align: center; color: var(--t3); font-size: 12.5px; }

/* ── Detail pane ────────────────────────────────────────────────── */
.detail { flex: 1; display: flex; flex-direction: column; min-width: 0; background: var(--bg); }
.detail-h { padding: 16px 22px 0; border-bottom: 1px solid var(--line); background: var(--bg-1); }
.detail-top { display: flex; align-items: flex-start; gap: 16px; }
.detail-top .grow { min-width: 0; flex: 1; }
.eyebrow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11.5px; color: var(--t3); margin-bottom: 5px; }
.eyebrow .ch { color: var(--t2); font-weight: 600; }
.eyebrow .dot { color: var(--t4); }
.detail-h h2 {
  font-size: 19px; line-height: 1.28; margin-bottom: 12px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.detail-actions { display: flex; gap: 8px; flex-shrink: 0; }
.yt-ico { color: #FF4B45; }

.tabs { display: flex; gap: 2px; }
.tab {
  padding: 9px 12px 10px; font-size: 13px; font-weight: 500; color: var(--t3);
  border-bottom: 2px solid transparent; margin-bottom: -1px;
  display: inline-flex; align-items: center; gap: 6px;
  transition: color .15s var(--ease), border-color .15s var(--ease);
}
.tab:hover { color: var(--t1); }
.tab.on { color: var(--t1); font-weight: 600; border-bottom-color: var(--acc); }
.tab .n {
  font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 999px;
  background: var(--bg-3); color: var(--t3);
}
.tab.on .n { background: var(--acc-s); color: var(--acc-t); }
.tab[disabled] { color: var(--t4); cursor: default; }
.tab[disabled]:hover { color: var(--t4); }

.detail-body { flex: 1; overflow-y: auto; padding: 20px 22px 32px; }
.pane { max-width: 860px; animation: rise .18s var(--ease); }
.pane[hidden] { display: none; }

/* summary / TL;DR */
.tldr {
  border-left: 2px solid var(--acc); border-radius: 0 var(--r2) var(--r2) 0;
  background: linear-gradient(90deg, var(--acc-s), rgba(124,108,245,0.02));
  padding: 14px 16px; margin-bottom: 18px;
}
.tldr .caps { color: var(--acc-t); margin-bottom: 6px; }
.tldr p { color: var(--t2); font-size: 13.5px; line-height: 1.65; }

.agenda {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
  gap: 6px 20px; margin-bottom: 20px;
}
.agenda .a { position: relative; padding-left: 15px; font-size: 12.5px; color: var(--t2); line-height: 1.5; }
.agenda .a::before {
  content: ""; position: absolute; left: 3px; top: .58em;
  width: 4px; height: 4px; border-radius: 50%; background: var(--acc-2);
}

/* insight cards */
.ins {
  background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r3);
  padding: 15px 16px 14px; margin-bottom: 10px;
  transition: border-color .15s var(--ease);
}
.ins:hover { border-color: var(--line-2); }
.ins.pri { border-left: 2px solid var(--acc); }
.ins-h { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 10px; }
.ins-n {
  font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 12px; font-weight: 500;
  color: var(--t4); padding-top: 2px; flex: 0 0 auto; min-width: 20px;
}
.ins.pri .ins-n { color: var(--acc-2); }
.ins-h h4 { flex: 1; font-size: 14.5px; line-height: 1.4; min-width: 0; }
.ins-pts { list-style: none; margin: 0; padding: 0 0 0 30px; display: flex; flex-direction: column; gap: 7px; }
.ins-pts li { position: relative; font-size: 13.5px; line-height: 1.62; color: var(--t2); }
.ins-pts li::before {
  content: ""; position: absolute; left: -14px; top: .62em;
  width: 4px; height: 4px; border-radius: 50%; background: var(--t4);
}
.ins.pri .ins-pts li::before { background: var(--acc-2); }
.tags { display: flex; flex-wrap: wrap; gap: 5px; margin: 11px 0 0 30px; }
.tag {
  font-size: 10px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase;
  color: var(--t3); background: var(--bg-3); border-radius: var(--r1); padding: 2px 6px;
}

/* timeline */
.density { display: flex; height: 6px; border-radius: 3px; overflow: hidden; background: var(--bg-3); margin-bottom: 22px; }
.density i { display: block; height: 100%; }
.density i.seg { background: var(--acc); }
.tl { position: relative; padding-left: 74px; }
.tl::before { content: ""; position: absolute; left: 61px; top: 6px; bottom: 6px; width: 1px; background: var(--line); }
.tl-item { position: relative; padding-bottom: 18px; }
.tl-item:last-child { padding-bottom: 0; }
.tl-item .at {
  position: absolute; left: -74px; top: 0; width: 52px; text-align: right;
  font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; color: var(--t3);
}
.tl-item .at:hover { color: var(--acc-t); }
.tl-item::before {
  content: ""; position: absolute; left: -14px; top: 6px; width: 7px; height: 7px;
  border-radius: 50%; background: var(--bg); border: 2px solid var(--line-2);
}
.tl-item.pri::before { border-color: var(--acc); background: var(--acc); }
.tl-item h4 { font-size: 13.5px; margin-bottom: 3px; }
.tl-item p { font-size: 12.5px; color: var(--t3); line-height: 1.55; }

/* research */
.topic { background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r3); padding: 15px 16px; margin-bottom: 10px; }
.topic h4 { font-size: 14px; margin-bottom: 6px; }
.topic .what { font-size: 13px; color: var(--t2); line-height: 1.6; margin-bottom: 10px; }
.notable { list-style: none; margin: 0; padding-left: 14px; display: flex; flex-direction: column; gap: 6px; }
.notable li { position: relative; font-size: 12.5px; color: var(--t2); line-height: 1.55; }
.notable li::before { content: ""; position: absolute; left: -14px; top: .6em; width: 4px; height: 4px; border-radius: 50%; background: var(--acc-2); }
.hot { margin-top: 11px; padding: 9px 11px; border-radius: var(--r2); background: rgba(243,178,63,.07); border: 1px solid rgba(243,178,63,.18); }
.hot .caps { color: var(--warn); margin-bottom: 4px; }
.hot li { font-size: 12.5px; color: var(--t2); }

.entity { border: 1px solid var(--line); border-radius: var(--r3); background: var(--bg-2); margin-bottom: 10px; overflow: hidden; }
.entity > summary {
  list-style: none; cursor: pointer; padding: 12px 14px;
  display: flex; align-items: center; gap: 10px;
  transition: background .14s var(--ease);
}
.entity > summary::-webkit-details-marker { display: none; }
.entity > summary:hover { background: var(--bg-3); }
.entity > summary .grow { flex: 1; min-width: 0; }
.entity > summary h4 { font-size: 13.5px; }
.entity .caret { color: var(--t4); font-size: 18px; transition: transform .2s var(--ease); }
.entity[open] .caret { transform: rotate(180deg); }
.entity-body { padding: 0 14px 14px; border-top: 1px solid var(--line); padding-top: 12px; }
.entity-body > p { font-size: 13px; color: var(--t2); line-height: 1.6; }
.matches { margin-top: 11px; display: flex; flex-direction: column; gap: 7px; }

.linkrow {
  display: flex; align-items: flex-start; gap: 9px; padding: 9px 11px;
  border-radius: var(--r2); border: 1px solid var(--line); background: var(--bg);
  transition: border-color .14s var(--ease), background .14s var(--ease);
}
.linkrow:hover { border-color: var(--acc-b); background: var(--bg-2); }
.linkrow .material-symbols-outlined { font-size: 15px; color: var(--t4); margin-top: 2px; flex: 0 0 auto; }
.linkrow:hover .material-symbols-outlined { color: var(--acc-2); }
.linkrow .grow { min-width: 0; flex: 1; }
.linkrow .t { font-size: 12.5px; color: var(--t2); font-weight: 550; line-height: 1.45; }
.linkrow:hover .t { color: var(--t1); }
.linkrow .u {
  font-size: 11px; color: var(--t4); font-family: 'JetBrains Mono', ui-monospace, monospace;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block;
}
.linkrow .c { font-size: 11.5px; color: var(--t3); line-height: 1.5; margin-top: 2px; }

/* resources */
.res-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(268px, 1fr)); gap: 9px; }
.res {
  background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r2);
  padding: 12px 13px; transition: border-color .14s var(--ease);
}
.res:hover { border-color: var(--line-2); }
.res-h { display: flex; align-items: center; gap: 7px; margin-bottom: 5px; }
.res-h .name { font-size: 13px; font-weight: 600; color: var(--t1); flex: 1; min-width: 0; }
.res .d { font-size: 12.5px; color: var(--t2); line-height: 1.55; }
.res .f { display: flex; align-items: center; gap: 7px; margin-top: 8px; }
.dotb { width: 6px; height: 6px; border-radius: 50%; flex: 0 0 6px; }
.f-ai { background: #A99BFF; } .f-tool { background: #5AA9F5; } .f-platform { background: #35D08A; }
.f-content { background: #F3B23F; } .f-person { background: #F0616A; } .f-company { background: #E08CF0; }
.f-concept { background: #6FD9D1; } .f-other { background: #858AA6; }

/* guest */
.guest { display: flex; gap: 14px; }
.guest .av {
  width: 46px; height: 46px; flex: 0 0 46px; border-radius: 12px;
  background: linear-gradient(140deg, var(--acc), #4B36C9);
  display: flex; align-items: center; justify-content: center; color: #fff; font-size: 17px; font-weight: 700;
}

/* errors + inline notices */
.notice {
  display: flex; gap: 9px; align-items: flex-start; padding: 10px 12px;
  border-radius: var(--r2); font-size: 12.5px; line-height: 1.55;
  background: var(--acc-s); border: 1px solid var(--acc-b); color: var(--acc-t);
}
.notice .material-symbols-outlined { font-size: 16px; flex: 0 0 auto; margin-top: 1px; }
.notice.err { background: rgba(240,97,106,.09); border-color: rgba(240,97,106,.28); color: #FFB4B8; }
.notice pre {
  margin: 6px 0 0; font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px;
  white-space: pre-wrap; word-break: break-word; color: var(--t3); max-height: 150px; overflow: auto;
}

/* composer */
.composer { border-top: 1px solid var(--line); background: var(--bg-1); padding: 12px 22px; }
.composer .wrap { position: relative; max-width: 860px; }
.composer textarea {
  width: 100%; background: var(--bg); border: 1px solid var(--line); border-radius: var(--r3);
  padding: 10px 40px 10px 13px; font-size: 13px; color: var(--t1);
  resize: none; max-height: 120px; line-height: 1.55;
}
.composer textarea:focus { outline: none; border-color: var(--acc); }
.composer textarea::placeholder { color: var(--t4); }
.composer .send {
  position: absolute; right: 8px; bottom: 8px; width: 26px; height: 26px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: var(--t4); transition: color .14s var(--ease), background .14s var(--ease);
}
.composer .send:hover { color: #fff; background: var(--acc); }

/* ── Modal ──────────────────────────────────────────────────────── */
.modal { position: fixed; inset: 0; z-index: 90; display: flex; align-items: flex-start; justify-content: center; padding-top: 12vh; }
.modal[hidden] { display: none; }
.modal .backdrop { position: absolute; inset: 0; background: rgba(5,6,12,.66); backdrop-filter: blur(3px); }
.modal .sheet {
  position: relative; width: min(520px, calc(100% - 40px));
  background: var(--bg-1); border: 1px solid var(--line-2); border-radius: 16px;
  box-shadow: 0 24px 70px rgba(0,0,0,.6); padding: 20px; animation: rise .16s var(--ease);
}
.modal h3 { font-size: 15px; margin-bottom: 3px; }
.modal .sub { font-size: 12.5px; color: var(--t3); margin-bottom: 16px; }
.modal .foot { display: flex; align-items: center; gap: 10px; margin-top: 16px; }
"""

_CSS += """
/* ── Full-width page bodies (queue / playlists / settings) ──────── */
.page { flex: 1; overflow-y: auto; }
.page-in { max-width: 1240px; margin: 0 auto; padding: 24px 28px 48px; }
.page-h { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 22px; }
.page-h h2 { font-size: 20px; margin-bottom: 3px; }
.page-h p { font-size: 13px; color: var(--t3); }

/* stat strip */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 22px; }
.stat { background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r3); padding: 13px 15px; }
.stat .v { font-size: 22px; font-weight: 650; color: var(--t1); letter-spacing: -0.02em; line-height: 1.15; }
.stat .k { margin-top: 3px; }
.stat.accent { border-color: var(--acc-b); background: linear-gradient(160deg, var(--acc-s), var(--bg-2) 70%); }
.stat.accent .v { color: var(--acc-t); }

/* queue rows */
.qrow {
  display: flex; align-items: center; gap: 14px; padding: 12px 14px;
  border: 1px solid var(--line); border-radius: var(--r3); background: var(--bg-2);
  margin-bottom: 8px; transition: border-color .14s var(--ease);
}
.qrow:hover { border-color: var(--line-2); }
.qrow.is-failed { border-left: 2px solid var(--err); }
.qrow.is-processing { border-left: 2px solid var(--warn); }
.qrow.is-pending { border-left: 2px solid var(--line-2); }
.qrow .grow { flex: 1; min-width: 0; }
.qrow h4 { font-size: 13.5px; line-height: 1.4; margin-bottom: 4px; }
.qrow .sub { display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--t3); flex-wrap: wrap; }
.qrow .why {
  margin-top: 7px; font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px;
  color: #FFA3A8; background: rgba(240,97,106,.07); border: 1px solid rgba(240,97,106,.2);
  border-radius: var(--r1); padding: 6px 8px; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}

/* pipeline steps */
.steps { display: flex; align-items: center; gap: 5px; }
.steps i { width: 22px; height: 3px; border-radius: 2px; background: var(--bg-3); display: block; }
.steps i.done { background: var(--ok); }
.steps i.now  { background: var(--warn); }

/* ── Playlists ──────────────────────────────────────────────────── */
.pl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.pl {
  background: var(--bg-2); border: 1px solid var(--line); border-radius: 16px;
  overflow: hidden; display: flex; flex-direction: column;
  transition: border-color .16s var(--ease), transform .16s var(--ease);
}
.pl:hover { border-color: var(--line-2); transform: translateY(-1px); }
.pl.on { border-color: var(--acc-b); }
.mosaic { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; height: 128px; background: var(--line); position: relative; }
.mosaic .cell { overflow: hidden; background: linear-gradient(135deg, #2C2560, #171A28); }
.mosaic .cell img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: .82; transition: opacity .25s var(--ease); }
.pl:hover .mosaic .cell img { opacity: 1; }
.mosaic::after {
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(to top, var(--bg-2) 2%, rgba(23,26,40,.25) 45%, transparent 75%);
}
.mosaic .tags { position: absolute; left: 11px; bottom: 10px; z-index: 1; margin: 0; }
.pl-b { padding: 14px 15px 15px; display: flex; flex-direction: column; gap: 11px; flex: 1; }
.pl-b h3 { font-size: 14.5px; }
.mix { display: flex; height: 4px; border-radius: 2px; overflow: hidden; background: var(--bg-3); }
.mix i { display: block; height: 100%; }
.mix .m-done { background: var(--ok); } .mix .m-proc { background: var(--warn); }
.mix .m-wait { background: var(--t4); } .mix .m-fail { background: var(--err); }
.legend { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11px; color: var(--t3); }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.focus-box {
  background: var(--bg); border: 1px solid var(--line); border-radius: var(--r2);
  padding: 10px 11px; font-size: 12.5px; color: var(--t2); line-height: 1.55; min-height: 62px;
}
.focus-box.none { color: var(--t4); font-style: italic; }
.pl-new {
  border: 1px dashed var(--line-2); border-radius: 16px; background: transparent;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 32px 20px; min-height: 240px; text-align: center;
  transition: border-color .16s var(--ease), background .16s var(--ease);
}
.pl-new:hover { border-color: var(--acc-b); background: var(--acc-s); }
.pl-new .material-symbols-outlined { font-size: 26px; color: var(--t3); }
.pl-new:hover .material-symbols-outlined { color: var(--acc-t); }
.pl-new .t { font-size: 13.5px; font-weight: 600; color: var(--t2); }
.pl-new p { font-size: 12px; color: var(--t3); max-width: 220px; }

/* ── Settings ───────────────────────────────────────────────────── */
.set-grid { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 6fr); gap: 32px; align-items: start; }
@media (max-width: 1080px) { .set-grid { grid-template-columns: minmax(0, 1fr); gap: 26px; } }
.set-sec { margin-bottom: 30px; }
.set-sec > h3 { font-size: 15px; padding-bottom: 9px; border-bottom: 1px solid var(--line); margin-bottom: 14px; }
.field { margin-bottom: 13px; }
.field > label { display: block; margin-bottom: 5px; }
.switch { position: relative; width: 38px; height: 21px; flex: 0 0 38px; }
.switch input { position: absolute; opacity: 0; width: 100%; height: 100%; margin: 0; cursor: pointer; z-index: 1; }
.switch .track { position: absolute; inset: 0; border-radius: 999px; background: var(--bg-3); border: 1px solid var(--line-2); transition: background .16s var(--ease), border-color .16s var(--ease); }
.switch .track::after {
  content: ""; position: absolute; top: 2px; left: 2px; width: 15px; height: 15px; border-radius: 50%;
  background: var(--t3); transition: transform .16s var(--ease), background .16s var(--ease);
}
.switch input:checked + .track { background: var(--acc); border-color: transparent; }
.switch input:checked + .track::after { transform: translateX(17px); background: #fff; }
.switch input:focus-visible + .track { outline: 2px solid var(--acc-2); outline-offset: 2px; }

.keyrow { background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r2); padding: 11px 12px; margin-bottom: 8px; }
.keyrow .top { display: flex; align-items: center; gap: 8px; }
.keyrow .top .material-symbols-outlined { font-size: 17px; color: var(--t3); }
.keyrow .top .name { flex: 1; font-size: 13px; font-weight: 600; color: var(--t1); }
.keyrow .src { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; color: var(--t4); margin-top: 5px; }

.meter { background: var(--bg-2); border: 1px solid var(--line); border-radius: var(--r3); padding: 18px; }
.meter .big { display: flex; align-items: baseline; gap: 7px; margin: 6px 0 14px; }
.meter .big b { font-size: 30px; font-weight: 650; color: var(--t1); letter-spacing: -0.03em; }
.meter .big span { font-size: 14px; color: var(--t3); }
.meter .track { height: 6px; border-radius: 3px; background: var(--bg); overflow: hidden; }
.meter .track i { display: block; height: 100%; border-radius: 3px; background: linear-gradient(90deg, var(--acc), var(--acc-2)); }
.meter .under { display: flex; justify-content: space-between; margin-top: 7px; }
.meter .cost { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 15px; padding-top: 13px; border-top: 1px solid var(--line); }
.pricetag {
  font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 12.5px; font-weight: 600;
  color: var(--acc-t); background: var(--acc-s); border: 1px solid var(--acc-b);
  border-radius: var(--r1); padding: 3px 9px;
}

.tbl { border: 1px solid var(--line); border-radius: var(--r3); overflow: hidden; background: var(--bg-1); }
.tbl .th, .tbl .tr { display: grid; grid-template-columns: 150px 1fr 88px 78px; gap: 10px; padding: 9px 13px; align-items: center; }
.tbl .th { background: var(--bg-2); border-bottom: 1px solid var(--line); }
.tbl .tr { border-bottom: 1px solid rgba(36,40,64,.55); font-size: 12px; }
.tbl .tr:last-child { border-bottom: 0; }
.tbl .tr:hover { background: var(--bg-2); }
.tbl .num { text-align: right; font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11.5px; }
.tbl .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--t2); }
.tbl .th .num { text-align: right; }
"""


# ---------------------------------------------------------------------------
# Shared document scaffolding
# ---------------------------------------------------------------------------

_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com"/>'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600'
    '&family=Material+Symbols+Outlined:opsz,wght,FILL@20..48,100..700,0..1&display=swap"/>'
)

# Streamlit renders us in a fixed-height iframe. Growing that iframe to the real
# viewport height is what lets the flex layout below own its own scrolling.
_FIT = """
<script>
(function fit() {
  try {
    var d = window.parent.document;
    var frames = d.querySelectorAll('iframe[title="st.iframe"]');
    var me = null;
    for (var i = 0; i < frames.length; i++) {
      if (frames[i].contentWindow === window) { me = frames[i]; break; }
    }
    if (!me) return;
    var apply = function () {
      var top = 0, el = me;
      while (el) { top += el.offsetTop || 0; el = el.offsetParent; }
      var h = Math.max(420, (window.parent.innerHeight || 900) - top);
      me.style.height = h + 'px';
    };
    apply();
    window.parent.addEventListener('resize', apply);
  } catch (e) { /* cross-origin or detached — fall back to the declared height */ }
})();
</script>
"""

_NAV = """
<script>
/* Streamlit sandboxes this iframe without allow-top-navigation, so assigning
   parent.location from in here throws — and the old fallback of navigating
   ourselves left the frame stranded on about:srcdoc. The frame *is* same-origin
   with the app, so hand the navigation to the parent document and let it run
   there, where no sandbox applies. */
function _nav(params) {
  var q = '?' + new URLSearchParams(params).toString();
  var p = null;
  try { p = window.parent; } catch (e) { p = null; }
  if (p && p !== window) {
    try {
      var s = p.document.createElement('script');
      s.textContent = 'window.location.search = ' + JSON.stringify(q) + ';';
      p.document.body.appendChild(s);
      s.remove();
      return;
    } catch (e) { /* fall through */ }
    try { p.location.search = q; return; } catch (e) { /* fall through */ }
  }
  window.location.search = q;
}
function goPage(p) { _nav({ page: p }); }
function selectVideo(v) { _nav({ page: 'library', vid: v }); }
</script>
"""


def _doc(title: str, body: str, scripts: str = "") -> str:
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        f"<title>{_e(title)}</title>{_FONTS}<style>{_CSS}</style></head>"
        f"<body>{body}{_FIT}{_NAV}{scripts}</body></html>"
    )


# The iframe is declared tall and then shrunk to the real viewport by _FIT; this
# value only matters for the moment before that script runs.
_IFRAME_HEIGHT = 900


def _embed(html: str) -> None:
    """st.components.v1.html is past its announced removal date. st.iframe
    renders an identical srcdoc iframe — same title, same sandbox flags — so
    the nav bridge and _FIT keep working either way."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=_IFRAME_HEIGHT)
    else:  # Streamlit < 1.58
        components.html(html, height=_IFRAME_HEIGHT, scrolling=False)


def _icon(name: str, cls: str = "") -> str:
    klass = f"material-symbols-outlined {cls}".strip()
    return f'<span class="{klass}">{name}</span>'


_RAIL_ITEMS = (
    ("library", "video_library", "Library"),
    ("queue", "pending_actions", "Queue"),
    ("playlists", "folder_open", "Playlists"),
    ("settings", "tune", "Settings"),
)


def _rail(active: str) -> str:
    items = ""
    for page_id, icon, label in _RAIL_ITEMS:
        on = " on" if page_id == active else ""
        items += (
            f'<button class="rail-btn{on}" title="{label}" aria-label="{label}" '
            f"onclick=\"goPage('{page_id}')\">{_icon(icon)}</button>"
        )
    return (
        '<nav class="rail">'
        '<div class="mark">IE</div>'
        f"{items}"
        '<div class="rail-sp"></div>'
        '</nav>'
    )


def _topbar(active: str, counts: dict, right: str = "") -> str:
    """Shared top bar. `counts` keys map to the tab ids they annotate."""
    tabs = ""
    for page_id, label in (("library", "Library"), ("queue", "Queue"), ("playlists", "Playlists")):
        on = " on" if page_id == active else ""
        n = counts.get(page_id)
        badge = f'<span class="n">{n}</span>' if n else ""
        tabs += f'<button class="tab-top{on}" onclick="goPage(\'{page_id}\')">{label}{badge}</button>'
    return (
        '<header class="topbar">'
        "<h1>InsightEngine</h1>"
        f'<nav class="tabs-top">{tabs}</nav>'
        '<div class="top-sp"></div>'
        f"{right}"
        "</header>"
    )


_STATUS_UI = {
    db.STATUS_DONE: ("b-done", "check_circle", "Done"),
    db.STATUS_PROCESSING: ("b-proc", "sync", "Researching"),
    db.STATUS_PENDING: ("b-wait", "schedule", "Queued"),
    db.STATUS_BATCH_QUEUED: ("b-wait", "schedule", "Batched"),
    db.STATUS_AWAITING_AGENDA: ("b-acc", "edit_note", "Needs agenda"),
    db.STATUS_FAILED: ("b-fail", "error", "Failed"),
}


# Chip value -> the statuses it covers. Buckets, not raw statuses, so "Queued"
# also catches batch_queued and awaiting_agenda.
_STATUS_BUCKET = {
    db.STATUS_DONE: "done",
    db.STATUS_PROCESSING: "running",
    db.STATUS_PENDING: "queued",
    db.STATUS_BATCH_QUEUED: "queued",
    db.STATUS_AWAITING_AGENDA: "queued",
    db.STATUS_FAILED: "failed",
}

def _status_badge(status: str) -> str:
    cls, icon, label = _STATUS_UI.get(status, ("b-wait", "schedule", str(status).title()))
    spin = " spin" if status == db.STATUS_PROCESSING else ""
    fill = " fill" if status == db.STATUS_DONE else ""
    return (
        f'<span class="badge {cls}">'
        f'<span class="material-symbols-outlined{fill}{spin}">{icon}</span>{label}</span>'
    )


def _kind_badge(video: dict) -> str:
    podcast = video.get("playlist_type") == db.PLAYLIST_PODCAST
    cls = "kind podcast" if podcast else "kind"
    return f'<span class="{cls}">{"Podcast" if podcast else "Video"}</span>'


# ---------------------------------------------------------------------------
# Library — sidebar rows
# ---------------------------------------------------------------------------

def _video_row(video: dict, selected: bool) -> str:
    vid = _e(video["video_id"])
    title = _e(video.get("title", "Untitled"))
    channel = _e(video.get("channel_name") or "Unknown channel")
    status = video.get("status", db.STATUS_PENDING)
    thumb = _e(_thumb_url(video))
    duration = _fmt_duration(_duration_of(video))
    kind = "podcast" if video.get("playlist_type") == db.PLAYLIST_PODCAST else "video"

    img = (
        f'<img src="{thumb}" alt="" loading="lazy" '
        f'onerror="this.style.display=\'none\'"/>' if thumb else ""
    )
    dur = f'<span class="dur">{_e(duration)}</span>' if duration else ""
    bar = '<span class="bar"></span>' if status == db.STATUS_PROCESSING else ""

    classes = "vrow"
    if selected:
        classes += " on"
    if status in (db.STATUS_PENDING, db.STATUS_BATCH_QUEUED):
        classes += " pending"
    bucket = _STATUS_BUCKET.get(status, "queued")

    # data-q powers the instant client-side filter; data-s / data-k the chips.
    haystack = _e(f"{video.get('title', '')} {video.get('channel_name', '')}".lower())

    return (
        f'<button class="{classes}" data-vid="{vid}" data-q="{haystack}" '
        f'data-s="{bucket}" data-k="{kind}" onclick="pickVideo(\'{vid}\')">'
        f'<span class="vthumb">{img}{dur}{bar}</span>'
        '<span class="vmeta">'
        f'<span class="vtitle">{title}</span>'
        f'<span class="vsub"><span class="ch">{channel}</span></span>'
        f'<span class="vsub">{_status_badge(status)}</span>'
        "</span></button>"
    )


# ---------------------------------------------------------------------------
# Library — detail panes
# ---------------------------------------------------------------------------

def _agenda_chips(video: dict) -> str:
    raw = (video.get("user_agenda") or "").strip() or (video.get("auto_agenda") or "").strip()
    if not raw:
        return ""
    items = [re.sub(r"^[\*•\-–]\s*", "", ln).strip() for ln in raw.splitlines()]
    items = [i for i in items if i][:8]
    if not items:
        return ""
    custom = bool((video.get("user_agenda") or "").strip())
    label = "Your agenda" if custom else "Auto-detected focus"
    chips = "".join(f'<span class="a">{_e(i)}</span>' for i in items)
    return (
        f'<div class="sec-h"><span class="caps">{label}</span><span class="rule"></span></div>'
        f'<div class="agenda">{chips}</div>'
    )


def _insight_card(idx: int, cluster: dict, video_id: str) -> str:
    topic = _e(cluster.get("topic") or cluster.get("title") or "Insight")
    points = [str(p).strip() for p in (cluster.get("points") or []) if str(p).strip()]
    start = cluster.get("timestamp_seconds")
    end = cluster.get("timestamp_range_end")
    priority = bool(cluster.get("is_agenda_item"))

    stamp = ""
    if start is not None:
        label = _fmt_ts(start)
        if end and end != start:
            label += f" – {_fmt_ts(end)}"
        stamp = (
            f'<a class="ts" href="{_e(_yt_url(video_id, start))}" target="_blank" rel="noopener" '
            f'title="Open at {_e(_fmt_ts(start))} on YouTube">'
            f'{_icon("play_arrow")}{_e(label)}</a>'
        )

    body = "".join(f"<li>{_e(p)}</li>" for p in points)
    tags = "".join(f'<span class="tag">{_e(t)}</span>' for t in (cluster.get("tags") or [])[:5])
    tags_html = f'<div class="tags">{tags}</div>' if tags else ""

    return (
        f'<article class="ins{" pri" if priority else ""}">'
        f'<div class="ins-h"><span class="ins-n">{idx:02d}</span>'
        f"<h4>{topic}</h4>{stamp}</div>"
        f'<ul class="ins-pts">{body}</ul>{tags_html}'
        "</article>"
    )


def _key_point_cards(points: list[str]) -> str:
    """Legacy shape: a flat list where '==' / '--' lines are cluster headers."""
    out, bucket, header, priority, idx = "", [], "", False, 0

    def flush() -> str:
        nonlocal bucket, idx
        if not bucket:
            return ""
        idx += 1
        card = _insight_card(idx, {"topic": header or "Key points", "points": bucket,
                                   "is_agenda_item": priority}, "")
        bucket = []
        return card

    for point in points:
        if point.startswith(("==", "--")):
            out += flush()
            header = point[2:].strip()
            priority = point.startswith("==")
        else:
            bucket.append(point)
    out += flush()
    return out


def _cost_note(video: dict) -> str:
    summary = parse_usage(video.get("usage_data", "")).get("summary", {})
    rows = [
        ("Gemini", summary.get("gemini_calls", 0), "transcription + extraction"),
        ("Groq", summary.get("groq_calls", 0), "fast extraction"),
        ("Anthropic", summary.get("anthropic_calls", 0), "insight generation"),
        ("Tavily", summary.get("tavily_searches", 0), "web research"),
    ]
    rows = [r for r in rows if r[1]]
    if not rows:
        return ""
    cost = summary.get("cost_usd_est", 0) or 0
    body = "".join(
        f'<div class="tr"><span class="name">{_e(name)}</span>'
        f'<span class="muted">{_e(note)}</span>'
        f'<span class="num">{n}</span><span class="num">&nbsp;</span></div>'
        for name, n, note in rows
    )
    return (
        '<div class="sec-h"><span class="caps">Pipeline &amp; cost</span><span class="rule"></span>'
        f'<span class="pricetag">${cost:.4f}</span></div>'
        f'<div class="tbl">{body}</div>'
    )


def _insights_pane(video: dict, structured: dict) -> str:
    vid = video["video_id"]
    status = video.get("status")

    if status == db.STATUS_FAILED:
        err = _e((video.get("error_message") or "No error detail recorded.")[:900])
        return (
            '<div class="notice err">' + _icon("error") +
            "<span><b>Processing failed.</b> The pipeline stopped before insights were "
            f"extracted.<pre>{err}</pre>"
            f'<button class="btn btn-primary" onclick="retryVideo(\'{_e(vid)}\')">'
            + _icon("refresh") + "Retry</button></span></div>"
        )

    if status != db.STATUS_DONE:
        return (
            '<div class="empty">' + _icon("hourglass_top") +
            "<h3>Not processed yet</h3>"
            "<p>Insights appear here once the transcription, research and extraction "
            "steps finish.</p></div>"
        )

    summary = video.get("summary") or structured.get("summary") or ""
    tldr = (
        '<div class="tldr"><div class="caps">Summary</div>'
        f"<p>{_e(summary)}</p></div>" if summary else ""
    )

    insights = structured.get("insights") or []
    if insights:
        cards = "".join(_insight_card(i + 1, c, vid) for i, c in enumerate(insights))
    else:
        cards = _key_point_cards(db.parse_key_points(video.get("key_points", "[]")))
    if not cards:
        cards = (
            '<div class="empty">' + _icon("lightbulb") +
            "<h3>No insights extracted</h3><p>The pipeline finished but returned no "
            "structured points for this video.</p></div>"
        )

    return tldr + _agenda_chips(video) + cards + _cost_note(video)


def _timeline_pane(video: dict, structured: dict) -> str:
    vid = video["video_id"]
    insights = [i for i in (structured.get("insights") or []) if i.get("timestamp_seconds") is not None]
    if not insights:
        return (
            '<div class="empty">' + _icon("timeline") +
            "<h3>No timestamps</h3><p>This extraction did not attach timecodes to its "
            "insights, so there is nothing to place on a timeline.</p></div>"
        )

    insights.sort(key=lambda i: i.get("timestamp_seconds") or 0)
    duration = _duration_of(video) or (
        (insights[-1].get("timestamp_range_end") or insights[-1]["timestamp_seconds"]) + 60
    )

    # Coverage bar: where in the runtime the extraction actually found material.
    segments, cursor = "", 0.0
    for ins in insights:
        start = max(float(ins["timestamp_seconds"]), 0.0)
        end = float(ins.get("timestamp_range_end") or start + 60)
        a = min(max(start / duration * 100, 0.0), 100.0)
        b = min(max(end / duration * 100, 0.0), 100.0)
        if b <= a:
            continue
        if a > cursor:
            segments += f'<i style="width:{a - cursor:.2f}%"></i>'
        segments += f'<i class="seg" style="width:{b - a:.2f}%"></i>'
        cursor = b
    if cursor < 100:
        segments += f'<i style="width:{100 - cursor:.2f}%"></i>'

    items = ""
    for ins in insights:
        start = ins["timestamp_seconds"]
        topic = _e(ins.get("topic") or "Insight")
        first = next((str(p).strip() for p in (ins.get("points") or []) if str(p).strip()), "")
        pri = " pri" if ins.get("is_agenda_item") else ""
        items += (
            f'<div class="tl-item{pri}">'
            f'<a class="at mono" href="{_e(_yt_url(vid, start))}" target="_blank" rel="noopener">'
            f"{_e(_fmt_ts(start))}</a>"
            f"<h4>{topic}</h4>"
            + (f"<p>{_e(first)}</p>" if first else "")
            + "</div>"
        )

    return (
        '<div class="sec-h"><span class="caps">Coverage across the runtime</span>'
        f'<span class="rule"></span><span class="mono muted">{_e(_fmt_duration(duration))}</span></div>'
        f'<div class="density">{segments}</div>'
        f'<div class="tl">{items}</div>'
    )


_CONFIDENCE = {
    "confirmed": ("b-done", "Confirmed"),
    "likely_match": ("b-proc", "Likely match"),
    "not_found": ("b-wait", "Not found"),
}


def _research_pane(video: dict, research: dict) -> str:
    topics = research.get("topics") or []
    targeted = research.get("targeted") or []
    guest = research.get("guest") or {}
    has_guest = bool(
        guest.get("name") and (guest.get("bio") or guest.get("summary") or guest.get("viral_things"))
    )

    if not (topics or targeted or has_guest):
        return (
            '<div class="empty">' + _icon("travel_explore") +
            "<h3>No web research</h3><p>Research runs for podcast-mode videos with an "
            "extraction focus. Nothing was gathered for this one.</p></div>"
        )

    out = ""

    if has_guest:
        initials = "".join(w[0] for w in str(guest["name"]).split()[:2]).upper()
        bio = guest.get("bio") or guest.get("summary") or ""
        viral = "".join(f"<li>{_e(v)}</li>" for v in (guest.get("viral_things") or [])[:5])
        out += (
            '<div class="sec-h"><span class="caps">Guest</span><span class="rule"></span></div>'
            f'<div class="card"><div class="guest"><div class="av">{_e(initials)}</div>'
            f'<div class="grow"><h4>{_e(guest["name"])}</h4>'
            f'<p style="font-size:13px;line-height:1.6;margin-top:5px">{_e(bio)}</p>'
            + (f'<ul class="notable" style="margin-top:10px">{viral}</ul>' if viral else "")
            + "</div></div></div>"
        )

    if topics:
        out += '<div class="sec-h"><span class="caps">Topics researched</span><span class="rule"></span></div>'
        for topic in topics:
            notable = "".join(f"<li>{_e(n)}</li>" for n in (topic.get("notable") or [])[:6])
            hot = "".join(f"<li>{_e(h)}</li>" for h in (topic.get("hot_takes") or [])[:4])
            what = topic.get("what_it_is") or topic.get("summary") or ""
            out += (
                f'<div class="topic"><h4>{_e(topic.get("topic") or "Topic")}</h4>'
                + (f'<p class="what">{_e(what)}</p>' if what else "")
                + (f'<ul class="notable">{notable}</ul>' if notable else "")
                + (f'<div class="hot"><div class="caps">Hot takes</div>'
                   f'<ul class="notable">{hot}</ul></div>' if hot else "")
                + "</div>"
            )

    if targeted:
        out += (
            '<div class="sec-h"><span class="caps">Verified against the web</span>'
            f'<span class="rule"></span><span class="muted mono">{len(targeted)}</span></div>'
        )
        for item in targeted:
            cls, label = _CONFIDENCE.get(item.get("status", ""), ("b-wait", str(item.get("status") or "Unknown")))
            matches = ""
            for m in (item.get("matches") or [])[:4]:
                url = _e(m.get("url") or "")
                snippet = _e((m.get("snippet") or "")[:190])
                matches += (
                    f'<a class="linkrow" href="{url}" target="_blank" rel="noopener">'
                    + _icon("open_in_new") +
                    f'<span class="grow"><span class="t">{_e(m.get("title") or url)}</span>'
                    f'<span class="u">{url}</span>'
                    + (f'<span class="c">{snippet}</span>' if snippet else "")
                    + "</span></a>"
                )
            out += (
                '<details class="entity"><summary>'
                f'<span class="grow"><h4>{_e(item.get("target") or "Entity")}</h4>'
                f'<span class="muted" style="font-size:11.5px">{_e(item.get("type") or "")}</span></span>'
                f'<span class="badge {cls}">{label}</span>'
                + _icon("expand_more", "caret") +
                '</summary><div class="entity-body">'
                f'<p>{_e(item.get("summary") or "")}</p>'
                + (f'<div class="matches">{matches}</div>' if matches else "")
                + "</div></details>"
            )

    return out


_LINK_GROUPS = (
    ("from_video", "Mentioned in the video", "play_circle"),
    ("from_description", "From the description", "notes"),
    ("from_research", "Found by research", "travel_explore"),
)


def _resources_pane(structured: dict, research: dict) -> str:
    resources = structured.get("resources") or []
    links = structured.get("links") or research.get("links") or {}
    if not isinstance(links, dict):
        links = {}

    if not resources and not any(links.get(k) for k, _, _ in _LINK_GROUPS):
        return (
            '<div class="empty">' + _icon("inventory_2") +
            "<h3>No resources</h3><p>Tools, books, people and links named in the video "
            "will be collected here.</p></div>"
        )

    out = ""
    if resources:
        cards = ""
        for r in resources:
            family = _resource_family(r.get("type"))
            url = (r.get("url") or "").strip()
            link = (
                f'<a class="ts" href="{_e(url)}" target="_blank" rel="noopener">'
                + _icon("open_in_new") + "Open</a>"
            ) if url else ""
            sources = ", ".join(str(r.get("source") or "").split("|"))
            cards += (
                '<div class="res"><div class="res-h">'
                f'<span class="dotb f-{family}"></span>'
                f'<span class="name">{_e(r.get("name") or "Untitled")}</span></div>'
                f'<p class="d">{_e(r.get("detail") or "")}</p>'
                f'<div class="f"><span class="caps">{_e(r.get("type") or family)}</span>'
                f'<span class="dim mono" style="flex:1">{_e(sources)}</span>{link}</div></div>'
            )
        out += (
            '<div class="sec-h"><span class="caps">Resources</span><span class="rule"></span>'
            f'<span class="muted mono">{len(resources)}</span></div>'
            f'<div class="res-grid">{cards}</div>'
        )

    for key, label, icon in _LINK_GROUPS:
        group = links.get(key) or []
        if not group:
            continue
        rows = ""
        for link in group[:24]:
            url = _e(link.get("url") or "")
            context = _e((link.get("context") or "")[:200])
            rows += (
                f'<a class="linkrow" href="{url}" target="_blank" rel="noopener">'
                + _icon(icon) +
                f'<span class="grow"><span class="t">{_e(link.get("title") or url)}</span>'
                f'<span class="u">{url}</span>'
                + (f'<span class="c">{context}</span>' if context else "")
                + "</span></a>"
            )
        out += (
            f'<div class="sec-h"><span class="caps">{label}</span><span class="rule"></span>'
            f'<span class="muted mono">{len(group)}</span></div>'
            f'<div style="display:flex;flex-direction:column;gap:6px">{rows}</div>'
        )
    return out


def _chat_pane() -> str:
    return (
        '<div class="empty" style="padding-top:40px">' + _icon("forum") +
        "<h3>Ask this video anything</h3>"
        "<p>Chat runs against the transcript embeddings for this video. It is not wired "
        "into this view yet — the box below is a preview of the interface.</p></div>"
        '<div class="composer" style="border:0;background:none;padding:0;margin-top:8px">'
        '<div class="wrap"><textarea rows="1" disabled '
        'placeholder="Chat is not connected yet…"></textarea>'
        '<button class="send" disabled aria-label="Send">' + _icon("send", "fill") + "</button>"
        "</div></div>"
    )


def _detail_pane(video: dict) -> str:
    vid = video["video_id"]
    structured = db.parse_structured_insights(video.get("structured_insights", "{}"))
    try:
        research = json.loads(video.get("research_data") or "{}")
        research = research if isinstance(research, dict) else {}
    except (json.JSONDecodeError, TypeError):
        research = {}

    insights = structured.get("insights") or []
    n_insights = len(insights) or len(
        [p for p in db.parse_key_points(video.get("key_points", "[]"))
         if not p.startswith(("==", "--"))]
    )
    n_timed = len([i for i in insights if i.get("timestamp_seconds") is not None])
    n_research = len(research.get("topics") or []) + len(research.get("targeted") or [])
    links = structured.get("links") or research.get("links") or {}
    n_resources = len(structured.get("resources") or []) + sum(
        len(links.get(k) or []) for k, _, _ in _LINK_GROUPS
    ) if isinstance(links, dict) else len(structured.get("resources") or [])

    cost = parse_usage(video.get("usage_data", "")).get("summary", {}).get("cost_usd_est", 0) or 0
    duration = _fmt_duration(_duration_of(video))
    added = _fmt_date(video.get("processed_at") or video.get("added_at") or "")

    meta = [f'<span class="ch">{_e(video.get("channel_name") or "Unknown channel")}</span>',
            _kind_badge(video)]
    if duration:
        meta.append(f'<span class="mono">{_e(duration)}</span>')
    if added:
        meta.append(f"<span>{_e(added)}</span>")
    meta.append(_status_badge(video.get("status", db.STATUS_PENDING)))
    if cost:
        meta.append(f'<span class="mono muted" title="Estimated pipeline cost">${cost:.4f}</span>')
    eyebrow = '<span class="dot">·</span>'.join(meta)

    tabs_spec = (
        ("insights", "Insights", n_insights),
        ("timeline", "Timeline", n_timed),
        ("research", "Research", n_research),
        ("resources", "Resources", n_resources),
        ("chat", "Chat", 0),
    )
    tabs = ""
    for i, (key, label, count) in enumerate(tabs_spec):
        badge = f'<span class="n">{count}</span>' if count else ""
        disabled = " disabled" if (count == 0 and key not in ("insights", "chat")) else ""
        tabs += (
            f'<button class="tab{" on" if i == 0 else ""}"{disabled} '
            f"onclick=\"showTab(this,'{key}')\">{label}{badge}</button>"
        )

    panes = {
        "insights": _insights_pane(video, structured),
        "timeline": _timeline_pane(video, structured),
        "research": _research_pane(video, research),
        "resources": _resources_pane(structured, research),
        "chat": _chat_pane(),
    }
    body = "".join(
        f'<div class="pane" data-pane="{key}"{"" if i == 0 else " hidden"}>{panes[key]}</div>'
        for i, (key, _l, _c) in enumerate(tabs_spec)
    )

    watch_url = _e(video.get("url") or _yt_url(vid))
    return (
        '<section class="detail">'
        '<div class="detail-h"><div class="detail-top"><div class="grow">'
        f'<div class="eyebrow">{eyebrow}</div>'
        f'<h2>{_e(video.get("title", "Untitled"))}</h2></div>'
        '<div class="detail-actions">'
        f'<a class="btn" href="{watch_url}" target="_blank" rel="noopener">'
        + _icon("play_circle", "yt-ico") + "Watch</a>"
        f'<button class="btn btn-primary" onclick="exportVideo(\'{_e(vid)}\')">'
        + _icon("ios_share") + "Export</button>"
        "</div></div>"
        f'<nav class="tabs">{tabs}</nav></div>'
        f'<div class="detail-body">{body}</div>'
        "</section>"
    )


def _empty_detail() -> str:
    return (
        '<section class="detail"><div class="empty">' + _icon("video_library") +
        "<h3>Nothing selected</h3>"
        "<p>Pick a video on the left, or paste a YouTube link to add one to the library."
        "</p></div></section>"
    )


# ---------------------------------------------------------------------------
# Library page
# ---------------------------------------------------------------------------

_ADD_MODAL = """
<div class="modal" id="addm" hidden>
  <div class="backdrop" onclick="closeAdd()"></div>
  <div class="sheet" role="dialog" aria-modal="true" aria-label="Add a video">
    <h3>Add a video</h3>
    <p class="sub">Paste any YouTube watch, share or shorts link. It is queued for
       transcription and extraction straight away.</p>
    <input id="addurl" class="input" type="url" spellcheck="false"
           placeholder="https://www.youtube.com/watch?v=…"
           onkeydown="if(event.key==='Enter'){event.preventDefault();doIngest();}
                      if(event.key==='Escape'){closeAdd();}"/>
    <div class="foot">
      <div class="seg" role="group" aria-label="Folder">
        <button id="f-video" class="on" onclick="setFolder('video')">Video</button>
        <button id="f-podcast" onclick="setFolder('podcast')">Podcast</button>
      </div>
      <span class="muted" style="font-size:11.5px;flex:1">
        Podcasts get web research and an extraction focus.</span>
      <button class="btn" onclick="closeAdd()">Cancel</button>
      <button class="btn btn-primary" onclick="doIngest()">Add &amp; queue</button>
    </div>
  </div>
</div>
"""

_STATUS_FILTERS = (
    ("all", "All"),
    ("done", "Done"),
    ("running", "Running"),
    ("queued", "Queued"),
    ("failed", "Failed"),
)


def _library_js(details: dict[str, str], selected_id: str | None) -> str:
    blob = json.dumps(details, ensure_ascii=False).replace("</", "<\\/")
    return """
<script>
const _D = __DETAILS__;
let _sel = __SEL__;
let _folder = 'video';

/* ── detail switching (no server round-trip) ─────────────────── */
function pickVideo(vid) {
  const html = _D[vid];
  if (html == null) { selectVideo(vid); return; }
  document.getElementById('detail').innerHTML = html;
  document.querySelectorAll('.vrow').forEach(function (el) {
    el.classList.toggle('on', el.dataset.vid === vid);
  });
  _sel = vid;
  try {
    window.parent.history.replaceState(null, '',
      '?page=' + _page + '&vid=' + encodeURIComponent(vid));
  } catch (e) {}
}

function showTab(btn, name) {
  if (btn.hasAttribute('disabled')) return;
  const root = btn.closest('.detail');
  root.querySelectorAll('.tabs .tab').forEach(function (b) { b.classList.remove('on'); });
  btn.classList.add('on');
  root.querySelectorAll('.pane').forEach(function (p) {
    p.hidden = p.dataset.pane !== name;
  });
  root.querySelector('.detail-body').scrollTop = 0;
}

/* ── instant filtering ───────────────────────────────────────── */
let _q = '', _status = 'all', _kind = 'all';

function applyFilter() {
  let shown = 0;
  document.querySelectorAll('.vrow').forEach(function (row) {
    const okQ = !_q || row.dataset.q.indexOf(_q) !== -1;
    const okS = _status === 'all' || row.dataset.s === _status;
    const okK = _kind === 'all' || row.dataset.k === _kind;
    const ok = okQ && okS && okK;
    row.hidden = !ok;
    if (ok) shown++;
  });
  document.querySelectorAll('.group-h').forEach(function (h) {
    let n = 0, el = h.nextElementSibling;
    while (el && el.classList.contains('vrow')) { if (!el.hidden) n++; el = el.nextElementSibling; }
    h.hidden = n === 0;
    h.querySelector('.mono').textContent = n;   /* count what is on screen */
  });
  document.getElementById('shown').textContent = shown;
  document.getElementById('noresults').hidden = shown > 0;
}

function onSearch(el) {
  _q = el.value.trim().toLowerCase();
  applyFilter();
}
function setStatus(btn, v) {
  _status = v;
  btn.parentElement.querySelectorAll('.chip').forEach(function (c) { c.classList.remove('on'); });
  btn.classList.add('on');
  applyFilter();
}
function setKind(btn, v) {
  _kind = v;
  btn.parentElement.querySelectorAll('button').forEach(function (c) { c.classList.remove('on'); });
  btn.classList.add('on');
  applyFilter();
}

/* ── add-video modal ─────────────────────────────────────────── */
function openAdd() {
  document.getElementById('addm').hidden = false;
  setTimeout(function () { document.getElementById('addurl').focus(); }, 30);
}
function closeAdd() { document.getElementById('addm').hidden = true; }
function setFolder(f) {
  _folder = f;
  document.getElementById('f-video').classList.toggle('on', f === 'video');
  document.getElementById('f-podcast').classList.toggle('on', f === 'podcast');
}
function doIngest() {
  const url = (document.getElementById('addurl').value || '').trim();
  if (!url) { document.getElementById('addurl').focus(); return; }
  _nav({ page: _page, action: 'ingest', url: url, folder: _folder });
}
function exportVideo(vid) { _nav({ page: _page, vid: vid, action: 'export' }); }
function retryVideo(vid) { _nav({ page: _page, vid: vid, action: 'retry' }); }

document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') closeAdd();
  if (e.key === '/' && document.activeElement.tagName !== 'INPUT'
      && document.activeElement.tagName !== 'TEXTAREA') {
    e.preventDefault();
    document.getElementById('q').focus();
  }
});
</script>
""".replace("__DETAILS__", blob).replace("__SEL__", json.dumps(selected_id))


_ACTIVE_STATUSES = (
    db.STATUS_PROCESSING,
    db.STATUS_PENDING,
    db.STATUS_BATCH_QUEUED,
    db.STATUS_AWAITING_AGENDA,
    db.STATUS_FAILED,
)


def render_library_page(
    videos: list[dict],
    selected_id: str | None,
    active_tab: str = "library",
    ingest_notice: str = "",
    embed_all_details: bool = False,
) -> None:
    """Render the library.

    `embed_all_details` pre-renders every video's pane into the page, which the
    static export needs so it stays browsable with no server behind it. The
    live app leaves it off and fetches panes on demand — see the note below.
    Callers passing it must supply full (non-light) rows.
    """
    selected = next((v for v in videos if v["video_id"] == selected_id), None) if selected_id else None
    if selected is None and videos:
        selected = videos[0]
    selected_id = selected["video_id"] if selected else None
    # `videos` may be light rows (no structured_insights/research_data), so pull
    # the complete record for the one video whose detail pane we actually draw.
    selected_full = dbcache.get_video(selected_id) if selected_id else None
    if selected_full is None:
        selected_full = selected

    active = [v for v in videos if v.get("status") in _ACTIVE_STATUSES]
    done = [v for v in videos if v.get("status") == db.STATUS_DONE]

    def group(label: str, rows: list[dict]) -> str:
        if not rows:
            return ""
        head = (
            f'<div class="group-h"><span class="caps">{label}</span>'
            f'<span class="mono dim">{len(rows)}</span></div>'
        )
        return head + "".join(_video_row(v, v["video_id"] == selected_id) for v in rows)

    list_html = group("In progress", active) + group("Processed", done)
    if not videos:
        list_html = (
            '<div class="empty" style="height:auto;padding-top:48px">' + _icon("video_library") +
            "<h3>Your library is empty</h3>"
            "<p>Paste a YouTube link to transcribe it and pull out structured insights.</p>"
            '<button class="btn btn-primary" style="margin-top:6px" onclick="openAdd()">'
            + _icon("add") + "Add a video</button></div>"
        )

    chips = "".join(
        f'<button class="chip{" on" if key == "all" else ""}" '
        f"onclick=\"setStatus(this,'{key}')\">{label}</button>"
        for key, label in _STATUS_FILTERS
    )

    notice = ""
    if ingest_notice:
        notice = (
            f'<div class="notice" style="margin:8px 6px 0">{_icon("info")}'
            f"<span>{_e(ingest_notice)}</span></div>"
        )

    counts = {"library": len(videos), "queue": len(active)}
    topbar = _topbar(
        active_tab, counts,
        right=(
            '<button class="btn btn-primary" onclick="openAdd()">'
            + _icon("add") + "Add video</button>"
        ),
    )

    body = (
        '<div class="app">' + _rail("library") +
        '<div class="shell">' + topbar +
        '<div style="flex:1;display:flex;min-height:0">'
        '<aside class="side">'
        '<div class="side-h">'
        '<div class="row"><span class="caps">Library</span>'
        '<span class="mono dim"><span id="shown">' + str(len(videos)) + "</span> of "
        + str(len(videos)) + "</span></div>"
        '<div class="search">' + _icon("search") +
        '<input id="q" class="input" type="search" placeholder="Filter by title or channel…" '
        'autocomplete="off" oninput="onSearch(this)"/></div>'
        f'<div class="filters">{chips}</div>'
        '<div class="seg" role="group" aria-label="Type">'
        '<button class="on" onclick="setKind(this,\'all\')">All</button>'
        "<button onclick=\"setKind(this,'video')\">Video</button>"
        "<button onclick=\"setKind(this,'podcast')\">Podcast</button></div>"
        f"{notice}"
        "</div>"
        f'<div class="side-list">{list_html}'
        '<div class="no-results" id="noresults" hidden>No videos match those filters.</div>'
        "</div></aside>"
        f'<div id="detail" style="flex:1;display:flex;min-width:0">'
        f'{_detail_pane(selected_full) if selected_full else _empty_detail()}</div>'
        "</div></div></div>" + _ADD_MODAL
    )

    # Only the open video is embedded; picking another asks the server for it
    # (see pickVideo's fallback). Pre-rendering all of them meant fetching every
    # video's full JSON up front and shipping a multi-megabyte page.
    if embed_all_details:
        details = {v["video_id"]: _detail_pane(v) for v in videos}
    else:
        details = {selected_id: _detail_pane(selected_full)} if selected_full else {}
    scripts = (
        f"<script>const _page = {json.dumps(active_tab if active_tab in ('library', 'queue') else 'library')};</script>"
        + _library_js(details, selected_id)
    )
    _embed(_doc("InsightEngine — Library", body, scripts))


# ---------------------------------------------------------------------------
# Queue page — the pipeline, not the library
# ---------------------------------------------------------------------------

_PIPELINE_STEPS = ("Transcript", "Knowledge graph", "Research", "Extraction")


def _queue_row(video: dict) -> str:
    status = video.get("status", db.STATUS_PENDING)
    vid = _e(video["video_id"])
    thumb = _e(_thumb_url(video))
    duration = _fmt_duration(_duration_of(video))

    # We only know "running" vs "waiting" — show honest progress, not a fake %.
    if status == db.STATUS_PROCESSING:
        steps = '<i class="now"></i>' + "<i></i>" * (len(_PIPELINE_STEPS) - 1)
    elif status == db.STATUS_FAILED:
        steps = ""
    else:
        steps = "<i></i>" * len(_PIPELINE_STEPS)

    why = ""
    if status == db.STATUS_FAILED and video.get("error_message"):
        why = f'<div class="why">{_e(video["error_message"][:400])}</div>'

    meta = [_kind_badge(video), f'<span>{_e(video.get("channel_name") or "—")}</span>']
    if duration:
        meta.append(f'<span class="mono">{_e(duration)}</span>')
    added = _fmt_date(video.get("added_at") or "")
    if added:
        meta.append(f"<span>added {_e(added)}</span>")

    return (
        f'<div class="qrow is-{_e(status)}">'
        f'<span class="vthumb" style="width:96px;height:54px;flex:0 0 96px">'
        + (f'<img src="{thumb}" alt="" loading="lazy"/>' if thumb else "")
        + "</span>"
        f'<div class="grow"><h4>{_e(video.get("title", "Untitled"))}</h4>'
        f'<div class="sub">{"<span class=dot>·</span>".join(meta)}</div>{why}</div>'
        + (f'<div class="steps" title="{" → ".join(_PIPELINE_STEPS)}">{steps}</div>'
           if steps else "")
        + f"{_status_badge(status)}"
        f'<button class="btn btn-sm" onclick="selectVideo(\'{vid}\')">Open</button>'
        "</div>"
    )


def render_queue_page(videos: list[dict], ingest_notice: str = "") -> None:
    buckets = {
        db.STATUS_PROCESSING: [],
        db.STATUS_PENDING: [],
        db.STATUS_BATCH_QUEUED: [],
        db.STATUS_AWAITING_AGENDA: [],
        db.STATUS_FAILED: [],
    }
    for v in videos:
        if v.get("status") in buckets:
            buckets[v["status"]].append(v)

    waiting = buckets[db.STATUS_PENDING] + buckets[db.STATUS_BATCH_QUEUED]
    done_count = sum(1 for v in videos if v.get("status") == db.STATUS_DONE)

    stats = "".join(
        f'<div class="stat{" accent" if accent else ""}"><div class="v">{value}</div>'
        f'<div class="k caps">{label}</div></div>'
        for label, value, accent in (
            ("Running now", len(buckets[db.STATUS_PROCESSING]), True),
            ("Waiting", len(waiting), False),
            ("Needs agenda", len(buckets[db.STATUS_AWAITING_AGENDA]), False),
            ("Failed", len(buckets[db.STATUS_FAILED]), False),
            ("Processed", done_count, False),
        )
    )

    sections = ""
    for status, label in (
        (db.STATUS_PROCESSING, "Running"),
        (db.STATUS_AWAITING_AGENDA, "Waiting on an agenda"),
        (db.STATUS_PENDING, "Queued"),
        (db.STATUS_BATCH_QUEUED, "Batched for overnight"),
        (db.STATUS_FAILED, "Failed"),
    ):
        rows = buckets.get(status) or []
        if not rows:
            continue
        sections += (
            f'<div class="sec-h"><span class="caps">{label}</span><span class="rule"></span>'
            f'<span class="mono muted">{len(rows)}</span></div>'
            + "".join(_queue_row(v) for v in rows)
        )

    if not sections:
        sections = (
            '<div class="empty">' + _icon("done_all") +
            "<h3>Queue is clear</h3><p>Every video in the library has been processed. "
            "Add another link and it will show up here while it runs.</p></div>"
        )

    notice = ""
    if ingest_notice:
        notice = f'<div class="notice" style="margin-bottom:18px">{_icon("info")}<span>{_e(ingest_notice)}</span></div>'

    active_total = sum(len(v) for v in buckets.values())
    body = (
        '<div class="app">' + _rail("queue") +
        '<div class="shell">'
        + _topbar("queue", {"library": len(videos), "queue": active_total},
                  right='<button class="btn btn-primary" onclick="openAdd()">'
                        + _icon("add") + "Add video</button>")
        + '<div class="page"><div class="page-in">'
        '<div class="page-h"><div><h2>Processing queue</h2>'
        "<p>Everything the pipeline is working on, waiting on, or stopped on.</p></div></div>"
        f"{notice}"
        f'<div class="stats">{stats}</div>{sections}'
        "</div></div></div></div>" + _ADD_MODAL
    )

    scripts = """
<script>
const _page = 'queue';
let _folder = 'video';
function openAdd() {
  document.getElementById('addm').hidden = false;
  setTimeout(function () { document.getElementById('addurl').focus(); }, 30);
}
function closeAdd() { document.getElementById('addm').hidden = true; }
function setFolder(f) {
  _folder = f;
  document.getElementById('f-video').classList.toggle('on', f === 'video');
  document.getElementById('f-podcast').classList.toggle('on', f === 'podcast');
}
function doIngest() {
  const url = (document.getElementById('addurl').value || '').trim();
  if (!url) { document.getElementById('addurl').focus(); return; }
  _nav({ page: 'queue', action: 'ingest', url: url, folder: _folder });
}
document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeAdd(); });
</script>
"""
    _embed(_doc("InsightEngine — Queue", body, scripts))


# ---------------------------------------------------------------------------
# Playlists page
# ---------------------------------------------------------------------------

def _playlist_card(playlist: dict, videos: list[dict], is_active: bool) -> str:
    name = playlist.get("name") or playlist["playlist_id"]
    focus = (playlist.get("extraction_focus") or "").strip()
    podcast = playlist.get("kind") == db.PLAYLIST_PODCAST

    tally = {"done": 0, "proc": 0, "wait": 0, "fail": 0}
    for v in videos:
        status = v.get("status")
        if status == db.STATUS_DONE:
            tally["done"] += 1
        elif status == db.STATUS_PROCESSING:
            tally["proc"] += 1
        elif status == db.STATUS_FAILED:
            tally["fail"] += 1
        else:
            tally["wait"] += 1
    total = len(videos)

    # Four newest thumbnails beat a decorative gradient: the cover shows what is
    # actually in the playlist.
    cells = ""
    for v in videos[:4]:
        url = _e(_thumb_url(v))
        cells += (
            '<div class="cell">'
            + (f'<img src="{url}" alt="" loading="lazy" '
               f"onerror=\"this.remove()\"/>" if url else "")
            + "</div>"
        )
    cells += '<div class="cell"></div>' * max(0, 4 - len(videos[:4]))

    mix = ""
    if total:
        for key, cls in (("done", "m-done"), ("proc", "m-proc"), ("wait", "m-wait"), ("fail", "m-fail")):
            if tally[key]:
                mix += f'<i class="{cls}" style="width:{tally[key] / total * 100:.1f}%"></i>'

    legend_bits = [
        ("m-done", "done", tally["done"]),
        ("m-proc", "running", tally["proc"]),
        ("m-wait", "queued", tally["wait"]),
        ("m-fail", "failed", tally["fail"]),
    ]
    legend = "".join(
        f'<span><i class="dotb" style="background:var(--{ "ok" if cls == "m-done" else "warn" if cls == "m-proc" else "t4" if cls == "m-wait" else "err" })"></i>'
        f"{n} {label}</span>"
        for cls, label, n in legend_bits if n
    )

    focus_html = (
        f'<div class="focus-box">{_e(focus)}</div>' if focus
        else '<div class="focus-box none">No extraction focus set — insights come out '
             "general-purpose. Add one to steer what the pipeline looks for.</div>"
    )

    badges = _kind_badge({"playlist_type": db.PLAYLIST_PODCAST if podcast else db.PLAYLIST_GENERAL})
    if is_active:
        badges += '<span class="badge b-acc">Default</span>'

    return (
        f'<article class="pl{" on" if is_active else ""}">'
        f'<div class="mosaic">{cells}<div class="tags">'
        f'<span class="badge b-wait" style="background:rgba(6,7,14,.7)">{total} videos</span>'
        "</div></div>"
        f'<div class="pl-b"><div class="row" style="display:flex;align-items:center;gap:8px">'
        f"<h3 style='flex:1'>{_e(name)}</h3>{badges}</div>"
        + (f'<div class="mix">{mix}</div><div class="legend">{legend}</div>' if total else
           '<div class="legend"><span class="dim">Empty playlist</span></div>')
        + '<div><span class="caps" style="display:block;margin-bottom:6px">Extraction focus</span>'
        f"{focus_html}</div></div></article>"
    )


def render_playlists_page(playlists: list[dict], all_videos: list[dict]) -> None:
    by_playlist: dict[str, list[dict]] = {}
    for v in all_videos:
        by_playlist.setdefault(v.get("playlist_id") or "", []).append(v)
    # Videos ingested before playlists existed only carry playlist_type.
    by_kind: dict[str, list[dict]] = {}
    for v in all_videos:
        by_kind.setdefault(v.get("playlist_type") or db.PLAYLIST_GENERAL, []).append(v)

    cards = ""
    for i, playlist in enumerate(playlists):
        videos = by_playlist.get(playlist["playlist_id"]) or by_kind.get(playlist.get("kind"), [])
        cards += _playlist_card(playlist, videos, i == 0)

    cards += (
        '<button class="pl-new" onclick="goPage(\'settings\')">' + _icon("create_new_folder") +
        '<span class="t">New playlist</span>'
        "<p>Group related videos and give them a shared extraction focus.</p></button>"
    )

    active = sum(1 for v in all_videos if v.get("status") in _ACTIVE_STATUSES)
    body = (
        '<div class="app">' + _rail("playlists") +
        '<div class="shell">'
        + _topbar("playlists", {"library": len(all_videos), "queue": active})
        + '<div class="page"><div class="page-in">'
        '<div class="page-h"><div><h2>Playlists</h2>'
        "<p>Collections of videos that share an extraction focus — the instructions the "
        "pipeline follows when it reads them.</p></div></div>"
        f'<div class="pl-grid">{cards}</div>'
        "</div></div></div></div>"
    )
    _embed(_doc("InsightEngine — Playlists", body))


# ---------------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------------

_API_KEYS = (
    ("bolt", "Groq", "GROQ_API_KEY", "Fast transcription and extraction"),
    ("psychology", "Anthropic", "ANTHROPIC_API_KEY", "Insight generation"),
    ("hub", "Gemini", "GEMINI_API_KEY", "Long-context extraction"),
    ("travel_explore", "Tavily", "TAVILY_API_KEY", "Web research"),
    ("smart_display", "YouTube Data", "YOUTUBE_API_KEY", "Playlist polling and metadata"),
)


def render_settings_page() -> None:
    profile = db.get_profile()
    lifetime = get_lifetime().get("summary", {})
    last_run = get_last_run()

    display_name = profile.get("display_name") or "InsightEngine User"
    email = profile.get("email") or ""
    bio = profile.get("about_me") or profile.get("interests") or ""
    personalize = bool(profile.get("personalize_extractions", False))

    gemini = lifetime.get("gemini_calls", 0)
    groq = lifetime.get("groq_calls", 0)
    anthropic = lifetime.get("anthropic_calls", 0) + lifetime.get("anthropic_batch_calls", 0)
    tavily = lifetime.get("tavily_searches", 0)
    tokens = gemini * 8000 + anthropic * 12000 + groq * 4000
    cap = 2_500_000
    pct = min(int(tokens / cap * 100), 100) if cap else 0
    used_k = tokens // 1000
    cost = lifetime.get("cost_usd_est", 0) or last_run.get("summary", {}).get("cost_usd_est", 0) or 0

    keys_html = ""
    for icon, name, env, note in _API_KEYS:
        value = os.environ.get(env, "").strip()
        if not value and env == "GEMINI_API_KEY":
            value = os.environ.get("GOOGLE_API_KEY", "").strip()
        badge = (
            '<span class="badge b-done">Connected</span>' if value
            else '<span class="badge b-wait">Not set</span>'
        )
        keys_html += (
            '<div class="keyrow"><div class="top">' + _icon(icon) +
            f'<span class="name">{_e(name)}</span>{badge}</div>'
            f'<div class="src">{_e(env)} · {_e(note)}</div></div>'
        )

    videos = db.list_videos()
    rows = ""
    for v in [x for x in videos if x.get("status") == db.STATUS_DONE][:12]:
        summary = parse_usage(v.get("usage_data", "")).get("summary", {})
        v_tokens = (
            summary.get("gemini_calls", 0) * 8000
            + summary.get("anthropic_calls", 0) * 12000
            + summary.get("groq_calls", 0) * 4000
        )
        rows += (
            '<div class="tr">'
            f'<span class="mono muted">{_e(_fmt_date(v.get("processed_at") or v.get("added_at")))}</span>'
            f'<span class="name">{_e(v.get("title", ""))}</span>'
            f'<span class="num muted">{v_tokens // 1000}k</span>'
            f'<span class="num">${summary.get("cost_usd_est", 0) or 0:.3f}</span>'
            "</div>"
        )
    if not rows:
        rows = '<div class="tr"><span class="muted">No processed videos yet.</span></div>'

    call_stats = "".join(
        f'<div class="stat"><div class="v">{value}</div><div class="k caps">{label}</div></div>'
        for label, value in (
            ("Gemini calls", gemini), ("Groq calls", groq),
            ("Anthropic calls", anthropic), ("Tavily searches", tavily),
        )
    )

    left = (
        '<div><section class="set-sec"><h3>Profile</h3>'
        '<div class="card" style="display:flex;gap:14px;align-items:center;margin-bottom:14px">'
        '<div class="av" style="width:46px;height:46px;flex:0 0 46px;border-radius:12px;'
        'background:linear-gradient(140deg,var(--acc),#4B36C9);display:flex;align-items:center;'
        'justify-content:center;color:#fff;font-weight:700">'
        f'{_e("".join(w[0] for w in display_name.split()[:2]).upper() or "IE")}</div>'
        f'<div><h4 style="font-size:14px">{_e(display_name)}</h4>'
        f'<p class="muted" style="font-size:12px">{_e(email or "No email set")}</p></div></div>'
        '<div class="field"><label class="caps">Display name</label>'
        f'<input id="s-name" class="input" type="text" value="{_e(display_name)}"/></div>'
        '<div class="field"><label class="caps">Email</label>'
        f'<input id="s-email" class="input" type="email" value="{_e(email)}"/></div>'
        '<div class="field"><label class="caps">Interests &amp; extraction bias</label>'
        '<textarea id="s-bio" class="textarea" '
        'placeholder="e.g. Focus on pricing, go-to-market and hiring signals…">'
        f"{_e(bio)}</textarea></div>"
        '<div class="card" style="display:flex;align-items:center;gap:14px;padding:12px 14px">'
        '<div style="flex:1"><div style="font-size:13px;font-weight:600;color:var(--t1)">'
        "Personalise extractions</div>"
        '<p class="muted" style="font-size:11.5px;margin-top:2px">Weight insights toward the '
        "interests above when the pipeline reads a video.</p></div>"
        '<label class="switch"><input type="checkbox" id="s-personalize"'
        f'{" checked" if personalize else ""}/><span class="track"></span></label></div>'
        '<div style="display:flex;gap:8px;margin-top:14px">'
        '<button class="btn btn-primary" onclick="saveProfile()">Save changes</button>'
        '<button class="btn" onclick="location.reload()">Discard</button></div>'
        "</section>"
        '<section class="set-sec"><h3>API keys</h3>'
        '<p class="muted" style="font-size:12.5px;margin-bottom:12px">Keys are read from the '
        'environment (<span class="mono">.env</span>) at startup. Edit that file and restart '
        "to change them.</p>"
        f"{keys_html}</section></div>"
    )

    right = (
        '<div><section class="set-sec"><h3>Usage</h3>'
        '<div class="meter"><span class="caps">Lifetime tokens (estimated)</span>'
        f'<div class="big"><b>{used_k}k</b><span>of 2.5M budget</span></div>'
        f'<div class="track"><i style="width:{pct}%"></i></div>'
        f'<div class="under"><span class="mono muted">{pct}% consumed</span>'
        f'<span class="mono muted">{max(0, 2500 - used_k)}k remaining</span></div>'
        '<div class="cost"><span class="muted" style="font-size:12.5px">'
        "Estimated spend to date</span>"
        f'<span class="pricetag">${cost:.2f}</span></div></div>'
        f'<div class="stats" style="margin-top:12px">{call_stats}</div></section>'
        '<section class="set-sec"><h3>Recent activity</h3>'
        '<div class="tbl"><div class="th"><span class="caps">Processed</span>'
        '<span class="caps">Video</span><span class="caps num">Tokens</span>'
        '<span class="caps num">Cost</span></div>'
        f"{rows}</div></section></div>"
    )

    active = sum(1 for v in videos if v.get("status") in _ACTIVE_STATUSES)
    body = (
        '<div class="app">' + _rail("settings") +
        '<div class="shell">'
        + _topbar("settings", {"library": len(videos), "queue": active})
        + '<div class="page"><div class="page-in">'
        '<div class="page-h"><div><h2>Settings</h2>'
        "<p>Who the pipeline is extracting for, what it is allowed to call, and what that "
        "has cost.</p></div></div>"
        f'<div class="set-grid">{left}{right}</div>'
        "</div></div></div></div>"
    )

    scripts = """
<script>
function saveProfile() {
  _nav({
    page: 'settings', action: 'save',
    display_name: document.getElementById('s-name').value,
    email: document.getElementById('s-email').value,
    bio: document.getElementById('s-bio').value,
    personalize: document.getElementById('s-personalize').checked ? '1' : '0'
  });
}
</script>
"""
    _embed(_doc("InsightEngine — Settings", body, scripts))
