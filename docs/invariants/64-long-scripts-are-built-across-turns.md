# Invariant 64 — Long scripts are built across turns

**A `long` script is built across REPL turns, and that is what the sandbox is FOR.** Written as one
code block it was TRUNCATED by the per-call generation cap mid-structure and the run failed;
accumulated in a list across turns — printing only its LENGTH, never its contents — the same corpus and
the same cap produced 80 utterances with 44 citations, with **nothing about the budget changed**. This
is the second time a truncation could have been answered by raising `max_tokens` and the first time it
should not have been: invariant 59's raise was correct because the PLANNER's reasoning did not fit, and
this is an OUTPUT that should never have been one reply. **If a finished object will not comfortably
fit in one reply, it must not be written in one reply** — recorded in the `corpus-navigation` skill
(named because it is one of exactly two shipped, and invariant 65's split decides what belongs in a
skill rather than a prompt), and as `instructions.ACCUMULATE_LARGE_OUTPUTS` (invariant 65).

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
