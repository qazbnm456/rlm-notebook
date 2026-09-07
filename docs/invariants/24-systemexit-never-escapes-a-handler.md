# Invariant 24 — SystemExit never escapes a handler

**Every `SystemExit` a request handler can reach is converted to an HTTP 500, rather than
letting it escape.** `cli.py` lets the same `SystemExit` propagate and exit the process, correct
for a one-shot CLI — but in a long-running server an unhandled `SystemExit` inside a request
handler is a crash, not a clean error response. `api._config()` wraps `NotebookConfig.from_env`;
never call `from_env()` directly from a handler.

**The RULE is the invariant, NOT the list of places it currently applies** — that list has to be
re-derived rather than trusted. `config.max_upload_bytes()` has a `SystemExit` of its own
(through `_env_int`), is the first statement of `upload_source`, and fell outside `_config()`'s
coverage precisely because it is deliberately not a `NotebookConfig` field (invariant 30). Any
standalone config reader a handler calls needs the same treatment.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
