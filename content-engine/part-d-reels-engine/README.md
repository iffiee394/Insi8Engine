# Part D — Capture-First Reels Engine

AI does everything except the face.

Outlier mining → transcribe → extract **structure only** → rewrite from the
client's own knowledge → compliance gate → filming-day packet → **90 minutes of
human filming** → ffmpeg post → clinical sign-off → per-platform captions →
export → archive.

Scripted for **sends per reach** — the DM share — because that is the signal
Instagram weights most heavily for Reels.

---

## Why a human is still in the middle

A local dental practice converts on trust and proximity. In 2026, 40% of
consumers say heavy AI use decreases their trust in a brand (double the previous
year), visibly-AI content tested four times more likely to reduce trust than
raise it, and most people identify AI video on sight. Reference video 1 reaches
the same conclusion independently: *"the more human you can make something look
in an automated fashion, the better it's going to perform."*

So the filming block is not a limitation of the system. It is the product.

---

## Commands

```bash
python run.py mine --csv fixtures/sample_posts.csv    # offline
python run.py script --fixture                        # offline structure
```

| Command | What it does |
|---|---|
| `run.py mine` | Scrape the watchlist, flag 3×+ outliers, queue them as ideas |
| `run.py mine --csv <file>` | Mine from a manual export instead |
| `run.py mine --multiple 4` | Raise the outlier threshold |
| `run.py list` | Idea queue and scripts |
| `run.py script --next` | Transcribe, extract structure, rewrite one |
| `run.py script --all --limit 14` | Build a whole filming block |
| `run.py script --fixture` | Offline; skips the transcribe/structure calls |
| `run.py packet` | Build the filming-day packet |
| `run.py post --video raw.mp4 --slug <slug>` | Normalise, burn captions, cut a cover |
| `run.py approve --slug <slug> --approver "Dr. X"` | Clinical sign-off |
| `run.py export --slug <slug>` | Per-platform captions + upload bundle |
| `run.py publish --slug <slug> --platform instagram tiktok` | Archive record |

---

## Files

| File | Role |
|---|---|
| `mine.py` | Outlier detection. **Median** baseline, pluggable source adapters |
| `transcribe.py` | youtube-transcript-api (free) → yt-dlp + Groq Whisper |
| `scripts.py` | Structure extraction, rewrite, similarity guard |
| `shotlist.py` | The filming-day packet — self-contained HTML with teleprompter |
| `post.py` | ffmpeg: 1080×1920, burned captions, cover frame |
| `watchlist/` | Creator watchlist (replace the example) |

---

## The structure/content separation

The most important thing in this lane.

`extract_structure()` reads the source transcript and returns an **abstract beat
sheet** — what each beat *does* for the viewer and *how*, with no phrasing and no
claims carried over.

`rewrite_to_client()` is then called with the beat sheet and the client's
knowledge base, and **never receives the transcript at all**. The model cannot
copy what it was not shown.

`similarity_guard()` proves it, flagging any shared 7-word run between output and
source. It should always come back empty; it exists to catch the day someone
wires the transcript in by accident.

This solves three problems at once: copyright, carrying over another creator's
unverified clinical claims, and Instagram's suppression of unoriginal content.

Structures that depend on the creator's face, fame, a trend audio or a stunt are
marked `transferable: false` and rejected — a licensed practice cannot repeat
them under the "dignified manner" rule anyway.

---

## Outlier maths

Median, not mean. One runaway hit drags a mean upward and then hides every
subsequent outlier behind it. Requires at least 6 posts before computing a
baseline, because a 3× multiple on four data points is noise.

Verified on the fixture: medians of 19,800 and 40,500, correctly flagging 10.8×
and 3.9× outliers.

### Source adapters

| Adapter | Cost | Good for |
|---|---|---|
| `ytdlp` | free | YouTube/Shorts (excellent), TikTok (works), Instagram (needs cookies) |
| `apify` | ~$1.00/1k results | Instagram at volume. Set `APIFY_TOKEN`. **Written, untested** |
| `csv` | free | Manual exports, fixtures |

**Honest limitation:** the free path does not reliably scrape Instagram. If your
watchlist is Instagram-first, budget for Apify.

---

## The filming-day packet

The real failure mode of this lane is not technical — it is that filming day does
not happen, or overruns. So the packet is built to be used on a phone or tablet
propped next to the camera:

- shots **grouped by setup**, so the room is moved once per group
- target duration per shot and a running total against the 90-minute block
- **teleprompter mode** with large type, arrow-key navigation
- a red consent warning on any shot with a patient in frame
- checkboxes that remember what has been filmed
- prints cleanly if the dentist prefers paper

One self-contained HTML file. No server, no app, works offline.

---

## Post-production

`post.py` does the four things that should never eat a human hour:

1. **normalise** — cover-fit to 1080×1920, no letterboxing, audio levelled
2. **captions** — styled `.ass` burned in, `margin_v=420` to clear the platform UI
3. **cover** — a still frame for the Reel cover
4. **duration probe**

Captions are burned in rather than left to platform auto-captions: much of the
audience watches muted, auto-captions cannot be proofread, and a misheard
clinical word is a compliance problem.

*Windows note, already handled:* ffmpeg's `subtitles` filter cannot take a path
with a drive letter, so calls run with `cwd` set and use bare filenames.

---

## Where it breaks

- **The client flakes on filming day** and the lane goes dark. Put the block in
  the contract as a named deliverable on a fixed monthly date, and always bank a
  surplus so one missed session does not empty the queue.
- **Instagram scraping is fragile.** Adapters are swappable for this reason.
- **`script --all` is the expensive command** — two model calls per idea.
- **Duration drift.** Estimated at 2.6 words/second; check against real takes.
