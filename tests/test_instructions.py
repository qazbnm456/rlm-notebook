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


# --- the pre-SUBMIT script check ------------------------------------------------------------

#: Correct Traditional characters a `zhconv` diff flags but this check must never touch. All nine
#: were measured in real prose in this project's own notebooks (`干預`, `一台`, `一群`, `里程碑`).
CORRECT_TRADITIONAL = "干台群里面系松板折繁體字概覽模組臺灣麼對點問題爾茲峽個們這"
#: Measured Simplified drift in two real notebooks' podcast fields.
MEASURED_DRIFT = {"尔": "爾", "兹": "茲", "峡": "峽", "对": "對", "点": "點", "问": "問", "题": "題"}


def _drifted(text, quote="正體"):
    import json

    return json.dumps(
        {
            "utterances": [
                {
                    "speaker": "host_a",
                    "text": text,
                    "citations": [
                        {"source_id": "s1", "locator": "whole", "quote": quote, "answer_span": ""}
                    ],
                }
            ]
        }
    )


def test_the_wrong_script_table_never_flags_a_correct_traditional_character():
    """PRECISION is the property that matters, and it is bought with recall.

    A false positive is a rejection the model cannot satisfy, which spends the step budget looping
    and loses a paid-for episode over one glyph. So the table is built from BIG5-ENCODABILITY, not
    from `zhconv`'s own `SIMPONLY` set — that set contains `干`, `台`, `群` and `里`, all of which
    appear in correct prose in this project's real notebooks.
    """
    from rlm_notebook.instructions import _wrong_script_chars

    wrong = _wrong_script_chars("hant")
    assert not [c for c in CORRECT_TRADITIONAL if c in wrong]
    # The mirror table must not condemn ordinary Simplified either.
    assert not [c for c in "简体字概览模块对点问题" if c in _wrong_script_chars("hans")]


def test_the_suggestion_is_phrase_aware_not_a_character_lookup():
    """A character-level table cannot answer "what should this be", and shipping one was a defect.

    `历` is `歷` in `历史` and `曆` in `日历`; `发` is `發` in `发现` and `髮` in `头发`; `汇` is
    `匯` in `汇率` and `彙` in `词汇`. The table gives whichever form is commoner, so the validator
    named the wrong character whenever the word was the less common one. Found by a sibling project
    in its converter and confirmed here against this project's own table.

    The regional preference must survive it AND must not override it — `因为` still gets `為` over
    `zh-hant`'s `爲`, while `日历` keeps the phrase-aware `曆` instead of losing it to `歷`.
    """
    from rlm_notebook.instructions import _script_offenders, _wrong_script_chars

    wrong = _wrong_script_chars("hant")

    def suggest(text, char):
        return next(g for _, b, g in _script_offenders(text, wrong, "hant") if b == char)

    assert suggest("日历提醒", "历") == "曆" and suggest("历史紀錄", "历") == "歷"
    assert suggest("头发很长", "发") == "髮" and suggest("发现問題", "发") == "發"
    assert suggest("词汇表", "汇") == "彙" and suggest("汇率", "汇") == "匯"
    # ...and the regional preference is still applied where context made no choice.
    assert suggest("因为众多", "为") == "為" and suggest("账户", "账") == "帳"


def test_the_wrong_script_table_names_the_fix_for_every_measured_drift_character():
    """The rejection has to be mechanically actionable, so each offender carries its right form.

    Recall is where this design spends its uncertainty — a missed character is one wrong glyph on
    screen, a false one is a rejection the model cannot satisfy. `么` was ABSENT for exactly that
    reason (a valid Big5 character) until it was measured drifting three times, at which point
    `_MEASURED_OTHER_SCRIPT` bought it back; the test below is the one that pins it now.
    """
    from rlm_notebook.instructions import _wrong_script_chars

    wrong = _wrong_script_chars("hant")
    for bad, good in MEASURED_DRIFT.items():
        assert wrong.get(bad) == good, f"{bad} should be reported as {good}"


def test_the_big5_letthrough_is_fully_classified():
    """Every character the codec lets through is READ, not characterised.

    An earlier note called them "almost exactly the genuinely ambiguous set" after reading the
    first forty of 131; the tail is `机 网 于 云 并 确 范 优 价 复`, so `基于`, `机器`, `后端`,
    `优化` and `价值` produced NO flag at all — this project's own subject matter.

    This is the guard that keeps the enumeration honest: a zhconv upgrade adding a character to
    neither half fails the build, instead of silently landing it in the unflagged one.
    """
    import zhconv.zhconv as zh

    from rlm_notebook.instructions import _BIG5_SHARED

    table = {
        src: dst
        for src, dst in zh.getdict("zh-hant").items()
        if len(src) == 1 and len(dst) == 1 and src != dst
    }
    encodable = set()
    for src in table:
        try:
            src.encode("big5")
        except (UnicodeEncodeError, UnicodeError):
            continue
        if src.isalnum():
            encodable.add(src)

    shared = _BIG5_SHARED["hant"]
    assert shared <= encodable, f"SHARED names characters the gate already flags: {shared - encodable}"
    unread = encodable - shared - set(_wrong_script_chars_keys())
    assert not unread, f"unclassified Big5-encodable rewrites: {''.join(sorted(unread))}"


def _wrong_script_chars_keys():
    from rlm_notebook.instructions import _wrong_script_chars

    return _wrong_script_chars("hant").keys()


def test_no_shared_character_is_ever_flagged_in_its_own_word():
    """The 52 unflagged characters, each with the Traditional word that earns it the exemption.

    Two independent readings produced this list — this project's and a sibling project's — agreeing on
    72 characters and disagreeing on 16, and EACH caught real errors in the other: `伙食` and
    `凶宅` would have been corrupted by this one, while `昵稱`, `腌菜`, `昆虫`, `蚝油` and `蝎子`
    were missed by it.
    """
    from rlm_notebook.instructions import _actionable, _script_offenders, _wrong_script_chars

    wrong = _wrong_script_chars("hant")
    words = [
        "干預", "台灣", "一群人", "里程碑", "高峰會", "秘密", "神采飛揚", "准許", "上游",
        "伙食", "凶宅", "范仲淹", "余光中", "東涌", "朴槿惠", "岳父", "咸豐", "濃郁",
        "涂先生", "公厘", "北斗", "占卜", "佳肴", "粽子", "肥皂", "痴心", "栗子", "床鋪",
        "征服", "托盤", "岩石", "嘴唇", "吃飯", "小丑", "復辟", "雇用", "發霉", "灶神",
        "杰出", "凄涼", "苧麻", "喂", "兩棲",
    ]
    for word in words:
        flagged = _actionable(_script_offenders(word, wrong, "hant"))
        assert not flagged, f"{word} is correct Traditional but was flagged: {flagged}"


def test_a_proper_noun_keeps_its_character_unflagged():
    """Where this list deliberately diverges from a sibling project's, and the reason is invariant 69.

    That project ranks `范`, `余`, `涌` as Simplified because the drift is commoner in technical rather than literary corpora
    than the surname. Here a name outranks it: told `范 -> 範`, an obedient model writes `範仲淹`,
    and a reader who wants to look the name up needs the string the sources used. `吁` and `咨` are
    the same call on an idiom rather than a name, and are the weaker half of it.
    """
    from rlm_notebook.instructions import _BIG5_SHARED

    for char in "范余涌涂朴杰岳郁":
        assert char in _BIG5_SHARED["hant"], f"{char} names a person or a place"


def test_the_suggestion_is_the_regional_standard_not_just_a_traditional_form():
    """`zh-hant` answers "a Traditional form", not "the form Taiwan writes": it maps `为` to `爲`
    where Taiwan writes `為`, and the same for `众`/`眾`, `启`/`啟`, `账`/`帳`, `伪`/`偽` — 22 of
    the characters this gate flags. Telling a model to write `爲` is telling it to write a
    character no Taiwanese reader uses.

    Mapped from the SOURCE character, never from `zh-hant`'s answer: `账` reaches `賬` under
    `zh-hant` and `zh-tw` leaves that alone, while `账` maps straight to `帳`. The two agree on 29
    of the 33 characters where anything differs and `via src` is right on all four of the rest.
    """
    from rlm_notebook.instructions import _wrong_script_chars

    wrong = _wrong_script_chars("hant")
    for bad, good in {"为": "為", "众": "眾", "启": "啟", "账": "帳",
                      "伪": "偽", "腭": "顎", "钚": "鈽"}.items():
        assert wrong.get(bad) == good, f"{bad} must be reported as {good}, the Taiwan standard"


def test_the_script_check_blocks_once_and_never_holds_a_run_hostage():
    """It fires AT MOST ONCE per run, and that bound is the design.

    Every other check here rejects something WRONG; a Simplified character is cosmetic, and the
    detector cannot tell one from a Japanese glyph being quoted inline. A check the model cannot
    satisfy loses the whole episode — the trade invariant 66 already refuses elsewhere.
    """
    from rlm_notebook.instructions import make_grounded_validator
    from rlm_notebook.schema import PodcastScript

    validate = make_grounded_validator(PodcastScript, lambda: set(), lambda: "hant")
    first = validate(_drifted("這有点像人類的合作，海峡的问题。"))
    assert first.startswith("Validation failed"), first
    # Named WITH its fix, or the model is being told only that it is wrong.
    assert "点 -> 點" in first and "峡 -> 峽" in first and "问 -> 問" in first
    # ...and the second call passes the identical input.
    assert not validate(_drifted("這有点像人類的合作，海峡的问题。")).startswith("Validation failed")


def test_a_quoted_character_is_exempt_from_the_script_check():
    """`quote` is verbatim source text, and this project's own corpora carry JAPANESE, whose
    shinjitai collide with Chinese simplified forms — `学`, `会`, `国` and `峡` are all flagged by
    the character test and are correct inside a Japanese quotation. Same exemption, and the same
    reason, as `_marker_offenders`."""
    from rlm_notebook.instructions import make_grounded_validator
    from rlm_notebook.schema import PodcastScript

    validate = make_grounded_validator(PodcastScript, lambda: set(), lambda: "hant")
    clean_prose_japanese_quote = _drifted("這一段完全是正體字。", quote="ホルムズ海峡の学会")
    assert not validate(clean_prose_japanese_quote).startswith("Validation failed")


def test_the_script_check_is_inert_when_the_language_pins_no_script():
    """`script_family` matches on the language NAME, which is correct HERE and was wrong in the
    prompt: `arun` receives the RESOLVED value, while a class-level `instructions` string is
    composed at import time and only ever sees the placeholder. Do not unify the two."""
    from rlm_notebook.instructions import make_grounded_validator, script_family
    from rlm_notebook.schema import PodcastScript

    assert script_family("Traditional Chinese") == "hant"
    assert script_family("zh-Hant") == "hant"
    assert script_family("Simplified Chinese") == "hans"
    assert script_family("English") is None and script_family(None) is None

    validate = make_grounded_validator(PodcastScript, lambda: set(), lambda: None)
    assert not validate(_drifted("這有点像人類的合作。")).startswith("Validation failed")


def test_every_shipped_task_wires_the_script_check_to_its_own_run():
    """Through the SHIPPED classes and their real `tools`, not a hand-built validator.

    This file exists because its first version tested a call shape the product never makes, and a
    green suite hid a feature that was entirely dead. The validator is built in `GroundedTask.
    __init__` from a `lambda: self._script`, so pointing that attribute at a family and calling the
    task's own tool is the same path a run takes.
    """
    import rlm_harness.runtime as rt
    from rlm_harness import RLMConfig
    from rlm_harness.testing import scripted_lm

    dummy = scripted_lm([{"reasoning": "r", "code": "SUBMIT"}])
    rt.configure(
        RLMConfig(main_model="x", sub_model="x", interpreter="pyodide", observe=False),
        main_lm=dummy,
        sub_lm=dummy,
    )

    from rlm_notebook.audio import GeneratePodcastScript
    from rlm_notebook.guide import (
        GenerateFAQ,
        GenerateKeyInsight,
        GenerateSummary,
        GenerateTimeline,
    )
    from rlm_notebook.task import AnswerQuestion

    for cls in (
        AnswerQuestion,
        GenerateSummary,
        GenerateFAQ,
        GenerateTimeline,
        GenerateKeyInsight,
        GeneratePodcastScript,
    ):
        task = cls(skills_dir=None)
        assert task._script is None, f"{cls.__name__} must start with no script pinned"
        task._script = "hant"
        payload = _payload_for(task.output_model, "這有点像合作，海峡的问题。")
        verdict = task.tools[0](payload)
        assert verdict.startswith("Validation failed"), f"{cls.__name__}: {verdict}"
        assert "点 -> 點" in verdict, cls.__name__


def test_arun_captures_the_resolved_output_language():
    """`_script` comes from the run's own kwargs. A task that never captured it would leave the
    check inert everywhere, which is exactly how the prompt rule this file already records spent
    its life shipping and doing nothing."""
    import rlm_harness.runtime as rt
    from rlm_harness import RLMConfig
    from rlm_harness.testing import scripted_lm

    dummy = scripted_lm([{"reasoning": "r", "code": "SUBMIT"}])
    rt.configure(
        RLMConfig(main_model="x", sub_model="x", interpreter="pyodide", observe=False),
        main_lm=dummy,
        sub_lm=dummy,
    )

    import asyncio

    from rlm_harness import RLMTask

    from rlm_notebook.task import AnswerQuestion

    task = AnswerQuestion(skills_dir=None)
    seen = {}

    async def fake(self, **inputs):
        seen["script"] = self._script

    original = RLMTask.arun
    RLMTask.arun = fake
    try:
        asyncio.run(task.arun(sources="", question="q", output_language="Traditional Chinese"))
        assert seen["script"] == "hant"
        asyncio.run(task.arun(sources="", question="q", output_language="English"))
        assert seen["script"] is None
    finally:
        RLMTask.arun = original


def _payload_for(model, text):
    """One minimal valid instance of `model` carrying `text` in a prose field."""
    import json

    name = model.__name__
    cite = {"source_id": "s1", "locator": "whole", "quote": "q", "answer_span": ""}
    shapes = {
        "Answer": {"text": text, "citations": [cite], "follow_ups": []},
        "Summary": {"text": text, "citations": [cite]},
        "KeyInsight": {"text": text, "citations": [cite]},
        "FAQ": {"items": [{"question": text, "answer": text, "citations": [cite]}]},
        "Timeline": {"events": [{"when": "2026", "description": text, "citations": [cite]}]},
        "PodcastScript": {"utterances": [{"speaker": "host_a", "text": text, "citations": [cite]}]},
    }
    # Read off `model_fields` rather than trusted: a task whose output shape changes must fail
    # LOUDLY here instead of silently testing a payload the schema no longer accepts.
    assert name in shapes, f"no payload shape for {name}; add one rather than skipping it"
    return json.dumps(shapes[name])


def test_the_script_check_never_asks_for_a_character_it_already_has():
    """`拮据` and `恒生` are ordinary Traditional, and the check rejected them with `据 -> 据` and
    `恒 -> 恒` — an instruction that cannot be followed.

    `_suggest` returns the phrase-aware conversion at the position, and where zhconv's phrase table
    leaves a character alone (because it is already right in THAT word) that is the character
    itself. A rejection the model cannot satisfy is the exact failure invariant 66 forbids; the
    once-per-run bound capped the cost and did not make the message coherent. Sixteen gate
    characters have such a context, so the documented `拮据` was not the only one.
    """
    from rlm_notebook.instructions import _actionable, _script_offenders, _wrong_script_chars

    wrong = _wrong_script_chars("hant")
    for text in ("公司財務拮据", "恒生指數", "溫度計與温泉", "推薦與草荐"):
        kept = _actionable(_script_offenders(text, wrong, "hant"))
        assert not [o for o in kept if o[1] == o[2]], f"{text}: told to rewrite a character as itself"

    # It must not swallow a real one: 这 has no phrase entry that leaves it alone.
    real = _actionable(_script_offenders("这个问题", wrong, "hant"))
    assert ("", "这", "這") in real


def test_the_rejection_counts_characters_not_fields():
    """`len(offenders)` counts `(path, char, fix)` triples, so one field holding four wrong
    characters reported "4 field(s) carry a character" — a sentence that is wrong twice."""
    import json

    from rlm_notebook.instructions import make_grounded_validator
    from rlm_notebook.schema import PodcastScript

    validate = make_grounded_validator(PodcastScript, lambda: set(), lambda: "hant")
    verdict = validate(
        json.dumps({"utterances": [{"speaker": "host_a", "text": "这个问题很难", "citations": []}]})
    )
    assert "across 1 field" in verdict, verdict
    assert "field(s)" not in verdict


def test_script_family_matches_both_orderings_of_the_language_name():
    """`Chinese (Traditional)` is as ordinary a spelling as `Traditional Chinese` and matched
    NOTHING, which turns the whole check off silently — and `RN_OUTPUT_LANGUAGE` and the settings
    file accept any string, since `clean_language` bounds length rather than the character set. A
    needle list is inherently incomplete; these are the spellings a person actually writes.
    """
    from rlm_notebook.instructions import script_family

    for name in ("Traditional Chinese", "Chinese (Traditional)", "zh-Hant", "繁體中文", "正體中文"):
        assert script_family(name) == "hant", name
    for name in ("Simplified Chinese", "Chinese (Simplified)", "zh-Hans", "简体中文", "簡體中文"):
        assert script_family(name) == "hans", name
    for name in ("English", "Japanese", "", None):
        assert script_family(name) is None, name


def test_the_validator_records_a_tool_call():
    """`record_tool_call` is OPT-IN — every tool wrapper calls it or the event does not exist.

    This one did not, so no `tool_call` event was ever written, the Trajectory drawer's timeline
    was empty on EVERY run, and its empty state read "this run called no tools" while the turn's
    own code pane showed `validate_podcastscript(...)` three lines away. Upstream's `read_skill`
    records; ours simply never did.

    It also closes a gap this project wrote down as a measurement limitation: a live A/B of the
    script check could not say whether the validator had FIRED.

    The JSON is the whole artifact, so its LENGTH is recorded and its TEXT is not — invariant 52's
    rule for the ticker and invariant 70's for the drawer.
    """
    import json
    import tempfile
    from pathlib import Path as _Path

    from rlm_harness.trace import TraceRecorder

    from rlm_notebook.instructions import make_grounded_validator
    from rlm_notebook.schema import PodcastScript

    out = _Path(tempfile.mkdtemp()) / "t.jsonl"
    validate = make_grounded_validator(PodcastScript, lambda: set(), lambda: None)
    secret = "這句話是成品本身，不該進 trace"
    good = json.dumps({"utterances": [{"speaker": "host_a", "text": secret, "citations": []}]})
    with TraceRecorder(str(out), run_id="x", meta={}):
        validate(json.dumps([{"speaker": "host_a"}]))
        validate(good)

    calls = [
        json.loads(line)["payload"]
        for line in out.read_text().splitlines()
        if json.loads(line).get("type") == "tool_call"
    ]
    assert len(calls) == 2, f"both calls must be recorded, got {calls}"
    assert [c["ok"] for c in calls] == [False, True], calls
    assert all(c["tool"] == "validate_podcastscript" for c in calls), calls
    assert all(c["duration_s"] is not None for c in calls), calls
    # The size, never the text.
    assert calls[1]["args"] == {"chars": len(good)}
    assert secret not in out.read_text(), "the artifact leaked into the trace"
