# Invariant 36 — Hidden toggles need a matching hidden rule

**`rlm_notebook/web/`'s `hidden`-toggled elements must never be given an author `display` rule
without a matching `[hidden]` rule, and `tests/test_web_assets.py` fails the build if one is.**
`hidden` works through the UA stylesheet's `[hidden] { display: none }`, which ANY author
`display` declaration outranks — author styles beat UA styles regardless of specificity. This
shipped broken twice: `.modal-overlay { display: flex }` left an overlay permanently visible
whose `inset: 0` swallowed every click on the page, and `.ticker-detail` left the reasoning log
permanently expanded. Invisible to every other layer this project can test — the Python suite
never renders, and a unit test of the close handler would pass against the broken stylesheet,
because the JS was always correct. Hence a SOURCE-TREE assertion, keyed on CSS CLASSES (which
markup and JS spell the same way) and asserting up front that it can still see every known
instance, so a future extraction failure fails the build instead of passing vacuously. The same
file pins invariant 29's "never `innerHTML` with an interpolated string" (and its `outerHTML`/
`insertAdjacentHTML`/`document.write` siblings).

**A visible author `display` on a hidden-toggled class IS allowed — with a guard that OUTRANKS
it**, i.e. a `[hidden]` rule whose selector is one token LONGER, so it wins on specificity
regardless of source order. This tripwire compares by class NAME and would accept a guard that
loses the cascade; `test_the_podcast_transcript_is_not_capped_by_a_fixed_height` computes
specificity and is the one that actually checks it.

**A flex column stretches its children to full width, and that is a DEFAULT, not a choice** —
only what should span may span.

**SUPERSEDED**: this invariant used to require that a re-click on an already-open citation detail
COLLAPSE it (`showCitationTurn`'s `_shownKey`) rather than blank to "Loading…" and re-fetch an
identical payload, keyed on WHICH citation including its `quote` — because text and web sources emit
a single block with locator `"whole"`, so every citation into one such source shares the
`source_id|locator` pair. None of that markup survives; invariant 58's References panel replaced it.
**The keying lesson does transfer** and is why `referenceKey` includes `quote` today.

**Known gap**: this project has no JavaScript test runner at all (zero-build vanilla JS, by
design), so interactive UI state has no test seam. A source-tree assertion catches the
stylesheet class of bug; it cannot catch a toggle that stops toggling.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
