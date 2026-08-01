"""`api.py`'s HTTP endpoints, driven through FastAPI's `TestClient`. `runner.start_run`/
`runner.wait_result` are monkeypatched to a fake in every test — this suite never spawns a real
subprocess or needs model credentials; `test_runner.py` covers the real subprocess mechanics, and
this project's "LIVE run" caveat (CLAUDE.md's Verify section) applies here too.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from rlm_notebook import api
from rlm_notebook.notebook import load_notebook
from rlm_notebook.schema import FAQ, KeyInsight, Summary, Timeline


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Every notebook path this test suite touches is relative (`notebooks/<id>.json`) — isolate
    each test into its own directory so tests can't see each other's notebook files."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _clear_active_runs():
    """`api._ACTIVE_RUNS` is a module-level dict shared by the whole test session (the module is
    imported once) — clear it before AND after each test so one test's fake in-flight run can
    never leak into another's."""
    api._ACTIVE_RUNS.clear()
    yield
    api._ACTIVE_RUNS.clear()


@pytest.fixture
def client():
    return TestClient(api.app)


class _FakeRun:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


def _mock_runner(monkeypatch, result: dict, *, dotted_tasks: list[str] | None = None):
    """Replace `runner.start_run`/`runner.wait_result` with fakes that return `result` — no
    subprocess is ever spawned. `dotted_tasks`, if given, records every `dotted_task` string
    `start_run` was called with, so a test can assert the right task class was requested."""

    async def _fake_start_run(run_id, trace_dir, dotted_task, kwargs):
        if dotted_tasks is not None:
            dotted_tasks.append(dotted_task)
        return _FakeRun(run_id)

    async def _fake_wait_result(run, *, timeout=None):
        return result

    monkeypatch.setattr(api.runner, "start_run", _fake_start_run)
    monkeypatch.setattr(api.runner, "wait_result", _fake_wait_result)


def _live_env(monkeypatch) -> None:
    monkeypatch.setenv("RN_MAIN_MODEL", "test/model")
    monkeypatch.delenv("RN_INTERPRETER", raising=False)


# --- /notebooks/{id}/sources & GET /notebooks/{id} ----------------------------------------------


def test_add_sources_creates_and_persists_a_notebook(client, tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")

    resp = client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "mynb"
    assert len(body["sources"]) == 1
    assert load_notebook("mynb") is not None  # actually persisted, not just returned


def test_add_sources_extends_without_duplicating(client, tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("hello b", encoding="utf-8")

    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})
    resp = client.post("/notebooks/mynb/sources", json={"sources": [str(a), str(b)]})

    assert resp.status_code == 200
    assert [s["origin"] for s in resp.json()["sources"]] == [str(a), str(b)]


def test_add_sources_reports_422_on_ingestion_failure(client, tmp_path):
    resp = client.post("/notebooks/mynb/sources", json={"sources": [str(tmp_path / "nope.txt")]})
    assert resp.status_code == 422


def test_add_sources_reports_409_on_a_corrupted_notebook_file(client, tmp_path):
    path = tmp_path / "notebooks" / "mynb.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"id": "mynb", "sources": [}', encoding="utf-8")

    resp = client.post("/notebooks/mynb/sources", json={"sources": []})
    assert resp.status_code == 409


def test_get_notebook_404_when_missing(client):
    resp = client.get("/notebooks/does-not-exist")
    assert resp.status_code == 404


def test_get_notebook_returns_sources_and_turn_count(client, tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})

    resp = client.get("/notebooks/mynb")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "mynb"
    assert body["turn_count"] == 0
    assert len(body["sources"]) == 1


# --- /notebooks/{id}/ask -------------------------------------------------------------------------


def test_ask_404_when_notebook_missing(client, monkeypatch):
    _live_env(monkeypatch)
    resp = client.post("/notebooks/does-not-exist/ask", json={"question": "what?"})
    assert resp.status_code == 404


def test_ask_runs_isolated_and_returns_verified_citations(client, monkeypatch, tmp_path):
    _live_env(monkeypatch)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})

    dotted_tasks: list[str] = []
    _mock_runner(
        monkeypatch,
        {
            "text": "the answer",
            "citations": [
                {"source_id": "s1", "locator": "whole", "quote": "hello"},
                {"source_id": "s1", "locator": "not-a-real-locator", "quote": "nope"},
            ],
        },
        dotted_tasks=dotted_tasks,
    )

    resp = client.post("/notebooks/mynb/ask", json={"question": "what does it say?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "the answer"
    assert body["citations"][0]["verified"] is True
    assert body["citations"][1]["verified"] is False
    assert dotted_tasks == ["rlm_notebook.task:AnswerQuestion"]


def test_ask_persists_the_turn_to_the_notebook(client, monkeypatch, tmp_path):
    _live_env(monkeypatch)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})
    _mock_runner(monkeypatch, {"text": "the answer", "citations": []})

    client.post("/notebooks/mynb/ask", json={"question": "what?"})

    notebook = load_notebook("mynb")
    assert len(notebook.turns) == 1
    assert notebook.turns[0].question == "what?"
    assert notebook.turns[0].answer.text == "the answer"


def test_ask_translates_a_run_error_into_502(client, monkeypatch, tmp_path):
    _live_env(monkeypatch)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})

    async def _fake_start_run(run_id, trace_dir, dotted_task, kwargs):
        return _FakeRun(run_id)

    async def _fake_wait_result(run, *, timeout=None):
        raise api.runner.RunError("simulated crash")

    monkeypatch.setattr(api.runner, "start_run", _fake_start_run)
    monkeypatch.setattr(api.runner, "wait_result", _fake_wait_result)

    resp = client.post("/notebooks/mynb/ask", json={"question": "what?"})
    assert resp.status_code == 502
    assert "simulated crash" in resp.json()["detail"]


def test_ask_reports_a_clean_500_when_the_server_is_misconfigured(client, monkeypatch, tmp_path):
    """`NotebookConfig.from_env()` raises SystemExit when RN_MAIN_MODEL is unset — `_config()` must
    convert that into an HTTP response, not let SystemExit escape the request handler."""
    monkeypatch.delenv("RN_MAIN_MODEL", raising=False)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})

    resp = client.post("/notebooks/mynb/ask", json={"question": "what?"})
    assert resp.status_code == 500
    assert "RN_MAIN_MODEL" in resp.json()["detail"]


# --- /notebooks/{id}/guide/{kind} ----------------------------------------------------------------


def test_guide_404_on_unknown_kind(client, monkeypatch, tmp_path):
    _live_env(monkeypatch)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})

    resp = client.post("/notebooks/mynb/guide/not-a-real-kind")
    assert resp.status_code == 404


def test_guide_summary(client, monkeypatch, tmp_path):
    _live_env(monkeypatch)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})
    _mock_runner(monkeypatch, Summary(text="a summary", citations=[]).model_dump())

    resp = client.post("/notebooks/mynb/guide/summary")

    assert resp.status_code == 200
    assert resp.json()["text"] == "a summary"


def test_guide_faq(client, monkeypatch, tmp_path):
    _live_env(monkeypatch)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})
    faq = FAQ(items=[{"question": "q?", "answer": "a.", "citations": []}])
    _mock_runner(monkeypatch, faq.model_dump())

    resp = client.post("/notebooks/mynb/guide/faq")

    assert resp.status_code == 200
    assert resp.json()["items"][0]["question"] == "q?"


def test_guide_timeline(client, monkeypatch, tmp_path):
    _live_env(monkeypatch)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})
    timeline = Timeline(events=[{"when": "ch.1", "description": "it happens", "citations": []}])
    _mock_runner(monkeypatch, timeline.model_dump())

    resp = client.post("/notebooks/mynb/guide/timeline")

    assert resp.status_code == 200
    assert resp.json()["events"][0]["when"] == "ch.1"


def test_guide_insight(client, monkeypatch, tmp_path):
    _live_env(monkeypatch)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})
    _mock_runner(monkeypatch, KeyInsight(text="the one thing", citations=[]).model_dump())

    resp = client.post("/notebooks/mynb/guide/insight")

    assert resp.status_code == 200
    assert resp.json()["text"] == "the one thing"


def test_guide_dispatches_the_correct_task_per_kind(client, monkeypatch, tmp_path):
    _live_env(monkeypatch)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    client.post("/notebooks/mynb/sources", json={"sources": [str(a)]})

    dotted_tasks: list[str] = []
    _mock_runner(monkeypatch, Summary(text="x", citations=[]).model_dump(), dotted_tasks=dotted_tasks)
    client.post("/notebooks/mynb/guide/summary")
    assert dotted_tasks == ["rlm_notebook.guide:GenerateSummary"]


# --- /notebooks/{id}/cancel -----------------------------------------------------------------------


def test_cancel_404_when_no_active_run(client):
    resp = client.post("/notebooks/mynb/cancel")
    assert resp.status_code == 404


def test_cancel_calls_cancel_on_the_active_run(client):
    fake_run = _FakeRun("mynb-abcd1234")
    api._ACTIVE_RUNS["mynb"] = fake_run

    resp = client.post("/notebooks/mynb/cancel")

    assert resp.status_code == 200
    assert resp.json()["cancelled"] == "mynb-abcd1234"
    assert fake_run.cancelled is True
