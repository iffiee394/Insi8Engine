# Chairside Content Engine

A content system for a regulated local business — built for one New Jersey dental
practice, designed to clone to client #2 through #10 without a rewrite.

Built 30-31 August 2026. **Nothing has been connected to a real social account and
nothing has been published.**

---

## The lanes, in separate folders

| Folder | What it is |
|---|---|
| **`part-c-carousel-factory/`** | Lane 1. Research → cited claims → slide outline → compliance gate → rendered 1080×1350 PNGs → review → approval → export. Fully automated; nobody on camera. |
| **`part-d-reels-engine/`** | Lane 2. Outlier mining → transcribe → extract structure → rewrite from the client's own knowledge → compliance gate → filming-day packet → ffmpeg post → export. Automated around one monthly filming block. |
| **`part-e-pillar-repurposer/`** | Lane 3, added after the video review. Reference video 1's exact pipeline: one long thing you already made → transcript → concept → photo cover → HTML plates → export. FAL swapped for CSS-over-a-real-photo; Blotato swapped for the export bundle. |
| **`content-systems-research/`** | Deep analysis of the two videos you sent, what they overlap on, what both miss, and the merged blueprint. |

Plus:

| Folder / file | What it is |
|---|---|
| `shared/` | The spine all three lanes use: client profile, compliance gates, consent register, append-only ad archive, voice, per-platform tailoring, publishing. |
| **`DECISIONS.md`** | **Read this first.** Every choice I made, why, and how to reverse it. |
| `data/engine.db` | SQLite: ideas, assets, claims, approvals, consent, archive. |

---

## Read in this order

1. **`DECISIONS.md`** — the decision log you asked for. Start at D-00 and D-23.
2. `content-systems-research/OVERLAP-AND-GAPS.md` — what the two videos agree on,
   where they disagree, and the ten things both are missing.
3. `content-systems-research/MERGED-BLUEPRINT.md` — the combined architecture.
4. The three lane READMEs: `part-c-carousel-factory/`, `part-d-reels-engine/`,
   `part-e-pillar-repurposer/`.

---

## Run it in two minutes

No API keys needed for this — it renders from a fixture.

```bash
cd content-engine/part-c-carousel-factory && "../../.venv/Scripts/python.exe" run.py build --fixture
```

That runs the compliance gate, renders 8 branded slides with headless Chrome, and
writes a review page. Open `out/<slug>/review.html`.

Then the reels side, from a CSV fixture:

```bash
cd content-engine/part-d-reels-engine && "../../.venv/Scripts/python.exe" run.py mine --csv fixtures/sample_posts.csv
```

And the pillar lane — the video's pipeline, end to end:

```bash
cd content-engine/part-e-pillar-repurposer && "../../.venv/Scripts/python.exe" run.py build --fixture --fix
```

---

## The stack, and what it costs

| Layer | Tool | Cost |
|---|---|---|
| Orchestration | Python 3.14 (your existing venv) | free |
| Rendering | Headless Chrome (already installed) | free |
| Video | ffmpeg (already installed) | free |
| Intelligence | Gemini free tier → Claude fallback → Groq Whisper | ~free |
| Research | Tavily (key already in your `.env`) | free tier |
| Publishing | export bundle → Blotato (optional) | $0, or $29/mo |

**Total to run today: $0.** The two reference videos' stack is ~$60–70/month per
client. See `DECISIONS.md` D-00 for why I went the other way and how to switch
back if you prefer their ergonomics.

Everything reads keys from your existing project `.env`. Nothing new was added.

---

## What is verified working

Every one of these was executed, not just written:

- 8 slides rendered at exactly 1080×1350 with correct webfonts
- Compliance gate caught 11 distinct violations on a deliberately bad outline
- Consent register correctly unblocks the patient-media gate when a release exists
- Ad archive is genuinely append-only — SQLite refuses `UPDATE` and `DELETE`
- Outlier miner found 10.8× and 3.9× outliers against correct medians
- A live model call produced a usable, compliant 38.5-second reel script
- Filming packet renders with a working teleprompter
- ffmpeg normalised to 1080×1920, burned captions above the UI rail, cut a cover
- Per-platform captions differentiate correctly across IG / FB / TikTok
- Publish gate refuses to export without a recorded clinical approval
- Part E: pillar transcript → concept → 3 photo-cover variants → mechanical
  self-check → vision review picked a winner → 8 plates → assembled → exported
- Part E pull-quotes come back verbatim from the source transcript, as intended

---

## Before this touches a real client

1. **Fill in the knowledge base.** `shared/clients/northfield-dental/` is a
   fictional practice with a `(555)` phone. The knowledge base caps the quality of
   everything downstream — it is the highest-leverage hour in the build.
2. **Run the voice interview** rather than relying on the static voice block.
3. **Replace the three synthetic test photos** in
   `part-e-pillar-repurposer/assets/photos/`. They are generated gradients, not
   photographs — they exist only so the cover renderer could be verified without
   spending anything. Real photos of the practice go there, with descriptions.
4. **Get the regulation question answered** (`DECISIONS.md` D-13): does an
   individual social post count as an "advertisement" under N.J.A.C. 13:30-6.2?
   It changes the template design.
5. **Name the clinical approver and their turnaround.** The pipeline blocks on
   this gate by design.
6. **Have the patient media release drafted by the client's counsel.**

I am not a lawyer and this encodes my reading of the rules for pipeline purposes.
The compliance layer is a safety net, not legal advice.
