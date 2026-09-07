# Invariant 26 — Add sources refuses local paths

**`add_sources` accepts ONLY http(s) URLs, never a local file path — unlike `cli.py`'s
`--source`.** `ingest.ingest_one` treats any non-URL string as a path on the machine running the
process and reads it with no allowlist: reasonable for a CLI whose operator already trusts their
own machine, and an unauthenticated arbitrary-file-read vulnerability the moment the same
function is reachable over an unauthenticated HTTP endpoint. The full attack was reproduced end
to end (`POST {"sources": ["/etc/passwd"]}` read the file and echoed it back through a citation
that passed coordinate verification). If a later slice wants the API to accept files, that needs
its own explicit upload design (invariant 30) — not quietly re-widening this check.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
