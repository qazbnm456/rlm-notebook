# Invariant 12 — Source ids are never reassigned

**Extending an existing notebook with `--source` dedupes by origin, and never reassigns an
existing source's id.** `notebook.existing_origins` + `ingest.ingest_new`'s `skip_origins`
(reached through `notebook.ingest_sources_for`) make re-passing the same path/URL a no-op. A
source already cited in a saved `ChatTurn.answer` can never have its id silently repointed at
different text. The GUARANTEE is what matters — id assignment itself belongs to
`append_sources`, which renumbers against the freshly-loaded notebook inside the lock
(invariants 34 and 50).

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
