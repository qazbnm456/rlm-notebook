# Invariant 45 — The podcast script has a stated shape

**The podcast script has a stated SHAPE, and is written to be SPOKEN in one language.** Asking
only for "a natural conversation" gave episodes no opening, no segment plan and no close — they
stopped when the model ran out of facts. The instructions ask for an opening that frames the
sources, a body that follows the interesting thread rather than the sources' order, and a CLOSE
that draws the threads together, with any reflection grounded in the sources ("what this makes me
wonder" is honest, inventing a finding is not).

**There is EXACTLY ONE close and it is written LAST, after every source the model means to use
has been covered — a rule that exists because this one and invariant 64 had never been checked
together.** The shape rule asks for a close; invariant 64 asks for a long script to be
ACCUMULATED across REPL turns. Neither said where the close goes, so a model that finishes a
batch writes a concluding exchange for it, then finds material it had not reached and keeps
going. Measured on a real 70-utterance episode: `感謝大家收聽` / `再見` at utterances 48-49,
then a step that read an unused section of the sources, then twenty more turns ending in a
SECOND close. The listener hears the episode end and restart. Prompt-only, with invariant 4's
residual-risk hedge.

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

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
