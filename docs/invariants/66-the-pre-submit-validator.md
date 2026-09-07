# Invariant 66 — The pre-SUBMIT validator

**The pre-SUBMIT validator is `instructions.make_grounded_validator` for EVERY task — schema plus "no
`[[SRC:...]]` marker in the model's own prose" — and SUBMIT belongs on a LATER REPL TURN than
the call that validated.**

"Only submit after it reports success" was read as an ORDERING WITHIN ONE CELL, and a real run
duly wrote `print(validate_podcastscript(json_str))` followed by `SUBMIT(final_output)`. That
validates nothing: the verdict is printed where the model cannot act on it, because the submit
beside it has already run. **`_SCRIPT_REPORT_LIMIT` cannot rescue that** — the limit governs how
many times the validator will REJECT, and a model in that shape asks ONCE. The rule names the
anti-pattern with the task's own tool name substituted in, and offers a guarded single cell as the
alternative. **Confirmed live, and it needed BOTH halves** — the ordering rule and the raised limit;
still one run, so invariant 4's hedge applies.

The marker check was written for the podcast, whose failure was loud (the voices read the markers
aloud), but it was a guard on the SYMPTOM: `GenerateSummary` produced the same defect silently. Six
tasks each holding their own validator is how one of them ended up with a check the other five lacked.

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

**A FOURTH check, and the only one here that is allowed to be wrong**: when the run's resolved
`output_language` names a Chinese variety (`script_family`, from the `arun` kwarg — matching on
the language NAME is correct HERE and was wrong in the prompt, which only ever sees invariant
39's placeholder), every character of the model's own prose is tested against the other
script's inventory.

- **The SUGGESTION is computed IN CONTEXT, because a character-level table cannot answer it.**
  `历` is `歷` in `历史` and `曆` in `日历`; `发` is `發` in `发现` and `髮` in `头发`; `汇` is
  `匯` in `汇率` and `彙` in `词汇`. A table gives whichever form is commoner, so a table-driven
  validator names the WRONG character whenever the word is the less common one. The whole string
  is converted instead (`zh-hant` is phrase-aware and script-only) and each offender takes the
  character at its own index, falling back to the table if the conversion changes LENGTH.
- **The SUGGESTION is also the REGION's standard, not merely a Traditional form** — and the two
  rules compose in ONE direction only: the regional preference applies where the phrase-aware
  pass made no choice of its own (it agrees with the plain single-character answer), never over
  one. Applying it unconditionally would lose `日历`'s `曆` back to `歷`, which is the defect
  above reintroduced from the other side. `zh-hant` maps `为` to `爲` where Taiwan writes `為`,
  and the same for `众`/`眾`, `启`/`啟`, `账`/`帳` and `伪`/`偽`. Each is post-mapped through
  `zh-tw`, **from the SOURCE character rather than from `zh-hant`'s answer** (the two disagree on
  nine characters and via-source is right on all nine), and **SINGLE-CHARACTER only**, because
  `zh-tw` carries a VOCABULARY layer that rewrites `鼠标` to `滑鼠` and would misalign a
  positional zip.
- **The 131 characters the codec lets through are ENUMERATED, not characterised**
  (`_BIG5_SHARED`, 52 of them; the other 79 are flagged despite the codec).
  `test_the_big5_letthrough_is_fully_classified` asserts the two halves cover the codec's
  let-through EXACTLY, so a zhconv upgrade fails the build rather than landing an unread
  character in the unflagged half.

  **SHARED means a live Traditional use the PHRASE TABLE does not protect.** Where it does
  (`皇后`, `茶几`, `划船`, `拮据`, `佣金`, `老么`, `尸位素餐`, `夸父`, `并州`, `云云`,
  `于右任`, `洪适`) the character is flagged and `_actionable` drops the self-suggestion, so
  the exemption is spent only where it is needed. `_actionable` is NOT a substitute for the
  list: over 27 ordinary Traditional words it rescues four and leaves 23 (`干預`->`幹`,
  `台灣`->`臺`, `里程碑`->`裏`, `高峰`->`峯`, `秘密`->`祕`, `神采`->`採`, `征服`->`徵` …).

  **A PROPER NOUN keeps a character SHARED even where the Simplified drift is commoner**, and
  that is where this list deliberately diverges from a sibling project's: `范` (范仲淹), `余`,
  `涌` (東涌), `涂`, `朴`, `杰`, `岳`, `郁`. Invariant 69 forbids translating a name and an
  obedient model told `范 -> 範` writes `範仲淹`. That project ranks them the other way because
  its corpora are technical rather than literary corpora; both answers are defensible and the reason is recorded rather
  than averaged. `吁` and `咨` are the same call on an idiom, and are its weaker half.
- **The membership test is BIG5-ENCODABILITY, not `zhconv`'s own `SIMPONLY` set.** That set was
  tried first and contains `干`, `台`, `群` and `里` — ordinary Traditional characters this
  project's real notebooks use correctly (`干預`, `一台`, `里程碑`) — so it would condemn good
  prose. Big5 answers the question that matters, "does this glyph exist in the Traditional
  inventory at all". `zhconv` is still the dependency, for the SUGGESTION (`对 -> 對`) and to
  bound the set to known Simplified forms so a rare Traditional character outside Big5 is not
  flagged.
- **Recall is deliberately imperfect; precision is BOUGHT, not free.** `_actionable` drops any
  offender whose fix equals the character it already has — which is what `_suggest` returns
  wherever the phrase-aware pass confirms the character is right in that word. Without it the
  check rejected `拮据` with `据 -> 据` and `恒生` with `恒 -> 恒`, and sixteen gate characters
  have such a context. A missed character is one wrong glyph on screen; a false one is a
  rejection the model cannot satisfy, which is the failure invariant 66 exists to forbid.
- **It is BOUNDED at `_SCRIPT_REPORT_LIMIT` (3) rejections per run, and the bound is the design
  — but ONE was measured too few, in BOTH directions.** Every other check here rejects
  something WRONG; a Simplified character is COSMETIC, and the detector cannot tell one from a
  Japanese glyph being quoted inline — `学`, `会`, `国` and `峡` are shinjitai, and this
  project's own corpora carry Japanese. A blocking check the model cannot satisfy spends the
  step budget looping and loses a paid-for episode over one glyph, which is the trade the "net
  must not destroy what it was protecting" rule below already refuses. At ONE, a non-compliant
  model's single look bought nothing, and a COMPLIANT model that fixed and re-validated was told
  `success` on its second call whether or not it had fixed anything — so the bound lied to the
  model that deserved a real answer. Three gives fix, verify, and one more fix, at a worst case
  of three planner turns against `max_iterations=25`. `quote` is exempt for the same reason it
  is exempt from the marker walk, one step sharper.
- **Measured live, A/B across three episodes, and it is the one significant number in this
  area — with a caveat attached that does not come off.** Six of the seven flags in the control
  arm are `峡`, a character the check's own rejection message tells the model it may keep, so
  the significance rests on a character the rule does not clearly require changing; and the CLI
  writes no trace, so whether the validator FIRED is unobservable. Arms, counts and the Poisson
  arithmetic are in `CHANGELOG.md`. The accepted recall loss is real and showed up once (`厘清`
  survived; `厘` is valid Big5 for `公厘`).

**A sibling project solves the same problem in a DIFFERENT PLACE, and that is why its
output was stable while ours was not.** It runs HOST-SIDE and POST-HOC in its pipeline, not
before SUBMIT: `output_language_mismatch` is a MAJORITY comparison on page BODIES (advisory,
tolerant — "a single stray character in several thousand says nothing"), `strict_script_offenders`
is per-character on page TITLES ONLY, and `to_script` actually REWRITES a title and persists it.
So a prompt rule that turns out to be inert costs that project nothing; this project had only
the prompt, and when the prompt was inert there was nothing underneath. **Its split is by FIELD
rather than by a global strictness dial** — strict where the text is short, navigational and
entirely the model's own words; majority where it quotes source — and that reasoning is better
than ours was.

**What does NOT transfer is its membership test.** It asks "would the zhconv table rewrite this
character", with a hand-kept `_KEEP_AS_WRITTEN` of ONE character (`台`) — so run against correct
Traditional prose its own shipped functions report `干` in `干預`, `里` in `里程碑` and `群` in
`一群`, and `to_script` would PERSIST `幹預`, `裏程碑` and `一羣` into a title. Big5-encodability
answers it with no hand list. Its four measured title offenders (`览 门 块 统`) are caught either
way.

**The MIRROR direction is NOT enumerated and still uses the codec** (`_BIG5_SHARED["hans"]` is
empty, GBK decides, 652 flagged). Collapsing the two branches into one is what shipped once:
an `encode` call with no `continue` after it makes the codec dead code, and with no enumeration
to replace it the Simplified direction had no gate at all — 4,704 flagged, every Japanese
shinjitai and every retained Simplified form (`瞭` in 一目瞭然, `徵` in 宫商角徵羽) with them.

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

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
