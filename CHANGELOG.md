# Changelog

All notable changes to `rlm-notebook` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`rlm-notebook` is an RLM-driven research notebook, built on
[`rlm-harness`](https://github.com/qazbnm456/rlm-harness): paste in sources of any kind, ask grounded
questions with verifiable citations, and get a distilled research artifact out.

## [Unreleased]

- **The script check measured live: zero flaggable characters, `P(X=0) = 0.001` against the run it
  is the only difference from.** A third episode off `nb-d22c2a9a`, same models, same `long` tier,
  same Traditional Chinese, 346s.

  | | utterances | chars | characters the check would flag |
  |---|---|---|---|
  | rule inert (`scripttest2`) | 80 | 5699 | 13 |
  | rule shipping, no check | 77 | 4013 | 6 |
  | **rule + check** | 66 | 4617 | **0** |

  Against the middle run — whose only difference is the check itself — the null expectation is 6.9
  and zero were observed: Poisson `P(X=0) = 0.001`. Against the inert baseline, 10.5 expected,
  `P = 0.00003`. That is the first significant number this line of work has produced; the two
  earlier drift comparisons were `P = 0.23` and `P = 0.31` and were recorded as not significant.

  **What it does NOT establish, stated because the whole area has a history of over-reading:**

  - The CLI writes no trace, so whether the validator FIRED is unobservable. The draft may have
    been clean on the first attempt. This measures the configuration, not the tool being exercised.
  - One episode per arm. The Poisson test treats the rate as a property of the configuration.
  - Two changes are conflated against the baseline (rule + check); only the middle comparison
    isolates the check.

  **The accepted 3% recall loss appeared, once**: `厘清` survived and should be `釐清`, because
  `厘` is valid Big5 (`公厘`) and therefore outside the gate by design. The only other `zhconv`
  hit, `制` in `問責制`, is `zhconv` being wrong rather than the gate being loose — `制度` is
  correct Traditional, and flagging it would have been exactly the false positive the gate exists
  to prevent.

- **Confirmed with a sibling project how it keeps its output Traditional, by reading and RUNNING its
  code rather than taking an answer.** Its stability comes from solving this in a different place:
  HOST-SIDE and POST-HOC, split BY FIELD — a majority comparison on page bodies (advisory,
  tolerant), per-character strictness on page TITLES only, and a converter that rewrites a title
  and persists it. A prompt rule that turns out to be inert therefore costs that project nothing,
  where this project had only the prompt. Its field split is better reasoning than a global
  strictness dial and is recorded in invariant 66.

  **Its membership test does not transfer, and its own shipped functions demonstrate why.** Run
  against correct Traditional prose, `strict_script_offenders` reports `干` in `干預`, `里` in
  `里程碑` and `群` in `一群`, and `to_script` would persist `幹預`, `裏程碑` and `一羣` into a
  title; `台` is safe only because `_KEEP_AS_WRITTEN` hand-lists it, while the docstring claims no
  such list is needed. Reported to that project with the reproduction and the Big5 alternative —
  their user's call, not ours.

- **A pre-SUBMIT script check now catches Simplified characters in Traditional output, and it is
  the only check here that is allowed to be wrong.** Invariant 39 had declined a validator; two of
  its conditions moved — the drift is real and three times larger than published (19 sites), and
  the correct output is demonstrably knowable BY THE MODEL, which is what separates a
  reject-and-look-again check from a converter.

  **The membership test is Big5-encodability, and that is the finding that made it possible.**
  `zhconv`'s own `SIMPONLY` set was tried first and is unusable: it contains `干`, `台`, `群` and
  `里`, which are ordinary Traditional characters this project's real notebooks use correctly. Big5
  answers "does this glyph exist in the Traditional inventory at all" — `干` is in it, `对` is not.
  `zhconv` is still the dependency, for the SUGGESTION (`对 -> 對`) and to bound the set to known
  Simplified forms.

  **Three properties, each a deliberate loss:**

  | property | choice | cost |
  |---|---|---|
  | precision | absolute — no correct Traditional character may be flagged | `么` passes, because it is valid Big5 |
  | blocking | fires AT MOST ONCE per run | a determined model can submit drifted prose |
  | scope | `quote` exempt | a Simplified character inside a quotation is never caught |

  **The one-shot bound is the design, not an optimisation.** Every other check in
  `make_grounded_validator` rejects something WRONG; a Simplified character is COSMETIC, and the
  detector cannot distinguish one from a Japanese glyph being quoted inline — `学`, `会`, `国` and
  `峡` are shinjitai and this project's own corpora carry Japanese. A blocking check the model
  cannot satisfy spends the step budget looping and loses a paid-for episode over one glyph, which
  is the trade invariant 66 already refuses for `tts.spoken_script`.

  **Replayed against real measured output**: 17 offenders on the episode that motivated this, 6 on
  the one after it, every one a genuine drift; 0 on the notebook whose only drift was `么`. Zero
  false positives across 119 utterances produced against a corpus containing Japanese.

  Six mutations run against the new tests, all killed: removing the check, dropping the `quote`
  exemption, removing the one-shot bound, using the raw `zhconv` table without the Big5 gate,
  dropping the `arun` capture, and unwiring it from `GroundedTask`. `validate_before_submit_rule`
  now says four things rather than three, because a prompt describing three checks while four run
  is the drift invariant 13 exists to prevent.

- **"The model cannot write `峽`" was falsified for about 600 tokens.** The live episode left one
  character of `霍爾木茲海峡` unconverted, and the obvious reading was a vocabulary limit no prompt
  could reach. Asked directly, the same configured LM returns `霍爾木茲海峽` — all six characters
  — and `峽` alone on request.

  So the residual Simplified drift is a COMPLIANCE problem rather than a knowledge one: the model
  holds the right answer and does not apply it across 4000 characters of dialogue. `CLAUDE.md`'s
  sentence excusing it as a capability limit is removed.

  **This reopens the validator question with one of its conditions now met.** Invariant 39 declined
  a validator because "every condition justifying one is absent, and the one field that would
  qualify does not drift". Two of those have moved: the drift is real and larger than published
  (19 sites, all in podcast fields), and the correct output is demonstrably knowable BY THE MODEL,
  which is what makes a reject-and-retry check different from a converter. A `zhconv` CONVERTER
  remains wrong for the reason already recorded — it rewrites `干`, `台`, `群`, `里`, which are
  correct Traditional — so any such check would have to report offenders and let the model judge
  context, not rewrite prose. Not built; recorded as a live option rather than a closed one.

  Method note for the next person: the first attempt at this check hand-rolled a `dspy.LM(...)`
  from `RN_MAIN_MODEL` and died on a missing provider prefix, because `config.setup` is the ONE
  place either entry point configures a model (invariant 35). Use it.

- **The Hormuz proper-noun story was false, and it had been used to justify two changes and to
  discount twelve drift hits.** `霍尔木兹海峡` in a Traditional podcast was recorded as the model
  faithfully keeping a Simplified source's own spelling. **Neither notebook's corpus contains a
  single Chinese character.** `nb-d22c2a9a`'s sources say `the Strait of Hormuz` in English, 22
  times, with Japanese prose around it; `nb-6f2d49d3`'s hold no CJK at all. The model rendered the
  name into Chinese from its own priors, and Simplified is what those priors produce.

  Three things fall out, in the order they were wrong:

  | claim | as recorded | corrected |
  |---|---|---|
  | drift across both notebooks | `么 对 点 问 题`, 5 chars, 5 sites | `尔 兹 峡 么 对 点 问 题`, **8 chars, 19 sites** |
  | the live A/B | 4 / 5699 -> 1 / 4013, `P<=1`=0.23 | **13 / 5699 -> 7 / 4013**, `P(X<=7)`=0.31 |
  | the half-converted name | a REGRESSION the rule caused | an **improvement**: 3 of 6 wrong characters -> 1 of 6 |

  **The exclusion was never checked against the corpus, only against a plausible story** — that a
  name appearing in a foreign script must have been copied from somewhere. It was applied while
  correcting a different bad exclusion in the same measurement, which is what made it feel
  rigorous. Still not significant either way: one run, `P = 0.31`.

  **`51d2dac` is reverted in full.** It added a sentence forbidding a PARTIAL proper-noun
  conversion, with `霍尔木兹海峡` as "a name the sources spell" — a factually false statement about
  this project's own data, shipping in all six prompts. The failure it described is not a
  carve-out failure at all: the model rendered the name itself and left one character unconverted,
  which is ordinary drift, and the script rule already says `throughout`. The clause may still be
  right in general and there is no evidence for it, so it does not ship.

  **The proper-noun precedence clause stays**, but on the sibling's measured Simplified-source
  case and the general argument, NOT on an observation here — `CLAUDE.md` now says so.

- **The script rule was measured live, and the run bought a REGRESSION rather than a
  confirmation.** A/B on one notebook (`nb-d22c2a9a`): same four sources, same
  `qwen36_35b_a3b`/`gpt-5.6-luna` pair, same Traditional Chinese, same `long` tier, 258s — only
  the prompt differed. Run through the CLI `audio` path, which persists nothing (invariant 42), so
  the stored episode the baseline came from was never overwritten and the comparison is against
  the real recorded artifact rather than a re-derivation.

  | | baseline (`scripttest2`, rule inert) | new (`SCRIPT_PINNED` shipping) |
  |---|---|---|
  | utterances / chars | 80 / 5699 | 77 / 4013 |
  | Simplified drift sites | 4 (1 per 1424 chars) | 1 (1 per 4013) |
  | the place name, ×n | `霍尔木兹海峡` ×3 | **`霍爾木茲海峡` ×6** |

  **The drift half is NOT significant and must not be reported as a win.** The null expectation
  for a 4013-character episode at the baseline rate is 2.82 hits; one was observed, Poisson
  `P(X<=1) = 0.23`. The previous run's "no measurable effect at this sample size" was wrong for a
  different reason — the prompt had not changed at all — and replacing one wrong conclusion with
  an over-read of the next one would be the same mistake wearing better numbers.

  **What the run DID establish is that the rule reaches the model, and it established it through a
  new defect.** With the rule inert the model copied `霍尔木兹海峡` verbatim from its Simplified
  source. With the rule shipping it produced `霍爾木茲海峡` — `尔`→`爾` and `兹`→`茲` converted,
  `峡`→`峽` not — six times, consistently. That string is neither the Simplified the sources use
  nor the correct Traditional `霍爾木茲海峽`, so a reader can search for it in NEITHER script,
  which is exactly the harm the proper-noun carve-out exists to prevent. Behaviour changed on
  precisely the collision the rule addresses, which is direct evidence rather than inference —
  and the change was for the worse on that name.

  **The failure mode had not been considered**: "keep the name" and "convert the name" were taken
  to be the only outcomes, and a PARTIAL conversion is worse than either. Caveats kept: one name,
  one run, one model, and `峡`/`峽` may simply be a character this model does not write.

  Also measured, one sample, not attributed: the new episode ran 27% shorter per utterance (71.2
  to 52.1 characters) at a near-identical turn count.

  **Method note.** The drift scan classifies only the four characters verified in context
  (`干 台 群 里`) as already-Traditional and prints everything else for a human to judge — a
  blanket exclusion list would forgive the context-dependent pairs (`面/麵`, `系/係`, `松/鬆`)
  and fail in the direction of UNDER-counting, which is the same error as the ~90-character hand
  table, run backwards.

- **The script rule never reached a prompt: it shipped inert, and three documents described it as
  working.** `instructions._script_rule` matched on the language NAME, but invariant 39 carries the
  language as a SIGNATURE FIELD — so all three call sites (`task.py:37`, `guide.py:37`,
  `audio.py:110`) compose their rule at import time with the literal placeholder
  `"the language named by the `output_language` variable"`, which matches nothing. It returned `""`
  for all six tasks, in production, from the day it shipped. Measured on the shipped classes: every
  one scored `script-rule-text=False`. Found by an independent review of the batch that added it.

  **Replaced by `instructions.SCRIPT_PINNED`, worded conditionally and shipped unconditionally** —
  the same shape the sentence beside it (`Write your prose in {language}`) had always had. All six
  now carry exactly one copy. The proper-noun carve-out moved with it and is stated ONCE covering
  both directions; the superseded table carved it out of the Traditional rule only and left the
  Simplified rule with the mirror-image exposure.

  **The test could not have caught it, and that is the transferable part.**
  `tests/test_instructions.py` called `artifact_language_rule("Traditional Chinese")` — a call shape
  that occurs nowhere in the product. A mutation making `_script_rule` `return ""` was duly KILLED
  by it while the feature was entirely dead. That is a test passing for a reason unrelated to its
  name at FEATURE level rather than assertion level, which is a level the project had not written
  down. Every assertion in that file now goes through a shipped task class.

  **Consequence for the live run this batch spent**: it cost 459s and could not have tested what it
  was spent on — the "after" prompt differed from the "before" only by `NATURAL_REGISTER`, which is
  an unconditional constant and did ship correctly. Whether the script rule prevents Simplified
  drift remains UNMEASURED.

- **The Simplified-character measurement was wrong on four of its five characters.** `CLAUDE.md`
  recorded "five genuine ones — `么 没 干 帮 们`". Re-run over the same two notebooks (675 string
  fields), excluding the three classes the batch had itself identified:

  | excluded | hits | why |
  |---|---|---|
  | Japanese context | 391 | one notebook holds Japanese sources; shinjitai maps to Traditional |
  | punctuation | 78 | zhconv rewrites `“ ” ’` |
  | correct Traditional already | 14 | `干` (干預/干擾), `台` (一台), `群`, `里` (里程碑) |
  | proper nouns | 12 | `霍尔木兹海峡`, copied verbatim from a Simplified source |

  What survives is **`么 对 点 问 题` — five characters, five sites, all in podcast utterances**.
  `没 帮 们` appear ZERO times in either notebook. The "all in podcast utterances, titles and
  answers clean" half of the claim stands and is now verified against field paths rather than
  asserted. No validator is still the right call, for the reason already recorded.

- **Three fixes from the previous batch had no regression test, and the sparse-band measurement was
  overstated in two places.** All from the same review.

  - `tests/test_web_assets.py` now pins the budget note's cap-without-usage branch (by ORDER, so a
    run with both fields cannot take the weaker one), the `dropped` notice's preservation of
    `is-cut` (by the DIRECTION of the conditional), and — as a general rule rather than a token
    name — that **no `var()` fallback in the stylesheet hardcodes a colour**. That last one is
    stated as a property of the fallback because `var(--danger, #d9534f)` is how a typo'd token
    ships looking healthy: the fallback renders, so nothing is visibly broken, and the value
    silently ignores all three theme blocks. `--danger` is assigned nowhere in the tree; `--bad` is
    defined in all three.
  - `tests/test_instructions.py` pins `AnswerQuestion`'s answer-first and "say what the sources did
    NOT settle" rules, which had no enforcement anywhere — mutations deleting each survived the
    full suite.
  - **The real-detector fixture cannot demonstrate the per-band defect and never could**: it
    carries ONE spanning region, so that page is a single band of 104 and both schemes agree on it
    exactly. `_ocr.py`'s docstring and `CLAUDE.md` both reported it as a three-region band the
    fixture holds. The 6-15% figure is sound and was reproduced (7.8% / 8.8% / 9.9% / 10.2% for
    contiguous windows of 3/4/5/8 regions) — it is a claim about PLAUSIBLE bands, and the hedge the
    commit message carried was dropped in both prose copies.

- **Two test guards measured something other than what they said.**
  `tests/test_parsers_pdf.py`'s single-column guard asserted `len(raw) > 20` under the message "the
  fixture must produce several regions" — `raw` is a normalised WORD list, and that page has FOUR
  regions, so the guard read literally was false while passing. It now asserts the GEOMETRY that
  actually decides (the page must be declined BY the spanning guard, not by the two-region
  short-circuit above it), computed with plain arithmetic so the fixture stays validated
  independently of the code under test. And `test_web_assets.py`'s regenerate test imported
  `rlm_notebook.api`, so without the `api` extra it FAILED rather than being absent — sharper than
  the trap the Verify section records, and it misreported a missing dependency as a broken feature.
  It reads `api.py` as text now, like every other assertion in that file.

- **OCR reading order: a two-column scan no longer comes back with its columns interleaved
  (invariant 73).** `parsers/_ocr.py` joined RapidOCR's regions with
  `" ".join(text for _, text, _ in result)`, throwing away the bounding quad reported alongside
  every one of them. RapidOCR emits regions roughly line-by-line ACROSS the full page, so a
  two-column page produced prose that jumps between columns mid-sentence — the model then read
  scrambled text, and a citation's `quote` could be a scrambled span that still passed coordinate
  verification (invariant 5 checks where, never what).

  **Measured against the same pages' own text layer** (`difflib.SequenceMatcher` over normalised
  word sequences), two real papers, every page over 120 words:

  | | before | after |
  |---|---|---|
  | ResNet, two-column, 12 pages | 0.425 | **0.756** |
  | "Attention Is All You Need", single-column, 15 pages | 0.802 | 0.792 |

  **The text-layer path was never affected, which is why this was not found earlier.**
  `pypdfium2` reads a two-column LaTeX paper in correct column order already — the content stream
  is written a column at a time — so only scanned/textless pages (invariant 7's OCR dispatch) were
  ever wrong. That was verified on the same PDF before any code changed, not assumed.

  **Two drafts were wrong before this one, and both failures are the reason the rules are shaped
  the way they are.** The first treated any band containing a centre-crossing region as untrustworthy
  and fell back to plain order: on a real page the ONLY crossing region was the page number centred
  in the footer, and that one tiny box cost the whole page its column order — the initial fix
  measured no better than no fix at all. It "worked" in the prototype only because an earlier version
  had used the image midpoint rather than the content midpoint, which happened to land on the other
  side of that page number. The second draft sorted each band by vertical position, which measured
  WORSE on BOTH layouts (two-column 0.756 -> 0.743, single-column 0.774 -> 0.751) — RapidOCR already
  emits a column's lines in reading order, so the re-sort only disturbed near-ties. Isolating the
  re-sort from the column split, as four separate variants over one cached OCR run, is what showed
  this; guard parameters were swept first and moved nothing, which is what prompted looking
  elsewhere.

  **Accepted cost, inspected rather than inferred**: a wide table on a single-column page can be
  split down the middle (the Transformer paper's Table 3 does), and two attention-visualisation
  pages measured -0.08/-0.06. Both were read directly before being accepted — a flattened table and
  a scatter of figure labels are word soup under either ordering. `_MAX_SPANNING_FRACTION = 0.15`
  is set from a two-document sample and deliberately errs low, since too low only declines to
  improve a page while too high reorders one that was already correct.

- **`rlm-harness` 1.0.0 -> 1.10.0, and `worker.py` stopped reaching into a private module.** Ten
  minor versions with no code change beyond one import: the only edit the upgrade itself forced was
  swapping `from rlm_harness._retry import _short_error` for the public `from rlm_harness import
  short_error`, verified to be the SAME object with the same signature before the swap. Note the
  fix went one step further than proposed — dropping the underscore off the NAME still left the
  import reaching through `_retry`, a `_`-prefixed MODULE; `short_error` is in the kit's `__all__`,
  so the top-level path is the one with a compatibility promise behind it.

  `dspy` moves 3.2.1 -> 3.3.1 with it (the kit's floor since 1.5.0), which renamed `max_iterations`
  to `max_iters` upstream. The kit absorbs that internally: `RLMConfig` still accepts
  `max_iterations` and invariant 59's budgets (25 / 16384 / 40000 / 1) still arrive intact —
  checked, not assumed. Resolution touches three packages in total.

  **The upgrade makes something measurable that was structurally unmeasurable here.** This project
  passes a plain `dspy.LM` and never wrapped it in `intercept_sub_lm`, and before kit 1.7.0 only
  that wrapper emitted `sub_call`. So every `sub_call` count in any trace this project has written
  is a property of its own WIRING, not of the model — while three features read those events:
  the ticker's event translation, the citation-turn lookup (invariant 29, which searches a
  `sub_call`'s whole payload precisely because its keys differ from a `main_step`'s) and the
  Trajectory timeline (invariant 70). The kit records it at the task seam now. Stated as a
  structural claim from the code path, NOT as a measurement: `traces/` is empty here, so nothing
  was counted to confirm it.

  **Any later comparison across this boundary must split on `run_start.rlm_harness`** and treat an
  absent field as UNMEASURED rather than zero. Traces written before kit 1.6.0 carry no such field
  and none of `sub_call`, `tool_call.duration_s`, `run_end.error_chain` or `run_end.budgets`/`usage`
  — so averaging a rate across the upgrade reads a component added afterwards as 100% and everything
  older as 0%, which is corpus composition rather than a property of this code.

- **Took two rules from the sibling's `prose-craft` skill, and left most of it, because the rest is
  answering a problem this project does not have.** Measured first on the two real notebooks here,
  20 model-authored fields:

  | `prose-craft` rule | violations measured here |
  |---|---|
  | space between Chinese and Latin | 1 (one podcast utterance) |
  | full-width Chinese punctuation | 0 |
  | avoid stacking three or more `的` | 8, of which 6 are podcast |

  So the two typography rules are answering a failure this project's model is not making, and adding
  them would be writing a rule against something never observed. The `的` stacking is real and it
  CONCENTRATES in the podcast, which fits: it is the only artifact meant to be heard, where a
  listener has no punctuation to lean on. That one went into `podcast-craft` with its measurement,
  not into a prompt — skipping it makes an episode duller to listen to, not wrong (invariant 65).

  **What did go in the PROMPT is an honesty rule**, and it is the half of `prose-craft`'s
  answer section that is not taste. `AnswerQuestion` already said to admit when the sources cannot
  answer a question AT ALL; the commoner case is a question mostly answered with one part left open,
  where an answer that reads confident throughout while quietly skipping the unsupported half is
  worse than a short one that names the gap — the reader cannot see it, and every citation on the
  rest still verifies (invariant 5). Answer-first and stop-when-done went in beside it: a closing
  summary paragraph is a second, worse copy of `follow_ups` (invariant 56).

  **Not taken, and why**: the nine AI-taste patterns (summary sentence, false contrast, bold as
  pseudo-heading) are taste judgements — nothing here can measure whether this project has them or
  whether a rule improved them, and a prompt rule whose effect cannot be observed is one more thing
  to maintain on faith. The em-dash prohibition is the sibling's house style. The `read_file` /
  `grep_repo` grounding advice has no analogue in a corpus this project hands over whole.

- **CI had been red on every push since the rlm-harness upgrade, and nobody looked.** Ten
  consecutive failures. Local `pytest` was green throughout, which is exactly why it went unnoticed:
  the suite passes on 3.13 and fails on 3.11 and 3.12, and only the full run fails — the OCR test
  file alone passes.

  **Root cause, isolated to one line of a dependency.** dspy 3.3.1 installs a lazy-import proxy for
  numpy (`dspy/utils/lazy_import.py`). Against numpy 1.x that proxy re-executes numpy's `__init__`
  while it is already partially imported, the moment another extension module touches the module
  object — so `import dspy; import cv2` dies with `ImportError: cannot import name 'array' from
  partially initialized module 'numpy.core'`, and cv2 reports only "OpenCV bindings requires numpy",
  which names the wrong thing. That takes the whole OCR path with it, since rapidocr imports cv2.

  **Why 3.11 and 3.12 had numpy 1.x at all**: `chatterbox-tts` pins `numpy<2.0.0` below 3.13 and
  permits numpy 2 at and above it, and uv's lock is UNIVERSAL — so the optional extra set the numpy
  version for every install of this project on those interpreters, chatterbox requested or not. CI
  syncs `--extra api` and never touches chatterbox, and still got numpy 1.26.4.

  **So this was never only a CI problem.** Any 3.11 or 3.12 user ingesting a scanned PDF would have
  hit it, because the API process imports dspy and ingestion reaches cv2 through rapidocr.

  The fix states the constraint where it lives: `numpy>=2` is a core dependency now, with the reason
  attached, and every entry in the `chatterbox` extra carries `python_full_version >= '3.13'`. Below
  that the extra resolves to nothing and `ChatterboxProvider`'s existing import guard reports a
  `TTSError` — a loud failure in the feature the user asked for, rather than a silent one in the
  ingestion they did not. Verified on all three interpreters: 621 passed on 3.11, 3.12 and 3.13,
  where 3.11 and 3.12 had been 17 failed / 604 passed.

  **The process lesson is the one worth keeping**: "I ran the suite" meant one interpreter. The
  matrix existed precisely because that is not the same claim, and ten pushes went out on it.

- **Spent a live podcast run to test the script rule. It has no measurable effect at this sample
  size, and the run bought three other things instead.** 459 seconds, one `long` episode on the same
  notebook, same tier as the baseline it replaced.

  | | before the rule | after |
  |---|---|---|
  | Han characters | 3,069 | 4,643 |
  | Simplified in the model's OWN prose | 3 | 4 |
  | rate | 9.78 / 10k | 8.62 / 10k |

  **Three against four is not evidence of anything.** One run, one notebook: the honest reading is
  "no measurable effect", not "it works" and not "it doesn't".

  **The first reading of this run was wrong, and by a lot** — 13.03 against 34.46 per 10k, a
  doubling, reported before the offenders were read. Two errors, both in the MEASUREMENT:

  - **`干` is not a Simplified character here.** The hits were `不干預` and `干擾`, both correct
    Traditional; zhconv rewrites them to `幹`, which is wrong. Three of the sixteen were the tool
    misreading, counted as the model's failure.
  - **Nine of the sixteen were one proper noun, three times.** `霍尔木兹海峡` came verbatim from a
    Simplified source, which is `PROPER_NOUNS` working rather than the script rule failing.

  **That second one is a rule conflict this project created and had not written down.**
  `PROPER_NOUNS` says never translate a name; the script rule says write Traditional throughout; a
  Simplified-spelled name in the sources puts them in direct opposition. The model picked the name,
  which is correct — converting it costs the reader the exact string they would search for
  (invariant 69) — but nothing had told it which wins. The precedence is now stated inside the
  script rule itself, so a reader of that paragraph meets the exception there rather than having to
  hold a later paragraph in mind.

  **The measurement tooling needs both exclusions to be worth anything**, and that is the durable
  part: a zhconv diff counts characters that are correct Traditional in their own right, and it
  counts proper nouns the rules deliberately preserve. Either alone turns a null result into an
  alarming one.

- **Re-measured the Simplified-character claim with a full conversion table, and the earlier zero
  was an artifact of the tool.** The check that produced it used a sibling's ~90-character hand
  table — deliberately small, and documented by its author as a script IDENTIFIER rather than a
  converter. Re-run through `zhconv`'s full mapping over the same fields:

  | | hand table (~90 chars) | zhconv full mapping |
  |---|---|---|
  | nb-6f2d49d3, 50 fields | 0 | 6 |
  | nb-d22c2a9a, 78 fields | 0 | 5 |

  **Most of that difference is not Simplified text.** `zh-hant` rewrites several characters that are
  correct Traditional in their own right — `台`→`臺`, `群`→`羣` — and `zh-tw` adds Taiwan locale
  vocabulary on top (`里`→`裡`). Excluding that class leaves **five genuine Simplified characters**:
  `么 没 干 帮 们`.

  **Where they are is what decides the design, and it inverts the sibling's case.** All five sit in
  PODCAST UTTERANCES. Titles, overviews, answers and follow-ups are clean — zero across both
  notebooks. The sibling's strict per-character check exists for a page TITLE: short, in the
  navigation, on every page, where one drifted character is a visible fraction of the field. Our
  equivalent short nav field (`naming.SuggestTitle`) is exactly the one with no offenders, and the
  field that has them is the one meant to be HEARD — `没` and `沒` are the same sound, and the
  transcript shows one character in a 32-character line.

  **So: still no validator, but now for a reason that survives its own measurement.** Every
  condition that justifies one (short field, visually prominent, repeated, demonstrably drifting) is
  absent here, and the one field that would qualify does not drift.

  **Untested, and stated rather than implied**: all five characters predate the script rule added in
  the entry above. Whether that rule prevents them is unmeasured — it needs a live podcast run, which
  costs money, and no run has been spent on it.

- **A language name buys neither its script nor its idiom; both now have a rule (invariant 39).**
  Two findings, one observed here and one borrowed from a sibling project after reading how
  it had solved the same class of problem.

  **Observed: `源文`.** A Traditional Chinese answer's follow-up questions wrote `源文` for "the
  source text", where a reader expects `原文`. That is a word-for-word rendering of the English, and
  no script rule can reach it — 源 and 原 are both perfectly ordinary Traditional characters, so it
  is a REGISTER failure rather than a script one. `NATURAL_REGISTER` asks for the term a reader of
  that language would use rather than a compound assembled from the English words for it, and it
  composes into a single-script language's rule too, because the failure is about wording.

  **Borrowed: the script rule.** The sibling pins the script in the script itself (`概览` must be
  `概覽`) after a real run returned a document set whose body text were Traditional while every page TITLE
  came back Simplified, so the nav and the page disagreed on screen. This project had NO script rule
  at all — just "write your prose in {language}", the exact under-specification that failure came
  from.

  **The "not reproduced here" that first accompanied this was itself a bad measurement, and the
  correction is the entry below.** It reported zero Simplified-only characters across every
  model-authored field — measured with the sibling's ~90-character hand table, whose own comment
  says it answers "which script is this text in", not "convert this text". A reader that cannot
  report a non-zero value reports absence either way.

  **What was deliberately NOT taken.** The sibling also carries a two-threshold VALIDATOR: a
  majority comparison for a page body (a repository may legitimately contain Simplified strings) and
  a strict per-character check for a short field like a title, justified by a measured case
  (`插件與鉤子系统`, where the majority check correctly reported clean because that is not the
  question a title asks). It is a good design and this project has the matching short field in
  `naming.SuggestTitle` — but adding a validator for a failure never observed here would be building
  machinery ahead of evidence. The prompt rule is cheap and the seam is recorded.

- **Rejected: concurrent source ingestion. It crashes, and the crash is documented in a direct
  dependency's own metadata (invariant 3).** A peer session implemented it in this working tree
  unprompted — `ingest_new` planning serially and fetching through a `ThreadPoolExecutor` — with a
  measured 7.55s to 2.85s on five HTML sources. The objection raised here was that the PDF path,
  the one claimed to scale the saving, had not been measured. Measured: four PDFs serial 0.41s
  `rc=0`; concurrent `rc=134`, SIGABRT (a first attempt gave `rc=139`, SIGSEGV). Cause, verified
  locally at `pypdfium2-5.12.1.dist-info/METADATA:1066`: *"PDFium is inherently not thread-safe."*

  **The upside was near zero exactly where the risk was.** Four ordinary PDFs parse in 0.41s;
  `api.py`'s "can take minutes" describes OCR on SCANNED pages, one branch of PDF ingestion, and it
  had been read as characterising the whole. The 2.94% saving was measured on HTML, where it is real
  and small.

  **The green suite proved nothing**, and that generalises past this patch: `tests/test_ingest.py`'s
  multi-value cases all take local text files through `parse_text`, so nothing in 614 passing tests
  drove two PDFs at once. A suite that is green on the path you did not change is not evidence about
  the path you did.

  Also recorded, from the same exchange: `traces/` is empty here because `cli.py` never reaches
  `runner.start_run` — the only caller is `api.py:1193` — so the CLI cannot produce a trace at all,
  and any future trace-reading measurement has to go through the API path. That sharpens an earlier
  entry which said only that this checkout had no corpus.

  A sound version is not ten lines: the waiting is the network fetch and the crashing is the PDF
  parse, and `ingest_one` fuses them, so separating them is a refactor of the ingestion dispatch.

- **A fourth review round over the eight unreviewed commits: one shipped regression, one false
  claim in three places, one more hollow test, three UI defects.** All verified locally before being
  acted on.

  **The regression is the serious one, and it was mine.** `_column_count` was called per BAND, and a
  column count is a property of the PAGE. A sparse band — a few short fragments between two spanning
  elements — reads its own intra-column whitespace as a gutter: on this project's own real-detector
  fixture a three-region band counted 3 columns and was DECLINED, returning the interleaved
  detection order the module exists to remove. Estimated at 6-15% of that page's plausible bands.
  The count now runs once over the page's non-spanning regions, beside the existing page-level
  guard, so a band cannot be seen at all.

  **The test written for it was hollow, which makes four in this session.** It asserted on the real
  fixture, whose page is a SINGLE band — so per-band and per-page counting cannot differ there and
  it passed against the bug. The replacement builds a page where the two readings disagree: the
  sparse band's fragments sit inside the left column's own x-range, so the page projects to two runs
  while the band alone projects to three. Verified by restoring the old code, which now fails it.

  **A consequence stated in three places was simply false.** `_MIN_GUTTER_SHARE`'s comment, invariant
  73 and a changelog entry all said raising the threshold past 0.038 would make the real page "read
  as one column and stop being reordered at all". It would not: the only test is `> 2`, so a count of
  1 falls through to the split exactly as 2 does, and the output is byte-identical at 0.02, 0.05 and
  0.30. The hazard runs the other way — a higher value merges runs, lowers the count, and stops the
  four-column DECLINE from firing.

  **The single-column end-to-end test never reached the guard it named.** `make_text_pdf` draws one
  unwrapped line per page, so OCR returned a single region and `reading_order` short-circuited at
  `len(items) < 2`; mutating the page-level threshold left it green. `make_single_column_pdf` draws
  five lines, and the test now asserts it produced enough regions for anything to be exercised.

  **Three defects in the budget note.** "No generation cap was reported" was shown when a cap WAS
  reported but the provider returned no usage — two states collapsed into the message for one, in
  both languages; there is a fifth state now. The `dropped` warning overwrote `className`, destroying
  the truncation colour on a run that both hit the cap and had its step budgets rejected — the one
  thing those colours exist to keep separable. And `.traj-note.is-cut` used `var(--danger)`, which is
  not a token in this stylesheet; the project's token is `--bad`, defined for all three themes.

  Also corrected: dspy's `_check_truncation` was credited with a mechanism it does not use (it
  branches on `finish_reason == "length"`, never on token counts — the rule is the kit's
  recommendation, not dspy's), and `worker.py` still carried a comment calling its import private on
  the very line `b841605` changed to the public one.

- **Made invariant 73's headline claim reproducible in CI.** Every accuracy figure recorded for the
  reading-order work was measured on real papers that cannot go in the repo, so CI could reproduce
  none of them — the numbers were evidence a reader had to take on trust. Two tests now run the REAL
  OCR stack over a two-column page built from prose this project owns
  (`_pdf_fixtures.make_two_column_pdf`, drawn at coordinates so the gutter belongs to the fixture
  rather than to a layout engine).

  **They assert STRUCTURE and DIRECTION, not a figure.** "Every left-column line precedes every
  right-column line" does not depend on how well the OCR read the characters; an exact ratio would
  move with an OCR version and would have to be re-measured rather than trusted. The similarity check
  only pins that the gain is real and clear (measured +0.222 on this page, asserted > +0.10).

  Confirmed the effect reproduces on synthetic content BEFORE building the test: 0.459 detector order
  against 0.681 reordered. The gap between 0.681 and a perfect 1.000 is OCR dropping spaces
  (`eachlayerhas`), which hits both readings equally — the ordering itself is exactly right, which is
  why the structural assertion is the load-bearing one. Verified by neutering `reading_order` to
  return detection order, which fails the two-column test.

  **What is still NOT reproducible, stated rather than left implied**: the corpus-level measurements —
  the 0.425 -> 0.756 across twelve real pages, the scanned-corpus validation, the CJK figures, the
  good/garbled score overlap behind invariant 74. Those are properties of documents, not behaviours,
  and pinning them would mean shipping the documents. They stay recorded as single-run measurements
  with their provenance.

- **A four-column page is declined instead of being cut in half (invariant 73).** Recorded as a
  limitation when a review found it; now fixed. Three columns already declined themselves — the
  middle column crosses the centre, so the page-level guard fires — but an even count has its centre
  in the middle gutter with nothing spanning it, so the split ran and produced
  `c1r1 c2r1 c1r2 c2r2 … c3r1 c4r1 …`: the page halved, and the rows inside each half interleaved.
  That is the defect the whole module exists to prevent, at half scale, and it was reproduced before
  being fixed rather than taken from the note.

  `_column_count` projects a band onto the x-axis and counts the runs a real gutter separates; above
  two, the count declines. **The threshold's hazard runs UPWARD, and the first version of this entry
  said the opposite**: the real two-column page has a 38px gutter across 996px of content, 0.038
  against a 0.02 threshold — but raising the value MERGES runs and LOWERS the count, and since the
  only test is `> 2`, a count of 1 falls through to the split exactly as 2 does. Output is
  byte-identical at 0.02, 0.05 and 0.30. What a higher value breaks is the DECLINE: a four-column
  page merges to two or fewer and is halved again.

  One probe was wrong before it was right: counting columns over ALL the page's regions returned 1,
  because the page number sits IN the gutter. `_order_band` never sees it — `reading_order` peels
  every centre-crosser off as a band boundary first — so the count on the band it actually receives
  is 2. The fix was to the probe, not the code.

  Four of five mutations die (dropping the decline, declining at >1, moving the gutter share to
  0.05, taking `reach = end` instead of the running max). The fifth is `>` versus `>=` at exactly
  the threshold, accepted unpinned for the same reason as the other exact-equality boundaries here.

- **`line-length = 110` is enforced now, not a convention.** Ruff's default rule set carries no
  `E501`, so the number in `pyproject.toml` was a formatter setting that `check` ignored — about 20
  over-long lines had accumulated, and a name scrub once left a 157-character line that only an
  independent review caught. All 19 remaining offenders rewrapped (eight prose, eleven restructured
  code) and the rule selected.

  **Selected with `extend-select`, never `select`.** The first attempt named `select` and re-listed
  what the defaults were believed to be, which is a guess: it pulled in `E402` and reddened 20 lines
  in the test suite — the deliberate `pytest.importorskip` that has to run BEFORE the imports it
  guards, which the Verify section documents. `extend-select` adds to the real defaults instead of
  replacing them with a reconstruction.

  Verified in both directions rather than by the tree going green: a probe file with a 120-character
  line is now reported, and the tree is clean.

- **Built the `run_end.budgets`/`usage` surfacing the entry below specified (invariant 75).**
  `trajectory.budget_summary` is a pure function over trace events — no server, no model, no run,
  the seam invariant 44 established — and the Trajectory drawer gained a budget note beside its
  timing note.

  **Three states, and the third is why this needed a rule.** A run that stayed under its cap shows
  the busiest turn against the cap and the percentage; a run that hit it shows the truncation with
  both numbers and what it costs (a truncated code cell is usually repaired by the planner's next
  turn, a truncated final answer ends the run); and a trace from before rlm-harness 1.10.0 shows
  **NOT RECORDED**, in its own colour, with the string itself denying the wrong reading. The three
  are distinguishable by colour before the sentence is read, which was the point.

  **The proximity reading shipped as a number**, per the correction recorded below — the "no
  gradient" measurement came from a corpus at twice its model's needed cap and does not transpose to
  16384. It is labelled as a shape to expect rather than a local figure.

  **Two of this project's own tripwires caught the work**, which is the system behaving as designed:
  invariant 48's translation-key check refused the new `t()` keys until the zh-Hant table had them,
  and the Chinese-punctuation check rejected an em dash carried over from the English copy. A third
  was added — a source-tree assertion that the not-recorded branch comes first and uses its own
  string, since there is no JS test runner (invariant 36).

  Verified by mutation rather than by passing: six mutations of `budget_summary` (returning `{}`
  instead of `None` for an unmeasured trace, `>=` to `>` at the cap, dropping the no-cap guard,
  taking the first attempt instead of the peak, always computing the ratio) each fail at least one
  test, and disabling the null branch fails the new tripwire.

- **Design constraint recorded for the `run_end.budgets`/`usage` follow-up, BEFORE building it.**
  The kit upgrade made those fields available; `trajectory.py` reads `run_end` and surfaces neither,
  which is a real gap for a drawer whose whole purpose is "why did it produce that"
  (`accepted-not-done`). Guidance arrived from the kit maintainer as a measurement, was recorded,
  and was then overturned by its own author — both halves are kept below, because which half
  survived is the useful part:

  **First guidance, since CORRECTED — recorded because the correction is the lesson.** The initial
  advice was "do not build a proximity indicator, there is no gradient": on the measured corpus the
  used/cap ratio had a HOLE, 363 runs below 0.6, zero between 0.6 and 1.0, 21 at exactly 1.0.

  **That hole is an artifact of the CAP, not a property of the model, and it does not survive
  transposition to this project's cap.** The measured corpus ran at 32768; this project's
  `max_tokens` is 16384 (invariant 59). Converting each bin back to absolute tokens and re-dividing
  by 16384 moves the two bins spanning 9,830-16,384 tokens — 64 runs — straight into the band that
  was empty, and the two runs sitting in 16,384-19,661 would TRUNCATE outright rather than fit
  comfortably. Median max-turn 0.209 -> 0.418, p90 0.378 -> 0.756; both are the mechanical doubling.
  **So at 16384 there IS a gradient, and a proximity reading may be exactly the right thing to
  build.** The hole said the cap was roughly twice what that model needed, never that the model has
  no middle.

  Arithmetic checked here rather than accepted: the bins transpose exactly as claimed and 49 + 15 =
  64. A denominator that did not reconcile — 64/379 against earlier figures summing to 384 — turned
  out to be **two populations reported without saying so**, and the split is worth keeping because
  it changes which number to quote: 385 runs reached `run_end`, of which 379 SUCCEEDED and 6 FAILED.
  The binned distribution is the successes only (363 / 0 / 16 at the cap); the failures add
  1 / 0 / 5; across all 385 it is 364 / 0 / 21, which closes. So **64/379 = 16.9% of successful runs
  and 64/385 = 16.6% of everything reaching `run_end`** — both defensible, neither interchangeable.
  It cross-checks independently against the same source's "21 hit the cap, 16 finished anyway":
  16 successes plus 5 failures at the cap is exactly 21.

  **What keeps this an indication rather than a measurement**: transposing assumes a run's token
  count is unchanged by the cap it ran under. `max_tokens` is a hard stop rather than a hint, so
  that is plausible, but a model given less room may genuinely write shorter and nothing here
  settles it. Confirm against this project's own runs before treating 17% as a local figure.

  **What survived the correction unchanged is the MECHANISM**, and it is the half worth relying on:
  of the runs that hit the cap, most finished anyway — a truncated CODE cell is a `SyntaxError` that
  dspy's own in-loop feedback repairs, while a truncated FINAL answer kills the run. That is a
  property of dspy's loop and carries to any cap and any model. So the surfacing to build is
  per-run and retrospective — "a turn in this run was truncated at N tokens against a cap of M" —
  with a proximity reading now a live option rather than a ruled-out one.

  **The pattern is the lesson, and it repeated twice in two exchanges**: a fact true in one
  configuration, stated without the configuration. The same source's import advice dropped an
  underscore from a NAME and left the import reaching through a private MODULE; this one reported a
  hole and left out that a hole at 2x the needed cap says nothing about 1x. Splitting an incoming
  claim by how far it travels — mechanism versus measured shape — caught both before either was
  known to be wrong, which is why the provenance line is recorded next to every borrowed number
  here rather than dropped once it looks settled.

  **And one working rule, earned by getting it wrong in this very entry: after correcting a claim,
  re-read what INTRODUCES it, not only the claim.** The correction above replaced the guidance and
  left the entry still opening with "it rules out the obvious design" — the one thing the correction
  had just removed, sitting in the first line a reader meets. Same shape as fixing the underscore in
  `_short_error` and leaving the import reaching through `_retry`. The challenged sentence is easy to
  find because somebody quoted it back; the sentence that set it up is not, because nobody did.

- **A third review round, this time over the restorations themselves; six defects fixed.** Restored
  prose is the dangerous kind, because it reads as authoritative while nobody has re-checked it
  against the code. Of 26 claims put back by the two restoration commits, four were wrong.

  **The worst pointed a maintainer at the wrong file.** The restored coverage floor — mutation
  testing once got `setAttribute("href")`, a template-literal `` createElement(`a`) `` and a
  `window.location` assignment past the test — was attributed to
  `test_the_markdown_renderer_builds_nodes_rather_than_markup`. That test checks
  `innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write` and would fail on none of the three.
  The floor belongs to `test_the_markdown_renderer_never_creates_a_navigable_link`, which is a
  different test with a different sink list. Someone widening an XSS guard would have widened a file
  that does not have one. The two are now named separately with an explicit "do not merge these in
  your head".

  **One overstated a guarantee.** The lazy-titling tripwire's `ensureTitle();` count is a FLOOR
  (`>= 4`), so it catches a call site being DELETED, not a fifth model-running action forgetting to
  add one. The restored sentence claimed the latter. The useful half is the slice assertion, and the
  text now says which half does what.

  **Two were mechanical and both from the restore itself**: a "rests on four rules" lead-in left
  standing over five bullets after one was appended, and an insertion that landed mid-sentence and
  orphaned a `The`.

  **The substantive code gap: the log's headline number was untested for the case it exists to
  explain.** Gating it on `replaced` instead of `second_opinions` survived every test — and that
  mutant silences the line for exactly the majority case in the 260-page measurement, where most
  suspected pages are NOT replaced. The logging test also made all four quantities equal (two pages,
  two suspected, two replaced), so swapping any two in the format string passed. Now: four pages,
  two suspected, one replaced, one blank — four different numbers, with a second test covering
  "suspected but nothing replaced". Getting the blank page to matter took two attempts: the
  monkeypatched OCR stub was handing text to a page that has none, so `len(blocks)` silently equalled
  `len(pdf)` again and the mutant lived through the first fix.

  Also: both empty-log assertions are scoped to this module's logger rather than to all of
  `caplog.text`, and the real-geometry fixture's self-disclaimer now names all three things it cannot
  see (its single centre-crosser is the last detection, so the spanning branch is invisible in it
  too) alongside the one thing only it can — `_order_band`'s within-column sort key, which no
  hand-built fixture reproduces.

- **Closed the mixed-script scoring hole, and made one measurement reproducible in CI.** Both were
  named as open when the OCR work was reviewed; neither had been acted on.

  **A garbled Chinese body carrying a clean English reference list scored 1.000 and was never
  challenged.** `wordlike_ratio` reads Latin tokens only, so on a mixed page its verdict came
  entirely from whatever minority happened to be readable — measured at a 0.49 Latin share of the
  page's alphabetic characters. The CJK protection was "there are no Latin tokens", which is a
  property of pure CJK pages and not of the mixed ones that actually occur. It is now a SHARE
  (`_MIN_LATIN_SHARE`, 0.7): the function asks whether the rule applies before asking what it says.
  Erring high costs a missed improvement, erring low lets a Latin-shaped rule pass sentence on a
  page written in something else, so the uncertainty is spent upward. `_WORD_TOKEN` and
  `_LATIN_CHAR` are built from one character-class constant so they cannot drift apart about what
  counts as Latin — one decides what is scored, the other whether scoring applies.

  **Every OCR number in these entries came from documents not in the repo, so CI could reproduce
  none of them.** One test now drives real detector geometry: 105 boxes measured off a rendered
  two-column page, stored as `tests/fixtures/ocr_two_column_page.json` with the TEXT EXCLUDED, so
  the fixture carries a real page's layout without carrying its prose. It asserts the structure —
  the whole left column, then the whole right, then the centred footer — rather than freezing an
  output list, which is the difference between saying what correct means and locking in today's
  answer; and its gutter bounds are read off the measurement rather than computed by the code under
  test. Stated rather than oversold: that page is a single band, so the band-assignment key and the
  vertical-centre choice are invisible in it and stay pinned by the synthetic fixtures. `tests/` is
  not in `pyproject.toml`'s `packages`, so none of this ships in the wheel.

- **Finished the condensation audit: invariants 1-37 read semantically, ten losses restored.** This
  range had only ever been checked mechanically — that every heading survived and every bold rule
  still appeared — which is a weaker check than the one that found real losses in 38-72, and it was
  the last unread part of the rewrite. Every restored item was verified live in the code first.

  **1-37 came through markedly better than 38-72**: no inverted security statement, no weakened
  contract, and every residual-risk hedge intact. What it lost is almost entirely the layer linking
  a rule to its enforcement, plus two client-side rules that had no other home.

  **The two that had nowhere else to live** are both in invariant 29's dropped `↓ Download`
  paragraph: the filename is SLUGGED from the model-authored notebook title, because `download` is an
  attribute the browser turns into a path component; and its extension follows the SERVED file,
  because a provider may emit WAV and naming it `.mp3` would mislabel half of them. The second is the
  sharper loss — `app.js` records that an audit once found it listed among invariant 43's "handled"
  consequences when it was not, so invariant 43 is explicitly not its home either.

  **One behaviour lost its "what" while keeping its "why".** Invariant 34 kept "the lifespan reads
  the retention settings itself — otherwise a typo'd value means silently never prune" but dropped
  "a malformed one refuses startup instead". Someone could satisfy every word of the surviving
  sentence by warning-and-defaulting, and turn a typo'd `RN_TRACE_RETENTION_DAYS` back into silently
  keeping files that hold ingested source text.

  **Also restored**: five enforcement links to live tests (the lazy-titling tripwire, which also
  asserts a CALL COUNT so a fifth model-running action must touch it; the process-group test that
  spawns a real grandchild, one of the few executable claims here rather than a source-tree
  assertion; the guide-registry tripwire; the captionless-YouTube 422 test; and the specificity test
  invariant 36 refers to only as "a separate test"); the temp file whose `finally` must wrap
  `synthesize()` itself, not just the read-back; the persisted `Overview.run_id`/`Podcast.run_id`
  contract that invariant 70's re-openable "⌁ N steps" pill rests on; invariant 6's "don't
  over-tighten it into false negatives chasing a clean read"; invariant 18's point, which the
  condensation left hanging (a third host needs BOTH maps updated and only one fails loudly); and
  invariant 37's `textContent`-never-`innerHTML` clause for the one model output with no schema
  validation behind it.

  **Checked and correctly dropped**, recorded so the line is visible: the pymupdf/AGPL discovery
  story, the `/etc/passwd` reproduction, the lost-update reproduction, the VTT design history and
  every "an independent audit found…" attribution are incident narrative and belong here. Invariant
  24's enumeration of `SystemExit` sources was declared wrong by the old text itself. Invariant 36's
  `.studio-view { display: flex }` example is stale — that rule no longer exists in `style.css`.

- **`parse_pdf` now reports what the second-opinion OCR cost, because that cost was measured only
  after it shipped.** Asking what invariant 74 actually does to the 260-page scan that motivated it
  gave: 61 pages suspected and OCR'd for comparison, 4 unscoreable, 187 untouched. So roughly a
  quarter of that document pays a full OCR pass on top of reading its own text layer — and on the
  API path that runs in the request's thread pool (invariant 34's accepted limitation), where a slow
  ingestion is indistinguishable from a hang. One log line per document, only when a page paid,
  naming how many paid and how many the payment changed. Same idiom as the trace sweep's line.

  **Deliberately not capped.** A page with NO text layer already costs the identical OCR pass under
  invariant 7, uncapped and uncontroversial, so bounding the speculative case more tightly than the
  unavoidable one it sits beside would be backwards — and a cap would silently leave garbled text on
  whichever pages fell past it. The honest answer to "why is this slow" is a sentence, not a limit.

  It also settles a question left open when invariant 74 shipped: the short garbled strings quoted as
  its trigger all score `None` on their own, so it was not obvious the feature fires on the document
  they came from. It does — those strings are excerpts, and the full pages clear the token floor.

- **Restored what the rulebook condensation dropped: enforcement links, one security statement, and
  four contract details.** The condensation moved incident narrative to this file, which was its
  stated intent and is right. What it also removed, unintentionally, was the layer of the rulebook
  that connects a rule to the thing enforcing it — and for rules whose ONLY enforcement is a
  source-tree assertion (invariant 36: this project has no JavaScript test runner), the rulebook is
  the only place a later reader would learn the rule exists at all. Every item below was verified
  live in the code before being restored; nothing was put back on the strength of the old text.

  **One rule had disappeared entirely.** `test_no_event_is_subscribed_twice_inside_one_init_function`
  (`tests/test_web_assets.py:209`) still runs, and the prohibition it enforces — one subscription per
  event per init, because four inits in `app.js` spell the same event names and a duplicate handler
  reads as a race that isn't one — appeared nowhere in CLAUDE.md. Deleting that test would have
  contradicted nothing.

  **One statement had been inverted, which matters most.** Invariant 52 said the ticker's `detail`
  "can quote ingested source text — the same category invariant 29 already records". What survived was
  only "the step's `output` is deliberately NOT streamed", which reads as though no source text
  reaches the SSE stream at all — on an API with no authentication (invariant 25). The stronger claim
  is now stated first, with the narrower one explicitly marked as not a promise.

  **Also restored**: the markdown renderer's XSS tripwire together with its coverage floor (mutation
  testing once got `setAttribute("href")`, a template-literal `` createElement(`a`) `` and a
  `window.location` assignment past its first version — a future widening must still catch all three);
  `assert_repl_safe` as half of what the invariant-1 tests check; `TTSProvider.synthesize`'s offsets
  being **in seconds**, which is the contract between every provider, `Podcast.offsets` and `app.js`'s
  seek handler; the `rlmnb-podcast-length` storage key; the `corpus-navigation` skill by name;
  `.notebook-menu` as a clipping ancestor, which invariant 54's own text says the test cannot see;
  `RN_BASE_URL` being "not just a URL, and a later reader must not relax it on that basis"; clearing
  the conversation being "the one thing NOT to do" as a freeze signal; and the residual-risk hedge on
  invariants 39, 49, 56 and 62, whose absence had made those four read as stronger claims than the
  ones that kept it.

  **Checked and deliberately NOT restored**: six other test names the old file mentioned are still
  live, but in each case the RULE survived the condensation and only the test's name went — and
  `test_the_podcast_transcript_is_not_capped_by_a_fixed_height` carries its whole rationale in its own
  docstring. Naming every test in the rulebook is not the convention; naming the ones that are a
  rule's only enforcement is.

- **An independent review of the OCR work found three real defects and a hollow test; all fixed.**
  Every finding below was reproduced locally before being acted on.

  **A correct text layer could be replaced by a WORSE OCR of itself, for accented Latin scripts.**
  `_WORD_TOKEN` was `[A-Za-z]{2,}`, so a diacritic split every accented word into ASCII fragments
  and the vowelless residue counted as garble: correct German scored 0.824 and correct Vietnamese
  0.375, both under the 0.85 suspicion gate. Worse, stripping the accents — exactly what a weak OCR
  does — raised both to 1.000, clearing the replacement margin. The metric REWARDED the degradation.
  This was the same "a bundled dictionary would describe one language while condemning pages in
  another" that the dictionary-free design exists to avoid, reintroduced through the regex, with
  only CJK actually protected. The token class now spans Latin-1 Supplement, Latin Extended-A/B and
  Latin Extended Additional, and the vowel test folds accents through NFD first. Deliberately not a
  general Unicode-letter class: CJK characters are letters too, and matching them would end the
  `None` that keeps a Chinese page away from rules about vowels.

  **The replace decision was volume-blind.** Both sides are RATIOS with no length term, so a
  484-character layer scoring 0.682 (four clean sentences plus a garbled figure block) was replaced
  by a 59-character OCR result scoring 1.000 — a page of prose traded for a caption.
  `_OCR_MIN_TOKEN_SHARE` (0.25) now requires the second opinion to have read a comparable amount of
  the page. Calibrated on real pages: the two that genuinely needed replacing scored 0.39 and 0.45,
  a diagram page that must keep its layer 0.03, the constructed loss 0.10.

  **`ocr_image`'s documented "never raises" had become false.** `reading_order` reads coordinates
  out of the detector's result and sat OUTSIDE `_try_rapidocr`'s try/except, so a `None` box, a flat
  xyxy box, a two-element row or a non-numeric coordinate all escaped — verified, all four. The
  earlier code touched only the text field, so this change widened the unguarded surface from row
  arity to every coordinate value, against a dependency pinned `>=1.3` with no upper bound.

  **The test named for invariant 74's headline rule did not test it.** Its OCR fixture contained
  `ELTN`, the same token the assertion looked for in the layer, so the assertion held whichever text
  came back: deleting the entire comparison from `_page_text` left the suite green, as did setting
  the margin to zero. Fixed, and the margin is now pinned from both sides.

  **Mutation testing drove the rest.** Of the surviving mutations the review reported, the two that
  mattered are now killed: the band sort key and the top-edge-versus-centre choice. Both needed a
  fixture with a centre-crossing region to be observable at all — inside one band the regions are
  re-sorted into detection order anyway, which is why every earlier fixture left them alive.
  Three survivors are ACCEPTED and stated rather than chased: centre versus bottom edge, and two
  boundary flips (`>` to `>=` on the spanning guard, `<=` to `<` in the partition) that differ only
  on exact equality. Writing tests for those would be contriving inputs to defend an arbitrary
  choice.

  **Overstated claims corrected rather than defended.** Invariant 7 said the garbled-layer gap was
  "closed"; it is narrowed — a layer too garbled to yield eight Latin tokens still scores `None` and
  is never challenged, which covers most of the short strings quoted as the trigger. The docstring
  listed `ELTN` as an example of "no vowel at all" while the code scores it wordlike. `pdf.py`'s
  comment still said this project's use case is a missing layer "not a garbled one" twelve lines
  above the code that handles a garbled one. The "safe side" framing on `_MAX_SPANNING_FRACTION`,
  the "unsupported layouts decline themselves" claim (true for odd column counts; a four-column page
  passes the guard and is split down the middle) and "language-agnostic" (the split hardcodes
  left-then-right, so a two-column RTL scan would be swapped) are recorded as limits.

  **Not fixed, and worth naming**: the condensation in `15813c4` dropped the enforcement records
  linking several live tripwire tests to the rules they pin, weakened invariant 52's statement that
  the reasoning stream can quote ingested source text, and dropped a few contract details
  (`synthesize`'s offsets being in seconds, the `rlmnb-podcast-length` key, the `corpus-navigation`
  skill by name). That is a separate restoration pass over a commit this work did not author.

- **Measured the CJK OCR coverage, and rejected a Traditional Chinese recognition model as a
  wash.** No code changed; this is the evidence, and the reason not to do it again.

  The default backend already handles both scripts. RapidOCR ships `ch_PP-OCRv4`, which is
  Chinese-native: Simplified measured 1.000 on a paragraph and 20/21 per isolated character,
  Traditional 0.879-0.973 per paragraph and 16-17/21 isolated (two fonts, Songti TC and Heiti TC).
  Invariant 73's reordering is language-agnostic and helps Chinese exactly as much as English —
  a two-column Simplified layout went 0.646 -> 1.000 — while a single-column CJK page crosses the
  centre on every line and is left untouched.

  PaddleOCR's `chinese_cht_PP-OCRv3` recognition model was then fetched with the official
  `chinese_cht_dict.txt` (8421 characters, covering every character that had failed) and wired in
  through RapidOCR's `rec_model_path`/`rec_keys_path` seam — which exists precisely because the
  bundled models carry their dictionary in ONNX metadata while an external file is also accepted.
  Head to head over six cases it was a wash: mean 0.929 against 0.922, winning two, losing three,
  tying one. Not worth an 11MB model, a doubled OCR pass on every CJK page, and the provenance of
  a third-party conversion (RapidOCR publishes no `chinese_cht` ONNX of its own; only japan, korean
  and english).

  **The trap, recorded because it inverted the conclusion twice.** `PIL.ImageFont.truetype(path,
  size)` loads face index 0 of a `.ttc` COLLECTION, and index 0 of macOS `Songti.ttc` is Songti
  **SC** — which silently renders nothing at all for Traditional-only glyphs. The first pass
  scored Traditional at 0.589 with 0/21 isolated characters, which read as the backend having no
  Traditional support, and produced two further false findings on top: that swapping in the
  `chinese_cht` model changed nothing (it was the *detector* finding no ink, not the recogniser
  lacking the character), and that invariant 73's reordering compounded the damage (the blank gaps
  fragmented each line into pieces the geometry then mistook for two columns). Rendering the
  fixture to a PNG and looking at it showed blank space where the characters should be. Every one
  of those findings evaporated with a font that has the glyphs.

- **A garbled-but-present text layer is now caught, by comparing against OCR rather than by
  trusting a threshold (invariant 74).** Invariant 7 had recorded "a bad-character-ratio heuristic"
  as the follow-up for this gap. The heuristic does not work on its own, and measuring is what
  showed it: across six documents the good pages' worst scores overlap the mis-decoded pages' on
  every metric tried — alphanumeric ratio, long-token ratio, dictionary hit rate, and the shape
  score that shipped (good 0.79-0.99 against garbled 0.63-0.80). A false positive is not free
  either, since a good text layer beats any OCR of the same page.

  So the score only decides whether to SPEND an OCR pass and the comparison decides what to keep:
  below 0.85 the page is OCR'd as a second opinion, and the layer stands unless OCR beats it by
  0.10. A generous gate then costs time and never quality. The margin earned its place immediately —
  a bare `>` flipped a healthy page (0.97) to OCR (0.98) on a rounding-level difference, while the
  genuinely mis-decoded pages won by +0.20 and +0.27.

  **The trigger was a real document**, found while validating the reading-order work: an Internet
  Archive scan of a 1960 IRE monograph whose chart pages were fed to the scanner upside-down or
  mirrored, so its embedded OCR decoded to `UN ELTN NII PIN COCO` and `Zh *9td 3ONVY G3zMw30!` —
  that second string is "FIG.72 / ACTUAL RANGE" reversed. `_MIN_TEXT_CHARS` sees characters, skips
  OCR, and that is what reached the corpus.

  **An assumption had to die first.** The initial read was that re-OCRing those pages gains nothing
  because the source is a chart, and that was stated before it was checked. It is false: on the same
  pages OCR recovered `FALSE ALARM INTERVAL`, `PULSE REPETITION RATE` and `THE INCOMPLETE TORONTO
  FUNCTION`, because it reads the page as rendered rather than as the scanner mis-fed it. Had that
  gone unchecked the conclusion would have been "not worth building".

  **`wordlike_ratio` is dictionary-free on purpose**: `/usr/share/dict/words` is absent on stock
  Debian so CI cannot depend on it, and a bundled list would describe one language while condemning
  pages in every other. Two shape rules replace it — no vowel anywhere in the token, and case
  flipping mid-token, with all-caps exempt. Real garble often does contain vowels (`ELTN` scores as
  wordlike), so it works in aggregate and never per token.

  **Accepted loss, stated rather than discovered later**: a pure diagram page OCRs to a handful of
  numeric labels, falls under the eight-token floor, scores `None`, and keeps its garbled layer even
  though the OCR was observed to be better. `None` is also what keeps a CJK page safe from rules
  written for alphabets with vowels, so the floor is load-bearing in the other direction.

- **Validated the OCR reading-order fix on real scans, which is the only population it serves.**
  Everything the fix was originally measured on was a rendered DIGITAL PDF — but only a page with
  no text layer reaches OCR at all, so the whole calibration had been done on a proxy for the
  target rather than the target. Skew was the specific worry: a scan rotated a fraction of a degree
  widens every line's bounding quad and drifts its vertical centre, and those are exactly the two
  numbers the ordering keys on.

  **It transfers.** Physical Review Letters, December 1958, a genuine two-column scan (with the
  facing page bleeding into the right margin, as scans do): 16 pages, **0.329 -> 0.509**, the split
  applied on every one of them, spanning fractions 0.01-0.05 — the same band the clean renders
  produced. The absolute numbers sit lower than the digital measurements because the reference is
  Abbyy's OCR of degraded 1958 print, so two OCR engines disagree at the character level no matter
  what the ordering does; the delta is the part that means anything. One page moved -0.005.

  **Skew was then isolated rather than left confounded** with sensor noise, old typography and the
  reference OCR's own errors: rotating a clean two-column render by 0.25, 0.5, 1.0 and 2.0 degrees
  held the spanning fraction at 0.00-0.08 and the split fired at every angle. Two degrees is well
  past what a scanner introduces, so the mechanism that prompted this check is not a risk in the
  range that occurs.

  **The first sample was wrong and the negative results are worth keeping.** Three other real scans
  (an IRE monograph, Scientific American Supplement 1890, a declassified typescript) all measured
  +0.000, which read as "inert on real scans" until the pages were actually looked at: the monograph
  is single-column, the typescript is single-column, and the 1890 magazine is THREE-column. Leaving
  all three untouched is the correct behaviour — a three-column page puts its middle column across
  the centre and so declines itself by the same arithmetic that recognises a single-column page. The
  reading was assumed from the journal's name; rendering one page to an image settled it in seconds.

  **Noted in passing, and now evidenced rather than theoretical**: that IRE scan's own embedded text
  layer is garbage on some pages (`'‘ \r\n“ i \r\nsi - a \r\nal 2 yt 7 wo'`). `_MIN_TEXT_CHARS = 1`
  sees characters, declines to run OCR, and that string is what would reach the corpus — the
  garbled-but-present text layer invariant 7 records as an open gap, in a document anyone could
  ingest today. *(Later in this same section: invariant 74 narrows that gap but does not close it,
  and this particular string is one it still misses — four Latin tokens is under the scoring floor,
  so the layer is never challenged. The entry below states the limit.)*

- **Rejected: `PaddlePaddle/PicoDet-S_layout_3cls` as a shipped default.** Evaluated after the
  OCR reading-order defect above was suspected, since a layout model is the textbook answer to it.
  Licensing was NOT the problem — Apache-2.0 on the model card and in the Hugging Face repo
  metadata, the same footing as RapidOCR and Tesseract, with none of the AGPL/Artifex trouble that
  removed `pymupdf` (invariant 7).

  **It detects table, image and stamp — there is no text class**, so it cannot recover reading
  order, columns or headings, which is the one thing that was actually broken. The same PicoDet-S
  backbone ships as `PicoDet-S_layout_17cls` at the SAME 4.8 MB and the same ~17.5 ms CPU latency
  (mAP 87.4 vs 88.2) with 17 categories including Text, Paragraph Title, Header and Footer — so
  within one model family the 3cls checkpoint is the least useful one available at that size.

  **The published checkpoint is Paddle's own inference format** (`inference.pdiparams` +
  `inference.json`, 4.8 MB), not ONNX: running it as documented needs `paddlepaddle` — measured at
  **104.5 MB for the macOS arm64 wheel and 194.8 MB for manylinux x86_64** — plus `paddleocr`, next
  to an OCR stack that is entirely ONNX today. An ONNX detour exists (`rapid-layout`, Apache-2.0,
  reusing the `onnxruntime`/`numpy`/`opencv`/`Pillow` this project already installs), so the runtime
  cost is avoidable, but only by taking the weights from somewhere other than this repo.

  **Nothing in the schema could consume the output either**: `SourceBlock` is text-only at
  `page:<n>` granularity, and a table bounding box is useless without a table-structure model
  (SLANet) behind it — that is PP-StructureV3, not one small model. **One objection was measured and
  withdrawn**: rasterising every page to feed a detector was assumed expensive, but 12-15 pages at
  2x measured 0.13-0.19s, the same order as text extraction.

  **If layout detection is revisited**, the checkpoint is `PicoDet-S_layout_17cls` or PP-DocLayout-S
  (4.83 MB, 23 categories), packaged as ONNX, and opt-in first per invariant 43's "installed and run
  before adopted" bar. Its remaining value is narrow: dropping figure-internal label noise from OCR
  text, which is what survives the geometric fix above.

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
  (the web-UI blueprint, gitignored, same convention as `docs/research/`). The audit
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
  (the web-UI blueprint's Phase 2 addendum) before any code was written. Found 2
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

- **Fourteenth slice: durable notebook writes + trace retention.** Not a feature — the one known
  defect in this project that silently LOSES a user's data, fixed at the root, plus the retention
  policy `traces/` had never had. Chosen over the remaining feature backlog deliberately: shipping
  more features on top of a store that can silently drop writes compounds the risk.

  **The defect was reproduced live over real HTTP against a real `uvicorn` server BEFORE anything
  was designed, and it is materially worse than what invariant 31 had recorded.** That entry
  described a race between two concurrent `POST /sources` calls — millisecond-wide, needing two
  browser tabs or a load test to hit. The actual reproduction needed no concurrency trickery at
  all: ask a question, and while the model works (which is exactly when a person has time to do
  something else) add a source and save a note from the panels the web UI leaves fully enabled
  during a run — `app.js`'s `pending` state gates only the Chat composer. Both writes returned 200.
  Both were gone the moment the answer was saved. `api.ask` held its notebook snapshot across the
  WHOLE run (up to `RN_RUN_TIMEOUT_SECONDS`, 300s by default) and wrote it back whole;
  `add_sources`/`upload_source` held theirs across ingestion (network fetch, PDF+OCR, YouTube
  captions).

  **Two faults, and the fix needs both halves.** A stale snapshot (the handler mutates an object it
  read minutes ago) and interleaved critical sections. A lock ALONE would not have prevented the
  reproduction above, because the two writes never overlapped in the file-writing instant — which
  is why `notebook.mutate_notebook` re-loads the file from disk INSIDE the lock and applies a
  caller-supplied DELTA. Its closure never sees the caller's snapshot, so "write back the object I
  built earlier" is not expressible. Every mutating path became: expensive work unlocked against a
  snapshot → `mutate_notebook` with the delta. Critical sections are now bounded by a JSON load
  plus a JSON write. Full account in CLAUDE.md invariant 34.

  **`extend_with_sources` was DELETED, not kept alongside its replacement pair** (`ingest_sources_for`
  + `append_sources`). Ingesting and appending in one breath is precisely what forces a caller to
  hold a snapshot across ingestion, so leaving it available would let a later caller silently
  reintroduce the bug. `save_notebook` now has exactly one caller in the whole package.

  **`fcntl.flock`, not `fcntl.lockf`, and both load-bearing properties verified with a probe rather
  than assumed**: `flock` locks attach to the open file description, so ONE mechanism serializes
  two threads of a `uvicorn` server as well as two processes (POSIX record locks are per-process —
  two threads would pass straight through each other), and it releases the GIL while blocked. The
  cross-process guarantee has its own test that spawns a REAL second process and times how long the
  parent blocks, the same discipline `test_runner.py`'s real-grandchild cancellation test already
  applies. POSIX-only, stated rather than papered over: without `fcntl` it degrades to a
  process-local `threading.Lock`.

  **Four real problems found by this slice's own pre-implementation audit, all fixed before any
  code was written.** (1) Building the prune's protected set inside a worker thread races the event
  loop's own mutation of `_RUN_PROCESSES` — `RuntimeError: dictionary changed size during
  iteration`, raised from a `finally` on an otherwise successful request; the snapshot is taken on
  the loop instead. (2) `ask` persisting with `create=False` would have thrown away an
  already-generated, already-paid-for answer if the notebook file vanished mid-run — the same
  "never discard work that already succeeded" reasoning invariant 19 applies to a TTS failure after
  a transcript exists. (3) Six handlers each hand-writing invariant 27's `ValueError`/
  `ValidationError`/`FileNotFoundError` mapping is exactly the drift that produced invariant 27 in
  the first place — one shared `_mutate_or_http` instead, which also validates the notebook id
  BEFORE the thread so `notebook_path`'s invalid-id `ValueError` can't be confused with
  `delete_note`'s same-typed "no such note" one (that confusion would report a missing note as
  "invalid notebook id"). (4) `cli._prepare` returning its own snapshot rather than the notebook
  `mutate_notebook` produced would have made every citation in a CLI run silently wrong —
  `append_sources` renumbers ids against the fresh notebook, so the model would cite `s2` for a
  source persisted as `s4`. The audit also checked whether the API's `ask` had the same exposure
  and found it does not (its snapshot holds only already-persisted sources, whose ids are never
  renumbered) — checked rather than assumed equivalent.

  **One intended behavior change**: `cli._prepare` now persists freshly ingested sources
  immediately, before the model runs, so a run that fails or is Ctrl+C'd partway no longer discards
  ingestion the user already paid for in OCR or network time. `_cmd_guide`/`_cmd_audio`'s trailing
  `save_notebook` calls existed only for that ingestion and are gone.

  **Trace retention (`traces.py`, new)** — `traces/{run_id}.jsonl` no longer accumulates forever.
  These are the one artifact here that can hold FULL ingested source text (the model echoes corpus
  spans into its REPL output while reading), in front of an API with no authentication. Sweeps by
  age (`RN_TRACE_RETENTION_DAYS`, default 7) and count (`RN_MAX_TRACE_FILES`, default 500), `0`
  disabling either, at startup and after every run. Two rules outrank both sweeps: an in-flight run
  id, and any file younger than a one-hour floor — **deleting a live run's trace wouldn't just
  break its SSE stream, it would free a run id `_run_isolated`'s exclusive-create collision gate
  (invariant 29) is still relying on being taken**, letting a second request append into the same
  file. The floor covers what the protected set cannot: the window between that exclusive create
  and the `_RUN_PROCESSES` registration a few lines later, and a just-finished run whose trace is
  exactly what the answer now on screen links to. Consequence stated rather than hidden: the count
  cap is a SOFT cap under a burst of runs.

  **`prune_traces` never raises, so the lifespan validates the settings itself.** Housekeeping in a
  `finally` must not turn a completed, paid-for `ask` into a 500 — but that same defensiveness
  would make a typo'd `RN_TRACE_RETENTION_DAYS` mean "silently never prune." Split: the per-run
  sweep stays defensive, and startup reads the values directly so a malformed one refuses to boot,
  matching what `config.py` already does for every other bad `RN_*` value. Verified against a real
  `uvicorn` server ("Application startup failed. Exiting.", nonzero exit) — the test drives the
  lifespan directly rather than through `TestClient`, whose anyio portal re-raises a startup
  failure wrapped in a `BaseExceptionGroup`; asserting on that would pin TestClient's wrapping
  rather than this project's behavior.

  **Three independent reviews (concurrency, security, test-quality) then found five more real
  problems, all fixed before merge.** The concurrency pass came back clean on its own axis.

  **A destructive sink with no ownership check (security, MEDIUM).** `_TRACE_DIR` is a bare
  relative `Path("traces")` resolved against whatever directory the server was started in, and
  this project's siblings all write `.jsonl` traces of their own — the review reproduced a
  co-located directory belonging to ANOTHER tool being emptied at server startup, on nothing but a
  filename glob and an mtime. Age and the protected set bound only WHEN a file dies, never WHOSE
  it is. Fixed with `traces._is_ours` (first line must parse as JSON carrying `rlm_harness.trace`'s
  schema marker, or the file must be empty — the abandoned `O_CREAT|O_EXCL` reservation case, which
  still has to stay collectable), plus logging of what each sweep removed; the first version
  discarded `prune_traces`'s return value entirely, so the one destructive operation in this
  project was also silent. Re-verified live against a real server with a mixed directory.

  **The count cap did the opposite of its own docstring (security, LOW but real).** It charged
  protected and too-young files against the cap while drawing every deletion from the eligible
  ones, so N concurrent runs — a client-influenceable number, since `_run_isolated` reserves the
  trace file before spawning — could force well-within-retention traces to be deleted early.
  Retention days was a function of load rather than a floor. Fixed so the cap governs how many
  PRUNABLE traces are kept, matching what the docstring already claimed. One of this slice's own
  tests had pinned the WRONG behavior and was rewritten.

  **404s left permanent lock files (security, LOW).** Entering `notebook_lock` creates its sidecar
  file, so every unauthenticated `DELETE /notebooks/<anything>/notes/n1` left a zero-byte file
  behind for a notebook that never existed — 503 requests, 503 files, invisible to
  `list_notebook_summaries`. Fixed by checking the `create=False` miss before taking the lock as
  well as inside it. Re-verified live: 100 such requests now leave zero files.

  **The entire CLI half of the fix had no test coverage (test-quality).** The review proved it by
  restoring the exact pre-slice defect in `cli._cmd_ask` and watching all 321 tests still pass.
  Four CLI regression tests added, each verified by mutation to actually fail on the code it
  guards. One of them failed that check on its first draft — it wrote concurrently BEFORE
  `_prepare` ran, where snapshot and fresh notebook are identical, so it passed against the very
  defect it was named for; rewritten to inject the write DURING ingestion, the only window where
  the two disagree.

  **Two hollow trace tests (test-quality).** Both were named for the young-file floor and both
  passed with the floor removed from `prune_traces` entirely: one file against a cap of one is AT
  the cap, not over it, so nothing was ever eligible. Rewritten to two files against a cap of one,
  and confirmed to fail without the floor. A third gap — `api._prune_traces` passing the real
  `_RUN_PROCESSES` keys rather than an empty set — had no coverage at all and now does.

  **Verification**: 329 tests pass (from 291), `uvx ruff@0.16.0 check .` clean. Every fix above was
  mutation-tested in a scratch copy (never the working tree) to confirm its test fails on the
  unfixed code. Both original live reproductions re-run after the fix — the single-user sequence
  (all writes now survive) and a cross-process one where a SEPARATE OS PROCESS writes the same
  notebook while a real server is mid-`ask`, which only `flock` covers.

  **Deliberately NOT in this slice**: a merging write (needs conflict semantics that lock +
  re-read makes unnecessary), a multi-worker `uvicorn` story for `_ACTIVE_RUNS`/`_RUN_PROCESSES`
  (the notebook FILE is now safe across processes; those in-memory maps still are not), any
  retention policy for `notebooks/` itself, and every remaining feature-backlog item (Guide/Audio
  artifacts as citable sources, Word/Slides/Docs parsing, full audio transcription).

- **Fifteenth slice: run on a Claude subscription instead of an API key — and this project's FIRST
  real live run.** Prompted by trying to actually start the thing: it turned out nothing here had
  ever been exercised against a real model. Every slice to date was verified offline or against a
  mocked runner.

  **`claude-agent-sdk/<id>` as a model-string sentinel** (`config.SUBSCRIPTION_PREFIX`) routes that
  role onto the user's Claude Pro/Max subscription through rlm-harness's `ClaudeAgentLM`. The
  crucial detail, confirmed by reading `rlm_harness/runtime.py` rather than assumed: **`configure`
  does NOT route on the prefix.** It calls `dspy.LM(cfg.main_model)` unconditionally for any seat
  left unsupplied, so the sentinel alone reaches litellm as a nonexistent provider — it works only
  because `config.setup` injects a pre-built LM through the public `main_lm=`/`sub_lm=` seam.
  Because `worker.py` calls the same `setup`, one change covers both the CLI's in-process path and
  the API's isolated subprocess.

  **Copied from the sibling `cve-reverser`, which shipped this pattern first** — same sentinel,
  same placement of the constant in the dspy-free config module, same lazy import of the adapter
  inside the sentinel branch only (so an API-key-only install never touches the optional SDK), same
  `subscription` extra MIRRORED as a `subscription-sdk` dev group under `[tool.uv] default-groups`.
  That mirror is not redundancy: an extra is not synced by default, so a bare `uv sync` prunes the
  SDK back out and the next subscription run dies with an `ImportError` nobody caused. Deliberately
  not re-invented in a second spelling.

  **One deliberate divergence from cve-reverser, pinned by a test**: an unset `RN_SUB_MODEL`
  inheriting the sentinel from `RN_MAIN_MODEL` is a HAZARD there (its generator is a separate tool
  that must stay on its own endpoint) and simply correct here, since this project has no such role.

  **First live evidence for invariants 4 and 11**, both of which had carried an explicit "residual
  risk, not yet verified" note since the first slice — the offline tests drive a scripted LM, which
  proves the tool-wiring, never that a real model behaves. A real model copied a `[[SRC:s1|whole]]`
  marker verbatim out of the corpus blob and `citations.py` verified it; a follow-up turn that
  needed `history` to resolve "those two launches" still re-derived its citation from `sources` and
  verified independently. It also answered a deliberately planted trap correctly (Voyager 2 launched
  first despite the name), so it was reading the corpus rather than reciting general knowledge. One
  run is evidence, not proof — the invariants' notes are updated, not deleted.

  **A real product defect this surfaced, recorded but NOT fixed here**: an authentication failure
  reaches the client as `RLMTaskError: Failed to produce a valid 'answer' after 1 attempts` —
  indistinguishable from a model that genuinely failed to produce valid output — and the trace file
  records only that same string, because `rlm_harness._retry` wraps the cause with `raise ... from`
  and the `__cause__` never reaches `TraceRecorder`. Diagnosing it required abandoning the API and
  re-running through the CLI to see a traceback, a route no browser user has. Surfacing the cause
  in the trace, and separating "misconfigured" from "the model failed", is its own follow-up.

- **Web UI: two real bugs found by opening the page, both fixed.** Neither was reachable by any
  test this project had.

  **The entire UI was dead from the first paint.** `.modal-overlay { display: flex }` outranks the
  UA stylesheet's `[hidden] { display: none }` — author styles beat UA styles regardless of
  specificity — so the source-viewer overlay was permanently visible, and with `inset: 0` and
  `z-index: 1000` it swallowed every click on the page. The ✕ looked unclickable because closing
  set an attribute that no longer changed anything. Shipped this way in the source-viewer slice.
  Fixed with the `.modal-overlay[hidden]` rule that must accompany any such `display` declaration.

  **The same defect had a SECOND instance, and the first fix shipped with a false justification.**
  `.ticker-detail` carried the identical `display: flex`-without-`[hidden]` bug from Phase 3,
  leaving the reasoning-step log permanently expanded with a dead `⌁ N steps` pill — and the
  `.modal-overlay` fix argued that a citation detail should toggle "because the ticker already
  does", which it never did. An independent review caught the missed instance and the claim built
  on it. Both are fixed; the tripwire below now keys on CSS classes so it can see elements built
  with `createElement`, and asserts up front that it still detects both known instances.

  **A re-click on an open citation detail now collapses it** instead of blanking the panel to
  "Loading…" and re-fetching the identical payload, which read as a flash with nothing ever
  closing. Keyed on which citation is shown — including its `quote`, since text and web sources all
  use locator `"whole"` and `source_id|locator` alone would make clicking a second citation into
  the same source CLOSE the panel rather than switch. Collapsing bumps the staleness token so an
  in-flight response cannot repopulate a panel the user just closed.

  **`tests/test_web_assets.py`** (new) asserts on the SOURCE TREE, because the stylesheet bug is
  invisible to every layer otherwise testable here: the Python suite never renders a page, and a
  unit test of `closeSourceViewer()` would have passed against the broken stylesheet — the JS was
  always correct. **Its first version was itself reviewed and found badly wrong**, every fault the
  same shape — it only looked at what was easy to parse. It harvested ids from `index.html` only,
  so it could not see either `createElement`-built element, including the one carrying a live
  unfixed instance of the very bug it claimed to prevent; it matched `X.hidden` by bare variable
  name, giving three confirmed false positives waiting on the next styling change; and its
  comment-stripping never ran, because a `{` inside a CSS comment splits that comment across two
  regex blocks. Rewritten to key on CSS CLASSES — the axis the hazard lives on, spelled identically
  by the markup and the JS. Both instances are now mutation-verified, the demonstrated false
  positive no longer fires, and the `innerHTML` check covers its `outerHTML`/`insertAdjacentHTML`/
  `document.write` siblings too. **Stated gap**: there is no JavaScript test runner here at all (zero-build
  vanilla JS, by design), so interactive UI state — a toggle that stops toggling — still has no
  test seam. A source-tree assertion cannot reach it.

- **Sixteenth slice: a notebook names itself.** The web UI refused to add a source until the user
  had invented a notebook id (`Open or name a notebook first`), which made the very first
  interaction with this product a naming puzzle about a thing that did not exist yet. I deferred
  this once as "its own slice"; the user pushed back, correctly — the blocker was never that the
  naming was unsophisticated, it was that naming was mandatory at all.

  **`id` and `title` are now two fields.** The id is a handle the UI mints itself
  (`nb-<uuid8>`), and it still backs every filename, `ChatTurn.run_id` prefix and URL, so it has to
  stay stable. `schema.Notebook.title` is the label a person reads and is free to be anything —
  which is exactly why splitting them beats renaming a notebook (which would move its file and
  invalidate its run ids). Optional, defaulting to `None`, so older notebooks still load.

  **`naming.SuggestTitle` is deliberately not an `RLMTask`**: a full REPL loop in the pyodide
  sandbox is right for exploring a multi-MB corpus with verifiable citations and absurd for five
  words. It is one plain `dspy.Predict` over a 4000-character excerpt — ~8s live, versus a sandbox
  boot plus planner turns. It still runs in the API's isolated subprocess, so invariant 21 is
  untouched: `worker.py` only calls `.arun(**kwargs)`, so satisfying that one method is the whole
  contract and `api.py` still imports neither `dspy` nor `rlm_harness`.

  **A title never costs the user their source.** `POST /notebooks/{id}/title` is separate from
  `add_sources` (ingestion must not wait on, or fail because of, a model call), fired on the first
  source only, and every failure path falls back to a deterministic title derived from the origins.
  An existing title is never overwritten.

  Verified live end to end with no name ever typed: an English source titled itself
  `Voyager 1 Interstellar Mission`, a Chinese one `蜜蜂的偏振光導航` (the prompt asks for the
  sources' own language), and the fallbacks were exercised directly.

- **Seventeenth slice: a "generate overview" action, in the conversation.** A user asked where the
  Gemini-style "produce the research artifact, then ask follow-ups from it" moment was. The
  functionality existed — Studio's Summary/FAQ/Timeline/Insight tabs — but adding a source left the
  screen doing nothing: Chat said "ask a question once you've added a source", Studio said "pick a
  tab to generate it", and both waited on the user to discover the next move. Even finding the
  Summary led nowhere, because it renders in a right-hand tab disconnected from the thread.

  `#chat-overview` sits above the chat history and holds either a primary `✨ Generate overview`
  button or the generated artifact: the Summary rendered through the SAME
  `renderAnswerWithCitations` a Chat answer uses (so its citations, source viewer and trace links
  all behave identically), then up to three clickable starter questions from the FAQ task. **No
  server-side change at all** — both endpoints already existed.

  **Still an explicit button, never auto-generated on open**: Phase 2's reasoning (a guide run is a
  real RLM loop; never spend one nobody asked for) is unchanged. What changed is that the action is
  obvious instead of hidden behind a tab. Summary and FAQ run CONCURRENTLY — two independent runs,
  so serial execution would double the wait for nothing (measured 34s live, against ~30s for one).
  FAQ is reused rather than adding a cheap ungrounded question generator: its questions are already
  grounded by a task that exists, and starter questions gesturing at something the sources don't
  cover would be worse than none. `allSettled`, so an FAQ failure never costs the user the summary.

  **An independent review found 8 problems in the first version, all fixed.** The worst was
  self-inflicted and 100% reproducible: the client sent a bare UUID as `run_id` and then used that
  bare value locally, but the server derives `{notebook_id}-{token}` and both trace endpoints reject
  anything without the prefix — so every citation's "view reasoning" in the overview 404'd. The
  shape was copied from `suggestTitle`, where a bare token is correct precisely because it is never
  used client-side. Verified after the fix by hitting both trace endpoints with each shape: old
  → 404, new → 200. Also fixed: a trace affordance rendering a dead "⌁ 0 steps" because
  `openTicker` was never called; starter chips bypassing the `chat:pending` lockout via
  `requestSubmit()` (which submits as if by the form, so a disabled submit button never blocks it)
  and producing two pending turns, one of which visibly vanished; the overview never being
  invalidated when the corpus changed, unlike the Studio cache next to it; no per-request guard, so
  two concurrent generations raced last-writer-wins; an unbounded flex item that would collapse the
  chat history and push the ask box off screen; and a silent FAQ failure. The button also moved out
  of `#chat-empty` — `chat:turnAdded` hides that node, so it vanished after the first question and
  was permanently unreachable for any notebook that already had turns, which is exactly the set most
  likely to want one.

- **The overview can be saved as a note — closing the loop this project already had every piece
  of.** Prompted by a direct question: does NotebookLM persist its overview? It does, and the
  mechanism is not a special one — its generated artifacts BECOME notes, which is how they survive
  at all. This project has had `Note`, `promote_note` and note-to-citable-source since the eleventh
  slice; the overview simply had no way in.

  `saveAsNoteButton` is a factory two call sites opt into (`renderTurn` and `generateOverview`),
  NOT a line inside `renderAnswerWithCitations` — the restriction invariant 32 records still holds,
  but its stated REASON was wrong. "Generated output is not something a user curates into notes" is
  contradicted by the product being chased; the line that actually holds is about the surface:
  things rendered IN the chat thread are the user's to curate, a Studio tab's artifact and a
  podcast transcript are not part of that thread.

  Verified live end to end: overview -> note -> promote -> a new source that later questions can
  cite. A toy source whose summary restated it verbatim instead hit the documented dedup no-op,
  which is the correct behaviour and worth having seen.

- **Eighteenth slice: the overview persists, and goes stale instead of vanishing.** A user
  re-opened a notebook holding a full conversation and still saw the first-run `✨ Generate
  overview` button. The overview had never been persisted — it lived as a flag on a DOM node — so
  every notebook opened in the "never generated" state. The second half was worse: adding a source
  DELETED the overview and reverted to that same button, making "never generated" and "generated
  but the sources moved since" render identically, and confiscating an artifact that cost a real
  RLM run.

  `schema.Overview` on `Notebook.overview` (optional, so old files still load), with the source ids
  it was computed from as the staleness key — a comparison, not a timestamp. Three states, and the
  stale one KEEPS the overview on screen with a marker plus `↻ Regenerate`, because it is still
  true about the sources it was computed from. A deliberately narrow cut of the long-deferred
  "guide artifacts aren't cached" item: the overview only, never the four Studio tabs.

  Generation moved server-side (`POST /notebooks/{id}/overview`, running Summary and FAQ
  concurrently), not because of provenance but because closing the tab between a client-side
  generate and a store call would lose a paid-for run.

  **A pre-implementation audit found 2 blockers and 6 should-fixes, all folded in before any code
  was written** — both blockers were cases where the natural implementation is silently wrong.
  Building the `Overview` inside the `mutate_notebook` closure would have captured the source ids
  at PERSIST time, claiming coverage of a source the model never read. And forming
  `<token>-summary` before slugging breaks twice: an absent `run_id` yields the literal
  deterministic `None-summary`, so the first anonymous request wins the exclusive-create gate and
  every later one 409s for as long as retention keeps the trace; and `slug`'s 120-char cap merges
  the two suffixes for a long token (`slug("a"*119 + "-summary") == slug("a"*119 + "-faq")`,
  verified). Both fixes are mutation-tested.

  The audit also caught a PRE-EXISTING bug it would have made permanent: `stream_run` and
  `citation_turn` compared the RAW notebook id against a run id `_derive_run_id` had slugged, so
  every trace link was dead for `"my notebook"` or any non-Latin id (invariant 10). Harmless while
  the affordance was ephemeral; a dead link on the front page once `Overview.run_id` persists.

  Verified live end to end: generate → reload (survives, `stale: false`) → add a source (still
  there, `stale: true`) → trace link still 200. Plus both blockers checked directly: two anonymous
  requests in a row both 200 with distinct run ids, and a 121-character token no longer collapses
  its two run ids into one.

- **Nineteenth slice: output language.** Every model-authored string came out in the SOURCES'
  language, so a Traditional-Chinese reader feeding in English papers got an English notebook. The
  language you read should not be decided by the documents you happen to be reading.

  **The carve-out turned out to be the load-bearing half.** `verify_citations` compares `locator`
  with an exact `==` and never inspects `quote` at all, so a model told "write everything in
  Chinese" that localises `page:1` to `第1頁` makes every citation UNVERIFIED, and one that
  translates a quote leaves a ✓ badge on something that is no longer the source's words. The design
  named only `quote`; the pre-implementation audit caught that and the rule now covers `source_id`,
  `locator`, the marker syntax and `quote` together, composed BEFORE the citation rules.
  `CITATION_RULES` also gained the "a quote is copied verbatim" sentence it had never contained, and
  `schema.py`'s "faithful summary" wording that muddied it is fixed.

  **The resolution is a model judgement, not a header lookup — and a sibling project
  already paid for the alternative.** Its ASR seeded itself from `Locale.current`, which answers
  "what language should this app's UI be in" while ASR was asking "what language is this person
  speaking", and transcribed Chinese speech as syllable-by-syllable English gibberish.
  `Accept-Language` is the same shape of wrong question. `naming.SuggestLanguage` (a cheap
  `dspy.Predict`, not an RLMTask) weighs the header, the sources' language, and any questions
  already asked, with questions weighted highest. Two more of a sibling project's lessons applied directly: a
  ladder cannot correct its own input, and an instrument that cannot reproduce production's shape is
  not evidence — so the live check sends the `Accept-Language` a real browser sends.

  `RN_OUTPUT_LANGUAGE` is a hard override and applies to CHAT too. The value reaches a task as a
  signature field and is never empty: instructions are composed at import time, so "a signature
  field" and "byte-identical prompts when unset" were a contradiction in the design, resolved with a
  literal default.

  **The Audio Overview is deliberately excluded, as a stated scope cut.** `tts.py` maps no language
  to a voice, so a forced-Chinese notebook would produce a correct Chinese script read by the en-US
  default cast — quietly breaking invariant 15. A tripwire asserts the podcast task does NOT declare
  the field (so the exclusion stays deliberate) and every other grounded task does, because a
  missing required input surfaces only as the opaque `RLMTaskError` while an undeclared extra kwarg
  is silently accepted — a partial rollout fails silently in both directions.

  The audit found 4 blockers and 8 should-fixes before any code was written, including two run-id
  collisions: sharing the artifact's derived id 409s on the exclusive-create gate, and `/overview`
  gathering two runs would have fired two concurrent resolutions deriving the same `-lang` id.

  **Verified live, both paths**, since the offline tests drive a scripted LM and can demonstrate
  none of it: forced Chinese against English sources gave Chinese prose with `s1`/`whole`
  untranslated, English quotes verbatim, every citation verified; and with the override unset,
  `Accept-Language: zh-TW` against the same English sources resolved to "Traditional Chinese",
  persisted it, and did not re-resolve for the next artifact.

- **Twentieth slice: language-aware default voices — the podcast rejoins the language story.**
  The previous slice excluded the Audio Overview as a stated scope cut; this closes it.

  **The gap was never "edge-tts is the wrong TTS".** Nothing in this project mapped a language to a
  voice: `voice_map` came straight from `RN_TTS_VOICE_HOST_A`/`_B` and `synthesize` spoke whatever
  it was handed. Every provider would have had the same hole, so swapping providers would not have
  fixed it — a correct Chinese script read by the en-US default cast is a routing bug, not a
  synthesis one.

  `tts.default_voices_for` maps a language to a voice pair, matching loosely because the value
  arrives either as a model-authored name ("Traditional Chinese") or as whatever an operator typed
  ("zh-TW"), with a BCP-47 tag falling back to its primary subtag. **Every voice id was read out of
  a real `edge_tts.list_voices()` response rather than written from memory** — a plausible-looking
  but nonexistent id fails only at synthesis time, after a real model call has already been spent on
  the script, exactly the waste invariant 19 exists to prevent.

  An explicitly set env voice beats the language default, read from the RAW environment rather than
  by comparing against the default value: setting `RN_TTS_VOICE_HOST_A=en-US-GuyNeural` on a Chinese
  notebook is a choice, and an equality check would overrule it. The two resolve independently.

  **The previous slice's tripwire earned itself immediately.** It pinned that
  `GeneratePodcastScript` did NOT declare `output_language`, so adding the field failed the test
  rather than letting a stated scope cut erode unnoticed — the exclusion had to be un-made
  deliberately.

  Verified live end to end: an English source in a forced-Chinese notebook produced a Chinese
  two-host script and synthesized it with the zh-TW cast into a valid 203KB MP3.

- **A download link on the podcast player.** A user asked where the generated mp3 was. Nowhere —
  by design: the server writes a temp file and unlinks it in a `finally`, so the episode exists only
  as the browser tab's `Blob` and a reload loses it. `<audio controls>` exposes a download in some
  browsers' overflow menu, which is neither discoverable nor uniform. An explicit `↓ Download mp3`
  now sits beside the player, sharing the player's object URL so the existing
  assign-new-then-revoke-old ordering keeps both valid together. The filename is slugged from the
  notebook title rather than interpolated — `download` is an attribute the browser turns into a path
  component, and that title is model-authored.

- **Twenty-first slice: a settings page — presentation settings only.** The user picked this shape
  after three were put on the table, and the reason is not preference: this API has no
  authentication (invariant 25) and today holds NO secrets, so a page that persisted API keys
  server-side would let anyone who can reach the server read or spend them.

  **"Non-secret" turned out to be the wrong filter.** Two candidates are levers an unauthenticated
  caller does not have today: lowering `RN_TRACE_RETENTION_DAYS` DELETES trace files that can hold
  ingested source text, and raising `RN_MAX_UPLOAD_BYTES` is a straight DoS lever. Moving a safety
  BOUND onto an unauthenticated page is the same mistake as moving a key there, just quieter. So the
  page carries the output language and the two podcast voices, and nothing else. `RN_BASE_URL` is
  the sharpest exclusion: `config.setup` hands it to `rlm_harness.configure` alongside `api_key`, so
  a writable base_url exfiltrates the key on the next run without anyone ever reading it.

  A pre-implementation audit found 4 blockers. The language ladder has FOUR rungs, not the two the
  design named — a one-line "read the file too" would have silently made a browser-typed language a
  hard override over every notebook's persisted resolution, in the CLI as well, with no test
  failing. The TTS provider is a `NotebookConfig` field, so reporting it needs `_config()`, which
  raises `SystemExit` → 500 when `RN_MAIN_MODEL` is unset — on the one page an operator opens when
  the server is misconfigured; it was cut from the slice. The voice ladder's position was undefined
  against invariant 40. And both proposed file locations were wrong: a repo-root `settings.json` is
  not gitignored, and `pathlib`'s `*.json` glob matches dotfiles, so `notebooks/.settings.json`
  would have been reported as a corrupt notebook.

  **A live check then caught a bug the tests had missed.** Pydantic DROPS unknown keys before the
  handler's validator sees them, and combined with full-replacement semantics a request carrying
  only a typo'd key silently WIPED every setting — while a test asserting "nothing outside the three
  settings is persisted" passed. Fixed with `extra="forbid"`, and the regression is mutation-tested.

  That same live check left a settings file in the working directory and turned an unrelated TTS
  test red, because every path here resolves against the process CWD. Rather than delete the file,
  `tests/conftest.py` now isolates every test into its own directory — a developer's local state
  silently changing a test result is the same class a sibling project's ASR locale design records.

- **Twenty-second slice: the Audio Overview persists and plays from the page.** Phase 2 deliberately
  kept no audio past one request — no file-serving endpoint, no retention to get right — and it cost
  the user their episode on every reload, since it existed only as the browser tab's `Blob`. Reported
  after they asked where the mp3 was.

  One mp3 per notebook (`notebooks/audio/<slug>.mp3`), replaced on regenerate, which is what makes
  retention a non-question: growth is bounded by how many notebooks exist, not by how many times
  anyone pressed the button — unlike `traces/`, which needed a whole sweep. The transcript persists
  on the notebook; the audio does NOT go in the JSON, because a multi-MB base64 blob would be
  re-parsed on every read of that notebook. `GET .../audio/file` serves it instead, which also lets
  the browser range-request it — verified live: a `Range` header returns `206 Partial Content`.

  The audio is written BEFORE the notebook record, so a crash between the two leaves an orphan file
  (harmless — overwritten on the next generate) rather than a notebook pointing at audio that isn't
  there. Same staleness treatment as the overview, citations re-verified on every read, and ONE
  `renderPodcast` serving both the just-generated and the reopened case so a persisted episode can
  never render differently from a fresh one.

  **Two features had shipped completely inert, found while investigating this.** `initSettings()`
  and `initNotebookTitle()` were never called: a scripted edit's anchor didn't match the file's
  actual indentation and `str.replace` silently did nothing. So the settings button was dead on
  click and the header's notebook title had NEVER displayed since it was added. Nothing else could
  catch it — there is no JavaScript test runner, and a defined-but-uncalled function is valid JS —
  so `tests/test_web_assets.py` now fails the build on any `init*()` that is defined and never
  called. Mutation-tested. The settings icon also reused `.theme-toggle`, whose `margin-left: auto`
  then applied to two elements at once; one `.header-actions` wrapper owns the push-right now.

- **Twenty-third slice: a fully local TTS provider.** `RN_TTS_PROVIDER=kokoro` (the `kokoro`
  extra) synthesizes with no network call at all — no API key, and none of the undocumented-endpoint
  grey area `edge-tts` operates in with its hardcoded client token.

  **Two recommendations were wrong before this one, both from unverified sources.** NeuTTS: no CJK,
  which is the language the whole output-language work exists for. Qwen3-TTS: recommended from a
  blog summary claiming CPU inference, but the repository documents `device_map="cuda:0"` and never
  mentions CPU — it would not run on the machine this project is developed on. (Its licence claim
  did hold up on checking the HF model card, but I had asserted it before looking.) Kokoro was
  chosen only after being installed and RUN: Apache-2.0, ~82M parameters, 17.4s one-time load then
  4.4s for 8.9s of Mandarin on CPU.

  **A `TTSProvider` now owns its output FORMAT and its own language→voice map.** A voice name is
  provider-specific — `zh-TW-YunJheNeural` versus `zf_xiaobei` — so one shared map would have leaked
  one provider's names into the other's request. Kokoro emits 24kHz WAV, and forcing it through an
  MP3 encoder would drag in the ffmpeg/pydub dependency invariant 17 refused. Handled rather than
  assumed: `find_audio` looks for whichever format is present (switching providers must not orphan
  an existing episode), `clear_audio` removes every format before a regenerate, and the file
  endpoint derives its media type from the file rather than the configured provider.

  An EXTRA, never core: 87 packages including torch, transformers and spacy (measured with
  `--dry-run`), plus weights on first use. Invariant 15's "works out of the box" rests on the
  DEFAULT provider needing neither a key nor a download.

  Verified end to end through the real product: a 14-turn Chinese episode generated with no network
  TTS call, written as `notebooks/audio/<slug>.wav` (2m53s, 24kHz), the previous `.mp3` removed, and
  served as `audio/wav` with range support.

- **A code-vs-docs consistency audit across all sixteen commits, and one real bug it found.**
  Requested after several slices had gone through pre-implementation design audits but no
  post-implementation review. It found 7 blockers, 10 should-fixes and a page of nits.

  **The bug: a persisted podcast never rendered on notebook open** — the entire point of persisting
  it. `initPodcastPlayer` registered two `notebook:switched` handlers, and `store.emit` runs them in
  registration order, so the later `clearPlayer` blanked the panel the first had just filled. The
  invariant claiming "one `renderPodcast` serving both the just-generated and the reopened case"
  was therefore false in practice. `tests/test_web_assets.py` now fails the build on two
  subscriptions to the same event inside one `init*` function; mutation-tested.

  **One invariant was simply FALSE, and verified false**: invariant 21 claimed `api.py` never
  imports `dspy`/`rlm_harness`. It does, transitively, through the task classes it imports for
  `_dotted()`'s introspection — `import rlm_notebook.api` loads both. The guarantee that actually
  holds is about EXECUTION (no `RLMTask` is ever run in the API process), and it now says so.

  **"No audio is ever persisted" survived in three places** after the previous slice reversed it —
  `api.py`'s module docstring (which is also the OpenAPI description), README, and a paragraph of
  invariant 29 whose neighbouring paragraph HAD been amended. Also fixed: invariant 40's voice
  ladder was missing the settings-file rung invariant 39's had gained, invariant 41's stated reason
  for excluding the TTS provider ("only one exists") stopped being true when kokoro landed,
  invariant 27's worked example was superseded by invariant 10, the Scope note was nine invariants
  behind, README still listed trace retention as unbuilt twenty-five lines after describing it, and
  `DESIGN.md` still specified the Blob player, a two-state overview and a header without the title,
  settings or wordmark button.

  **Two format assumptions the previous slice claimed were "handled" were not**: the download link
  hardcoded `.mp3` for a file that may be WAV, and the CLI's `--out` default did the same. The
  server now REPORTS the episode's suffix rather than leaving the client to infer it from the
  configured provider, and the CLI corrects its default extension only when the user did not choose
  the path themselves.

- **A Traditional Chinese interface.** Batch two of the UX pass.

  Kept SEPARATE from the notebook's output language, which is a server setting deciding what the
  model writes. This one is a browser preference deciding what the buttons say — a reader may well
  want a Chinese interface over English papers, and folding the two together makes that
  unexpressible. It lives in `localStorage`, never reaches the server, and never reaches a prompt.
  Detected from the browser, switchable in Settings.

  The English table is deliberately empty: English is whatever the markup and the code already say,
  with every call site carrying its own fallback, so there is no second copy to drift. Two tripwires
  guard the parts that fail silently — a key used but not translated (the interface would just stay
  half-English) and a call with no English fallback (an English reader would see the key).
  Simplified Chinese deliberately does not resolve to the Traditional table.

- **A UX pass over the whole product surface, from a user's list of seven.** Batch one of three.

  **"Pressed generate, it said Finished, then nothing appeared."** Reproduced as a design fault
  rather than a crash: the response arrives, a staleness guard drops it silently, and the last
  ticker line sits there looking stuck. What trips that guard is pressing the button again — which
  is the natural move when a minute-long run shows no progress and offers no way out. So the three
  are one fix: every long action now shows a pulsing dot, the live action and a ticking timer, a
  superseded generation says so instead of returning silently, and there is a Stop button.

  **Stop cancels by run id.** `/overview` fires two runs and `_ACTIVE_RUNS` holds one slot per
  notebook, so the existing notebook-scoped cancel would leave the second one burning a model call
  to completion. The new run-scoped endpoint kills exactly what was asked for — verified live:
  both halves killed mid-run, exit -9, zero orphan workers.

  **Selecting a Studio tab no longer runs anything.** It used to fire a real RLM call on click, so
  browsing the four kinds to see what they were cost four model runs. Each tab now says what it is
  (on hover) and offers a button.

  Also: "Audio Overview" is "Podcast"; Studio, Podcast and Notes each carry one sentence saying what
  they are for; and `+ Save as note` explains that promoting a note is what makes it citable.

- **Fix `no run '…-summary' found` on the first overview of a new notebook.** Reported from real
  use and reproduced on the first attempt.

  The ticker opens before the request and waits five seconds for the run's trace file. But every
  run-taking handler resolves the output language first, and that is a real model round trip in its
  own subprocess — on a new notebook it always happens, because the language has by definition never
  been resolved, and it always takes longer than five seconds. So the client gave up while the
  language run was still going, on a request that then succeeded normally. `traces/…-lang.jsonl`
  sitting beside the summary trace is the fingerprint.

  This is a different window from the one the trace-stream slice already closed: that one was
  microseconds between reserving the trace file and registering the process, this one is minutes
  and sits before either. Run ids are now ANNOUNCED before any pre-work, and the stream waits
  indefinitely for an announced run while still bounding one nobody will ever write. Applied to all
  five run-taking handlers, including `/title`, which no client streams today but could.

  The first regression test was hollow — it pinned the mechanism and stayed green with the fix
  deleted from the very endpoint that was reported. Mutation-testing caught that; the behavioural
  test now makes language resolution slow and opens a ticker alongside the request the way a browser
  does.

- **Twenty-fifth slice: the local TTS provider is Chatterbox now, not Kokoro — and the reason is the
  language matrix, not audio quality.**

  The user's audience is English first, Chinese (both scripts) second, Japanese and Korean third,
  with foreign words mixed into all of them. Nothing about that was true of the local provider:
  Kokoro's Chinese G2P passes Latin straight through (its "phonemes" for `NASA` are the literal
  string `NASA` — that is the mechanism behind the mangled audio a user reported), it has no Korean
  at all, and its own model card grades every Chinese voice D.

  **MeloTTS was measured as the replacement first, approved after a listening test, and then
  rejected on the matrix.** Its Japanese module DELETES embedded Latin; its Korean needs a package
  that destructively overwrites the one its Japanese needs, so the two cannot coexist in a single
  environment at all; its English needs an NLTK resource its own installer never fetches. Recording
  that here because the listening test had already picked it — the requirement is what disqualified
  it, not the sound.

  Everything else was checked against its LICENSE file or model card rather than a summary: Fish
  Speech, Higgs Audio v3, IndexTTS-2 and F5-TTS are all licence-blocked; CosyVoice 3 is zero-shot
  only (every synthesis needs a reference clip); VibeVoice is English and Chinese only and embeds an
  audible AI disclaimer in every output.

  **Chatterbox is MIT for both code and weights, covers all four languages, and handles a foreign
  word inside a sentence for free** — it has no G2P stage to fail at, which is the structural reason
  the G2P-based engines all break the same way.

  **Three costs, measured rather than assumed, and none of them hidden.** It runs at RTF ~4.5
  against Kokoro's ~0.2 — a 3.4-minute episode took 16.1 minutes end to end through the real
  product, 15 of them synthesis, where Kokoro took about forty seconds. Its output LENGTH is
  unstable — the same Traditional Chinese sentence came back at 34.80s / 5.48s / 11.68s against an
  expected ~7s, and the long take was the decoder looping, not trailing silence — so
  `ChatterboxProvider._generate_one` re-rolls against a character-count estimate that is calibrated
  against four real measured utterances and pinned by a test. And it ships exactly ONE built-in
  voice, so two distinguishable hosts need reference clips.

  **Those two clips are synthesized, not recorded**, so no person's voice is being cloned — and the
  provenance chain behind them is disclosed in `rlm_notebook/voices/README.md` rather than left to
  be discovered, because it is three hops long and this project has paid once already for taking a
  licence chain on trust.

  Also: `TTSProvider.synthesize` now takes the resolved `language`, because a cross-lingual
  provider's voice and language are independent axes; a path to a custom reference clip is reachable
  from the environment but deliberately NOT from the unauthenticated settings page; and the extra
  carries two odd-looking pins (`numba>=0.61`, `setuptools<82`) that are what make it install and
  import at all on Python 3.13.

  **Verified live end to end**: a 16-turn Traditional-Chinese episode from English sources, 16
  offsets each landing on its own line's audio, `NASA` rendered `美國航空暨太空總署` with zero Latin
  runs, the two hosts measurably distinct (median F0 126 Hz against 201 Hz), served as `audio/wav`
  with range support. The runaway guard did not fire — which shows the ceiling is not set so tight
  that it burns re-rolls on correct takes, and is NOT evidence the instability is gone.

  **An independent review then found two blockers**, both silent failures. CI would have gone red:
  the new provider test faked `soundfile` and `chatterbox.mtl_tts` but not `torch`, whose only root
  in the dependency graph is `chatterbox-tts` — verified fixed by running the whole suite under a
  meta-path blocker that makes the extra genuinely unimportable. And mixing `built-in` with a
  reference clip collapsed BOTH hosts into one voice, because the built-in conditioning exists only
  as `model.conds` and the first `prepare_conditionals` overwrote it.

  From the same review: `validate()` moved ahead of the script run (a language chatterbox has no id
  for used to burn a whole model call before failing); the language pass-through had zero coverage
  at either call site; the lazy-import test was a vacuous disjunction that a module-scope
  `import torch` still satisfied; the settings page's voice help was edge-tts-only; and the
  provenance file pointed at a regeneration command that shipped nowhere. Every fix mutation-tested.

- **A code-vs-docs consistency audit across the whole repo, and the eleven fixes it produced.**
  Run as the closing step of the slice above, over all 45 invariants rather than just the diff. It
  found doc claims in both directions — things the docs promised that the code did not do, and
  things the code did that no doc mentioned — plus four invariants whose "confirmed by a test"
  turned out to rest on nothing.

  **Real defects, all mutation-tested:**

  - `RN_MAX_UPLOAD_BYTES=not-an-int` returned a raw 500 with a traceback. Invariant 24 claimed every
    `SystemExit` in `config.py` was reachable only through `from_env()`, so `_config()` covered them
    all; `max_upload_bytes` has one of its own and is the first statement of the upload handler.
    (It is standalone *because* invariant 30 says an upload must not depend on a model being
    configured — which is exactly how it fell outside the wrapper.)
  - Trace links were dead for `"my notebook"` or any non-Latin notebook id — the ids invariant 10
    exists to support. The server-side half of this was fixed two slices ago; the CLIENT was still
    building run ids from the raw id. `NotebookResponse.slug` now carries the server's own
    transform rather than a second copy of it in JS.
  - `RN_TTS_PROVIDER=kokoro` plus a language kokoro does not know fell through to the shipped
    `en-US-GuyNeural` — an edge-tts name handed to `KPipeline`, so synthesis failed *after* a real
    model call. The language map moved onto the provider in the previous slice; the last resort had
    not moved with it. And the settings page's voice pattern rejected every kokoro id, so a user
    could not name a voice for the provider they had configured.
  - Generating a podcast whose script came back empty left the previous episode on disk, so
    `GET .../audio/file` kept serving audio the notebook no longer had.

  **Four invariants that claimed a test and had none** — each now pinned, each verified by mutating
  the code and watching the new test go red: invariant 2's "do not swap back to plain `urlopen`"
  (swapping it left the suite green — the redirect tests call the handler directly and never
  exercise which opener fetches); invariant 22's `start_new_session=True` (deleting it left the
  suite green, because the existing test hardcodes the flag itself instead of calling
  `runner.start_run`); invariant 29's pre-spawn `_RUN_PROCESSES` reservation, the fix for the
  user-reported "run ended without a final event"; and invariant 23's identity check, which the
  invariant said was "confirmed with an interleaved-`asyncio` test" that did not exist. The first
  attempt at that last one was itself hollow — asserting both entries are gone afterwards is
  satisfied by the buggy version too — and only caught the bug once rewritten to check that a
  *finishing* run leaves a *later* run's slot alone.

  One test was also quietly downloading spaCy models over the network and skipping on CI; it fakes
  `kokoro` and `soundfile` through `sys.modules` now, verified with a meta-path blocker rather than
  by trusting its own docstring.

  **Doc corrections worth naming**, since several were overclaims of the exact kind invariant 5
  exists to prevent: the size cap fires at question time, not at ingestion time; there is no
  model-side injection conclusion to union with, and the flags reach the CLI only; `GET /notebooks`
  is no longer "metadata only" now that it carries a model-authored title; synthesis runs on
  schema-validated output, not "citation-checked" output; there are six citation-grounded tasks, not
  five; `NotebookConfig.ocr_provider` has zero consumers; the CLI's `audio` persists nothing. Two
  design documents referenced from 21 places had never existed, and the rest of `docs/` is
  gitignored anyway.

- **Twenty-fourth slice: subtitle-style transcript, a podcast that lands, and speakable prose.**
  All three reported by a user listening to a real episode.

  **The transcript is now subtitles**: the line being spoken is highlighted, a timecode sits beside
  each line, and clicking a line seeks to it. Timing comes from the PROVIDER — every provider here
  already synthesizes utterance by utterance — rather than from parsing the audio. `Podcast.offsets`
  is parallel to `utterances` rather than a field on `Utterance`, because `Utterance` is the model's
  output shape and the model cannot know how long its own words take to say; anything but one
  strictly-increasing offset per utterance means "no timing" and renders a plain transcript.

  **A bug the offsets themselves revealed**: the first version keyed on edge-tts's `WordBoundary`,
  but the installed version defaults to `boundary="SentenceBoundary"` and emits only that — so every
  offset came back 0.0, a transcript highlighting nothing. Found by generating a real episode and
  reading the numbers.

  **An independent review then found the safety net for that case did not exist.** A provider
  reporting no boundaries returns `[0.0, 0.0, ...]` — the RIGHT LENGTH, so the documented length
  check could never fire; simulated, it stamps every line `0:00`, highlights the second row for the
  whole episode and seeks every click to zero. The guard is monotonicity now, and the claim in the
  docstring is gone. The same review showed by mutation that the entire API side of `offsets` (the
  response, what gets persisted, and the reopen path) had no coverage at all — deleting all three
  left the suite green — and that the edge-tts offset test could not catch a per-utterance state bug
  because its fixture gave every utterance the same duration. Both are pinned now, and kokoro's
  gap-before-offset rule moved into a pure function (`tts.sequence_offsets`) so CI can check it
  without the extra, a model download, or any audio. Every fix here was mutation-tested.

  Also from that review, all in the player: clicking into an expanded trace payload (or the mouseup
  ending a drag-selection) seeked and autoplayed; the hover state was the colour the row already had
  AND outranked `.is-speaking`, so hovering the playing line deleted its highlight; `formatTimecode`
  had no hour component; and the playhead follower used `scrollIntoView`, which walks every
  scrollable ancestor — the transcript is its own scroll box now, so following the playhead can no
  longer drag the studio column back from whatever the reader had scrolled to.

  **The episode has a shape.** `audio.py` asked only for "a natural conversation" — no opening, no
  segment plan, and no close, so episodes simply stopped when the model ran out of facts.
  NotebookLM's Audio Overview was never used as a reference; that gap is closed after a user named
  it. There is now an opening that frames the sources, a body that follows the interesting thread,
  and a close that draws the threads together and says what it adds up to, grounded in the sources.

  **Prose is written to be SPOKEN in one language.** A TTS voice for one language cannot pronounce
  another script, which the user heard. The mechanism was confirmed rather than assumed: kokoro's
  Chinese G2P returns the literal string `NASA`, and `Voyager i→`, as its own "phonemes" — raw
  Latin letters reach the acoustic model as unknown tokens. Foreign proper nouns are now rendered
  the way a native speaker would say them, scoped to what is actually spoken and exempting a
  `Citation.quote`. Two things the first draft of the rule got wrong, both caught by checking a real
  episode rather than re-reading the prompt: it invited the original in parentheses (the exact
  failure it exists to prevent — an utterance is both the transcript AND what the voice reads), and
  it let acronyms through, which a live run duly demonstrated. Both closed, and re-verified by
  regenerating: `NASA` became `美國國家航空暨太空總署`, every proper noun renders spoken, each
  citation kept its verbatim English quote and verified, and the episode closes on a genuine
  reflection rather than a stray fact. One Latin letter survives — the `E` in `泰坦三號E半人馬座運
  載火箭`, which is how the designation is written in Chinese — and is left stated rather than
  chased with a stricter sentence.

  Also: kokoro now inserts a short gap between utterances (free, since it holds raw samples — unlike
  edge-tts, where invariant 17 refuses re-encoding), and `.btn` sets `color`/`text-decoration`
  because it has to work on an `<a>` — the download link had been rendering as UA-blue underlined
  text on the dark theme.

- **Three more UX defects, all reported by a user actually using the thing.**

  **A notebook named in Chinese was rejected outright.** `notebook.slug`'s `[A-Za-z0-9._-]`
  whitelist strips every CJK/Arabic/Cyrillic/emoji character, so `"模型要睡覺"` reduced to the
  empty string and came back as `400 invalid notebook id … reduces to an empty token` — a message
  that says nothing about the name being the problem. `slug` now falls back to `nb-<sha256[:16]>`
  for any id the whitelist empties: deterministic, collision-resistant, inside the same whitelist,
  and affecting the FILENAME only (`Notebook.id` keeps what the user typed, and
  `list_notebook_summaries` already reported the stored id rather than the filename stem — a
  property it was given for exactly this reason). Verified end to end against the running server: a
  Chinese-named notebook accepts sources, lists under its own name, and lands on disk as
  `nb-55de69c77d45b935.json`. A genuinely empty id still 400s. **Deliberate consequence, not a
  regression**: `"!!!"` is an ordinary notebook now rather than a 400 (invariant 27's arm), since
  once a Chinese name had to work there was no principled line left between "punctuation only" and
  "non-Latin only" — the unhandled 500 that invariant was created to fix is still gone.

  **Editing the notebook-id box without pressing Open silently wrote to the previously-opened
  notebook**, with the box on screen showing a different name entirely — reported as "I can't
  create a second notebook without reloading the page", and visible in the user's screenshot as an
  error naming a notebook that was no longer in the box. Everything mutating acts on
  `state.notebookId`, which only `openNotebook` sets. Two fixes together: the box is rewritten from
  state on every switch so it can never disagree with what the app is acting on, and the wordmark
  is now a real button that starts an empty notebook. That also surfaced a latent bug it made
  one-click reachable — switching from a notebook with turns to an empty one left a blank chat
  panel with no placeholder, because `chat:turnAdded` hides it and nothing un-hid it.

- **A working session with the thing, turned into one slice.** Everything below was reported by a
  user driving the real product, and each item names what was actually broken rather than what was
  improved.

  **The highlighter strokes had silently stopped existing, and could never have come back on their
  own.** A citation was drawn as a stroke through the sentence it backs by searching the answer for
  the citation's `quote` — which works only while the answer and the source share a language. Since
  invariant 39 the prose follows the READER and the quote stays in the SOURCE's words, so the two
  never share a substring and no span was ever found. `schema.Citation.answer_span` (new, optional,
  backward-compatible) is the model's own pointer at the stretch of ITS OWN text a citation
  supports; `citations.locate_answer_spans` drops any span that does not occur in that prose
  verbatim, keeping the citation — the same coordinate-existence discipline invariant 5 applies to
  `source_id`/`locator`, aimed at the model's prose instead of at the corpus. `_citation_responses`
  now takes the exact string each artifact renders, so a chat answer, an FAQ item, a timeline event
  and a podcast utterance each check their span against their own text.

  **A source could not be removed**, and adding removal broke id numbering the moment it landed:
  `append_sources` numbered from `len(sources) + 1`, so deleting `s2` and appending produced a
  SECOND live `s3`. Reproduced before the fix. `notebook.next_source_id` derives from the max id in
  use — the same bug `_next_note_id` was written for (invariant 32) one field over. Nothing is
  renumbered on removal, which is what makes removal safe: a citation into a removed source comes
  back unverified with a reason rather than resolving to different text.

  **A pasted URL showed as a bare link.** `parsers/web.extract_preview` scrapes title/description/
  site from the html `parse_web` ALREADY fetched — one request, as invariant 1 requires — into
  `Source.preview`, which is display-only and never reaches the corpus blob. **`og:image` is
  deliberately absent**: rendering it makes the reader's browser fetch a URL the page author chose,
  turning every pasted link into a beacon, in exchange for a thumbnail.

  **The live ticker said far less than the sibling studios' feeds**, because
  `_translate_trace_event` emitted a fixed sentence per event type and threw the payload away. It
  now carries `{kind, primary, detail, meta}` — the model's own reasoning, the tool's name, the
  sub-model escalation's attempt number. The step's `output` is deliberately NOT streamed; its SIZE
  is, which is the part that says whether a step did much. `summary` is kept as the concatenation of
  the first two, so a consumer written against the old shape keeps working.

  **`⚠ instruction-like phrase matching '\bsystem\s*:\s*'` was shown to a person.** Invariant 6's
  flags gate nothing, so their entire value is whether a human can act on them — and a raw regex
  names an implementation detail and says nothing about what to do. Every pattern now carries a
  sentence. That same pattern was also measured firing on ordinary prose ("The operating system: a
  set of layers"), so it is anchored to a role label opening a line.

  **Renaming a notebook.** `PUT /notebooks/{id}/title` is a separate VERB from the model-generated
  `POST` — setting a title is an instant write that always succeeds, generating one is a run that
  can fail, take seconds and be superseded, and folding them together would give rename the failure
  semantics of a model call. `naming.normalize_title` is split out of `clean_title` because the two
  callers need opposite things from an unusable value: generation falls back to a derived label, a
  rename is REFUSED, since substituting a title for what someone typed would be the UI lying.

  **The picker.** Model-authored titles are not unique — a user hit three notebooks with
  near-identical generated names — so the list is ordered by file mtime and carries `updated_at`.
  `derived_title` (the same `fallback_title` the generate path uses, no model call) now appears in
  BOTH `NotebookSummary` and `NotebookResponse`, because the header and the picker row disagreed:
  one said "Untitled notebook" while the other showed a derived label for the same notebook.
  `GET /settings/choices` serves the settings page's dropdown values for the CONFIGURED provider —
  a voice name is provider-specific (invariant 43), and a second copy in JS would drift from
  `tts._LANGUAGE_VOICES`. Like `GET /settings` it never calls `_config()` (invariant 41).

  **Titling is LAZY now.** It used to fire from adding a source, which a user called too
  aggressive: pasting a link spent a model call naming something they had not started working on
  yet. `ensureTitle()` is called from the actions that already run a model. `derived_title` is what
  keeps an untitled-but-populated notebook from reading as "Untitled" in the picker.

  **Front end.** The right column is now a resizable, collapsible rail with four switchable views
  (Studio / Podcast / References / Notes), the shape `cloud.projectdiscovery.io` uses: drag the grip
  to size it, drag past the threshold to put it away. The two tab rows are structurally different
  (underline vs pill) because two identical rows said nothing about which contained the other. Two
  defects found while building it are pinned as source-tree assertions, since this project still has
  no JS test runner (invariant 29): a tooltip host that clips its own tooltip erases it outright
  (two real instances, one of which took out every tip inside the Sources card), and inverted
  hysteresis on the drag thresholds makes the panel flip state on every pointer event.

- **What three independent reviews then found, all of it fixed here.** Listed because each one is a
  defect this slice introduced, not a pre-existing one.

  **`promote_note` still numbered sources by length**, so the collision the fix above was written
  for was alive on the ONE path that makes a note citable (invariant 32): the corpus blob emitted
  one id twice and the promoted note was unreachable by any citation. Reproduced over real HTTP.

  **`extract_preview`'s regexes backtracked catastrophically.** A page of unclosed `<meta` tags took
  38 seconds at 19.7KB, cubic, with `re` holding the GIL the whole time — a one-request freeze of
  the entire server, reachable by anyone who can paste a URL into a no-auth API. Every quantifier is
  bounded and the input is windowed to the `<head>` now: a constant ~330ms whatever the input size,
  while a well-formed 681KB page with 5000 meta tags still parses in 0.019s.

  **`_citation_responses`' `prose` argument failed OPEN.** It defaulted to `""` and then skipped
  validation entirely when empty, returning the model's raw unchecked span — the opposite of what
  the docstring promised. It is required now. Worse, a reviewer removed it from all eight call sites
  — completely disabling the highlighter strokes — and the whole suite stayed green; two tests pin
  the wiring.

  **`remove_source` returned `False` on a miss**, and `mutate_notebook` writes unless the delta
  raises, so a 404-ing DELETE still saved the file and bumped the mtime the picker now sorts by.

  **The settings page offered languages the configured provider cannot speak** — Thai/Vietnamese/
  Indonesian to a chatterbox deployment, while hiding the eleven it can. Picking one persisted a
  GLOBAL `output_language` and then failed every `/audio` request. `supported_languages()` is on the
  provider now, where `default_voices` already lives (invariant 43).

  **The References view could not contain the citations that linked to it.** Every citation in a
  guide artifact or the podcast transcript was clickable and switched to a list built only from the
  overview and chat. It only looked like it worked when the same coordinate happened to be cited in
  chat too — which, since text and web sources all use locator `"whole"`, is most of the time.

  Also: three source-tree assertions were repaired after mutation testing showed they passed with
  their own documented defect reintroduced (the drag thresholds' state PAIRING, two hidden-toggled
  classes the harvester could not see, and every `data-i18n-tip` key); `normalize_title` now strips
  control characters; a malformed trace payload can no longer abort an SSE connection mid-stream;
  and a set of smaller UI defects — three tooltips lost while restyling the header, a duplicate
  translation key, a `t` shadowed in three closures, Escape-during-rename that could still commit,
  arrow keys silently rewriting a collapsed panel's width, `localStorage` written on every
  `pointermove`, and hover rules that were inert on the element they were pointing at.

- **Five things a user asked for after reading real answers on the page.**

  **Markdown is rendered.** Answers arrived full of raw `**bold**`, `## headings` and `- lists`,
  because the model writes markdown whether or not anyone asked. The renderer is hand-written and
  builds DOM nodes — no library, no HTML strings, the exception a sibling studio states outright
  for the reason that applies here too: every string came out of a model that has been reading
  source content an attacker may have written, and one missed `esc()` in a string-building renderer
  is an XSS sink. Headings, nested lists, blockquotes, inline and fenced code, tables, rules, bold
  and italic. **A link is shown but not clickable** — invariant 1 refuses to let the model reach a
  URL because a prompt-injected source could steer it into exfiltrating notebook contents, and an
  `<a href>` in an answer is that same hazard with the reader's click as the transport. The URL is
  visible so it can be copied deliberately.

  The renderer never creates a text node: it walks raw offsets and appends through `emit`, which
  owns citation splitting. That is what lets markdown structure and highlighter strokes compose — a
  stroke crossing an inline `**bold**` is split into fragments, and only the last carries the
  reference number. Verified against a real DOM shim under `node` before it was believed: nested
  lists land inside their `<li>`, a `<script>` in a code fence stays text, zero anchors created.

  **Every answer now suggests what to ask next.** `Answer.follow_ups` comes from the SAME run that
  wrote the answer, so it costs no extra model call; starter questions previously existed only on
  the overview, appearing once per notebook and never again. Not citation-grounded — a question is a
  prompt, not a claim. The overview keeps "Start with" and a turn says "Ask next", deliberately not
  unified: the overview's appears before any conversation exists.

  **The overview stopped covering the conversation.** It was a sibling above the thread with
  `max-height: 45%`, so it permanently owned half the chat column. It is the thread's first entry
  now and scrolls away as the conversation grows.

  **The References view is a list of rows again.** It rendered every quote as an always-visible
  blockquote, so one source cited eight times filled the column. Now: number, title, a hostname
  chip, the use count, one clamped line of the passage, everything else behind a click — the shape
  Kagi's assistant and Google's AI answers both use. And the part a user actually pointed at:
  pointing at a reference lights up the strokes it backs, pointing at a stroke lights up its row.

  **The run log is a timeline** — one rail with a node per step, the current one pulsing and open,
  past ones clamped and expandable, each timestamp carrying how long that step took. Four separate
  left borders read as four unrelated items; a rail reads as one process advancing.

  Also: the reference link under an answer gets its own line and real space above it.

- **What two independent reviews then found in that slice.** Both ran the real code rather than
  reading it — one fuzzed the markdown renderer against a DOM shim under `node` (~62,000
  documents), the other drove `app.js` in headless Chrome.

  **The reciprocal highlight had never worked, in this slice or the one that introduced
  `focusReference`.** `referenceKey` joined its coordinate with U+0000, and `CSS.escape` maps
  U+0000 to U+FFFD by spec — as does the CSS tokenizer parsing the selector — so every
  `[data-ref-key="..."]` lookup matched nothing at all. Measured in a browser; invisible to the
  Python suite and to any amount of reading. The separator is U+001F now.

  **A citation's reference number vanished whenever its span ended on markdown syntax the renderer
  drops** — a closing `**`, a backtick, a link's `](url)`. `isLast` was decided while emitting, and
  no emit ever reached the span's end in those cases, so the stroke got no number while the
  References panel numbered it anyway. Stamped after the render now, where every fragment is known.

  Also fixed: emphasis follows a flanking rule, so `3 * 4 * 5` and `my_var and other_var_name` are
  left alone; a table written directly under a sentence is no longer swallowed by the paragraph, and
  prose containing a pipe is no longer swallowed by a table; a list whose first item is indented no
  longer emits `<ul>` inside `<ul>`; the run log's step duration is visible text rather than a
  tooltip clipped by the log's own scroller, and the first row measures from the run's start;
  `is-current` is cleared when a run finishes; `.is-focused` and `.is-linked` are genuinely disjoint
  now rather than only claimed to be; the new pulse has a reduced-motion opt-out; opening a notebook
  no longer lands scrolled past the overview; and a markdown link's URL can actually be copied,
  which the tooltip alone never allowed.

  Three tests were widened after mutation testing walked past them: the navigable-link check missed
  `setAttribute("href")`, a template-literal `createElement(`a`)` and a `window.location`
  assignment, and nothing pinned the chat overview's position inside the thread.

- **`RN_MAX_ITERATIONS` is 25 and `RN_RUN_TIMEOUT_SECONDS` depends on how the model is served.** A
  user hit `502 ... timed out after 300.0s` on the subscription path, with a trace file holding one
  `run_start` and nothing else — cancelled before its first step ever returned. That path spawns a
  Claude Code CLI subprocess per LM call (invariant 35), so the default is 1800s there and stays
  300s for a direct API model. The step budget went from rlm-harness's own 10 to 25 because the
  failure modes are not symmetric: exhausting it loses a run already paid for, unused headroom costs
  nothing, and a runaway is bounded by the wall-clock timeout instead. A judgement, not a
  measurement about the ceiling — but what IS measured is that 10 was about to bind: an 8-source
  notebook's Summary took NINE main steps, one short of the old limit, having already spent three
  minutes of model time. The same overview's FAQ half died on the 300s timeout, which is why that
  notebook has a summary and no starter questions at all. The timeout error names the variable now,
  and an overview that comes back without suggested questions says so instead of rendering nothing —
  it read as the feature having been removed.

- **A model switch turned three budget defaults into real failures, and one of them was already
  written down in a sibling.** Pointing `RN_MAIN_MODEL` at a Qwen3 MoE behind a proxy made
  `GeneratePodcastScript` fail instantly with `RLMTaskError: Failed to produce a valid 'script'
  after 1 attempts` — a two-event trace, nothing to read, while Summary, FAQ and chat all worked on
  the same model.

  The cause was `max_tokens`, not the podcast. dspy reads `content` and DISCARDS
  `reasoning_content`, so a reasoning model's chain-of-thought is billed against a cap it never
  appears in; `ctx-distillery` documents that trap and recommends 16384, having watched a sibling
  hit it on its first live turn. Verified as a single-variable change here: same notebook, same
  model, same 146,284-character corpus, `max_retries` untouched — 8192 died at turn 0, 16384
  produced 8 utterances and 11 citations in 121.5s. The podcast went first because its instructions
  are the longest and its output schema the deepest.

  `max_retries` stays PINNED at 1. It was briefly raised on the argument that a turn-0 parse failure
  is transient and cheap to re-run; that is wrong, because the second attempt hits the same ceiling
  and fails identically — and every sibling pins 1 for the reason that a re-run also writes a second
  copy of the same failure into the trace. It is readable from `RN_MAX_RETRIES` now, so raising it
  is a deliberate act rather than a code edit.

  `worker.py` now carries the ROOT CAUSE across the process boundary. The wrapper named the symptom
  and the `AdapterParseError` underneath named the cause; diagnosing this took a trace dump and an
  in-process re-run when it should have taken reading the error.

- **Podcast generation says which of its two phases it is in, and a long wait says something new.**
  Only the script half is a traced, cancellable subprocess run; synthesis then happens in-process
  with no trace and no way to stop it, and the label said "Writing the script" throughout. A user
  also watched "waiting for the model's first response" for seven minutes and read it as a crash —
  nothing more CAN be observed before the model replies, so after 90 seconds the status says that,
  and points at Stop, instead of repeating a phrase that has already failed to reassure.

  The steps affordance survives a reload: `tickerLogs` lives for one page session, so every "N
  steps" pill vanished on refresh even though the trace file is still on the server and the stream
  endpoint replays it from the start. It loads on demand now, and says so honestly when retention
  has already collected the record.

- **What two more independent reviews found, both by running the code rather than reading it.** One
  monkeypatched `rlm_harness.configure` and drove a real worker subprocess; the other drove the page
  in headless Chrome and in jsdom.

  **The error-cause change deleted the diagnostic it existed to surface.** dspy orders
  `AdapterParseError.__str__` as adapter-name, then the WHOLE LM completion, then the
  expected/actual summary — so a head truncation drops the only two useful lines. Measured cutoff: a
  completion over ~534 characters. rlm-harness already ships `_short_error`, which head+tail elides
  with the same constant and whose docstring names this exact case; it is used now instead of a
  worse re-implementation. The output is bounded on BOTH halves too — an unwrapped
  `AdapterParseError` was producing a 20,000-character HTTP body.

  **The guards were on the wrong knob.** Both `RN_MAX_TOKENS` mutations — hardcoding the default,
  and deleting the forwarding line — survived the whole suite, while the pinned `max_retries` had
  two guards. The forwarding test is behavioural now and covers all five budgets.

  **`max_output_chars` was the fourth field of the same shape**, left at rlm-harness's 10000 while
  `ctx-distillery`'s own audit (which names exactly these two fields) had raised its own to 40000.
  It bounds how much of a REPL output reaches the planner's prompt, and every task here explores the
  corpus by `.find()`/slicing and prints spans — a truncated one costs an iteration to re-fetch.

  **Front end**: the podcast's new synthesis label was silently overwritten 20 seconds later by
  "waiting for the model's first response", and the 90-second tier then offered a Stop that was
  greyed out — reintroducing, in the same diff, the complaint that tier was added to fix. A disabled
  Stop was pixel-identical to a live one. Regenerating the overview mid-question deleted the
  question, its status and its Stop. And the stroke-numbering fix covered the chat thread only, so
  adding a turn left every podcast and guide stroke pointing at the wrong row.

  Also fixed: the guide cache lost `delete` when it moved onto `state`, so Studio's ↻ Regenerate
  threw `TypeError` and did nothing; an empty cached trace log counted as a cache hit, so a dropped
  stream left a permanent `0 steps` pill; `data-reference="0"` rendered a literal superscript zero;
  `raise X from None` had its suppressed context resurfaced; a falsy exception had its cause
  skipped; an `ExceptionGroup` swallowed the real fault; and an exception whose `__str__` raises
  would have killed the worker's only JSON line.

  **Six of twelve front-end mutations walked past the tests** — including `i + 1` → `i`, the exact
  off-by-one the numbering change exists to fix — because every assertion checked that a token
  appeared somewhere rather than what it did. They assert structure now.

- **Clicking a transcript timecode had silently stopped seeking, and it was a rename that did not
  reach the body.** Fixing a shadowed `t` (the i18n function) renamed the parameter of the podcast's
  `seek` to `seconds` and left `player.currentTime = t` behind — assigning a function coerces to
  NaN, so every seek did nothing, with valid syntax, a resolvable identifier and no error anywhere.
  `t` is now pinned as call-only: every occurrence in `app.js` must be a call, never a value.

  **Three layout defects in the same panel, each the consequence of the previous fix.** The
  utterance rows carried negative margins from when they were bare text, so inside the now-scrolling
  transcript every row was wider than its box and the whole thing gained a horizontal scrollbar. The
  transcript's fixed `22rem` (chosen when the podcast shared a column with two other sections) left
  a blank strip below it; `60vh` then made the panel taller than the column, so the column itself
  scrolled and took the heading away. Only a flex chain sizes this correctly, and the `display:
  flex` it needs on a `hidden`-toggled class is safe because a longer `[hidden]` selector outranks
  it. That flex column then stretched the download link and the steps pill to full width.

  **The Generate podcast button now has the overview's three states** — offer / quieter regenerate /
  regenerate-because-sources-moved — instead of one permanent primary button sitting above a player
  that already existed.

  Also: the answer-footer spacing added for chat answers was applying inside every transcript line;
  and two `forEach` parameters named `body` collided with the podcast panel's own local, which made
  the hidden-toggle tripwire flag `.podcast-body` — fixed by renaming the locals, which is what that
  test's own docstring prescribes for its known false positive rather than loosening the check.

- **A listening comparison retired an assumption, and the assumption was load-bearing.** The record
  said "a TTS voice cannot pronounce another script" — established for kokoro, and merely ASSUMED
  for `edge-tts`, the provider that actually ships by default. One hostile line synthesized through
  both settles it: Chinese prose carrying `NASA`, `Voyager 1`, `CVE-2026-1234`, `RAPTOR`, `harness`
  and a whole English clause took **8.2s / 81KB on edge-tts** and **273.4s / 749KB on chatterbox**,
  and edge-tts handled the mixed script — some pronunciations odd, none mangled.

  So `GeneratePodcastScript`'s rule to transliterate foreign proper nouns (acronyms included, no
  original in parentheses) was solving a problem the default provider does not have, while costing
  something real: `Utterance.text` is BOTH the transcript and what the voice reads, and a rewritten
  name is exactly the word a listener cannot look up when the audio is unclear. The rule is gone.
  Names stay as their source wrote them; numbers, dates and units still get spoken form, because
  those read aloud badly everywhere and nobody looks them up.

  Also recorded: chatterbox's position is the LOCAL/privacy option, not "the only one that handles
  mixed script" — 33x the wall clock and 9x the bytes is a trade a reader whose sources cannot leave
  the machine should be able to make, and one nobody should be made to take by default.

- **Two defects a user found in one notebook, and the smaller-looking one was the dangerous one.**

  **The notebook was titled by transliterating its first source's paper title**, because the titler
  reads a WINDOW of the corpus and that window was `blob()[:4000]` — a prefix of a string that
  concatenates sources in order. Source one alone was 69,859 characters, so sources two, three and
  four were never seen. `Corpus.excerpt(n)` gives every source an equal share from its opening
  lines; verified against the reported notebook, where the old prefix saw `s1` and the new excerpt
  sees `s1 s2 s3 s4`. **Language resolution read the same prefix**, which is worse than a bad title:
  a notebook whose later sources are in another language would resolve the wrong one, and that guess
  is then persisted (invariant 39). The prompt now names "translate source one's title" as the
  failure mode instead of leaving it to be inferred.

  **Raw `[[SRC:s1|whole]]` markers were on screen in the overview** — the model wrote the coordinate
  into its own prose, which the rules never covered because they only ever said where a marker
  BELONGS. Stripped at the display boundary, so nothing stored is rewritten and every notebook
  already on disk is fixed with no migration. The same strip runs on `answer_span`, or a span
  carrying a marker silently stops matching and every highlighter stroke vanishes.

  Also measured, in answer to a question rather than a bug report: the two podcast hosts speak at
  different speeds (5.43 vs 4.84 characters per second, consistent across every line) because they
  are two different edge-tts voices and this project sets no rate at all.

- **The podcast got a length, and then the length broke it in a way worth recording.** Three tiers
  (`short`/`default`/`long`, ~3-5/8-12/18-25 minutes), chosen at generation time and carried by both
  entry points. The tiers are numbers because the previous instruction — "a natural episode length
  given how much the sources contain" — measurably did nothing: four episodes all landed near three
  minutes and the eight-source notebook produced the shortest.

  `long` then failed outright: written as one code block it exceeded the per-call generation cap and
  the salvaged fragment parsed as an empty object. dspy named the cause in a warning. The fix was
  NOT to raise the cap — it was to build the script across REPL turns, which is what the sandbox is
  for. Same corpus, same budget: 80 utterances and 44 citations.

- **A user asked where the markers were coming from, and the answer was worse than a render bug.**
  One episode had 20 markers written across 19 of its 47 utterances and ZERO citations: the model had
  abandoned the `citations` field entirely and was citing by writing coordinates into the prose. So
  the voices read them aloud, the transcript had no references, and the display-layer strip added
  earlier made the evidence vanish rather than recovering it. Three layers now: a pre-SUBMIT
  validator that rejects a marker in prose, the display strip, and a strip before synthesis.

  That validator started life on the podcast alone, because that is where the failure made a noise —
  `GenerateSummary` had produced the same defect silently, four markers in an overview. It is shared
  by all six tasks now, from one factory.

- **This project had no `rlm_harness.skills` at all, which a user had to point out.** It is
  `rlm-harness`'s own progressive-disclosure mechanism for downstream RLMs — distinct from the
  Claude Code skills a coding agent reads and this task never sees — and four sibling projects
  already shipped the same `discovery="inject"` shape.

  Two skills so far: `podcast-craft` (tension, pacing, the reveal — from the NotebookLM team's own
  account of how the format is made, plus the one technique this project cannot copy and why) and
  `corpus-navigation` (every measured way a run has been lost here: the one-code-block truncation,
  printing what you are accumulating, a truncated span costing a whole turn, the nine-of-ten step
  budget, and the marker incident). Nothing was moved out of the four Guide prompts, which are
  entirely must-apply — inventing craft to have something to move would have been worse than an
  empty directory.

  `podcast-craft` also records a mistake made while writing it: its no-disfluencies rule was
  justified with a quote attributed to the NotebookLM team that was actually their hosts' show note,
  and the guest contradicts it when asked directly. It came from a fetched summary nobody opened the
  transcript to check. The rule now stands on this project's own measurement — a Chinese sentence
  with six characters of written filler synthesized to 4.08s against the plain sentence's 2.90s.

- **The independent review of this batch found the marker net could destroy the episode it was
  protecting.** A line that is nothing but a coordinate strips to empty or to a lone piece of
  punctuation, and edge-tts raises on punctuation-only text — a 502 that discards the whole
  paid-for run. In the incident that motivated the strip, those nineteen utterances were merely
  garbled; with the strip they would have been a lost episode. It falls back to the original text
  when nothing speakable survives.

  The same review found the strip's punctuation tidy running over the whole string rather than the
  hole the marker left, which normalises text that never had a marker and — because the strip
  early-returns on a marker-free string — makes the prose and the `answer_span` disagree, so every
  highlighter stroke vanishes. And in the validator itself: `model_fields` read off the instance
  (a silent fail-open under pydantic 3), dict fields skipped, a rejection message giving impossible
  advice when the offender is a citation field, and the skills catalog opened without being closed.

  Two behaviours that had shipped undocumented are written down now: the display strip's
  whitespace-before-punctuation rule, and the podcast length being remembered per browser in
  `localStorage` rather than on the notebook — a per-reader habit, the same split invariant 48 draws
  for the interface language.

  The CLI half of the length feature was not pinned at all: the review changed `target_length` to a
  hardcoded `"default"` and renamed the tier choices, and the whole suite stayed green both times,
  because the assertions read the flag's own help text. They read the parser and drive `_cmd_audio`
  now.

- **A fact-check of the documentation against the code found a fix that had only been written
  down.** `apply_skills` gated the skills CATALOG on a manifest existing but appended the
  `read_skill` TOOL whenever the directory did — so an empty skills directory handed the model a
  tool whose description points at a list that is not in its instructions, while CLAUDE.md said
  that was prevented. The code does it now and a test pins both directions.

  Five other doc claims did not survive the same pass and are corrected rather than quietly
  dropped: the podcast length was described as browser-local "never sent to the server" when it is
  sent on every generate and reaches the prompt (only the REMEMBERING is browser-local); the
  marker-strip fallback was justified partly by a chatterbox failure mode that does not exist
  (its runaway ceiling floors at one second, so a short line burns no re-rolls and never raises);
  the marker count disagreed with four other files; invariant 20 was cited for a feature-parity rule
  it does not state; and the skills work was framed as content MOVED out of prompts when almost
  nothing was — both skills are new material, and the two rules that appear in a prompt and a skill
  are there deliberately, the prompt stating a must-apply rule and the skill carrying its reason.

- **A user's overview came back with five red "unverified" badges, and the cause was not what the
  badge said.** Every web source is one block with locator `whole`; the model had written the
  section heading it was citing into `locator` instead. The chat turns on the same notebook were
  12/12 clean, so this was a per-task behaviour, not a corpus problem.

  The pre-SUBMIT validator now checks each citation's coordinate against the markers that actually
  occur in the blob this run was given — the same ground truth the server checks afterwards, applied
  while the model can still fix it. Its rejection shows a REAL coordinate, because a message that
  only says "wrong" invites the model to compose a different sentence.

  That needed a per-run value, which a class-level tool list cannot hold, so the six tasks share one
  base class now. It deleted six byte-identical `__init__`s and six per-task validator declarations
  — and exposed six test functions that asserted "no network tool is ever registered" against a
  ClassVar that is now empty, i.e. against nothing.

  The reader-facing half was fixed too: a reference card now explains what "unverified" MEANS (the
  coordinate could not be found — the quote may be fine and filed at the wrong address), shows the
  server's own reason, and no longer renders an empty box for the one citation someone most wants to
  inspect. A long locator can no longer stretch the card until the rest of the row falls out of it.

- **`long` podcasts could not finish.** One 502'd at the 300s default backstop with a trace holding
  three events: started, read two skills at 6.8s, then nothing for 293 seconds until `killpg`. An
  ordinary chat answer on the same notebook and model took 77s across 4-5 turns, one of them 54s
  alone — so the tier shipped unable to complete under its own default. The backstop scales with the
  requested tier now; a runaway chat turn stays bounded where it always was.

- **A Traditional-Chinese interface produced an English notebook title.** The one place the reader
  had actually said which language they read was never sent — language resolution weighed the OS's
  `Accept-Language`, the sources, and any typed questions. The interface language is a fourth signal
  now, ranked above `Accept-Language` because it was chosen rather than inherited. The two settings
  stay separate: a Chinese interface over English papers is still expressible, just stated rather
  than default.

  And no artifact translates a proper noun any more. "Trinity" stays "Trinity" — a translated name
  is the one term a reader then cannot search for. One shared rule, in every task and the titler.

- **The run's reasoning moved out of the chat bubble into a Trajectory drawer.** The inline step log
  put the planner's own prose inside the answer, which a user reported as unreadable and
  space-consuming. Full parity with a sibling project's own trajectory drawer, at the user's
  explicit choice: turn nav, a tool timeline whose segment width tracks real elapsed time, a detail
  pane, search, and a replay that dwells on each turn for the time it really took.

  The decomposition is server-side and keeps the run's two clocks apart — per-turn timing is
  reported only when the trace was live-stamped, never invented for an older one. It reads a trace
  that is still being written, which is the point for a run that takes minutes. Verified with a DOM
  shim under `node` against a real 12-turn trace, since this project has no JS test runner.

- **Scrollbars are themed.** The UA paints them from the OS theme, not the page's, so the dark theme
  had a near-white bar down the middle of every scroller. Both spellings ship, because neither
  covers the other's browsers.

- **A citation's hover says what the source IS.** It read `s1 · whole` — the interface's own filing
  system. Clicking one now OPENS its reference card at the quote that was clicked, rather than
  scrolling to a collapsed row and leaving the reader to work out which of its quotes was theirs.

- **The independent review of this batch found the podcast-timeout fix revertible with a green
  suite.** Its tripwire asserted the tier factors were monotonic, which is true of an all-equal
  table — i.e. of no scaling at all, the exact state that 502'd the reported episode. Flattening it
  to `{1.0, 1.0, 1.0}` passed 539 tests. The same review disabled descent into nested models in the
  new coordinate check and the suite stayed green too, which would have silently unguarded FAQ,
  Timeline and the podcast — three of the six tasks, including the one the marker check had already
  spent a slice living only on.

  Three real UI defects came out of the same pass. The drawer's live poll rebuilt everything every
  four seconds, throwing away the reader's selection and search box — in the one case reading a
  live trace exists to serve. The backdrop kept eating clicks for the 280ms of its own fade-out, a
  short-lived form of the failure invariant 36 records. And five new controls carried both
  `data-tip` and the native `title`, which invariant 47 had removed for showing two tooltips.

  Every one of those is pinned now, and each mutation was replayed to confirm it fails — including
  one where the first fix was itself defeated: a token check on `markWantedQuote` passed with the
  function's body replaced by `return;`.

- **The build-across-turns rule reaches all six tasks now, not just the podcast.** It is must-apply
  by its own account — skipping it loses the whole run to a truncated reply — and it lived in one
  prompt while the other five relied on an OPTIONAL skill a model may never open. Invariant 65 had
  recorded that as the single unclean line of the prompt/skill split; this closes it.

  Worded conditionally, because the rule is not "always accumulate": a short answer built across
  turns wastes the step budget just as surely as a long one written in a single reply loses the
  run. The podcast keeps its tier-specific warning (60-90 utterances is a fact about that task) and
  no longer restates the mechanic — one copy, pinned by a tripwire over all six.

- **A user asked whether the chat should be frozen while an overview regenerates. It should not —
  but the question found a real bug next door.** `renderChatOverview` clears the element that holds
  the run's progress dot and its only Stop, and adding or removing a source calls it. So a source
  added mid-generation wiped both, while a deliberate decision one line away (not bumping the
  generation token, so a paid-for run is never stranded) kept the run alive with no way to see or
  cancel it until it landed minutes later. Two individually-right decisions that had never been
  checked together. The panel is owned by its run now, exactly as invariant 60 already does for a
  pending chat turn.

  A notebook switch has to RELEASE that ownership rather than only strand the run, or the new
  notebook keeps the old one's status node — and a pre-existing sibling turned up in the same
  function: the "superseded" note was written into `#chat-overview` even when the reader had
  switched notebooks, overwriting a different notebook's overview with a note about a run it never
  started.

  The original question's answer: the two runs are independent, both writes land under the
  per-notebook lock, and neither repaint can now delete the other's run. Blocking the composer for
  a multi-minute run would cost more than it protects.

  **REVERSED later in this same slice** — see "The chat composer is frozen while an overview
  generates" below. The technical half of this paragraph still holds (nothing was ever at risk);
  what changed is that the user asked twice, and whether two runs LOOK like they are fighting is
  their call rather than a question the locking answers.

- **An overview could only be regenerated if something had INVALIDATED it.** A user asked how to
  press "↻ Regenerate" while looking at an overview whose five citations had all failed coordinate
  verification — the stored form of the defect fixed earlier in this slice. The button was gated on
  the overview being stale or incomplete; their sources had not moved and the FAQ half had
  succeeded, so it was not on the page at all. An artifact that is current and complete but simply
  wrong is a real state, and it was the one with no way out.

  It is always offered now. The flag picks the label and the weight rather than the existence:
  quiet when nothing is wrong, because regenerating costs two real model runs and must not be the
  loudest control on a panel that already holds what it makes; louder and explicit when stale or
  incomplete. The same three-state shape the podcast's own button has had since it was persisted.

- **"完成" appeared next to a live Stop button, and the pairing was the tell.** `/overview` runs two
  tasks and its ticker follows only the summary; forwarding that run's terminal event made
  "Finished" the whole action's headline while the FAQ half was still going and the POST had not
  returned. Measured on the user's own run: a 63KB summary trace beside a 226-byte FAQ trace whose
  worker was still alive. Invariant 60's rule broken by a second RUN rather than by a phase — so the
  fix reuses the same `setPhase` seam that invariant added, naming the second half honestly and
  keeping Stop available, because that half really is cancellable.

- **The chat composer is frozen while an overview generates.** Asked for by the user twice, and not
  because of a race: the runs are independent, both writes land under the per-notebook lock, and
  neither repaint can delete the other's run. Nothing was ever lost. The reason is that a question
  asked into a thread whose overview is being rewritten reads as two things fighting whether or not
  they are — a product decision, recorded as one so it does not get simplified away later as
  redundant with the locking.

  The composer only. Clearing the conversation was the offered alternative and is the one thing not
  to do: it would destroy history to signal a transient state.

- **A user pressed the steps pill and got the old inline reasoning log back.** Their browser was
  running the previous `app.js`; the server was serving the new one. Starlette's static files carry
  an ETag but no `Cache-Control`, so the browser was on heuristic caching — and this is a zero-build
  app whose filenames carry no content hash, so there was no cache-busting URL either. The assets
  now say `no-cache`, which means revalidate rather than don't store: unchanged assets still cost
  one conditional request and a 304 with no body.

- **The steps pill still expanded inline after a hard reload, and the cache was not the reason.**
  There are TWO "⌁ N steps" affordances: the live one during a run, and the persisted one under a
  finished artifact — which is the one a reader presses most, because most of the time the run is
  over. Only the live one had been moved into the Trajectory drawer. The previous entry's
  cache-revalidation fix is a real improvement and was not the cause of this.

  Both open the drawer now. `.ticker-detail`/`.ticker-row` and their CSS are gone, and the
  invariant-36 tripwire — which had `.ticker-detail` as one of its two anti-vacuity sentinels —
  gained a route for a bare `hidden` attribute in the markup. That is the ordinary spelling of the
  very attribute the tripwire polices, and all four of its existing routes were blind to it.

- **The Trajectory drawer was cramped, and the first pass is the lesson.** The sibling's data model
  had been ported faithfully and then a UI was invented for it: 0.75rem rows, a 0.85rem-tall bar
  strip, `flex-grow` segments that divided the strip into slivers. A user put the two side by side
  and rejected it — every fact was present and none of it was legible.

  The structure and proportions are ported now: a header carrying the task name and the run's
  totals, transport as one segmented control, the timing note as a labelled callout, timeline
  BLOCKS with icon/label/duration that keep a readable minimum width and scroll rather than squash,
  a turn nav of cards each with a preview line and a duration bar, and a detail pane that sets the
  model's reasoning as prose rather than as another monospace dump.

  The worker also records what the run was configured with — model names and budgets, never
  credentials — because the "Initial state" panel was built from a meta holding only the task name,
  which the header already showed.

- **A timeline segment was slicing its own label in half.** Three stacked lines in a 72px box with
  `overflow: hidden`, and at the browser's default line-height they measured 74.3px. A test now
  recomputes that sum from the stylesheet and fails when it exceeds the box, so the next size change
  cannot reintroduce it quietly.

- **"Initial state" carries the run's real metadata now.** It held the task name — which the drawer
  already shows as its headline — and nothing else. It carries the models, the budgets, the corpus
  size and every short scalar input the run was given: the question, the resolved language, the
  requested podcast tier. The corpus text never goes in, only its size; credentials never go in at
  all. Verified against a real run rather than assumed.

- **The timeline's sizing was reimplemented from memory and wrong twice, in opposite directions.**
  `flex-grow` against the strip's total made slivers; a fixed width then left a run with one tool
  call sitting at 316px beside empty space, which a user reported. It is `flex: <duration> 0
  <floor>px` now — the sibling's own sizing, read out of its `renderTimeline` rather than guessed
  from its stylesheet. Grow fills a short run's strip; the floor keeps a fast call legible and lets
  a long run scroll instead of squashing.

  A segment's label is the TARGET now (`corpus-navigation`), not `skill corpus-navigation` — the
  family is already the icon and the colour. Its offset and owning turn moved to the detail pane,
  where clicking a segment lands anyway and where nothing clips them: a tooltip on a segment is
  clipped by the segment AND by the scroller around it.

- **The model was numbering its own citations.** One overview carried `[1]`..`[8]` in its prose
  while holding six citations, so the page showed two numbering systems and they disagreed. The
  interface numbers them; the prompt now says so. Prompt-only on purpose — `arr[1]` is ordinary
  prose here, so a display-layer strip would corrupt real text to tidy a number.

- **A chat answer can be regenerated now.** The overview, the podcast and every Guide kind had a way
  to be redone; a chat answer did not, so one the reader was unhappy with was permanent. It sits in
  the row that answer's other affordances already occupy, at the same quiet weight — re-answering
  costs a full model run and should not be the loudest thing under an answer.

  The LAST turn only, and that is correctness: every later answer was produced with this one in its
  history, so redoing a middle turn would leave the answers after it derived from a conversation
  that no longer exists. The server re-checks inside its lock and appends instead of replacing when
  the question no longer matches, so a regenerate that lands late can never overwrite a turn it did
  not mean to.

- **The empty "Initial state" now names which empty it is.** A user asked whether the
  "recorded before the app saved these details" branch could go away once the old traces were
  deleted. It cannot: the trace file is reserved before the run spawns, so a run opened in its first
  moments — or one whose spawn failed, or one killed instantly — has a real file with zero events.
  What had to go was the WORDING, which named a cause the cleanup makes unreachable.

- **A conversation can be cleared.** Turns were append-only — a source could be deleted and a note
  could be deleted, but a chat could only grow — so "start over" was impossible, and regenerate
  reaches the last answer only (every later one was produced with it in `history`). Sources, notes,
  the overview and the podcast are kept, and the confirmation says so: losing sources is the fear a
  destructive control in the chat panel invites.

- **A tooltip at the left edge of the chat was clipped**, photographed arriving with its first
  characters sliced off. The default tip anchors right, so a 15rem panel on a left-edge control
  extends off the scroller — which clips horizontally, because an `overflow-y: auto` box computes
  `overflow-x` to `auto` too. Anchoring it into the space the control actually has is the fix, and
  this stylesheet already did exactly that elsewhere. Deleting the tooltips was the first instinct
  and would have removed working information to avoid a positioning bug.

- **An independent fact-check of this batch's documentation against its code found nine problems,
  and the sharpest was a claim in an OLDER invariant that today's work had quietly falsified.**
  Invariant 48 still said the interface language "is never sent to the server, and never reaches a
  prompt" — both halves untrue since it became a language-resolution signal earlier in this same
  slice. `i18n.js`'s own header had been rewritten for exactly that; the invariant had not.

  Also corrected: a sentinel list miscounted as two when it has six; a stylesheet comment whose
  arithmetic said 64.6px where recomputing from its own values gives 66.7px (the fix was right, the
  sum beside it was not); two contradictory CHANGELOG entries on freezing the chat composer, with
  nothing saying the first had been reversed; an invariant asserting a root cause that a LATER
  invariant records as having been wrong; an enumeration of "three callers" that was five, listed
  one of them twice, and disagreed with the code comment beside it; a `tickerLogs` comment keeping
  a paragraph the next paragraph retracts; and `web/DESIGN.md` — tracked and shipped in the wheel —
  still documenting an element that was deleted.

  And one new test did not pin what it claimed: inserting `return;` at the top of `syncClearBtn`
  left the suite green, because every substring it checked still matched the dead code below. That
  is the identical defeat this batch already recorded fixing for `markWantedQuote`, made again in
  the very next test written.

- **An independent review of the clear-conversation slice found three real defects in one handler,
  all by driving the shipped source under stubs rather than reading it.** Clearing while a question
  ran deleted the turns and then let that question's answer be appended to the empty list, so the
  conversation came back with one entry; the repaint took the running question's row and its only
  Stop with it; and nulling the pending turn made the ask's own error handler throw on a null, so a
  run that failed after a clear showed nothing at all. Clearing is disabled during a run now, and
  the handler carries the pending row and the notebook generation the way every other awaiting flow
  here already did.

  Its test was hollow in both directions — deleting every call site (leaving the control permanently
  hidden, the feature entirely dead) and inverting the visibility condition both left 563 tests
  green. It pins the condition as an expression, the five call sites by count, and each of the three
  handlers by name now. The first rewrite of that assertion matched a DIFFERENT init function's
  `notebook:switched` subscription, which is its own small lesson: in a file where four inits spell
  the same event, a test that says "the handler" has to say which.

- **`line-length = 110` was never enforced.** It is a formatter setting, ruff's default rule set has
  no `E501`, and the name scrub duly left a 157-character line that `check` passed. CLAUDE.md said
  the command enforced it; it says what is true now. Twenty over-long lines predate this and
  rewrapping them plus enabling `E501` is a follow-up, not a silent bundled edit. *(Done later in
  this same section: the rule is selected via `extend-select` and all 19 offenders are rewrapped.)*

- **The Chinese interface carried English dashes, which is a translation artifact rather than a
  translation.** A user photographed "PDF、TXT 或 Markdown——一次一個檔案。" — the dash renders as a
  long rule and reads like a glyph run that failed to resolve. Fifteen strings had it, in three
  different spellings within one file: `——`, a SPACED `——` (the dash is already full-width, the
  spaces are the English habit) and a half-width `—`. Chinese punctuation carries the same joins a
  dash was standing in for: a comma continues, a semicolon separates two complete thoughts, a colon
  labels. A test now fails on any dash inside the string table, and only inside it — the file's own
  comments are English prose and keep theirs.
