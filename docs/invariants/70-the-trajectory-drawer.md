# Invariant 70 — The trajectory drawer

**The Trajectory drawer (`trajectory.py` + `GET .../runs/{run_id}/trajectory`) is where a run's
reasoning lives — NOT the chat bubble.** The inline step log put the planner's own prose inside the
answer. Full parity with the sibling project's own drawer: turn nav, a tool timeline whose segment width
is proportional to real elapsed time, a detail pane, search, and a replay transport that dwells on each
turn for the time it REALLY took divided by the speed.

**The decomposition is server-side and the two clocks are kept apart.** `iterations` (planner turns)
carries per-turn timing ONLY when the trace was live-stamped; an older trace flushed every `main_step`
at finalize, so their timestamps cluster and durations are OMITTED rather than invented. `timeline`
(tool and sub-LM calls) is always real. Conflating them would produce confident numbers that are not
measurements.

**Server-side because a trace can hold full ingested source text** (invariant 29): the per-field caps
here are what keep a multi-megabyte REPL output from being shipped to a page that renders a preview of
it. This endpoint is the FIFTH such surface under invariant 25's posture.

**It reads a trace that is still being written**, which is the point for a run taking minutes: a torn
final line means the writer is mid-flush and is skipped, not raised on. The read happens in a thread.

**A `validate_*` call surfaces its VERDICT**, because on a failed run that is the single most useful
fact in the whole trace: exactly what the model was told to fix, and how many rounds it took.

**It only reaches the trace because the validator RECORDS it, and for a long time it did not.**
`rlm_harness.record_tool_call` is OPT-IN — every tool wrapper calls it or the event does not
exist — and `make_grounded_validator`'s `validate` never did. So no `tool_call` event was ever
written by this project, the timeline was empty on EVERY run, and the empty state said "this
run called no tools" while the turn's own code pane showed `validate_podcastscript(...)` three
lines away. Upstream's `read_skill` records; ours simply never did, and the drawer had no way
to know the difference. **It also closed a stated measurement limitation**: a live A/B of
invariant 66's script check could not say whether the validator had FIRED, and that caveat was
attached to every number in it.

The JSON handed to the validator is the whole ARTIFACT, so its LENGTH is recorded and its TEXT
is not — invariant 52's rule for the ticker applied to the drawer. The verdict is bounded and
is the model's own rejection message: paths, coordinates and character names, never source text.

**A duration the TOOL measured beats the strip's GAP, and a turn's FIRST call keeps no gap at
all.** `_tool_entry` sized every segment by the distance from the previous timeline event —
the best available answer for a call that reports nothing, the wrong one for a call that does,
since it charges the tool with everything since. The first run after the validator started
recording drew a 3.3-second segment for a call it had measured at 1.9ms.

The gap remains the fallback, and a non-numeric report does not become one — but for the FIRST
call of a turn even the fallback is dropped to `None`, because that gap reaches back through
the model generating the whole code cell and the number would be mostly model time wearing a
tool's name. a sibling project measured 287 of 972 calls first-in-turn: a THIRD of every duration
it displayed. `duration_measured` is what keeps a self-timed call out of that rule.

**A run can legitimately have NO model calls, and the drawer says so correctly.** `dspy.LM`
defaults to `cache=True`, so a run with an unchanged corpus, language and tier replays the
previous one from cache: same turns, same reasoning text, same validator failures, zero calls,
3.4s against 263.6s. `budget_summary` then reports a cap with no usage and the per-turn timing
is omitted because the steps span 0.09s in total — both notes true, and both easy to misread as the
drawer being broken.

**A REGENERATE bypasses that cache (`RunOptions.fresh`); a first generate does not.** A button
labelled Regenerate that returns what you already had is a UI that lies, and the drawer then
reports the honest emptiness above as if the panel were broken. A FIRST generate keeps the
cache, where a hit is a free correct answer — so the flag is the EXISTENCE of the artifact
(`Boolean(state.overview)`, `Boolean(state.podcast)`, and `AskRequest.regenerate` for chat),
never a constant.

It rides **alongside** `kwargs` down to the worker, never inside them: `kwargs` are the task's
`arun()` arguments and anything added there reaches the MODEL as a signature field (invariant
39). The worker switches it GLOBALLY with `dspy.configure_cache(...)` before `setup`, which is
correct because a worker handles exactly one run — process-global IS run-scoped — and because
rebuilding the LMs instead would mean a second construction of `runtime.configure`'s
`lm_kwargs` that would drift from upstream's.

**Four of the five run-taking handlers take it; `/title` is exempt and that is stated rather
than left as an absence.** `suggest_title` never overwrites an existing title, so it is
idempotent by construction and there is no "regenerate" of it to bypass anything for. `guide`
accepts it from the shared body although no client sends one today — the field is on
`RunOptions`, and a handler that silently ignored it would be invariant 46's "a rule with one
silent exception" in the API surface rather than in the UI. **The CLI has no way to bypass the
cache at all**, which is a real gap and not a decision.

**The replay draws its PROGRESS through the stop it is dwelling on.** The transport waits for
the time a turn really took divided by the speed, and without a bar that is indistinguishable
from a frozen panel — the same complaint the run ticker's long-wait tier exists to answer, in a
panel with no other sign of life. It NAMES the stop as well as drawing the bar, because a bar
alone says how long is left and not what it is waiting for. The transition is RESTARTED per
stop — cleared, snapped to zero, forced reflow, run — since without the reflow the browser
coalesces both writes into one recalculation and the bar jumps to 100% with no animation.

**The timing note and the budget note share ONE ROW, and stay TWO ELEMENTS.** Stacked, they
were two full-width rows of one short sentence each pushing the strip down for no information.
Merging the TEXT would have cost the thing the note colours exist for: the budget note turns
red on a truncation and the timing note never does. The row carries the two guards its own
`display: flex` creates — a `[hidden]` pairing (invariant 36, pre-emptive as `.btn`'s is) and a
`:has()` rule that removes it entirely when both notes are hidden, or its margins hold 11px of
blank above the strip, which is the space the change exists to reclaim.

**Interface copy is built from the BOOLEAN, not from the server's sentence.** `timing_note` is English
prose written in Python, and rendering it verbatim put an English line in the middle of a Chinese
drawer. The server says WHICH case holds; the interface says it in the reader's language (invariant 48).

**There are TWO "⌁ N steps" affordances and moving one is not moving both.** `runStatus` owns the LIVE
log during a run; `renderTickerAffordance` owns the PERSISTED pill under a finished artifact — and it is
the one a reader presses most, because most of the time the run is over. Both open the drawer.
`.ticker-detail` was one of invariant 36's tripwire sentinels and is replaced by `.traj-drawer` rather
than dropped, with the extraction gaining a route for a BARE `hidden` attribute in the markup, which all
four existing routes were blind to.

**A tool segment offers a way BACK to the turn that called it**, on every ATTRIBUTED segment
rather than only a failed one — "why was this called" is the same question whether or not it
worked — and absent where nothing is attributed, since a button reading "open turn null" is
worse than none (the sibling shipped that and said so). The head already names the turn; naming
one a reader then has to find in the nav by eye is the two-lists-to-correlate problem the
strip's own turn marks exist to remove.

**A timeline segment is sized `flex: <normalised duration> 0 <floor>px`, and all three parts fix
another's failure**: `flex-grow` against the strip's TOTAL divides it into unreadable slivers,
while a fixed `width` leaves a one-call run stranded beside empty space. Grow makes a short run
fill the strip; the basis is a floor so a fast call stays legible and the strip SCROLLS rather
than squashing.

**The NORMALISATION is the third part and it is not cosmetic.** CSS distributes free space in
proportion to the grow values and STOPS AT THEIR SUM, so a run whose calls are all milliseconds
— floored to 0.01 each — summed to 0.06 and left **94% of the strip empty**. Dividing each
weight by the total makes the sum exactly 1 while leaving every ratio between segments
untouched.

**A turn mark is labelled `T<index + 1>`.** The trace data is 0-indexed and every other surface
counts from one, so the strip said `T2` for the call the nav rail and the detail head both
called turn 3. Reported from a screenshot; the fix is display-only and the data stays 0-based. **A segment's label is the
TARGET, not the family** — the family, offset and owning turn live in the detail pane, which is where
clicking a segment lands anyway. A `data-tip` on a `.seg` is doomed twice over: the segment clips
itself, and `.traj-timeline` is an `overflow-x` ancestor (invariant 54's uncovered case). **A
fixed-height box with `overflow: hidden` needs its line-heights DECLARED** — a 72px segment stacking
icon, label and duration at the browser's ~1.5 default measures 74.3px and slices the MIDDLE line
through its letterforms; a test recomputes the sum from the stylesheet.

**`traces.run_meta` records what the run was configured with AND what it was asked to do**, for
BOTH entry points — it moved out of `worker.py` when the CLI gained `--trace`, because two
copies would drift on the next field added (invariant 20). It lives in `traces.py`, which is
already about what a trace file IS and stays free of `dspy`/`rlm_harness` so importing it costs
a CLI invocation nothing. It records model names,
budgets, the corpus SIZE, and every short scalar input by name (the question, the resolved language, the
requested podcast tier). Each answers "why did it produce that" and none is derivable afterwards from a
notebook that has since moved on. **The corpus TEXT never goes in** — its size does, invariant 52's
reasoning — and neither do `api_key` or `base_url`.

**An empty panel reads as broken, so the empty STATE names which empty it is**, and the branch stays
reachable regardless of old traces being cleared: `_run_isolated` reserves the trace file exclusively
BEFORE spawning and `run_trajectory` stops at a torn final line, so a run opened in its first moments,
one whose spawn failed, or one killed instantly has a real file with zero events.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
