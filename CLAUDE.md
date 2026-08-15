# rlm-notebook — agent guide

`rlm-notebook` is a downstream consumer of [`rlm-harness`](https://github.com/qazbnm456/rlm-harness): paste
in sources of any kind (text, web pages, PDFs — including scanned/OCR'd ones), ask questions
grounded in them with a citation you can verify, and get a distilled research artifact out the
other end. See `README.md` for the overview.

`rlm-harness` comes from PyPI, pinned to an exact version (see `pyproject.toml`). For local
co-development against an in-progress rlm-harness checkout, install it editable over the top:

```
uv pip install -e ../rlm-harness
```

**This file is the RULEBOOK: each invariant is what must hold, plus why it exists so a later reader
does not "simplify" it away. The incident that produced it — who found it, what was measured, which
draft was wrong — lives in `CHANGELOG.md`.** Put new history there, not here.

## Verify

- `uvx ruff@0.16.0 check .` — lint. **`line-length = 110` is a FORMATTER setting and is NOT
  enforced by `check`**: ruff's default rule set has no `E501`, so over-long lines pass (about 20
  are in the tree). Enabling `E501` is a real follow-up; until then it is a convention kept by
  hand. The version is pinned because an unpinned `uvx ruff check .` resolves the latest ruff at
  run time and can redden CI with nobody having touched a line of code.
- `uv run python -m pytest -q` — the whole suite, fully offline. `test_task.py` drives a REAL
  `dspy.RLM.aforward` through `rlm_harness.testing.ScriptedInterpreter` + `scripted_lm`.
  `test_api.py`/`tests/test_runner.py` need the `api` extra to be COLLECTED AT ALL — without it
  they are silently absent, not failing, so a bare local `uv sync` can look greener than CI. **The
  same trap runs the OTHER way for `chatterbox`**, which CI does NOT sync: a local venv with that
  extra installed is greener than CI. Nothing in the suite may `importorskip` a package that ships
  only in an extra CI skips — `tests/test_tts.py` fakes `chatterbox.mtl_tts` AND `soundfile`
  through `sys.modules`. Verify with a meta-path blocker, not by trusting a docstring.
- A LIVE run additionally needs real model credentials and a Deno sandbox (`brew install deno`).
  Don't run it in CI; it costs money.
- Before claiming done, actually run both commands and paste the output.

## Scope note

What exists: ingestion (text / web / PDF with local hybrid OCR / YouTube captions), citation-grounded
chat, a persistent multi-turn `Notebook` (one JSON file, no database), a Notebook Guide
(`guide.py` — summary/faq/timeline/insight), an Audio Overview (`audio.py` script + `tts.py`
synthesis), an HTTP API (`api.py`, the `api` extra) with a live reasoning-trace stream and a
Trajectory drawer, and a web UI (`rlm_notebook/web/`) that is a real end-user product surface.
The API is the only place a run is subprocess-isolated (`runner.py`/`worker.py`); `cli.py` runs
synchronously in-process.

**Still unbuilt — do not assume any of these exist because a design discussion mentioned them:**
the four Studio guide kinds are NOT cached onto a notebook (only the overview is — invariant 38);
no guide artifact is citable as a source for a later `ask` without being promoted through a note
(32); there is no multi-worker `uvicorn` deployment story for `_ACTIVE_RUNS`/`_RUN_PROCESSES` (the
notebook FILE is safe across processes, those in-memory maps are not); the HTTP API has NO
authentication of any kind (25); Word/Slides/Docs native-format parsing and full audio
transcription (as opposed to YouTube captions, which ship) are undone.

## Invariants — do not break

1. **No fetch/network tool is ever registered on the chat task's `RLMTask(tools=…)`.**
   `parsers/web.py`'s fetcher is called exactly once, host-side, during ingestion — never handed to
   the model at question-answering time. A source's own content is untrusted (invariant 6); if a
   fetch tool were reachable from the REPL, an instruction hidden in that content could steer the
   model into exfiltrating notebook contents to an attacker-controlled URL, and `rlm_harness`'s
   SSRF guard (`is_safe_url`) blocks internal/loopback/metadata targets only — it cannot block a
   legitimate-looking external domain. "Fetch one more page on request" would be a separate,
   explicitly user-confirmed, non-agentic action — not a tool the model decides to call.

2. **`parsers/web.py` re-validates the SSRF guard on EVERY redirect hop, not just the requested
   URL.** `_SafeRedirectHandler` runs `is_safe_url`/`resolved_host_is_safe` again on each
   `Location` target before following it. Without this, an initially-safe-looking URL could 302 to
   an internal/loopback/metadata address and the default `urllib` opener would follow it unchecked.
   Do not swap back to plain `urllib.request.urlopen`.

3. **Ingestion is host-side only, never inside the sandbox.** `parsers/{text,web,pdf,youtube}.py`
   and `parsers/_ocr.py` all run before any `RLMTask` exists. `pypdfium2`, `trafilatura`, `yt-dlp`
   and the OCR backends are native/C-extension dependencies unsuited to the pyodide/deno sandbox —
   and untrusted parsing logic has no reason to run inside the same trust boundary as the model's
   own code anyway. `corpus.py` only ever hands the RLM a plain string, already parsed.

4. **The corpus blob uses `[[SRC:<id>|<locator>]]` markers, and EVERY citation-grounded task's
   instructions teach the model to treat them as opaque and echo them verbatim in a `Citation`.**
   That is all SIX: `AnswerQuestion` (`task.py`), the four Notebook Guide tasks (`guide.py`) and
   `GeneratePodcastScript` (`audio.py`). `instructions.py`'s `CITATION_RULES` is the ONE copy of
   this rule (invariant 13). Without an explicit rule the model has no reason to preserve an ad hoc
   marker format across `.find()`/slice operations, and `citations.py` has nothing to verify
   against. **Residual risk**: the offline tests drive a scripted LM whose turns are fixed dicts, so
   they prove the tool-wiring/SUBMIT chain and nothing about real compliance. One live run observed
   a real model doing it. Evidence, not proof — do not restate as a guarantee.

5. **`citations.py` verifies coordinate existence only — never content faithfulness.** It confirms
   a claimed `source_id` exists and its `locator` resolves to real text in the corpus; it does NOT
   confirm the surrounding prose faithfully represents that text. Never let a docstring, log
   message, or UI copy imply a stronger guarantee — that gap is exactly the
   "grounded-but-not-verified" failure mode found in NotebookLM itself. A citation that fails
   coordinate verification is marked unverified, never silently dropped, never silently trusted.

6. **`injection_scan.py`'s flags are deterministic and additive — they gate nothing.** A flagged
   source's content still reaches the model and its answer still returns; the flag is metadata
   attached to the SOURCE at ingestion (`ingest.with_injection_flags`) and printed by `cli.py`
   only — `AskResponse` carries no flags, so this is NOT true of the API or the web UI. It is a
   transparency mechanism; do not wire it to refuse a run. Its patterns trade recall for precision
   on purpose (a paper *discussing* prompt injection can trip it) — an acceptable false-positive
   rate for a flag nobody is forced to act on.

   **A flag is a SENTENCE addressed to a person, never a regex**, because since these flags gate
   nothing, whether a human can act on them is their entire value. `_INSTRUCTION_PATTERNS` pairs
   every pattern with its description, and the role-label pattern is anchored to its own LINE
   (`^\s*(system|assistant|user)\s*:\s*`, MULTILINE) rather than matching mid-sentence prose.

   **Both apply to sources ingested FROM NOW ON only.** `scan_source` runs once and the result is
   persisted into `Source.flags`; nothing re-scans. No migration, deliberately — re-scanning on
   every `GET` is expensive, and rewriting on load would silently edit stored notebooks.

7. **OCR ships enabled by default, not merely pluggable-but-off.** `parsers/pdf.py` extracts each
   page's text via `pypdfium2`; a page below `_MIN_TEXT_CHARS` (literally 1, i.e. no text layer at
   all) is rendered to an image and dispatched to `parsers/_ocr.py`'s hybrid OCR (RapidOCR primary,
   Tesseract fallback, both Apache-2.0, both CPU-only). The backends are core `dependencies`, not
   an opt-in extra — a plain `uv sync` installs them. **Qualifier**: `pytesseract` is a WRAPPER; the
   `tesseract` binary is a system dependency no Python manifest can express, and `_ocr.py` swallows
   `TesseractNotFoundError`, so the fallback silently is not there on a machine without it. A
   `vision_llm` OCR mode is a deferred follow-up.

   **`NotebookConfig.ocr_provider` / `RN_OCR_PROVIDER` has ZERO consumers** — `parse_pdf` takes no
   config and calls `ocr_image` unconditionally. Validated on read, then ignored. Kept as the seam
   the `vision_llm` follow-up will use; do not infer that anything dispatches on it today.

   **`pypdfium2` replaced `pymupdf`/`pymupdf4llm` over a real licence conflict.** Those are
   "AGPL v3 OR Artifex Commercial" with no free non-AGPL path, and `pymupdf-layout` carried a
   second Polyform Noncommercial licence. This project is `license = "MIT"` and ships an HTTP API
   meant to run as a network service (invariant 25), which is exactly what AGPL's network-use
   clause binds. `Pillow` is an explicit DIRECT dependency: `pypdfium2` declares no runtime
   dependencies of its own, so `.to_pil()` previously worked only by luck via a transitive.

   **A deliberately simpler OCR-need heuristic than `pymupdf4llm`'s**: a plain
   "extracted text below a small threshold" check does NOT detect a GARBLED-but-present text layer,
   only a missing one. A bad-character-ratio heuristic is a later, independently-mergeable
   follow-up. **`tests/_pdf_fixtures.py` builds test PDFs with `reportlab`, a `dev`-only
   dependency** — never a runtime dependency of the shipped package.

8. **`corpus.py` enforces a size cap on the assembled blob and fails loudly, not silently, past
   it.** The single-blob-as-REPL-variable design has a real memory ceiling in the pyodide/deno
   sandbox; the cap exists to stop a mysteriously failing or slow chat turn later. **Two known
   gaps**: `Corpus.blob()` concatenates every source in full BEFORE checking the length, and the
   check fires at QUESTION time, not at ingestion (`max_chars` defaults to `None`, and every call
   site that passes it is an `ask`/`guide`/`audio` path). Closing either means assembling the blob
   on every source add — they are one follow-up, not two.

9. **`AnswerQuestion` always runs in the `pyodide` sandbox; `NotebookConfig.from_env` refuses any
   other `RN_INTERPRETER` value rather than silently overriding it.** An operator who set
   `RN_INTERPRETER=local` believes something about this run that would not be true if the kit
   quietly corrected it; refusal makes the misconfiguration visible.

10. **A notebook id is sanitized (`notebook.slug`) before it becomes a filename, and an id the
    whitelist empties falls back to a content hash rather than being rejected.** `--notebook` and
    the API's `{notebook_id}` turn directly into `<notebooks_dir>/<slug(id)>.json`, so an
    unsanitized id could become a traversal segment (`..`, an absolute path, a nested directory) or
    blow past a path-component length limit.

    **`nb-<sha256[:16]>` when the whitelist leaves nothing.** `[A-Za-z0-9._-]` strips every CJK,
    Arabic, Cyrillic and emoji character, so a notebook named in Chinese reduced to the empty string
    and was rejected. The id is NFC-normalized before hashing (two spellings reach the same file)
    and encoded with `surrogatepass` — load-bearing, because `api._derive_run_id` calls `slug()`
    OUTSIDE every error wrapper, which would make a raising `slug` an unauthenticated 500. It
    affects the FILENAME only: `Notebook.id` stores what the user typed and
    `list_notebook_summaries` reports that stored value, so non-Latin names round-trip. A genuinely
    empty or whitespace-only id still raises.

    **This deliberately supersedes part of invariant 27**: `"!!!"` is an ordinary notebook now, not
    a 400. The unhandled 500 that 27 exists to fix is still gone; that input simply no longer
    reaches the arm, and a genuinely empty id still exercises it.

11. **`history` (prior conversation turns) is context only — it is never itself a source of facts
    or citations.** `AnswerQuestion.instructions` says so, and nothing in `citations.py`
    special-cases a citation just because a similar one appeared earlier: every citation is verified
    fresh against the CURRENT `sources` blob. A past answer being wrong, or a source having been
    removed since, must not be inherited into a new one. **Residual risk, same class as invariant
    4's**: one live turn showed a real model using history to resolve a referent while still
    re-deriving its citation from `sources`. Evidence, not proof.

12. **Extending an existing notebook with `--source` dedupes by origin, and never reassigns an
    existing source's id.** `notebook.existing_origins` + `ingest.ingest_new`'s `skip_origins`
    (reached through `notebook.ingest_sources_for`) make re-passing the same path/URL a no-op. A
    source already cited in a saved `ChatTurn.answer` can never have its id silently repointed at
    different text. The GUARANTEE is what matters — id assignment itself belongs to
    `append_sources`, which renumbers against the freshly-loaded notebook inside the lock
    (invariants 34 and 50).

13. **Every citation-grounded RLMTask shares its citation-marker and validate-before-submit
    instructions from `instructions.py` — not a hand-copied paragraph per task.** All six compose
    the SAME three shared pieces (`CITATION_RULES`, `validate_before_submit_rule(...)`, and
    `VERBATIM_COORDINATES` via `chat_language_rule`/`artifact_language_rule`) onto their own
    task-specific opening. A wording fix to a shared piece must never be applied to one task's local
    copy — there should be no local copy. **The task-specific opening is deliberately NOT unified**:
    `AnswerQuestion`'s "ground only in sources" sentence is about a missing *answer*,
    `guide.py:_grounded_instructions`' is about an unsupported *claim* — forcing one sentence would
    blur one of them. `cli._prepare` is the same "one copy, not five" discipline applied to the
    ingestion/notebook setup `ask` and `guide` both need.

14. **TTS synthesis (`tts.py`) runs entirely host-side, on an already-generated,
    already-schema-validated `PodcastScript` — it is never a tool the model can call, and
    `GeneratePodcastScript` (`audio.py`) has no dependency on `tts.py` at all.** Same reasoning as
    invariants 1 and 3: synthesis is a real network call, and the model's job (writing a grounded
    script) is finished long before any audio is generated.

15. **The default TTS provider (`RN_TTS_PROVIDER=edge-tts`) needs no API key or paid account, so
    `rlm-notebook audio` works out of the box** — the same "ship a working default, not just a
    pluggable interface" reasoning as OCR (invariant 7). The known-provider list lives in ONE place,
    `tts.py`'s `_PROVIDERS` (`get_tts_provider` refuses loudly on an unknown name); `config.py`
    deliberately keeps NO second copy to validate against, because a second list drifts.

16. **`PodcastScript.utterances` may legitimately be empty, and `cli._cmd_audio` says so
    explicitly rather than printing nothing** — the same allowance and UI fix `Timeline.events`/
    `FAQ.items` already have, where "silently prints nothing" was a real bug.

17. **`EdgeTTSProvider` synthesizes one utterance at a time (one voice per `edge-tts` call) and
    concatenates the raw MP3 byte streams — it does not re-encode.** A deliberate tradeoff to avoid
    an `ffmpeg`/`pydub` dependency (`ffmpeg` is a system binary, not pip-installable) for what would
    only be a gapless-playback cosmetic improvement. Weigh that dependency cost before "fixing" it.

18. **The Audio Overview's cast is a fixed two hosts, `host_a`/`host_b` (`schema.Speaker`), not
    freely-named per episode.** Keeps `Utterance.speaker` a closed enum (`Literal[...]`, not an
    `enum.Enum`) that citations and voice-mapping can rely on, and keeps `RN_TTS_VOICE_HOST_A`/`_B`
    a fixed two-variable surface. A deliberate MVP scope cut. **Known gap**: `config.tts_voice_map`
    hardcodes both speaker keys with no tripwire, unlike `cli._SPEAKER_LABELS`.

19. **`cli._cmd_audio` resolves the TTS provider before running the (potentially expensive)
    script-generation model call, not after.** The original ordering wasted a real model call
    whenever `RN_TTS_PROVIDER` was misconfigured — the error surfaced only once the transcript had
    already been generated. Don't move `get_tts_provider(...)` back after
    `GeneratePodcastScript().run(...)`. Relatedly, `EdgeTTSProvider.synthesize` wraps its file WRITE
    in the same try/except as the network call: both are one "make this file exist" operation as far
    as any caller is concerned, and a bad `--out` directory must not raise after synthesis has
    already spent a real network call.

20. **`ingest.py`/`notebook.py` (`is_url`/`ingest_one`/`ingest_new`, `load_or_create`,
    `ingest_sources_for`/`append_sources`, `mutate_notebook`) are shared by `cli.py` AND `api.py` —
    neither entry point depends on the other.** Extracted here once both needed the identical
    "get me a notebook, ingest new sources into it" step, so a fix to source-handling can't land on
    only one of the two by accident. Don't reach into `cli.py` from `api.py` (or the reverse) — if
    both need it, it belongs in a shared, entry-point-agnostic module.

21. **Every API request that runs an `RLMTask` does so in an isolated subprocess
    (`runner.py`/`worker.py`), never in-process.** A SEPARATE execution model from `cli.py`'s
    synchronous in-process one; the two coexist. **`worker.py` is the only place an `RLMTask` is
    ever RUN** — `.arun()` is called there and nowhere else — so a crash deep in a model run takes
    down a worker subprocess, never the API server. **Do not restate the claim that `api.py` never
    imports `dspy`/`rlm_harness`; it is FALSE and was verified false** (it imports the task classes
    for `_dotted()`, and those import `rlm_harness` at module scope). The guarantee is about
    EXECUTION, not imports.

22. **Cancellation works via `killpg` on the WHOLE process group (`start_new_session=True` when
    spawning), not just the worker's own PID.** A stuck Deno grandchild must not survive as an
    orphan after its parent worker is killed. Don't simplify this to `process.kill()`, which only
    signals the worker's own PID.

23. **`api._ACTIVE_RUNS` is a single-process, in-memory map with ONE SLOT PER NOTEBOOK ID — two
    documented limitations, neither a silent bug.** (a) No multi-worker/multi-process `uvicorn`
    story: each worker process gets its own dict, and `POST .../cancel` only reaches whichever holds
    the request. (b) Two concurrent requests against the SAME notebook id share one slot, so
    `/cancel` reaches only the most recent — the first still finishes on its own. The overwrite
    itself never corrupts state (each request's `finally` clears only its OWN entry, an `is run`
    identity check). A per-run-id registry would remove (b); `POST /runs/{run_id}/cancel`
    (invariant 47) already does exactly that for the paths that have it.

24. **Every `SystemExit` a request handler can reach is converted to an HTTP 500, rather than
    letting it escape.** `cli.py` lets the same `SystemExit` propagate and exit the process, correct
    for a one-shot CLI — but in a long-running server an unhandled `SystemExit` inside a request
    handler is a crash, not a clean error response. `api._config()` wraps `NotebookConfig.from_env`;
    never call `from_env()` directly from a handler.

    **The RULE is the invariant, NOT the list of places it currently applies** — that list has to be
    re-derived rather than trusted. `config.max_upload_bytes()` has a `SystemExit` of its own
    (through `_env_int`), is the first statement of `upload_source`, and fell outside `_config()`'s
    coverage precisely because it is deliberately not a `NotebookConfig` field (invariant 30). Any
    standalone config reader a handler calls needs the same treatment.

25. **This API has NO authentication or authorization of any kind.** Any caller can create, extend,
    query, `ask`/`guide` against, cancel a run for, RENAME, or irreversibly DELETE A SOURCE FROM any
    `notebook_id`, and can mutate GLOBAL state through `PUT /settings` (invariant 41). There is no
    concept of an owner. Meant for local or otherwise fully-trusted-network use only; do not expose
    it to an untrusted network without adding auth first. Both `api.py`'s module docstring and
    `README.md` say so — don't let that warning quietly disappear in a later edit.

    `GET /notebooks` makes every id enumerable without knowing it, and `NotebookSummary.title` is
    model-authored prose derived from a corpus excerpt (invariant 37) — so an unauthenticated caller
    enumerating it gets a one-line summary of every notebook's subject matter. Inside the same
    accepted posture, but no longer "metadata only".

26. **`add_sources` accepts ONLY http(s) URLs, never a local file path — unlike `cli.py`'s
    `--source`.** `ingest.ingest_one` treats any non-URL string as a path on the machine running the
    process and reads it with no allowlist: reasonable for a CLI whose operator already trusts their
    own machine, and an unauthenticated arbitrary-file-read vulnerability the moment the same
    function is reachable over an unauthenticated HTTP endpoint. The full attack was reproduced end
    to end (`POST {"sources": ["/etc/passwd"]}` read the file and echoed it back through a citation
    that passed coordinate verification). If a later slice wants the API to accept files, that needs
    its own explicit upload design (invariant 30) — not quietly re-widening this check.

27. **Every endpoint that resolves a notebook by id catches BOTH `pydantic.ValidationError` (a
    corrupted notebook file → 409) AND `ValueError` (an id `notebook.slug` reduces to an empty
    token → 400) — not just the first.** Without it, an unhandled `ValueError` escapes as a raw 500.
    The original worked example (`"!!!"`) is SUPERSEDED by invariant 10; only a genuinely empty or
    whitespace-only id still takes this arm. `cancel` is unaffected (it never loads a notebook).
    Route path-traversal payloads do NOT reach this code path — Starlette's default path converter
    refuses to match a literal `/` inside one `{notebook_id}` segment — but that is a FRAMEWORK
    default, not this project's code; re-check it if the route ever changes shape.

28. **`cli._GUIDE_TASKS` and `api._GUIDE_TASKS` are two independent registries, kept in sync by a
    tripwire test, not by sharing code** (invariant 20 explains why `api.py` doesn't import from
    `cli.py`). Add a new `guide` kind to BOTH dicts, or the tripwire fails immediately rather than
    the two silently drifting.

29. **The web UI (`rlm_notebook/web/`) is a real end-user product surface, not a replay-only trace
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
    `_ACTIVE_RUNS` entry, so a stuck synthesis call has no `killpg`-equivalent to reach it. The
    response is JSON with base64-encoded audio, never a raw binary body, so error handling stays
    uniform with every other endpoint.

    **The live reasoning-trace stream rests on four rules:**

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

    **Known limitations**: a missing trace degrades that ONE affordance and never the rest of the
    page (retention is bounded by invariant 34); the marker search is a HEURISTIC — finding the
    marker proves the REPL saw it, never that this occurrence is what the model relied on, the same
    "coordinate, not faithfulness" limit as invariant 5; and a `sub_call` event's `input` is
    truncated to 4000 characters upstream. **The trace endpoints are a MATERIALLY DIFFERENT exposure
    than metadata-only responses** — a trace can contain full ingested source text — inheriting
    invariant 25's no-auth posture as a sharper version of the same accepted risk.

30. **`POST /notebooks/{id}/sources/upload` and `add_sources`'s `texts` field never reopen
    invariant 26's local-path ban.** Upload is the opposite shape: the server only receives opaque
    bytes the caller already had, plus a claimed filename used solely for extension-based kind
    detection (`.pdf`/`.txt`/`.md`, `ingest.ingest_uploaded_file`) and display. Pasted text has no
    path at all — `ingest.ingest_pasted_text` gives it a content-derived origin (a readable snippet
    plus a hash, not a bare hash, because the Sources list renders `origin` verbatim as its label).

    **The size cap must be checked BEFORE FastAPI parses the body.** Declaring the endpoint the
    natural way (`file: UploadFile = File(...)`) makes FastAPI parse the ENTIRE multipart body
    before the handler runs — a 5MB body is fully read and spooled to disk the instant the handler
    starts — and Starlette's `max_part_size` never applies to file parts, only plain form fields, so
    there is no framework-level backstop. `upload_source` therefore takes `request: Request`
    directly (no `File(...)` parameter), checks `Content-Length` FIRST, and only calls
    `request.form()` once that clears `config.max_upload_bytes()` (`RN_MAX_UPLOAD_BYTES`, 50MB). A
    missing `Content-Length` (chunked encoding) is refused outright (411) — there is no safe way to
    bound an unknown-length body before reading it.

    **`config.max_upload_bytes()` is deliberately NOT a `NotebookConfig` field.** `from_env()` raises
    `SystemExit` whenever `RN_MAIN_MODEL` is unset, correct for `ask`/`guide`/`audio` and a real bug
    here: uploading a source has nothing to do with whether a model is configured. (See invariant 24
    for the coverage gap this creates.)

    **Deliberately not attempted**: Word/Slides/Docs native-format parsing, and multi-file batch
    upload (matching the single-file `<input>`).

31. **`GET /notebooks/{id}/sources/{source_id}` returns a source's FULL text — a materially
    different exposure than every other endpoint except the trace pair (invariant 29).** Before it,
    no caller could read more of a source than a citation's short `quote`. It reuses
    `corpus.Corpus.get(source_id)` — the SAME lookup `citations.py` already performs on every
    request — rather than a second hand-rolled scan. Invariant 25's posture covers this in spirit
    (the model already has the whole corpus), but the SURFACE is new and worth its own line.

    **The web UI's citation-list row is the primary click target for the source-text viewer**, with
    the reasoning-trace view demoted to a secondary per-row `⌁ trace` icon that calls
    `event.stopPropagation()` so the two never double-fire. `.citation-row` is clickable regardless
    of whether the `quote` matched inline in the answer text — before this, an inline-match miss had
    NO way to open anything. Both citation-detail fetch paths carry a staleness guard
    (`sourceViewerAbort`, an `AbortController`; and a monotonic token on `detailArea` for
    `showCitationTurn`, a plain GET with no browser-level cleanup to invoke). Don't reintroduce
    either gap in a future citation-detail fetch path.

    **Known and explicitly NOT fixed here**: `Corpus.add()`'s duplicate-id dedup guard is dead code —
    nothing in the real ingestion path calls it.

32. **Notes (`schema.Note`, `Notebook.notes`) are freeform, uncited text — grounded and citable only
    once PROMOTED into a real `Source`, never before.** A note may have originated as a copy of a
    citation-grounded answer, but the note itself carries no `citations` and is never re-verified —
    invariant 5's guarantee doesn't extend to it. `notebook.promote_note` is the ONLY path a note's
    text reaches `notebook.sources`, and it reuses `ingest.ingest_pasted_text` UNCHANGED, so a
    promoted note gets the identical content-derived-origin, dedup-by-origin and injection-scan
    treatment. Promotion removes the note regardless of whether a source was appended (a dedup hit
    appends nothing) — promotion is a completed user action either way, and the endpoint returns the
    full `NotebookResponse` so a client distinguishes outcomes by diffing, never by a status code.

    **A note id is assigned from the MAX id among currently-live notes, never `len(notes) + 1`**
    (`notebook._next_note_id`). With length-based ids, deleting a non-last note lets TWO LIVE notes
    share one id, and since `delete_note`/`promote_note` both act BY id, that made either one
    silently affect BOTH. `delete_note`/`promote_note` also remove exactly the first matching note
    by index rather than filtering every id-equal match — defence in depth on top of the id fix.
    Reusing an id once NO live note holds it is safe and unchanged.

    **`POST /notebooks/{id}/notes` creates a notebook (`create=True`, like `add_sources`) so a new
    notebook can start life with a note; `DELETE .../notes/{note_id}` requires an existing one
    (`create=False`, matching `ask`/`guide`).**

    **The "+ Save as note" button belongs to a CALL SITE that opts in, never to the shared
    `renderAnswerWithCitations`**, which is called from six sites — putting it inside would leak it
    onto every artifact. It is a small factory (`saveAsNoteButton`) so opting-in sites share one
    implementation. **Two sites opt in: a Chat answer (`renderTurn`) and the chat overview
    (`renderChatOverview`).** The line is about the SURFACE, not who authored the text: things
    rendered IN the chat thread are the user's to curate; a Studio tab's artifact and a podcast
    transcript are not part of that thread.

33. **YouTube source ingestion (`parsers/youtube.py`) fetches CAPTIONS ONLY — never the video or
    audio stream.** A deliberate, user-confirmed MVP scope decision: no `ffmpeg`, no Whisper, no
    transcription API key. A video with neither official nor auto-generated captions is a clean,
    loud ingestion-time error (`CaptionError`), never a silent empty/partial source.

    **Accepted ToS caveat**: YouTube's Terms prohibit automated access outside its own interfaces;
    `yt-dlp` (a core dependency, same "ship a working default" reasoning as invariants 7 and 15)
    operates in the same grey area every YouTube-downloading tool does. Fetching only captions is
    narrower than downloading media but is not risk-free — the risk is accepted by whoever DEPLOYS
    this, and `README.md` states it.

    **`CaptionError` is a `ValueError` subclass.** `cli._prepare` and `api.add_sources` both catch
    ingestion failures as `except (FetchError, ValueError, OSError)`; a bare `RuntimeError` would
    land a captionless video as an unhandled 500 / raw traceback. Don't give a future
    ingestion-failure exception a base class outside that tuple without updating both call sites.

    **`_parse_vtt` flattens EVERY non-blank line into its own `(start, text)` entry — one per LINE,
    never one per cue — and leaves ALL deduplication to `_dedupe_consecutive`.** Cue-level
    classification was tried twice and under-collapsed on real auto-caption data both times: a
    rolling-karaoke cue advancing by exactly ONE new word carries no `<...>` tag, so tag-presence
    misclassifies it. Line-level flattening sidesteps classification entirely — a transition cue's
    settled line is always identical to a line the preceding cue already emitted, so plain adjacent
    dedup collapses it, while a genuine multi-line official dialogue cue's lines are both new and
    both survive (`_chunk`, not `_parse_vtt`, rejoins them). **The cue-boundary check is separate and
    still correct**: a whitespace-only line is part of a cue's OWN payload (real auto-caption VTT
    uses a single-space line for exactly this), so ending a cue tests EXACT emptiness
    (`lines[i] != ""`) while extracting text still treats whitespace-only content as blank — two
    notions of "blank" at two steps, not one check reused. `tests/test_parsers_youtube.py`'s
    fixtures are real captured dumps for this reason.

    **A `"ts:<mm:ss>"` locator prefix** (a fixed `_CHUNK_SECONDS = 120` window, coarser than one
    cue), alongside `"whole"` (text/web) and `"page:<n>"` (pdf). Locator is fully opaque everywhere
    it matters — `citations.py` and `CITATION_RULES` never parse it — so a new prefix breaks nothing.

    **`_fetch_caption_track` reuses `parsers/web.py`'s hardened `_opener`** rather than a bespoke
    unguarded fetch. The caption URL comes from YouTube's own `timedtext` API, not from untrusted
    source content, so invariant 2's threat model doesn't apply — but reusing the hardened opener
    costs nothing and removes the residual risk instead of reasoning it away. `web.py` is UNCHANGED.

34. **Every write to a notebook goes through `notebook.mutate_notebook`, which re-loads the file
    from disk INSIDE a per-notebook lock and applies a caller-supplied DELTA — never a snapshot the
    caller read earlier.** `save_notebook` writes the whole `Notebook` model, so persisting an
    object read minutes ago silently destroys everything written in between. Two distinct faults and
    the fix needs both halves: a stale snapshot and interleaved critical sections — a lock alone
    would not have helped, since the racing writes never overlapped in the file-writing instant.
    Every mutating path is now: expensive work UNLOCKED against a snapshot → `mutate_notebook`
    applying only the delta. **`save_notebook` has exactly one caller in the whole package
    (`mutate_notebook`); application code calling it directly is the bug**, and `extend_with_sources`
    was DELETED rather than kept beside `ingest_sources_for` + `append_sources`, because ingesting
    and appending in one breath is exactly what forces a caller to hold a snapshot across ingestion.

    - **`fcntl.flock` on a sidecar `<base_dir>/.<slug>.json.lock`, NOT `fcntl.lockf`.** `flock`
      attaches to the open file description, so one mechanism serializes two threads of one process
      AND two processes; POSIX record locks are per-process and two `uvicorn` threads would pass
      straight through each other. A SIDECAR because `load_or_create` legitimately runs for a
      notebook that doesn't exist yet. **Not reentrant** — nothing passed to `mutate_notebook` may
      call `mutate_notebook`/`save_notebook`. **POSIX only**; without `fcntl` it degrades to a
      process-local `threading.Lock`, still correct for the single-process deployment invariant 23
      describes as the only supported one.
    - **`api.py` dispatches every call through `asyncio.to_thread`** (the shared `_mutate_or_http`,
      which holds the ONE copy of invariant 27's error mapping plus `FileNotFoundError`→404), because
      a blocking `flock` a CLI invocation holds must not stall the event loop. It validates the id
      BEFORE the thread, since `notebook_path`'s invalid-id `ValueError` and `delete_note`'s "no such
      note" `ValueError` are the same type and catching them together misreports one as the other.
    - **READS take no lock** (`os.replace` is atomic, so a reader sees a complete old or new file,
      never a torn one), and **`ask` verifies citations against the SNAPSHOT corpus** — the blob the
      model actually read. Invariant 11 governs reading a turn BACK.
    - **`cli._prepare` persists ingestion before the model runs and returns the notebook
      `mutate_notebook` produced, NOT its own snapshot.** `append_sources` renumbers ids against the
      fresh notebook, so a corpus built from pre-merge objects would make the model cite `s2` for a
      source persisted as `s4` — every citation in the run silently wrong. The API's `ask` is NOT
      exposed to this (its snapshot holds only already-persisted sources).
    - **`mutate_notebook` checks the `create=False` miss BEFORE taking the lock as well as inside
      it.** Entering `notebook_lock` creates its sidecar file, so without the pre-check every 404-ing
      unauthenticated request leaves a permanent zero-byte file behind. The check INSIDE the lock is
      what makes it correct; the outer one only keeps a miss from writing anything.

    **Trace retention (`traces.py`)** — `traces/{run_id}.jsonl` is the one artifact here that can
    contain FULL ingested source text, in front of an API with no authentication. `prune_traces`
    sweeps by age (`RN_TRACE_RETENTION_DAYS`, 7) and count (`RN_MAX_TRACE_FILES`, 500), `0` disabling
    either, at startup and after every run.

    - **Two rules OUTRANK both sweeps**: a run id in the caller-supplied `protected` set
      (`_RUN_PROCESSES`'s keys) and any file younger than a one-hour floor. Deleting a live run's
      trace would not just break its SSE stream — it would free a run id the exclusive-create gate
      (invariant 29) is still relying on being taken. The floor covers what `protected` cannot: the
      window before registration, and a JUST-finished run whose trace the answer on screen links to.
    - **`traces._is_ours` gates every deletion, and this is not optional hardening.** `_TRACE_DIR` is
      a bare relative `Path("traces")` resolved against whatever directory the server started in, and
      sibling projects write `.jsonl` traces of their own — age and `protected` bound only WHEN a file
      dies, never WHOSE it is. Ours means its first line carries `rlm_harness.trace`'s schema marker,
      or it is EMPTY (an abandoned `O_CREAT|O_EXCL` reservation, which must stay collectable).
      `api._prune_traces` LOGS what it removed: the only destructive operation here must not be silent.
    - **The count cap governs how many PRUNABLE traces are kept**, so `max_files` is a SOFT cap on the
      directory total. Charging protected and too-young files against it while deleting only from the
      eligible ones lets N concurrent runs — a client-influenceable number — force well-within-
      retention traces to die early. `RN_TRACE_RETENTION_DAYS` is a floor, not a function of load.
    - **`prune_traces` never raises** (housekeeping must not turn a completed, paid-for `ask` into a
      500), which is why the **lifespan reads the retention settings itself** — otherwise a typo'd
      value means "silently never prune". Standalone readers, never `NotebookConfig` fields, for
      invariant 30's reason: a server with no model configured must still tidy up after itself.
    - **`api._prune_traces` snapshots `set(_RUN_PROCESSES)` on the EVENT LOOP, before dispatching to
      the thread**, or it races the loop's own mutation of the dict.

    **Accepted limitation**: every call shares the asyncio default `ThreadPoolExecutor` with ingestion
    and TTS synthesis, so a lock held by an external process can queue writes for unrelated notebooks.
    Availability only, on a trusted-network service. **NOT attempted**: a merging write, a multi-worker
    story for the in-memory run registries, any retention policy for `notebooks/` itself.

35. **A model string prefixed `claude-agent-sdk/` routes that role onto the user's Claude Pro/Max
    SUBSCRIPTION, and it works ONLY because `config.setup` injects the LM — `rlm_harness.configure`
    does not route on the prefix itself.** `runtime.configure` calls `dspy.LM(...)` unconditionally
    for any seat left unsupplied, so a `claude-agent-sdk/…` string handed to it alone reaches
    litellm as a provider that does not exist. `setup` builds a `rlm_harness.ClaudeAgentLM` per
    sentinel role and passes it through `configure`'s public `main_lm=`/`sub_lm=` seam; every
    non-sentinel role is still built from the `RN_*` config. The sentinel string ALSO stays in
    `RLMConfig` — inert for an injected seat, but it is what labels the trace and the log.

    `SUBSCRIPTION_PREFIX` lives in `config.py` (a naming convention, in the module that stays free of
    `dspy`/`rlm_harness` at import time) and `_maybe_subscription_lm` imports `ClaudeAgentLM` LAZILY,
    inside the sentinel branch only, so an API-key-only install never touches the optional SDK.
    **`config.setup` is the ONE place either entry point configures a model** — `cli.py` in-process
    and `worker.py` inside the subprocess both call it — so one change covers both execution models.

    **`RN_SUB_MODEL` inheriting the sentinel from `RN_MAIN_MODEL` is correct HERE** (this project has
    no separate role that must stay on its own endpoint), and is pinned by a test so the divergence
    from the sibling that gates against it stays deliberate.

    `claude-agent-sdk` is the `subscription` extra, MIRRORED as a `subscription-sdk` dev group with
    `[tool.uv] default-groups`. Not redundancy: an extra is not synced by default, so a bare
    `uv sync` PRUNES the SDK back out and the next subscription run dies with an `ImportError`
    nobody caused. The SDK also needs the Claude Code CLI installed and logged in, a runtime
    prerequisite no manifest can express. `ClaudeAgentLM` refuses to construct when
    `ANTHROPIC_API_KEY` is set (the CLI silently prefers it over subscription OAuth, which would
    quietly bill API credit) — an upstream guard. A BARE `claude-agent-sdk/` with no model after the
    slash raises `SystemExit`, reaching the API as a clean 500 through `_config()`.

36. **`rlm_notebook/web/`'s `hidden`-toggled elements must never be given an author `display` rule
    without a matching `[hidden]` rule, and `tests/test_web_assets.py` fails the build if one is.**
    `hidden` works through the UA stylesheet's `[hidden] { display: none }`, which ANY author
    `display` declaration outranks — author styles beat UA styles regardless of specificity. This
    shipped broken twice: `.modal-overlay { display: flex }` left an overlay permanently visible
    whose `inset: 0` swallowed every click on the page, and `.ticker-detail` left the reasoning log
    permanently expanded. Invisible to every other layer this project can test — the Python suite
    never renders, and a unit test of the close handler would pass against the broken stylesheet,
    because the JS was always correct. Hence a SOURCE-TREE assertion, keyed on CSS CLASSES (which
    markup and JS spell the same way) and asserting up front that it can still see every known
    instance, so a future extraction failure fails the build instead of passing vacuously. The same
    file pins invariant 29's "never `innerHTML` with an interpolated string" (and its `outerHTML`/
    `insertAdjacentHTML`/`document.write` siblings).

    **A visible author `display` on a hidden-toggled class IS allowed — with a guard that OUTRANKS
    it**, i.e. a `[hidden]` rule whose selector is one token LONGER, so it wins on specificity
    regardless of source order. This tripwire compares by class NAME and would accept a guard that
    loses the cascade; a separate test computes specificity and is the one that actually checks it.

    **A flex column stretches its children to full width, and that is a DEFAULT, not a choice** —
    only what should span may span.

    **A re-click on an already-open citation detail COLLAPSES it** (`showCitationTurn`'s `_shownKey`)
    rather than blanking to "Loading…" and re-fetching an identical payload. Keyed on WHICH citation
    is shown, so clicking a different one switches instead of closing — and the key includes
    `quote`, because text and web sources emit a single block with locator `"whole"`, so every
    citation into one such source shares that pair. Collapsing bumps the staleness token, so an
    in-flight response cannot repopulate a panel the user just closed.

    **Known gap**: this project has no JavaScript test runner at all (zero-build vanilla JS, by
    design), so interactive UI state has no test seam. A source-tree assertion catches the
    stylesheet class of bug; it cannot catch a toggle that stops toggling.

37. **A notebook's `id` is a HANDLE; `schema.Notebook.title` is the label a person reads. The UI
    mints the id itself and never asks for one.** Requiring a name before the first source made the
    very first interaction a naming puzzle about a thing that did not exist yet. The id still backs
    every filename, `ChatTurn.run_id` prefix and URL, so it must stay stable; the title is free to be
    anything, which is why they are two fields. `title` is optional and defaults to `None`, so
    notebooks written before it existed still load.

    **`naming.SuggestTitle` is deliberately NOT an `RLMTask`.** The full REPL loop is right when the
    model must explore a multi-MB corpus and produce verifiable citations, and absurd for five words
    — it would cost a sandbox boot plus several planner turns. This is one plain `dspy.Predict` over
    a corpus excerpt (invariant 61). It STILL runs inside the API's isolated subprocess, so invariant
    21 is untouched: `worker.py` only calls `.arun(**kwargs)` on the class it is handed.

    **Titling is a separate endpoint (`POST /notebooks/{id}/title`), never folded into
    `add_sources`** — ingestion must not wait on, or fail because of, a model call.

    **It is LAZY**: `app.js`'s `ensureTitle()` is called from actions that ALREADY run a model
    (generating an overview, asking, opening a Studio tab, generating a podcast), never from
    ingestion, because pasting a link should not spend a model call naming something nobody has
    started working on. The consequence — a notebook with sources and no title — is why
    `derived_title` exists (invariant 53).

    **Nothing about a title may cost the user their source**: `SuggestTitle.arun` catches every
    exception and `suggest_title` catches the `HTTPException` a failed/timed-out run raises, both
    falling back to `naming.fallback_title`. An existing title is never overwritten — re-titling on
    every source add would rename a notebook under a user who had already learned its name — so the
    endpoint is idempotent. `clean_title` is the ONLY guard on what reaches the UI, since this is the
    one model output with no schema validation behind it.

38. **The chat overview is the ONE guide artifact persisted onto a notebook (`schema.Overview`,
    `Notebook.overview`), and it is marked STALE rather than deleted when the sources change.**
    Before, it lived only as a front-end flag on a DOM node, so re-opening a notebook showed the
    first-run button again, and adding a source DELETED an overview that cost a real RLM run — with
    "never generated" and "generated but the sources moved" rendering identically. Three states now:
    never generated → the button; current → the overview; stale → the overview, marked, plus
    `↻ Regenerate`.

    A deliberately NARROW cut of "guide artifacts aren't cached onto a notebook": the overview only,
    never the four Studio guide kinds. The overview is the notebook's front page and is what a
    returning user expects to still be there; a Studio tab is an on-demand tool. It does not make
    `+ Save as note` redundant — the field holds the CURRENT overview and is replaced on
    regeneration, while a note is a copy the user chose to keep and the only thing `promote_note` can
    turn into a citable source.

    **`Overview.source_ids` is captured at RUN START, never at persist time.** Building the object
    inside the `mutate_notebook` closure reads as tidy and is silently wrong: a source added while
    the run was in flight would be listed as covered by an overview the model never read, and the
    staleness key would then claim "current" when it isn't. Honest consequence, not a bug: adding a
    source mid-generation makes the overview land ALREADY STALE — the same reasoning `ask` uses for
    verifying against the snapshot corpus.

    **Staleness is SET-EQUALITY on source ids computed SERVER-side**, never by a client (which would
    need `source_ids` exposed and would be re-implemented in every future consumer). It is one small
    comparison each in `_podcast_response` and `_overview_response`. A set rather than a length check
    because a future source-removal path would then break it in the SAFE direction — that path exists
    now (invariant 50) and the foresight paid.

    **`/overview` suffixes its two run ids AFTER derivation** — `base = _derive_run_id(id, token)`
    then `f"{base}-summary"`/`f"{base}-faq"`, with `token = body.run_id or uuid4().hex` capped at
    `_RUN_TOKEN_MAX`. Forming `<token>-summary` first and slugging the result breaks twice: `run_id`
    is OPTIONAL, so an anonymous request yields the literal deterministic `None-summary` and every
    request after the first 409s until retention collects the trace; and `slug`'s 120-character cap
    MERGES the two suffixes for a long client-chosen token. The cap also keeps the filename clear of
    a 255-byte `NAME_MAX`.

    **Generation is server-side, not a `PUT` of what the client already has.** The reason is not
    provenance (invariant 25 already lets any caller store arbitrary prose) — it is that closing the
    tab between the guide response and a store call would LOSE a paid-for run. An FAQ failure
    persists the summary with no starter questions; a summary failure persists nothing, because there
    is no overview without it.

    **Run-id guards compare `slug(notebook_id)`, not the raw id**, on BOTH ends: `stream_run` and
    `citation_turn` server-side, and `app.js` client-side via `NotebookResponse.slug`. Guarding with
    the raw form makes every trace link dead for any id the slug changes — `"my notebook"`, or any
    non-Latin id, which invariant 10 exists to support. The slug is RETURNED rather than
    re-implemented in JS, because the hash fallback would have to be duplicated too.

39. **Model-authored prose follows the READER's language, not the documents'. Citation coordinates
    never follow anything.**

    **The carve-out is the load-bearing half, and it covers coordinates, not just quotes.**
    `citations.verify_citations` compares `locator` with an exact `==` and never inspects `quote` at
    all (invariant 5) — so a model told "write everything in Chinese" that helpfully localises
    `page:1` to `第1頁` turns every citation UNVERIFIED, and one that translates a `quote` produces a
    citation still wearing a ✓ badge while no longer being the source's own words.
    `instructions.VERBATIM_COORDINATES` names `source_id`, `locator`, the marker syntax AND `quote`
    together, and is composed BEFORE `CITATION_RULES`.

    **`Accept-Language` is the wrong API to rank first**: it answers "what language should this app's
    UI be in", not "what language does this person read research in". Resolution is one cheap
    `dspy.Predict` (`naming.SuggestLanguage`, NOT an `RLMTask` — invariant 37's reasoning) weighing
    the interface language (invariant 69), the header, the sources' language and any questions
    already asked — questions weighted highest, because they are the one place the reader CHOSE a
    language rather than inheriting one.

    **Precedence**: `RN_OUTPUT_LANGUAGE` (a HARD override, applying to CHAT too — scoping it to
    artifacts would leave an operator wondering why answers stayed in the sources' language) → the
    settings file (invariant 41) → `Notebook.output_language`, resolved once and persisted → a
    literal default. **The settings file sits ABOVE the persisted value deliberately**: the first two
    rungs are STATED preferences and the third is a CACHED GUESS, existing only so a resolution isn't
    paid for per artifact. Below the cache, a language chosen in the settings page would be inert for
    every notebook that has ever generated anything.

    **The value reaches a task as a SIGNATURE FIELD and is never empty**: a class-level
    `instructions` string is composed at import time and cannot know a per-request language, so "a
    signature field" and "byte-identical prompts when unset" were a contradiction — the default is a
    literal like "the language the sources are written in". Precedence is resolved in `api.py`/
    `cli.py` and passed DOWN; **`worker.py` must never re-read the env**, or precedence would be
    applied twice with the persisted value invisible to the subprocess.

    **`_resolve_language` runs at most once per request, with its own `-lang` run-id suffix appended
    AFTER derivation.** Sharing the artifact's derived id 409s on the exclusive-create gate; and
    `/overview` must resolve BEFORE its `asyncio.gather`, or the two branches fire two concurrent
    resolutions deriving the same id. A failed resolution returns `None` and the caller uses its
    default: a language guess never costs the user the artifact they asked for.

    `tests/test_api.py`'s tripwire asserts every grounded task declares the field, because a missing
    required input surfaces only as an opaque `RLMTaskError` while an UNDECLARED extra kwarg is
    silently accepted — so a partial rollout fails silently in both directions.

40. **`tts.default_voices_for` maps a language to a voice, which is what let the podcast join
    invariant 39's language story.** Nothing here previously mapped language to voice: `voice_map`
    came straight from `RN_TTS_VOICE_HOST_A`/`_B` and `synthesize` spoke whatever it was handed. Any
    provider would have had the same hole — a correct Chinese script read by the en-US default cast
    is a routing bug, not a synthesis one.

    **Every voice id in the table was read out of a real `edge_tts.list_voices()` response, never
    written from memory** — a plausible-looking but nonexistent voice id fails only at SYNTHESIS
    time, after a real model call has been spent on the script, which is the waste invariant 19
    exists to prevent. A test asserts the shape of every id as a guard against hand-editing.

    **Precedence: an explicitly set `RN_TTS_VOICE_HOST_A`/`_B` beats the settings file (invariant
    41), which beats the language default, which beats the shipped en-US cast.** The file rung sits
    above the language default because both it and the env are a human saying "use this voice".
    Explicitness is read from the RAW environment, never by comparing against the default VALUE: an
    operator who deliberately sets the en-US default on a Chinese notebook is making a choice. The
    two voices resolve independently. An unknown language returns `None` from `default_voices` and
    the configured voices stand — a wrong-language voice is bad, but substituting a voice for a
    language nobody asked for is worse.

    **`fallback_voices` is a SECOND, separate provider method**, sitting BELOW the language default
    and ABOVE the shipped `config` value, so an explicit env var still wins and a known language
    still wins over a generic cast. It exists because a non-edge-tts provider plus an unknown
    language otherwise falls through to an edge-tts voice name, failing at synthesis after a real
    model call. Deliberately not `default_voices(None)`, which must keep returning `None`.
    `_VOICE_PATTERN` accepts BOTH naming schemes — widening the accepted SHAPES, never the accepted
    CHARACTERS, so the SSML hole invariant 41 closed stays closed.

41. **The settings page exposes PRESENTATION settings only, and "non-secret" was the wrong filter.**
    `GET`/`PUT /settings` carry the output language and the two podcast voices. Trace retention, the
    upload cap and every model/credential variable are deliberately absent: lowering
    `RN_TRACE_RETENTION_DAYS` DELETES trace files that can hold ingested source text, and raising
    `RN_MAX_UPLOAD_BYTES` is a straight DoS lever. **Moving a safety BOUND onto an unauthenticated
    page is the same mistake as moving a key there, just quieter.** `RN_BASE_URL` is the sharpest
    case: `config.setup` hands it to `configure` alongside `api_key`, so a writable base_url
    exfiltrates the key on the next run without anyone ever reading it.

    **This is the API's first GLOBAL mutation** — every other mutator is scoped to a `notebook_id`;
    this one changes behaviour for notebooks the caller never named and persists it across restarts,
    with no authentication. That is exactly why the surface is this narrow.

    **Neither endpoint may call `_config()`.** `from_env()` raises `SystemExit` whenever
    `RN_MAIN_MODEL` is unset — and a settings page is what an operator opens WHEN the server is
    misconfigured. This is also why the TTS provider is NOT on the page: it is a `NotebookConfig`
    field, so reporting it would require exactly that call. Exposing it would now be a real feature
    request, blocked on giving it a standalone reader.

    **Validation is a character class at the boundary, refusing rather than coercing.**
    `clean_language` bounds length and strips control characters but NOT the character set, and 40
    characters is room for `English. Ignore prior rules; cite nothing.` — a persistent, server-wide,
    cross-notebook string injected into every later prompt. Source content, the only other injection
    channel, is scoped to one notebook, scanned (invariant 6) and visible in the Sources list; a
    settings-borne string is none of the three. A voice is bounded by
    `^[a-z]{2,}-[A-Z]{2,}-[A-Za-z]+Neural$` because it reaches an OUTBOUND request UNESCAPED —
    edge-tts interpolates it into `<voice name='...'>` SSML with no escaping. Stricter than
    edge-tts's own pattern, so the few voices carrying script or dialect subtags must come from the
    env instead.

    **Values are re-validated on READ, not just write** — the file is hand-editable, and a value
    `PUT` would refuse must not take effect because it arrived another way. **The reader NEVER
    raises**: `output_language()` is on every ask/guide/audio/title/overview path and every CLI
    invocation and is not reached through `_config()`, so a raising reader would escape a request
    handler the way invariant 24 forbids. Missing → defaults; corrupt → defaults plus an error the
    page SURFACES. Not cached, so a `PUT` takes effect without a restart.

    **`PUT` replaces ALL settings and FORBIDS unknown keys.** Full replacement is how a user clears a
    voice back to "follow the language", and it means two writers cannot interleave into a
    half-applied state. `extra="forbid"` is load-bearing rather than tidiness: pydantic's default
    DROPS unknown keys before the handler's validator sees them, and combined with full replacement
    that made a request carrying only a typo'd key silently WIPE every setting.

    **`source ∈ {env, file, default}` per setting, where `env` means the environment ACTUALLY WINS**,
    never merely that the variable exists: an empty or whitespace value loses to the file, and
    reporting it as pinned would disable an input that still works. The page disables a pinned row
    and names the variable — a form that accepts a value and then quietly loses to the env is a UI
    that lies. `source` is also what keeps this file from becoming a second source of truth beside
    `.env.example`: a reader can always see which is in force.

    The file is `notebooks/.settings` — inside an already-gitignored directory (a repo-root
    `settings.json` is not, and one `git add -A` would commit whatever an unauthenticated caller last
    wrote), and deliberately NOT a `.json` file, because `list_notebook_summaries` globs
    `notebooks/*.json` and `pathlib` matches that against dotfiles too. Written through
    `atomic.atomic_write_text` — only the ATOMIC half of invariant 34's discipline, not its
    lock-and-re-read half, which a full-replacement write does not need.

42. **A generated Audio Overview from the API is PERSISTED — one file per notebook, served as a real
    file.** Scoped to the API on purpose: `cli._cmd_audio` writes `--out` and returns, with no
    `Podcast` record and no offsets, so a CLI-generated episode can never have subtitles — correct
    for a one-shot CLI whose caller named the output path themselves. The web UI's episode previously
    existed only as the browser tab's `Blob`, so a reload lost it.

    **One file per notebook (`notebook.audio_path` → `<base_dir>/audio/<slug><suffix>`, the suffix
    being the PROVIDER's — invariant 43), replaced on regenerate.** That is what makes retention a
    non-question: growth is bounded by how many notebooks exist, not by how many times anyone pressed
    the button — unlike `traces/`, which needed invariant 34's whole sweep. A SUBDIRECTORY so
    `list_notebook_summaries`' `*.json` glob never sees it.

    **The transcript persists on the notebook (`schema.Podcast`); the AUDIO does not go in the JSON.**
    A multi-MB base64 blob inside the notebook file would be re-parsed on every read, including every
    `GET /notebooks/{id}`. `GET /notebooks/{id}/audio/file` serves it instead, which also lets the
    browser range-request it (a `Range` header returns `206`, so seeking does not re-download).

    **The audio is written BEFORE the notebook record**, so a crash between the two leaves an orphan
    file (harmless — the next generate overwrites it) rather than a notebook pointing at audio that
    isn't there. **An empty script is a regenerate too**: that arm clears both the file and the
    record, or `GET .../audio/file` keeps serving audio for a script the notebook no longer has.

    Same staleness treatment as invariant 38, and citations re-verified against the current corpus on
    every read. **`GET .../audio/file` is the FOURTH materially-different exposure in this API** —
    with no authentication, anyone who can reach this server can play any notebook's episode.

    **The generate button has the same three states the chat overview has**: no episode → a primary
    offer; an episode → a QUIETER "Regenerate"; stale → the same button saying the sources moved.
    Deliberately NOT primary once an episode exists, because regenerating costs a full model run plus
    synthesis (invariant 43). Adding or removing a source re-syncs the BUTTON only — re-rendering the
    panel would rebuild its `<audio>` and interrupt playback (invariant 60's `renumberStrokes`
    reasoning).

    **`renderPodcast` is ONE function serving both the just-generated and the reopened case**, so a
    persisted episode can never render differently from a fresh one. It plays from the server URL,
    not an object URL. `preload="none"` keeps a multi-MB episode from being fetched on every notebook
    open, and the generate path cache-busts the stable URL, or "Regenerate" would look like it did
    nothing because the browser still had the previous episode.

43. **A `TTSProvider` owns its OUTPUT FORMAT, its own cast, and — since it may be cross-lingual — is
    handed the LANGUAGE as a separate input. None of the three is the caller's.**

    A voice NAME is provider-specific (edge-tts wants `zh-TW-YunJheNeural`, chatterbox wants one of
    its shipped reference-clip names), so `default_voices`/`fallback_voices` live on the protocol — a
    shared map would leak one provider's names into the other's request. **The format is on the
    provider for the same reason**: chatterbox emits 24kHz WAV, and forcing it through an MP3 encoder
    would drag in the `ffmpeg`/`pydub` dependency invariant 17 refused. **`synthesize` takes
    `language`** because a cross-lingual provider's voice and language are independent axes;
    `EdgeTTSProvider` ignores it, because an edge-tts voice id already carries its locale. That same
    fact makes `ChatterboxProvider.default_voices` return `None` for EVERY language, routing the
    default to `fallback_voices` exactly as invariant 40's ladder intends. An unknown language RAISES
    rather than falling back to `"en"`: synthesizing Korean with an English language id produces
    confident nonsense, and failing before any audio is written beats a wrong-language episode.

    **`tts.ChatterboxProvider` (`RN_TTS_PROVIDER=chatterbox`, the `chatterbox` extra) is the
    local/privacy option, NOT the default.** No network, no API key. It sounds better and never
    touches the network — exactly the trade a reader who cannot send their sources to a cloud service
    wants, and exactly the trade nobody should be made to take by default: measured against edge-tts
    on the same input, **33x the wall clock and 9x the bytes**, and a 3.4-minute episode took 16.1
    minutes end to end, of which 15.0 was synthesis. Invariant 29's "only the script half is
    cancellable" therefore covers a far longer window here.

    Consequences handled rather than assumed: `notebook.find_audio` looks for WHICHEVER format is
    present, because the provider that generated an episode may not be the one currently configured;
    `clear_audio` removes every format before a regenerate; and `GET .../audio/file` derives its
    media type from the FILE, never from the configured provider.

    **`_generate_one` re-rolls against `expected_seconds`** because chatterbox's output LENGTH is
    unstable (the identical sentence measured 34.80s / 5.48s / 11.68s against an expected ~7s, the
    long take holding 25.1s of actual speech, i.e. the decoder looping). It keeps the SHORTEST take
    if it never converges rather than raising — losing a paid-for episode is worse than a clipped
    line (invariants 19 and 37). `expected_seconds` is CALIBRATED against real measured utterances
    and pinned by a test; a moderate 1.7× overshoot is explicitly NOT caught, because tightening that
    far would start rejecting correct takes.

    **Two hosts need two reference clips**, because chatterbox's checkpoint carries a single
    `conds.pt` and naming both hosts that voice turns a two-host episode into a monologue in two
    halves. `rlm_notebook/voices/{host_a,host_b}.wav` are ten-second clips (the `DEC_COND_LEN` bound)
    SYNTHESIZED by Kokoro (Apache-2.0) — no person was recorded, because cloning a real human's voice
    raises a consent question a recording's licence does not answer. Kokoro's own model card says its
    training data includes synthetic audio from closed TTS models, so the provenance chain is three
    hops; `rlm_notebook/voices/README.md` carries the full statement and the escape hatch
    (`RN_TTS_VOICE_HOST_A`/`_B` accept an absolute path to your own clip). Under `rlm_notebook/` for
    invariant 29's packaging reason. **The built-in voice must be captured BEFORE the prep loop**,
    since it exists only as `model.conds` and the first `prepare_conditionals` overwrites it — a
    MIXED map (one host `built-in`, one clip, a documented configuration) otherwise leaves the
    built-in speaker inheriting whichever clip was prepared last, so BOTH hosts come out in one
    voice, silently, after fifteen minutes of synthesis.

    **`validate(language, voice_map)` runs BEFORE the script generation, not inside `synthesize`** —
    invariant 19's discipline one level deeper than the provider NAME. A language chatterbox has no
    id for (Thai and Vietnamese are in edge-tts's map but not `_CHATTERBOX_LANGUAGES`) would
    otherwise burn a whole model call on every attempt and could never succeed.
    `EdgeTTSProvider.validate` is an explicit no-op. A source-tree test pins the ORDERING at both
    call sites, because neither has a seam to observe it through.

    **A PATH is reachable from the ENVIRONMENT only, never the settings file.** `_VOICE_PATTERN`
    accepts edge-tts ids and short lowercase names and excludes `.` and `/`, so a path arriving
    through the unauthenticated settings page — a brand-new arbitrary-file-read surface — cannot
    happen. Invariant 26's reasoning applied to a second input channel.

    **An EXTRA, never a core dependency**, and its two odd pins are load-bearing: `numba>=0.61`,
    without which the resolver backtracks to a `llvmlite` supporting Python <3.10 and the install
    FAILS on the 3.13 this project targets; and `setuptools<82`, because `perth` and `librosa` both
    import `pkg_resources`, which setuptools removed in exactly 82.0.0 — and `perth` swallows that
    ImportError and sets its watermarker to `None`, so the failure surfaces as an uninformative
    `TypeError` seconds into model loading. The watermark is imperceptible and is KEPT: a provenance
    marker on synthetic speech is a feature.

    **Nothing is adopted here until it has been installed and run.** Three earlier recommendations
    were wrong, all from unverified sources; the rejected alternatives and why are in `CHANGELOG.md`.

44. **The podcast transcript behaves like subtitles, and the timing comes from the PROVIDER rather
    than from measuring the audio.** `TTSProvider.synthesize` returns each utterance's start offset;
    every provider here already synthesizes utterance by utterance, so it knows them, and parsing MP3
    frame headers to recover a number the provider already reports would be a second, worse
    implementation.

    **`Podcast.offsets` is a list PARALLEL to `utterances`, never a field on `Utterance`** —
    `Utterance` is the MODEL's output shape, and the model has no idea how long its own words take to
    say.

    **The consumer's guard is MONOTONICITY, not length alone.** A provider reporting no boundaries
    yields `[0.0, 0.0, ...]`, which is exactly as long as `utterances` — every line stamped `0:00`,
    one row highlighted for the whole episode, every click seeking to zero. `app.js`'s `timed`
    requires finite, non-negative, strictly increasing offsets AND a matching length; anything else
    renders a plain transcript (which is also what a persisted episode from before this field existed
    gets). Mis-aligned subtitles are worse than none.

    **Match ANY `*Boundary` event from edge-tts, not `WordBoundary`** — the installed edge-tts
    defaults to `boundary="SentenceBoundary"` and emits only that, so keying on `WordBoundary`
    returns every offset as 0.0. The boundary sum APPROXIMATES each utterance's duration rather than
    equalling it (measured error -0.049s..+0.066s per utterance, non-systematic in sign): fine for
    highlighting a line, and NOT a drift that grows in one direction. The drift-free alternative is
    named in the docstring and left as a follow-up.

    **A provider holding raw samples gets its offsets from a PURE FUNCTION, `tts.sequence_offsets`,**
    with the gap between utterances charged to the line BEFORE it, so an offset is where its own
    line's audio starts. Extracting the bookkeeping out of `synthesize` is what lets CI check it at
    all — with no extra, no model download and no audio. Both offset tests use THREE DIFFERENT
    durations on purpose: with equal ones, a running-total bug and a correct implementation produce
    the same list.

    **`.btn` sets `color: inherit`, `text-decoration: none` and `display: inline-block` because it
    has to work on an `<a>`** — the global reset covers `button` only. The `display` is what would
    enrol this file's most-used class in invariant 36's tripwire the moment anyone `hidden`-toggles a
    `.btn`, so `.btn` carries its own `[hidden] { display: none }` up front: a pre-emptive pairing,
    not a tripwire the code trips today.

    **The transcript scrolls in its OWN box (`.podcast-transcript.is-timed`) and the playhead follower
    moves `scrollTop` directly, never `scrollIntoView`**, which walks EVERY scrollable ancestor and
    would drag a listener who scrolled away back to the podcast panel every few seconds. Positions are
    read from `getBoundingClientRect`, not `offsetTop`, so the arithmetic doesn't break if the box
    stops being positioned. Only a TIMED transcript becomes a scroll box.

    **A transcript line seeks on click, but not when the click was meant for something inside it** —
    excluding `.citation, .citation-row, .citation-detail, .podcast-timecode`. `.citation-detail` is
    the expanded trace payload appended as a SIBLING of the citation list inside the same utterance,
    so clicking into that JSON would jump the player. `click` also fires on the mouseup ending a
    drag-selection, so a non-collapsed selection suppresses the seek. The `play()` promise is caught:
    a cleared file should be a silent no-op, not an unhandled rejection. **And a `.is-seekable:hover`
    rule must not touch a property `.is-speaking` sets** — the fix is DISJOINT PROPERTIES, not lower
    specificity: hover still wins any property it declares, it just declares `border-color`, which
    `.is-speaking` (`background` + `box-shadow`) never sets.

45. **The podcast script has a stated SHAPE, and is written to be SPOKEN in one language.** Asking
    only for "a natural conversation" gave episodes no opening, no segment plan and no close — they
    stopped when the model ran out of facts. The instructions ask for an opening that frames the
    sources, a body that follows the interesting thread rather than the sources' order, and a CLOSE
    that draws the threads together, with any reflection grounded in the sources ("what this makes me
    wonder" is honest, inventing a finding is not).

    **Foreign proper nouns stay as the source wrote them — this REVERSES an earlier transliteration
    rule, and the reversal is the point.** That rule existed because kokoro's Chinese G2P passed Latin
    text through unconverted, mangling `NASA`; kokoro is gone, and the assumption that this
    generalised was measured FALSE on the provider that actually ships (edge-tts renders mixed
    Chinese/English acceptably). `Utterance.text` is BOTH the transcript and the string the voice
    reads, and the transcript is what a listener falls back on when a word doesn't come through — a
    transliterated name is precisely the word they then cannot look up. **Acronyms are named
    explicitly** (a live episode duly contained `NASA` under a looser wording), and giving the
    original once in parentheses is forbidden: there is no reader-only channel to put it in. Numbers,
    dates and units still get spoken form — they read aloud badly everywhere and nobody looks them up.
    A `Citation.quote` is exempt and stays verbatim, because it is evidence a reader checks against
    the source (invariant 39's carve-out).

    **Accepted cost**: a provider with kokoro's weakness would now mangle those names. That is a
    provider problem to solve in the provider, not by degrading every transcript in advance. **Same
    residual-risk hedge as invariants 4 and 11** — this is a PROMPT-COMPLIANCE claim and the offline
    suite drives a scripted LM.

46. **Every run-taking handler ANNOUNCES its run id (`api._announced`) before any pre-work, not just
    before the spawn.** A DIFFERENT and much larger window than the one invariant 29 closed: that one
    sits between the exclusive-create and the registration a few lines later, while this one sits
    BEFORE the exclusive-create happens at all. Every one of these handlers calls `_resolve_language`
    first (invariant 39), a real model round trip in its own subprocess — and on a NEW notebook
    `output_language` is by definition unresolved, so that call ALWAYS happens and always outlasts
    `_TRACE_FILE_WAIT_GRACE` (5s). The client opens its ticker, waits five seconds for a trace file
    that cannot exist yet, and reports the run missing while the request itself succeeds.

    `_announced` reuses `_RUN_PROCESSES` rather than adding a second registry, because `stream_run`
    already reads it as "is anything still going to write this file". `setdefault`, so an id
    `_run_isolated` has already claimed is never downgraded; and the release only removes an id still
    at the `None` placeholder, because a spawned run belongs to `_run_isolated`'s own `finally`. A
    handler that fails before spawning DOES release, so a failed request can never make a stream wait
    forever. `_tail_trace_events` resets its grace counter while the id is announced.

    **Applied to all FIVE run-taking handlers, including `/title`, which no client currently
    streams** — it accepts `run_id` exactly like the others, and a rule with one silent exception is
    the kind that gets rediscovered as a bug report.

47. **Every long-running action shows that it is running and offers a way to STOP it, and no action
    starts without an explicit press.** All four surfaces — chat, the chat overview, each Guide kind,
    the podcast — mount the same `runStatus` component (pulsing dot, live action, ticking elapsed,
    Stop).

    **Stop cancels by RUN ID** (`POST /notebooks/{id}/runs/{run_id}/cancel`), because `/overview`
    fires TWO runs and invariant 23's `_ACTIVE_RUNS` holds one slot per NOTEBOOK — the notebook-scoped
    `/cancel` reaches only whichever registered last, so the user asks to stop and the other run keeps
    burning a model call to completion. `_RUN_PROCESSES` is already run-id-keyed and already holds the
    process, so cancelling precisely is a lookup, not a new registry. It `killpg`s the whole group
    (invariant 22) and reports an announced-but-unspawned id honestly rather than as a 404 reading
    "already finished".

    **Selecting a Studio tab does not start a run.** It used to fire a real RLM call on click, so
    browsing the four kinds to see what they were cost four model runs with no way to tell which click
    had committed them. Each tab shows what it is and offers a button.

    **A superseded generation SAYS SO.** A silent `return` in a staleness guard is indistinguishable
    from a hang, and it is the exact path that produces "pressed generate, it said Finished, then
    nothing ever appeared".

    **Panels say what they are for.** "Podcast", not "Audio Overview" (users did not know what it
    was), and Studio/Podcast/Notes each carry ONE visible sentence, with per-control detail in
    `data-tip` hovers — this project's own tooltip, not the native `title=`, whose ~1s delay made the
    help feel disconnected from the hover effect accompanying it. Notes says what a note is *for*,
    since neither the section nor the button explained that promotion is what makes it citable.

    `tests/test_web_assets.py` pins all of it as source-tree assertions, since there is no JS test
    runner.

48. **The INTERFACE language (`web/i18n.js`) is a browser preference, deliberately separate from the
    OUTPUT language (invariant 39, a server setting).** One decides what the buttons say, the other
    what the model writes. A reader in Taiwan may well want a Chinese interface over English papers,
    and folding the two together makes that combination unexpressible — so the UI language lives in
    `localStorage` and the settings page carries both, on separate rows, saying which is which.

    **The separation is NOT isolation**: the chosen interface language IS sent on every request and
    DOES reach a prompt (invariant 69). What survives is that they are two settings with two rows, and
    an explicit output language still wins outright.

    **`STRINGS.en` is EMPTY on purpose.** English is whatever `index.html` and `app.js` already say:
    static markup carries `data-i18n`/`-title`/`-placeholder`/`-tip` and keeps its own text as the
    fallback, and every `t(key, fallback)` call passes its English at the call site. So there is no
    English table to drift out of sync with a translation nobody updated. A tripwire fails the build on
    a bare `t("key")` (which would render the KEY to an English reader) and a second one on a key used
    but not translated, because a typo is otherwise invisible — `t()` falls back and the interface
    silently stays half-English.

    **`zh-CN`/`zh-Hans` deliberately does NOT resolve to the Traditional table** — shipping Traditional
    text to a Simplified reader is worse than leaving it in English. Detection is `localStorage` →
    `navigator.languages` → English.

    **A language change re-renders** rather than threading a language argument through every renderer:
    `setUiLang` re-applies the static markup and dispatches `ui-lang-changed`. A renderer added later is
    translated by construction instead of by somebody remembering to subscribe.

48.5. **The model must not number its own citations.** The interface numbers them itself, from the
    order it renders them in (invariant 60's `renumberStrokes`), and draws each as a highlight on the
    span the model named — so a `[1]` written into the sentence is a second, competing scheme by
    construction, and the two disagree on screen. **Prompt-only, deliberately**: a display-layer strip
    is what invariant 62 does for `[[SRC:...]]`, which is unambiguous, whereas a bare `[1]` is not —
    `arr[1]` is ordinary prose in this project's own subject matter, and stripping it would corrupt a
    quote or a code snippet to tidy a number. Same residual-risk hedge as invariants 4 and 11.

49. **`Citation.answer_span` is the model pointing at its OWN prose, and it exists because locating the
    highlight by `quote` stopped being possible.** The highlighter stroke used to find its span with
    `answer.indexOf(citation.quote)`, which works only while the answer and the source share a
    language. Invariant 39 made the prose follow the READER while the quote stays in the SOURCE's
    words, so the two never share a substring and NO span could be found again. Not a bug in either
    invariant — it is what 39 costs, paid here rather than by weakening the verbatim-quote rule.

    **`citations.locate_answer_spans` applies invariant 5's coordinate-existence discipline to the
    model's own text.** A span that does not occur VERBATIM in the prose is dropped; the citation
    survives. Losing a highlight costs a reader one affordance, highlighting the wrong sentence tells
    them a claim is supported when it is not. Matching is EXACT with one allowance — leading and
    trailing whitespace — and deliberately no case folding, punctuation normalisation or fuzzy match:
    each buys a few more highlights at the price of sometimes underlining prose the citation does not
    support. It verifies WHERE, never WHETHER.

    **`_citation_responses` takes the prose it must check against as a REQUIRED argument**, and every
    call site passes the string that artifact actually renders (a chat answer, an FAQ item's `answer`,
    a timeline event's `description`, a podcast utterance's `text`, the overview's `text`). It had a
    `""` default that SKIPPED validation when empty — a fail-OPEN default under a docstring promising
    the opposite — now simply not expressible. Passing the WRONG text is still silent (the spans stop
    being found and the page renders with no strokes), which is what the dedicated test pins.

    `instructions.CITATION_RULES` teaches it as the deliberate MIRROR of `quote`: `quote` is in the
    source's language, `answer_span` is in the model's. (NOT `VERBATIM_COORDINATES`, which does not
    mention `answer_span` at all.)

50. **A source can be REMOVED now, which ended append-only id numbering — and the survivors are never
    renumbered.** `notebook.next_source_id` derives from the MAX id in use; `len(sources) + 1` was
    correct only while sources were append-only, and the moment removal existed it produced TWO live
    sources under one id, with `Corpus.get` resolving whichever it reaches first, so a stored citation
    reads the wrong text — exactly what invariant 12 forbids, and the identical bug `_next_note_id`
    was written for (invariant 32) one field over.

    **There are TWO append sites.** `promote_note` appends to `notebook.sources` DIRECTLY rather than
    through `append_sources`, and it is the worse of the two, because promotion is the ONLY thing that
    makes a note citable — a colliding promoted note is unreachable by any citation.

    **`remove_source` deletes the first match by index rather than filtering every id-equal entry, and
    RAISES on a miss.** `mutate_notebook` writes the file unless the delta raises, so returning `False`
    meant a 404-ing DELETE still did a full save and bumped the mtime invariant 53 made the picker's
    sort key.

    **Nothing is renumbered on removal, and that is what makes removal safe to offer.** A citation
    pointing at the removed source comes back UNVERIFIED with a reason (invariants 5 and 11) rather
    than silently resolving to a different source's text, and persisted artifacts are marked STALE by
    invariant 38's set-equality comparison.

51. **`Source.preview` is display-only page metadata, scraped from html already in hand, and it NEVER
    references an image.** `parsers/web.extract_preview` reads og:/twitter:/`description`/`<title>` out
    of the SAME html `parse_web` already fetched — one host-side request per source, as invariant 1
    requires; a preview that fetched anything of its own would quietly break that. The corpus blob is
    built from `blocks` alone, so a page controlling its own `<meta>` tags influences what a Sources row
    LOOKS like and nothing the model reads — the same trust level `origin` already carries, rendered
    with `textContent` for the same reason.

    **`og:image` is deliberately absent, and adding it back looks like an obvious improvement.**
    Rendering one makes the READER's browser fetch a URL the page author chose, handing that third party
    the reader's IP and a request to log — every pasted link becomes a beacon, in exchange for a
    thumbnail. Pinned by a test. Regex rather than an HTML parser because the point is to add no
    dependency to an ingestion path where `trafilatura` already does the real work; a malformed match is
    a cosmetic miss, never a hazard.

    **Every quantifier in those patterns is BOUNDED and the input is windowed to the `<head>`, and both
    are load-bearing.** With an unbounded `[^>]*?`, a page of UNCLOSED `<meta` tags backtracks
    catastrophically — cubic, and `re` does NOT release the GIL, so `asyncio.to_thread` buys the event
    loop nothing. On a no-auth API where any caller can paste any URL, that is a one-request freeze of
    the whole server.

52. **The live ticker's event shape is `{kind, primary, detail, meta}` and it carries the model's own
    words — but never the step's OUTPUT.** `_translate_trace_event` used to emit one fixed sentence per
    event type and throw the payload away. `summary` is kept as `primary` + `detail` so a consumer
    written against the older one-line shape keeps working, and the synthesized terminal event for an
    orphaned run comes from `_orphaned_run_event` rather than a hand-written literal — two copies had
    already drifted back to the older form.

    **`detail` is the model's own prose in the main case, and not ONLY that**: a `main_step` with no
    `reasoning` falls back to the step's CODE, and a `result` event carries its output dict's KEY NAMES.
    The step's `output` is where whole corpus spans land and is deliberately NOT streamed; its SIZE is
    reported instead, which is the part that tells a reader whether a step did much. `_DETAIL_CHARS`
    bounds the rest, because this goes down an SSE stream once per step. The full text stays in the
    trace file the citation-turn lookup already reads.

    **`run_end` with `ok=False` is `kind: "failed"`, not `"done"`** — any client's terminal-state check
    has to accept BOTH, or a failed run's ticker never closes.

53. **Renaming is a separate VERB from generating a title, and a rename REFUSES rather than derives.**
    `PUT /notebooks/{id}/title` sets what a user typed; `POST` to the same path runs
    `naming.SuggestTitle`. Setting a title is an instant write that always succeeds; generating one is a
    model run that can fail, take seconds and be superseded — folding them into one endpoint would give
    rename the failure semantics of a model call for no reason. `naming.normalize_title` is split out of
    `clean_title` because the two callers need OPPOSITE things from an unusable value: generation falls
    back to a derived label (a notebook must end up with one), a rename returns 422, because silently
    substituting a derived title for what someone typed would be the UI lying. It still normalises,
    because this API has no authentication and "a person typed it" is not a provenance claim.

    **A model-authored title is NOT unique, so the picker orders by file mtime.** Since invariant 37
    stopped showing the id anywhere, "which one did I touch last" is the only thing left to tell two
    same-named notebooks apart. The timestamp is carried out-of-band (`notebook._MTIMES`/
    `last_modified`) rather than added to the schema: it is a property of the FILE, and a schema field
    would mean writing a timestamp nobody reads on every mutation.

    **`derived_title` appears in BOTH `NotebookSummary` and `NotebookResponse`**, or the header says
    "Untitled notebook" while the picker row shows a derived label for the same notebook. It is
    `naming.fallback_title` and costs no model call, which matters because titling is lazy (invariant
    37) — a notebook someone has only put sources into would otherwise sit in the picker as "Untitled"
    forever.

    **`GET /settings/choices` serves the settings page's dropdown values, and must never call
    `_config()`** — invariant 41's reason, one endpoint further. A voice name is provider-specific, so
    the answer depends on `RN_TTS_PROVIDER`, read straight from the environment; an unknown provider
    yields an empty voice list rather than raising, so the page still renders. Served rather than
    hardcoded in JS because a second copy would drift from `tts._LANGUAGE_VOICES`.

54. **Two more web-UI hazards that ONLY a source-tree assertion can catch, both extending invariant
    36's reasoning to properties nothing else in this project can see.**

    **A tooltip host must not clip its own tooltip.** A `data-tip` tip is an `::after` on its host, so
    any clipping `overflow` on that host erases it outright — no console error, no layout shift, just
    an affordance that stops existing. `test_no_tooltip_host_clips_its_own_tooltip` harvests tip-bearing
    classes from the markup, from `dataset.tip` in `app.js`, and from stylesheet rules already naming
    `[data-tip]`. **A HORIZONTAL clip at the left edge is fixable, and removing the tip is the wrong
    instinct**: `[data-tip]::after` anchors `right: 0`, so a wide panel on a control at the LEFT edge of
    a scroller extends off it — the fix is to anchor into the space the control actually has
    (`left: 0; right: auto`).

    **An ANCESTOR's clipping overflow does the same thing and is NOT covered** — finding those needs a
    DOM this suite does not have. `.col`'s `overflow-y: auto` is exactly such an ancestor (one
    non-visible axis forces the other to `auto`), which is why both tab rows anchor their tips to the tab
    ROW rather than to a tab, in their EXPANDED state. The collapsed rail deliberately does not: it
    anchors to the button and opens LEFTWARD, safe only because `.col-studio.is-collapsed` sets
    `overflow: visible`.

    **A drag threshold pair must not be inverted.** A two-state toggle driven by one continuous value is
    stable only while the OPEN threshold is at or above the CLOSE one; setting `STUDIO_EXPAND_AT` below
    `STUDIO_COLLAPSE_AT` to make re-opening cheap turns the gap into a band where every `pointermove`
    flips the state. Expanding at exactly `STUDIO_MIN_WIDTH` both satisfies the ordering and opens with
    no jump, since at the crossing the pointer and the panel are the same number; the dead band it
    creates is covered by stretching the RAIL under the pointer, never by breaking the ordering.

    **Applying a width and REMEMBERING one are separate.** Persisting on every `pointermove` made
    dragging the panel away overwrite the user's own width with the minimum clamp; a drag commits only
    when it ends, and only if it ended open.

55. **Markdown in an answer is rendered by a HAND-WRITTEN renderer that builds DOM nodes, and a link in
    it is shown but NOT navigable.** Answers arrive full of raw `**bold**`, `## heading` and `- list`
    characters because the model writes markdown whether or not anyone asked.

    **No library and no HTML strings**, which is invariant 29's rule stated where it costs the most.
    Every string here came out of a model that has been reading source content an attacker may have
    written (invariant 6); one missed `esc()` in a string-building renderer is an XSS sink, and building
    nodes removes the failure mode instead of guarding it.

    **A `[label](url)` renders its label with the URL revealed on hover and COPIED on click, never an
    `<a href>`.** Invariant 1 refuses to let the MODEL reach a URL because a prompt-injected source could
    steer it into exfiltrating notebook contents; a clickable link in an answer is the same hazard with
    the READER's click as the transport, arriving dressed as a citation-grounded reference. A stated
    trade — `createElement("a")` is exactly what a later edit reaches for, since the renderer has the URL
    in hand. Copy-on-click exists because CSS generated content is not selectable, so "shown so a reader
    can copy it" was not otherwise true.

    **The renderer never creates a text node.** It walks RAW OFFSETS into the original string and appends
    through `emit`, which is where a citation range is split out — that is what lets block structure and
    citation strokes compose rather than one being applied on top of the other's output. A renderer that
    made its own text nodes would silently produce prose no stroke can reach.

    **`data-reference` is stamped AFTER the whole answer is built, not decided while emitting.** A stroke
    crossing an inline `**bold**` is emitted as several fragments, and an `isLast` test of
    `sliceTo === match.end` never fires when a span's final characters are syntax the renderer DROPS (a
    closing `**`, a backtick, a link's `](url)`) — so the stroke got NO number while the References panel
    numbered it anyway, which is the two-lists-to-join-by-eye that invariant 58 exists to remove.
    Collecting the fragments and stamping the last one afterwards is decided where every fragment is
    known.

    **Emphasis follows a simplified CommonMark flanking rule**, without which `3 * 4 * 5` renders as
    `3 <em>4</em> 5` and `my_var and other_var_name` mangles — multiplication and snake_case identifiers
    both appear in this project's own subject matter.

    **Known limits**: a blockquote does not nest other blocks; a `.md-link` tooltip inside a table is
    clipped by `.md-table-wrap`'s scroller (invariant 54's uncovered ancestor case, mitigated by
    copy-on-click working everywhere); and `renderMdList` recurses per indent level, bounded in practice
    by the corpus cap.

56. **`Answer.follow_ups` comes from the SAME run that produced the answer — never a second model call —
    and is not verified against anything.** The model already holds the corpus and its own answer in
    context when it submits, so asking for two or three next questions in the same SUBMIT costs nothing;
    a separate `dspy.Predict` per turn would be a real call per answer for the same words. Deliberately
    NOT citation-grounded: a question is a prompt, not a claim, so invariant 5 has nothing to check. The
    instruction still requires each be answerable from `sources` — prompt compliance, with the usual
    hedge. Optional and defaulting to empty, so turns persisted before the field existed still load.

    **The two labels are deliberately NOT unified**: the overview's row says "Start with" and a turn's
    says "Ask next", sharing one renderer (`starterQuestionRow`). The overview's appears before any
    conversation exists, where "ask next" would be asking the reader to continue something they have not
    begun.

57. **The chat overview is the THREAD's first entry, inside the scroller — not a panel pinned above it.**
    As a sibling of `.chat-history` with `flex: 0 0 auto` and `max-height: 45%` it permanently owned up to
    half the chat column; inside the scroller it simply scrolls away as the conversation grows. The
    `max-height` was there for a real reason — as a sibling it was a flex item whose automatic minimum
    size is its content, which would have collapsed `.chat-history` — and that reason evaporates once
    there is no competing flex item.

    **A returning reader must not LAND scrolled past it**: `chat:turnAdded` scrolls to the bottom, and
    replaying a saved conversation fired it once per turn, so the overview started far above the fold.
    Only a genuinely new turn scrolls now.

    **Every path that redraws the thread goes through `rebuildHistory`**, which re-appends the overview
    node; a `history.innerHTML = ""` that forgot to would silently delete it.

58. **A reference is a compact ROW that opens, and pointing at either end of a citation lights up the
    other.** Rendering every quote as an always-visible `blockquote` let one source cited eight times fill
    the whole column. The shape now is number, title, a provenance chip, the use count, TWO clamped lines
    of the passage, and everything else behind a click.

    **`linkReference` is the reciprocal highlight**, without which a numbered stroke and a numbered row
    are two lists a reader has to join up by eye. **`.is-linked` is kept DISJOINT from `.is-focused`** —
    hover owns `background`, focus owns `border-color` plus an inset bar — so hovering one reference can
    never wipe the focus ring on another. (Both setting `background` at equal specificity is the same
    mistake invariant 44 records, made again.)

    **`referenceKey`'s separator is `\u001f`, and U+0000 is a trap.** Every lookup is a
    `[data-ref-key="…"]` selector, and `CSS.escape` maps U+0000 to U+FFFD by spec — as does the CSS
    tokenizer parsing the selector — so a key joined with a NUL can never match ANY element, and the
    reciprocal highlight was dead on arrival. Unreachable from the Python suite.

    **The run log is a TIMELINE**: one continuous rail with a node per step, the current step pulsing and
    shown in full, past steps clamped and expandable. Four per-line left borders read as four unrelated
    items; a rail reads as one process advancing. Node colour comes from the step's KIND and "current" is
    the animation plus a ring — disjoint properties, because the two rules sit at equal specificity. Each
    row shows how long its step took as VISIBLE text, because "where is it stuck" is a question about
    durations and a column of absolute stamps makes the reader subtract — visible rather than a tooltip
    because `.run-log` is a scroller and a tip anchored inside it is clipped (invariant 54's ancestor
    case). The FIRST row measures from the run's start, since that gap is the wait for the model's first
    response. `finish()` clears `is-current`, or the last step keeps pulsing while the header says
    Finished.

59. **The four budget defaults are each a decision, and `max_tokens` is the one that silently kills a
    run.** `RLMConfig`'s own defaults are 10 / 8192 / 10,000 / 1; this project ships
    `max_iterations=25`, `max_tokens=16384`, `max_output_chars=40000`, `max_retries=1`.

    **`max_tokens: 16384` — a per-call GENERATION cap, and a trap for a reasoning model**, whose
    chain-of-thought is billed against a cap it never appears in, so the reply arrives cut mid-JSON and
    fails to parse; `max_retries=1` then makes that terminal, since a second attempt hits the same
    ceiling. It is NOT only the planner's: `runtime.configure` builds ONE `lm_kwargs` and hands it to both
    `dspy.LM(cfg.main_model)` and `dspy.LM(cfg.sub_model)`. On the `claude-agent-sdk/` subscription path
    (invariant 35) it is ENTIRELY INERT — `ClaudeAgentLM` tolerates and ignores sampling kwargs — so it is
    visible in the trace and applied to nothing, the same shape invariant 7 records for `ocr_provider`.

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

60. **A status line may not claim something the page is not doing, and a repaint may not delete a run.**

    **`runStatus` tracks `awaitingFirstReply` separately from `stepsSeen`.** `setPhase` names a stage the
    TRACE CANNOT SEE — the podcast's synthesis half, which runs in-process with no events — so "waiting
    for the model's first response" is simply false there, and `paint`'s pre-first-step branch REPLACES
    the phrase rather than appending, so a phase set at second 0 is silently gone by second 20. With
    chatterbox synthesis running up to fifteen minutes (invariant 43) that was the whole second half, and
    it reintroduced the "watched it for seven minutes and read it as a crash" complaint the long-wait tier
    was added to fix.

    **`.btn:disabled` is styled, not just `.btn-primary:disabled`.** A disabled Stop was pixel-identical
    to a live one, so `stoppable: false` produced a control that looked operable and swallowed the click.
    Disabling rather than hiding is still right (a control must not vanish out from under a pointer), but
    only if disabled LOOKS disabled.

    **Only a SUCCESSFUL script run leads to synthesis** — flipping the phase on any terminal kind announces
    a stage that will never start, and greys out Stop, until the HTTP error lands.

    **A repaint carries the run in flight with it.** `chat:rerender` rebuilding the thread from
    `state.turns` alone deletes a running question, its status and its only Stop — invariant 47's rule
    broken by a repaint. The pending turn is a closure variable, cleared on completion and on cancel (a
    stale one would render the same question twice).

    **Stroke numbers are re-stamped across the WHOLE PAGE, not just the surface that changed.**
    `collectReferences` orders overview → turns → podcast → guides, so adding one chat turn shifts the
    number of every podcast and guide coordinate — and those panels do not re-render. `renumberStrokes`
    walks every `.citation[data-ref-key]` and re-stamps from the current order, deliberately instead of
    re-rendering: re-rendering the podcast rebuilds its `<audio>` and would interrupt playback, and it is
    the NUMBER that went stale. A number that resolves to nothing leaves the attribute ABSENT rather than
    setting `"0"`, because `content: attr(data-reference)` renders the literal character.

    **A substring assertion is not a behavioural one.** `test_web_assets.py` assertions check a rule's
    SUBJECT (its last compound), the ORDER of two branches, the DIRECTION of a comparison, and the literal
    mapping expression — because token-appears-somewhere checks walked past six of twelve mutations,
    including `i + 1` → `i`, the exact off-by-one the numbering change exists to fix. A duck-typed stand-in
    gets the same treatment: every method called on it is checked against the ones it defines.

61. **The cheap `dspy.Predict` callers read `Corpus.excerpt`, never `blob()[:n]` — a prefix is source ONE,
    not the notebook.** `naming.SuggestTitle` and `naming.SuggestLanguage` cannot read a multi-MB corpus
    (invariant 37), so they get a window; but the blob concatenates sources IN ORDER, so a 69,859-character
    first source against a 4,000-character budget made sources two through four invisible — a four-source
    notebook got titled by transliterating source one's own paper title. **Language resolution read the
    same prefix, and that is the worse half**: a notebook whose later sources are in another language would
    resolve the wrong one, and invariant 39 then persists that guess and stops re-resolving.

    `excerpt(n)` gives every source an equal share taken from its START — a paper, a page or a report
    states its subject in the opening lines. The prompt matches: name what the COLLECTION is about, with
    "translate source one's title" as the named failure mode.

62. **A `[[SRC:...]]` marker is a coordinate for the interface and must never reach the reader — stripped
    at the DISPLAY boundary, not before persisting.** Invariant 4 tells the model to echo a marker into a
    `Citation`; it says nothing about ALSO writing one into the sentence being composed, which a real run
    did. **On the way OUT, so nothing stored is rewritten and every notebook already on disk is fixed with
    no migration** — rewriting on the way in would make an old notebook and a new one disagree about their
    own history.

    **`api._prose` is the ONE place, and the same value goes to `_citation_responses`.** Handing the raw
    text to one and the stripped text to the other is silent in both directions: the markers vanish from
    screen and every `answer_span` stops being locatable, so every stroke disappears — invariant 49's
    failure mode one layer down. `locate_answer_spans` strips the SPAN too, because a span copied out of
    the model's own prose can carry a marker with it.

    **Removing a marker leaves a HOLE, and closing it is done at the hole — never globally.** A marker
    between a word and its punctuation leaves `claim . Next`, cosmetic on screen and audible in synthesis.
    A space-before-punctuation rule over the whole string is wrong twice: it normalises text that never had
    a marker (French typographic spacing), and because `strip_markers` early-returns on a marker-free
    string, the prose and the `answer_span` would then get DIFFERENT normalisation and the span would stop
    matching. `_close_gap` is a replacement function on the marker match itself, so it can only ever edit
    the whitespace the marker sat between.

    The prompt gained the rule as well. A display-layer strip is a NET, not a reason to stop asking.

63. **The podcast has a LENGTH, chosen at generation time, and the tiers are numbers rather than
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

    **The CHOICE is remembered in the browser (`localStorage`), deliberately not on the server.** It is a
    per-reader habit, not a notebook property — one person who always wants `long` should not impose it on
    a shared notebook. This is the WHERE-IT-LIVES half of invariant 48's split, only that half: the length
    IS sent on every generate and DOES reach the prompt, because it changes what the model writes.

    **Honest calibration gap**: the turn counts are met and the minute figures are not (`long` produced 80
    turns, inside its 60-90 target, but about 14-15 minutes against a stated 18-25 — the minutes were
    computed from an assumed ~90 characters per turn and the real figure is ~56). One sample per tier is
    not enough to recalibrate on, so both numbers stand.

64. **A `long` script is built across REPL turns, and that is what the sandbox is FOR.** Written as one
    code block it was TRUNCATED by the per-call generation cap mid-structure and the run failed;
    accumulated in a list across turns — printing only its LENGTH, never its contents — the same corpus and
    the same cap produced 80 utterances with 44 citations, with **nothing about the budget changed**. This
    is the second time a truncation could have been answered by raising `max_tokens` and the first time it
    should not have been: invariant 59's raise was correct because the PLANNER's reasoning did not fit, and
    this is an OUTPUT that should never have been one reply. **If a finished object will not comfortably
    fit in one reply, it must not be written in one reply** (also `instructions.ACCUMULATE_LARGE_OUTPUTS`,
    invariant 65).

65. **Every RLM task here carries `rlm_harness.skills` with `discovery="inject"`, and the prompt/skill
    split is a rule rather than a preference.** (This is `rlm-harness`'s own mechanism, distinct from the
    Claude Code skills a coding agent reads and this task never sees.)

    **The split**: a skill is read only if the model chooses to, so anything that CORRUPTS the output when
    skipped stays in the PROMPT — grounding, citations, the marker rule, language, the output shape, the
    length target. Craft and measured technique are what a skill is for: work done without them is duller
    or more expensive, not wrong. A no-disfluencies rule and a good-close rule appear in BOTH, deliberately:
    they are must-apply so they cannot leave the prompt, and the skill is where the REASON lives.

    **`instructions.ACCUMULATE_LARGE_OUTPUTS` is the one line of that split that had to be fixed.** The
    build-across-turns mechanic (invariant 64) is must-apply by its own account — skipping it LOSES the run
    — yet it lived in `GeneratePodcastScript`'s prompt only, existing for the other five tasks solely in an
    optional skill a model may never read. It is a shared constant composed into all six now, worded
    CONDITIONALLY, because a short answer built across turns wastes the step budget just as surely as a long
    one written in a single reply loses the run. The podcast keeps its TIER-SPECIFIC pointer and no longer
    restates the mechanic. A tripwire asserts all six carry it and the podcast holds exactly one copy.

    **`instructions.apply_skills` is the ONE copy of the wiring**, next to `CITATION_RULES` and for the
    identical reason: six tasks each calling `load_skills_as_tools` would each own a catalog header, and
    the headers would drift. A test forbids `load_skills_as_tools` from appearing in `audio.py`/`guide.py`/
    `task.py` at all.

    **The catalog is CLOSED (`</available_skills>`) and the MANIFEST decides whether anything is wired at
    all.** Without an explicit close, every rule in the task's own prompt reads as though it were inside the
    skills element. Gating on the manifest rather than on the directory existing is what stops an empty
    directory from adding `read_skill`, whose own description tells the model to pick from a manifest that
    would not be there. Pinned in both directions.

    **`skills_dir` is a constructor argument defaulting ON**: a test points it at a fixture and `None` turns
    it off, which a caller needs because a stale skill is worse than an absent one — and defaulting ON
    because a planner that has to be told to consult its own knowledge base will not. `read_skill` resolves
    a NAME against the skills discovered at construction, so it cannot read an arbitrary path and never
    touches the network; invariants 1 and 14 are about reaching the outside world, which this does not do.

    **ONE directory for every task**, because `discover_skills` takes a single directory and does not
    recurse, and a catalog line per skill is cheap. Split it when a chat turn is measurably paying to be
    told about podcast craft — not before. The files ship inside the wheel for invariant 29's packaging
    reason.

    **Provenance is part of the craft.** A skill is a durable claim about how to work; an unchecked quote in
    one is worse than no skill, because a later reader has no reason to doubt it. Every technique in
    `podcast-craft` must be traceable to a source someone actually opened, or to this project's own
    measurement.

66. **The pre-SUBMIT validator is `instructions.make_grounded_validator` for EVERY task — schema plus "no
    `[[SRC:...]]` marker in the model's own prose".** The marker check was written for the podcast, whose
    failure was loud (the voices read the markers aloud), but it was a guard on the SYMPTOM:
    `GenerateSummary` produced the same defect silently. Six tasks each holding their own validator is how
    one of them ended up with a check the other five lacked.

    **Not a schema-level reject, deliberately.** Nothing rewrites a stored artifact (invariant 62 strips on
    the way OUT), so a notebook written before this validator existed holds whatever the model produced —
    and a field validator would make those files fail to LOAD, turning untidy data into a corrupt-notebook
    409. The check belongs where the model can still act on it.

    **`Citation.quote` is exempt**: a quote is copied verbatim out of a source, so a source containing the
    literal text `[[SRC:` would make an honest quote look like a violation. Every other string in every
    output model is the model's own prose, where a marker is always wrong.

    **`_marker_offenders` reads `model_fields` off `type(value)`, walks dicts and sets as well as lists, and
    its rejection message BRANCHES on where the marker is.** Each is a fail-open, not a refinement: reading
    `model_fields` off the INSTANCE is deprecated in pydantic 2.11 and removed in 3.0, so the walk would one
    day return "no offenders" for every input while still passing every test; a dict field skipped silently
    is the same hole; and telling a model to "put the coordinate in the accompanying `citations` entry" when
    the offender IS a citation field is advice it cannot follow, costing the whole step budget looping on
    it. **A guard that fails open is worse than no guard, because the prompt still promises it.**

    **Three layers, none sufficient alone and all cheap**: this validator (before SUBMIT),
    `citations.strip_markers` at the display boundary (invariant 62), and `tts.spoken_script` before
    synthesis.

    **A net must not be able to destroy what it was protecting.** A line that is NOTHING but a coordinate
    strips to `""` or a lone piece of punctuation, and `EdgeTTSProvider` raises `NoAudioReceived` for
    punctuation-only text — a `TTSError`, a 502, and the whole paid-for RLM run discarded. So a net added to
    stop a marker being READ ALOUD would have turned a survivable defect (a garbled line) into a lost
    episode. `tts.spoken_script` falls back to the ORIGINAL text when nothing alphanumeric survives. The
    fallback is justified by the DEFAULT provider, where the failure is measured;
    `ChatterboxProvider`'s behaviour on a stripped-empty line is simply UNMEASURED.

67. **The pre-SUBMIT validator checks each citation's COORDINATE against the corpus this run was given, and
    the six tasks share ONE base class instead of six identical `__init__`s.** The observed failure is
    specific: every web source is one block with locator `whole`, and a model wrote the SECTION HEADING it
    was citing into `locator`, turning every citation in an overview unverified.

    **`citations.verify_citations` remains the guarantee (invariant 5); this is the early warning** — the
    same ground truth, computed from the SAME blob, applied while the model can still fix it rather than
    after the reader has found it. `instructions.coordinates_in` extracts every `source_id|locator` pair
    that actually occurs as a marker; `_cited_coordinates` walks the output model STRUCTURALLY (anything
    carrying both fields) rather than importing `Citation`, so a future citation-shaped model is covered
    without anyone remembering this function.

    **The rejection shows a REAL coordinate, not just which ones are wrong.** The failure is a model
    composing a locator out of the passage's own wording, and a message that only says "wrong" invites it to
    compose a different sentence.

    **It fails OPEN when the blob yields no markers at all**, deliberately rather than as an oversight of
    invariant 66's rule. An empty set means "we do not know what is valid here"; rejecting every citation of
    a legitimate run is far worse than letting server-side verification catch an invented one. The trigger
    is stated and tested, which is the difference from the silent kind.

    **`instructions.GroundedTask` is the base all six tasks share.** The check needs a per-RUN value, which
    a `ClassVar` tool list composed at import time cannot hold: `arun` captures the blob before the model
    can cite anything, and the validator is built per instance from `output_model`. That deleted six
    byte-identical `__init__`s AND six `tools: ClassVar = [...]` lines — six chances for one task to get a
    weaker validator, which is exactly how the marker check spent a slice living only on the podcast.

    **Consequence: `Task.tools` is now EMPTY at class level.** Tests asserting invariant 1 against that
    ClassVar would pass against a tuple of nothing, checking precisely what a run does not use. They
    construct an instance instead.

68. **A wall-clock backstop scales with the work that was asked for (`schema.PODCAST_TIMEOUT_FACTOR`).** A
    `long` episode 502'd at the 300s default having written three trace events, and on the same notebook an
    ordinary chat answer took 77s across 4-5 planner turns — so a tier asking for 60-90 utterances
    ACCUMULATED ACROSS TURNS (invariant 64) could not have fitted, and invariant 63 shipped a tier unable to
    finish under its own default. The backstop exists to catch a RUNAWAY, not to cap work a reader
    explicitly requested; scaling per request keeps a runaway CHAT turn bounded at the value it always had,
    and an operator's `RN_RUN_TIMEOUT_SECONDS` still moves every tier because the factor multiplies it. The
    table lives NEXT TO the tier literal, and a tripwire asserts every tier has one and that the factors
    never decrease.

69. **The INTERFACE language is a SIGNAL to output-language resolution — a fourth one, ranked above
    `Accept-Language` — which narrows invariant 48 without merging it.** A user running a Chinese interface
    got an English notebook title, because the one place they had actually SAID which language they read
    was invisible to `naming.SuggestLanguage`.

    **Chosen beats inherited.** `Accept-Language` comes from the operating system; the interface language
    was picked in this app. That ordering is the whole justification, and it is the same reasoning invariant
    39 uses to weight typed questions highest. Invariant 48's separation survives: two rows on the settings
    page, and an explicit output-language setting still wins outright.

    **Carried in a header (`X-RLM-Interface-Language`), added once in `app.js`'s `api()`** —
    `_resolve_language` is reached from every run-taking endpoint, so a body field would be five schema
    changes and a sixth one forgotten. **The value sent is the language's ENGLISH NAME, not `zh-Hant`**: the
    model answers in English language names, so sending a code or a word in the very language it is
    identifying makes it parse rather than weigh.

    **A proper noun is never translated (`instructions.PROPER_NOUNS`)** — translating the WORD hands a
    reader a term they cannot search for, which is the opposite of what a research notebook is for.
    Composed into BOTH `chat_language_rule` and `artifact_language_rule` from one constant (invariant 13),
    plus the title prompt, which is a plain `dspy.Predict` and shares nothing. This generalises invariant
    45's reversal from the podcast to every artifact a reader might search from.

70. **The Trajectory drawer (`trajectory.py` + `GET .../runs/{run_id}/trajectory`) is where a run's
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

    **Interface copy is built from the BOOLEAN, not from the server's sentence.** `timing_note` is English
    prose written in Python, and rendering it verbatim put an English line in the middle of a Chinese
    drawer. The server says WHICH case holds; the interface says it in the reader's language (invariant 48).

    **There are TWO "⌁ N steps" affordances and moving one is not moving both.** `runStatus` owns the LIVE
    log during a run; `renderTickerAffordance` owns the PERSISTED pill under a finished artifact — and it is
    the one a reader presses most, because most of the time the run is over. Both open the drawer.
    `.ticker-detail` was one of invariant 36's tripwire sentinels and is replaced by `.traj-drawer` rather
    than dropped, with the extraction gaining a route for a BARE `hidden` attribute in the markup, which all
    four existing routes were blind to.

    **A timeline segment is sized `flex: <duration> 0 <floor>px`, and BOTH halves fix the other's failure**:
    `flex-grow` against the strip's TOTAL divides it into unreadable slivers, while a fixed `width` leaves a
    one-call run stranded beside empty space. Grow makes a short run fill the strip; the basis is a floor so
    a fast call stays legible and the strip SCROLLS rather than squashing. **A segment's label is the
    TARGET, not the family** — the family, offset and owning turn live in the detail pane, which is where
    clicking a segment lands anyway. A `data-tip` on a `.seg` is doomed twice over: the segment clips
    itself, and `.traj-timeline` is an `overflow-x` ancestor (invariant 54's uncovered case). **A
    fixed-height box with `overflow: hidden` needs its line-heights DECLARED** — a 72px segment stacking
    icon, label and duration at the browser's ~1.5 default measures 74.3px and slices the MIDDLE line
    through its letterforms; a test recomputes the sum from the stylesheet.

    **`worker.py` records what the run was configured with AND what it was asked to do** — model names,
    budgets, the corpus SIZE, and every short scalar input by name (the question, the resolved language, the
    requested podcast tier). Each answers "why did it produce that" and none is derivable afterwards from a
    notebook that has since moved on. **The corpus TEXT never goes in** — its size does, invariant 52's
    reasoning — and neither do `api_key` or `base_url`.

    **An empty panel reads as broken, so the empty STATE names which empty it is**, and the branch stays
    reachable regardless of old traces being cleared: `_run_isolated` reserves the trace file exclusively
    BEFORE spawning and `run_trajectory` stops at a torn final line, so a run opened in its first moments,
    one whose spawn failed, or one killed instantly has a real file with zero events.

71. **A repaint may not delete a RUN — and `#chat-overview` is owned by its generation while one is in
    flight (`overviewRunning`).** Invariant 60 fixed this for the pending chat turn; the overview's OWN run
    had the mirror-image hole. `renderChatOverview` clears the element holding the run's pulsing dot, its
    elapsed counter and its only Stop, and several callers invoke it for reasons unrelated to the run. The
    guard sits at the TOP of `renderChatOverview`, so every caller is covered without anyone maintaining a
    list. Worse than it sounds because of a deliberate decision one line away: `sources:changed` does NOT
    bump `overviewToken` — stranding a generation the server has already paid for would be the bigger bug —
    so the run stays live with no way to see or stop it. Both decisions are individually right and were
    never checked together.

    **A notebook SWITCH must release the flag, not just bump the token**, or the new notebook's panel keeps
    the previous run's status node. **And `!live()` covers two situations, only ONE of which belongs to this
    panel**: a second press of Generate is a supersede and must SAY so (invariant 47 — a silent `return`
    reads as a hang), while a notebook switch is not, because `#chat-overview` belongs to a different
    notebook by then and `supersededNote` would overwrite ITS overview. Both call sites guard on
    `generation === notebookGeneration`.

    **Regenerate is UNCONDITIONAL once an overview exists; `offerRegenerate` picks its LABEL and WEIGHT
    instead of its existence.** Gating it on stale-or-incomplete left an overview that is current and
    complete but WRONG — the state a reader most wants out of — with no control on the page at all. Quiet and
    short when nothing is wrong (regenerating costs two real RLM runs, so it must not be the loudest thing on
    a panel that already holds what it makes), louder and explicit when stale or incomplete. That is the
    three-state treatment invariant 42 gave the podcast's button.

    **`/overview` runs TWO tasks and its ticker follows ONE**, so forwarding the summary run's terminal event
    made the shared status line say "Finished" beside a live Stop while the FAQ half was still running —
    invariant 60's rule broken by a second RUN rather than by a phase, which is why the fix reuses `setPhase`.
    It stays STOPPABLE: `runIds` carries both ids and the FAQ run is genuinely cancellable.

    **The chat composer IS frozen while an overview generates — a product decision, NOT a race**, and the
    COMPOSER only, never the thread. The two runs are independent, `mutate_notebook` makes both writes land,
    `rebuildHistory` re-appends the SAME `overviewEl` node, and invariant 60 makes the reverse safe. Nothing
    is lost either way; the reason is that a question asked into a thread whose overview is being rewritten
    READS as two things fighting whether or not they are. Recorded so a later reader does not "simplify" it
    away as redundant with the locking. Every exit thaws it — cancel, success, error, and a notebook switch,
    which strands the run rather than ending it and would otherwise freeze the NEW notebook's composer.

    **A chat answer can be regenerated, and only the LAST one.** Every later answer was produced with this
    one in its `history` (invariant 11), so redoing a turn in the middle would leave the answers after it
    derived from a conversation that no longer exists. Gated by a STYLESHEET rule
    (`.turn:not(:last-child)`), because turns reach the DOM through two paths (`rebuildHistory` and the
    `chat:turnAdded` replay) and a rule that reads the DOM is right for both without either having to
    remember — and it hides the control during a pending question for free. The SERVER re-checks
    independently: `AskRequest.regenerate` replaces `turns[-1]` only when its question still matches, inside
    the lock, so a request landing after someone else asked something new appends instead. **Replacing
    rather than appending**, because the reason a reader regenerates is that the answer was wrong, and
    keeping it in the thread keeps it in `history` for every future turn. Both entry points share ONE flow
    (`askQuestion`) — the pending row, the ticker, Stop, the cancel path and the rebuild are what would
    drift between two copies.

    **A conversation can be CLEARED (`DELETE /notebooks/{id}/turns`), which is the other end of the same
    fact**: regenerate reaches the last answer only, so clearing is the only honest way to undo a turn in
    the middle, and turns were otherwise the one thing here that could only grow. Sources, notes, the
    overview and the podcast are untouched and nothing is marked stale — an overview's `source_ids` are
    about the CORPUS, which has not moved. The confirmation names what SURVIVES as well as what goes, since
    losing sources is the fear a destructive control in the chat panel invites.

    **Clearing is DISABLED while a question is in flight**: the server would delete the turns and then
    `ask`'s own persist would append its answer to the now-empty list, so the conversation the reader just
    cleared comes back with one entry in it. Stop is the control for a run in flight. The handler must also
    pass the pending turn to `rebuildHistory` (or it deletes a running question's only Stop), must not null
    `pendingTurn` (or `askQuestion`'s catch throws on a null and a failed run renders nothing at all), and
    must capture `notebookGeneration` like every other awaiting flow here (or a notebook switch during the
    DELETE wipes the NEW notebook's conversation).

72. **The web assets are served `Cache-Control: no-cache`, because a zero-build app has no other way to stop
    a browser running last week's JavaScript.** Starlette's `StaticFiles` sends `ETag` and `Last-Modified`
    and NO `Cache-Control`, leaving the browser on heuristic caching — free to reuse a stale copy without
    asking — and invariant 29's zero-build choice means the filenames carry no content hash either, so there
    is no cache-busting URL to fall back on. This rests on the MECHANISM, not on the bug report that
    prompted it (which turned out to be invariant 70's second steps pill).

    **`no-cache` is NOT `no-store`.** The copy stays in the cache and the ETag short-circuits the transfer,
    so an unchanged asset costs one conditional request and a 304 with no body. `no-store` would turn every
    navigation into a full re-download of a ~190KB script, which is why the test asserts the ETag and the
    304 as well as the header.

73. **RapidOCR's region coordinates decide reading order (`_ocr.reading_order`) — joining its regions in
    detection order interleaves the columns of a two-column scan.** RapidOCR reports a bounding quad per
    region and no layout, and emits regions roughly line-by-line ACROSS the full page, so
    `" ".join(text for _, text, _ in result)` produced prose that jumps between columns mid-sentence.
    Measured against the same pages' own text layer, over two real papers: a two-column paper scored
    **0.425 -> 0.756**, a single-column one 0.802 -> 0.792. **The text-layer path was never affected** —
    `pypdfium2` reads a LaTeX two-column paper in correct column order already, because the content stream
    is written a column at a time — so this is an OCR-path defect only, and only scanned/textless pages
    reach it (invariant 7).

    **Three rules, each degrading to the detector's own order rather than to a wrong one:**

    - **A page is left EXACTLY as detected unless it looks two-column** — above `_MAX_SPANNING_FRACTION`
      (0.15) of regions crossing the content's horizontal centre, nothing is touched. A two-column page
      crosses the centre only on what spans the measure (a banner heading, a caption, a centred page
      number); a single-column page crosses it on nearly every body line. Too low a value merely declines
      to improve a page, too high reorders one that was already right, so it is set on the SAFE side.
      **The threshold was calibrated on rendered digital PDFs and then checked against the population it
      actually serves** — only a page with NO text layer reaches OCR — and it transfers: a real
      two-column scan (Physical Review Letters, 1958) measured 0.01-0.05 per page, the same band as the
      clean renders, and every one of its 16 pages was reordered. Controlled skew of 0.25-2.0 degrees held
      it at 0.00-0.08, so the drift a scanner introduces does not reach the threshold.
    - **A centre-crossing region is a band BOUNDARY, never a veto.** The first draft distrusted any band
      holding a centre-crosser, and a real two-column page's single crossing region — the page number
      centred in its footer — cost the whole page its column order. Boundaries cut the page into bands and
      each band is column-split on its own.
    - **Within a band nothing is re-sorted; only the two columns are separated out of the detector's
      order.** Sorting a band by vertical position measured WORSE on BOTH layouts (two-column 0.756 ->
      0.743, single-column 0.774 -> 0.751): RapidOCR already emits a column's lines in reading order, and
      re-sorting on a quad's vertical centre only disturbs near-ties like a superscript or a skewed line.
      This is the half that is counter-intuitive and the half a later reader is most likely to "fix".

    **`_order_band` partitions rather than filtering twice**, because a zero-width region sitting exactly ON
    the centre satisfies both the left and the right test and would be emitted into both columns.

    **Tesseract is deliberately NOT given the same treatment**: it does its own page segmentation, columns
    included, and reports text already in reading order.

    **The known cost, inspected rather than inferred**: a wide TABLE on a single-column page can be split
    down the middle, and two attention-visualisation figure pages measured -0.08/-0.06. Both were read
    directly — a flattened table and a scatter of figure labels are word soup under either ordering, which
    is why that cost is accepted against a +0.331 gain on two-column prose.

    **THREE columns are out of scope and decline themselves.** A three-column scan (Scientific American
    Supplement, 1890) puts the middle column across the centre, so it crosses on nearly every line and the
    page is left alone — the same arithmetic that recognises a single-column page, not a case anyone had to
    special-case. Do not "extend" this to N columns without measuring: the guard is what makes an
    unsupported layout safe, and a generalisation that removes it trades a decline for a corruption.

    **A layout-detection MODEL was evaluated for this and rejected** (`PicoDet-S_layout_3cls`): its classes
    are table/image/stamp with no text class, so it cannot do the one thing that was actually broken. See
    `CHANGELOG.md` for the full evaluation, including which checkpoint would be the right one if this is
    ever revisited.

See `CHANGELOG.md` for the incidents, measurements and superseded drafts behind every invariant above.
