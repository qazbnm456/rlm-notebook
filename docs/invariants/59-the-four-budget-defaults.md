# Invariant 59 — The four budget defaults

**The four budget defaults are each a decision, and `max_tokens` is the one that silently kills a
run.** `RLMConfig`'s own defaults are 10 / 8192 / 10,000 / 1; this project ships
`max_iterations=25`, `max_tokens=32768`, `max_output_chars=40000`, `max_retries=1`.

**`max_tokens: 32768` — a per-call GENERATION cap, and a trap for a reasoning model**, whose
chain-of-thought is billed against a cap it never appears in, so the reply arrives cut mid-JSON and
fails to parse; `max_retries=1` then makes that terminal, since a second attempt hits the same
ceiling. It is NOT only the planner's: `runtime.configure` builds ONE `lm_kwargs` and hands it to both
`dspy.LM(cfg.main_model)` and `dspy.LM(cfg.sub_model)`. On the `claude-agent-sdk/` subscription path
(invariant 35) it is ENTIRELY INERT — `ClaudeAgentLM` tolerates and ignores sampling kwargs — so it is
visible in the trace and applied to nothing, the same shape invariant 7 records for `ocr_provider`.

**Raised 16384 -> 32768 against a DISTRIBUTION, never against one truncation.** A live
`GeneratePodcastScript` call hit 16384 exactly and came back `Invalid Python syntax`, cut
mid-code, costing an iteration — and it was invariant 59's case rather than 64's, because the
model was ALREADY batching 5-20 utterances per step and the call left only 407 characters of
reasoning and 995 of code in the trace. One truncation is not a size, so the size came from
a sibling project's 3,683 calls on the same model under a 32768 cap: median 1,621, p90 6,993, p99
15,030, at cap 0.71%, and **the band from 60% to 90% of that cap is EMPTY**. Legitimate long
turns end below ~16k — the 13-16k bucket is exactly what this project's old cap was cutting —
and everything that reaches the cap is a runaway no cap saves. So the doubling buys the
legitimate tail and a second one buys nothing. **Do not raise it again without a distribution.**

Their measured cost: a run WITH a cap hit is ~2.5x the completion tokens and ~2.5x the wall
clock of one without, which at 0.71% is noise — and the same runaways under the old cap cost
half each and failed the same runs anyway. **One thing does NOT transfer**: their cap hits are
single turns, while `max_iterations` here is 25 and the budgets MULTIPLY, so
`run_timeout_seconds` (scaled per podcast tier, invariant 68) is the only bound on a looping
runaway.

**`max_output_chars: 40000`** bounds how much of a REPL OUTPUT reaches the planner's prompt, which
matters for invariant 8's reason: every task explores a corpus blob by `.find()`/slicing and prints
the spans, so a truncated output is a span that has to be fetched again — a wasted iteration.

**`max_iterations: 25`, and 10 was about to bind** — an 8-source notebook's Summary took NINE main
steps. The failure modes are not symmetric: exhausting the budget loses a run already paid for, unused
headroom costs nothing since the loop ends when the model submits, and a runaway is bounded by
`run_timeout_seconds`, which is a wall-clock bound the step budget cannot be.

**`max_retries: 1` is PINNED, and stays pinned.** A whole-run retry rarely fixes a PERSISTENT coercion
failure, and it burns the budget a second time while writing a second copy of the same failure into
the trace. The counter-argument — that a turn-0 parse failure is transient and cheap to re-run — is
wrong, because the second attempt hits the same token ceiling and fails identically. **One DIVERGENCE
from the siblings, which hardcode the 1: this project reads `RN_MAX_RETRIES`.** The default does not
move, so raising it is a deliberate choice — and the budgets MULTIPLY: `RN_MAX_RETRIES=5` against
`max_iterations=25` is up to 125 iterations. The API path has `run_timeout_seconds` as a wall-clock
backstop; **the CLI path has none at all**.

**`worker._describe` carries the ROOT CAUSE across the process boundary.** `RLMTaskError: Failed to
produce a valid 'script' after 1 attempts` names the symptom; the chain names the cause, and the cause
was being discarded at exactly the boundary where a person starts reading.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
