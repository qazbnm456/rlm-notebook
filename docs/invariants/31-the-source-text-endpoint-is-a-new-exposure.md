# Invariant 31 — The source text endpoint is a new exposure

**`GET /notebooks/{id}/sources/{source_id}` returns a source's FULL text — a materially
different exposure than every other endpoint except the trace pair (invariant 29).** Before it,
no caller could read more of a source than a citation's short `quote`. It reuses
`corpus.Corpus.get(source_id)` — the SAME lookup `citations.py` already performs on every
request — rather than a second hand-rolled scan. Invariant 25's posture covers this in spirit
(the model already has the whole corpus), but the SURFACE is new and worth its own line.

**The Sources row is the click target for the source-text viewer** (`app.js`'s
`showSourceViewer(source.id, null, null)`), and its fetch carries a staleness guard —
`sourceViewerAbort`, a module-level `AbortController` — so a slow first response cannot repopulate
a panel the reader has moved on from. Don't reintroduce that gap in a future source-detail fetch
path.

**SUPERSEDED, recorded because the earlier shape is still described in older entries**: this
invariant used to name a per-answer citation LIST whose rows opened the viewer, with a secondary
per-row `⌁ trace` icon. That markup is gone — invariant 58's References panel replaced it, a
citation stroke now calls `focusReference`, and `showCitationTurn`/`_shownKey`/`.citation-row` exist
nowhere in `app.js`. `style.css` still carries the dead `.citation-list` rules; removing them is a
loose end, not a behaviour change.

**Known and explicitly NOT fixed here**: `Corpus.add()`'s duplicate-id dedup guard is dead code —
nothing in the real ingestion path calls it.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
