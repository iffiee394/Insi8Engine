# Future plan — what this is, and what comes later

Updated: 2026-09-15.

## What the system is for

In the owner's words:

> The whole purpose of it is to have the playlist that I like. I add videos to
> it. They use daily Gemini quota or Anthropic credits and keep insights in the
> dashboard, and I can see them whenever I want. I just want this much
> functionality, and I want this to be fast.

And where it is heading:

> This is going to be a knowledge system where I will either keep a directory of
> a lot of YouTubers so that I have their insights, or I will manually add the
> videos and then watch their insights.

So the core loop, and the only thing the current UI is optimised for, is:

**curate a playlist → add a video → spend quota extracting insights → read those
insights in the library, whenever.**

Everything else is deliberately out of the way until that loop is fast and
dependable.

## What the interface does now

- The app opens on **Library**. No search box in the way of the content.
- Videos are a scannable list, not a dropdown, so the library can be browsed.
- Insights render **open** — no click per topic. Timestamps are plain links.
- Supporting material (resources, technical error detail) stays folded.
- Navigation is **Library · Playlists · + Add video**, with Queue and Settings
  under More. Five destinations, down from nine.

## Deferred, not deleted

Semantic search, Saved items and library Chat are complete and tested. They are
**kept intact** and will be built on later. They are simply not in the
navigation.

| Feature | Lives in | Still reachable |
|---|---|---|
| Semantic search | `components/future_pages.py` → `render_search_page` | `?page=search` |
| Saved items / collections | `components/future_pages.py` → `render_saved_page` | `?page=saved` |
| Library chat (cited) | `components/future_pages.py` → `render_chat_page` | `?page=chat` |
| Search backend | `search.py` (`search_insights_response`) | unchanged |
| Chat backend | `knowledge_chat.py` | unchanged |
| Storage for saved/chat | `knowledge_store.py`, schema v4 | unchanged |

Their tests still run as part of the suite (`tests/test_knowledge_*.py`).

**Embedding generation is still on during ingest.** It costs one extra API call
per video and keeps the index current, so semantic search can be switched on
later without re-processing the whole library. Turning it off would save a
little quota now at the cost of a full re-index later.

To put a feature back: add it to `render_native_nav` in
`components/knowledge_pages.py`. The routes already resolve.

## Later — Stage 0: make search fast (when search returns)

Measured on the live system, one search costs **~4.5 s**:

| Stage | Time | Share |
|---|---|---|
| Gemini query embedding (API) | 3,350 ms | 75% |
| Database round-trip (Singapore) | 430 ms | 10% |
| *Postgres actually executing* | *2.6 ms* | *0.06%* |

The database is not the problem, and neither is Streamlit. Two fixes:

1. **Cache query embeddings.** Repeat questions become instant.
2. **Hybrid search.** Try Postgres full-text first (~10 ms, no API call) and
   only fall back to embeddings for genuinely conceptual questions. Most
   searches would never touch the API.

Also outstanding, from `knowledge_health.py`:

- **19 of 66 videos have empty structured insights** — in the library, invisible
  to search, contributing nothing. They need reprocessing, which costs quota.
- **All 47 indexed videos are `unknown_model`.** Mixing embedding models
  silently degrades results. Stamp provenance, then rebuild mismatches.

## Later — Stage 1: make ingestion scale

Today ingestion runs *inside* the web app: `background_jobs.py` spawns
`subprocess.Popen(poll.py)`. Streamlit Cloud sleeps the container, so work in
flight is abandoned, and one video at a time (2–5 min each) means 1,000 videos
is 33–83 hours.

A directory of channels posting daily needs:

1. **A `jobs` table** — the durable to-do list. Enqueueing is a row insert.
2. **A worker process** that is not a website — a small always-on container
   (Railway / Fly, ~$5/month) that drains the queue and cannot be put to sleep.
3. **Claim / lease / retry** — a worker owns a job for N minutes; failures back
   off and retry themselves instead of sitting failed.
4. **A quota budget** — stop before the daily Gemini limit rather than failing a
   batch against it. (This is what stranded `JpaK3F7fLHE`.)
5. **Concurrency** — 3–5 videos at once turns 83 hours into ~16.
6. **A channel watcher** — scheduled check of the followed YouTubers that
   enqueues new uploads. This is what makes it a knowledge *system* rather than
   something fed by hand.

Streamlit keeps working unchanged throughout; it only reads the database.

**Once ingestion lives outside the web process, the frontend becomes a free
choice** — FastAPI over the existing Python plus a Next.js UI, or stay on
Streamlit. Triggers worth acting on: wanting it on a phone, wanting to share it
with someone, or the UI fighting back.

## Capacity notes

- Storage is ~93 KB/video today → ~0.9 GB at 10,000 videos. Supabase's free tier
  (0.5 GB) runs out around **~5,500 videos**; Pro is 8 GB.
- `transcript_chunks` is barely populated, so expect ~150 KB/video once durable
  transcripts cover the library.
- Extraction costs ~$0.004/video — 10,000 videos ≈ $40. **Rate limits, not
  money, are the binding constraint.**
- pgvector currently seq-scans 426 rows (correct at this size); the HNSW index
  is already in place for when it matters.
