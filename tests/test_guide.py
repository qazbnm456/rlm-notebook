"""Notebook Guide tasks (`guide.py`), driven through REAL offline forward passes — same pattern as
`test_task.py`: `rlm_harness.testing.ScriptedInterpreter` + `scripted_lm` drive `dspy.RLM.aforward` for
real, no live model, no Deno, no network.
"""

from __future__ import annotations

import asyncio
import json

import pytest

dspy = pytest.importorskip("dspy")

import rlm_harness.runtime as rt
from rlm_harness import RLMConfig
from rlm_harness.testing import ScriptedInterpreter, assert_repl_safe, call, scripted_lm, submit

from rlm_notebook.guide import GenerateFAQ, GenerateKeyInsight, GenerateSummary, GenerateTimeline
from rlm_notebook.schema import FAQ, KeyInsight, Summary, Timeline

_SOURCES = "[[SRC:s1|page:1]]\nApples are red or green. Oranges are orange."

_GUIDE_TASKS = [GenerateSummary, GenerateFAQ, GenerateTimeline, GenerateKeyInsight]


def _configure(turns) -> None:
    dummy = scripted_lm(turns)
    rt.configure(
        RLMConfig(main_model="x", sub_model="x", interpreter="pyodide", observe=False),
        main_lm=dummy,
        sub_lm=dummy,
    )


def _validate_then_submit(task_cls, tool_name: str, output_field: str, payload: dict):
    _configure(
        [
            {"reasoning": "validate my draft before submitting", "code": f"{tool_name}(...)"},
            {"reasoning": "validation passed, submit", "code": "SUBMIT"},
        ]
    )
    interpreter = ScriptedInterpreter(
        steps=[
            call(tool_name, data_json_str=json.dumps(payload)),
            submit({output_field: payload}),
        ]
    )
    return asyncio.run(task_cls(interpreter=interpreter).arun(sources=_SOURCES))


@pytest.mark.parametrize("task_cls", _GUIDE_TASKS)
def test_guide_task_tools_are_repl_safe(task_cls):
    for tool in task_cls.tools:
        assert_repl_safe(tool)


@pytest.mark.parametrize(
    "task_cls,expected_tool_name",
    [
        (GenerateSummary, "validate_summary"),
        (GenerateFAQ, "validate_faq"),
        (GenerateTimeline, "validate_timeline"),
        (GenerateKeyInsight, "validate_keyinsight"),
    ],
)
def test_guide_task_never_exposes_a_network_capable_tool(task_cls, expected_tool_name):
    """Same invariant-1 regression guard as AnswerQuestion's — none of these tasks need a fetch
    tool (they only summarize what's already in `sources`), so none should ever grow one."""
    names = {getattr(tool, "__name__", "") for tool in task_cls.tools}
    assert names == {expected_tool_name}
    assert not any("fetch" in n or "http" in n or "url" in n for n in names)


def test_generate_summary_offline_forward_pass():
    payload = {
        "text": "The sources describe fruit colors.",
        "citations": [{"source_id": "s1", "locator": "page:1", "quote": "Apples are red or green."}],
    }
    result = _validate_then_submit(GenerateSummary, "validate_summary", "summary", payload)
    assert isinstance(result, Summary)
    assert result.text == payload["text"]
    assert result.citations[0].source_id == "s1"


def test_generate_faq_offline_forward_pass():
    payload = {
        "items": [
            {
                "question": "What color are apples?",
                "answer": "Red or green.",
                "citations": [{"source_id": "s1", "locator": "page:1", "quote": "Apples are red or green."}],
            }
        ]
    }
    result = _validate_then_submit(GenerateFAQ, "validate_faq", "faq", payload)
    assert isinstance(result, FAQ)
    assert result.items[0].question == "What color are apples?"
    assert result.items[0].citations[0].source_id == "s1"


def test_generate_timeline_offline_forward_pass():
    payload = {
        "events": [
            {
                "when": "page:1",
                "description": "Fruit colors are described.",
                "citations": [{"source_id": "s1", "locator": "page:1", "quote": "Apples are red or green."}],
            }
        ]
    }
    result = _validate_then_submit(GenerateTimeline, "validate_timeline", "timeline", payload)
    assert isinstance(result, Timeline)
    assert result.events[0].when == "page:1"


def test_generate_timeline_offline_forward_pass_empty_events():
    """CLAUDE.md/guide.py: a source describing no sequence of events must produce an EMPTY
    timeline, not a fabricated one — the schema (Timeline.events default_factory=list) and the
    instructions both allow this; this pins that an empty list actually round-trips correctly."""
    result = _validate_then_submit(GenerateTimeline, "validate_timeline", "timeline", {"events": []})
    assert isinstance(result, Timeline)
    assert result.events == []


def test_generate_key_insight_offline_forward_pass():
    payload = {
        "text": "Fruit color varies by type.",
        "citations": [{"source_id": "s1", "locator": "page:1", "quote": "Apples are red or green."}],
    }
    result = _validate_then_submit(GenerateKeyInsight, "validate_keyinsight", "insight", payload)
    assert isinstance(result, KeyInsight)
    assert result.text == payload["text"]
