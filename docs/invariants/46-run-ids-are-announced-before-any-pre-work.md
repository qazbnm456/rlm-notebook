# Invariant 46 — Run ids are announced before any pre-work

**Every run-taking handler ANNOUNCES its run id (`api._announced`) before any pre-work, not just
before the spawn.** A DIFFERENT and much larger window than the one invariant 29 closed: that one
sits between the exclusive-create and the registration a few lines later, while this one sits
BEFORE the exclusive-create happens at all. Every one of these handlers calls `_resolve_language`
first (invariant 39), a real model round trip in its own subprocess — and on a NEW notebook
`output_language` is by definition unresolved, so that call ALWAYS happens and always outlasts
`_TRACE_FILE_WAIT_GRACE` (5s). The client opens its ticker, waits five seconds for a trace file
that cannot exist yet, and reports the run missing while the request itself succeeds.

`_announced` reuses `_RUN_PROCESSES` rather than adding a second registry, because `stream_run`
already reads it as "is anything still going to write this file". `setdefault`, so an id
`_run_isolated` has already claimed is never downgraded; and the release only removes an id still
at the `None` placeholder, because a spawned run belongs to `_run_isolated`'s own `finally`. A
handler that fails before spawning DOES release, so a failed request can never make a stream wait
forever. `_tail_trace_events` resets its grace counter while the id is announced.

**Applied to all FIVE run-taking handlers, including `/title`, which no client currently
streams** — it accepts `run_id` exactly like the others, and a rule with one silent exception is
the kind that gets rediscovered as a bug report.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
