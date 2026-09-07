# Invariant 20 — Shared ingestion module for both entry points

**`ingest.py`/`notebook.py` (`is_url`/`ingest_one`/`ingest_new`, `load_or_create`,
`ingest_sources_for`/`append_sources`, `mutate_notebook`) are shared by `cli.py` AND `api.py` —
neither entry point depends on the other.** Extracted here once both needed the identical
"get me a notebook, ingest new sources into it" step, so a fix to source-handling can't land on
only one of the two by accident. Don't reach into `cli.py` from `api.py` (or the reverse) — if
both need it, it belongs in a shared, entry-point-agnostic module.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
