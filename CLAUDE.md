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

This is an early, single-slice build: ingestion (text / web / PDF, with local hybrid OCR) plus
citation-grounded chat. There is no multi-turn session persistence, no subprocess-per-turn
execution isolation, no Notebook Guide (summary/FAQ/timeline), no Audio Overview, and no
API/UI yet — `cli.py` drives one `AnswerQuestion` run in-process, synchronously. Each of those is
its own follow-up slice; do not assume any of them exist because an earlier design discussion
mentioned them.

## Invariants — do not break

1. **No fetch/network tool is ever registered on the chat task's `RLMTask(tools=…)`.**
   `parsers/web.py`'s fetcher is called exactly once, host-side, during ingestion — never handed to
   the model at question-answering time. A source's own content is untrusted (see invariant 5); if a
   fetch tool were reachable from the REPL, an instruction hidden in that content could steer the
   model into exfiltrating notebook contents to an attacker-controlled URL, and `rlm_kit`'s SSRF
   guard (`is_safe_url`) only blocks internal/loopback/metadata targets — it does not, and cannot,
   block a legitimate-looking external domain. If a later slice wants "fetch one more page on
   request," that is a separate, explicitly user-confirmed, non-agentic action — not a tool the
   model decides to call.
2. **Ingestion is host-side only, never inside the sandbox.** `parsers/{text,web,pdf}.py` run
   before any `RLMTask` exists. `pymupdf4llm`, `trafilatura`, and the OCR backends (invariant 6) are
   native/C-extension dependencies unsuited to the pyodide/deno sandbox rlm-kit builds by default —
   and untrusted parsing logic has no reason to run inside the same trust boundary as the model's
   own code anyway. `corpus.py` only ever hands the RLM a plain string, already parsed.
3. **The corpus blob uses `[[SRC:<id>|<locator>]]` markers, and `AnswerQuestion.instructions`
   teaches the model to treat them as opaque and echo them verbatim in `Citation`.** Without an
   explicit rule the model has no reason to preserve an ad hoc marker format across `.find()`/slice
   operations, and `citations.py` (invariant 4) has nothing to verify against if it doesn't. Do not
   drop or reword that instruction block when editing `task.py`.
4. **`citations.py` verifies coordinate existence only — never content faithfulness.** It confirms
   a claimed `source_id` exists and its `locator` resolves to real text in the corpus; it does NOT,
   and cannot cheaply, confirm the model's surrounding prose faithfully represents that text. Never
   let a docstring, log message, or UI copy imply a stronger guarantee than this — that gap is
   exactly the "grounded-but-not-verified" failure mode academic evaluations have found in
   NotebookLM itself (see the design discussion this was born from). A citation that fails
   coordinate verification is marked unverified, never silently dropped, never silently trusted.
5. **`injection_scan.py`'s flags are deterministic and additive — they gate nothing.** A flagged
   source's content still reaches the model and its answer still returns; the flag is metadata
   surfaced alongside the answer, unioned with (never overridden by) whatever the model itself
   concluded. This is a transparency mechanism, not a blocking one — do not wire it to refuse a
   run.
6. **OCR ships enabled by default, not merely pluggable-but-off.** `parsers/pdf.py` uses
   `pymupdf4llm`'s built-in hybrid OCR (RapidOCR primary, Tesseract fallback — both Apache-2.0, both
   CPU-only) for scanned/image PDF pages, and the `ocr` extra installs the actual backend, not just
   an interface. A sibling open-source project (`lfnovo/open-notebook`, issue #819) shipped OCR as
   pluggable-but-not-installed-by-default and image sources silently failed to parse in its Docker
   image — don't repeat that. A `vision_llm` OCR mode (reusing the already-configured multimodal
   `dspy.LM` for hard/handwritten pages) is a deferred follow-up, not yet implemented.
7. **`corpus.py` enforces a size cap on the assembled blob and fails loudly, not silently, past
   it.** The single-blob-as-REPL-variable design (rlm-kit's core mechanic) has a real memory
   ceiling in the pyodide/deno sandbox; a notebook that exceeds the cap must get a clear error at
   ingestion time, not a mysteriously failing/slow chat turn later.

See `CHANGELOG.md` for what shipped in the current slice and why.
