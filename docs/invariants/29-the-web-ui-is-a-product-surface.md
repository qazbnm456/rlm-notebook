# Invariant 29 — The web UI is a product surface

**The web UI (`rlm_notebook/web/`) is a real end-user product surface, not a replay-only trace
console like the sibling projects' `studio/`s.** A persistent, multi-notebook, multi-turn
knowledge workspace is structurally different, and the divergence is a recorded design decision.
Zero-build vanilla HTML/CSS/JS — no framework, no build step.

**Assets live under `rlm_notebook/web/`, NOT a top-level `web/`** — a top-level directory has no
entry in `pyproject.toml`'s wheel `packages` list and would silently vanish from an installed
wheel.

**`app.js` builds every DOM node that could carry model- or source-derived content via
`createElement`/`textContent`/`element.title` — NEVER `innerHTML` with an interpolated string**,
because a citation's `source_id`/`locator`/`quote` could echo attacker-supplied text from a
prompt-injected source (invariant 6: flags are advisory, not a filter).

**`POST /notebooks/{id}/audio` is split into TWO host-side steps.** `GeneratePodcastScript` runs
in the same isolated subprocess `ask`/`guide` use (the only step cancellable via `/cancel`); TTS
synthesis then runs AFTER that subprocess returns, IN-PROCESS, dispatched through
`asyncio.to_thread` specifically because `EdgeTTSProvider.synthesize()` internally calls
`asyncio.run(...)`, which raises if invoked from a running event loop. **Accepted limitation**:
by the time synthesis begins, `_run_isolated`'s `finally` has cleared this notebook's
`_ACTIVE_RUNS` entry, so a stuck synthesis call has no `killpg`-equivalent to reach it.

Synthesis writes through a temp file whose `finally` covers BOTH the success and the
synthesis-FAILURE path — the `try` has to start before `synthesize()`, or a `TTSError` raised
from inside it leaks the file. **`↓ Download` slugs its filename from the (model-authored)
notebook title**, since `download` is an attribute the browser turns into a path component, and
**its extension follows the SERVED file**, because a provider may emit WAV (invariant 43) and
naming it `.mp3` unconditionally would mislabel half of them. That second rule has no other home:
an audit once found it listed among invariant 43's "handled" consequences when it was not. The
GENERATE response is JSON with base64-encoded audio, never a raw binary body, so error handling stays
uniform with every other endpoint. **`GET .../audio/file` is the exception and has to be**: it is a
`FileResponse`, because that is what lets the browser range-request an episode instead of
re-downloading it to seek (invariant 42). The rule is about the endpoint that can FAIL after
spending a model run, not about the one that serves a file already on disk.

**The live reasoning-trace stream rests on five rules:**

- **The client picks the run id, never the server** (`RunOptions.run_id`, a shared optional body
  field on `ask`/`guide`/`audio`), so the caller can open `GET .../runs/{run_id}/stream` before
  or alongside the request that will populate it; a server-generated id never reaches a client
  mid-run. `_derive_run_id` sanitizes the token through the SAME whitelist `notebook.slug()`
  uses and always prefixes it with `notebook_id` — never the client's raw value alone.
- **`_run_isolated` exclusively creates `traces/{run_id}.jsonl` before spawning anything**
  (`O_CREAT|O_EXCL|O_WRONLY`, a 409 on `FileExistsError`). Not optional hardening:
  `TraceRecorder`'s own lock is process-local and gives ZERO cross-process serialization, so two
  concurrent requests on one run id would have two worker subprocesses append interleaved,
  duplicate-`step_id` events to one file. If the create succeeds but the spawn then fails, the
  still-empty file is unlinked — otherwise a failed spawn permanently occupies that run id and
  every legitimate retry gets a false 409.
- **`_RUN_PROCESSES` (run-id-keyed) is a SEPARATE map from `_ACTIVE_RUNS` (notebook-id-keyed),
  deliberately not reused**, because invariant 23's single slot per notebook means a second
  concurrent request overwrites the first's entry, which would make the FIRST run's stream
  falsely conclude it was cancelled. A run is RESERVED in it (value `None`) before being spawned
  and ANNOUNCED before the handler's pre-work (invariant 46): an ABSENT key means
  finished/cancelled/never-started, `None` means the subprocess is still being spawned, and
  `stream_run` reads exactly that pair.
- **Citation-to-turn linking is a separate lookup endpoint**
  (`GET .../runs/{run_id}/citation-turn?source_id=&locator=`), not a reuse of the live stream. It
  searches a trace's events in step order for the first whose ENTIRE serialized payload contains
  the literal marker — the whole payload rather than a fixed field list, because a `sub_call`
  event's real keys are nothing like a `main_step`'s and a citation appearing only in a sub-LM
  escalation would silently 404. `stream_run` and `citation_turn` both check the run id belongs
  to the notebook, comparing `slug(notebook_id)` (invariant 38).
- **Every artifact that can be re-opened PERSISTS the run id that produced it** —
  `ChatTurn.run_id`, `Overview.run_id` (invariant 38) and `Podcast.run_id` (invariant 42), all
  optional and backward-compatible. Without it a reload has no way back to the trace, so both
  affordances above (and invariant 70's persisted "⌁ N steps" pill) exist only until the page is
  refreshed. This is the storage contract those features rest on, which is why it is stated here
  rather than left implicit in three schema fields.

**Known limitations**: a missing trace degrades that ONE affordance and never the rest of the
page (retention is bounded by invariant 34); the marker search is a HEURISTIC — finding the
marker proves the REPL saw it, never that this occurrence is what the model relied on, the same
"coordinate, not faithfulness" limit as invariant 5; and a `sub_call` event's `input` is
truncated to 4000 characters upstream. **The trace endpoints are a MATERIALLY DIFFERENT exposure
than metadata-only responses** — a trace can contain full ingested source text — inheriting
invariant 25's no-auth posture as a sharper version of the same accepted risk.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
