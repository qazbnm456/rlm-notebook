# Invariant 11 — History is context not a source

**`history` (prior conversation turns) is context only — it is never itself a source of facts
or citations.** `AnswerQuestion.instructions` says so, and nothing in `citations.py`
special-cases a citation just because a similar one appeared earlier: every citation is verified
fresh against the CURRENT `sources` blob. A past answer being wrong, or a source having been
removed since, must not be inherited into a new one. **Residual risk, same class as invariant
4's**: one live turn showed a real model using history to resolve a referent while still
re-deriving its citation from `sources`. Evidence, not proof.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
