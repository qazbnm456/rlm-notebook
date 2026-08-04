"""`AnswerQuestion` wiring, driven through a REAL offline forward pass — no live model, no Deno, no
network. Mirrors the sibling projects' own `test_task.py` pattern: `rlm_harness.testing.ScriptedInterpreter`
+ `scripted_lm` drive `dspy.RLM.aforward` for real, so the planner -> validate_answer -> SUBMIT chain
executes (the tool's own tracing runs) at zero cost.
"""

from __future__ import annotations

import asyncio
import json

import pytest

dspy = pytest.importorskip("dspy")

import rlm_harness.runtime as rt
from rlm_harness import RLMConfig
from rlm_harness.testing import ScriptedInterpreter, assert_repl_safe, call, scripted_lm, submit

from rlm_notebook.schema import Answer
from rlm_notebook.task import AnswerQuestion

_ANSWER_DICT = {
    "text": "Apples are red or green.",
    "citations": [{"source_id": "s1", "locator": "page:1", "quote": "Apples are red or green."}],
}


def _configure() -> None:
    dummy = scripted_lm(
        [
            {"reasoning": "validate my draft before submitting", "code": "validate_answer(...)"},
            {"reasoning": "validation passed, submit", "code": "SUBMIT"},
        ]
    )
    rt.configure(
        RLMConfig(main_model="x", sub_model="x", interpreter="pyodide", observe=False),
        main_lm=dummy,
        sub_lm=dummy,
    )


def test_answer_question_tools_are_repl_safe():
    """CLAUDE.md invariant: every tool this task exposes must have explicit named params (no
    *args/**kwargs — see rlm_harness.testing.assert_repl_safe's docstring for why)."""
    for tool in AnswerQuestion.tools:
        assert_repl_safe(tool)


def test_answer_question_never_exposes_a_network_capable_tool():
    """CLAUDE.md invariant 1: no fetch/network tool is ever reachable from the chat task's REPL.
    A regression guard, not a redundant check — the risk is someone later adding
    `make_fetch_tool(...)` to `tools=` "just to fetch one more page on request," which every other
    test here would keep passing right through."""
    names = {getattr(tool, "__name__", "") for tool in AnswerQuestion.tools}
    assert not any("fetch" in name or "http" in name or "url" in name for name in names), (
        f"AnswerQuestion.tools contains a suspiciously network-shaped tool name: {names}"
    )
    assert names == {"validate_answer"}, (
        f"AnswerQuestion.tools changed to {names} — if this is intentional, re-read CLAUDE.md "
        f"invariant 1 before adding anything with network access."
    )


def test_answer_question_offline_forward_pass():
    _configure()
    interpreter = ScriptedInterpreter(
        steps=[
            call("validate_answer", data_json_str=json.dumps(_ANSWER_DICT)),
            submit({"answer": _ANSWER_DICT}),
        ]
    )
    task = AnswerQuestion(interpreter=interpreter)

    result = asyncio.run(
        task.arun(
            sources="[[SRC:s1|page:1]]\nApples are red or green.",
            history="(no prior turns in this conversation)",
            question="What color are apples?",
        )
    )

    assert isinstance(result, Answer)
    assert result.text == "Apples are red or green."
    assert result.citations[0].source_id == "s1"
    assert result.citations[0].locator == "page:1"


def test_validate_answer_tool_reports_success_on_valid_json():
    validator = AnswerQuestion.tools[0]
    assert "successful" in validator(json.dumps(_ANSWER_DICT))


def test_validate_answer_tool_reports_failure_on_invalid_json():
    validator = AnswerQuestion.tools[0]
    assert "failed" in validator(json.dumps({"text": 123, "citations": "not a list"}))
