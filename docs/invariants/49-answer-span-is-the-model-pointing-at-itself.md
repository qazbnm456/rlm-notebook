# Invariant 49 — Answer span is the model pointing at itself

**`Citation.answer_span` is the model pointing at its OWN prose, and it exists because locating the
highlight by `quote` stopped being possible.** The highlighter stroke used to find its span with
`answer.indexOf(citation.quote)`, which works only while the answer and the source share a
language. Invariant 39 made the prose follow the READER while the quote stays in the SOURCE's
words, so the two never share a substring and NO span could be found again. Not a bug in either
invariant — it is what 39 costs, paid here rather than by weakening the verbatim-quote rule.

**`citations.locate_answer_spans` applies invariant 5's coordinate-existence discipline to the
model's own text.** A span that does not occur VERBATIM in the prose is dropped; the citation
survives. Losing a highlight costs a reader one affordance, highlighting the wrong sentence tells
them a claim is supported when it is not. Matching is EXACT with one allowance — leading and
trailing whitespace — and deliberately no case folding, punctuation normalisation or fuzzy match:
each buys a few more highlights at the price of sometimes underlining prose the citation does not
support. It verifies WHERE, never WHETHER.

**`_citation_responses` takes the prose it must check against as a REQUIRED argument**, and every
call site passes the string that artifact actually renders (a chat answer, an FAQ item's `answer`,
a timeline event's `description`, a podcast utterance's `text`, the overview's `text`). It had a
`""` default that SKIPPED validation when empty — a fail-OPEN default under a docstring promising
the opposite — now simply not expressible. Passing the WRONG text is still silent (the spans stop
being found and the page renders with no strokes), which is what the dedicated test pins.

`instructions.CITATION_RULES` teaches it as the deliberate MIRROR of `quote`: `quote` is in the
source's language, `answer_span` is in the model's. (NOT `VERBATIM_COORDINATES`, which does not
mention `answer_span` at all.) Same residual-risk hedge as invariants 4 and 11 — whether the model
emits a usable span at all is a compliance claim, and the offline suite drives a scripted LM.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
