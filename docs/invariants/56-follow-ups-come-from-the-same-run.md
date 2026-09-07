# Invariant 56 — Follow ups come from the same run

**`Answer.follow_ups` comes from the SAME run that produced the answer — never a second model call —
and is not verified against anything.** The model already holds the corpus and its own answer in
context when it submits, so asking for two or three next questions in the same SUBMIT costs nothing;
a separate `dspy.Predict` per turn would be a real call per answer for the same words. Deliberately
NOT citation-grounded: a question is a prompt, not a claim, so invariant 5 has nothing to check. The
instruction still requires each be answerable from `sources` — a PROMPT-COMPLIANCE claim carrying the
same hedge as invariants 4 and 11, spelled out rather than referred to: the offline suite drives a
scripted LM whose turns are fixed dicts, so it can demonstrate none of it. Optional and defaulting to
empty, so turns persisted before the field existed still load.

**The two labels are deliberately NOT unified**: the overview's row says "Start with" and a turn's
says "Ask next", sharing one renderer (`starterQuestionRow`). The overview's appears before any
conversation exists, where "ask next" would be asking the reader to continue something they have not
begun.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
