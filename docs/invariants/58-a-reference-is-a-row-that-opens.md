# Invariant 58 — A reference is a row that opens

**A reference is a compact ROW that opens, and pointing at either end of a citation lights up the
other.** Rendering every quote as an always-visible `blockquote` let one source cited eight times fill
the whole column. The shape now is number, title, a provenance chip, the use count, TWO clamped lines
of the passage, and everything else behind a click.

**`linkReference` is the reciprocal highlight**, without which a numbered stroke and a numbered row
are two lists a reader has to join up by eye. **`.is-linked` is kept DISJOINT from `.is-focused`** —
hover owns `background`, focus owns `border-color` plus an inset bar — so hovering one reference can
never wipe the focus ring on another. (Both setting `background` at equal specificity is the same
mistake invariant 44 records, made again.)

**`referenceKey`'s separator is `\u001f`, and U+0000 is a trap.** Every lookup is a
`[data-ref-key="…"]` selector, and `CSS.escape` maps U+0000 to U+FFFD by spec — as does the CSS
tokenizer parsing the selector — so a key joined with a NUL can never match ANY element, and the
reciprocal highlight was dead on arrival. Unreachable from the Python suite.

**The run log is a TIMELINE**: one continuous rail with a node per step, the current step pulsing and
shown in full, past steps clamped and expandable. Four per-line left borders read as four unrelated
items; a rail reads as one process advancing. Node colour comes from the step's KIND and "current" is
the animation plus a ring — disjoint properties, because the two rules sit at equal specificity. Each
row shows how long its step took as VISIBLE text, because "where is it stuck" is a question about
durations and a column of absolute stamps makes the reader subtract — visible rather than a tooltip
because `.run-log` is a scroller and a tip anchored inside it is clipped (invariant 54's ancestor
case). The FIRST row measures from the run's start, since that gap is the wait for the model's first
response. `finish()` clears `is-current`, or the last step keeps pulsing while the header says
Finished.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
