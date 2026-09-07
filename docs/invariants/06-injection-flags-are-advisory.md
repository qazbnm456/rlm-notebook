# Invariant 6 — Injection flags are advisory

**`injection_scan.py`'s flags are deterministic and additive — they gate nothing.** A flagged
source's content still reaches the model and its answer still returns; the flag is metadata
attached to the SOURCE at ingestion (`ingest.with_injection_flags`). `AskResponse` carries no
flags, so an ANSWER never shows one — but the SOURCE does, on every surface: `cli.py` prints it,
`api.py` emits `flags` on each source in `NotebookResponse` and on `SourceDetailResponse`, and
`app.js` renders an amber `⚠` chip in the Sources list plus a row in the source viewer. An earlier
wording read the `AskResponse` premise as covering the whole API and concluded the flag was
CLI-only, which the Sources list has contradicted on screen for as long as it has existed. It is a
transparency mechanism; do not wire it to refuse a run. Its patterns trade recall for precision
on purpose (a paper *discussing* prompt injection can trip it) — an acceptable false-positive
rate for a flag nobody is forced to act on — **don't over-tighten it into false negatives chasing
a clean read.**

**A flag is a SENTENCE addressed to a person, never a regex**, because since these flags gate
nothing, whether a human can act on them is their entire value. `_INSTRUCTION_PATTERNS` pairs
every pattern with its description, and the role-label pattern is anchored to its own LINE
(`^\s*(system|assistant|user)\s*:\s*`, MULTILINE) rather than matching mid-sentence prose.

**Both apply to sources ingested FROM NOW ON only.** `scan_source` runs once and the result is
persisted into `Source.flags`; nothing re-scans. No migration, deliberately — re-scanning on
every `GET` is expensive, and rewriting on load would silently edit stored notebooks.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
