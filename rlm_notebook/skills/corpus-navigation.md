---
name: corpus-navigation
description: How to read a multi-megabyte corpus blob and build a large answer inside the REPL without exhausting a budget — the measured failure modes, and what each one costs
---

# Working the corpus blob in the REPL

`sources` is ONE string holding every source in the notebook, each block preceded by a
`[[SRC:<id>|<locator>]]` marker. There is no index and no search API: you read it with ordinary
Python — `.find()`, slicing, `enumerate`, a regex when it earns its keep. That is the point of this
architecture, and it is why a step per probe is the NORMAL shape of a run here, not a sign of
floundering.

Everything below is a measured failure from this project's own runs, with what it cost.

## Never build a large result in one code block

**Measured.** A podcast script targeting 60-90 turns, written as a single code block, was cut off by
the per-call generation cap mid-structure. The salvaged fragment parsed as an empty object and the
run failed after about two minutes of model time, all of it wasted.

Build it across turns instead: keep a list in the sandbox, append a few items per turn, and SUBMIT
the finished variable at the end. The same notebook, the same 131,057-character corpus and the same
cap then produced 80 turns with 44 citations in 166 seconds. **Nothing about the budget changed —
only where the work was accumulated.**

(That comparison was run in-process, one tier against the other, so no trace file records it: a
direct `arun` has no `TraceRecorder`. The evidence is the run's own output, not something `traces/`
can be searched for.)

This generalises to any large output, not just scripts: a long summary, a many-item FAQ, a timeline
with dozens of events. If the finished object will not comfortably fit in one reply, it should not
be written in one reply.

## Never print what you are accumulating

Printing your growing result back to yourself puts the whole thing into the next turn's prompt,
which spends the same budget a second time and brings the ceiling above that much closer. Print its
LENGTH to check progress (`len(utterances)`), never its contents.

## A printed span is truncated, and a truncated span costs a whole turn

REPL output is head+tail truncated before it reaches the next prompt (this project sets that cap
deliberately high — 40,000 characters — precisely because these tasks explore by printing spans).
A span that overflows it is a span you have to locate and print AGAIN, which is one more turn
against the step budget for no new information.

So: print the SMALLEST window that answers the question you are asking. Locate first with `.find()`,
then slice a few hundred characters around the hit, rather than printing a whole block to see what
is in it.

## The step budget is generous but not unlimited

**Measured.** A Summary took NINE main steps and about three minutes of model time against a budget
of ten. One more probe would have lost the run. It is 25 now, which is headroom rather than an
invitation — a run that ends because it ran out of steps loses work that was already paid for.

Spend steps on reading you actually need. Reading the same block twice because you did not keep what
you found in a variable is the common way to waste them.

## Markers are coordinates, not text you write

A `[[SRC:...]]` marker exists so a citation can point at a passage. It belongs in a `Citation`, never
in your prose.

**Measured.** One run wrote 20 markers across 19 of a podcast's 47 utterances and filled in ZERO
citations.
The episode read them aloud as "S R C S one", the reader saw what looked like a broken template, and
every passage those markers pointed at was lost — a citation the interface can resolve is the whole
point of copying the coordinate in the first place.
