# Invariant 39 — Prose follows the reader; coordinates follow nothing

**Model-authored prose follows the READER's language, not the documents'. Citation coordinates
never follow anything — and naming a language buys neither its SCRIPT nor its IDIOM.**

**The carve-out is the load-bearing half, and it covers coordinates, not just quotes.**
`citations.verify_citations` compares `locator` with an exact `==` and never inspects `quote` at
all (invariant 5) — so a model told "write everything in Chinese" that helpfully localises
`page:1` to `第1頁` turns every citation UNVERIFIED, and one that translates a `quote` produces a
citation still wearing a ✓ badge while no longer being the source's own words.
`instructions.VERBATIM_COORDINATES` names `source_id`, `locator`, the marker syntax AND `quote`
together, and is composed BEFORE `CITATION_RULES`.

**Two things a language NAME does not settle, each with its own rule.**

- **SCRIPT** (`instructions.SCRIPT_PINNED`): a language with more than one script is
  under-specified by its name, and a model treats the scripts as interchangeable. A sibling
  project shipped a Traditional Chinese document set whose page bodies were Traditional while
  every page TITLE came back Simplified, so the nav and the page disagreed on screen — the rule
  names the characters (`概览` must be `概覽`) because that cannot be read as a loose synonym.

  **It is worded CONDITIONALLY and shipped UNCONDITIONALLY, and that is forced rather than
  chosen.** The first version was a table keyed on the language NAME (`_SCRIPT_RULES`, matched
  by `_script_rule`) — but the language arrives as a SIGNATURE FIELD, so all three call sites
  compose their rule at import time with the literal placeholder
  `"the language named by the \`output_language\` variable"`, which matches nothing. It returned
  the empty string for every task, in production, from the day it shipped, and three documents
  described it as working. The sentence beside it (`Write your prose in {language}`) had been a
  conditional the model evaluates all along; only the script half was written as an import-time
  branch. **A test that calls `artifact_language_rule("Traditional Chinese")` cannot see this** —
  that call shape occurs nowhere in the product — so `tests/test_instructions.py` asserts on the
  six SHIPPED task classes instead, and a mutation to `_script_rule` was killed by the old test
  while the feature was entirely dead. Passing for a reason unrelated to its name, at FEATURE
  level rather than assertion level.

  **A `zhconv` CONVERTER is the wrong shape for this and stays refused**: it rewrites `干`, `台`,
  `群` and `里`, which are ordinary Traditional characters this project's own notebooks use
  correctly. What is built instead is a reject-and-look-again check (invariant 66's fourth), and
  what justifies it is that the correct output is demonstrably knowable BY THE MODEL — asked
  directly it writes `霍爾木茲海峽` correctly, while composing 4000 characters of dialogue it does
  not. The residual drift is a COMPLIANCE problem, not a knowledge one. **When a measurement
  leaves a capability question open, ASK THE MODEL before designing around the answer** — that
  one cost less than a thousandth of the episode that raised the question.

  **A PROPER NOUN outranks the script rule, and the rule says so ONCE, covering both
  directions** — the two collide whenever the sources spell a name in the other script, and
  nothing stated a precedence until the clause was added. It rests on a GENERAL argument (the
  sibling's Simplified-source case is real and this project cannot rule it out), **not on any
  observation here**: the incident once recorded as motivating it was checked against the corpus
  and did not happen. A superseded table carved the exception out of the Traditional rule only
  and left the Simplified rule with the mirror-image exposure.

  **The failure mode to watch for is a PARTIAL conversion — worse than either whole answer.**
  With the rule shipping, one episode produced `霍爾木茲海峡` six times: `尔`→`爾` and `兹`→`茲`
  converted, `峡`→`峽` not. That string is neither the Simplified spelling nor the Traditional
  `霍爾木茲海峽`, so it is searchable in NEITHER — precisely the harm the proper-noun exception
  exists to prevent, reached by a route nobody had considered, because "keep the name" and
  "convert the name" were assumed to be the only two outcomes. **OPEN**: whether "stays exactly
  as they spell it" has to forbid a partial conversion in as many words — it plainly was not read
  that way once. Arms, counts and the three corrected readings are in `CHANGELOG.md`.
- **REGISTER** (`NATURAL_REGISTER`): observed here. A Traditional Chinese answer wrote `源文`
  for "the source text" where a reader expects `原文` — a word-for-word rendering of the English.
  No script rule can reach it, because 源 and 原 are both ordinary Traditional characters, so
  this is about WORDING and applies to a single-script language too.

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

**Everything above about what the MODEL does was verified live, on both paths, and could not have
been otherwise**: the offline tests drive a scripted LM and can demonstrate none of it (invariant 4's
residual-risk note applies with full force). Forced Chinese against English sources returned Chinese
prose with `s1`/`whole` untranslated, English quotes verbatim and every citation verified.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
