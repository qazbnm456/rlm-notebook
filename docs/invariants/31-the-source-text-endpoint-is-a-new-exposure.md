# Invariant 31 — The source text endpoint is a new exposure

**`GET /notebooks/{id}/sources/{source_id}` returns a source's FULL text — a materially
different exposure than every other endpoint except the trace pair (invariant 29).** Before it,
no caller could read more of a source than a citation's short `quote`. It reuses
`corpus.Corpus.get(source_id)` — the SAME lookup `citations.py` already performs on every
request — rather than a second hand-rolled scan. Invariant 25's posture covers this in spirit
(the model already has the whole corpus), but the SURFACE is new and worth its own line.

**The web UI's citation-list row is the primary click target for the source-text viewer**, with
the reasoning-trace view demoted to a secondary per-row `⌁ trace` icon that calls
`event.stopPropagation()` so the two never double-fire. `.citation-row` is clickable regardless
of whether the `quote` matched inline in the answer text — before this, an inline-match miss had
NO way to open anything. Both citation-detail fetch paths carry a staleness guard
(`sourceViewerAbort`, an `AbortController`; and a monotonic token on `detailArea` for
`showCitationTurn`, a plain GET with no browser-level cleanup to invoke). Don't reintroduce
either gap in a future citation-detail fetch path.

**Known and explicitly NOT fixed here**: `Corpus.add()`'s duplicate-id dedup guard is dead code —
nothing in the real ingestion path calls it.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
