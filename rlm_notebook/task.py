"""`AnswerQuestion` — the RLM task this slice's `ask` command drives.

A thin `RLMTask` declaration, per the sibling projects' convention: `signature` names three input
fields — `sources` (the corpus blob `Corpus.blob()` assembles, injected into the sandboxed REPL as
a plain variable per rlm-kit's native mechanic — see `corpus.py`), `history` (prior turns in this
notebook's conversation, as plain text — see `notebook.py:history_text`), and `question` — and one
output field, `answer: Answer`. Everything else (retry, sandbox selection, budget caps, tracing) is
inherited from `rlm_kit.RLMTask`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from rlm_kit import RLMTask
from rlm_kit.tools.validation import make_schema_validator

from .schema import Answer

__all__ = ["AnswerQuestion"]

_INSTRUCTIONS = """\
You are answering a question grounded ONLY in the `sources` text given to you as a REPL variable —
never your own background knowledge. If the sources don't contain an answer, say so; do not fill
the gap from what you already know.

`history` is the prior turns of this same conversation (earlier questions and your earlier
answers), oldest first, as plain text — use it ONLY to understand what a follow-up question refers
to (e.g. what "it" or "that" means), never as a source of facts or citations in its own right. A
past answer is not automatically still correct: re-derive and re-verify every claim and citation in
THIS answer from `sources` fresh, exactly as if `history` did not exist for grounding purposes. If
this is the first question in the conversation, `history` says so plainly.

`sources` is a single string containing every source in this notebook. Each citable block is
preceded by a marker line of the EXACT form `[[SRC:<source_id>|<locator>]]`, immediately followed
by that block's text. Explore `sources` with Python — `.find()`, slicing, splitting on the literal
substring "[[SRC:" — to locate the passages relevant to the question; you have not already been
shown its contents above, so read before you answer.

Markers are OPAQUE identifiers, not something you compute. When a claim in your answer relies on a
block, copy that block's marker's `source_id` and `locator` VERBATIM into a `Citation` — never
invent, alter, guess, or reconstruct one from surrounding context. If you cannot find a marker
supporting a claim, leave that claim uncited rather than fabricating a citation for it; an
uncited claim is honest, a fabricated citation is not.

Before you SUBMIT, validate your draft JSON against the expected schema with the `validate_answer`
tool, and only submit after it reports success. That tool checks JSON SHAPE only — it does not, and
cannot, confirm your citations point at real sources; a separate check does that after this run
ends, so getting the shape right here is what you are responsible for.
"""


class AnswerQuestion(RLMTask):
    """Answer one question grounded in a notebook's corpus blob, with citations."""

    signature = "sources: str, history: str, question: str -> answer: Answer"
    output_field = "answer"
    output_model = Answer
    instructions = _INSTRUCTIONS
    tools: ClassVar[list[Callable[..., Any]]] = [make_schema_validator(Answer)]
