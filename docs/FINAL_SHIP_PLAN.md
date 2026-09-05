# Final Ship Plan — YouTube Insight Agent

> **Goal:** Public, shareable deploy (Railway + Docker) with BYO API keys, live queue, and a polished UI.
> **Strategy:** Option A (Streamlit stays). Option B (Next.js) deferred until after validation.

---

## North star

A dark, queue-first insight dashboard where each user brings their own keys, watches videos process step-by-step, and jumps from insights to exact YouTube moments — demoable in ~30 seconds without reading a README.

---

## Locked decisions

| Decision | Choice |
|----------|--------|
| Deploy target | Railway + Docker |
| Database (v0) | SQLite + persistent volume on `/app/data` |
| Database (later) | Postgres when ~10–20+ active users |
| Auth | Required before public URL |
| API keys | BYO, encrypted in DB (`APP_ENCRYPTION_KEY` on server) |
| Queue | Dedicated `processing_queue` table + `current_step` |
| Anonymous demo | Seeded fixtures, read-only, CTA to register |
| Pipeline | V4 unchanged — additive platform + UI layers only |
| Key loading | `contextvars` user config (avoid threading keys through every signature) |

---

## Phase 1 — Product & UI (local, single-user)

**Goal:** Screen-recordable product quality before auth.

| Track | Scope | Status |
|-------|--------|--------|
| **UI plan** | Layout, cards, hierarchy, `config.toml` theme, queue-first dashboard | 🔜 User to provide plan |
| **Interactions** | Playlist/status filters, sort, bulk enqueue, export, re-process | 🔜 |
| **Search v2** | Sidebar search + type filter, min score, jump-to-video, optional playlist scope | 🔜 Partial (v1 semantic search done) |
| **Polish** | Empty/loading states, failed-video actions, mobile sanity | 🔜 |

**Already done (BUILD_SPEC):** timestamps, timeline, Markdown export, semantic search v1, demo seed, config validator, smart errors, `config.py`.

**Exit criteria:** Record full flow — select videos → process → see progress → insights + timestamps + export + search.

---

## Phase 2 — Platform (Option A core)

**Goal:** Safe for internet strangers.

- Auth (`streamlit-authenticator`) + `user_id` on `videos`, `playlists`, `embeddings`
- `user_settings` + Fernet encryption + Settings page (test connection per key)
- Per-user config via contextvars; worker loads keys from queue row’s `user_id`
- `processing_queue` table; pipeline updates `current_step`
- Queue tab (`st.fragment(run_every=3)`): Now processing / Up next / Recently done

**Exit criteria:** Two accounts fully isolated; each uses own keys; queue processes serially with live steps.

See also: [OPTION_A_FAST_SHIP_PLAN.md](OPTION_A_FAST_SHIP_PLAN.md) (full detail).

---

## Phase 3 — Deploy & launch

- Dockerfile (Python 3.11-slim, ffmpeg, Streamlit `0.0.0.0:8501`)
- Railway: repo, volume, `APP_ENCRYPTION_KEY`
- Demo mode for logged-out visitors
- README + 20–30s GIF (enqueue → queue → timestamp click)
- Public GitHub repo, pinned

---

## Deferred (post-launch)

Postgres migration, managed tier / Stripe, Next.js rebuild, Notion, knowledge graph, newsletter, keyboard shortcuts.

---

## Feature vs UI order (recommended)

When the user provides UI plan + feature list:

1. **UI shell first** — layout, theme, sidebar order, cards, empty states (no new backend).
2. **Interactions on new shell** — filters, dropdowns, buttons wired to existing DB/actions.
3. **Search v2 + queue UX mock** — UI against current poll/worker; real `processing_queue` in Phase 2.
4. **Phase 2 platform** — auth, BYO keys, queue table, settings page.
5. **Deploy**.

Small backend-only fixes (bugs, error messages) can ship anytime between steps.

---

## Open inputs (from user)

- [ ] UI overhaul plan (layout, components, screenshots/wireframes)
- [ ] Search v2 must-haves confirmed
- [ ] Launch mode: public register / demo-only / password gate for friends
- [ ] Any additional buttons, dropdowns, bulk actions

---

## Related docs

| Doc | Purpose |
|-----|---------|
| [PROJECT_GUIDE.md](../PROJECT_GUIDE.md) | Current architecture & features |
| [PRODUCTION_PLAN.md](PRODUCTION_PLAN.md) | Tier 1–3 feature rationale |
| [BUILD_SPEC.md](BUILD_SPEC.md) | Implemented production tasks |
| Option A source | `OPTION_A_FAST_SHIP_PLAN.md` (user Downloads — copy to repo when updated) |
