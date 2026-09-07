# Invariant 65 — The prompt/skill split

**Every RLM task here carries `rlm_harness.skills` with `discovery="inject"`, and the prompt/skill
split is a rule rather than a preference.** (This is `rlm-harness`'s own mechanism, distinct from the
Claude Code skills a coding agent reads and this task never sees.)

**The split**: a skill is read only if the model chooses to, so anything that CORRUPTS the output when
skipped stays in the PROMPT — grounding, citations, the marker rule, language, the output shape, the
length target. Craft and measured technique are what a skill is for: work done without them is duller
or more expensive, not wrong. A no-disfluencies rule and a good-close rule appear in BOTH, deliberately:
they are must-apply so they cannot leave the prompt, and the skill is where the REASON lives.

**`instructions.ACCUMULATE_LARGE_OUTPUTS` is the one line of that split that had to be fixed.** The
build-across-turns mechanic (invariant 64) is must-apply by its own account — skipping it LOSES the run
— yet it lived in `GeneratePodcastScript`'s prompt only, existing for the other five tasks solely in an
optional skill a model may never read. It is a shared constant composed into all six now, worded
CONDITIONALLY, because a short answer built across turns wastes the step budget just as surely as a long
one written in a single reply loses the run. The podcast keeps its TIER-SPECIFIC pointer and no longer
restates the mechanic. A tripwire asserts all six carry it and the podcast holds exactly one copy.

**`instructions.apply_skills` is the ONE copy of the wiring**, next to `CITATION_RULES` and for the
identical reason: six tasks each calling `load_skills_as_tools` would each own a catalog header, and
the headers would drift. A test forbids `load_skills_as_tools` from appearing in `audio.py`/`guide.py`/
`task.py` at all.

**The catalog is CLOSED (`</available_skills>`) and the MANIFEST decides whether anything is wired at
all.** Without an explicit close, every rule in the task's own prompt reads as though it were inside the
skills element. Gating on the manifest rather than on the directory existing is what stops an empty
directory from adding `read_skill`, whose own description tells the model to pick from a manifest that
would not be there. Pinned in both directions.

**`skills_dir` is a constructor argument defaulting ON**: a test points it at a fixture and `None` turns
it off, which a caller needs because a stale skill is worse than an absent one — and defaulting ON
because a planner that has to be told to consult its own knowledge base will not. `read_skill` resolves
a NAME against the skills discovered at construction, so it cannot read an arbitrary path and never
touches the network; invariants 1 and 14 are about reaching the outside world, which this does not do.

**ONE directory for every task**, because `discover_skills` takes a single directory and does not
recurse, and a catalog line per skill is cheap. Split it when a chat turn is measurably paying to be
told about podcast craft — not before. The files ship inside the wheel for invariant 29's packaging
reason.

**Provenance is part of the craft.** A skill is a durable claim about how to work; an unchecked quote in
one is worse than no skill, because a later reader has no reason to doubt it. Every technique in
`podcast-craft` must be traceable to a source someone actually opened, or to this project's own
measurement.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
