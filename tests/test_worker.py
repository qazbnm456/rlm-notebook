"""`worker.py`'s internal functions, tested directly (in-process) rather than through a real spawned
subprocess — that's what `test_runner.py` covers, using tiny throwaway scripts rather than the full
dspy/rlm-harness stack, to keep the offline suite fast and credential-free.
"""

from __future__ import annotations

import io
import json

import pytest

from rlm_notebook import worker


def test_resolve_task_class_finds_a_real_class():
    cls = worker._resolve_task_class("rlm_notebook.schema:Answer")
    from rlm_notebook.schema import Answer

    assert cls is Answer


def test_resolve_task_class_raises_on_missing_colon():
    with pytest.raises(ValueError, match="module:ClassName"):
        worker._resolve_task_class("rlm_notebook.schema.Answer")


def test_resolve_task_class_raises_on_unknown_module():
    with pytest.raises(ImportError):
        worker._resolve_task_class("rlm_notebook.not_a_real_module:Thing")


def test_resolve_task_class_raises_on_unknown_class():
    with pytest.raises(AttributeError):
        worker._resolve_task_class("rlm_notebook.schema:NotARealClass")


def test_emit_prints_exactly_one_json_line(capsys):
    worker._emit({"ok": True, "result": {"a": 1}})
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"ok": True, "result": {"a": 1}}


def test_emit_serializes_pydantic_models_via_model_dump(capsys):
    from rlm_notebook.schema import Answer

    worker._emit({"ok": True, "result": Answer(text="hi", citations=[])})
    payload = json.loads(capsys.readouterr().out)
    assert payload["result"] == {"text": "hi", "citations": [], "follow_ups": []}


def test_main_reports_a_clean_error_on_malformed_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    code = worker.main(["run1", "/tmp/trace.jsonl", "rlm_notebook.schema:Answer"])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "not valid JSON" in payload["error"]


def test_main_reports_a_clean_error_on_an_unresolvable_task(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    code = worker.main(["run1", "/tmp/trace.jsonl", "not.a.real:Module"])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "cannot resolve task" in payload["error"]


def test_main_rejects_the_wrong_number_of_arguments(capsys):
    code = worker.main(["only-one-arg"])
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False


def test_a_wrapped_error_carries_its_root_cause_across_the_process_boundary():
    """`RLMTaskError: Failed to produce a valid 'script' after 1 attempts` is what a user was shown
    for a run whose real fault was the model echoing a JSON schema instead of the fields the adapter
    asked for. The wrapper names the symptom and the chain names the cause, and the cause was being
    dropped at exactly the boundary where a person starts reading."""
    try:
        try:
            raise ValueError("adapter failed to parse: got a schema, expected [reasoning, code]")
        except ValueError as inner:
            raise RuntimeError("Failed to produce a valid 'script' after 2 attempts") from inner
    except RuntimeError as exc:
        described = worker._describe(exc)

    assert described.startswith("RuntimeError: Failed to produce a valid 'script'")
    assert "caused by ValueError: adapter failed to parse" in described


def test_an_unwrapped_error_is_not_padded_with_itself():
    described = worker._describe(ValueError("plain"))
    assert described == "ValueError: plain"
    assert "caused by" not in described


def test_both_halves_are_bounded_not_just_the_cause():
    """It ends up in an HTTP error body and on screen. The first version capped only the CAUSE and
    asserted `< 800` against a 600 cap, so a raw `AdapterParseError` reaching the worker unwrapped —
    which embeds the model's entire completion — produced a 20,000-character HTTP body and the test
    saw nothing, its own head being seven characters long."""
    huge = "H" * 20000
    assert len(worker._describe(RuntimeError(huge))) < 2 * worker._ERROR_CHARS

    try:
        try:
            raise ValueError("c" * 20000)
        except ValueError as inner:
            raise RuntimeError(huge) from inner
    except RuntimeError as exc:
        described = worker._describe(exc)
    assert len(described) < 3 * worker._ERROR_CHARS


def test_the_diagnostic_tail_survives_truncation():
    """dspy orders `AdapterParseError.__str__` as adapter-name, then the WHOLE LM completion, then
    the expected/actual field summary — so a HEAD truncation deletes precisely the two lines worth
    reading. An independent review measured the cutoff at a ~534-character completion, i.e. the
    first version failed on the exact bug this function was added for."""
    message = (
        "Adapter JSONAdapter failed to parse the LM response.\n\nLM Response: "
        + "x" * 3000
        + "\n\nExpected to find output fields in the LM response: [reasoning, code]"
        + "\n\nActual output fields parsed from the LM response: []"
    )
    try:
        try:
            raise ValueError(message)
        except ValueError as inner:
            raise RuntimeError("Failed to produce a valid 'script' after 1 attempts") from inner
    except RuntimeError as exc:
        described = worker._describe(exc)

    assert "JSONAdapter failed to parse" in described, "the head is gone"
    assert "Actual output fields parsed from the LM response: []" in described, (
        "the diagnostic TAIL is gone — this is the half that says what the model actually returned"
    )
    assert "chars elided" in described, "a reader cannot tell the message was cut"


def test_a_suppressed_context_stays_suppressed():
    """`raise X from None` is an explicit statement that the context is not to be shown; resurfacing
    it here would leak what somebody deliberately suppressed."""
    try:
        try:
            raise ValueError("SUPPRESSED")
        except ValueError:
            raise RuntimeError("outer") from None
    except RuntimeError as exc:
        described = worker._describe(exc)
    assert described == "RuntimeError: outer"
    assert "SUPPRESSED" not in described


def test_a_falsy_exception_still_has_its_cause_found():
    """`root.__cause__ or root.__context__` tests truthiness. An exception class with a falsy
    `__bool__` would have its cause skipped entirely."""

    class Falsy(Exception):
        def __bool__(self):
            return False

    try:
        try:
            raise ValueError("the real fault")
        except ValueError as inner:
            raise Falsy("wrapper") from inner
    except Falsy as exc:
        described = worker._describe(exc)
    assert "the real fault" in described


def test_an_exception_group_does_not_swallow_the_fault():
    """The subscription path's SDK runs on anyio task groups, and this project has been bitten by a
    `BaseExceptionGroup` once already (invariant 34)."""
    described = worker._describe(ExceptionGroup("group", [ValueError("inner fault")]))
    assert "inner fault" in described


def test_an_unprintable_exception_does_not_cost_the_whole_report():
    """`str(exc)` is arbitrary third-party code, and a raise here happens inside the handler about
    to emit the only JSON line the parent will ever see — the worker would die with no output and
    `runner` would report "failed with no error message", losing even the wrapper."""

    class Unprintable(Exception):
        def __str__(self):
            raise RuntimeError("nope")

    try:
        try:
            raise Unprintable()
        except Unprintable as inner:
            raise RuntimeError("outer") from inner
    except RuntimeError as exc:
        described = worker._describe(exc)
    assert described.startswith("RuntimeError: outer")
    assert "Unprintable" in described


def test_a_cause_cycle_terminates():
    a = ValueError("a")
    b = ValueError("b")
    a.__cause__ = b
    b.__cause__ = a
    assert "ValueError" in worker._describe(a)


def test_the_context_chain_is_followed_when_there_is_no_explicit_cause():
    try:
        try:
            raise ValueError("implicit")
        except ValueError:
            raise RuntimeError("outer")
    except RuntimeError as exc:
        described = worker._describe(exc)
    assert "implicit" in described
