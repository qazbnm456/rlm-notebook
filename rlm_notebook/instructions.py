"""Shared instruction fragments for every RLMTask that grounds its output in the corpus blob and
cites it — `AnswerQuestion` (`task.py`), the four Notebook Guide tasks (`guide.py`) and
`GeneratePodcastScript` (`audio.py`). Plain string constants/functions, not a class hierarchy: the
citation-marker rules are IDENTICAL text every one of these tasks needs (CLAUDE.md invariant 4), and
hand-duplicating that paragraph across SIX task classes (an independent audit found this docstring
still saying five, from before the podcast joined them) is a drift hazard waiting to happen — a wording fix applied to one and forgotten in the
others would silently weaken the guarantee for whichever task got missed.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rlm_harness import load_skills_as_tools, render_skills_manifest
from rlm_harness.tools.validation import make_schema_validator

#: This package's own recorded craft and measured failure modes, shipped INSIDE the wheel for the
#: same packaging reason the web assets are (`packages = ["rlm_notebook"]`, invariant 29): a
#: top-level directory works from a checkout and silently vanishes from an install. Verified by
#: building a wheel and reading its manifest, not by trusting the layout.
SKILLS_DIR = str(Path(__file__).resolve().parent / "skills")

#: The catalog header every task shares. ONE copy, like `CITATION_RULES` — six tasks each wording
#: their own invitation is exactly the drift invariant 13 exists to prevent.
_SKILLS_HEADER = (
    "<available_skills> — this project's own recorded craft and measured failure modes. "
    "`read_skill(name)` loads one in full. Consult the relevant skill BEFORE working: they record "
    "what was actually measured here, including several ways a run has been lost outright:"
)



def _marker_offenders(value: Any, path: str = "") -> list[str]:
    """Every path under `value` whose string holds a `[[SRC:...]]` marker.

    `quote` is EXEMPT: it is copied verbatim out of a source, and a source that itself contains the
    literal text `[[SRC:` would make an honest quote look like a violation. Every other string in
    every output model is the model's own prose, where a marker is always wrong.
    """
    from .citations import MARKER_PATTERN

    if isinstance(value, str):
        return [path] if MARKER_PATTERN.search(value) else []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [p for i, v in enumerate(value) for p in _marker_offenders(v, f"{path}[{i}]")]
    # No output model has a dict field today; skipping one silently would be a fail-open the moment
    # somebody adds one, and this walk exists precisely because a guard that fails open is worse
    # than no guard.
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _marker_offenders(v, f"{path}[{k!r}]")]
    # `type(value)`, NOT the instance: pydantic deprecated instance access in 2.11 and removes it
    # in 3.0, and `getattr(instance, "model_fields", None)` would then return None — this walk
    # would return [] for every model and the guard would silently stop checking anything, on all
    # six tasks, with no error. A guard that fails OPEN is worse than one that raises.
    fields = getattr(type(value), "model_fields", None)
    if fields:
        out: list[str] = []
        for name in fields:
            if name == "quote":
                continue
            out += _marker_offenders(getattr(value, name), f"{path}.{name}" if path else name)
        return out
    return []


def make_grounded_validator(model: type) -> Callable[[str], str]:
    """`rlm_harness`'s schema validator PLUS a check the schema cannot express: no `[[SRC:...]]`
    marker anywhere in the model's own prose.

    **Why not a schema validator.** Nothing rewrites a stored artifact (the strip happens on the way
    OUT), so a notebook written before this validator existed holds whatever the model produced — the
    measured cases were a podcast with twenty markers across nineteen of its forty-seven utterances
    and an overview with four — and a field-level reject would make those files fail to LOAD, turning
    untidy data into a corrupt-notebook 409. The check belongs
    where the model can still act on it: before SUBMIT, in the tool the instructions already tell it
    to call.

    **Why every task and not just the podcast.** It was written for `GeneratePodcastScript`, whose
    failure was loud (the voice read the markers aloud). `GenerateSummary` had produced exactly the
    same defect, silently — four markers printed in an overview a user reported as a broken render.
    A guard on the one task that made a noise is a guard on the symptom.
    """
    schema_check = make_schema_validator(model)

    def validate(data_json_str: str) -> str:
        """Validate a JSON string against the expected output schema AND check that no
        `[[SRC:...]]` marker appears in your own prose. Pass your generated JSON here before
        emitting it as the final answer."""
        verdict = schema_check(data_json_str)
        if verdict.startswith("Validation failed"):
            return verdict
        offenders = _marker_offenders(model.model_validate_json(data_json_str))
        if offenders:
            # The advice has to differ by WHERE the marker is. "put it in the citations entry" is a
            # dead end when the offender IS a citation field, and a model that loops on impossible
            # advice spends the whole step budget doing it.
            inside = [o for o in offenders if "citations[" in o or o.startswith("citations")]
            if inside:
                advice = (
                    "a `source_id` is the id alone (`s1`) and a `locator` the locator alone "
                    "(`whole`, `page:3`) — copy the PARTS out of the marker, never the marker itself"
                )
            else:
                advice = (
                    "remove it from the text and put the coordinate in the accompanying "
                    "`citations` entry instead"
                )
            where = ", ".join(offenders)
            verb = "contains" if len(offenders) == 1 else "contain"
            return (
                f"Validation failed: {where} {verb} a [[SRC:...]] marker. A marker is a coordinate "
                f"for the interface, not a citation and not something a reader or a listener should "
                f"ever see — {advice}."
            )
        return verdict

    validate.__name__ = f"validate_{model.__name__.lower()}"
    validate.__qualname__ = validate.__name__
    return validate


def apply_skills(task: Any, skills_dir: str | None) -> None:
    """Wire `skills_dir` onto `task` using `discovery="inject"`, the shape four sibling projects
    already use (`cabt-forge`, `bugcademy`, `cve-reverser`, `nuclei-forge`).

    The CATALOG (one `- name: description` line per skill) is prepended to the instructions at
    construction time, so the planner knows which skills exist without spending a `list_skills`
    round-trip; only `read_skill` becomes a tool, pulling a body just-in-time. That is the whole
    reason craft lives in a skill rather than in the prompt: the prompt is paid for on EVERY planner
    turn, a skill body only when the model decides it needs one.

    **What belongs in a skill and what does not.** A skill is read only if the model chooses to, so
    anything that CORRUPTS the output when skipped stays in the prompt — grounding, citations, the
    marker rule, language, the output shape. Craft and technique are the right things to move: work
    done without them is duller or more expensive, not wrong.

    `read_skill` resolves a NAME against the skills discovered here, so it cannot read an arbitrary
    path and never touches the network — invariants 1 and 14 are about a model reaching the outside
    world at generation time, which this does not do.

    ONE directory for every task, deliberately: `rlm_harness.skills.discover_skills` takes a single
    directory and does not recurse, and the catalog costs one line per skill. If it ever grows
    enough that a chat turn is paying to be told about podcast craft, that is the point to split it —
    not before.
    """
    if skills_dir is None or not os.path.isdir(skills_dir):
        return
    manifest = render_skills_manifest(skills_dir, header=_SKILLS_HEADER)
    # The MANIFEST decides, not the directory. `load_skills_as_tools` returns `read_skill`
    # regardless of whether anything was discovered, and that tool's own description tells the model
    # to pick "the ones listed in the skills manifest in your instructions" — so an empty or
    # skill-less directory used to hand the model a tool pointing at a list that was not there.
    if not manifest:
        return
    task.tools = [*task.tools, *load_skills_as_tools(skills_dir, discovery="inject")]
    # `instructions` is a ClassVar on RLMTask, so assigning it on the INSTANCE shadows the class
    # default for this task only — the same pattern the `tools` line above relies on.
    # CLOSED. `render_skills_manifest` only prepends the header, so without this every rule in
    # the task's own prompt — citations, language, validate-before-submit — reads as though it
    # were inside the skills element.
    task.instructions = manifest + "\n</available_skills>\n\n" + type(task).instructions


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
