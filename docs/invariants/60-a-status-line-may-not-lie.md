# Invariant 60 — A status line may not lie

**A status line may not claim something the page is not doing, and a repaint may not delete a run.**

**`runStatus` tracks `awaitingFirstReply` separately from `stepsSeen`.** `setPhase` names a stage the
TRACE CANNOT SEE — the podcast's synthesis half, which runs in-process with no events — so "waiting
for the model's first response" is simply false there, and `paint`'s pre-first-step branch REPLACES
the phrase rather than appending, so a phase set at second 0 is silently gone by second 20. With
chatterbox synthesis running up to fifteen minutes (invariant 43) that was the whole second half, and
it reintroduced the "watched it for seven minutes and read it as a crash" complaint the long-wait tier
was added to fix.

**`.btn:disabled` is styled, not just `.btn-primary:disabled`.** A disabled Stop was pixel-identical
to a live one, so `stoppable: false` produced a control that looked operable and swallowed the click.
Disabling rather than hiding is still right (a control must not vanish out from under a pointer), but
only if disabled LOOKS disabled.

**Only a SUCCESSFUL script run leads to synthesis** — flipping the phase on any terminal kind announces
a stage that will never start, and greys out Stop, until the HTTP error lands.

**A repaint carries the run in flight with it.** `chat:rerender` rebuilding the thread from
`state.turns` alone deletes a running question, its status and its only Stop — invariant 47's rule
broken by a repaint. The pending turn is a closure variable, cleared on completion and on cancel (a
stale one would render the same question twice).

**Stroke numbers are re-stamped across the WHOLE PAGE, not just the surface that changed.**
`collectReferences` orders overview → turns → podcast → guides, so adding one chat turn shifts the
number of every podcast and guide coordinate — and those panels do not re-render. `renumberStrokes`
walks every `.citation[data-ref-key]` and re-stamps from the current order, deliberately instead of
re-rendering: re-rendering the podcast rebuilds its `<audio>` and would interrupt playback, and it is
the NUMBER that went stale. A number that resolves to nothing leaves the attribute ABSENT rather than
setting `"0"`, because `content: attr(data-reference)` renders the literal character.

**A substring assertion is not a behavioural one.** `test_web_assets.py` assertions check a rule's
SUBJECT (its last compound), the ORDER of two branches, the DIRECTION of a comparison, and the literal
mapping expression — because token-appears-somewhere checks walked past six of twelve mutations,
including `i + 1` → `i`, the exact off-by-one the numbering change exists to fix. A duck-typed stand-in
gets the same treatment: every method called on it is checked against the ones it defines.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
