# Acceptance checklist — personal knowledge system

Status at creation: all implementation checks below are **not run**. These are future release gates, not claimed test results.

Use sanitized fixtures and mocked provider responses for automated tests. Never point a destructive test at the configured personal database. Add a small real-provider smoke test only for paths whose provider integration needs verification. Test PostgreSQL-specific behavior on a disposable PostgreSQL target; SQLite alone does not prove it.

Record command, environment/backend, actual result, and evidence location for each gate in BUILD_STATUS. Screenshots are useful for interactive behavior; persistence and concurrency need database/test evidence too.

## Release A: Search and save

- [ ] **A01 Baseline and restore:** health command performs only reads; record status and index coverage; restore pre-migration backup into an isolated target and compare important counts/content samples.
- [ ] **A02 Migrations:** run additive migrations twice on SQLite and PostgreSQL; existing videos/playlists survive; a failed migration does not leave a falsely advanced schema version.
- [ ] **A03 Profile persistence:** migrate a fixture profile containing custom keys; edit and restart; old local JSON cannot overwrite the new DB record. Missing/corrupt local JSON has a visible safe outcome.
- [ ] **A04 Save persistence:** save a result twice; one item exists; add to two collections; remove one membership; restart; snapshot and personal note remain.
- [ ] **A05 Atomic index replacement:** start with a known working index; simulate provider failure and mid-insert failure separately; old generation remains intact. On success, exactly one complete replacement generation is visible.
- [ ] **A06 Index consistency:** saved auto insight hash matches the searchable generation; manual agenda processing cannot replace auto vectors; stale worker promotion is rejected; missing/partial/unknown-model rows are reported correctly.
- [ ] **A07 Search behavior:** a paraphrase finds relevant insight text; title-only matches do not substitute for content retrieval; ranking scope is enforced before final top-k; filtered PostgreSQL results include a deliberately low-global-rank in-scope hit.
- [ ] **A08 Degraded retrieval:** missing key, quota error, malformed vector, and no-match cases produce distinct truthful states. Lexical fallback works where applicable. Empty results are not falsely described as provider success.
- [ ] **A09 Browser flow:** active navigation reaches Search and Saved; query survives source navigation; source/timestamp links work; form submission is required for provider calls. Test desktop and one narrow viewport.
- [ ] **A10 Download:** the browser receives Markdown, not a path on the server; title/date/source/personal-note content is correct; valid zero-second timestamps are retained; unknown timing has no invented offset.

## Release B: Ask and remember

- [ ] **B01 Transcript reuse:** acquire once, ask twice, restart, ask again; stored text is reused. Provider mocks prove no unintended second transcription. Untimed text remains untimed.
- [ ] **B02 Long-video coverage:** include an answer-bearing passage beyond the old 320,000-character truncation boundary in a synthetic transcript; retrieval can select it without loading the whole transcript into the answer prompt.
- [ ] **B03 Scoped answers:** video chat never cites another video; library chat can combine multiple relevant videos; changing the UI filter cannot mutate an existing conversation's scope silently.
- [ ] **B04 Citations:** reject invented source IDs, malformed source URLs, and direct quotations absent from evidence. Every displayed source link is assembled from validated stored metadata. Manually check claim support, not only citation syntax.
- [ ] **B05 Honest evidence:** test an unsupported question and a disagreement. Answer acknowledges absence/disagreement; saved AI insights are not labeled transcript quotes; personal suggestions are distinguishable from source claims.
- [ ] **B06 Source instructions:** a transcript fixture containing “ignore prior instructions” cannot alter scope, trigger actions, or reveal profile/system content. User preferences guide relevance without making sources authoritative instructions.
- [ ] **B07 Rerun and persistence:** submitting once and rerendering three times generates one normal request; refresh/restart reopens conversation and evidence snapshots. A crash in the response-save window is surfaced as uncertain, not automatically billed again.
- [ ] **B08 Failures and usage:** provider failure leaves a visible retryable attempt; successful replies remain intact; usage totals do not double count request IDs; unpriced usage is labeled unknown.
- [ ] **B09 End-to-end:** search → source → question → inspect citation → save answer → add collection note → restart → download works through the actual UI, without needing a developer-only function call.

## Evidence-quality evaluation

Build a small evaluation set after examining representative real sources. Do not fabricate expected answers from video titles. Keep any private evaluation content outside public Git history.

Use ten cases:

1. An exact tool/person name actually present in a source.
2. A paraphrase of an important idea.
3. A question answerable from two different videos.
4. A comparison with a known disagreement, using fixtures if absent from the real library.
5. A question about a late passage in a long transcript.
6. A playlist-scoped question whose answer would be displaced by global ranking.
7. A question answerable only from an unindexed video before repair.
8. A source without trustworthy timing.
9. An unsupported question.
10. A follow-up question referring to the prior answer.

For each case record: question, scope, expected source/passage, expected behavior, retrieved source IDs, answer, citation support verdict, elapsed time, and pass/fail reason. Designate two as unsupported/negative cases if appropriate and use eight answerable cases for retrieval measurement.

Initial release target: expected evidence in the top five for at least seven of eight answerable cases; all negative cases acknowledge limitations; no fabricated quotations or citation IDs; every substantive factual claim in the inspected answers has supporting evidence. This is a small release check, not proof of general accuracy. Fix systematic errors before adding more features.

## Release C: unattended operation

- [ ] **C01 Atomic jobs:** two worker processes compete; only one claims a job; duplicate enqueue cannot create duplicate active work.
- [ ] **C02 Recovery:** terminate the owning worker, let the lease expire, resume elsewhere; stale owner cannot publish over newer results; a healthy long provider call retains its lease.
- [ ] **C03 Queue drain:** paste another video while processing one; it completes without another manual start; stored stage/progress changes appear in the UI.
- [ ] **C04 Batch resume:** save a mocked/real provider batch ID, restart, resume collection rather than submitting the same batch again.
- [ ] **C05 Independence:** with the browser closed, an authorized scheduled job runs through the independent worker. Record scheduler/host and any PC-on dependency.
- [ ] **C06 Recovery and access:** restore current personal settings, saved items, conversations, transcripts and indexes into an isolated target. Verify actual hosted access restrictions and deployed commit before declaring private personal use ready.

## Performance evidence

Measure warm and cold behavior separately. Record sample count, environment, median and slowest observed result; do not call the maximum of a tiny sample a reliable p95. Capture enough evidence to identify provider latency versus repeated database/render work. Verify new pages do not pull all vectors/transcripts or render every video detail.
