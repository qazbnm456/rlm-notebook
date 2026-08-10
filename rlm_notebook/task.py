"""`AnswerQuestion` — the RLM task this slice's `ask` command drives.

A thin `RLMTask` declaration, per the sibling projects' convention: `signature` names four input
fields — `sources` (the corpus blob `Corpus.blob()` assembles, injected into the sandboxed REPL as
a plain variable per rlm-harness's native mechanic — see `corpus.py`), `history` (prior turns in this
notebook's conversation, as plain text — see `notebook.py:history_text`), `question`, and `output_language` (invariant 39) — and one
output field, `answer: Answer`. Everything else (retry, sandbox selection, budget caps, tracing) is
inherited from `rlm_harness.RLMTask`.
"""

from __future__ import annotations

from .instructions import (
    ACCUMULATE_LARGE_OUTPUTS,
    CITATION_RULES,
    GroundedTask,
    chat_language_rule,
    validate_before_submit_rule,
)
from .schema import Answer

__all__ = ["AnswerQuestion"]

_INSTRUCTIONS = f"""\
You are answering a question grounded ONLY in the `sources` text given to you as a REPL variable —
never your own background knowledge. If the sources don't contain an answer, say so; do not fill
the gap from what you already know.

`history` is the prior turns of this same conversation (earlier questions and your earlier
answers), oldest first, as plain text — use it ONLY to understand what a follow-up question refers
to (e.g. what "it" or "that" means), never as a source of facts or citations in its own right. A
past answer is not automatically still correct: re-derive and re-verify every claim and citation in
THIS answer from `sources` fresh, exactly as if `history` did not exist for grounding purposes. If
this is the first question in the conversation, `history` says so plainly.

{chat_language_rule("the language named by the `output_language` variable")}

{CITATION_RULES}

Also fill `follow_ups` with two or three questions a reader might naturally ask NEXT, in the same
language as your answer. Each one must be answerable from `sources` — they are an offer, so
proposing something the corpus cannot support wastes the reader's next turn. Keep them short and
specific; skip any that just rephrase the question you were asked. If nothing worthwhile follows,
leave the list empty rather than padding it. They carry no citations: a question is a prompt, not
a claim.

{ACCUMULATE_LARGE_OUTPUTS}

{validate_before_submit_rule("validate_answer")}
"""


class AnswerQuestion(GroundedTask):
    """Answer one question grounded in a notebook's corpus blob, with citations."""

    signature = "sources: str, history: str, question: str, output_language: str -> answer: Answer"
    output_field = "answer"
    output_model = Answer
    instructions = _INSTRUCTIONS

