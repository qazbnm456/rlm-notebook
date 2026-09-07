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
    return asyncio.run(task_cls(interpreter=interpreter).arun(output_language="English", sources=_SOURCES))


@pytest.mark.parametrize("task_cls", _GUIDE_TASKS)
def test_guide_task_tools_are_repl_safe(task_cls):
    # An INSTANCE's tools: the validator is built per run and `read_skill` is appended per run, so
    # the ClassVar is empty and iterating it would assert nothing about what a run can reach.
    _configure([])
    for tool in task_cls(skills_dir=None).tools:
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
    tool (they only summarize what's already in `sources`), so none should ever grow one.

    Reads the INSTANCE's tools, not the class's. `GroundedTask.__init__` builds the validator per
    run (it closes over that run's coordinates) and `apply_skills` appends `read_skill`, so the
    ClassVar is empty and a class-level assertion would pass against a tuple of nothing — checking
    exactly what a run does NOT use."""
    _configure([])
    names = {getattr(tool, "__name__", "") for tool in task_cls(skills_dir=None).tools}
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
    """AGENTS.md/guide.py: a source describing no sequence of events must produce an EMPTY
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


def test_a_locator_the_model_composed_from_the_passage_is_rejected_before_submit():
    """The exact defect a user reported as a red "unverified" badge on their overview.

    Every web source is ONE block with locator `whole`, and the model wrote the section heading it
    was citing into `locator` instead — five of five overview citations failed coordinate
    verification server-side, with nothing having warned the model while it could still fix it.

    `citations.verify_citations` is still the guarantee (invariant 5); this is the early warning.
    """
    from rlm_notebook.guide import GenerateSummary

    _configure([])
    task = GenerateSummary(skills_dir=None)
    validator = next(t for t in task.tools if t.__name__ == "validate_summary")

    blob = '[[SRC:s1|whole]]\nMoving from a localized security "skill" to a pipeline is hard.\n'
    task._coordinates = __import__(
        "rlm_notebook.instructions", fromlist=["coordinates_in"]
    ).coordinates_in(blob)
    assert task._coordinates == {"s1|whole"}

    invented = {
        "text": "The sources describe a pipeline.",
        "citations": [
            {
                "source_id": "s1",
                "locator": 'Moving from a localized security "skill" to a pipeline',
                "quote": "Moving from a localized security",
                "answer_span": "The sources describe a pipeline.",
            }
        ],
    }
    verdict = validator(json.dumps(invented))
    assert verdict.startswith("Validation failed"), verdict
    assert "does not exist in `sources`" in verdict
    # It must show a REAL coordinate, or the model just invents a different sentence.
    assert "'s1|whole'" in verdict, verdict

    honest = json.loads(json.dumps(invented))
    honest["citations"][0]["locator"] = "whole"
    assert "successful" in validator(json.dumps(honest))


def test_the_coordinate_check_reaches_citations_NESTED_under_a_list_of_models():
    """Three of the six tasks keep citations inside a list of sub-models — FAQ items, timeline
    events, podcast utterances — and only `Summary`/`Answer`/`KeyInsight` have them at the top.

    An independent review disabled descent into nested models and the whole suite stayed green,
    which would have left `GenerateFAQ`, `GenerateTimeline` and `GeneratePodcastScript` unguarded.
    The podcast is the very task the MARKER check already spent a slice living only on."""
    from rlm_notebook.instructions import _cited_coordinates
    from rlm_notebook.schema import FAQ, Citation, PodcastScript, Timeline, TimelineEvent, Utterance

    bad = Citation(source_id="s9", locator="A SECTION HEADING", quote="q", answer_span="a")
    faq = FAQ.model_validate({"items": [{"question": "q?", "answer": "a", "citations": [bad.model_dump()]}]})
    assert _cited_coordinates(faq) == [("items[0].citations[0]", "s9|A SECTION HEADING")]

    timeline = Timeline(events=[TimelineEvent(when="2026", description="d", citations=[bad])])
    assert _cited_coordinates(timeline) == [("events[0].citations[0]", "s9|A SECTION HEADING")]

    script = PodcastScript(utterances=[Utterance(speaker="host_a", text="t", citations=[bad])])
    assert _cited_coordinates(script) == [("utterances[0].citations[0]", "s9|A SECTION HEADING")]


def test_the_coordinate_check_fails_open_when_the_blob_has_no_markers():
    """An empty coordinate set means "we do not know what is valid here", and rejecting every
    citation of a legitimate run is far worse than letting server-side verification catch an
    invented one. Deliberate and documented — not the silent fail-open invariant 66 warns about."""
    from rlm_notebook.guide import GenerateSummary

    _configure([])
    task = GenerateSummary(skills_dir=None)
    validator = next(t for t in task.tools if t.__name__ == "validate_summary")
    assert task._coordinates == set()
    payload = {
        "text": "A claim.",
        "citations": [
            {"source_id": "s9", "locator": "invented", "quote": "q", "answer_span": "A claim."}
        ],
    }
    assert "successful" in validator(json.dumps(payload))


def test_arun_captures_this_runs_coordinates_from_the_blob_it_was_handed():
    """The WIRING, not the closure: `GroundedTask.arun` reads `sources` before the model can cite
    anything. Without it the set stays empty and the check above silently never fires — which is
    how a guard that "exists" protects nothing."""
    import asyncio

    from rlm_notebook.guide import GenerateSummary

    payload = {
        "text": "Fruit colors.",
        "citations": [
            {
                "source_id": "s1",
                "locator": "page:1",
                "quote": "Apples are red or green.",
                "answer_span": "Fruit colors.",
            }
        ],
    }
    _configure(
        [
            {"reasoning": "validate", "code": "validate_summary(...)"},
            {"reasoning": "submit", "code": "SUBMIT"},
        ]
    )
    interpreter = ScriptedInterpreter(
        steps=[
            call("validate_summary", data_json_str=json.dumps(payload)),
            submit({"summary": payload}),
        ]
    )
    task = GenerateSummary(interpreter=interpreter, skills_dir=None)
    asyncio.run(
        task.arun(
            sources="[[SRC:s1|page:1]]\nApples are red or green.\n[[SRC:s2|whole]]\nPears.",
            output_language="English",
        )
    )
    assert task._coordinates == {"s1|page:1", "s2|whole"}
