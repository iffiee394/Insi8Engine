# InsightEngine playbook

How the system behaves, and every setting you can change. Dashboard: https://web-mu-five-61.vercel.app

## The flow in one line

YouTube playlist → **sync** lists new videos → each video becomes **one job in Queue** → the worker processes jobs **one at a time** → insights appear in the Library under that playlist's tab.

## Rules

### Playlists
1. Every playlist has its own tab in the Library, named after the playlist. Adding a playlist creates the tab immediately.
2. Each playlist has a **type** (Videos or Podcasts) and a **focus**. Insights are written from *your profile + the playlist's focus + the transcript*. Podcasts also get guest and topic research.
3. A playlist must be **Public or Unlisted** on YouTube. Private playlists can't be read.
4. "Pull in new videos on sync" off = the playlist is ignored by syncs. Its existing videos stay in the Library.

### Syncing
5. The worker syncs **every 8 hours** by default (3 times a day). Change it on **Playlists → Automatic sync** (2, 4, 8, 12, 24 hours, or off).
6. **Sync playlists now** (Queue or Playlists page) runs a sync immediately.
7. A sync queues **every** new video from every syncing playlist, oldest first. Nothing is skipped or capped.
8. A video that already has a job waiting is never queued twice.

### Queue order and pausing
9. Syncs run before videos. Videos run oldest-first, one at a time.
10. **Pause** a playlist in Queue (or tick "Pause processing" on its card) and its videos stay waiting while every other playlist goes first. **Resume** puts them back in line. Pausing doesn't stop a video that's already running.
11. A single video added from **Add** goes in Queue under "Single videos" unless you pick a playlist for it.

### When something fails
12. Each step has a fallback, tried in order:
    - **Transcript:** YouTube captions → Gemini reading the video from its link → downloading the audio (Gemini, then Groq Whisper).
    - **Writing insights:** Gemini key 1 → key 2 → key 3 → key 4 → **Claude, only if every Gemini key is unavailable**.
13. A key that hits its free daily quota **rests until midnight Pacific** (Google's reset) and is skipped until then. A key Google rejects is skipped for 6 hours and flagged on the Usage page.
14. A job that still fails retries by itself after **2 min, 10 min, 1 h, 6 h, 24 h**. If the failure is "all keys out of quota", it waits for the quota reset instead.
15. After that, a failed video is retried automatically **every 12 hours, up to 10 runs**.
16. Private or removed videos are **not** retried; the error says a manual fix is needed.
17. Errors always name each step and its real reason. To get past a blocked video yourself: open it → **Reprocess → Paste transcript**.

### Per-video control
18. **Reprocess → Default agenda** reruns with your profile and the playlist's focus.
19. **Reprocess → Custom agenda** adds a one-off instruction for that video on top of your profile.
20. **Reprocess → Paste transcript** skips YouTube entirely.

## Settings you can change

| What | Where | Default |
|---|---|---|
| Your interests, writing style, what to skip | My profile | — |
| A playlist's type and focus | Playlists → the playlist's card | Videos, no focus |
| Whether a playlist syncs | Playlists → "Pull in new videos on sync" | On |
| Hold a playlist's videos back | Queue → Pause, or Playlists → "Pause processing" | Off |
| How often syncs run | Playlists → Automatic sync | Every 8 hours |
| Gemini keys and their order | Worker secrets `GEMINI_API_KEY`, `GEMINI_API_KEY_2` … `_9` (see below) | 4 keys |
| Whether Claude may be used at all | Worker env `FALLBACK_TO_ANTHROPIC` in `fly.toml` (`false` = never) | `true` (last resort) |
| Gemini models, best first | Worker env `GEMINI_CHAT_MODEL`, `GEMINI_FALLBACK_MODELS` | `gemini-flash-latest`, then `gemini-2.5-flash`, `gemini-flash-lite-latest` |
| Retry timing | `RETRY_DELAYS_MIN` and `HEAL_*` in `Vercel Remake/worker/worker.py` | as in rules 14–15 |

Add or replace a Gemini key (from a new Google account or project, so it gets its own quota):

```bash
flyctl secrets set -a insightengine-worker GEMINI_API_KEY_5=your-new-key
```

The worker restarts and the key shows on the Usage page.

## Where things run

| Piece | Host | Deploy |
|---|---|---|
| Dashboard | Vercel project `web` | `cd "Vercel Remake/web" && npx vercel deploy --prod` |
| API | Vercel project `api` | `cd "Vercel Remake/api" && npx vercel deploy --prod` |
| Worker (queue, syncs, retries) | Fly.io app `insightengine-worker` | `flyctl deploy` from the repo root |
| Data | Supabase Postgres | — |
