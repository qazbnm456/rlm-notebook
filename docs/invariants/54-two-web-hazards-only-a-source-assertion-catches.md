# Invariant 54 — Two web hazards only a source assertion catches

**Two more web-UI hazards that ONLY a source-tree assertion can catch, both extending invariant
36's reasoning to properties nothing else in this project can see.**

**A tooltip host must not clip its own tooltip.** A `data-tip` tip is an `::after` on its host, so
any clipping `overflow` on that host erases it outright — no console error, no layout shift, just
an affordance that stops existing. `test_no_tooltip_host_clips_its_own_tooltip` harvests tip-bearing
classes from the markup, from `dataset.tip` in `app.js`, and from stylesheet rules already naming
`[data-tip]`. **A HORIZONTAL clip at the left edge is fixable, and removing the tip is the wrong
instinct**: `[data-tip]::after` anchors `right: 0`, so a wide panel on a control at the LEFT edge of
a scroller extends off it — the fix is to anchor into the space the control actually has
(`left: 0; right: auto`).

**An ANCESTOR's clipping overflow does the same thing and is NOT covered** — finding those needs a
DOM this suite does not have. `.col`'s `overflow-y: auto` is exactly such an ancestor (one
non-visible axis forces the other to `auto`), which is why both tab rows anchor their tips to the tab
ROW rather than to a tab, in their EXPANDED state. The collapsed rail deliberately does not: it
anchors to the button and opens LEFTWARD, safe only because `.col-studio.is-collapsed` sets
`overflow: visible`. **`.notebook-menu` is the other such ancestor** (`overflow-y: auto`), so the
picker's running-dot tip needed the same row treatment — worth naming because this is precisely
the case the test above CANNOT see, which makes this file its only record.

**A drag threshold pair must not be inverted.** A two-state toggle driven by one continuous value is
stable only while the OPEN threshold is at or above the CLOSE one; setting `STUDIO_EXPAND_AT` below
`STUDIO_COLLAPSE_AT` to make re-opening cheap turns the gap into a band where every `pointermove`
flips the state. Expanding at exactly `STUDIO_MIN_WIDTH` both satisfies the ordering and opens with
no jump, since at the crossing the pointer and the panel are the same number; the dead band it
creates is covered by stretching the RAIL under the pointer, never by breaking the ordering.

**Applying a width and REMEMBERING one are separate.** Persisting on every `pointermove` made
dragging the panel away overwrite the user's own width with the minimum clamp; a drag commits only
when it ends, and only if it ended open.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
