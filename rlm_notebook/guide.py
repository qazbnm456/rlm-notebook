"""Notebook Guide: whole-corpus artifacts generated from a notebook's sources — a summary, an FAQ,
a timeline, and a single key insight. Same citation-grounded `RLMTask` pattern as `AnswerQuestion`
(`task.py`): `signature` names two input fields — `sources` (the corpus blob) and
`output_language` (invariant 39) — and one output field, with no `question`/`history` since these describe the corpus as a whole rather than answer one
question. Everything else (retry, sandbox selection, budget caps, tracing) is inherited from
`rlm_harness.RLMTask`, exactly as `AnswerQuestion` inherits it.
"""

from __future__ import annotations

from .instructions import (
    CITATION_RULES,
    GroundedTask,
    artifact_language_rule,
    validate_before_submit_rule,
)
from .schema import FAQ, KeyInsight, Summary, Timeline

__all__ = ["GenerateFAQ", "GenerateKeyInsight", "GenerateSummary", "GenerateTimeline"]


def _grounded_instructions(task_description: str, tool_name: str) -> str:
    """Compose one Guide task's instructions: a task-specific opening paragraph, a grounding rule
    shared across the FOUR Guide tasks (below — worded for "generating a claim," not "answering a
    question," so it is NOT the same text `AnswerQuestion` uses and is not in `instructions.py`;
    don't conflate the two when editing either), then the truly cross-cutting pieces every
    citation-grounded task (Guide AND `AnswerQuestion`) shares from `instructions.py`: the
    citation-marker rules and the validate-before-submit rule. See `instructions.py`'s docstring
    for why THOSE two are factored out rather than hand-duplicated across five task classes."""
    return f"""\
{task_description} Ground EVERY claim ONLY in the `sources` text given to you as a REPL variable —
never your own background knowledge. If the sources don't support a claim, leave it out rather
than filling the gap from what you already know.

{artifact_language_rule("the language named by the `output_language` variable")}

{CITATION_RULES}

{validate_before_submit_rule(tool_name)}
"""


class GenerateSummary(GroundedTask):
    """A concise summary of a notebook's sources, with citations."""

    signature = "sources: str, output_language: str -> summary: Summary"
    output_field = "summary"
    output_model = Summary
    instructions = _grounded_instructions(
        "You are writing a concise summary of the sources in this notebook — the key points a "
        "reader would need, not a chapter-by-chapter recap.",
        "validate_summary",
    )



class GenerateFAQ(GroundedTask):
    """A set of frequently-asked questions and answers derived from a notebook's sources."""

    signature = "sources: str, output_language: str -> faq: FAQ"
    output_field = "faq"
    output_model = FAQ
    instructions = _grounded_instructions(
        "You are generating a FAQ (frequently-asked questions and answers) that a reader of these "
        "sources would find useful — questions the sources actually answer, not ones you invent "
        "for their own sake.",
        "validate_faq",
    )



class GenerateTimeline(GroundedTask):
    """A chronological (or otherwise ordered) timeline of events described across a notebook's
    sources."""

    signature = "sources: str, output_language: str -> timeline: Timeline"
    output_field = "timeline"
    output_model = Timeline
    instructions = _grounded_instructions(
        "You are extracting a timeline of events, milestones, or ordered steps described across "
        "the sources. If the sources give explicit dates, use them in `when`; if they only imply "
        "an order (e.g. \"first ... then ... finally\"), describe that order in `when` instead of "
        "inventing a date. If the sources describe no sequence of events at all, return an empty "
        "list of events rather than fabricating one.",
        "validate_timeline",
    )



class GenerateKeyInsight(GroundedTask):
    """The single most important, non-obvious takeaway from a notebook's sources, in one sentence."""

    signature = "sources: str, output_language: str -> insight: KeyInsight"
    output_field = "insight"
    output_model = KeyInsight
    instructions = _grounded_instructions(
        "You are identifying the SINGLE most important, non-obvious takeaway from these sources — "
        "one sentence that would let someone who has not read the sources understand the one "
        "thing that matters most. Not a summary of everything: the ONE insight a careful reader "
        "would consider most worth knowing.",
        "validate_keyinsight",
    )

