# Invariant 47 — Every long run is visible and stoppable

**Every long-running action shows that it is running and offers a way to STOP it, and no action
starts without an explicit press.** All four surfaces — chat, the chat overview, each Guide kind,
the podcast — mount the same `runStatus` component (pulsing dot, live action, ticking elapsed,
Stop).

**Stop cancels by RUN ID** (`POST /notebooks/{id}/runs/{run_id}/cancel`), because `/overview`
fires TWO runs and invariant 23's `_ACTIVE_RUNS` holds one slot per NOTEBOOK — the notebook-scoped
`/cancel` reaches only whichever registered last, so the user asks to stop and the other run keeps
burning a model call to completion. `_RUN_PROCESSES` is already run-id-keyed and already holds the
process, so cancelling precisely is a lookup, not a new registry. It `killpg`s the whole group
(invariant 22) and reports an announced-but-unspawned id honestly rather than as a 404 reading
"already finished".

**Selecting a Studio tab does not start a run.** It used to fire a real RLM call on click, so
browsing the four kinds to see what they were cost four model runs with no way to tell which click
had committed them. Each tab shows what it is and offers a button.

**A superseded generation SAYS SO.** A silent `return` in a staleness guard is indistinguishable
from a hang, and it is the exact path that produces "pressed generate, it said Finished, then
nothing ever appeared".

**Panels say what they are for.** "Podcast", not "Audio Overview" (users did not know what it
was), and Studio/Podcast/Notes each carry ONE visible sentence, with per-control detail in
`data-tip` hovers — this project's own tooltip, not the native `title=`, whose ~1s delay made the
help feel disconnected from the hover effect accompanying it. Notes says what a note is *for*,
since neither the section nor the button explained that promotion is what makes it citable.

`tests/test_web_assets.py` pins all of it as source-tree assertions, since there is no JS test
runner.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
