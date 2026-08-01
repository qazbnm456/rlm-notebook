"""Shared instruction fragments for every RLMTask that grounds its output in the corpus blob and
cites it — `AnswerQuestion` (`task.py`) and the Notebook Guide tasks (`guide.py`). Plain string
constants/functions, not a class hierarchy: the citation-marker rules are IDENTICAL text every one
of these tasks needs (CLAUDE.md invariant 4), and hand-duplicating that paragraph across five task
classes is a drift hazard waiting to happen — a wording fix applied to one and forgotten in the
others would silently weaken the guarantee for whichever task got missed.
"""

from __future__ import annotations

CITATION_RULES = """\
`sources` is a single string containing every source in this notebook. Each citable block is
preceded by a marker line of the EXACT form `[[SRC:<source_id>|<locator>]]`, immediately followed
by that block's text. Explore `sources` with Python — `.find()`, slicing, splitting on the literal
substring "[[SRC:" — to locate the passages relevant to your task; you have not already been shown
its contents above, so read before you answer.

Markers are OPAQUE identifiers, not something you compute. When a claim relies on a block, copy
that block's marker's `source_id` and `locator` VERBATIM into a `Citation` — never invent, alter,
guess, or reconstruct one from surrounding context. If you cannot find a marker supporting a claim,
leave that claim uncited rather than fabricating a citation for it; an uncited claim is honest, a
fabricated citation is not.\
"""


def validate_before_submit_rule(tool_name: str) -> str:
    """The "validate before SUBMIT" paragraph, parameterized by the schema-validator tool's name
    (`make_schema_validator` derives it from the output model as `validate_<model name, lowered>`).
    """
    return (
        f"Before you SUBMIT, validate your draft JSON against the expected schema with the\n"
        f"`{tool_name}` tool, and only submit after it reports success. That tool checks JSON\n"
        f"SHAPE only — it does not, and cannot, confirm your citations point at real sources; a\n"
        f"separate check does that after this run ends, so getting the shape right here is what\n"
        f"you are responsible for."
    )
