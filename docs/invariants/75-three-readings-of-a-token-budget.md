# Invariant 75 — Three readings of a token budget

**A trace's token budget has THREE readings, and the third is the one that matters
    (`trajectory.budget_summary`, the Trajectory drawer's budget note).** `run_end.budgets`/`usage`
    arrived with rlm-harness 1.10.0, so a trace written before the upgrade carries neither field.
    `budget_summary` returns `None` for those and the drawer says **NOT RECORDED** — never a zero,
    never a clean bill of health. Reading an absent field as "nothing was truncated" turns a corpus
    boundary into a property of the code, and the same rule governs any later analysis: split on
    `run_start.rlm_harness` and treat absent as UNMEASURED.

    **Truncation is `completion_tokens` reaching the APPLIED cap** — the kit's own recommended
    reading, and NOT what dspy's `_check_truncation` does (it branches on `finish_reason ==
    "length"` and never compares token counts, so it is not the authority for this rule even though
    an earlier draft cited it as one). The cap is read off the LM the run actually used rather than
    off `NotebookConfig` — an injected `main_lm` is used verbatim, so the configured cap can be one
    no call ever saw. With no cap reported, `truncated` stays False rather than guessing from the
    magnitude of the number. `usage` is per ATTEMPT, so the peak is taken ACROSS retries: a retry is
    exactly the run whose fatal call matters most.

    **Three different exhaustions are reported, not one.** The token cap, the iteration caps
    (`max_iterations`/`max_llm_calls`) and `max_output_chars` are independent, and a reader
    diagnosing "it stopped early" has to be able to tell them apart. `iterations.dropped` says dspy
    rejected the budget kwargs outright and every cap reverted to its own default — without
    surfacing it, the three numbers beside it read as applied when they were not.

    **A proximity reading is offered as a NUMBER, and that is a reversal.** The kit maintainer's
    first measurement said the used/cap ratio is never an early warning because the distribution has
    no gradient; that corpus ran at twice the cap its model needed, and transposed to this project's
    16384 it filled the band that was empty (about one run in six). **That transposition was to the
    cap of the time; invariant 59 has since raised it to 32768, which is the cap the maintainer's own
    corpus ran at and found no gradient in** — so on this project's current setting the two
    invariants argue opposite ways and neither has enough of its own data to settle it. Measured
    here, at 32768: two capped calls in 54, at ratios 1.0 and 0.275, with the band between intact.
    So the ratio is shown, with the
    honest status: a shape to expect, not a figure confirmed on this project's own runs. See
    `CHANGELOG.md` for the correction and what survived it — the MECHANISM (a truncated code cell is
    a `SyntaxError` the planner's next turn usually repairs, a truncated final answer ends the run)
    carries to any cap; the DISTRIBUTION does not.

See `CHANGELOG.md` for the incidents, measurements and superseded drafts behind every invariant above.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
