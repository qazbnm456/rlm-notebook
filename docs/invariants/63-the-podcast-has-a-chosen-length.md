# Invariant 63 — The podcast has a chosen length

**The podcast has a LENGTH, chosen at generation time, and the tiers are numbers rather than
adjectives.** `short` / `default` / `long` (about 3-5 / 8-12 / 18-25 minutes, 12-18 / 30-45 / 60-90
turns). Numbers because "aim for a natural episode length given how much the sources contain"
demonstrably did nothing — four measured episodes all landed near three minutes, and the EIGHT-source
notebook produced the shortest.

**Asked at generation time, not on the settings page** — that is the moment a reader has an opinion
about how long they want to listen, and changing your mind afterwards costs a full model run plus
synthesis. It also keeps invariant 41's surface as narrow as it was.

**Both entry points carry it** (`POST /audio`'s `length`, `rlm-notebook audio --length`). Invariant 20
does not require this, but a browser-only capability is the same divergence one level up, and the CLI
is the path with no server at all. The value reaches the model as a SIGNATURE FIELD, for the same
reason `output_language` does.

**`AudioOptions` SUBCLASSES `RunOptions` rather than re-declaring `run_id`** — a copy would silently
skip `/audio` the next time a field is added to the shared body, which is how `run_id` itself was
added. It keeps `extra="forbid"` for invariant 41's reason: pydantic DROPS unknown keys, so
`{"len": "long"}` would otherwise return a `default` episode with nothing indicating the knob was
ignored.

**The CHOICE is remembered in the browser (`localStorage`, key `rlmnb-podcast-length`), deliberately
not on the server.** It is a
per-reader habit, not a notebook property — one person who always wants `long` should not impose it on
a shared notebook. This is the WHERE-IT-LIVES half of invariant 48's split, only that half: the length
IS sent on every generate and DOES reach the prompt, because it changes what the model writes.

**Honest calibration gap**: the turn counts are met and the minute figures are not (`long` produced 80
turns, inside its 60-90 target, but about 14-15 minutes against a stated 18-25 — the minutes were
computed from an assumed ~90 characters per turn and the real figure is ~56). One sample per tier is
not enough to recalibrate on, so both numbers stand.

**Eight `long` episodes later the picture is sharper, and the target is met at its FLOOR.** On a
18,466-character corpus: 70, 70, 65, 65, 61, 60 and one 43; on a 131,057-character one: 80. So
length tracks the CORPUS at least as much as the tier, and six of seven small-corpus runs sat in
the bottom sixth of a 60-90 band rather than in the middle.

**The 43 is explained, and the explanation is a rule that was missing.** That run hit an
`IndexError` at step 9, escalated to the sub-LM for 1m45s, spent two more turns re-parsing the
corpus, and submitted at 43 without ever comparing 43 against 60. Building across turns keeps
the count in a VARIABLE and not in front of the model: a 70-turn run and the 43-turn run BOTH
printed their count in the step before validating, and neither compared it to anything.
`GeneratePodcastScript` now says to count against the target before validating and, when short,
to go back to the SOURCES rather than forward to the close — which is deliberately a different
sentence from the filler rule beside it, since that one is about a corpus with nothing left in
it and this one is about material still uncovered. Prompt-only, invariant 4's hedge.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
