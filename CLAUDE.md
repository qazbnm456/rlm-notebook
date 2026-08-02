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

Five slices in: ingestion (text / web / PDF, with local hybrid OCR), citation-grounded chat, a
persistent multi-turn `Notebook` (sources + history surviving across `ask` invocations, one JSON
file, no database), a Notebook Guide — `rlm-notebook guide {summary,faq,timeline,insight}`
generates a whole-corpus artifact (`guide.py`) — an Audio Overview — `rlm-notebook audio` generates
a two-host podcast script (`audio.py`) and synthesizes it to an MP3 (`tts.py`) — and now an HTTP
API (`api.py`, the `api` extra) over `POST/GET /notebooks/...`, `ask`, `guide/{kind}`, and
`cancel`. The API is the FIRST place a run is subprocess-isolated (`runner.py`/`worker.py`) rather
than in-process; `cli.py`'s synchronous in-process invocation is unaffected and unchanged. The API
has no `/audio` endpoint and no SSE/progress streaming yet (both deferred — see CHANGELOG), and
Guide/Audio artifacts still aren't cached onto a notebook or made citable as sources for later
`ask` turns. Each of these is its own follow-up slice; do not assume any of them exist because an
earlier design discussion mentioned them.

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
    in a later edit.
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

See `CHANGELOG.md` for what shipped in the current slice and why.
