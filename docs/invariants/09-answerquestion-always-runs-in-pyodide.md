# Invariant 9 — AnswerQuestion always runs in pyodide

**`AnswerQuestion` always runs in the `pyodide` sandbox; `NotebookConfig.from_env` refuses any
other `RN_INTERPRETER` value rather than silently overriding it.** An operator who set
`RN_INTERPRETER=local` believes something about this run that would not be true if the kit
quietly corrected it; refusal makes the misconfiguration visible.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
