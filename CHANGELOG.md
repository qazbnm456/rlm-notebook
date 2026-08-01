# Changelog

All notable changes to `rlm-notebook` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`rlm-notebook` is an RLM-driven research notebook, built on
[`rlm-kit`](https://github.com/qazbnm456/rlm-kit): paste in sources of any kind, ask grounded
questions with verifiable citations, and get a distilled research artifact out.

## [Unreleased]

- **First slice: ingestion (text/web/PDF with local hybrid OCR) + citation-grounded chat, driven
  from a CLI.** No session persistence, no API/UI, no Notebook Guide, no Audio Overview yet — see
  CLAUDE.md's Scope note. Everything below is what this slice actually contains, and the design
  calls that shaped it.

  **All sources become one blob, not a vector index.** `corpus.py` concatenates every ingested
  source into a single string tagged with `[[SRC:<id>|<locator>]]` markers and hands the whole thing
  to `AnswerQuestion` as one signature field — the model explores it in the sandboxed REPL
  (`.find()`/slicing) rather than through embedding similarity search. This is rlm-kit's native
  mechanic (an RLM signature field *is* a REPL variable), not a new indexing layer; a vector-search
  fallback for corpora too large for one blob is deferred until real usage shows the size cap
  (invariant 8) actually binds.

  **No fetch/network tool is reachable at question-answering time.** Early designs considered
  reusing `rlm_kit.tools.fetch.make_fetch_tool` as a live tool so the model could pull in more
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
  via `rlm_kit.tools.validation.make_schema_validator` — chosen over a post-hoc whole-run retry
  because rlm-kit's own retry policy defaults to `max_retries=1` specifically because a full RLM
  re-run rarely fixes a persistent (rather than transient) coercion failure. Not yet verified
  against a real model, only an offline scripted one — see invariant 4's residual-risk note.

  **`injection_scan.py` flags, never blocks.** A deterministic heuristic scan runs at ingestion
  time; a flagged source's content still reaches the model and its answer still returns, with the
  flag surfaced as metadata alongside it (invariant 6) — this is a transparency mechanism, not a
  gate, matching the reward-free/judgement-only posture this whole family of rlm-kit consumers
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
