# Overlap, divergence, and what both are missing

The two videos were made independently, two months apart, by unrelated creators
with different sponsors. Where they agree is therefore worth taking seriously.
Where they disagree is where you actually have a decision to make.

---

## 1. Where they agree (seven convergences)

| # | Both do this | Adopted here? |
|---|---|---|
| 1 | **Claude Code is the engine.** Neither uses n8n, Make or Zapier. The orchestration layer is a model in a working directory. | Partly — Python instead, but see D-00 for the mapping |
| 2 | **A single voice file built by INTERVIEW**, one question at a time, pushing back on vague answers. Near-identical prompts. | **Yes** — `shared/voice.py` |
| 3 | **Blotato for publishing.** Independently. One sponsored, one explicitly not. | **Yes, optional** — `shared/publish.py` |
| 4 | **Carousels first.** Both treat them as the highest-engagement automatable format. | **Yes** — Part C |
| 5 | **A reference image or extracted style doc** locks visual consistency. | Partly — brand kit in `client.json`; style extraction not built |
| 6 | **Persisted instruction files** in the working directory make the setup repeatable. | **Yes** — client profile + knowledge base + voice file |
| 7 | **Do it manually once, then have the model write the automation** from what it learned. | **Yes** — this is how the templates and prompts were derived |

Seven independent convergences is a strong signal. Items 2, 3, 4 and 7 are the
ones I would not argue with.

---

## 2. Where they diverge (and which I picked)

| Question | Video 1 | Video 2 | This build |
|---|---|---|---|
| Tool connection | API key + paste the docs | MCP connectors (OAuth) | Direct SDK calls — neither, because Python |
| Image generation | FAL, pay-per-image | Higgsfield MCP, subscription | **Headless Chrome, free** (D-01) |
| Interior slides | **HTML render** (cheaper) | AI-generated images | **HTML render** — agrees with video 1 |
| Cover slide | AI-enhanced **real photo** | fully AI-generated | Typographic for now; photo cover deferred |
| Model | Sonnet for creative, Opus for build | Fable 5 at "extra" effort | Gemini → Claude fallback (D-04) |
| Automation unit | a Claude **skill** (`/carousel-creator`) | Claude **routines** + prompt pack | CLI subcommands |
| Voice file scope | general only, platform rules downstream | platform rules **inside** the voice file | **Video 1's way** (D-21) |
| Human gate | a prompt instruction | none, posts immediately | **enforced in code** (D-20) |
| Cost | ~$60–70/mo | higher | **$0**, Blotato optional |

Three of these mattered enough to write up: **D-21** (voice scope — video 1 is
right), **D-01** (rendering — neither, Chrome is free), and **D-20** (the gate
must be code, not a prompt).

---

## 3. What BOTH are missing

This is the useful part. Ten gaps, ordered by how much they matter for a
regulated local business.

| # | Gap | Severity for dental | Status here |
|---|---|---|---|
| 1 | **No compliance layer at all.** No concept of advertising rules, claim substantiation, or record retention. | **Fatal** | Built — `shared/compliance.py`, 3-year append-only archive |
| 2 | **No fact grounding or citation.** Video 2 generates health-adjacent claims from a voice file alone. | **Fatal** | Built — Tavily research + citation verification (D-05) |
| 3 | **No consent / PHI handling.** Neither considers patient imagery. | **Fatal** | Built — consent register hard-blocks publishing |
| 4 | **No approval gate.** Video 1 asks the model nicely; video 2 has none. | **High** | Built — `publish.preflight()` (D-20) |
| 5 | **No performance feedback loop.** Both are open loops: generate → post → done. Nothing measures what worked. | **High** | **NOT built** — biggest remaining gap |
| 6 | **No competitive research, despite claiming it.** Video 2 promises "researches what's working in your niche" and never shows it; video 1's ideation is manual Pinterest browsing. | **High** | Built — Part D outlier miner with median baseline (D-11) |
| 7 | **No originality guard.** Video 1 actively encourages close imitation. | **High** | Built — structure/content separation + n-gram guard (D-15) |
| 8 | **No capture workflow.** Neither has a way to get a real human on camera systematically. | **High** for dental | Built — Part D filming packet (D-16) |
| 9 | **No cost instrumentation.** Both mention cost; neither tracks it. | Medium | **NOT built** |
| 10 | **No idempotency / dedupe.** Nothing stops the same concept being posted twice. | Medium | Partly — `UNIQUE(client, lane, title)` on ideas |

---

## 4. What I took FROM them into this build

Five things the videos do that my Part C/D did not, now added:

1. **Interview-built voice file** (`shared/voice.py`) — both videos.
   My original design had a static `voice` block in `client.json`. The interview
   is better: it extracts things a client would never think to write down.
2. **Per-platform caption tailoring** (`shared/platforms.py`) — video 2.
   Verified: one caption → Instagram 134 words/10 tags, TikTok 28 words/4 tags,
   Facebook 122 words/0 tags and it names the town.
3. **A publishing layer** (`shared/publish.py`) — both videos.
   My build archived but never published. Free export bundle by default, Blotato
   adapter optional.
4. **AI-slop linting** (`voice.lint_slop`) — video 1's refinement loop, generalised
   into a reusable rule set. Warning-only (D-22).
5. **The "only the last two need a model" principle** — video 1's best line.
   Used to justify keeping compliance, rendering, archiving and outlier maths in
   deterministic code, with the model confined to research, scripting and taste.

## 5. What I deliberately did NOT take

- **Fully AI-generated presenters/imagery** (video 2). See the strategy artifact:
  40% of consumers say heavy AI use decreases trust, and video 1 independently
  warns against it.
- **"Reuse what already worked with a different character"** (video 1). Sound for
  a personal brand; a liability when the content is someone else's medical claims.
- **Immediate posting** (video 2). Everything here is schedule-only.
- **Platform rules inside the voice file** (video 2). See D-21.
- **The comment-keyword lead magnet** (video 1). It works, but it is engagement
  bait and sits awkwardly against the "dignified manner" rule. Flagged for your
  decision rather than built.
