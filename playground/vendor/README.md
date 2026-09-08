# Vendored third-party assets

**`driver.js` 1.8.0 — MIT, zero dependencies, ~25KB unminified.**
<https://driverjs.com> · <https://github.com/kamranahmedse/driver.js>

Committed rather than fetched at build time so the build is reproducible offline and the published
page has no third-party origin in its critical path.

## Why this one

The playground's guided script has to spotlight a real control, position a popover next to it, scroll
it into view, and then **let the reader actually click it**. The spotlight/positioning half is fiddly
and thoroughly solved; the wait-for-the-real-action half is ours (`src/director.js` polls
`PG.progress()`, which reads the stage the shim has actually reached).

`driver.js` fits because the highlighted element stays interactive by default, `showButtons: []` plus
`moveNext()` gives fully programmatic control, and `popoverClass` lets the popover be styled with the
application's own custom properties.

**The alternatives were rejected on licence, not features.** Intro.js and Shepherd.js are **AGPL**
unless you buy a commercial licence, and this project is MIT and ships an HTTP API meant to run as a
network service — the same reasoning that removed `pymupdf` (invariant 7). Driver.js is MIT.

Upgrade by re-downloading both files from the same version tag and re-running
`node playground/smoke.mjs`.
