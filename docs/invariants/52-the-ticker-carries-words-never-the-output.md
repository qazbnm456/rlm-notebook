# Invariant 52 — The ticker carries words never the output

**The live ticker's event shape is `{kind, primary, detail, meta}` and it carries the model's own
words — but never the step's OUTPUT.** `_translate_trace_event` used to emit one fixed sentence per
event type and throw the payload away. `summary` is kept as `primary` + `detail` so a consumer
written against the older one-line shape keeps working, and the synthesized terminal event for an
orphaned run comes from `_orphaned_run_event` rather than a hand-written literal — two copies had
already drifted back to the older form.

**A `tool_call` NAMES the tool and says what it did.** The branch emitted the fixed word
`Tool` with the payload discarded — the exact shape this function was rewritten to stop doing —
and it survived because this project emitted no `tool_call` events at all until the validator
started recording, so nobody read it. Its `meta` also read a `status` key `record_tool_call`
never writes, so it was always `None`. A user watching a real run reported the consequence: the
status line said "4 tools, 18 steps" while the validator was rejecting a draft, and nothing on
screen said so. Now: the tool name is `primary`, the FIRST SENTENCE of the verdict (or the named
argument) is `detail`, and a rejection sets `meta`. **First sentence, because a verdict is
written for the MODEL** — it names the offenders and then explains what to do and which
exception applies, so sending it whole filled the live line with two sentences of advice
addressed to somebody else and truncated the rest. The full text stays in the trace and in the
drawer's detail pane. **The kind stays `tool` even for a rejection** — `failed` is
TERMINAL and `app.js`'s `TERMINAL_KINDS` would close the live log while the run carried on.

**`detail` is the model's own prose in the main case, and not ONLY that**: a `main_step` with no
`reasoning` falls back to the step's CODE, and a `result` event carries its output dict's KEY NAMES.
**`detail` CAN therefore quote ingested source text** — the model's prose and the step's code both
routinely repeat what they just read — which is the same materially-different exposure invariant 29
records for the trace endpoints, on an API with no authentication (invariant 25). Do not read the
next sentence as a promise that no source text reaches this stream; it is narrower than that.
The step's `output` is where whole corpus spans land and is deliberately NOT streamed; its SIZE is
reported instead, which is the part that tells a reader whether a step did much. `_DETAIL_CHARS`
bounds the rest, because this goes down an SSE stream once per step. The full text stays in the
trace file the citation-turn lookup already reads.

**`run_end` with `ok=False` is `kind: "failed"`, not `"done"`** — any client's terminal-state check
has to accept BOTH, or a failed run's ticker never closes.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
