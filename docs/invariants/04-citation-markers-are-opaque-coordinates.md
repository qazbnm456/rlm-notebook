# Invariant 4 — Citation markers are opaque coordinates

**The corpus blob uses `[[SRC:<id>|<locator>]]` markers, and EVERY citation-grounded task's
instructions teach the model to treat them as opaque and echo them verbatim in a `Citation`.**
That is all SIX: `AnswerQuestion` (`task.py`), the four Notebook Guide tasks (`guide.py`) and
`GeneratePodcastScript` (`audio.py`). `instructions.py`'s `CITATION_RULES` is the ONE copy of
this rule (invariant 13). Without an explicit rule the model has no reason to preserve an ad hoc
marker format across `.find()`/slice operations, and `citations.py` has nothing to verify
against. **Residual risk**: the offline tests drive a scripted LM whose turns are fixed dicts, so
they prove the tool-wiring/SUBMIT chain and nothing about real compliance. One live run observed
a real model doing it. Evidence, not proof — do not restate as a guarantee.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
