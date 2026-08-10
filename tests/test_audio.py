"""`GeneratePodcastScript` (`audio.py`), driven through a REAL offline forward pass — same pattern
as `test_task.py`/`test_guide.py`: `rlm_harness.testing.ScriptedInterpreter` + `scripted_lm` drive
`dspy.RLM.aforward` for real, no live model, no Deno, no network.
"""

from __future__ import annotations

import asyncio
import json
import pathlib

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
    # An INSTANCE's tools — the ClassVar is empty now that the validator is built per run.
    _configure()
    for tool in GeneratePodcastScript(skills_dir=None).tools:
        assert_repl_safe(tool)


def test_generate_podcast_script_never_exposes_a_network_capable_tool():
    """Same invariant-1-style regression guard as AnswerQuestion's/the Guide tasks' — this task
    only writes a script from `sources`, so it should never grow a fetch/TTS tool of its own (TTS
    synthesis happens entirely AFTER this task returns, in tts.py, host-side)."""
    _configure()
    names = {getattr(tool, "__name__", "") for tool in GeneratePodcastScript(skills_dir=None).tools}
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

    result = asyncio.run(task.arun(output_language="English", sources=_SOURCES, target_length="default"))

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
    result = asyncio.run(GeneratePodcastScript(interpreter=interpreter).arun(
        output_language="English", sources=_SOURCES, target_length="default"
    ))
    assert isinstance(result, PodcastScript)
    assert result.utterances == []


def test_the_script_never_asks_for_disfluencies():
    """`Utterance.text` is BOTH the transcript and the string a text-to-speech voice reads, and these
    voices read it literally — measured: the same Chinese sentence with six characters of written
    filler synthesized to 4.08s against the plain sentence's 2.90s.

    Pinned because it reads as an obvious improvement. Invariant 45 records the same shape once
    already, for transliteration. (An earlier version of this docstring justified the rule with a
    quote attributed to the NotebookLM team; that sentence was their hosts' show note and the guest
    contradicts it when asked. The `podcast-craft` skill records that, and the rule now stands on
    this project's own measurement instead.)
    """
    instructions = GeneratePodcastScript.instructions
    assert "Do NOT write disfluencies" in instructions, (
        "the prohibition moved out of the PROMPT. A skill is read only if the model chooses to, and "
        "a written 'um' corrupts both the transcript and the audio — that cannot be optional"
    )

    # The SPLIT itself: craft lives in the skill (read when wanted), must-apply rules in the prompt.
    craft = (
        pathlib.Path(__file__).resolve().parent.parent
        / "rlm_notebook" / "skills" / "podcast-craft.md"
    ).read_text(encoding="utf-8")
    for technique in ("Tension", "Pacing", "The reveal"):
        assert technique in craft, f"the {technique} guidance is gone from the skill"
        assert technique.upper() not in instructions, (
            f"{technique} is back in the prompt, which is paid for on every planner turn"
        )


def test_a_long_script_is_told_to_build_across_turns():
    """Measured, not assumed: `long` (60-90 turns) written as one code block was TRUNCATED by
    `max_tokens=16384` and the whole run was lost — dspy said so in as many words. Built across REPL
    turns instead, the same tier produced 80 utterances and 44 citations with the budget untouched.
    That is what the sandbox is FOR, and it is the reason this project did not answer a truncation
    by raising a cap for the second time."""
    instructions = GeneratePodcastScript.instructions
    assert "does NOT fit in one reply" in instructions
    assert "Never print the accumulated script" in instructions, (
        "printing the accumulated script back spends the same budget twice — it lands in the "
        "planner's next prompt"
    )


def test_the_podcast_task_exposes_its_skills_by_injection():
    """`discovery="inject"`, the shape four sibling projects already use: the CATALOG goes into the
    instructions at construction, so the planner knows which skills exist without spending a
    `list_skills` round-trip, and only `read_skill` is a tool.

    This project had NO skills at all until a user pointed out that `rlm_harness.skills` exists —
    distinct from the Claude Code skills that are read by a coding agent and never by this task.
    """
    _configure()
    task = GeneratePodcastScript()
    names = {getattr(tool, "__name__", "") for tool in task.tools}
    assert "read_skill" in names
    assert "list_skills" not in names, (
        "discovery is back to `list`, which spends a planner turn discovering what the catalog "
        "already says"
    )
    assert "podcast-craft" in task.instructions, "the catalog was not injected"
    assert len(task.instructions) > len(GeneratePodcastScript.instructions)


def test_the_skills_directory_can_be_pointed_elsewhere_or_turned_off(tmp_path):
    """A constructor argument, matching the siblings: a test points it at a fixture and `None`
    turns it off — which a caller needs, because a stale skill is worse than an absent one."""
    _configure()  # instantiating an RLMTask needs the harness configured; nothing here runs a model
    off = GeneratePodcastScript(skills_dir=None)
    assert {getattr(t, "__name__", "") for t in off.tools} == {"validate_podcastscript"}
    assert off.instructions == GeneratePodcastScript.instructions

    (tmp_path / "only-this.md").write_text(
        "---\nname: only-this\ndescription: a fixture\n---\n\nbody\n", encoding="utf-8"
    )
    fixture = GeneratePodcastScript(skills_dir=str(tmp_path))
    assert "only-this" in fixture.instructions
    assert "podcast-craft" not in fixture.instructions


def test_a_shipped_skill_carries_the_frontmatter_the_catalog_is_built_from():
    """`render_skills_manifest` reads `name`/`description` out of the frontmatter. A skill missing
    either renders as `(no description)` in the catalog — present, and useless to choose between."""
    import pathlib

    skills = pathlib.Path(__file__).resolve().parent.parent / "rlm_notebook" / "skills"
    files = sorted(skills.glob("*.md"))
    assert files, "the skills directory is empty; the catalog would inject nothing"
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---"), f"{path.name} has no frontmatter"
        head = text[3 : text.index("\n---", 3)]
        keys = {line.split(":")[0].strip().lower() for line in head.splitlines() if ":" in line}
        assert {"name", "description"} <= keys, f"{path.name} is missing name/description"


def test_no_prompt_hardcodes_a_skill_name():
    """A prompt that names a specific skill breaks the moment `skills_dir` points somewhere else —
    it would tell the model to read something that is not in the catalog. The catalog is injected
    precisely so the prompt does not have to know what is in it.

    Found by `test_the_skills_directory_can_be_pointed_elsewhere_or_turned_off` when the podcast
    prompt started saying `read_skill("podcast-craft")`.
    """
    import pathlib as _p

    from rlm_notebook.audio import GeneratePodcastScript
    from rlm_notebook.guide import (
        GenerateFAQ,
        GenerateKeyInsight,
        GenerateSummary,
        GenerateTimeline,
    )
    from rlm_notebook.task import AnswerQuestion

    skills = _p.Path(__file__).resolve().parent.parent / "rlm_notebook" / "skills"
    names = [f.stem for f in skills.glob("*.md")]
    assert names, "no skills shipped; this would pass vacuously"
    for cls in (
        AnswerQuestion,
        GenerateSummary,
        GenerateFAQ,
        GenerateTimeline,
        GenerateKeyInsight,
        GeneratePodcastScript,
    ):
        for name in names:
            assert name not in cls.instructions, (
                f"{cls.__name__}'s prompt names the `{name}` skill, so pointing `skills_dir` "
                f"elsewhere leaves it asking for something the catalog does not list"
            )
