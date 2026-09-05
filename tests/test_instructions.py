"""The shared prompt pieces every citation-grounded task composes (invariant 13).

**Every assertion here goes through a SHIPPED task class, never through a helper called with an
argument the product does not pass.** The first version of this file tested
`artifact_language_rule("Traditional Chinese")` — a call shape that occurs nowhere outside these
tests, because invariant 39 carries the language as a SIGNATURE FIELD and all three call sites
compose the rule at import time with a literal placeholder. The script rule matched on the language
NAME, so it returned `""` for every task in production while these tests stayed green, and a
mutation that made it `return ""` unconditionally was still killed. A test can pass for a reason
unrelated to its name at FEATURE level, not only at assertion level.
"""

import pytest


def _shipped_tasks():
    """The six citation-grounded task classes, as their class-level `instructions` string.

    Class-level rather than constructed, because constructing one requires a configured
    `rlm_harness` runtime and this file is about the prompt text alone.
    """
    from rlm_notebook.audio import GeneratePodcastScript
    from rlm_notebook.guide import (
        GenerateFAQ,
        GenerateKeyInsight,
        GenerateSummary,
        GenerateTimeline,
    )
    from rlm_notebook.task import AnswerQuestion

    return {
        cls.__name__: cls.instructions
        for cls in (
            AnswerQuestion,
            GenerateSummary,
            GenerateFAQ,
            GenerateTimeline,
            GenerateKeyInsight,
            GeneratePodcastScript,
        )
    }


def test_every_shipped_task_pins_the_script_a_language_name_leaves_open():
    """Naming a language does not name its SCRIPT. A sibling project shipped a Traditional Chinese
    document set whose body text were Traditional while every page TITLE came back Simplified, so the nav
    and the page disagreed on screen — the rule names the characters IN the script, which cannot be
    read as a loose synonym.

    This is the tripwire the first version of the feature lacked: it asserts the rule reaches the
    six prompts that ship, which is exactly what name-matching failed to do.
    """
    from rlm_notebook.instructions import SCRIPT_PINNED

    for name, instructions in _shipped_tasks().items():
        assert SCRIPT_PINNED in instructions, f"{name} does not carry the script rule"
        # Both varieties, named in their own characters — not a description of them.
        assert "繁體字" in instructions and "简体字" in instructions, name
        # Exactly one copy: a task with a local paragraph of its own is invariant 13's failure.
        assert instructions.count("繁體字") == 1, f"{name} carries more than one script rule"


def test_the_script_rule_is_worded_conditionally_rather_than_matched_on_a_language_name():
    """The rule ships in EVERY prompt, including a run whose output language has one script, and it
    is worded so the model applies it only when its own condition holds.

    That is forced by invariant 39, not chosen for economy: `instructions` is composed at import
    time and the language arrives per-request as a signature field, so no import-time branch can
    see it. Pinned because "compose the rule for the language that was asked for" reads as the
    obvious improvement and is the exact defect this replaced.
    """
    from rlm_notebook.instructions import SCRIPT_PINNED

    assert SCRIPT_PINNED.startswith("If that language has more than one script")
    # No call site may reintroduce a language-name branch.
    import inspect

    from rlm_notebook import audio, guide, instructions, task

    for module in (instructions, task, guide, audio):
        source = inspect.getsource(module)
        assert "_script_rule" not in source, f"{module.__name__} matches on a language name again"


def test_every_shipped_task_asks_for_native_wording_not_a_calque():
    """The observed failure was LEXICAL, not script: a Traditional Chinese answer wrote `源文` for
    "the source text" where a reader expects `原文`. 源 and 原 are both ordinary Traditional
    characters, so no script rule can reach it — only a rule about wording."""
    from rlm_notebook.instructions import NATURAL_REGISTER

    for name, instructions in _shipped_tasks().items():
        assert NATURAL_REGISTER in instructions, f"{name} does not carry the register rule"


def test_a_proper_noun_outranks_the_script_rule_in_every_shipped_task():
    """The two rules collide, and nothing said which wins until a live run made them collide.

    A Traditional Chinese podcast carried `霍尔木兹海峡` — a Simplified place name — verbatim from a
    Simplified source, four times. `PROPER_NOUNS` says never translate a name; the script rule says
    write Traditional throughout. The model chose the name, which is right (converting it costs the
    reader the string they would search for, invariant 69), but it chose it without being told.

    Stated INSIDE the script rule, so a reader of that paragraph meets the exception without having
    to hold a later paragraph in mind — and stated ONCE, covering both directions, because the
    first version carved it out of the Traditional rule only and left the Simplified rule with the
    mirror-image exposure.
    """
    from rlm_notebook.instructions import NATURAL_REGISTER, SCRIPT_PINNED

    assert "PROPER NOUN is the exception" in SCRIPT_PINNED
    assert SCRIPT_PINNED.index("PROPER NOUN is the exception") > SCRIPT_PINNED.index("繁體字")
    # It is not direction-specific: one carve-out serves Traditional and Simplified alike.
    # Whitespace-collapsed, because the constant is hard-wrapped prose and a rewrap must not
    # be able to break this.
    assert "the other variety" in " ".join(SCRIPT_PINNED.split())

    for name, instructions in _shipped_tasks().items():
        assert instructions.index("PROPER NOUN is the exception") < instructions.index(
            NATURAL_REGISTER
        ), f"{name} states the exception after the register rule rather than inside the script rule"


@pytest.mark.parametrize(
    "phrase",
    [
        "Begin by answering",
        "Stop when the answer is done",
        "Say what the sources did NOT settle",
    ],
)
def test_the_chat_answer_shape_rules_reach_the_prompt(phrase):
    """`AnswerQuestion` asks for an answer-first shape and for the corpus's own limits to be named.

    Pinned for the same reason as the script rule above: these are prompt-only rules with no
    runtime enforcement anywhere, so a deletion is invisible to every other test in the suite —
    mutations removing each of these survived the full 621-test run before this existed.
    """
    from rlm_notebook.task import AnswerQuestion

    assert phrase in AnswerQuestion.instructions
