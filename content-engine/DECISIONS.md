# Decision Log — Chairside Content Engine

Every non-obvious choice made while building Part C and Part D, plus the merge
with the two reference videos. Written so that when you come back to this you
can see what was decided, **why**, and **what you would change to go the other
way**.

Built: 30 August 2026. Nothing here has been run against a real client account.

---

## How to read this

Each entry has the decision, the reasoning, and — the important part — the
**reversal note**: what to do if you disagree. I made these calls without you,
so every one of them should be cheap to undo.

---

## Stack-level decisions

### D-00 — Three tools, and they are not the three tools in the videos

You asked for roughly three tools, free where possible. The videos use
**Claude Code + FAL + Blotato** (~$60–70/mo). I used:

| Layer | This build | Video equivalent | Cost |
|---|---|---|---|
| Engine / orchestration | **Python 3.14** (already in your venv) | Claude Code | free |
| Image rendering | **Headless Chrome** (already installed) | FAL (pay per image) | free |
| Video post-production | **ffmpeg** (already installed) | not covered | free |
| Intelligence | Gemini free tier → Claude fallback → Groq Whisper | Claude subscription | ~free |
| Publishing | export bundle (free) → Blotato (optional) | Blotato $29/mo | $0 or $29 |

**Why:** every one of these was already on your machine. Total new spend to run
the whole engine: **$0**. The videos' stack costs ~$70/mo per client before you
have revenue, and two of its three tools are paid subscriptions that become a
per-client line item when you scale to client 2–10.

**Reversal note:** if you would rather live inside Claude Code the way the videos
do, the Python modules map one-to-one onto Claude skills. `run.py build` becomes
`/carousel`, `run.py mine` becomes `/outliers`. Keep `compliance.py` and
`store.py` as real code either way — see D-20.

### D-01 — Headless Chrome for rendering, not Playwright and not a carousel API

Chrome and Edge are both on this machine. `chrome --headless=new --screenshot`
renders a 1080×1350 PNG from local HTML with zero installs. Verified working.

Rejected: **Playwright** (≈500 MB download for something Chrome already does),
**Contentdrips / Orshot / Bannerbear / Placid** ($20–40/mo, per-image quotas,
vendor lock-in, and your templates live on someone else's server),
**FAL** (as the videos use — great for photographic covers, wrong tool for
typographic information slides, and it costs per render forever).

The flag that makes it reliable is `--virtual-time-budget=4000`, which makes
Chrome wait for webfonts before capturing instead of screenshotting a
half-loaded page.

**Reversal note:** `render.py:html_to_png()` is the only place that shells out.
Swap that one function for a Playwright or API call and nothing else changes.
The HTML files are always written to disk first, so there is also a zero-tool
fallback: open `slide-01.html` in any browser and screenshot it.

### D-04 — Gemini first, Claude for clinical work, Groq for audio

Your `.env` already had all three. Gemini's free daily tier covers this
workload, so routine generation costs nothing. Claude is pinned explicitly for
**clinical claim extraction** (`prefer="claude"` in `research.py`) because that
is the step where being wrong is a regulatory problem rather than a style one.
Groq's `whisper-large-v3-turbo` handles transcription at effectively zero cost.

**Reversal note:** `shared/llm.py` has one `ask()` with a provider chain. Change
`LLM_PRIMARY` in `.env` to flip the order globally, or pass `prefer=` per call.

### D-18 — One SQLite file shared by both parts, no server

`content-engine/data/engine.db` holds ideas, assets, claims, approvals, consent
and the archive for both lanes. Rejected Airtable/Notion (monthly cost, network
dependency, and the archive needs to be tamper-evident, which a shared cloud
table is not).

**Reversal note:** if the client needs to see the calendar, sync *out* to Notion
rather than moving the source of truth there. The DB stays authoritative because
the archive lives in it.

---

## Part C — Carousel Factory

### D-05 — Citations are verified against the search results, not trusted

`research.py` collects sources via Tavily, then the model extracts claims. Any
claim whose `source_url` is **not literally in the fetched result set** is
demoted to `is_clinical=false` and its URL is stripped. The compliance gate then
refuses to render an uncited clinical claim.

**Why:** fabricated citations are the single most likely failure mode of an
LLM research step, and a fabricated medical citation on a dental account is the
worst thing this system could produce. Neither reference video has any equivalent
check — video 1 repurposes the creator's own transcript (safe by accident) and
video 2 generates from a brand-voice file alone (not safe).

If Tavily is unavailable the step enters **degraded mode**: it returns no claims
rather than inventing them, and a human must attach sources before rendering.

**Reversal note:** loosen by allowing domain-level matching instead of exact URL.
Do not loosen to "trust the model".

### D-06 — Deterministic gate first, LLM opinion second and advisory only

`compliance.py` runs two layers. Layer 1 is phrase lists, structural checks and
consent lookups: free, instant, reproducible, unit-testable, and it **blocks**.
Layer 2 is an LLM "dignified manner" review behind `--advisory`: it **warns** and
can never clear something layer 1 blocked.

**Why:** a gate you cannot test is not a gate. Also, a non-deterministic gate
that occasionally blocks good content trains the operator to disable it.

**Reversal note:** the advisory layer is off by default. Turn it on with
`--advisory` once you trust it. Never let it *unblock* anything.

### D-08 — The identification block is written by code, not by the model

N.J.A.C. 13:30-6.2 requires the practice name, address, phone and "General
Dentist" designation. `outline.py` overwrites whatever the model produced on the
final slide with `client.identification_block`.

**Why:** it is a regulatory field. Models paraphrase. A paraphrased phone number
is a compliance failure and an actual business failure.

**Known cosmetic nit:** the CTA slide shows the practice name twice — once as the
logo line, once inside the identification block. I left it because removing it
from the identification line would break the compliance check that scans for the
name. Fix by teaching `check_carousel` to also read the template's logo field.

### D-09 — Two different scripting targets: saves vs sends

Carousels are written for **saves and slide completion** (what the Feed ranks).
Reels are written for **sends per reach** (what the Reels algorithm weights most,
per Mosseri). These are different prompts and different structures, not one
"make it engaging" instruction.

**Reversal note:** if Instagram changes what it weights, the targets live in the
prompt headers of `outline.py` and `scripts.py`. Nothing else needs to move.

### D-10 — Four distinct templates, because template fatigue is the real risk

`explainer`, `myth`, `checklist`, `question` — genuinely different layouts, not
recolours. Ten identical carousels read as a content mill and stop earning saves,
which is the exact metric the lane is optimised for.

**Design fix applied:** the first render put all content at the top of the canvas
with a dead zone below. Every template now uses a `.center` band that vertically
centres the content, so slides compose correctly regardless of copy length.

**Reversal note:** templates are Jinja2 in `part-c-carousel-factory/templates/`.
Adding a fifth is a new `.html.j2` plus one line in `outline.py:TEMPLATES`.

### D-23 — Tailored captions are re-gated (this was a real bug)

When I added per-platform captions, the tailored text initially bypassed
compliance. The very first run produced a compliant carousel and a
**non-compliant Instagram caption**: *"you won't feel sharp pain during the
appointment."*

Two fixes: `cmd_export` now runs `compliance.check_text` on every tailored
caption and refuses to export on failure, and a new `COMFORT_PROMISE` rule
blocks promises about how treatment will feel ("you won't feel", "the procedure
will not hurt", "you will be comfortable"). These are outcome guarantees in
everything but wording, and models reach for them constantly when asked to write
reassuring healthcare copy.

**This is the single most important entry in this log.** Any step that generates
new user-facing copy must re-enter the gate. If you add a step, gate it.

---

## Part D — Capture-First Reels Engine

### D-11 — Median, not mean, for the outlier baseline

`find_outliers()` compares each post to the **median** of that account's recent
posts. One runaway hit drags a mean upward and then hides every subsequent
outlier behind it. Verified on the fixture: correctly found 10.8× and 3.9×
outliers against medians of 19,800 and 40,500.

Also requires at least 6 posts before computing a baseline, because a 3× multiple
on four data points is noise.

**Reversal note:** `--multiple` changes the threshold; `MIN_POSTS_FOR_BASELINE`
in `mine.py` changes the confidence floor.

### D-12 — Pluggable source adapters, free one by default

`ytdlp` (free, no key, great for YouTube/Shorts, works for TikTok, needs cookies
for Instagram), `apify` (paid ~$1.00/1k, the reliable Instagram path at volume,
enabled by setting `APIFY_TOKEN`), `csv` (manual export, always works).

**Why:** Instagram scraping is the one genuinely fragile part of any system like
this. Making the source swappable means a broken scraper is a config change, not
a rebuild.

**Honest limitation:** the free path does **not** reliably scrape Instagram.
If your watchlist is Instagram-first you will need the Apify adapter (~$5–15/mo).
I did not add a token; the adapter is written and untested against the live API.

### D-15 — Structure and content are separated, and the rewrite never sees the source

The most important architectural decision in Part D. `extract_structure()` reads
the source transcript and returns an **abstract beat sheet** — function and
device only, no phrasing, no claims. `rewrite_to_client()` is then called with
the beat sheet and the client's knowledge base, and **never receives the
transcript at all**.

**Why:** the model cannot copy what it was not shown. Three problems solved at
once — copyright, carrying over someone else's unverified clinical claim, and
Instagram's suppression of unoriginal content.

`similarity_guard()` verifies this by checking for any shared 7-word run between
the output and the source. On the test run it reported no overlap, as designed.

**This is where I disagree most with reference video 1**, which says: *"People
don't want to be seeing something new. They want to be seeing something they've
already seen before with a different character behind it."* That is fine for a
personal brand repurposing its own content. For a dental practice rewriting
another creator's medical claims it is a liability, and it is also the pattern
Instagram now demotes.

### D-16 — The filming packet is the product, not the scripts

Part D's real failure mode is not technical, it is that filming day does not
happen or overruns. So the output is a self-contained HTML packet that: groups
shots **by setup** so the room is moved once per group, shows target duration per
shot, has a large-type teleprompter mode for a phone or tablet next to the
camera, flags any shot needing patient consent, and remembers which shots are
filmed. Verified working in the browser.

**Reversal note:** it is one file, `shotlist.py`. No server, no app, prints
cleanly if the dentist prefers paper.

### D-17 — Captions are burned in, not left to the platform

`post.py` generates a styled `.ass` subtitle file from the whisper segments and
burns it in with ffmpeg, positioned with `margin_v=420` to clear the platform UI
rail. Verified on a synthetic clip.

**Why:** much of the audience watches muted; platform auto-captions cannot be
styled or proofread; and burned-in text survives cross-posting to TikTok and
Facebook. A misheard clinical word in an auto-caption is a compliance problem.

**Windows gotcha, already handled:** ffmpeg's `subtitles` filter cannot take a
path with a drive letter, so every call runs with `cwd` set to the working
directory and refers to the file by bare name.

### D-14 — Transcription tries the free path first

`youtube-transcript-api` (free, instant, no download) before
`yt-dlp` → Groq Whisper. Results are cached so re-running never re-downloads.

---

## Merge with the two reference videos

Full analysis in `content-systems-research/`. What changed in the build:

### D-19 — Publishing: free export by default, Blotato optional

Both videos independently land on **Blotato** (one sponsored, one explicitly
not), so it is the sensible paid default. But the engine must not *require* it,
because everything else here is free and a $29/mo dependency for the last mile is
a bad trade at one client.

`export_bundle()` writes numbered media, one caption file per platform, and a
manifest — upload by hand or hand it to any scheduler. The Blotato adapter is
written but **untested against the live API** and needs `BLOTATO_API_KEY`.

### D-20 — The publish gate is code, not a prompt instruction

Video 1 sets this rule by telling Claude *"nothing gets posted until you say
go."* That is a request, not a control — the same model that follows it can
forget it. Here `publish.preflight()` refuses to proceed without a recorded
clinical approval **and** a passing compliance re-check at publish time.

I also made every publish path **schedule-only**: `blotato_schedule()` raises if
you call it without a `scheduled_time`. Nothing in this engine fires an immediate
post.

**I have not connected any real social account and have not published anything.**

### D-21 — Voice file is general; platform rules live separately

The videos disagree here. Video 2 bakes per-platform formatting into the brand
voice file; video 1 argues voice should stay general with platform rules
downstream. **I went with video 1.** A file that answers both "who is speaking"
and "how many hashtags does Instagram want" gets edited for the wrong reason and
drifts.

So: `voice.py` holds identity and phrasing, built by the 8-question interview
both videos use. `platforms.py` holds per-network shape. Verified: from one
source caption, Instagram got 134 words + 10 hashtags, TikTok got 28 words + 4,
Facebook got 122 words + 0 and named the town.

### D-22 — AI-slop lint warns; compliance blocks

Adopted the anti-slop idea from both videos (banned words: *delve, leverage,
seamless, unlock, robust, elevate, game changer, empower, streamline,
transformative…*; banned shapes: *"Not X. Y."*, *"That's it. That's the…"*,
*"Here's the uncomfortable part"*, em/en dashes, three-clipped-sentences cadence).

But kept it **separate from compliance and warning-only**. A regulator cares
about compliance; a reader cares about slop. Conflating them means a stylistic
tic can halt a publish, and people then disable the gate that also catches the
regulatory problems.

Verified: 13 tells on synthetic slop, clean on hand-written human copy.

### D-24 — Platform numbers are conventions, not verified limits

The word counts and hashtag ranges in `platforms.py` are format conventions.
Only the hard character ceilings claim to be platform-enforced, and **I did not
verify them against current platform documentation.** Check before you depend on
them.

---

---

## Part E — Pillar Repurposer (reference video 1's pipeline, built)

Added after you asked for the video's pipeline with Blotato swapped out. It is a
separate lane rather than an extension of Part C because it has a different
**input** (content the practice already made) and a different **output** (a
photographic cover instead of pure typography).

### D-25 — CSS over a real photograph replaces the paid image model

The reference build generates its cover with FAL at a few cents per image. Every
effect that was buying is CSS: the golden-hour grade is a `filter` chain, the
vignette is a radial gradient, the film grain is an inline SVG `feTurbulence`
with `mix-blend-mode: overlay`, and the text sits into the image via a
directional scrim.

Three advantages beyond cost. It is **deterministic** — same input, same output,
forever. It **cannot misspell the headline or grow a sixth finger**, which is the
real failure mode of generated text-on-image. And it composites over a **real
photograph of the actual practice**, which is what reference video 1 itself
recommends: *"the more human you can make something look in an automated
fashion, the better it's going to perform."*

**Reversal note:** `cover.py:render_variants()` builds contexts and calls the
shared renderer. To use a generation API instead, replace that one function. The
templates and everything downstream stay.

### D-26 — Pillar input reuses the transcription module, which moved to `shared/`

`part-d-reels-engine/transcribe.py` became `shared/transcribe.py`, with a shim
left behind so Part D keeps working unchanged. Both lanes now share one
implementation: `youtube-transcript-api` first (free, instant), then yt-dlp plus
Groq Whisper.

Part E accepts a YouTube URL, a local `.txt`/`.md`/`.srt`, or an audio/video file.

### D-27 — A photo manifest, not descriptive filenames

Reference video 1 encodes photo meaning in filenames (`balcony-ocean-coffee`) so
the model can guess. That is fine for a personal brand and not enough here,
because a dental photo can contain a patient.

`assets/photos.json` carries a description, tags, brightness hint, and
`depicts_patient` / `subject_ref` / `consent` per photo. Photos without a release
are **excluded from the candidate pool entirely** rather than picked and then
blocked downstream — a gate that fires before the work is wasted.

**Reversal note:** `photos scan` is idempotent and never overwrites a description
you wrote, so you can re-scan freely.

### D-28 — Self-check is mechanical; review is taste

Straight application of the best line in either video. `review.py` splits into:

- `self_check()` — exact canvas dimensions, blank-render detection, and a real
  WCAG contrast ratio computed on the actual pixels in the band where the text
  sits. Free, deterministic, runs always, catches an unreadable cover before a
  human ever looks at it.
- `pick_cover()` — the model *looks at* the rendered variants and picks one,
  with a reason and one suggested fix.

The mechanical layer runs first and the taste layer only sees variants that
passed it. Vision failure degrades to the first clean variant rather than
blocking.

### D-29 — Three cover variants, every run

The reference video generates several covers and picks by eye. Same here, but
the variants differ only in things that change stop-rate — treatment, text
position, scrim strength — not in decoration. Rendering is free, so there is no
reason to generate one and hope.

### D-30 — Two kinds of claim: `practice_fact` vs `clinical_general`

**Found by testing, and it changed the compliance model for every lane.**

The first pillar run blocked on: *"Modern local anaesthetic makes most
restorative work tolerable for most patients."* The gate was right to block it —
that is a general clinical claim with no citation. But the same rule was also
about to block *"we hold emergency slots every weekday morning,"* which has no
external source and never will, because it is a fact about this practice.

So claims now carry `source_type`:

- `clinical_general` — about dentistry as a field. **Needs a citation.** Part C
  produces mostly these.
- `practice_fact` — about how this practice operates. **No citation possible or
  required**; the clinical sign-off gate is the dentist attesting it is true.
  Part E produces mostly these.

The pillar prompt tells the model to *cut* general clinical claims rather than
assert them, since the pillar lane has no research step to cite from.

**Reversal note:** if you want the stricter old behaviour, delete the
`source_type == "practice_fact"` early-continue in `compliance.check_carousel`.
Be aware it makes the pillar lane block on almost every run.

### D-31 — One automatic repair pass, and the gate stays authoritative

`build --fix` feeds the compliance report back and asks for a revision, then
**re-runs the gate on the result**. A second failure blocks like any other. The
repair prompt is explicit that it must cut uncitable claims rather than invent
citations, and regulatory fields are rewritten by code afterwards regardless.

This is the difference between a gate and a suggestion: the model gets one
chance to fix its own work, and no ability to declare itself compliant.

### D-32 — Part E refuses a remote source unless you claim it as your own

**Found by running the pipeline on a real third-party YouTube video**, which you
asked for. It worked mechanically and the output was wrong in a way that matters.

The pillar lane does two things that are correct for your own material and
indefensible for anyone else's: it rewrites the transcript in the client's voice,
and it lifts **verbatim pull-quotes** onto the slides. Run against a stranger's
video it produced slides quoting *"most patients say that root canal procedures
are actually boring"* — that creator's sentence, attributed to your client, along
with her clinical claims and none of her evidence.

So `build --from <http…>` now **refuses** unless you pass `--own-content`, and
the refusal points at Part D, which is the correct tool for someone else's
content because it extracts abstract structure and never shows the rewrite step
the source at all. Local files are assumed to be yours and pass without a flag.

**Reversal note:** `pillar.assert_ownership()`. If you want a soft warning
instead of a refusal, change the raise to a log line — but understand you are
removing the only thing standing between this lane and plagiarism-by-default.

### D-33 — Insurance and out-of-pocket copy counts as fee advertising

Same real run: a slide said *"Many dental insurances cover root canals"* and
sailed through the pricing gate, because the gate only looked for currency,
discounts and the word "free".

Telling a reader what they will pay is fee advertising whatever words you use.
`PRICING_TRIGGERS` now also catches insurance coverage, out-of-pocket, co-pay,
deductible, in-network, "we accept … insurance", "affordable", and cost
comparisons. All of it routes to the separate pricing approval path, where the
preceding-60-day baseline fee requirement lives.

**Note the plural bug this exposed:** the first version matched `insurance
covers` but not `insurances cover`. Regex rules need their own test cases —
there is a small suite in the verification section of the summary.

### Two bugs Part E surfaced

1. **Kicker truncation.** The cover kicker was derived from the concept's angle
   with a blind 40-character cut, which rendered as `COMMUNICATION H` on the
   image. The *vision reviewer caught this on its own* — it reported "remove the
   extraneous H". Now the model supplies a proper short kicker and
   `clamp_words()` trims on word boundaries only.
2. **The slop linter missed the "It's not X, it's Y" reversal** when X was more
   than one word, so it passed *"It's not the pain, it's the unknown."* The
   pattern now allows a multi-word first clause and also catches the
   `X isn't A, it's B` variant.

---

## What I deliberately did NOT build

- **Anything that posts to a real account.** Adapters exist; nothing is connected.
- **AI avatars / synthetic presenters.** See the strategy artifact — for a local
  practice this trades away the only advantage they have.
- **A performance feedback loop.** Both videos lack this and so does this build.
  It is the biggest remaining gap — see the blueprint's roadmap.
- **AI-generated photographic covers** (video 1's FAL step). Worth adding: a
  photographic cover slide would likely lift stop-rate over pure typography.
  Deliberately deferred because it needs real photos of the actual dentist.
- **Cost instrumentation.** No token/spend tracking.

---

## Open questions for you

### D-13 — Is an individual social post an "advertisement" under N.J.A.C. 13:30-6.2?

**This changes the template design.** If yes, the name/address/phone/designation
requirements attach to every post, not just campaigns. I built it the strict way
(identification block on every carousel's final slide) because that is the safe
default, but it costs you a slide.

This is a question for the client's attorney or malpractice carrier. I read the
regulation through a secondary source (Cornell LII) — verify against the current
New Jersey Administrative Code.

### D-02 / D-03 — The example client is fictional and the knowledge base is invented

`shared/clients/northfield-dental/` is a placeholder with a `(555)` phone and a
fake address. **The knowledge base caps the quality of everything downstream** —
Part D's rewrite step has nothing but that file to draw substance from. Filling it
with the real practice's answers is the highest-leverage hour in the whole build.

### Other things worth your judgement

1. **Who is the named clinical approver and what is their turnaround?** The
   pipeline blocks on this gate by design. Configured as 48 hours in
   `client.json`; if the real answer is five days, the posting cadence is fiction.
2. **Is the watchlist Instagram-first?** If so, budget for Apify (D-12).
3. **Do you want the comment-keyword CTA** both videos use for lead capture?
   I left it out — it is an engagement-bait pattern and sits awkwardly against
   the "dignified manner" rule. Your call, and it does work.
