# Merged blueprint — one system

What the two videos and Parts C and D become when combined into a single
architecture. This describes what is **built and running** in this repo, plus a
short roadmap of what is not.

---

## The organising principle

Taken from reference video 1, where Claude was asked to analyse its own session:

> *"Almost nothing that went wrong was a taste problem. It was mechanical. That
> should decide where you spend agents versus where you spend code. Only the last
> two need a model. Everything above them is code."*

So every step is classified, and the classification decides the implementation:

| Step type | Implementation | Why |
|---|---|---|
| **Mechanical** — rendering, file handling, format conversion, hashing, archiving, outlier arithmetic, consent lookup, phrase matching | deterministic code | testable, free, reproducible, cannot drift |
| **Taste** — research synthesis, scripting, rewriting, caption shaping | model call | genuinely needs judgement |
| **Judgement with liability** — clinical claims, publishing | **human**, enforced by code | a prompt is not a control |

Roughly 80% of this system is the first row. That is the point.

---

## Architecture

```
                    ┌──────────────── SHARED SPINE ────────────────┐
                    │  client profile · knowledge base · voice.md  │
                    │  compliance gates · consent register         │
                    │  append-only ad archive · SQLite store       │
                    └───────┬──────────────────────────┬───────────┘
                            │                          │
        ┌───────────────────┴────────┐   ┌─────────────┴──────────────────┐
        │  LANE 1 — CAROUSEL (Part C)│   │  LANE 2 — REEL (Part D)        │
        │  fully automated           │   │  automated around the human    │
        ├────────────────────────────┤   ├────────────────────────────────┤
        │ 1 topic from queue      [c]│   │ 1 mine outliers (median)    [c]│
        │ 2 research + cite       [m]│   │ 2 transcribe                [c]│
        │ 3 slide outline JSON    [m]│   │ 3 extract STRUCTURE only    [m]│
        │ 4 COMPLIANCE GATE       [c]│   │ 4 rewrite from client KB    [m]│
        │ 5 render HTML→PNG       [c]│   │ 5 COMPLIANCE GATE           [c]│
        │ 6 review page           [c]│   │ 6 filming packet            [c]│
        │ 7 CLINICAL SIGN-OFF     [H]│   │ 7 ── FILMING DAY ──         [H]│
        │ 8 per-platform captions [m]│   │ 8 ffmpeg: captions, cover   [c]│
        │ 9 caption re-gate       [c]│   │ 9 CLINICAL SIGN-OFF         [H]│
        │10 export / schedule     [c]│   │10 per-platform captions     [m]│
        │11 ARCHIVE               [c]│   │11 export / schedule         [c]│
        └────────────────────────────┘   │12 ARCHIVE                   [c]│
                                         └────────────────────────────────┘
              [c] code   [m] model   [H] human, enforced by code
```

Both lanes share one idea queue, one brand kit, one voice file, one compliance
gate and one archive. That shared spine is what makes client #2 cheap.

---

## The pipeline, merged from all four sources

| Stage | From | Implementation |
|---|---|---|
| Idea supply — outlier mining | **Part D** (neither video has it) | `mine.py`, median baseline, pluggable adapters |
| Idea supply — pillar repurposing | **Video 1** | *roadmap* — feed a transcript in as a topic |
| Voice capture | **Both videos** | `voice.py`, 8-question interview + refinement |
| Research and citation | **Part C** (neither video has it) | `research.py`, Tavily + URL verification |
| Structure extraction | **Part D** | `scripts.py`, abstract beats only |
| Rewrite to client knowledge | **Part D + video 1's voice file** | `scripts.py`, never sees the source |
| Slide outline as JSON | **Part C** | `outline.py` |
| Compliance gate | **Part C/D only** | `compliance.py`, blocking |
| Slop lint | **Video 1**, generalised | `voice.lint_slop`, warning-only |
| Rendering | **Video 1's HTML insight**, done free | `render.py`, headless Chrome |
| Filming day | **Part D** (neither video has it) | `shotlist.py`, teleprompter packet |
| Post-production | **Part D** | `post.py`, ffmpeg |
| Per-platform captions | **Video 2** | `platforms.py` |
| Publishing | **Both videos (Blotato)** | `publish.py`, free export default |
| Approval gate | **Video 1's rule, enforced** | `publish.preflight()` |
| Ad archive | **Part C/D only** | `store.py`, append-only triggers |

---

## What is actually built and verified

Everything below was run, not just written:

- Carousel: fixture → compliance → 8 rendered PNGs at 1080×1350 → review page
- Compliance: 11 distinct violations caught on a deliberately bad outline;
  consent register unblocks the media gate when a release exists
- Archive: append-only enforced at the SQLite level — `UPDATE` and `DELETE`
  both refused inside the retention window
- Outlier miner: correct medians (19,800 / 40,500) and outliers (10.8× / 3.9×)
- Reel scripting: live Gemini call produced a usable 38.5s script that passed
  compliance and drew its substance from the knowledge base
- Filming packet: renders, groups by setup, teleprompter mode works
- ffmpeg: normalise → burn captions → cover frame, verified visually
- Platform tailoring: IG 134 words/10 tags, TikTok 28/4, FB 122/0 + names the town
- Publish gate: refused without clinical approval, allowed after
- Slop lint: 13 tells on synthetic slop, clean on human copy

---

## Roadmap — what is not built

Ordered by value.

### 1. The performance feedback loop (the biggest gap in all four systems)
Nothing here measures what worked. Pull `sends/reach` and saves back in, rank
your own hooks by measured performance, and feed the winners into the scripting
prompt. Both videos claim to do this; neither does. Until this exists, the system
is a very good open loop.

### 2. Photographic covers
Video 1's strongest visual technique: a real photo of the dentist, AI-enhanced,
as slide 1, with typographic interior slides. Needs real photos of the actual
practice before it is worth wiring up. Would likely lift stop-rate more than any
other single change.

### 3. Pillar repurposing as an input
One long asset (a consultation FAQ, a recorded talk) → 20 posts. Video 1's main
input path; currently the queue only accepts topics and outliers.

### 4. Style extraction into a brand-kit file
Video 1's move of having the model analyse a reference image and write a reusable
style doc. Currently the brand kit is hand-written in `client.json`.

### 5. Live Blotato scheduling
Adapter is written, schedule-only by design, untested against the live API.

### 6. Cost instrumentation
Token and render spend per asset, per client.

### 7. Claude Code skill wrappers
If you prefer the videos' ergonomics, wrap the CLI subcommands as skills so the
whole thing is `/carousel` and `/outliers`.
