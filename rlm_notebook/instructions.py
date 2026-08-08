"""Shared instruction fragments for every RLMTask that grounds its output in the corpus blob and
cites it — `AnswerQuestion` (`task.py`), the four Notebook Guide tasks (`guide.py`) and
`GeneratePodcastScript` (`audio.py`). Plain string constants/functions, not a class hierarchy: the
citation-marker rules are IDENTICAL text every one of these tasks needs (CLAUDE.md invariant 4), and
hand-duplicating that paragraph across SIX task classes (an independent audit found this docstring
still saying five, from before the podcast joined them) is a drift hazard waiting to happen — a wording fix applied to one and forgotten in the
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
fabricated citation is not.

A `[[SRC:...]]` marker belongs in a `Citation` and NOWHERE ELSE. Never write one into your own
prose: it is a coordinate for the interface, and a reader sees it as a template that failed to
render. Cite by filling in a `Citation`; write the sentence as a sentence.

A `Citation`'s `quote` is copied VERBATIM from the block — never translated, paraphrased,
summarised, re-punctuated, or tidied. It is the reader's way of checking your prose against the
source's own words, and it stops being that the moment you rewrite it.

A `Citation`'s `answer_span` points the other way: copy into it, VERBATIM, the stretch of YOUR OWN
text that this citation supports — usually the sentence or clause making the claim. Two rules make
it usable:

- It must appear in your own text EXACTLY, character for character. The reader's interface finds it
  by searching your text for it; a span that has been re-typed, trimmed differently or
  re-punctuated simply will not be found.
- It is in YOUR language, not the source's. `quote` stays in the source's words and `answer_span`
  stays in yours — that is the whole point of having both, and it is what lets a reader writing in
  one language cite a source written in another.

Pick the smallest stretch that carries the claim: a sentence is usually right, a whole paragraph is
too coarse to be useful, and three words are too little to find reliably. If a citation supports
something you cannot point at that precisely, leave `answer_span` out — an absent span costs the
reader a highlight, and a wrong one sends them to the wrong sentence.\
"""

#: The carve-out every language instruction composes with. Kept SEPARATE from the language rules
#: below so both of them share one copy (CLAUDE.md invariant 13) rather than each restating it.
#:
#: Naming only `quote` would be insufficient, and the omission is not cosmetic: a model told to
#: write everything in Chinese will equally localise a LOCATOR — `page:1` becomes `第1頁`, a YouTube
#: `ts:01:30` gets reformatted — and `citations.verify_citations` compares locators with an exact
#: `==`. Every such citation lands as UNVERIFIED, which reads to a user as the model having made the
#: citation up. Found by this slice's pre-implementation audit, before any of it was written.
VERBATIM_COORDINATES = """\
This does NOT apply to citation coordinates. A `source_id`, a `locator`, the `[[SRC:...]]` marker
syntax, and a `quote` are all copied EXACTLY as they appear in `sources`, in the source's own
language and formatting, however you are writing your prose. `page:1` stays `page:1`; a quote of
English text stays in English inside a Chinese answer. These are coordinates and evidence, not
prose, and a reader uses them to find the passage you are pointing at.\
"""


def chat_language_rule(language: str) -> str:
    """`AnswerQuestion`'s language rule. Separate from the artifact rule because chat has something
    no artifact has — a question, whose own language is the strongest available signal.

    `language` is never empty: callers pass a literal default rather than an empty string, so this
    paragraph is always present and never has to guard an absent value (a class-level `instructions`
    string is composed at import time and cannot know a per-request language — trying to have both a
    signature field and byte-identical prompts-when-unset was a contradiction this slice's audit
    caught in its own design)."""
    return (
        f"Write your prose in {language}. If that instruction names the question's own language,\n"
        f"answer in whatever language the question was asked in; when a follow-up is too short to\n"
        f"tell (\"and Y?\", \"why?\"), use the language of the most recent question in `history`.\n"
        f"Reading `history` for THAT is reading it as context for what the question refers to, which\n"
        f"is what it is for — it remains never a source of facts or citations.\n\n"
        f"{VERBATIM_COORDINATES}"
    )


def artifact_language_rule(language: str) -> str:
    """The language rule for whole-corpus artifacts, which have no question to take a cue from."""
    return f"Write your prose in {language}.\n\n{VERBATIM_COORDINATES}"


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
