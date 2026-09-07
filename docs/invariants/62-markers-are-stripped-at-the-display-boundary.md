# Invariant 62 — Markers are stripped at the display boundary

**A `[[SRC:...]]` marker is a coordinate for the interface and must never reach the reader — stripped
at the DISPLAY boundary, not before persisting.** Invariant 4 tells the model to echo a marker into a
`Citation`; it says nothing about ALSO writing one into the sentence being composed, which a real run
did. **On the way OUT, so nothing stored is rewritten and every notebook already on disk is fixed with
no migration** — rewriting on the way in would make an old notebook and a new one disagree about their
own history.

**`api._prose` is the ONE place, and the same value goes to `_citation_responses`.** Handing the raw
text to one and the stripped text to the other is silent in both directions: the markers vanish from
screen and every `answer_span` stops being locatable, so every stroke disappears — invariant 49's
failure mode one layer down. `locate_answer_spans` strips the SPAN too, because a span copied out of
the model's own prose can carry a marker with it.

**Removing a marker leaves a HOLE, and closing it is done at the hole — never globally.** A marker
between a word and its punctuation leaves `claim . Next`, cosmetic on screen and audible in synthesis.
A space-before-punctuation rule over the whole string is wrong twice: it normalises text that never had
a marker (French typographic spacing), and because `strip_markers` early-returns on a marker-free
string, the prose and the `answer_span` would then get DIFFERENT normalisation and the span would stop
matching. `_close_gap` is a replacement function on the marker match itself, so it can only ever edit
the whitespace the marker sat between.

The prompt gained the rule as well. A display-layer strip is a NET, not a reason to stop asking: the
same residual-risk hedge as invariants 4 and 11 applies to whether the model complies, and the net is
what makes non-compliance cost nothing.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
