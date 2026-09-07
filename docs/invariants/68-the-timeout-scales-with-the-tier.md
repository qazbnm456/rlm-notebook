# Invariant 68 — The timeout scales with the tier

**A wall-clock backstop scales with the work that was asked for (`schema.PODCAST_TIMEOUT_FACTOR`).** A
`long` episode 502'd at the 300s default having written three trace events, and on the same notebook an
ordinary chat answer took 77s across 4-5 planner turns — so a tier asking for 60-90 utterances
ACCUMULATED ACROSS TURNS (invariant 64) could not have fitted, and invariant 63 shipped a tier unable to
finish under its own default. The backstop exists to catch a RUNAWAY, not to cap work a reader
explicitly requested; scaling per request keeps a runaway CHAT turn bounded at the value it always had,
and an operator's `RN_RUN_TIMEOUT_SECONDS` still moves every tier because the factor multiplies it. The
table lives NEXT TO the tier literal, and a tripwire asserts every tier has one and that the factors
never decrease.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
