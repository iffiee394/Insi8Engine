# Implementation and review handoff

Main specification: [specs plan](../../specs%20plan.md).
Progress: [BUILD_STATUS.md](BUILD_STATUS.md).
Release gates: [ACCEPTANCE.md](ACCEPTANCE.md).

## Prompt for the implementation model

Copy the following into the model that will do the build:

> Build the personal knowledge system described in `D:\projS\CursorP1\specs plan.md`. First read that file and `docs/knowledge-system/BUILD_STATUS.md` and `ACCEPTANCE.md` in the same repository. Inspect the actual checkout before editing. Execute the first incomplete task and continue through Releases A and B, producing a working application rather than another plan. Show Release A as soon as search, saving, and downloads work, then continue to cited chat and persistent conversations. Keep Streamlit and the existing database/extraction stack. Preserve unrelated files and existing data. Use native Streamlit forms for new interactions, atomic embedding replacement, additive migrations, explicit provenance, and focused tests. Avoid regenerating the whole library. Update BUILD_STATUS with evidence after each task. Distinguish local checks, live provider checks, and hosted verification. If an external dependency blocks one task, record the exact missing dependency and continue independent authorized work. Do not silently expand into Release C or optional integrations; leave a concrete follow-up after the minimum system works. End with what works, what was verified, what remains, and how to run the built system.

This prompt does not select or switch a model automatically. Choose the desired model in the app, then send the prompt. No separate task needs to be created unless desired.

## Quick orientation

- Real active UI: `components/ui_shell.py` and `components/stitch_pages.py`.
- Legacy functions in `app.py` do not prove a capability is reachable.
- Search backend exists; current displayed search only filters video metadata.
- Current Chat tab is disabled.
- Embedding replacement and extraction/index ordering need repair before bulk indexing.
- Profiles currently live in a local JSON file; transcripts are fetched again instead of durably reused.
- Save personal items as snapshots with provenance; mutable chunk indexes are not stable saved-item identities.
- Preserve light reads, lazy detail rendering, caching and PostgreSQL search.

## Minimum completion report

1. Release and task IDs completed, with changed files/commit IDs when available.
2. Exact startup and operational commands that actually exist and were checked.
3. Test results and browser evidence; note any untested PostgreSQL/hosted paths.
4. Current index coverage and exceptions, without exposing private content or keys.
5. Remaining blockers and the next concrete task.

## Prompt for the later stronger-model review

Use after the implementation model has produced working changes:

> Review the implementation of `D:\projS\CursorP1\specs plan.md`. Read `docs/knowledge-system/BUILD_STATUS.md` and `ACCEPTANCE.md`, inspect the real diff and active UI routes, and independently verify material claims. Focus on lost-data risks, profile/transcript durability, atomic indexing, scoped retrieval, unsupported or fabricated citations, duplicate LLM calls on rerun, provider failure handling, cache freshness, and whether the user can complete search → source → save → note → ask → download. Check that saved sources survive reprocessing and that no personal content is sent in URL query parameters. Prioritize concrete defects that block personal use. Separate verified bugs, unverified risks, and optional improvements. Fix issues within the user's authorized scope, using focused tests, and update the status file. Preserve the fast-delivery scope; do not recommend a rewrite without evidence that the existing stack cannot meet the acceptance criteria.
