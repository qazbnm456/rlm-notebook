# Invariant 13 — Grounded tasks share one instruction set

**Every citation-grounded RLMTask shares its citation-marker and validate-before-submit
instructions from `instructions.py` — not a hand-copied paragraph per task.** All six compose
the SAME three shared pieces (`CITATION_RULES`, `validate_before_submit_rule(...)`, and
`VERBATIM_COORDINATES` via `chat_language_rule`/`artifact_language_rule`) onto their own
task-specific opening. A wording fix to a shared piece must never be applied to one task's local
copy — there should be no local copy. **The task-specific opening is deliberately NOT unified**:
`AnswerQuestion`'s "ground only in sources" sentence is about a missing *answer*,
`guide.py:_grounded_instructions`' is about an unsupported *claim* — forcing one sentence would
blur one of them. `cli._prepare` is the same "one copy, not five" discipline applied to the
ingestion/notebook setup `ask` and `guide` both need.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
