# Invariant 5 — Citations verify coordinates not faithfulness

**`citations.py` verifies coordinate existence only — never content faithfulness.** It confirms
a claimed `source_id` exists and its `locator` resolves to real text in the corpus; it does NOT
confirm the surrounding prose faithfully represents that text. Never let a docstring, log
message, or UI copy imply a stronger guarantee — that gap is exactly the
"grounded-but-not-verified" failure mode found in NotebookLM itself. A citation that fails
coordinate verification is marked unverified, never silently dropped, never silently trusted.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
