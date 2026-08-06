"""`GeneratePodcastScript` (`audio.py`), driven through a REAL offline forward pass — same pattern
as `test_task.py`/`test_guide.py`: `rlm_harness.testing.ScriptedInterpreter` + `scripted_lm` drive
`dspy.RLM.aforward` for real, no live model, no Deno, no network.
"""

from __future__ import annotations

import asyncio
import json

import pytest

dspy = pytest.importorskip("dspy")

import rlm_harness.runtime as rt
from rlm_harness import RLMConfig
from rlm_harness.testing import ScriptedInterpreter, assert_repl_safe, call, scripted_lm, submit

from rlm_notebook.audio import GeneratePodcastScript
from rlm_notebook.schema import PodcastScript

_SOURCES = "[[SRC:s1|page:1]]\nApples are red or green. Oranges are orange."

_PAYLOAD = {
    "utterances": [
        {
            "speaker": "host_a",
            "text": "So I was reading about fruit colors, did you know apples come in two colors?",
            "citations": [],
        },
        {
            "speaker": "host_b",
            "text": "Really? What colors?",
            "citations": [],
        },
        {
            "speaker": "host_a",
            "text": "Red or green, according to the source.",
            "citations": [{"source_id": "s1", "locator": "page:1", "quote": "Apples are red or green."}],
        },
    ]
}


def _configure() -> None:
    dummy = scripted_lm(
        [
            {"reasoning": "validate my draft before submitting", "code": "validate_podcastscript(...)"},
            {"reasoning": "validation passed, submit", "code": "SUBMIT"},
        ]
    )
    rt.configure(
        RLMConfig(main_model="x", sub_model="x", interpreter="pyodide", observe=False),
        main_lm=dummy,
        sub_lm=dummy,
    )


def test_generate_podcast_script_tools_are_repl_safe():
    for tool in GeneratePodcastScript.tools:
        assert_repl_safe(tool)


def test_generate_podcast_script_never_exposes_a_network_capable_tool():
    """Same invariant-1-style regression guard as AnswerQuestion's/the Guide tasks' — this task
    only writes a script from `sources`, so it should never grow a fetch/TTS tool of its own (TTS
    synthesis happens entirely AFTER this task returns, in tts.py, host-side)."""
    names = {getattr(tool, "__name__", "") for tool in GeneratePodcastScript.tools}
    assert names == {"validate_podcastscript"}
    assert not any(bad in n for n in names for bad in ("fetch", "http", "url", "tts", "audio"))


def test_generate_podcast_script_offline_forward_pass():
    _configure()
    interpreter = ScriptedInterpreter(
        steps=[
            call("validate_podcastscript", data_json_str=json.dumps(_PAYLOAD)),
            submit({"script": _PAYLOAD}),
        ]
    )
    task = GeneratePodcastScript(interpreter=interpreter)

    result = asyncio.run(task.arun(output_language="English", sources=_SOURCES))

    assert isinstance(result, PodcastScript)
    assert len(result.utterances) == 3
    assert result.utterances[0].speaker == "host_a"
    assert result.utterances[1].speaker == "host_b"
    assert result.utterances[2].citations[0].source_id == "s1"


def test_generate_podcast_script_offline_forward_pass_empty_script():
    """A source with nothing worth discussing must be able to produce a legitimately empty
    script — pins that an empty utterances list round-trips correctly, same as
    test_guide.py's empty-timeline test."""
    _configure()
    interpreter = ScriptedInterpreter(
        steps=[
            call("validate_podcastscript", data_json_str=json.dumps({"utterances": []})),
            submit({"script": {"utterances": []}}),
        ]
    )
    result = asyncio.run(GeneratePodcastScript(interpreter=interpreter).arun(output_language="English", sources=_SOURCES))
    assert isinstance(result, PodcastScript)
    assert result.utterances == []
