"""
Part D, step 4 — the filming-day packet.

Part D's real failure mode is not technical, it is that filming day does not
happen or runs long. So the packet is built to be used on a phone or tablet
propped next to the camera: scripts are grouped by SETUP so the room is moved
once per group rather than once per script, each card carries its target
duration, and there is a teleprompter view with large type.

Output is a single self-contained HTML file - no server, no app, works offline.
See DECISIONS.md D-16.
"""
from __future__ import annotations

import html
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # -> content-engine/

from shared.config import ClientProfile  # noqa: E402

PACKET_CSS = """
:root{
  --accent:%(accent)s; --accent-deep:%(accent_deep)s; --ink:%(ink)s;
  --muted:%(muted)s; --paper:%(paper)s; --alt:%(alt)s; --rule:%(rule)s;
  --flag:#AC4839;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);
  font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;}
.wrap{max-width:920px;margin:0 auto;padding:28px 20px 100px}
header{border-bottom:3px solid var(--accent);padding-bottom:16px;margin-bottom:8px}
h1{font-size:26px;letter-spacing:-.02em}
.sub{color:var(--muted);font-size:14px;margin-top:4px}
.summary{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 26px}
.pill{background:var(--alt);border:1px solid var(--rule);border-radius:999px;
  padding:5px 12px;font-size:13px;color:var(--muted)}
.pill b{color:var(--ink)}
h2.setup{font-size:13px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--accent-deep);margin:30px 0 12px;padding-top:14px;
  border-top:1px solid var(--rule)}
.card{background:#fff;border:1px solid var(--rule);border-radius:8px;
  margin-bottom:14px;overflow:hidden}
.card-head{display:flex;gap:12px;align-items:center;padding:12px 16px;
  background:var(--alt);border-bottom:1px solid var(--rule)}
.n{font-weight:700;color:var(--accent-deep);font-size:15px;min-width:28px}
.card-title{font-weight:600;flex:1;font-size:15px}
.dur{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums;
  white-space:nowrap}
.card-body{padding:14px 16px;display:flex;flex-direction:column;gap:12px}
.hook{font-size:19px;font-weight:600;line-height:1.35}
.lines{display:flex;flex-direction:column;gap:6px;font-size:15.5px}
.cta{font-style:italic;color:var(--accent-deep)}
.meta{display:grid;gap:6px 14px;font-size:13px;color:var(--muted)}
@media(min-width:640px){.meta{grid-template-columns:auto 1fr}}
.meta dt{font-size:11px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--accent-deep);padding-top:2px}
.meta dd{margin:0}
.warn{background:#F7E8E5;border-left:3px solid var(--flag);color:#7d2f22;
  padding:9px 12px;font-size:13.5px;border-radius:4px}
.done{margin-left:auto;font-size:13px;color:var(--muted);display:flex;
  align-items:center;gap:6px;cursor:pointer;user-select:none}
.done input{width:17px;height:17px;accent-color:var(--accent)}
button.tp{background:var(--accent);color:#fff;border:0;border-radius:5px;
  padding:7px 13px;font-size:13px;cursor:pointer;font-weight:600}
button.tp:hover{background:var(--accent-deep)}
/* teleprompter overlay */
#tp{position:fixed;inset:0;background:#0c1216;color:#fff;display:none;
  flex-direction:column;padding:40px 32px;z-index:50}
#tp.on{display:flex}
#tp .tp-hook{font-size:min(7vw,54px);font-weight:700;line-height:1.2;
  margin-bottom:28px;color:#fff}
#tp .tp-lines{font-size:min(5.4vw,38px);line-height:1.5;flex:1;overflow:auto;
  color:#dbe6ea;display:flex;flex-direction:column;gap:18px}
#tp .tp-cta{font-size:min(4.6vw,30px);color:#7fd0d4;margin-top:22px;font-style:italic}
#tp .tp-bar{display:flex;gap:12px;align-items:center;margin-top:22px;
  color:#8fa3ad;font-size:14px}
#tp button{background:#1d2b33;color:#fff;border:1px solid #33454f;border-radius:5px;
  padding:9px 15px;font-size:15px;cursor:pointer}
@media print{
  body{background:#fff}
  .done,button.tp,#tp{display:none!important}
  .card{break-inside:avoid;border:1px solid #ccc}
}
"""

PACKET_JS = """
const scripts = %(scripts_json)s;
let cur = 0;
const tp = document.getElementById('tp');
function paint(){
  const s = scripts[cur];
  document.getElementById('tp-hook').textContent = s.hook || '';
  const box = document.getElementById('tp-lines');
  box.innerHTML = '';
  (s.lines||[]).forEach(l => { const d=document.createElement('div'); d.textContent=l; box.appendChild(d); });
  document.getElementById('tp-cta').textContent = s.cta || '';
  document.getElementById('tp-pos').textContent = (cur+1)+' / '+scripts.length+'  ·  ~'+(s.target_seconds||45)+'s  ·  '+(s.setup||'');
}
function openTp(i){ cur=i; paint(); tp.classList.add('on'); }
function closeTp(){ tp.classList.remove('on'); }
function step(d){ cur=(cur+d+scripts.length)%%scripts.length; paint(); }
document.addEventListener('keydown', e => {
  if(!tp.classList.contains('on')) return;
  if(e.key==='Escape') closeTp();
  if(e.key==='ArrowRight'||e.key===' ') { e.preventDefault(); step(1); }
  if(e.key==='ArrowLeft') step(-1);
});
// remember which shots are filmed, per packet, on this device only
document.querySelectorAll('.done input').forEach(cb => {
  const k = 'shot_'+%(packet_key)s+'_'+cb.dataset.i;
  try { cb.checked = localStorage.getItem(k)==='1'; } catch(e){}
  cb.addEventListener('change', () => { try{ localStorage.setItem(k, cb.checked?'1':'0'); }catch(e){} });
});
"""


def build_packet(
    scripts: list[dict[str, Any]],
    client: ClientProfile,
    out_path: Path,
    *,
    packet_date: str | None = None,
) -> Path:
    """Render the filming-day packet to a single self-contained HTML file."""
    packet_date = packet_date or date.today().isoformat()
    setups = client.raw.get("filming", {}).get(
        "setups", ["operatory chair", "reception desk", "consult room", "outside signage"]
    )

    # Group by setup, preserving the configured room order so the crew moves once.
    grouped: dict[str, list[dict[str, Any]]] = {s: [] for s in setups}
    grouped.setdefault("unassigned", [])
    for s in scripts:
        key = s.get("setup") if s.get("setup") in grouped else "unassigned"
        grouped[key].append(s)

    ordered: list[dict[str, Any]] = []
    for key in list(setups) + ["unassigned"]:
        ordered.extend(grouped.get(key, []))

    total_sec = sum(int(s.get("target_seconds") or 45) for s in ordered)
    n_consent = sum(1 for s in ordered if any(
        m.get("depicts_patient") for m in (s.get("media") or [])))

    body: list[str] = []
    idx = 0
    for key in list(setups) + ["unassigned"]:
        items = grouped.get(key, [])
        if not items:
            continue
        body.append(f'<h2 class="setup">{html.escape(key)} &middot; {len(items)} shot(s)</h2>')
        for s in items:
            idx += 1
            lines = "".join(
                f"<div>{html.escape(str(l))}</div>" for l in (s.get("lines") or [])
            )
            b_roll = ", ".join(html.escape(str(b)) for b in (s.get("b_roll") or [])) or "—"
            ost = ", ".join(html.escape(str(t)) for t in (s.get("on_screen_text") or [])) or "—"
            share = html.escape(str(s.get("share_trigger") or "—"))
            warn = ""
            if any(m.get("depicts_patient") for m in (s.get("media") or [])):
                warn = ('<div class="warn"><b>Consent required.</b> A patient appears in '
                        'this shot. Do not film until the signed release naming this '
                        'channel is on file.</div>')
            body.append(f"""
<div class="card">
  <div class="card-head">
    <span class="n">{idx:02d}</span>
    <span class="card-title">{html.escape(str(s.get('title','untitled')))}</span>
    <span class="dur">~{int(s.get('target_seconds') or 45)}s</span>
    <button class="tp" onclick="openTp({idx-1})">Prompter</button>
    <label class="done"><input type="checkbox" data-i="{idx}"> filmed</label>
  </div>
  <div class="card-body">
    {warn}
    <div class="hook">{html.escape(str(s.get('hook','')))}</div>
    <div class="lines">{lines}</div>
    <div class="cta">{html.escape(str(s.get('cta','')))}</div>
    <dl class="meta">
      <dt>B-roll</dt><dd>{b_roll}</dd>
      <dt>On screen</dt><dd>{ost}</dd>
      <dt>Sent to</dt><dd>{share}</dd>
    </dl>
  </div>
</div>""")

    brand = client.brand
    css = PACKET_CSS % {
        "accent": brand.get("accent", "#0E6A70"),
        "accent_deep": brand.get("accent_deep", "#0A4E53"),
        "ink": brand.get("ink", "#15202A"),
        "muted": brand.get("ink_muted", "#546674"),
        "paper": brand.get("paper", "#FBFCFC"),
        "alt": brand.get("paper_alt", "#EEF3F4"),
        "rule": brand.get("rule", "#D9E2E6"),
    }
    js = PACKET_JS % {
        "scripts_json": json.dumps(ordered, ensure_ascii=False),
        "packet_key": json.dumps(packet_date),
    }

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Filming day — {html.escape(client.name)} — {packet_date}</title>
<style>{css}</style></head>
<body><div class="wrap">
<header>
  <h1>Filming day &middot; {html.escape(client.name)}</h1>
  <div class="sub">{packet_date} &middot; grouped by setup so the room moves once per group</div>
</header>
<div class="summary">
  <span class="pill"><b>{len(ordered)}</b> shots</span>
  <span class="pill">~<b>{total_sec // 60}m {total_sec % 60}s</b> of finished video</span>
  <span class="pill">block: <b>{client.raw.get('filming', {}).get('block_minutes', 90)} min</b></span>
  <span class="pill">consent needed: <b>{n_consent}</b></span>
</div>
{''.join(body)}
</div>

<div id="tp">
  <div class="tp-hook" id="tp-hook"></div>
  <div class="tp-lines" id="tp-lines"></div>
  <div class="tp-cta" id="tp-cta"></div>
  <div class="tp-bar">
    <button onclick="step(-1)">&larr; Prev</button>
    <button onclick="step(1)">Next &rarr;</button>
    <button onclick="closeTp()">Close</button>
    <span id="tp-pos"></span>
  </div>
</div>

<script>{js}</script>
</body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path
