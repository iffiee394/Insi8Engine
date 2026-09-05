# Part C — Carousel Factory

The lane that automates end to end, because nobody has to be on camera.

Research → cited claims → structured slide outline → **compliance gate** →
rendered PNGs → review page → clinical sign-off → per-platform captions →
export → archive.

Scripted for **saves and slide completion**, which is what the Instagram Feed
ranks. (The reels lane is scripted for sends — a different target. See
`../DECISIONS.md` D-09.)

---

## Commands

```bash
python run.py build --fixture
```

Offline. No API calls. Renders the sample outline so you can see the whole path.

| Command | What it does |
|---|---|
| `run.py seed` | Put six example dental topics in the queue |
| `run.py list` | Show the idea queue and built assets |
| `run.py build --next` | Take the top queued idea and build it |
| `run.py build --topic "Is a root canal painful"` | Build a specific topic |
| `run.py build --fixture` | Offline render, no API calls |
| `run.py build --no-png` | Write HTML only, skip Chrome |
| `run.py build --advisory` | Add the LLM "dignified manner" second opinion |
| `run.py render --slug <slug>` | Re-render after hand-editing `outline.json` |
| `run.py approve --slug <slug> --approver "Dr. X"` | Record clinical sign-off |
| `run.py export --slug <slug> --platform instagram facebook` | Tailor captions per platform, write an upload-ready bundle |
| `run.py publish --slug <slug> --platform instagram` | Write the archive record |
| `run.py archive` | Show the 3-year advertisement archive |

---

## Files

| File | Role |
|---|---|
| `research.py` | Tavily search → LLM claim extraction → **citation verification** |
| `outline.py` | Claims → structured JSON slide outline; forces the identification block |
| `render.py` | Jinja2 → HTML → headless Chrome `--screenshot` → 1080×1350 PNG |
| `run.py` | CLI and pipeline orchestration |
| `templates/` | Four distinct layouts (see below) |
| `fixtures/` | Offline sample outline |
| `out/<slug>/` | `outline.json`, `slide-NN.html`, `slide-NN.png`, `review.html` |

---

## The four templates

Four genuinely different layouts, not recolours — ten identical carousels read as
a content mill and stop earning saves.

| Template | Use it for | Look |
|---|---|---|
| `explainer` | How something works, what to expect | Editorial. Dark accent hook, numbered steps, generous whitespace |
| `myth` | Correcting a misconception | Horizontal split: struck-through claim on dark, correction on light |
| `checklist` | "Signs of", "questions to ask", "steps to" | Oversized numerals, progress rail down the left edge |
| `question` | Anxiety-adjacent topics | Quiet. The patient's question set large in italic serif |

The model picks one in `outline.py`. To add a fifth: new `.html.j2` extending
`_base.html.j2`, plus one line in `outline.py:TEMPLATES`.

Brand colours and fonts come from `shared/clients/<slug>/client.json`, so the
same templates serve every client without a code change.

---

## Rendering

Headless Chrome, no Playwright, no paid image API. See `../DECISIONS.md` D-01.

The flag that matters is `--virtual-time-budget=4000`: it makes Chrome wait for
Google Fonts before capturing instead of screenshotting a half-loaded page.

**If Chrome is missing**, the HTML is still written to disk. Open `slide-01.html`
in any browser and screenshot at 1080×1350. The HTML is the source of truth; the
PNG step is only automation.

---

## The compliance gate

Blocking. Nothing renders if it fails. Checks:

- prohibited claim language (superlatives, guarantees, "painless", "100%")
- **comfort promises** — "you won't feel", "the procedure will not hurt",
  "you will be comfortable" (outcome guarantees in everything but wording)
- specialty implication when the practice is designated a General Dentist
- technical-competence testimonials
- **every clinical claim must carry a source URL**
- the identification block on the final slide
- pricing/offer content routed to a separate approval path
- patient imagery blocked unless a matching signed release is on file
- slide count within Instagram's limit of 20

A **slop lint** also runs (banned AI vocabulary and sentence shapes) but only
warns — see `../DECISIONS.md` D-22.

---

## Where it breaks

- **Template fatigue.** Rotate all four. Consider a fifth per client.
- **A blocked build is normal.** The outline is saved to `out/<slug>/outline.json`;
  edit it and `run.py render --slug <slug>`.
- **Degraded research.** No Tavily → no claims rather than invented ones. You must
  attach sources by hand before it will render.
- **The CTA slide shows the practice name twice** (logo line + identification
  block). Cosmetic; see `../DECISIONS.md` D-08 for why it is left that way.
