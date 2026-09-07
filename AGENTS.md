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

- `uvx ruff@0.16.0 check .` — lint. **`line-length = 110` is now ENFORCED**: ruff's default rule
  set carries no `E501`, so for most of this project's life an over-long line passed `check` and
  the number was a convention kept by hand (about 20 had accumulated, and a name scrub once left a
  157-character line that only an independent review caught). `pyproject.toml` selects it
  explicitly — via **`extend-select`, never `select`**, because naming `select` REPLACES ruff's
  defaults and re-listing what you believe them to be is a guess: doing exactly that here pulled in
  `E402` and broke 20 lines in the suite, the deliberate `importorskip` that must run BEFORE the
  imports it guards. The version is pinned because an unpinned `uvx ruff check .` resolves the
  latest ruff at run time and can redden CI with nobody having touched a line of code.
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

**This is the INDEX. Each entry states the rule and the one thing that would stop you breaking it;
the argument, the evidence and the traps live in [`docs/invariants/`](docs/invariants/), one file
per invariant under the same number.**

**Read that invariant's file before overturning, narrowing or "simplifying" anything.** A rule
without its argument is easy to talk yourself out of just this once — the argument is what makes
these non-negotiable rather than preferences. If the repo contradicts either file, that is drift to
flag, not licence to pick a different design.

Three places, and each new thing belongs in exactly one:

| | goes to |
|---|---|
| The rule, and the sentence that stops you breaking it | this index |
| Why it holds, what it costs, what a later reader will try instead | `docs/invariants/<n>-<slug>.md` |
| Who found it, what was measured, which draft was wrong | `CHANGELOG.md` |

**This index does not grow.** An entry that has acquired a second paragraph has taken on something
belonging to one of the other two files — move it there rather than letting this section become the
thing the split was done to remove. (Measured on a sibling repo that made exactly this split: its
indexed section held steady at ~5,100 tokens while an un-indexed section beside it grew to ~55,600.)

1. **No fetch/network tool is ever registered on the chat task's `RLMTask(tools=…)`.** An instruction hidden
   in a source could otherwise steer the model into exfiltrating the notebook to a URL the SSRF guard cannot
   recognise as hostile.
   ([why](docs/invariants/01-no-network-tool-in-chat-repl.md))

2. **`parsers/web.py` re-validates the SSRF guard on EVERY redirect hop, not just the requested URL.** An
   initially-safe URL can 302 to a loopback or metadata address, and the default opener follows it
   unchecked.
   ([why](docs/invariants/02-ssrf-guard-revalidated-per-redirect.md))

3. **Ingestion is host-side only AND SERIAL — never inside the sandbox, never in a thread pool.** PDFium is
   not thread-safe — four PDFs ingested concurrently died with `rc=134`, and 614 tests stayed green because
   nothing drove two PDFs at once.
   ([why](docs/invariants/03-ingestion-is-host-side-and-serial.md))

4. **The corpus blob uses `[[SRC:<id>|<locator>]]` markers, and EVERY citation-grounded task's instructions
   teach the model to treat them as opaque and echo them verbatim in a `Citation`.** Without an explicit
   rule the model has no reason to preserve an ad hoc marker across `.find()`/slice operations, and
   `citations.py` has nothing to verify against.
   ([why](docs/invariants/04-citation-markers-are-opaque-coordinates.md))

5. **`citations.py` verifies coordinate existence only — never content faithfulness.** Never let a
   docstring, log line or UI string imply the stronger guarantee — that gap is the grounded-but-not-verified
   failure mode found in NotebookLM itself.
   ([why](docs/invariants/05-citations-verify-coordinates-not-faithfulness.md))

6. **`injection_scan.py`'s flags are deterministic and additive — they gate nothing.** It is a transparency
   mechanism; wiring it to refuse a run turns a deliberately imprecise regex into a gate.
   ([why](docs/invariants/06-injection-flags-are-advisory.md))

7. **OCR ships enabled by default, not merely pluggable-but-off.** `pypdfium2` replaced `pymupdf` over a
   real AGPL conflict, and `ocr_provider` has zero consumers despite being validated on read.
   ([why](docs/invariants/07-ocr-ships-enabled-by-default.md))

8. **`corpus.py` enforces a size cap on the assembled blob and fails loudly, not silently, past it.** The
   single-blob-as-REPL-variable design has a real memory ceiling; the cap is what stops a mysteriously slow
   chat turn later.
   ([why](docs/invariants/08-corpus-blob-size-cap-fails-loudly.md))

9. **`AnswerQuestion` always runs in the `pyodide` sandbox; `NotebookConfig.from_env` refuses any other
   `RN_INTERPRETER` value rather than silently overriding it.** An operator who set `RN_INTERPRETER=local`
   believes something about this run that a silent correction would make false.
   ([why](docs/invariants/09-answerquestion-always-runs-in-pyodide.md))

10. **A notebook id is sanitized (`notebook.slug`) before it becomes a filename, and an id the whitelist
    empties falls back to a content hash rather than being rejected.** An unsanitized id becomes a traversal
    segment, and the `nb-<sha256>` fallback is what lets a notebook named in Chinese exist at all.
    ([why](docs/invariants/10-notebook-ids-are-sanitized-filenames.md))

11. **`history` (prior conversation turns) is context only — it is never itself a source of facts or
    citations.** A past answer being wrong, or a source having been removed since, must not be inherited
    into a new one.
    ([why](docs/invariants/11-history-is-context-not-a-source.md))

12. **Extending an existing notebook with `--source` dedupes by origin, and never reassigns an existing
    source's id.** A source already cited in a saved turn can never have its id silently repointed at
    different text.
    ([why](docs/invariants/12-source-ids-are-never-reassigned.md))

13. **Every citation-grounded RLMTask shares its citation-marker and validate-before-submit instructions
    from `instructions.py` — not a hand-copied paragraph per task.** A wording fix to a shared piece must
    never land on one task's local copy — there should be no local copy.
    ([why](docs/invariants/13-grounded-tasks-share-one-instruction-set.md))

14. **TTS synthesis (`tts.py`) runs entirely host-side, on an already-generated, already-schema-validated
    `PodcastScript` — it is never a tool the model can call, and `GeneratePodcastScript` (`audio.py`) has no
    dependency on `tts.py` at all.** Same reasoning as 1 and 3: synthesis is a real network call, and the
    model's job is finished long before any audio exists.
    ([why](docs/invariants/14-tts-is-host-side-never-a-tool.md))

15. **The default TTS provider (`RN_TTS_PROVIDER=edge-tts`) needs no API key or paid account, so `rlm-
    notebook audio` works out of the box** Ship a working default, not just a pluggable interface — and keep
    the provider list in ONE place, because a second list drifts.
    ([why](docs/invariants/15-default-tts-provider-needs-no-key.md))

16. **`PodcastScript.utterances` may legitimately be empty, and `cli._cmd_audio` says so explicitly rather
    than printing nothing** "Silently prints nothing" was a real bug in `Timeline.events` and `FAQ.items`
    before it could be one here.
    ([why](docs/invariants/16-an-empty-podcast-script-says-so.md))

17. **`EdgeTTSProvider` synthesizes one utterance at a time (one voice per `edge-tts` call) and concatenates
    the raw MP3 byte streams — it does not re-encode.** A deliberate trade to avoid an `ffmpeg`/`pydub`
    dependency for what is only a gapless-playback cosmetic gain.
    ([why](docs/invariants/17-edge-tts-concatenates-without-reencoding.md))

18. **The Audio Overview's cast is a fixed two hosts, `host_a`/`host_b` (`schema.Speaker`), not freely-named
    per episode.** Keeps `Utterance.speaker` a closed enum citations and voice-mapping can rely on;
    `config.tts_voice_map` hardcodes both keys with no tripwire.
    ([why](docs/invariants/18-the-podcast-cast-is-two-fixed-hosts.md))

19. **`cli._cmd_audio` resolves the TTS provider before running the (potentially expensive) script-
    generation model call, not after.** The original ordering wasted a real model call whenever
    `RN_TTS_PROVIDER` was misconfigured.
    ([why](docs/invariants/19-resolve-the-tts-provider-before-the-model-call.md))

20. **`ingest.py`/`notebook.py` (`is_url`/`ingest_one`/`ingest_new`, `load_or_create`,
    `ingest_sources_for`/`append_sources`, `mutate_notebook`) are shared by `cli.py` AND `api.py` — neither
    entry point depends on the other.** Extracted once both entry points needed it, so a fix to source-
    handling cannot land on only one of them.
    ([why](docs/invariants/20-shared-ingestion-module-for-both-entry-points.md))

21. **Every API request that runs an `RLMTask` does so in an isolated subprocess (`runner.py`/`worker.py`),
    never in-process.** `worker.py` is the only place an `RLMTask` is ever RUN, so a crash takes down a
    subprocess and never the server. The guarantee is about EXECUTION, not imports.
    ([why](docs/invariants/21-api-runs-every-task-in-a-subprocess.md))

22. **Cancellation works via `killpg` on the WHOLE process group (`start_new_session=True` when spawning),
    not just the worker's own PID.** A stuck Deno grandchild must not survive as an orphan — pinned by a
    test that spawns a real grandchild and confirms it dies.
    ([why](docs/invariants/22-cancellation-kills-the-process-group.md))

23. **`api._ACTIVE_RUNS` is a single-process, in-memory map with ONE SLOT PER NOTEBOOK ID — two documented
    limitations, neither a silent bug.** Two documented limitations, neither a silent bug: no multi-worker
    story, and one slot per notebook id.
    ([why](docs/invariants/23-active-runs-is-one-slot-per-notebook.md))

24. **Every `SystemExit` a request handler can reach is converted to an HTTP 500, rather than letting it
    escape.** An unhandled `SystemExit` inside a request handler is a crash, not an error response. The RULE
    is the invariant, NOT the current list of places it applies.
    ([why](docs/invariants/24-systemexit-never-escapes-a-handler.md))

25. **This API has NO authentication or authorization of any kind.** Any caller can rename or irreversibly
    delete from any notebook, and `GET /notebooks` makes every id enumerable without knowing it.
    ([why](docs/invariants/25-the-api-has-no-authentication.md))

26. **`add_sources` accepts ONLY http(s) URLs, never a local file path — unlike `cli.py`'s `--source`.** The
    full attack was reproduced end to end — `POST {"sources": ["/etc/passwd"]}` read the file and echoed it
    back through a citation that passed verification.
    ([why](docs/invariants/26-add-sources-refuses-local-paths.md))

27. **Every endpoint that resolves a notebook by id catches BOTH `pydantic.ValidationError` (a corrupted
    notebook file → 409) AND `ValueError` (an id `notebook.slug` reduces to an empty token → 400) — not just
    the first.** Without both arms an unhandled `ValueError` escapes as a raw 500.
    ([why](docs/invariants/27-notebook-lookup-catches-both-error-types.md))

28. **`cli._GUIDE_TASKS` and `api._GUIDE_TASKS` are two independent registries, kept in sync by the tripwire
    `test_api.py::test_guide_task_registries_stay_in_sync_between_cli_and_api`, a tripwire test, not by
    sharing code** Two registries kept in sync by a tripwire rather than by sharing code, because invariant
    20 explains why `api.py` does not import `cli.py`.
    ([why](docs/invariants/28-guide-registries-kept-in-sync-by-tripwire.md))

29. **The web UI (`rlm_notebook/web/`) is a real end-user product surface, not a replay-only trace console
    like the sibling projects' `studio/`s.** Rests on five rules for the live trace stream and the
    never-`innerHTML` rule; assets live under `rlm_notebook/web/` or they vanish from the wheel.
    ([why](docs/invariants/29-the-web-ui-is-a-product-surface.md))

30. **`POST /notebooks/{id}/sources/upload` and `add_sources`'s `texts` field never reopen invariant 26's
    local-path ban.** The size cap must be checked BEFORE FastAPI parses the body, and `max_upload_bytes()`
    is deliberately not a `NotebookConfig` field.
    ([why](docs/invariants/30-upload-and-paste-do-not-reopen-the-path-ban.md))

31. **`GET /notebooks/{id}/sources/{source_id}` returns a source's FULL text — a materially different
    exposure than every other endpoint except the trace pair (invariant 29).** Before it, no caller could
    read more of a source than a citation's short `quote`.
    ([why](docs/invariants/31-the-source-text-endpoint-is-a-new-exposure.md))

32. **Notes (`schema.Note`, `Notebook.notes`) are freeform, uncited text — grounded and citable only once
    PROMOTED into a real `Source`, never before.** A note carries no citations and is never re-verified; ids
    come from the MAX live id, because length-based ids let two live notes share one.
    ([why](docs/invariants/32-notes-are-uncited-until-promoted.md))

33. **YouTube source ingestion (`parsers/youtube.py`) fetches CAPTIONS ONLY — never the video or audio
    stream.** A captionless video is a loud ingestion-time error, and `CaptionError` subclasses `ValueError`
    so both call sites already catch it.
    ([why](docs/invariants/33-youtube-ingestion-is-captions-only.md))

34. **Every write to a notebook goes through `notebook.mutate_notebook`, which re-loads the file from disk
    INSIDE a per-notebook lock and applies a caller-supplied DELTA — never a snapshot the caller read
    earlier.** A stale snapshot and interleaved critical sections are two distinct faults — a lock alone
    would not have helped.
    ([why](docs/invariants/34-every-write-goes-through-mutate-notebook.md))

35. **A model string prefixed `claude-agent-sdk/` routes that role onto the user's Claude Pro/Max
    SUBSCRIPTION, and it works ONLY because `config.setup` injects the LM — `rlm_harness.configure` does not
    route on the prefix itself.** `rlm_harness.configure` does not route on the prefix; it works only
    because `config.setup` injects the LM.
    ([why](docs/invariants/35-the-subscription-path-needs-an-injected-lm.md))

36. **`rlm_notebook/web/`'s `hidden`-toggled elements must never be given an author `display` rule without a
    matching `[hidden]` rule, and `tests/test_web_assets.py` fails the build if one is.** Shipped broken
    twice. An author `display` beats the UA `[hidden]` rule regardless of specificity, and no other layer
    here can test it.
    ([why](docs/invariants/36-hidden-toggles-need-a-matching-hidden-rule.md))

37. **A notebook's `id` is a HANDLE; `schema.Notebook.title` is the label a person reads. The UI mints the
    id itself and never asks for one.** Requiring a name before the first source made the first interaction
    a naming puzzle. Titling is LAZY and never overwrites.
    ([why](docs/invariants/37-the-notebook-id-is-a-handle-not-a-label.md))

38. **The chat overview is the ONE guide artifact persisted onto a notebook (`schema.Overview`,
    `Notebook.overview`), and it is marked STALE rather than deleted when the sources change.** Three
    states, not two — "never generated" and "generated but the sources moved" used to render identically.
    ([why](docs/invariants/38-the-overview-is-persisted-and-marked-stale.md))

39. **Model-authored prose follows the READER's language, not the documents'. Citation coordinates never
    follow anything — and naming a language buys neither its SCRIPT nor its IDIOM.** A model told to write
    in Chinese that helpfully localises `page:1` to `第1頁` turns every citation unverified.
    ([why](docs/invariants/39-prose-follows-the-reader-coordinates-follow-nothing.md))

40. **`tts.default_voices_for` maps a language to a voice, which is what let the podcast join invariant 39's
    language story.** A correct Chinese script read by the en-US default cast is a routing bug, not a
    synthesis one.
    ([why](docs/invariants/40-language-decides-the-podcast-voice.md))

41. **The settings page exposes PRESENTATION settings only, and "non-secret" was the wrong filter.** Moving
    a safety BOUND onto an unauthenticated page is the same mistake as moving a key there, just quieter.
    ([why](docs/invariants/41-settings-expose-presentation-only.md))

42. **A generated Audio Overview from the API is PERSISTED — one file per notebook, served as a real file.**
    One file per notebook is what makes retention a non-question, unlike `traces/`.
    ([why](docs/invariants/42-the-generated-episode-is-persisted.md))

43. **A `TTSProvider` owns its OUTPUT FORMAT, its own cast, and — since it may be cross-lingual — is handed
    the LANGUAGE as a separate input. None of the three is the caller's.** A shared voice map would leak one
    provider's names into the other's request; chatterbox is 33x the wall clock and is deliberately not the
    default.
    ([why](docs/invariants/43-a-tts-provider-owns-its-format-and-cast.md))

44. **The podcast transcript behaves like subtitles, and the timing comes from the PROVIDER rather than from
    measuring the audio.** A provider reporting no boundaries yields a list as long as `utterances` with
    every line stamped `0:00`, so the consumer's guard is MONOTONICITY.
    ([why](docs/invariants/44-the-transcript-is-subtitles-timed-by-the-provider.md))

45. **The podcast script has a stated SHAPE, and is written to be SPOKEN in one language.** Asking only for
    "a natural conversation" gave episodes no opening, no plan and no close. There is exactly ONE close and
    it is written LAST.
    ([why](docs/invariants/45-the-podcast-script-has-a-stated-shape.md))

46. **Every run-taking handler ANNOUNCES its run id (`api._announced`) before any pre-work, not just before
    the spawn.** `_resolve_language` always runs on a new notebook and always outlasts the 5s grace, so the
    client reports a run missing while the request succeeds.
    ([why](docs/invariants/46-run-ids-are-announced-before-any-pre-work.md))

47. **Every long-running action shows that it is running and offers a way to STOP it, and no action starts
    without an explicit press.** Stop cancels by RUN ID, because `/overview` fires two runs and
    `_ACTIVE_RUNS` holds one slot per notebook.
    ([why](docs/invariants/47-every-long-run-is-visible-and-stoppable.md))

48. **The INTERFACE language (`web/i18n.js`) is a browser preference, deliberately separate from the OUTPUT
    language (invariant 39, a server setting).** A reader in Taiwan may want a Chinese interface over
    English papers, and folding the two together makes that combination unexpressible.
    ([why](docs/invariants/48-interface-language-is-separate-from-output.md))

48.5. **The model must not number its own citations.** The interface numbers them itself, so a `[1]` written
      into the sentence is a second, competing scheme by construction.
      ([why](docs/invariants/48.5-the-model-must-not-number-its-citations.md))

49. **`Citation.answer_span` is the model pointing at its OWN prose, and it exists because locating the
    highlight by `quote` stopped being possible.** Invariant 39 made prose follow the reader while the quote
    stays in the source's words, so `answer.indexOf(quote)` could no longer find anything.
    ([why](docs/invariants/49-answer-span-is-the-model-pointing-at-itself.md))

50. **A source can be REMOVED now, which ended append-only id numbering — and the survivors are never
    renumbered.** `len(sources) + 1` was correct only while sources were append-only; the moment removal
    existed it produced two live sources under one id.
    ([why](docs/invariants/50-removal-ended-append-only-source-ids.md))

51. **`Source.preview` is display-only page metadata, scraped from html already in hand, and it NEVER
    references an image.** Rendering `og:image` makes the READER's browser fetch a URL the page author chose
    — every pasted link becomes a beacon.
    ([why](docs/invariants/51-source-preview-never-references-an-image.md))

52. **The live ticker's event shape is `{kind, primary, detail, meta}` and it carries the model's own words
    — but never the step's OUTPUT.** The branch emitted the fixed word `Tool` with the payload discarded,
    and nobody read it because this project emitted no `tool_call` events at all.
    ([why](docs/invariants/52-the-ticker-carries-words-never-the-output.md))

53. **Renaming is a separate VERB from generating a title, and a rename REFUSES rather than derives.**
    Setting a title is an instant write; generating one is a model call that can fail — folding them gives
    rename the failure semantics of a model call.
    ([why](docs/invariants/53-renaming-and-generating-a-title-are-separate.md))

54. **Two more web-UI hazards that ONLY a source-tree assertion can catch, both extending invariant 36's
    reasoning to properties nothing else in this project can see.** A tooltip host that clips its own
    tooltip erases it outright, and an inverted drag-threshold pair makes every `pointermove` flip the
    state.
    ([why](docs/invariants/54-two-web-hazards-only-a-source-assertion-catches.md))

55. **Markdown in an answer is rendered by a HAND-WRITTEN renderer that builds DOM nodes, and a link in it
    is shown but NOT navigable.** One missed `esc()` in a string-building renderer is an XSS sink, and a
    clickable link is invariant 1's hazard with the READER's click as the transport.
    ([why](docs/invariants/55-markdown-builds-nodes-and-links-are-inert.md))

56. **`Answer.follow_ups` comes from the SAME run that produced the answer — never a second model call — and
    is not verified against anything.** The model already holds the corpus and its own answer, so asking in
    the same SUBMIT costs nothing a second call would.
    ([why](docs/invariants/56-follow-ups-come-from-the-same-run.md))

57. **The chat overview is the THREAD's first entry, inside the scroller — not a panel pinned above it.** As
    a sibling of `.chat-history` it permanently owned up to half the chat column.
    ([why](docs/invariants/57-the-overview-is-the-threads-first-entry.md))

58. **A reference is a compact ROW that opens, and pointing at either end of a citation lights up the
    other.** Rendering every quote as a `blockquote` let one source cited eight times fill the column;
    `referenceKey`'s separator is `\u001f` because `CSS.escape` maps U+0000 to U+FFFD.
    ([why](docs/invariants/58-a-reference-is-a-row-that-opens.md))

59. **The four budget defaults are each a decision, and `max_tokens` is the one that silently kills a run.**
    `max_tokens` is billed against a cap the reasoning never appears in, so the reply arrives cut mid-JSON.
    Raised against a DISTRIBUTION, never one truncation.
    ([why](docs/invariants/59-the-four-budget-defaults.md))

60. **A status line may not claim something the page is not doing, and a repaint may not delete a run.**
    `setPhase` names a stage the trace cannot see, and `chat:rerender` rebuilding from `state.turns` alone
    deletes a running question.
    ([why](docs/invariants/60-a-status-line-may-not-lie.md))

61. **The cheap `dspy.Predict` callers read `Corpus.excerpt`, never `blob()[:n]` — a prefix is source ONE,
    not the notebook.** The blob concatenates sources IN ORDER, so a 69,859-character first source made
    sources two through four invisible.
    ([why](docs/invariants/61-cheap-predict-callers-read-an-excerpt.md))

62. **A `[[SRC:...]]` marker is a coordinate for the interface and must never reach the reader — stripped at
    the DISPLAY boundary, not before persisting.** Stripped on the way OUT, so nothing stored is rewritten
    and every notebook already on disk is fixed with no migration.
    ([why](docs/invariants/62-markers-are-stripped-at-the-display-boundary.md))

63. **The podcast has a LENGTH, chosen at generation time, and the tiers are numbers rather than
    adjectives.** "Aim for a natural episode length" demonstrably did nothing — four measured episodes all
    landed near three minutes.
    ([why](docs/invariants/63-the-podcast-has-a-chosen-length.md))

64. **A `long` script is built across REPL turns, and that is what the sandbox is FOR.** Written as one code
    block it was truncated mid-structure and the run failed; accumulated across turns the same cap produced
    80 utterances.
    ([why](docs/invariants/64-long-scripts-are-built-across-turns.md))

65. **Every RLM task here carries `rlm_harness.skills` with `discovery="inject"`, and the prompt/skill split
    is a rule rather than a preference.** Anything that CORRUPTS the output when skipped stays in the
    PROMPT, because a skill is read only if the model chooses to.
    ([why](docs/invariants/65-the-prompt-skill-split.md))

66. **The pre-SUBMIT validator is `instructions.make_grounded_validator` for EVERY task — schema plus "no
    `[[SRC:...]]` marker in the model's own prose" — and SUBMIT belongs on a LATER REPL TURN than the call
    that validated.** A run printed the verdict beside its SUBMIT and shipped the character it had just been
    told about.
    ([why](docs/invariants/66-the-pre-submit-validator.md))

67. **The pre-SUBMIT validator checks each citation's COORDINATE against the corpus this run was given, and
    the six tasks share ONE base class instead of six identical `__init__`s.** A model wrote the SECTION
    HEADING it was citing into `locator`, turning every citation in an overview unverified.
    ([why](docs/invariants/67-the-validator-checks-citation-coordinates.md))

68. **A wall-clock backstop scales with the work that was asked for (`schema.PODCAST_TIMEOUT_FACTOR`).** A
    `long` tier asking for 60-90 accumulated utterances could not fit under the 300s default it shipped
    with.
    ([why](docs/invariants/68-the-timeout-scales-with-the-tier.md))

69. **The INTERFACE language is a SIGNAL to output-language resolution — a fourth one, ranked above `Accept-
    Language` — which narrows invariant 48 without merging it.** The one place a reader had actually SAID
    which language they read was invisible to `naming.SuggestLanguage`.
    ([why](docs/invariants/69-interface-language-signals-output-language.md))

70. **The Trajectory drawer (`trajectory.py` + `GET .../runs/{run_id}/trajectory`) is where a run's
    reasoning lives — NOT the chat bubble.** The inline step log put the planner's prose inside the answer —
    and the validator recorded no calls, so the timeline was empty on every run.
    ([why](docs/invariants/70-the-trajectory-drawer.md))

71. **A repaint may not delete a RUN — and `#chat-overview` is owned by its generation while one is in
    flight (`overviewRunning`).** `renderChatOverview` clears the element holding the run's only Stop, and
    several callers invoke it for reasons unrelated to the run.
    ([why](docs/invariants/71-a-repaint-may-not-delete-a-run.md))

72. **The web assets are served `Cache-Control: no-cache`, because a zero-build app has no other way to stop
    a browser running last week's JavaScript.** `StaticFiles` sends no `Cache-Control`, and a zero-build app
    has no content hash in the filename to bust with.
    ([why](docs/invariants/72-web-assets-are-served-no-cache.md))

73. **RapidOCR's region coordinates decide reading order (`_ocr.reading_order`) — joining its regions in
    detection order interleaves the columns of a two-column scan.** RapidOCR emits regions line-by-line
    ACROSS the page, so joining in detection order jumps between columns mid-sentence.
    ([why](docs/invariants/73-ocr-reading-order-for-two-column-scans.md))

74. **A garbled text layer is decided by COMPARING against OCR, never by a threshold alone
    (`pdf._page_text`, `_ocr.wordlike_ratio`).** No threshold separates good pages from mis-decoded ones, so
    the score only decides whether to SPEND an OCR pass; the comparison decides what to keep.
    ([why](docs/invariants/74-a-garbled-text-layer-is-decided-by-comparison.md))

75. **A trace's token budget has THREE readings, and the third is the one that matters
    (`trajectory.budget_summary`, the Trajectory drawer's budget note).** Reading an absent field as
    "nothing was truncated" turns a corpus boundary into a property of the code.
    ([why](docs/invariants/75-three-readings-of-a-token-budget.md))

76. **The SSRF guard's DNS half is handed an operator-supplied carve-out (`RN_FETCH_ALLOW_CIDRS`),
    resolved in ONE place (`web.allow_nets`) that both host-side fetchers read.** A fake-IP resolver
    answers every public hostname with a RESERVED address, so full strictness refuses every
    ingestion on that machine — the guard is not wrong, it just cannot see that the operator's own
    resolver is lying to it.
    ([why](docs/invariants/76-the-ssrf-carve-out-for-fake-ip-resolvers.md))

