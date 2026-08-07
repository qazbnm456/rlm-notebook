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
