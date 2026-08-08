"""`GeneratePodcastScript` — the RLM task behind the Audio Overview (`rlm-notebook audio`).

Same citation-grounded `RLMTask` pattern as `AnswerQuestion`/the Notebook Guide tasks: two input
fields (`sources` and, since invariant 39, `output_language`), one output field
(`script: PodcastScript`), sharing `instructions.py`'s citation-marker and validate-before-submit
rules. Audio synthesis itself (`tts.py`) runs entirely AFTER this task returns, on its
already-SCHEMA-VALIDATED output — this module produces text only. (Not "already citation-checked":
nothing gates synthesis on verification, and an independent audit flagged the stronger phrasing as
exactly the kind of upgrade invariant 5 forbids. Citations are computed for DISPLAY alongside the
transcript.)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from rlm_harness import RLMTask
from rlm_harness.tools.validation import make_schema_validator

from .instructions import CITATION_RULES, artifact_language_rule, validate_before_submit_rule
from .schema import PodcastScript

__all__ = ["GeneratePodcastScript"]

_INSTRUCTIONS = f"""\
You are writing the script for a two-host podcast episode ("Audio Overview") that discusses the
sources in this notebook — the kind of natural, conversational back-and-forth two people have when
one is explaining something interesting to the other, NOT alternating monologues or a dry
recitation of facts. Ground EVERY substantive claim ONLY in the `sources` text given to you as a
REPL variable — never your own background knowledge. If the sources don't support a claim, leave
it out rather than filling the gap from what you already know.

There are exactly two speakers, `host_a` and `host_b` — do not invent a third, and do not let one
host dominate; a good episode has both contributing roughly evenly, asking each other questions,
reacting, and building on what the other just said. Aim for a natural episode length given how much
the sources actually contain — a handful of substantive exchanges for a short source, more for a
long or dense one; do not pad with filler to hit some target length, and do not try to cover every
single detail in the sources at the cost of a natural conversation.

Give the episode a SHAPE. It has three parts, and the last one is the one most easily forgotten:

1. An opening that says what these sources are and why they are worth half an hour of someone's
   attention — one or two turns, not a formal preamble.
2. The body: the substance, in whatever order makes the conversation work. Follow the interesting
   thread rather than the order the sources happen to be in.
3. A CLOSE. Do not simply stop when you run out of facts. Land it: one host briefly draws the
   threads together, and then the two of them say what it adds up to — the implication, the tension
   that is still unresolved, the thing that changed how they see it. Ground that reflection in what
   the sources actually support; "what this makes me wonder" is honest, inventing a finding is not.
   An episode that ends mid-fact feels broken even when every fact in it was right.

**Write to be SPOKEN, but keep a name as its source wrote it.** This script is read aloud AND read
on screen, and the same `Utterance.text` is both — so a proper noun, a product, a standard or an
identifier stays in its original form (`Voyager 1`, `NASA`, `CVE-2026-1234`), not transliterated
into your own language. The transcript is what a listener falls back on when a word does not come
through clearly, and a rewritten name is exactly the word they cannot look up.

Numbers, dates and units DO get written the way they are spoken rather than the way they are
printed — those read aloud badly in every language and nobody needs to look them up. (A
`Citation`'s `quote` is verbatim regardless: it is evidence a reader checks against the source.)

{artifact_language_rule("the language named by the `output_language` variable")}

{CITATION_RULES}

{validate_before_submit_rule("validate_podcastscript")}
"""


class GeneratePodcastScript(RLMTask):
    """Generate a two-host podcast script grounded in a notebook's sources, with citations."""

    signature = "sources: str, output_language: str -> script: PodcastScript"
    output_field = "script"
    output_model = PodcastScript
    instructions = _INSTRUCTIONS
    tools: ClassVar[list[Callable[..., Any]]] = [make_schema_validator(PodcastScript)]
