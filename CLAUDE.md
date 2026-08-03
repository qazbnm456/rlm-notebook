# rlm-notebook — agent guide

`rlm-notebook` is a downstream consumer of [`rlm-kit`](https://github.com/qazbnm456/rlm-kit): paste
in sources of any kind (text, web pages, PDFs — including scanned/OCR'd ones), ask questions
grounded in them with a citation you can verify, and get a distilled research artifact out the
other end. See `README.md` for the overview.

`rlm-kit` is pinned as a git dependency (see `pyproject.toml`). For local co-development against an
in-progress rlm-kit checkout, install it editable over the top:

```
uv pip install -e ../rlm-kit
```

## Verify

- `uvx ruff@0.16.0 check .` — lint (line-length 110, matching rlm-kit/ctx-distillery's pin — an
  unpinned `uvx ruff check .` resolves the latest ruff at run time and can redden CI with nobody
  having touched a line of code).
- `uv run python -m pytest -q` — the whole suite, fully offline. The dspy-bearing test
  (`test_task.py`) drives a REAL `dspy.RLM.aforward` through `rlm_kit.testing.ScriptedInterpreter` +
  `scripted_lm`, so the planner → tools → SUBMIT chain executes for real (`importorskip("dspy")`).
  `test_api.py`/`tests/test_runner.py` need the `api` extra installed to be collected at all (CI's
  `uv sync --extra api` covers this — see `pyproject.toml`); without it they're silently absent
  from the run, not failing, so a bare local `uv sync` can look greener than CI actually is.
- A LIVE run additionally needs real model credentials and a Deno sandbox (`brew install deno`).
  Don't run it in CI; it costs money.
- Before claiming done, actually run both commands and paste the output.

## Scope note

Six slices in: ingestion (text / web / PDF, with local hybrid OCR), citation-grounded chat, a
persistent multi-turn `Notebook` (sources + history surviving across `ask` invocations, one JSON
file, no database), a Notebook Guide — `rlm-notebook guide {summary,faq,timeline,insight}`
generates a whole-corpus artifact (`guide.py`) — an Audio Overview — `rlm-notebook audio` generates
a two-host podcast script (`audio.py`) and synthesizes it to an MP3 (`tts.py`) — an HTTP API
(`api.py`, the `api` extra) over `POST/GET /notebooks/...`, `ask`, `guide/{kind}`, `audio`, `cancel`,
and now a live reasoning-trace stream + a citation-turn lookup — and a web UI (`rlm_notebook/web/`,
invariant 29), all 3 phases of its blueprint now shipped: a real end-user product surface
(Sources/Chat/Studio with Guide tabs, a podcast player, and a live "what is the model doing right
now" ticker fused with citations), NOT a replay-only trace console like the sibling projects'
`studio/`s. The API is the FIRST place a run is subprocess-isolated (`runner.py`/`worker.py`) rather
than in-process; `cli.py`'s synchronous in-process invocation is unaffected and unchanged. A
post-launch addendum (invariant 30) then wired the Sources panel's previously-inert "Paste text"
and "File" tabs to the API — `POST /notebooks/{id}/sources/upload` (`.pdf`/`.txt`/`.md` bytes) and
`add_sources`'s new `texts` field — the first Gemini-Notebook feature-parity gap closed after a
deliberate assessment named it the highest-priority one. Guide/Audio artifacts still aren't cached
onto a notebook or made citable as sources for later `ask` turns, there's still no trace-file
retention policy anywhere in this project, there's still no multi-worker `uvicorn` deployment story
for `_ACTIVE_RUNS`/`_RUN_PROCESSES`, and Word/Slides/Docs native-format parsing, YouTube/audio
source ingestion, and a source-text viewer (click a citation and jump to the highlighted original,
not just the reasoning trace) remain unbuilt. Each of these is its own follow-up slice; do not
assume any of them exist because an earlier design discussion mentioned them.

## Invariants — do not break

1. **No fetch/network tool is ever registered on the chat task's `RLMTask(tools=…)`.**
   `parsers/web.py`'s fetcher is called exactly once, host-side, during ingestion — never handed to
   the model at question-answering time. A source's own content is untrusted (see invariant 6); if a
   fetch tool were reachable from the REPL, an instruction hidden in that content could steer the
   model into exfiltrating notebook contents to an attacker-controlled URL, and `rlm_kit`'s SSRF
   guard (`is_safe_url`) only blocks internal/loopback/metadata targets — it does not, and cannot,
   block a legitimate-looking external domain. If a later slice wants "fetch one more page on
   request," that is a separate, explicitly user-confirmed, non-agentic action — not a tool the
   model decides to call.
2. **`parsers/web.py` re-validates the SSRF guard on EVERY redirect hop, not just the requested
   URL.** `_SafeRedirectHandler` runs `is_safe_url`/`resolved_host_is_safe` again on each `Location`
   target before following it. Without this, an initially-safe-looking URL could 302 to an
   internal/loopback/metadata address and the default `urllib` opener would follow it unchecked —
   `rlm_kit.tools.fetch`'s own docstring names this exact gap ("call it INSIDE your fetcher at
   connection time, and on every redirect hop"). Caught by an independent review of the first
   version of this module, which fetched with the default opener and had no per-hop check; verified
   against a real redirect target before landing the fix. Do not swap back to plain
   `urllib.request.urlopen`.
3. **Ingestion is host-side only, never inside the sandbox.** `parsers/{text,web,pdf}.py` run
   before any `RLMTask` exists. `pymupdf4llm`, `trafilatura`, and the OCR backends (invariant 7) are
   native/C-extension dependencies unsuited to the pyodide/deno sandbox rlm-kit builds by default —
   and untrusted parsing logic has no reason to run inside the same trust boundary as the model's
   own code anyway. `corpus.py` only ever hands the RLM a plain string, already parsed.
4. **The corpus blob uses `[[SRC:<id>|<locator>]]` markers, and EVERY citation-grounded task's
   instructions teach the model to treat them as opaque and echo them verbatim in a `Citation`.**
   This applies to `AnswerQuestion` (`task.py`) and all four Notebook Guide tasks (`guide.py`)
   alike — `instructions.py`'s `CITATION_RULES` is the ONE copy of this rule, imported by both
   modules rather than hand-duplicated (see invariant 13). Without an explicit rule the model has
   no reason to preserve an ad hoc marker format across `.find()`/slice operations, and
   `citations.py` (invariant 5) has nothing to verify against if it doesn't. **Residual risk, not
   yet verified**: the offline tests (`test_task.py`, `test_guide.py`) drive a scripted LM whose
   turns are fixed dicts — they prove the tool-wiring/SUBMIT chain works, not that a real model
   reliably copies a marker verbatim out of a multi-MB string it must locate itself. Treat that as
   unverified until a live run confirms it, not as covered.
5. **`citations.py` verifies coordinate existence only — never content faithfulness.** It confirms
   a claimed `source_id` exists and its `locator` resolves to real text in the corpus; it does NOT,
   and cannot cheaply, confirm the model's surrounding prose faithfully represents that text. Never
   let a docstring, log message, or UI copy imply a stronger guarantee than this — that gap is
   exactly the "grounded-but-not-verified" failure mode academic evaluations have found in
   NotebookLM itself (see the design discussion this was born from). A citation that fails
   coordinate verification is marked unverified, never silently dropped, never silently trusted.
6. **`injection_scan.py`'s flags are deterministic and additive — they gate nothing.** A flagged
   source's content still reaches the model and its answer still returns; the flag is metadata
   surfaced alongside the answer, unioned with (never overridden by) whatever the model itself
   concluded. This is a transparency mechanism, not a blocking one — do not wire it to refuse a
   run. Its patterns trade recall for precision on purpose (e.g. a paper *discussing* prompt
   injection as a topic can trip it) — that is an acceptable false-positive rate for a flag nobody
   is forced to act on; don't over-tighten it into false negatives chasing a clean read.
7. **OCR ships enabled by default, not merely pluggable-but-off.** `parsers/pdf.py` uses
   `pymupdf4llm`'s built-in hybrid OCR (RapidOCR primary, Tesseract fallback — both Apache-2.0, both
   CPU-only) for scanned/image PDF pages. The backends are core `dependencies` in `pyproject.toml`,
   not an opt-in extra — a plain `uv sync` installs them, no flag required. (An earlier draft of
   this project put them behind an `ocr` extra and CI's plain `uv sync` never installed them;
   caught by an independent review that reproduced the exact CI sync and got a real test failure.
   A sibling open-source project, `lfnovo/open-notebook` issue #819, shipped the same
   pluggable-but-not-installed-by-default mistake and image sources silently failed to parse in its
   Docker image — this is that pitfall, hit for real once, not a hypothetical.) A `vision_llm` OCR
   mode (reusing the already-configured multimodal `dspy.LM` for hard/handwritten pages) is a
   deferred follow-up, not yet implemented.
8. **`corpus.py` enforces a size cap on the assembled blob and fails loudly, not silently, past
   it.** The single-blob-as-REPL-variable design (rlm-kit's core mechanic) has a real memory
   ceiling in the pyodide/deno sandbox; a notebook that exceeds the cap must get a clear error at
   ingestion time, not a mysteriously failing/slow chat turn later. Known gap: `Corpus.blob()`
   currently concatenates every source in full *before* checking the length, so the cap catches an
   oversized notebook loudly but only after paying the memory cost of assembling it once — real
   memory-safety (abort while assembling) is a follow-up, not yet done.
9. **`AnswerQuestion` always runs in the `pyodide` sandbox; `NotebookConfig.from_env` refuses any
   other `RN_INTERPRETER` value rather than silently overriding it.** Matches the sibling projects'
   own pin (e.g. ctx-distillery's `PINNED_INTERPRETER`) — an operator who set `RN_INTERPRETER=local`
   believes something about this run that would not be true if the kit quietly corrected it; refusal
   makes the misconfiguration visible instead of teaching the wrong lesson.
10. **A notebook id is sanitized (`notebook.slug`) before it becomes a filename.** `--notebook` is
    user input and turns directly into `<notebooks_dir>/<slug(id)>.json`; the same
    strip-to-`[A-Za-z0-9._-]`-then-cap-length treatment ctx-distillery's `cli._slug` gives a run id,
    for the same reason — an unsanitized id could otherwise become a traversal segment (`..`, an
    absolute path, a nested directory) or blow past a filesystem's path-component length limit.
11. **`history` (prior conversation turns) is context only — it is never itself a source of facts
    or citations.** `AnswerQuestion.instructions` says so explicitly, and nothing in `citations.py`
    special-cases a citation just because a similar one appeared in an earlier turn: every citation
    in every answer is verified fresh against the CURRENT `sources` blob (invariant 5), regardless
    of what history says was cited before. A past answer being wrong, or a source having been
    removed since, must not be inherited into a new one. **Residual risk, not yet verified** (the
    same class as invariant 4's): the offline test drives a scripted LM with a fixed
    `history="(no prior turns in this conversation)"` — it cannot demonstrate that a real model,
    handed a history containing an EARLIER citation, reliably treats that citation as inert context
    rather than something to reuse or re-cite without re-deriving it from `sources`. Treat that as
    unverified until a live run confirms it, not as covered.
12. **Extending an existing notebook with `--source` dedupes by origin, and never reassigns an
    existing source's id.** `notebook.existing_origins` + `cli._ingest_new`'s `skip_origins` make
    re-passing the same path/URL on a later turn a no-op rather than a duplicate; new sources are
    numbered starting from `len(notebook.sources) + 1`, so a source already cited in a saved
    `ChatTurn.answer` can never have its id silently repointed at different text on a later `ask`.
13. **Every citation-grounded RLMTask shares its citation-marker and validate-before-submit
    instructions from `instructions.py` (`CITATION_RULES`, `validate_before_submit_rule(...)`) —
    not a hand-copied paragraph per task.** `AnswerQuestion` and the four Notebook Guide tasks
    (`GenerateSummary`/`GenerateFAQ`/`GenerateTimeline`/`GenerateKeyInsight`) each compose the SAME
    two shared pieces onto their own task-specific opening. A wording fix to either shared piece
    must never be applied to just one task's local copy — there should be no local copy to apply
    it to. **The task-specific opening (including its "ground only in sources" sentence) is
    deliberately NOT unified across all five** — `AnswerQuestion`'s says so for a missing *answer*
    to a question, the four Guide tasks' (`guide.py:_grounded_instructions`) says so for an
    unsupported *claim* in a generated artifact — different enough failure modes that forcing one
    shared sentence would blur one of them; don't read this invariant as claiming that opening is
    shared too. `cli._prepare` is the same "one copy, not five" discipline applied to the
    ingestion/notebook setup `ask` and `guide` both need before running their own task; don't
    reintroduce a second copy of that setup either.
14. **TTS synthesis (`tts.py`) runs entirely host-side, on an already-generated,
    already-schema-validated `PodcastScript` — it is never a tool the model can call, and
    `GeneratePodcastScript` (`audio.py`) has no dependency on `tts.py` at all.** Same reasoning as
    invariants 1/3: audio synthesis is a real network call to a TTS provider, and the model's job
    (writing a grounded script) is finished long before any audio is generated. Don't wire
    synthesis into the RLM loop, e.g. as a tool the script-writing task could call mid-run.
15. **The default TTS provider (`RN_TTS_PROVIDER=edge-tts`) needs no API key or paid account, so
    `rlm-notebook audio` works out of the box** — the same "ship a working default, not just a
    pluggable interface" reasoning as OCR (invariant 7). The known-provider list lives in ONE
    place, `tts.py`'s `_PROVIDERS` dict (`get_tts_provider` refuses loudly on an unknown name) —
    unlike `RN_OCR_PROVIDER`, `config.py` does NOT keep a second copy of the known-provider list to
    validate against; don't add one; a second list is exactly the kind of thing that drifts.
    Instead, `cli._cmd_audio` calls `get_tts_provider(config.tts_provider)` and handles its
    `TTSError` BEFORE running `GeneratePodcastScript` (invariant 19) — that's how a bad provider
    name gets caught early without a second validated list.
19. **`cli._cmd_audio` resolves the TTS provider before running the (potentially expensive)
    script-generation model call, not after.** An independent review found and reproduced the
    original ordering wasting a real model call whenever `RN_TTS_PROVIDER` was misconfigured — the
    error only surfaced as an uncaught `TTSError` once the transcript had already been generated
    and printed. Don't move `get_tts_provider(...)` back after `GeneratePodcastScript().run(...)`.
    Relatedly, `tts.py`'s `EdgeTTSProvider.synthesize` now wraps its file WRITE in the same
    try/except as the network synthesis call — an independent review reproduced (against the real
    edge-tts network service, not just an offline fake) that a bad `--out` directory used to raise
    an uncaught `OSError` after synthesis had already succeeded and spent a real network call; both
    are one "make this file exist" operation as far as any caller is concerned and share one error
    boundary now.
16. **`PodcastScript.utterances` may legitimately be empty, and `cli._cmd_audio` says so
    explicitly rather than printing nothing** — the same allowance and the same UI fix
    `Timeline.events`/`FAQ.items` already have (see the Notebook Guide's own history in
    CHANGELOG.md for why "silently prints nothing" was a real bug there, not a hypothetical one).
17. **`EdgeTTSProvider` synthesizes one utterance at a time (one voice per `edge-tts` call) and
    concatenates the raw MP3 byte streams — it does not re-encode.** This is a deliberate,
    documented tradeoff (`tts.py`'s docstring) to avoid an `ffmpeg`/`pydub` dependency (`ffmpeg` is
    a system binary, not pip-installable) for what would only be a gapless-playback cosmetic
    improvement; don't "fix" the concatenation without weighing that dependency cost first.
18. **The Audio Overview's cast is a fixed two hosts, `host_a`/`host_b` (`schema.Speaker`), not
    freely-named per episode.** Keeps `Utterance.speaker` a closed enum citations/voice-mapping
    can rely on, and keeps `RN_TTS_VOICE_HOST_A`/`_B` a fixed two-variable surface rather than an
    open-ended per-episode cast configuration — a deliberate MVP scope cut, not an oversight.
20. **`ingest.py`/`notebook.py` (`is_url`/`ingest_one`/`ingest_new`, `load_or_create`,
    `extend_with_sources`) are shared by `cli.py` AND `api.py` — neither entry point depends on the
    other.** `cli.py` used to own this logic outright; it was extracted here once `api.py` needed
    the identical "get me a notebook, ingest new sources into it" step, so a fix to one entry
    point's source-handling can't be applied to only one of the two by accident. Don't reach into
    `cli.py` from `api.py` (or the reverse) for anything — if both need it, it belongs in a shared,
    entry-point-agnostic module.
21. **Every API request that runs an `RLMTask` does so in an isolated subprocess
    (`runner.py`/`worker.py`), never in-process.** This is a SEPARATE execution model from
    `cli.py`'s synchronous in-process one — the two coexist; `cli.py` is completely unaffected.
    `worker.py` is the ONLY module in this project's process tree that imports `dspy`/`rlm_kit`
    from an API request path; `api.py` itself never does, so a crash deep in the model stack takes
    down a worker subprocess, never the API server process itself.
22. **Cancellation works via `killpg` on the WHOLE process group (`start_new_session=True` when
    spawning), not just the worker's own PID.** Verified with a real test
    (`test_runner.py::test_cancel_kills_the_whole_process_group_not_just_the_leader`) that spawns
    an actual grandchild subprocess and confirms it dies too when the run is cancelled — a stuck
    Deno grandchild in a real run must not survive as an orphan after its parent worker is killed.
    Don't simplify this to `process.kill()` (which only signals the worker's own PID).
23. **`api._ACTIVE_RUNS` is a single-process, in-memory map with ONE SLOT PER NOTEBOOK ID — two
    distinct, documented limitations, neither a silent bug.** (a) There is no multi-worker/
    multi-process `uvicorn` deployment story: running more than one worker process gives each its
    own copy of this dict, and `POST .../cancel` only reaches whichever worker happens to hold the
    request. (b) Two concurrent requests against the SAME notebook id share one slot: the second
    overwrites the first's entry, so `/cancel` can only ever reach the MOST RECENT of the two — the
    first still finishes or times out on its own, just not cancellable through this API. An
    independent review verified (b) is a capacity limitation, not a race: each request's `finally`
    only clears its OWN entry (an `is run` identity check), confirmed with an interleaved-`asyncio`
    test, so the overwrite/cleanup itself never corrupts state. A per-run-id (rather than
    per-notebook-id) registry would remove limitation (b); deferred, not implemented here.
24. **`api._config()` converts `NotebookConfig.from_env()`'s `SystemExit` into an HTTP 500, rather
    than letting it escape a request handler.** `cli.py` lets the same `SystemExit` propagate and
    exit the process, which is correct for a one-shot CLI invocation — it is NOT correct for a
    long-running server process, where an unhandled `SystemExit` inside a request handler is a
    crash, not a clean error response. Verified against a real running server (`curl`, not just the
    mocked test suite) before landing this: an unset `RN_MAIN_MODEL` now returns a clean 500 with
    the same message `cli.py` would have printed, not a broken connection. Every `SystemExit`
    source in `config.py` (`from_env`'s own checks, `_env_int`/`_env_float`/`_ocr_provider_from_env`)
    is reachable only through `from_env()`, and every `api.py` call site uses `_config()`, never
    `NotebookConfig.from_env()` directly — confirmed by an independent review; don't add a new
    direct call that bypasses this wrapper.
25. **This API has NO authentication or authorization of any kind.** Any caller can create,
    extend, query, `ask`/`guide` against, or cancel a run for ANY `notebook_id` — there is no
    concept of an owner. It is meant for local or otherwise fully-trusted-network use only (the
    same posture ctx-distillery's studio takes for its own reasons); do not expose it to an
    untrusted network without adding auth first, which this slice does not attempt. Both `api.py`'s
    module docstring and `README.md` say so explicitly — don't let that warning quietly disappear
    in a later edit. `GET /notebooks` (invariant 29) extends this posture from "any id is reachable
    if you know it" to "every id is enumerable without knowing it" — reviewed and accepted as part
    of that slice, since the response is metadata only (ids, source counts, turn counts — never
    source text or answers), not a new category of exposure.
26. **`add_sources` accepts ONLY http(s) URLs, never a local file path — unlike `cli.py`'s
    `--source`.** `ingest.ingest_one` treats any non-URL string as a path on the machine running
    the process and reads it with no allowlist or directory boundary; that is a reasonable design
    for a CLI whose operator already trusts their own machine (invariant 3's ingestion model was
    built for that trust boundary), and an unauthenticated arbitrary-file-read vulnerability the
    moment the same function is reachable over an unauthenticated HTTP endpoint (invariant 25 — no
    auth at all). An independent review reproduced the full attack end to end: `POST
    {"sources": ["/etc/passwd"]}` read the file, and a mocked `ask` echoed its contents back through
    a citation that passed coordinate verification. Fixed by rejecting any non-URL value in
    `add_sources` before it ever reaches `extend_with_sources`. Local files still only ever reach a
    notebook through the CLI, which has a different, legitimate trust boundary. If a later slice
    wants the API to accept file uploads, that needs its own explicit multipart-upload design — not
    quietly re-widening this check back to accept arbitrary paths.
27. **Every endpoint that resolves a notebook by id catches BOTH `pydantic.ValidationError` (a
    corrupted notebook file → 409) AND `ValueError` (an invalid id that `notebook.slug` reduces to
    an empty token, e.g. `"!!!"` → 400) — not just the first.** An independent review reproduced an
    unhandled `ValueError` escaping as a raw 500 on all four id-taking endpoints
    (`GET /notebooks/{id}`, `sources`, `ask`, `guide/{kind}`) before this fix, using nothing more
    exotic than a notebook id made entirely of punctuation. `cancel` is unaffected (it never calls
    `load_notebook`/`load_or_create`). Route path-traversal payloads (e.g. `../../../tmp/evil`) were
    checked too and do NOT reach this code path at all — Starlette's default path converter refuses
    to match a literal `/` inside a single `{notebook_id}` segment, so those 404 at the routing
    layer before any handler runs; don't assume that protection is this project's own code, though —
    it's a framework default, worth re-checking if the route ever changes shape.
28. **`cli._GUIDE_TASKS` and `api._GUIDE_TASKS` are two independent registries, kept in sync by a
    tripwire test (`test_api.py::test_guide_task_registries_stay_in_sync_between_cli_and_api`), not
    by sharing code** (invariant 20 already explains why `api.py` doesn't import from `cli.py`).
    Add a new `guide` kind to BOTH dicts, or the tripwire fails immediately rather than the two
    silently drifting — the same class of gap an earlier review found in `cli._SPEAKER_LABELS`
    before this slice added the analogous test here proactively.

29. **The web UI (`rlm_notebook/web/`) is a real end-user product surface, not another instance of
    the sibling projects' replay-only trace console.** `ctx-distillery`/`cve-reverser`/`diff-sentry`/
    `toolscout` each ship a `studio/` that is a single-verdict security/review console (one input,
    one derived-state card, a Trajectory replay drawer); this project's persistent, multi-notebook,
    multi-turn knowledge workspace is structurally different, and the divergence is a recorded
    design decision (`docs/design/web-ui-blueprint.md`'s §0), not an oversight. Zero-build vanilla
    HTML/CSS/JS, same family convention as the siblings' own `studio/` stacks — no framework, no
    build step. Assets live under `rlm_notebook/web/`, NOT a top-level `web/` — a top-level directory
    has no entry in `pyproject.toml`'s `[tool.hatch.build.targets.wheel] packages` list and would
    silently vanish from an installed wheel (caught by an independent pre-implementation design
    audit, verified fixed by actually building a wheel and confirming the assets are inside it, not
    by trusting the fix's own commit message). `app.js` builds every DOM node that could carry
    model- or source-derived content (citation spans, source list rows) via `createElement`/
    `textContent`/`element.title` — NEVER `innerHTML` with an interpolated string — because a
    citation's `source_id`/`locator`/`quote` could in principle echo attacker-supplied text from a
    prompt-injected source (invariant 6: injection-scan flags are advisory, not a filter); an
    earlier version of this file built a citation's `title` attribute via string concatenation,
    found and fixed before it ever shipped. This is the same "textContent only" discipline the
    sibling studios' own `app.js` files already enforce, for the identical reason.

    A full three-phase blueprint exists (`docs/design/`, gitignored, same convention as
    `docs/research/`). Phase 1 (web shell, Sources, Chat, `GET /notebooks`,
    `GET /notebooks/{id}` now returning full turn history instead of a count) and Phase 2 (Guide
    tabs + podcast player) are both shipped. Phase 2 added `POST /notebooks/{id}/audio`, split into
    TWO host-side steps rather than one: `GeneratePodcastScript` runs in the same isolated
    subprocess `ask`/`guide` already use (the only step that's cancellable via
    `POST .../cancel`); TTS synthesis then runs AFTER that subprocess returns, IN-PROCESS inside
    `api.py` itself, dispatched through `asyncio.to_thread` specifically because
    `EdgeTTSProvider.synthesize()` internally calls `asyncio.run(...)`, which raises if invoked from
    a running event loop (this handler's own) — `tts.py`'s own docstring had already flagged this
    exact scenario as the caller's responsibility to route around, not something `synthesize()`
    itself should change. No audio is ever persisted past one request (a temp file, deleted in a
    `finally` that covers BOTH the success and the synthesis-failure path, not just the former —
    caught and fixed by this phase's own pre-implementation audit before it was ever code); the
    response is JSON with base64-encoded audio, never a raw binary body, so error handling stays
    uniform with every other endpoint. Known, accepted limitation: only the script-generation half
    of `/audio` is cancellable — by the time synthesis begins, `_run_isolated`'s `finally` has
    already cleared this notebook's `_ACTIVE_RUNS` entry, so a stuck synthesis call blocks its
    request with no `killpg`-equivalent to reach it.

    **Phase 3 (a live reasoning-trace ticker fused with citations) is shipped.** Its original
    design was pulled and redesigned before implementation — the redesign resolved all three of the
    original blockers:

    - **The client picks the run id, never the server** (`RunOptions.run_id`, a shared optional
      body field on `ask`/`guide`/`audio`). A server-generated id never reaches a client mid-run;
      a client-supplied one lets the caller open `GET /notebooks/{id}/runs/{run_id}/stream` before
      or alongside the request that will populate it — the same pattern `toolscout-studio` already
      ships (a previewed run id the solve call sends explicitly). `_derive_run_id` sanitizes a
      given token through the SAME whitelist `notebook.slug()` uses (it becomes a filename
      component) and always prefixes it with `notebook_id` — never the client's raw value alone.
    - **`_run_isolated` exclusively creates `traces/{run_id}.jsonl` before spawning anything** —
      `os.open(path, O_CREAT|O_EXCL|O_WRONLY)`, mapped to a 409 on `FileExistsError`. Not
      optional hardening: `TraceRecorder`'s own lock (`rlm_kit/trace.py`) is process-local and
      gives ZERO cross-process serialization, so two concurrent requests landing on the same
      run_id — two browser tabs, a retried request, nothing in this no-auth API prevents it —
      would otherwise have two independent worker subprocesses append interleaved,
      duplicate-`step_id` events to one file. A collision found during this phase's own
      pre-implementation audit, not a hypothetical. If the exclusive-create succeeds but
      `runner.start_run` then fails to spawn, the just-reserved (still-empty) file is unlinked
      before the error propagates — otherwise a failed spawn permanently occupies that run id and
      a legitimate retry gets a false 409 forever.
    - **`_RUN_PROCESSES` (run-id-keyed) is a SEPARATE map from `_ACTIVE_RUNS` (notebook-id-keyed),
      deliberately not reused.** An earlier draft of this phase's own design planned to reuse
      `_ACTIVE_RUNS` to detect a cancelled/dead run for the trace stream's termination logic — a
      second audit round found this misfires under ordinary same-notebook concurrency: invariant
      23's single slot per notebook id means a second concurrent request overwrites the first's
      entry, which would make the FIRST run's stream falsely conclude it was cancelled the moment
      a second one starts. `_RUN_PROCESSES` is keyed by the actual (now-guaranteed-unique) run id
      instead, so two concurrent runs on one notebook get two independent, non-colliding entries.
    - **Citation-to-turn linking is a separate, small lookup endpoint**
      (`GET /notebooks/{id}/runs/{run_id}/citation-turn?source_id=&locator=`), not a reuse of the
      live stream — searches a trace's events in step order for the first one whose ENTIRE
      serialized payload (`json.dumps(event["payload"])`, not a fixed field list) contains the
      literal marker `[[SRC:<source_id>|<locator>]]`. Searching the whole payload rather than named
      fields is itself a fix: an earlier draft hardcoded `reasoning`/`code`/`output`, which a
      second audit round found is simply the WRONG field list for a `sub_call` event
      (`rlm_kit.sub_lm`'s real keys are `kind`/`name`/`model`/`attempt`/`input`/`raw`/`processed`/
      `error`) — a citation whose marker only appears in a sub-LM escalation would have silently
      404'd. `schema.ChatTurn.run_id` (new, optional, backward-compatible) is the ONE schema
      change this needed — Guide/Audio results still aren't persisted onto a notebook at all
      (unchanged scope), so their citation links only need to work within the current browser
      session, which the client's own already-in-memory run id already satisfies with no server
      round-trip. `citation_turn` checks `run_id` actually belongs to `notebook_id`
      (`run_id.startswith(f"{notebook_id}-")`) — a follow-up completion check found `stream_run`
      lacked the same check, fixed in a small post-merge commit so both endpoints apply it
      consistently.

    **Known, stated limitations, not solved by this phase**: no trace-file retention policy exists
    anywhere in this project (a citation's "view reasoning" link is only as durable as a file
    nobody has committed to keeping — a missing trace degrades that ONE affordance, never the rest
    of the page); the marker-search endpoint is a heuristic (finding the marker text proves the
    model's REPL saw it, never that this occurrence is what the model relied on — the same
    "coordinate, not faithfulness" limit invariant 5 already states for citation verification
    generally), and a `sub_call` event's `input` field is truncated to 4000 characters upstream
    (`rlm_kit.sub_lm`), a real (if partial) source of false negatives. The trace stream and
    citation-turn endpoints are a MATERIALLY DIFFERENT exposure than every other endpoint in this
    API — unlike metadata-only or model-authored-prose responses, a trace can contain full ingested
    source text the model echoed while reading it; both inherit invariant 25's no-auth posture as a
    sharper version of the same accepted risk, not a new category of it.

30. **`POST /notebooks/{id}/sources/upload` and `add_sources`'s `texts` field never reopen
    invariant 26's local-path ban — they add a genuinely different, safe mechanism alongside it,
    never a way around it.** Invariant 26 forbids a local-path STRING because the server would read
    an arbitrary file off its own machine; file upload is the opposite shape — the server only ever
    receives opaque bytes the caller already had, plus a claimed filename used solely for
    extension-based kind detection (`.pdf`/`.txt`/`.md` only, `ingest.ingest_uploaded_file`) and
    display. Pasted text has no path at all — `ingest.ingest_pasted_text` gives it a
    content-derived origin (a readable snippet plus a hash, not a bare hash — a bare hash was found
    during design to be a real UX regression, since the Sources list renders `origin` verbatim as
    its only label).

    **The upload size cap does not work the way a first draft assumed, and the fix was verified
    live before landing.** Declaring the endpoint the natural FastAPI way
    (`file: UploadFile = File(...)`) would make FastAPI itself parse the ENTIRE multipart body,
    inside its own request-handling code, BEFORE the handler (or any in-handler `Content-Length`
    check) ever runs — confirmed against the installed version: a 5MB body was already fully read
    and spooled to disk the instant the handler started, with an ACCURATE `Content-Length` header,
    not just in a chunked-encoding edge case. Starlette's own `max_part_size` never applies to file
    parts either, only plain form fields — so there is no framework-level backstop at all regardless
    of any app-level cap declared the obvious way. Fixed by taking `request: Request` directly
    (no `File(...)` parameter), so FastAPI never eagerly parses anything — `upload_source` checks
    `Content-Length` FIRST and only calls `request.form()` once that check already clears
    `config.max_upload_bytes()` (`RN_MAX_UPLOAD_BYTES`, default 50MB). A missing `Content-Length`
    (chunked transfer encoding) is refused outright (411), not accepted with a disclosed gap — there
    is no safe way to bound an unknown-length body before reading it. Verified live (a standalone
    test app, a 5MB POST against a 1000-byte cap) that the fixed shape genuinely never calls
    `request.form()` when the declared size already exceeds the cap, before this was believed rather
    than just reasoned about.

    **Deliberately NOT gated behind `NotebookConfig.from_env()`.** `config.max_upload_bytes()` is a
    standalone function, not a `NotebookConfig` field — `from_env()` raises `SystemExit` (a 500 via
    `_config()`) whenever `RN_MAIN_MODEL` is unset, correct for `ask`/`guide`/`audio` (they actually
    run a model) but would be a real bug here: uploading a source has nothing to do with whether a
    model is configured, and `add_sources` (the existing URL-based path) already reflects this by
    never calling `_config()` either. Caught while designing this, not left for a later audit.

    **Scope, deliberately not attempted here**: Word/Slides/Docs native-format parsing (would need
    new parser dependencies — this only wires up the two parsers that already existed, PDF and
    plain text/markdown); multi-file batch upload (matches the Sources panel's single-file
    `<input>`, no `multiple` attribute).

31. **`GET /notebooks/{id}/sources/{source_id}` returns a source's FULL text, every block — a
    materially different exposure than every other endpoint here except the trace stream/
    citation-turn lookup (invariant 29's Phase 3 paragraph already names that pair; this is the
    third).** Before this endpoint, no caller could read more of a source than the short `quote`
    strings a citation happens to include. It reuses `corpus.Corpus.get(source_id)` — the SAME
    lookup `citations.py` already performs on every `ask`/`guide` request — rather than a second
    hand-rolled scan; `Corpus.get` was confirmed cheap (a linear scan already proven fine at
    citation-verification time) before reuse, not assumed. CLAUDE.md invariant 25's no-auth
    posture already covers this in spirit (the model itself already has the whole corpus), but the
    endpoint SURFACE returning full source text is new and worth its own line rather than folding
    silently into "same as everything else."

    **The web UI's citation-list row is now the primary click target for the source-text viewer —
    NotebookLM's most basic closed loop (click a citation, see the highlighted original passage) —
    with the pre-existing reasoning-trace view demoted to a secondary per-row `⌁ trace` icon.**
    `app.js`'s `.citation-row` is clickable regardless of whether the citation's `quote` matched
    inline in the answer text (an inline-match miss still leaves the citation in the list below,
    per the row's own pre-existing comment — before this slice that case had NO way to open
    anything at all). The trace icon inside each row calls `event.stopPropagation()` so the two
    click targets never double-fire. A brand-new `AbortController`-based staleness guard
    (`sourceViewerAbort`, module-level, aborted and replaced on every open) protects the new
    `showSourceViewer` fetch; the audit that designed this endpoint found the SAME class of defect
    already present, unfixed, in the pre-existing `showCitationTurn` (Phase 3) and it was retrofit
    with an equivalent guard (a monotonic token on `detailArea` itself, chosen over
    `AbortController` there since it's a plain GET with no browser-level cleanup to invoke) in the
    same slice — don't reintroduce either gap in a future citation-detail fetch path.

    **Known, pre-existing, explicitly NOT fixed here**: `notebook.py`'s module docstring assumes
    "exactly one writer at a time," true when only `cli.py` existed but false now that `api.py`
    serves concurrent HTTP requests with zero per-notebook locking — two concurrent
    `POST /notebooks/{id}/sources` calls on the SAME notebook can silently discard one via
    `save_notebook`'s non-merging atomic-file-replace. `Corpus.add()`'s duplicate-id dedup guard is
    dead code: nothing in the real ingestion path calls it. Found by this slice's own
    pre-implementation audit; a per-notebook lock (or a merging write) is a separate, tracked
    follow-up, not a blocker for a read-only endpoint.

32. **Notes (`schema.Note`, `Notebook.notes`) are freeform, uncited text — grounded and citable
    only once PROMOTED into a real `Source`, never before.** A note may have originated as a copy
    of a citation-grounded `Answer`'s text (the web UI's "+ Save as note" button), but the note
    itself carries no `citations` and is never re-verified against `sources` — invariant 5's
    coordinate-only guarantee doesn't extend to it. `notebook.promote_note` is the ONLY path a
    note's text ever reaches `notebook.sources`, and it reuses `ingest.ingest_pasted_text`
    UNCHANGED (the same function `add_sources`'s pasted-text field already goes through) rather
    than a parallel ingestion path — a promoted note gets the identical content-derived-origin,
    dedup-by-origin, and injection-scan treatment any other pasted text already gets. Promotion
    removes the note from `notes` regardless of whether a new source was actually appended (a
    dedup hit against already-identical text returns `None` and appends nothing) — promotion is a
    completed user action either way, and the endpoint always returns the full, ground-truth
    `NotebookResponse` so a client distinguishes outcomes by diffing `sources`/`notes`, never by an
    ambiguous status code.

    **A note id is assigned from the MAX id among currently-live notes, never from `len(notes) +
    1`** (`notebook._next_note_id`) — a real bug, not a style preference. An independent completion
    check found and reproduced live that `len(notes) + 1` lets TWO LIVE notes share one id the
    moment a non-last note is deleted (e.g. notes `n1`/`n2`, delete `n1`, add a third — the old
    scheme computed `n2` again, colliding with the note still alive under that exact id); since
    `delete_note`/`promote_note` both act BY id, the collision made either one silently affect
    BOTH same-id notes at once — a promoted note's colliding sibling was discarded with no source
    ever created for it and no error raised. `_next_note_id` fixes this at the root (derived from
    the max id actually in use, so a new id can never collide with one still alive); `delete_note`/
    `promote_note` ALSO now remove exactly the first matching note by index rather than filtering
    every id-equal match, as defense in depth on top of the id fix, not instead of it. An id CAN
    still be reused once NO live note holds it (e.g. every note gets deleted, then a new one is
    added) — that case is genuinely safe and unchanged.

    **`DELETE /notebooks/{id}/notes/{note_id}` is the first `DELETE` route in this API** — every
    other mutator here is a `POST`. Uses `_load_notebook_or_404` (an existing note can only be
    deleted from an EXISTING notebook, matching `ask`/`guide`'s existing-notebook-only precedent),
    unlike `POST /notebooks/{id}/notes` itself, which uses `load_or_create` like `add_sources` (a
    brand-new notebook can start life by adding a note).

    **The "+ Save as note" button lives in `renderTurn` (Chat's own call site), never inside the
    shared `renderAnswerWithCitations`.** That shared function is called from SIX sites (Chat plus
    all four Guide-kind renders and the podcast transcript) — an earlier design draft would have
    added the button INSIDE the shared function, leaking it onto Guide/Podcast artifacts, which are
    generated output, not conversational turns a user is meant to curate into notes. Caught by an
    independent pre-implementation audit before any code was written, not found live afterward:
    don't move this button call into the shared function even as a "simplification."

33. **YouTube source ingestion (`parsers/youtube.py`) fetches CAPTIONS ONLY — never the video or
    audio stream.** A deliberate, user-confirmed MVP scope decision (two real technical forks —
    captions-only vs. full audio-download-plus-transcription, and if the latter, local Whisper vs.
    a cloud API — were put to the user directly rather than assumed); no `ffmpeg`, no Whisper, no
    transcription API key. A YouTube video with neither official nor auto-generated captions is a
    clean, loud ingestion-time error (`CaptionError`), never a silent empty/partial source. Full
    audio transcription, if ever wanted, is a separate, later, independently-mergeable follow-up —
    this invariant does not half-build it.

    **A real, accepted ToS/legal caveat, not glossed over**: YouTube's Terms of Service prohibit
    automated access outside interfaces it provides; `yt-dlp` (a core, not opt-in, dependency —
    same "ship a working default" reasoning as OCR/TTS, invariants 7/15) operates in the same
    long-standing gray area every YouTube-downloading tool does. Fetching only the caption track is
    narrower/lower-risk than downloading media, but is not risk-free — the risk is accepted by
    whoever DEPLOYS this project, not invented by it. `README.md` states this explicitly.

    **`CaptionError` is a `ValueError` subclass, found necessary by this feature's own
    pre-implementation audit before any code was written.** `cli._prepare` and `api.add_sources`
    both catch ingestion failures as `except (FetchError, ValueError, OSError)`; a bare
    `RuntimeError` (the first draft's plan) would satisfy neither, landing a captionless video as
    an unhandled 500 (API) / raw traceback (CLI) instead of the clean error this invariant's
    opening promises. Verified live and with a dedicated test
    (`test_add_sources_reports_422_not_500_on_a_captionless_youtube_video`) — don't reopen this by
    giving a future ingestion-failure exception a base class outside that tuple without updating
    both call sites.

    **`parsers/youtube.py`'s WebVTT parsing (`_parse_vtt`) is built against REAL caption dumps, and
    two real bugs were found and fixed against that real data before this shipped, not assumed
    correct from reasoning alone.** (1) A first design keeping only each cue's LAST non-blank line
    correctly extracts an auto-caption "building" cue's current text, but WRONGLY drops real
    content from a genuine multi-line OFFICIAL dialogue cue (verified against a real official
    track: a cue's two display-wrapped lines are both real dialogue, not an "old line / new line"
    pair) — fixed by keying the extraction rule on whether a cue's raw text contains ANY `<...>`
    tag markup at all (a reliable signal: official subtitles never carry `<c>`/timestamp tags,
    auto-captions emit them ONLY on a building cue): a tagged cue keeps its last non-blank
    stripped line; an untagged cue joins ALL its non-blank lines. (2) The cue-boundary check
    originally treated a whitespace-only line the same as a truly empty separator line
    (`lines[i].strip() != ""`) — but real auto-caption VTT uses a SINGLE-SPACE line as part of a
    cue's own two-line payload (the "old" half of the rolling-karaoke pair), so that check
    silently dropped entire cues. Fixed: cue-boundary detection checks EXACT emptiness
    (`lines[i] != ""`); content-extraction still treats a whitespace-only line as blank CONTENT —
    two different notions of "blank" at two different steps, not the same check reused. Both bugs
    were caught by running the real parser against real fetched VTT data, not by reasoning about
    the algorithm in the abstract — `tests/test_parsers_youtube.py`'s fixtures are real captured
    dumps for this reason, and a live end-to-end run (`parse_youtube` against a real public video,
    both the official AND auto-generated caption paths) was re-verified after each fix.

    **A `"ts:<mm:ss>"` (or `"ts:<h:mm:ss>"`) locator prefix, alongside the existing `"whole"`
    (text/web) and `"page:<n>"` (pdf) conventions** — coarser than a single caption cue (a fixed
    `_CHUNK_SECONDS = 120` window), the same "start coarse, refine later if it turns out to
    matter" precedent the Scope note already applies to text/web's own single `"whole"` locator.
    Locator is fully opaque everywhere it matters (`citations.py`/`instructions.py`'s
    `CITATION_RULES` never parse or pattern-match it) — this new prefix breaks nothing.

    **`_fetch_caption_track` reuses `parsers/web.py`'s already-hardened, already-audited `_opener`
    (built with `_SafeRedirectHandler`) directly, rather than a bespoke unguarded fetch** — an
    independent audit's recommendation: the caption URL is resolved by `yt-dlp` from YouTube's own
    official `timedtext` API response, never extracted from untrusted source content, so it
    doesn't carry `parse_web`'s attacker-controlled-redirect threat model invariant 2 defends
    against — but reusing the existing hardened opener costs nothing and removes the
    (already-judged-small) residual risk entirely rather than reasoning it away. `web.py` itself
    is UNCHANGED by this reuse.

See `CHANGELOG.md` for what shipped in the current slice and why.
