# Invariant 1 — No network tool in chat REPL

**No fetch/network tool is ever registered on the chat task's `RLMTask(tools=…)`.**
`parsers/web.py`'s fetcher is called exactly once, host-side, during ingestion — never handed to
the model at question-answering time. A source's own content is untrusted (invariant 6); if a
fetch tool were reachable from the REPL, an instruction hidden in that content could steer the
model into exfiltrating notebook contents to an attacker-controlled URL, and `rlm_harness`'s
SSRF guard (`is_safe_url`) blocks internal/loopback/metadata targets only — it cannot block a
legitimate-looking external domain. "Fetch one more page on request" would be a separate,
explicitly user-confirmed, non-agentic action — not a tool the model decides to call.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
