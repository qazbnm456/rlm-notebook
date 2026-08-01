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
- A LIVE run additionally needs real model credentials and a Deno sandbox (`brew install deno`).
  Don't run it in CI; it costs money.
- Before claiming done, actually run both commands and paste the output.

## Scope note

Two slices in: ingestion (text / web / PDF, with local hybrid OCR), citation-grounded chat, and
now a persistent multi-turn `Notebook` (sources + history surviving across `ask` invocations, one
JSON file, no database). There is still no subprocess-per-turn execution isolation, no Notebook
Guide (summary/FAQ/timeline), no Audio Overview, and no API/UI yet — `cli.py` drives one
`AnswerQuestion` run in-process, synchronously, per invocation. Each of those is its own follow-up
slice; do not assume any of them exist because an earlier design discussion mentioned them.

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
4. **The corpus blob uses `[[SRC:<id>|<locator>]]` markers, and `AnswerQuestion.instructions`
   teaches the model to treat them as opaque and echo them verbatim in `Citation`.** Without an
   explicit rule the model has no reason to preserve an ad hoc marker format across `.find()`/slice
   operations, and `citations.py` (invariant 5) has nothing to verify against if it doesn't. Do not
   drop or reword that instruction block when editing `task.py`. **Residual risk, not yet
   verified**: the offline test (`test_task.py`) drives a scripted LM whose turns are fixed dicts —
   it proves the tool-wiring/SUBMIT chain works, not that a real model reliably copies a marker
   verbatim out of a multi-MB string it must locate itself. Treat that as unverified until a live
   run confirms it, not as covered.
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
    removed since, must not be inherited into a new one.
12. **Extending an existing notebook with `--source` dedupes by origin, and never reassigns an
    existing source's id.** `notebook.existing_origins` + `cli._ingest_new`'s `skip_origins` make
    re-passing the same path/URL on a later turn a no-op rather than a duplicate; new sources are
    numbered starting from `len(notebook.sources) + 1`, so a source already cited in a saved
    `ChatTurn.answer` can never have its id silently repointed at different text on a later `ask`.

See `CHANGELOG.md` for what shipped in the current slice and why.
