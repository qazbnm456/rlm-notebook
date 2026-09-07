# Invariant 8 — Corpus blob size cap fails loudly

**`corpus.py` enforces a size cap on the assembled blob and fails loudly, not silently, past
it.** The single-blob-as-REPL-variable design has a real memory ceiling in the pyodide/deno
sandbox; the cap exists to stop a mysteriously failing or slow chat turn later. **Two known
gaps**: `Corpus.blob()` concatenates every source in full BEFORE checking the length, and the
check fires at QUESTION time, not at ingestion (`max_chars` defaults to `None`, and every call
site that passes it is an `ask`/`guide`/`audio` path). Closing either means assembling the blob
on every source add — they are one follow-up, not two.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
