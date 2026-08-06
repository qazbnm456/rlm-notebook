"""`GeneratePodcastScript` — the RLM task behind the Audio Overview (`rlm-notebook audio`).

Same citation-grounded `RLMTask` pattern as `AnswerQuestion`/the Notebook Guide tasks: one input
field (`sources`), one output field (`script: PodcastScript`), sharing `instructions.py`'s
citation-marker and validate-before-submit rules. Audio synthesis itself (`tts.py`) runs entirely
AFTER this task returns, on its already-citation-checked output — this module produces text only.
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
