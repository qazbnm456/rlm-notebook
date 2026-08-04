# Changelog

All notable changes to `rlm-notebook` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`rlm-notebook` is an RLM-driven research notebook, built on
[`rlm-harness`](https://github.com/qazbnm456/rlm-harness): paste in sources of any kind, ask grounded
questions with verifiable citations, and get a distilled research artifact out.

## [Unreleased]

- **First slice: ingestion (text/web/PDF with local hybrid OCR) + citation-grounded chat, driven
  from a CLI.** No session persistence, no API/UI, no Notebook Guide, no Audio Overview yet — see
  CLAUDE.md's Scope note. Everything below is what this slice actually contains, and the design
  calls that shaped it.

  **All sources become one blob, not a vector index.** `corpus.py` concatenates every ingested
  source into a single string tagged with `[[SRC:<id>|<locator>]]` markers and hands the whole thing
  to `AnswerQuestion` as one signature field — the model explores it in the sandboxed REPL
  (`.find()`/slicing) rather than through embedding similarity search. This is rlm-harness's native
  mechanic (an RLM signature field *is* a REPL variable), not a new indexing layer; a vector-search
  fallback for corpora too large for one blob is deferred until real usage shows the size cap
  (invariant 8) actually binds.

  **No fetch/network tool is reachable at question-answering time.** Early designs considered
  reusing `rlm_harness.tools.fetch.make_fetch_tool` as a live tool so the model could pull in more
  context on demand; adversarial review found this turns a prompt-injected source into a live data
  exfiltration path, since the SSRF guard only blocks internal targets, not legitimate-looking
  external ones. Ingestion-time fetching is host-side and one-shot instead — see invariant 1. A
  second, independent review then found that the ingestion-time fetch itself had a gap: the
  default `urllib` opener follows a redirect's `Location` header unconditionally, so an
  initially-safe URL could 302 to an internal/metadata target with no further check. Fixed with a
  redirect handler that re-validates every hop (invariant 2), verified against a real redirect
  target before landing.

  **Citation verification is coordinate-only, and says so.** `citations.py` confirms a `Citation`'s
  `source_id`/`locator` resolves to real corpus text; it does not attempt to verify the model's
  prose is faithful to that text, and no docstring or UI copy should imply otherwise (invariant 5).
  `AnswerQuestion` also validates its own draft against `Answer`'s schema in-REPL, before SUBMIT,
  via `rlm_harness.tools.validation.make_schema_validator` — chosen over a post-hoc whole-run retry
  because rlm-harness's own retry policy defaults to `max_retries=1` specifically because a full RLM
  re-run rarely fixes a persistent (rather than transient) coercion failure. Not yet verified
  against a real model, only an offline scripted one — see invariant 4's residual-risk note.

  **`injection_scan.py` flags, never blocks.** A deterministic heuristic scan runs at ingestion
  time; a flagged source's content still reaches the model and its answer still returns, with the
  flag surfaced as metadata alongside it (invariant 6) — this is a transparency mechanism, not a
  gate, matching the reward-free/judgement-only posture this whole family of rlm-harness consumers
  shares. Its rules favor recall over precision on purpose (invariant 6's note).

  **OCR ships enabled, not merely pluggable.** `parsers/pdf.py` uses `pymupdf4llm`'s built-in hybrid
  OCR (RapidOCR primary, Tesseract fallback) for scanned/image PDF pages, with the backends as core
  `dependencies` rather than an opt-in extra left uninstalled by default — an independent review
  caught an earlier draft doing exactly that (an `ocr` extra CI's plain `uv sync` never installed,
  reproduced with a real failing test against a clean sync), the same mistake a sibling open-source
  project shipped and had silently fail to parse image sources in its default Docker image; see
  invariant 7.

  **Execution model: still in-process for this slice.** An earlier design iterated on how to isolate
  each chat turn (a `serving.py`/`harness_serve.py`-based subprocess pool was proposed, then
  adversarial review found that mechanism is built for one-shot hierarchical task delegation, not
  high-frequency low-latency turns, and its `stdout` contract blocks any progress-event side
  channel). The simplification landed on was: one plain subprocess per turn, `start_new_session=True`
  for a reliable `killpg`-based cancel, no pre-warmed pool. That runner (`runner.py`/`worker.py`) is
  not implemented in this slice — `cli.py` calls `AnswerQuestion.run()` in-process — and lands with
  the API/UI slice that actually needs concurrent turns and cancellation.

- **Second slice: a persistent, multi-turn `Notebook`** (`schema.Notebook`/`notebook.py`) — sources
  and chat history now survive across `ask` invocations via `--notebook <id>`, one JSON file per
  notebook (`notebooks/<slug(id)>.json`), no database. Without `--notebook`, `ask` is unchanged
  from the first slice (ephemeral, nothing persisted).

  **History is a third signature field, not folded into `question`.** `AnswerQuestion.signature`
  is now `sources: str, history: str, question: str -> answer: Answer`. Kept as its own field
  (rather than string-concatenated into the question) so `AnswerQuestion.instructions` can draw a
  sharp line: `history` is for understanding what a follow-up question refers to, never a source
  of facts or citations — `citations.py` verifies every citation fresh against the current
  `sources` blob every turn regardless of what an earlier turn cited (invariant 11). A past answer
  being wrong, or a source having been removed since, must not carry forward silently.

  **No summarization or truncation of growing history yet.** `notebook.history_text` renders every
  prior turn verbatim, oldest first. An earlier round of design discussion flagged unbounded
  history growth as something that would compound with a since-abandoned subprocess-per-turn
  cold-start cost; with execution still in-process (see above), that compounding doesn't currently
  apply, so truncation/summarization is deferred until real usage shows the corpus-blob size cap
  (invariant 8) or per-turn latency actually motivates it — not implemented preemptively.

  **Extending a notebook dedupes by origin, and ids are never reassigned.** `cli._ingest_new` skips
  any `--source` value already present as an existing source's `origin`, and numbers genuinely new
  sources starting from `len(notebook.sources) + 1` (invariant 12) — re-passing the same source on
  a later turn is a no-op, and a source a saved `ChatTurn.answer` already cites can never have its
  id silently repointed at different text.

  **A notebook id is sanitized before it becomes a filename** (`notebook.slug`, invariant 10) — the
  same `[A-Za-z0-9._-]`-then-length-cap treatment ctx-distillery's `cli._slug` gives a run id,
  since `--notebook` is user input that becomes a path component.

  **`notebook.save_notebook` writes atomically** (temp file in the same directory, `fsync`, then
  `os.replace` onto the real path) rather than writing the real path directly. An independent
  review found the direct-write version left a truncated, unparseable JSON file behind if the
  process was interrupted mid-write (Ctrl+C, crash, power loss), with no recovery but deleting the
  whole conversation and starting over; verified by simulating the interruption (`os.fsync`
  monkeypatched to raise mid-save) and confirming the original file is untouched afterward.
  `cli._cmd_ask` also now catches a `pydantic.ValidationError` from `load_notebook` — a hand-edited
  or otherwise externally-corrupted file — and reports it clearly instead of an uncaught traceback.

  **`_ingest_new`'s dedupe also covers repeats WITHIN one invocation**, not just across separate
  `ask` calls against the same notebook. The first version only checked the caller's static
  `skip_origins` set, so `--source a.txt --source a.txt` in a single command ingested `a.txt`
  twice under two different ids — a `seen` set that grows as the loop runs fixes it. A second,
  related gap the same review found — two different path SPELLINGS of the same file (e.g. a
  relative vs. an absolute path) aren't recognized as the same origin, since `origin` is compared
  as a plain string with no `Path.resolve()` normalization — is NOT fixed in this slice; it's a
  data-duplication/context-dilution issue, not a correctness or security one, and is deferred.

  **`AnswerQuestion`'s sandbox pin is now a numbered invariant** (9), not just a `config.py`
  comment — found while renumbering CLAUDE.md for this slice's additions: the pin was already
  enforced in code and tested, just never promoted to the Invariants list the way the sibling
  projects promote theirs.

- **Third slice: a Notebook Guide** — `rlm-notebook guide {summary,faq,timeline,insight}`
  generates a whole-corpus artifact (`guide.py`: `GenerateSummary`/`GenerateFAQ`/
  `GenerateTimeline`/`GenerateKeyInsight`), the same citation-grounded `RLMTask` pattern as
  `AnswerQuestion` — one input field (`sources`, no `question`/`history`) and one output field per
  task. Guide artifacts share `ask`'s citation verification (`citations.py`) unmodified — it was
  already generic over any `list[Citation]` + `Corpus`, so nothing needed to change there.

  **Citation-marker and validate-before-submit instructions are now factored into
  `instructions.py`** (`CITATION_RULES`, `validate_before_submit_rule`), shared by `AnswerQuestion`
  and all four Guide tasks (invariant 13) — five near-identical copies of the same paragraph was a
  drift hazard (a wording fix landing on one task and not the others), not a stylistic preference.
  Invariant 4 (citation-marker copying) is reworded to say it applies to every grounded task, not
  just `AnswerQuestion`, since it's now literally the same instruction text. The task-specific
  "ground only in sources" OPENING sentence each task supplies is deliberately NOT unified into
  `instructions.py` — `AnswerQuestion`'s is worded for a missing *answer*, the Guide tasks'
  (`guide.py:_grounded_instructions`, shared across just those four) for an unsupported *claim* —
  and an earlier draft of this entry (and of `guide.py`'s docstring) overstated that this opening
  was shared too, which it never was; corrected by the same independent review that found the two
  gaps below.

  **`guide` printed nothing at all for a legitimately empty FAQ/timeline.** `GenerateFAQ`/
  `GenerateTimeline`'s instructions explicitly allow "the sources don't support any items" as an
  honest answer (schema.py's Timeline/FAQ default to an empty list) — but `cli._cmd_guide`'s
  per-item loop then printed literally nothing, so a source with a legitimately empty timeline
  looked identical to a hung or broken command. Fixed with an explicit "(no FAQ items — ...)" /
  "(no timeline — ...)" message when the list comes back empty.

  **A citation-less answer printed a stray trailing blank line.** Refactoring `_cmd_ask`'s output
  around the new shared `_print_citations` helper left every call site printing its own
  unconditional blank line before calling it, so `"...text\n"` became `"...text\n\n"` even when
  there were no citations to print. Fixed by moving the leading blank line INTO
  `_print_citations` itself, printed only when there's something to print after it.

  **`cli._prepare` factors out the load-or-create-notebook / ingest-new-sources / print-flags setup
  `ask` and `guide` both need**, returning `(notebook, corpus)` or `None` (an error already
  printed). `_cmd_ask` and `_cmd_guide` differ only in which RLMTask they run afterward and how
  they print the result — a second command was the forcing function to notice this setup wasn't
  `ask`-specific.

  **Timeline events use free-text `when`, not a parsed date** — sources rarely give a full
  calendar date for every event, and `GenerateTimeline`'s instructions explicitly allow (and
  `Timeline.events`'s default empty list explicitly supports) "the sources describe no sequence of
  events at all" as a valid, non-fabricated answer rather than forcing a timeline into existence.

  **Guide artifacts are not cached onto the notebook or made citable as sources for later `ask`
  turns.** An early design discussion floated treating a generated summary/FAQ/timeline as a
  "generated" source type other answers could cite. Deferred: it adds a second citable-content
  shape (generated vs. ingested) that `citations.py`/`corpus.py` don't yet distinguish, and no
  concrete need for it has shown up yet. Each `guide` call regenerates from the current `sources`
  blob fresh every time.

- **Fourth slice: an Audio Overview** — `rlm-notebook audio` generates a two-host podcast script
  (`audio.py`'s `GeneratePodcastScript`, same citation-grounded `RLMTask` pattern, sharing
  `instructions.py`'s citation rules) and synthesizes it to an MP3 (`tts.py`). The transcript
  prints first, with citations, regardless of whether synthesis succeeds afterward — a TTS
  failure (network, misconfigured voice) doesn't lose the script, since it was already generated
  and printed before synthesis is even attempted.

  **Script generation and audio synthesis are two fully separate steps with no RLM-side coupling**
  (invariant 14): `GeneratePodcastScript` doesn't import `tts.py` at all, and the TTS provider is
  never a tool the model can call — the same "the model's job is done before this step runs"
  reasoning invariants 1/3 already establish for ingestion/fetching. `tts.py` only ever receives
  an already-generated, already-schema-validated `PodcastScript`.

  **Default TTS provider is `edge-tts` — free, no API key, no paid account** (invariant 15),
  matching the OCR default's "ship a working default" reasoning (invariant 7) rather than leaving
  `rlm-notebook audio` usable only after separately acquiring TTS credentials. Verified against
  the REAL edge-tts network service (not just the offline-injected-fake unit tests) before
  landing this: a two-utterance script produced a 52KB MP3 starting with a valid MPEG frame sync
  header. The known-provider list lives in exactly one place, `tts.py`'s `_PROVIDERS` — unlike
  `RN_OCR_PROVIDER`, `config.py` does not keep a second copy to validate against, so the two lists
  can't drift apart the way a duplicated list eventually does.

  **`EdgeTTSProvider` synthesizes per-utterance and concatenates raw MP3 bytes, no re-encoding**
  (invariant 17) — `edge-tts` is one-voice-per-call, and re-encoding a proper gapless multi-speaker
  file would need `pydub` + a system `ffmpeg` binary (not pip-installable) for what's ultimately a
  playback-smoothness cosmetic improvement. Documented, deliberate tradeoff, not an oversight.

  **The cast is a fixed two hosts, `host_a`/`host_b`** (invariant 18) — not a per-episode
  configurable roster. Keeps `Utterance.speaker` a closed enum and the voice-selection surface
  (`RN_TTS_VOICE_HOST_A`/`_B`) two fixed variables rather than an open-ended cast config; a
  deliberate MVP scope cut matching how NotebookLM's own Audio Overview also ships a fixed
  two-host format.

  **An empty `PodcastScript` is a legitimate answer, and `cli._cmd_audio` says so explicitly**
  rather than printing nothing — the identical fix (and the identical bug shape) `guide`'s empty
  FAQ/timeline needed; applied proactively here rather than waiting for a second independent
  review to find the same class of bug again.

  **Found and fixed two invariant cross-references that had gone stale across earlier
  renumberings and survived three prior independent reviews: `pyproject.toml`'s inline comments
  (citing invariant 1/6 where the actual invariants were 3/7) and `.env.example`'s (citing
  invariant 7/6 where they were 8/7, and still describing OCR as behind an `ocr` extra that no
  longer exists).** Earlier renumbering passes grepped `.py`/`.md` files only — `.toml`/`.env.example`
  were never included, so these survived undetected. Worth remembering next time invariants are
  renumbered: grep needs `--include` for every text format the repo actually has comments in, not
  just the two most common ones.

  **A fourth independent review reproduced two real, previously-uncaught crashes and fixed both**
  (invariant 19): (1) `cli._cmd_audio` called `get_tts_provider(config.tts_provider)` AFTER
  `GeneratePodcastScript().run(...)`, so a mistyped `RN_TTS_PROVIDER` only surfaced as an uncaught
  `TTSError` once a real model call had already run and the transcript had already printed —
  reordered so the provider is resolved (and its error handled) first. (2)
  `EdgeTTSProvider.synthesize`'s `out_path.write_bytes(...)` sat outside its own try/except, so a
  `--out` path whose parent directory doesn't exist raised an uncaught `OSError` AFTER a real
  network synthesis call had already succeeded and been spent — reproduced against the real
  edge-tts service (not just the offline fake) both before and after the fix. Also added a spy
  test asserting `_cmd_audio` passes `config.tts_provider` (not some other, wrongly-named config
  field) to `get_tts_provider` — every prior audio test had monkeypatched that function wholesale
  and would have passed even if the wrong field were wired in. Documented (not fixed, low
  priority) that `EdgeTTSProvider.synthesize`'s internal `asyncio.run()` would raise if ever called
  from inside an already-running event loop — harmless for today's synchronous CLI, a real
  constraint for the planned API/UI slice to keep in mind if it calls this directly. Added a
  tripwire test pinning that `cli._SPEAKER_LABELS` covers every `schema.Speaker` value, since
  nothing in this project's CI (ruff + pytest, no type checker) would otherwise catch the two
  drifting apart.

- **Fifth slice: an HTTP API** (`api.py`, the `api` extra: `uv sync --extra api`) —
  `POST/GET /notebooks/{id}`, `POST /notebooks/{id}/ask`, `POST /notebooks/{id}/guide/{kind}`,
  `POST /notebooks/{id}/cancel`. This is the first place a run is isolated in its own subprocess
  rather than executed in-process; `cli.py` is completely unaffected and unchanged in behavior.

  **The subprocess-per-run execution model an earlier design round sketched and then deferred is
  now implemented**: `worker.py` is the subprocess entrypoint (resolves an RLMTask by dotted
  `module:ClassName`, runs it, records a full trace, prints exactly one JSON line as its result);
  `runner.py` is the host-side launcher (`start_new_session=True` so the worker is its own process
  group leader, `killpg` on cancel/timeout so a stuck Deno grandchild dies with it rather than
  becoming an orphan). Verified with a real test that spawns an actual grandchild subprocess and
  confirms it dies on cancellation, not just the worker's own PID (invariant 22) — this was the
  exact failure mode an earlier design round worried an over-eager `process.kill()` would miss.

  **`api.py` never imports `dspy`/`rlm_harness` itself** (invariant 21) — only `worker.py`, inside the
  subprocess, does. A crash deep in the model stack takes down a worker subprocess, never the API
  server process.

  **Extracted `ingest.py` and two new `notebook.py` functions (`load_or_create`,
  `extend_with_sources`) out of `cli.py`**, so `api.py` doesn't have to import from `cli.py` (or
  vice versa) to reuse the identical "get me a notebook, ingest new sources into it" step
  (invariant 20). `cli._prepare` is now a thin argparse-`Namespace`-shaped wrapper around the same
  shared functions `api.py` calls directly. Existing `_is_url`/`_ingest_one`/`_ingest_new` tests
  moved to `tests/test_ingest.py` unchanged in substance, just relocated with the code.

  **`api._config()` converts `NotebookConfig.from_env()`'s `SystemExit` into an HTTP 500** rather
  than letting it escape a request handler (invariant 24) — `cli.py` legitimately lets the same
  `SystemExit` exit the process, which is wrong for a server. Verified against a REAL running
  server with `curl` (not just the mocked test suite): an unset `RN_MAIN_MODEL` now returns a
  clean 500 with `cli.py`'s own error message, not a broken connection or a raw traceback. The
  rest of the API was also smoke-tested end to end against a real running server this way —
  `add_sources` (including that re-adding the same source is a no-op, not a duplicate),
  `get_notebook`, 404s on a missing notebook, and 404 on `cancel` with no in-flight run.

  **`_ACTIVE_RUNS` is single-process, in-memory, keyed by notebook id** (invariant 23) — a known,
  documented limitation (no multi-worker `uvicorn` deployment story yet), not a silent gap:
  running more than one `uvicorn` worker would split this dict across processes and `cancel` would
  only reach whichever worker happens to hold a given notebook's in-flight run.

  **Deliberately NOT in this slice** (deferred, not forgotten): an `/audio` endpoint (Audio
  Overview synthesis is slower/heavier than `ask`/`guide` and deserved its own wiring rather than
  being rushed in here), SSE/progress streaming (a request currently blocks until its subprocess
  finishes or `RN_RUN_TIMEOUT_SECONDS` — default 300s, a NEW config field distinct from
  `RN_MAX_ITERATIONS`/`RN_MAX_LLM_CALLS`, which bound loop steps, not wall-clock time — elapses),
  and any browser UI at all.

- **An independent review of `feat/api` found and reproduced two real security/robustness issues
  before merging, both fixed:**

  **`add_sources` was an unauthenticated arbitrary-file-read vector (invariants 25, 26).**
  `ingest.ingest_one` treats any non-URL string as a local file path with no allowlist — correct
  for `cli.py`, where the operator already trusts their own machine, and a vulnerability the moment
  the exact same function sat behind an unauthenticated HTTP endpoint. The review reproduced the
  full chain: `POST {"sources": ["/etc/passwd"]}` read the file, and a mocked `ask` echoed its
  contents back through a citation that passed coordinate verification. Fixed by rejecting any
  non-URL value in `add_sources` before it reaches ingestion. This also surfaced that the API has
  NO authentication at all (invariant 25) — now stated explicitly in `api.py`'s module docstring
  and README, not left implicit.

  **Four id-taking endpoints crashed with a raw 500 on a notebook id that reduces to an empty
  slug** (invariant 27) — e.g. `GET /notebooks/!!!`. `_load_notebook_or_404`/`add_sources` only
  caught `pydantic.ValidationError` (a corrupted file), not the `ValueError` `notebook.notebook_path`
  raises for an empty slug; reproduced on `GET`, `sources`, `ask`, and `guide/{kind}` with nothing
  more exotic than a notebook id made of punctuation. Fixed by catching `ValueError` too (→ 400).
  The review also checked route-level path-traversal payloads (`../../../tmp/evil`) and confirmed
  they never reach this code at all — Starlette's path converter refuses a literal `/` inside one
  `{notebook_id}` segment, so those 404 at the routing layer first; a real finding, but not a bug.

  **Verified the `_ACTIVE_RUNS` single-slot-per-notebook-id design is a capacity limitation, not a
  race**, with an `asyncio`-interleaved test: the `finally` block's `is run` identity check
  correctly lets only the request that OWNS an entry clear it, even when a second concurrent
  request for the same notebook id has already overwritten the slot. Documented this more
  precisely (invariant 23) — the previous wording only mentioned the multi-worker-process
  limitation, not this same-process one.

  **Added a tripwire test for `cli._GUIDE_TASKS`/`api._GUIDE_TASKS` staying in sync** (invariant
  28) — the same class of gap the PREVIOUS slice's own `_SPEAKER_LABELS` drift was found to have,
  applied proactively here instead of waiting for a fourth review to find the fourth instance of
  the same lesson.

- **Sixth slice: a web UI (`rlm_notebook/web/`), Phase 1 of a 3-phase blueprint** — Web shell +
  Sources + Chat. Gives the HTTP API added in the previous slice a real end-user product surface;
  before this slice it was only usable via `curl`/tests. Two small, additive API changes support
  it: `GET /notebooks` (a listing endpoint for the notebook switcher) and `GET /notebooks/{id}` now
  returning full turn history instead of just a count, so a re-opened notebook's past conversation
  renders immediately (citations re-verified fresh against the current corpus on every read, same
  discipline as a brand-new answer — invariant 11).

  **Deliberately NOT another instance of the sibling projects' replay-only trace console.**
  `ctx-distillery`/`cve-reverser`/`diff-sentry`/`toolscout` each ship a `studio/` that's a
  single-verdict security/review console; this project's persistent, multi-notebook, multi-turn
  knowledge workspace is structurally different on purpose (invariant 29). An original visual
  identity — two full first-class OKLCH themes, Paper (light, default) and Study (dark), sharing
  one hue family for brand continuity rather than the siblings' cool blue-slate security-console
  dark — and a citation-as-highlighter-stroke signature interaction, not a footnote number.

  **Went through a pre-implementation independent design audit before any code was written**
  (`docs/design/web-ui-blueprint.md`, gitignored, same convention as `docs/research/`). The audit
  found 4 blockers: the originally planned SSE reasoning-trace fusion was unbuildable as scoped (no
  `run_id` ever reaches a client mid-run from `ask`/`guide`'s synchronous contract, and
  citation-to-trace-turn linking had no data model at all) — pulled from this round entirely rather
  than patched under pressure, and held for its own future design pass; a top-level `web/` directory
  would have silently vanished from an installed wheel (no `pyproject.toml` packaging entry) — fixed
  by moving assets under `rlm_notebook/web/`, verified by actually building a wheel and confirming
  the files are inside it; `GET /notebooks`' original design cited a `NotebookConfig` field that
  doesn't exist — fixed to read the same bare `notebook.DEFAULT_NOTEBOOKS_DIR` constant every other
  notebook operation already uses; and two real, COMPUTED (not eyeballed) WCAG contrast failures in
  the original palette (Paper's `--text-faint` measured 3.08:1 against `--surface-3`, Study's
  2.97:1 — both below the 4.5:1 AA floor for normal text) plus a third the audit's own checklist
  didn't anticipate (Study's citation highlight wash was self-contrast ≈1.0 against an elevated
  panel, i.e. invisible) — all three fixed with recomputed, re-verified OKLCH values, and the
  citation highlight gained a border backstop so its perceptibility never depends on wash luminance
  alone.

  **A second, independent completion check after implementation** (the project's standard
  pre-merge gate) re-verified every one of those fixes was actually real in the shipped code, not
  just described in a commit message — rebuilt the wheel and confirmed the static assets were
  inside it, independently recomputed the WCAG contrast ratios from the real `style.css` values,
  and ran the real test suite and a live `curl` smoke test against a running server. It also caught
  that `app.js`'s citation renderer built an HTML attribute via string interpolation
  (`<span title="...">`), which a `"` character inside a model-echoed `source_id`/`locator` could
  have broken out of under a prompt-injected source (invariant 6) — found and fixed (rebuilt with
  `createElement`/`textContent`/`element.title` throughout, never `innerHTML`) before the audit
  even ran, then independently confirmed landed cleanly.

  **Deliberately NOT in this slice**: Phase 2 (Guide tabs + podcast player, needs a new `/audio`
  endpoint) and Phase 3 (the live reasoning-trace ticker, held back per the audit above) are
  separate, not-yet-scheduled slices. Paste-text and file-upload source ingestion in the UI are
  visible tabs that say plainly they aren't wired to the API yet, rather than silently failing or
  pretending to work — the API itself still only accepts http(s) URLs (invariant 26).

- **Seventh slice: web UI Phase 2 — Studio panel (Guide tabs + podcast player)**. Adds
  `POST /notebooks/{id}/audio` and wires the Studio panel Phase 1 left as a placeholder.

  **`/audio` is two host-side steps, not one, and deliberately doesn't touch `worker.py`/
  `runner.py` at all.** `GeneratePodcastScript` runs in the exact same isolated subprocess `ask`/
  `guide` already use — the only step that touches `dspy`/`rlm_harness`, and the only one cancellable
  via `POST .../cancel`. TTS synthesis (`tts.py`) then runs AFTER that subprocess returns,
  IN-PROCESS inside `api.py` itself: `tts.py` imports neither `dspy` nor `rlm_harness`, so this doesn't
  reopen invariant 21, and it's the same precedent `api.py` already sets by importing the Guide/
  `AnswerQuestion` RLMTask classes at module load purely for introspection, never calling `.arun()`
  on them itself.

  **`EdgeTTSProvider.synthesize()`'s own previously-flagged residual risk finally landed for real,
  and got its predicted fix.** Its docstring already said a future async caller would need to
  route around its internal `asyncio.run()` call rather than changing `synthesize()` itself — this
  slice is that caller, dispatching through `asyncio.to_thread` (a fresh OS thread has no event
  loop of its own, so `asyncio.run()` inside it never collides with the request handler's own
  running loop). `tts.py` is unmodified; `cli.py`'s existing synchronous call site is unaffected.

  **No audio is ever persisted past one request** — synthesis writes to a temp file, the bytes are
  read back and base64-encoded into the JSON response, and the temp file is deleted whether
  synthesis succeeded or failed. Deliberately no `GET .../audio/{run_id}.mp3`-style file-serving
  endpoint and no retention policy to get right, unlike the reasoning-trace files Phase 3 left
  unresolved.

  **Went through the same pre-implementation independent design audit Phase 1 established**
  (`docs/design/web-ui-blueprint.md`'s Phase 2 addendum) before any code was written. Found 2
  blockers, both fixed before implementation started: the ordering list omitted the notebook-load/
  corpus/blob-size steps every other endpoint performs first, which as originally written would
  have surfaced a 500 (bad `RN_TTS_PROVIDER`) ahead of a 404/413 whenever both conditions held,
  inverting `cli._cmd_audio`'s real precedence; and the temp-file cleanup plan only covered the
  success path, which would have leaked a `.mp3` per failed synthesis (`tts.py`'s `synthesize()`
  has two real `TTSError` raise sites that fire after the file already exists on disk). Two
  non-blocking fixes folded in too: the Guide-tab cache now invalidates on a source being added,
  not just on a notebook switch; and the podcast player's object-URL revocation order is now
  explicit (assign the new URL before revoking the old one, so a previous episode being played
  when "regenerate" is clicked is never yanked out from under a live `<audio>` element).

  **Studio panel**: four Guide tabs (`Summary`/`FAQ`/`Timeline`/`Insight`), each fetched only on
  first activation or an explicit `↻ Regenerate` click — never automatically, including on
  notebook open, since a guide run is a real RLM loop and auto-fetching on open would burn a model
  call for nothing (a mistake caught and fixed during this slice's own implementation, before it
  ever shipped, not by the audit). Results are cached client-side per notebook and invalidated on a
  source being added. A `Generate podcast` button below produces a `Blob`/`ObjectURL`-backed
  `<audio controls>` player (not a `data:` URI, which would keep a multi-MB episode's whole
  base64 string live in a DOM attribute) plus a transcript, reusing Phase 1's citation-highlighter
  rendering verbatim.

  **Known, accepted limitation, stated explicitly (invariant 29)**: only `/audio`'s script-
  generation half is cancellable — by the time synthesis begins, `_run_isolated`'s `finally` has
  already cleared this notebook's `_ACTIVE_RUNS` entry, so a stuck synthesis call blocks its
  request with no `killpg`-equivalent to reach it. Not a regression (`cli._cmd_audio` has no
  cancellation story for this phase either), but new: an API request's total latency can now
  include a real network TTS call serialized after an RLM run.

  **Deliberately NOT in this slice**: Phase 3 (the live reasoning-trace ticker) remains held back,
  same reasons as before. The full source-text viewer (and Literata, the typeface reserved for it)
  is still unbuilt.

- **Eighth slice: web UI Phase 3 — reasoning-trace fusion (live ticker + citation-turn linking)**.
  The blueprint's Phase 3 addendum was redesigned from scratch (its own two audit rounds, before
  any code was written) to resolve the two blockers the ORIGINAL Phase 3 design was pulled over:
  no `run_id` ever reached a client mid-run, and citation-to-trace-turn linking had no data model.

  **The client picks the run id, never the server** — `ask`/`guide`/`audio` all gain an optional
  `run_id` body field (a shared `RunOptions` model); when given, it's sanitized through the SAME
  whitelist `notebook.slug()` already uses and always prefixed with `notebook_id`. This is the
  toolscout-studio pattern (a previewed run id the solve call sends explicitly), not a fire-and-poll
  rewrite of endpoints Phase 1/2 already shipped and audited — fully additive, byte-for-byte
  unchanged behavior for any caller that doesn't supply one.

  **Real concurrency bugs found and fixed before implementation, not discovered as runtime bugs.**
  The redesign's own first pre-implementation audit found 3 blockers, all clustered around one
  blind spot: same-notebook concurrency was never stress-tested against a client-controlled run id.
  (1) Two concurrent requests deriving the same run id would have let two independent worker
  subprocesses append interleaved, duplicate-`step_id` events to one trace file —
  `TraceRecorder`'s own lock is process-local and provides zero cross-process serialization. Fixed
  with a hard uniqueness gate: `_run_isolated` now exclusively creates the trace file
  (`O_CREAT|O_EXCL`) before spawning anything, mapping a collision to 409. (2) The originally
  planned cancelled-run liveness check reused `_ACTIVE_RUNS` (notebook-id-keyed, one slot per
  invariant 23), which would misfire the moment a second concurrent request on the same notebook
  overwrote the first's entry — fixed with a NEW, run-id-keyed `_RUN_PROCESSES` map, decoupled
  entirely from `_ACTIVE_RUNS`'s single-slot semantics. (3) The citation-lookup search's field list
  was verified wrong against `rlm_harness.sub_lm`'s real `sub_call` payload shape (`input`/`raw`/
  `processed`/etc, not `reasoning`/`code`/`output`) — fixed by searching a trace event's ENTIRE
  serialized payload rather than a hardcoded field list. A second, targeted audit round then found
  2 more real gaps in the collision-gate fix itself (a directory-existence race with a fresh
  checkout's very first run, and a missing cleanup path that would have permanently false-409'd a
  retry after a failed subprocess spawn) — both fixed before implementation started.

  **`GET /notebooks/{id}/runs/{run_id}/stream`** — one SSE endpoint serving both a live tail (the
  run is still in progress) and a replay (the run already finished) from the same polling loop,
  verified safe against `rlm_harness/trace.py`'s actual write behavior: `TraceRecorder.record()` writes
  one complete, flushed JSON line per event under its own lock, so a reader that buffers any
  trailing partial line can never see a torn or interleaved line. Synthesizes a terminal event for
  a `killpg`-cancelled run whose `TraceRecorder.__exit__` never got to write `run_end`, the same fix
  `ctx-distillery-studio` already documents for the identical failure mode.

  **`GET /notebooks/{id}/runs/{run_id}/citation-turn`** — a small, separate lookup (not a reuse of
  the live stream, which would ship a whole trace to the client just to search it) for "which trace
  turn shows the model reading this citation's source span." A heuristic, stated as one: finding
  the marker proves the model's REPL saw it, never that this occurrence is what the model relied
  on — the same "coordinate, not faithfulness" limit invariant 5 already states for citation
  verification generally. `schema.ChatTurn.run_id` (new, optional, backward-compatible) is the ONE
  schema change needed — Guide/Audio results still aren't persisted onto a notebook at all, so
  their citation links only need to work within the current browser session, which the client's
  own in-memory run id already satisfies with no server round-trip or schema change.

  **Post-merge follow-up**: a code-vs-docs consistency check (dispatched separately from this
  slice's own implementation/completion checks) found `stream_run` was missing the same
  `run_id`-belongs-to-`notebook_id` check `citation_turn` already had, so a mismatched
  `notebook_id` in the URL could still stream a trace belonging to a different notebook. Fixed in
  a small follow-up commit; both endpoints now apply the check consistently.

  **Frontend**: every `ask`/Guide-tab/podcast-generate call opens a live ticker alongside the
  actual request, replacing static "Thinking…"/"Generating…" copy with live-updating copy in the
  SAME pending slot — deliberately not a new UI element, and deliberately a SECONDARY layer: losing
  the ticker (a dropped SSE connection) never blocks or alters the request's own result. Every
  citation with a known run id becomes clickable, filling one shared detail slot per answer with
  the matching trace turn. The Phase 2 Guide-tab cache's value shape widened to `{result, runId}`
  (an earlier draft only cached the result, which would have lost the run id the moment a user
  switched tabs and back — found and fixed during the redesign, before implementation).

  **Known, stated limitations, not solved by this phase**: no trace-file retention policy exists
  anywhere in this project — a citation's "view reasoning" link is only as durable as a file
  nobody has committed to keeping (a missing trace degrades that ONE affordance, never the rest of
  the page); a `sub_call` event's `input` field is truncated to 4000 characters upstream
  (`rlm_harness.sub_lm`), a real source of false negatives in the citation-turn search. The trace
  stream and citation-turn endpoints inherit invariant 25's no-auth posture as a materially
  different, sharper exposure than every other endpoint (they can surface full ingested source
  text, not just metadata/prose) — stated explicitly in CLAUDE.md, not left implicit.

- **Ninth slice: file upload + paste-text ingestion, wiring up the Sources panel's previously-inert
  "File" and "Paste text" tabs.** Prompted by a Gemini-Notebook feature-parity assessment that
  named this the single highest-priority gap: a browser user dragging a PDF into the Sources panel
  used to hit an `alert()` and nothing happened — NotebookLM's single most common operation.

  **`POST /notebooks/{id}/sources/upload`** (new) and `add_sources`'s new `texts` field are a
  genuinely different, safe mechanism alongside invariant 26's local-path ban, never a way around
  it — the server only ever receives opaque bytes/text the caller already had, never a path it
  reads from its own filesystem. `ingest.ingest_uploaded_file` dispatches on the claimed filename's
  suffix (`.pdf`/`.txt`/`.md` only, anything else a clear 422) and reuses the two parsers that
  already existed unchanged; `ingest.ingest_pasted_text` gives pasted text a readable-snippet-plus-
  content-hash origin (a bare hash was found, during design, to be a real UX regression — the
  Sources list renders `origin` verbatim as its only label).

  **A real, verified-before-landing security fix**: the upload size cap (`RN_MAX_UPLOAD_BYTES`,
  default 50MB) doesn't work the way the first draft assumed. Declaring the endpoint the natural
  FastAPI way (`file: UploadFile = File(...)`) makes FastAPI itself parse the entire multipart body
  BEFORE the handler (or any in-handler check) ever runs, for ANY route shaped that way, regardless
  of `Content-Length` — confirmed live against the installed version (a 5MB body was already fully
  spooled to disk the instant a test handler started, with an accurate `Content-Length` header,
  not just in a chunked-encoding edge case). Starlette's own `max_part_size` never applies to file
  parts either. Fixed by taking `request: Request` directly instead — `Content-Length` is checked
  BEFORE ever calling `request.form()`, so an oversized declared size is rejected with the body
  never read off the socket at all; a missing `Content-Length` (chunked encoding) is refused
  outright (411), not accepted with a disclosed gap. Verified live (a standalone test app, a 5MB
  POST against a 1000-byte cap) before this was believed rather than just reasoned about.

  **Deliberately NOT gated behind `NotebookConfig.from_env()`**: `config.max_upload_bytes()` is a
  standalone function — gating it on a full model config (which raises `SystemExit` whenever
  `RN_MAIN_MODEL` is unset) would make uploading a source fail with "server misconfigured" for a
  reason that has nothing to do with what the caller is trying to do. Caught while designing this,
  not left for an audit to find — `add_sources` already established this same discipline for the
  URL-based path.

  **Deliberately NOT in this slice**: Word/Slides/Docs native-format parsing (would need new parser
  dependencies — this only wires up the two parsers that already existed), multi-file batch upload,
  YouTube/audio source ingestion, and a source-text viewer (still open gaps from the same
  feature-parity assessment, not attempted here).

- **Tenth slice: a source-text viewer — NotebookLM's most basic closed loop (click a citation, see
  the highlighted original passage).** The second of the three remaining gaps from the same
  Gemini-Notebook feature-parity assessment; the first (file upload) shipped the previous slice.

  **`GET /notebooks/{id}/sources/{source_id}`** (new) returns a source's full text, every block —
  `{id, kind, origin, flags, blocks: [{locator, text}]}`. Reuses `corpus.Corpus.get(source_id)`,
  the same lookup `citations.py` already performs on every `ask`/`guide` request, confirmed cheap
  before reuse rather than assumed. A materially different exposure than most other endpoints here
  (invariant 31) — before this, no caller could read more of a source than a citation's short
  `quote`.

  **The web UI's citation-list row is now clickable, opening a source-viewer modal** — the first
  stacking-context component in `rlm_notebook/web/` (`.modal-overlay`/`.modal`, closing via `✕`/
  backdrop/`Esc`, the same family convention the sibling projects' own `studio/`s already use for
  their trace-replay drawers). The matching block is highlighted (reusing the existing `.citation`
  highlighter-stroke styling) and scrolled into view. The pre-existing reasoning-trace view
  (`showCitationTurn`, Phase 3) is demoted to a secondary `⌁ trace` icon inside the same row rather
  than removed — the two click targets coexist, the icon calling `event.stopPropagation()` so
  clicking it never also opens the source viewer.

  **Two staleness-guard bugs, one new and one pre-existing, both fixed in this slice.** The
  pre-implementation audit required a guard against a slower first fetch overwriting a faster
  second one's render for the brand-new source-viewer fetch (fixed with a module-level
  `AbortController`), then found the SAME class of defect already present, unfixed, in the
  pre-existing `showCitationTurn` from Phase 3 — retrofit with an equivalent monotonic-token guard
  there (`detailArea._requestToken`), chosen over `AbortController` for that one site since it's a
  plain GET with no browser-level cleanup worth invoking.

  **A pre-existing concurrency bug found, and explicitly NOT fixed here**: `notebook.py`'s
  single-writer assumption doesn't hold once `api.py` serves concurrent requests — two concurrent
  `POST /notebooks/{id}/sources` calls on the same notebook can silently discard one via
  `save_notebook`'s non-merging atomic replace (invariant 31's closing paragraph). Read-only, so
  not a blocker for this slice; a per-notebook lock (or a merging write) is a separate follow-up.

  **Deliberately NOT in this slice**: source editing, next/prev-citation navigation, caching across
  viewer opens (each open re-fetches), and pagination for very large sources. YouTube/audio source
  ingestion and a Notes research loop remain the last two open gaps from the same feature-parity
  assessment.

- **Eleventh slice: Notes — the research-loop closing feature.** The third of the four gaps named
  by the same Gemini-Notebook feature-parity assessment; only YouTube/audio source ingestion
  remains after this. NotebookLM's own differentiating loop — read a source, write a note (or save
  an AI answer as one), promote it into a full source, keep going — had no concept at all in this
  project before this slice: `schema.Notebook` had only `sources` and `turns`.

  **`schema.Note`/`Notebook.notes`** (new): a note is freeform, uncited text — grounded and citable
  only once PROMOTED into a real `Source`, never before (invariant 32). Backward-compatible via
  pydantic's default, the same precedent `ChatTurn.run_id` already established.

  **`notebook.add_note`/`delete_note`/`promote_note`** (new): `promote_note` reuses
  `ingest.ingest_pasted_text` UNCHANGED — the exact function pasted-text sources already go
  through — so a promoted note gets the identical content-derived-origin, dedup, and
  injection-scan treatment any other pasted text already gets, rather than a parallel code path.
  Removes the note from `notes` regardless of outcome (a dedup hit against already-identical text
  returns `None` and appends nothing new) — promotion is a completed action either way.

  **Three new API endpoints, one extended response**: `POST /notebooks/{id}/notes` (uses
  `load_or_create`, like `add_sources`), `DELETE /notebooks/{id}/notes/{note_id}` (this API's FIRST
  `DELETE` route), `POST /notebooks/{id}/notes/{note_id}/promote` — the latter two use
  `_load_notebook_or_404`, matching `ask`/`guide`'s existing-notebook-only precedent.
  `NotebookResponse` gains a `notes` field, so every endpoint that already returns a notebook gets
  it for free through the one shared `_notebook_response` conversion function.

  **Web UI**: a Notes section in the Studio panel (below Audio Overview), each note with a
  `→ Promote to source` and a `✕` delete button; a "+ Save as note" button on every Chat answer.

  **A real pre-implementation-audit catch, not found live afterward**: the original design would
  have put the "+ Save as note" button inside `renderAnswerWithCitations` — a function SIX
  different call sites share (Chat plus all four Guide kinds and the podcast transcript) — which
  would have leaked the button onto generated artifacts a user never curates into notes. Fixed
  before any code was written: the button lives in `renderTurn` (Chat's own call site) instead.

  **A real bug found by the independent post-implementation completion check, fixed before
  merge**: the original `n{len(notes)+1}` id scheme let two LIVE notes share one id the moment a
  non-last note was deleted (delete `n1` out of `[n1, n2]`, add a third — the old scheme reused
  `n2`, colliding with the note still alive under that id) — reproduced live, and confirmed to
  cause a real silent data loss: promoting one of a colliding pair discarded the other with no
  source ever created and no error raised. Fixed at the root with `_next_note_id` (derives the
  next id from the MAX id actually in use, not the count, so a new id can never collide with one
  still alive); `delete_note`/`promote_note` also now remove exactly the first matching note by
  index rather than filtering every id-equal match, as defense in depth on top of the id fix, not
  instead of it (invariant 32). An id can still be safely reused once NO live note holds it.

  **Deliberately NOT in this slice**: note editing (delete-and-recreate is the only revision path),
  rich-text/markdown notes, note-to-note linking or tagging, and retroactively re-citing past `ask`
  turns after a note they referenced gets promoted (a note was never a citable source before
  promotion, so there's nothing to retroactively fix). YouTube/audio source ingestion is the one
  remaining gap from the feature-parity assessment.

- **Twelfth slice: YouTube caption ingestion.** The last of the four gaps named by the same
  Gemini-Notebook feature-parity assessment. Pasting a YouTube URL used to silently mis-ingest as
  a generic web page (`parse_web` against YouTube's own HTML shell, which has no transcript text
  at all — the page loads captions via client-side JS, not server-rendered markup).

  **MVP scope, decided WITH the user, not guessed.** Two real technical forks existed: captions-
  only via `yt-dlp` vs. full audio-download-plus-transcription, and — had the latter been chosen —
  local Whisper vs. a cloud transcription API. The user picked captions-only: no video/audio
  download, no `ffmpeg`, no Whisper, no transcription API key. A video with neither official nor
  auto-generated captions is a clean ingestion-time error, not a silent partial ingestion; full
  audio transcription remains a separate, later, independently-mergeable follow-up.

  **A real ToS/legal caveat, disclosed and accepted, not glossed over**: YouTube's Terms of
  Service prohibit automated access outside its own interfaces; `yt-dlp` (new, but a CORE
  dependency — pure Python, no `ffmpeg` needed for this path, same "ship a working default"
  reasoning as OCR/TTS) operates in the same long-standing gray area every YouTube-downloading
  tool does. Fetching only captions is narrower/lower-risk than downloading media, but not
  risk-free — the risk is accepted by whoever deploys this project.

  **`parsers/youtube.py`** (new): `is_youtube_url` dispatches ahead of the existing generic
  `is_url` → `parse_web` fallback in `ingest.ingest_one`, so `cli.py`'s `--source` and `api.py`'s
  `POST /sources` both get this for free with no per-entry-point change. `parse_youtube` fetches a
  caption track via `yt-dlp` (`skip_download: True` — no video/audio ever touches disk), parses
  WebVTT into `(start, text)` cues, collapses auto-caption's "rolling karaoke" duplication, and
  chunks into `~120`-second blocks with a new `"ts:<mm:ss>"` locator prefix.

  **Three real bugs found and fixed against REAL caption data across two independent review
  rounds, not assumed correct from reasoning alone** (invariant 33 has the full account). A first
  design kept only each cue's last non-blank line, which WRONGLY dropped real content from
  genuine multi-line official dialogue cues — fixed (pre-implementation) by keying the extraction
  rule on whether a cue contains ANY `<...>` tag markup. An independent POST-implementation
  completion check then found that fix itself still under-collapses: a real auto-caption
  "building" cue advancing by exactly ONE new word often carries NO tag at all, so the
  tag-presence heuristic misclassified it and left a duplicated word pair in a live-fetched
  transcript. Fixed by replacing the whole classification approach with something simpler:
  flatten EVERY non-blank line into its own entry and leave all deduplication to plain adjacent-
  collapse — sidesteps the tag-presence question entirely, since a rolling-karaoke transition
  line always collides with something the preceding cue already emitted regardless of tags,
  while genuine multi-line dialogue lines never collide with anything. A separate, still-correct
  fix treats a whitespace-only line as part of a cue's OWN payload (not a separator), since real
  auto-caption VTT uses a single-space line for exactly that. All fixes re-verified live against a
  real public video's official AND auto-generated caption tracks, checking for adjacent duplicate
  words across the WHOLE reconstructed transcript, not just the hand-written test fixtures.

  **A real pre-implementation-audit catch**: `CaptionError` was first drafted as a bare
  `RuntimeError`; `cli._prepare`/`api.add_sources` both catch ingestion failures as
  `except (FetchError, ValueError, OSError)`, so a captionless video would have escaped as an
  unhandled 500/traceback instead of the clean error this slice promises. Fixed by making
  `CaptionError` a `ValueError` subclass — found and fixed before any code was written, verified
  live afterward with a dedicated test.

  **A separate, unrelated dependency gap surfaced (not caused) by adding `yt-dlp`**:
  `python-multipart` (needed by `POST /notebooks/{id}/sources/upload`'s multipart form parsing,
  invariant 30) had never been an explicit dependency — it arrived transitively, silently, until
  `yt-dlp` shifted dependency resolution enough that it stopped being pulled in and the upload
  tests broke with no code change of their own. Pinned explicitly in the `api` extra now.

  **Deliberately NOT in this slice**: any video/audio download (the user's explicit MVP decision),
  a captionless video, a non-YouTube video URL, or a directly-uploaded audio file (all out of
  scope); timestamp-precise single-cue citation granularity (the 120-second chunking window is a
  deliberate coarser grain, matching text/web's own single-locator precedent); playlist/channel
  ingestion. This closes out the four-gap Gemini-Notebook feature-parity assessment that started
  with file upload.

- **Thirteenth slice: replace `pymupdf`/`pymupdf4llm` — a real AGPL-vs-MIT license conflict, found
  and fixed, not a preemptive style choice.** `pymupdf`/`pymupdf4llm` are dual-licensed "GNU AGPL
  v3 OR Artifex Commercial License" (confirmed via `importlib.metadata` against the actually-
  installed distributions and the vendor's own file header) — no free non-AGPL option exists. A
  transitive `pymupdf4llm` dependency, `pymupdf-layout`, carried a SECOND, even stricter Artifex
  license (Polyform Noncommercial — bars commercial use outright, no source-disclosure escape
  valve at all). This project is `license = "MIT"` and ALSO ships an HTTP API meant to run as a
  network service (invariant 25) — AGPL-3.0's network-use clause obligates anyone running a
  covered program as a network service to offer the combined work's complete source, and nothing
  in `LICENSE`/`README.md`/`pyproject.toml` ever disclosed this. Found while auditing the
  project's overall dependency licensing after a direct user question; the user decided to
  replace the dependency rather than relicense to AGPL, gate PDF support behind an extra, or
  merely disclose the risk.

  **`pypdfium2`** (BSD-3-Clause/Apache-2.0, wraps Google's PDFium — the engine Chromium itself
  uses) replaces `pymupdf`/`pymupdf4llm` in `parsers/pdf.py`. Verified permissive down to every
  bundled native dependency (`freetype`/`zlib`/`libpng`/`libtiff`/`libjpeg_turbo`/`libopenjpeg`/
  `lcms`/`icu`/`abseil` — no AGPL/GPL anywhere in the tree, confirmed by listing the actual bundled
  license files, not trusting the top-level metadata field alone). `Pillow` was ALSO added as an
  explicit direct dependency — `pypdfium2` declares zero runtime dependencies of its own, and
  `.render(...).to_pil()` only worked before by luck via `rapidocr-onnxruntime`'s own transitive
  dependency, the exact same "worked by luck until resolution shifted" class already documented
  for `python-multipart` (invariant 30) — caught proactively this time, before it broke anything.

  **`parsers/_ocr.py`** (new): RapidOCR primary, Tesseract fallback, hand-implemented now that
  `pymupdf4llm`'s built-in OCR dispatch goes away with it. Deliberately simpler than
  `pymupdf4llm`'s former ML-based OCR-need classifier — a plain "extracted text below a small
  character threshold" check, which does NOT catch a GARBLED-but-present text layer the way the
  old ONNX classifier did. This project's own actual scanned-PDF case (a page with no text layer
  at all) is unaffected; a bad-character-ratio heuristic for the garbled case is a smaller, later,
  independently-mergeable follow-up if it ever turns out to matter — a disclosed tradeoff, not
  silently assumed equivalent (CLAUDE.md invariant 7 has the full account).

  **`tests/_pdf_fixtures.py`** (new): builds test PDFs with `reportlab` (BSD), a `dev`-only
  dependency — never a runtime dependency of the shipped package. Replaces this project's former
  `fitz` (`pymupdf`) based fixture-building across THREE test files
  (`test_parsers_pdf.py`/`test_ingest.py`/`test_api.py`) — an independent pre-implementation audit
  found the first draft of this slice's design named only one of the three, before any code was
  written.

  **Also disclosed, not fixed here**: `edge-tts` (the default TTS provider) is LGPLv3 — lower
  risk (LGPL generally permits an unmodified dependency relationship from a permissively-licensed
  program without forcing that program under LGPL itself), but named in `README.md`'s new
  "Licensing" section rather than left undisclosed alongside everything else.
