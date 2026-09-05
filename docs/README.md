# Documentation index

| Document | Purpose |
|----------|---------|
| [../PROJECT_GUIDE.md](../PROJECT_GUIDE.md) | Full reference — architecture, features, pricing, troubleshooting (current V4 state) |
| [PRODUCTION_PLAN.md](PRODUCTION_PLAN.md) | **What & why** — tiers, priorities, GitHub packaging, what not to do yet |
| [BUILD_SPEC.md](BUILD_SPEC.md) | **How** — step-by-step tasks for Cursor (acceptance criteria, code samples) |

## Build order (from PRODUCTION_PLAN)

| Status | Task |
|--------|------|
| ✅ Done | **Task 0** — `config.py` + OS-agnostic paths |
| ✅ Done | **Task 1** — Timestamp-linked insights |
| ✅ Done | **Task 2** — Visual timeline |
| ✅ Done | **Task 3** — Markdown export |
| ✅ Done | **Task 4** — Semantic search |
| ✅ Done | **Task 5** — Demo seed (`python seed_demo.py`) |
| ✅ Done | **Task 6** — Config validator UI |
| ✅ Done | **Task 7** — Smart error states |
| ✅ Done | **Task 8** — Logging cleanup (core modules) |
| 🔜 Now | **Phase 1 UI** — [UI_BUILD_SPEC.md](UI_BUILD_SPEC.md) + [STITCH_DESIGN_BRIEF.md](STITCH_DESIGN_BRIEF.md) |
| 🔜 Then | **Phase 2** — Auth, BYO keys, queue table |
| 🔜 Then | **Phase 3** — Docker, Railway, launch |

### New files

- `config.py`, `errors.py`, `export.py`, `search.py`, `logutil.py`
- `components/timeline.py`, `seed_demo.py`, `export_fixtures.py`
- `data/fixtures/demo_example.json`

V4 pipeline is **unchanged** — all work is additive.
