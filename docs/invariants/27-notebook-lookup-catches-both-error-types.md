# Invariant 27 — Notebook lookup catches both error types

**Every endpoint that resolves a notebook by id catches BOTH `pydantic.ValidationError` (a
corrupted notebook file → 409) AND `ValueError` (an id `notebook.slug` reduces to an empty
token → 400) — not just the first.** Without it, an unhandled `ValueError` escapes as a raw 500.
The original worked example (`"!!!"`) is SUPERSEDED by invariant 10; only a genuinely empty or
whitespace-only id still takes this arm. `cancel` is unaffected (it never loads a notebook).
Route path-traversal payloads do NOT reach this code path — Starlette's default path converter
refuses to match a literal `/` inside one `{notebook_id}` segment — but that is a FRAMEWORK
default, not this project's code; re-check it if the route ever changes shape.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
