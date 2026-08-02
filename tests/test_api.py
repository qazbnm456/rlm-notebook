"""`api.py`'s HTTP endpoints, driven through FastAPI's `TestClient`. `runner.start_run`/
`runner.wait_result` are monkeypatched to a fake in every test — this suite never spawns a real
subprocess or needs model credentials; `test_runner.py` covers the real subprocess mechanics, and
this project's "LIVE run" caveat (CLAUDE.md's Verify section) applies here too.

The API only accepts http(s) URLs as sources (CLAUDE.md invariant 26 — local file paths were an
unauthenticated arbitrary-file-read vector, found and fixed after an independent review), so every
test that needs a notebook with sources uses a fake `parse_web` (`_fake_web_ingestion` below)
rather than a real network call.
"""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from rlm_notebook import api, cli
from rlm_notebook.notebook import load_notebook
from rlm_notebook.schema import FAQ, KeyInsight, Summary, Timeline

_FAIL_URL = "https://example.com/fails-to-fetch"


def test_guide_task_registries_stay_in_sync_between_cli_and_api():
    """`cli._GUIDE_TASKS` and `api._GUIDE_TASKS` are two independent dicts (api.py must not import
    cli.py — see CLAUDE.md invariant 20), kept manually in sync. Found by an independent review:
    the sibling project's `_SPEAKER_LABELS` drift tripwire (added the previous slice, after an
    earlier review found the SAME class of gap) had no counterpart here yet."""
    assert set(cli._GUIDE_TASKS) == set(api._GUIDE_TASKS)
    for kind, task_cls in cli._GUIDE_TASKS.items():
        assert api._GUIDE_TASKS[kind][0] is task_cls


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


@pytest.fixture(autouse=True)
def _fake_web_ingestion(monkeypatch):
    """Fakes `ingest.parse_web` so every test that adds a `https://...` source never makes a real
    network call. `_FAIL_URL` is a sentinel the fake treats as a real ingestion failure, for the
    one test that needs to exercise `add_sources`'s error path."""
    from rlm_notebook.parsers.web import FetchError
    from rlm_notebook.schema import Source, SourceBlock

    def _fake_parse_web(url, source_id):
        if url == _FAIL_URL:
            raise FetchError(f"simulated fetch failure for {url}")
        return Source(
            id=source_id, kind="web", origin=url,
            blocks=[SourceBlock(locator="whole", text=f"content of {url}")],
        )

    monkeypatch.setattr("rlm_notebook.ingest.parse_web", _fake_parse_web)


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


def _add_a_source(client) -> None:
    resp = client.post("/notebooks/mynb/sources", json={"sources": ["https://example.com/a"]})
    assert resp.status_code == 200, resp.text


# --- /notebooks/{id}/sources & GET /notebooks/{id} ----------------------------------------------


def test_add_sources_creates_and_persists_a_notebook(client):
    resp = client.post("/notebooks/mynb/sources", json={"sources": ["https://example.com/a"]})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "mynb"
    assert len(body["sources"]) == 1
    assert load_notebook("mynb") is not None  # actually persisted, not just returned


def test_add_sources_extends_without_duplicating(client):
    client.post("/notebooks/mynb/sources", json={"sources": ["https://example.com/a"]})
    resp = client.post(
        "/notebooks/mynb/sources",
        json={"sources": ["https://example.com/a", "https://example.com/b"]},
    )

    assert resp.status_code == 200
    origins = [s["origin"] for s in resp.json()["sources"]]
    assert origins == ["https://example.com/a", "https://example.com/b"]


def test_add_sources_rejects_local_file_paths(client, tmp_path):
    """The core LFI fix: unlike `cli.py`'s `--source`, the API must never read an arbitrary local
    path off the machine it runs on — found and reproduced by an independent review (a mocked
    `/etc/passwd` read whose contents then came back through a citation)."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET CONTENTS", encoding="utf-8")

    resp = client.post("/notebooks/mynb/sources", json={"sources": [str(secret)]})

    assert resp.status_code == 422
    assert "secret.txt" not in resp.text or "TOP SECRET" not in resp.text  # never echoes file contents
    assert load_notebook("mynb") is None  # nothing was created, let alone populated


def test_add_sources_reports_422_on_a_real_ingestion_failure(client):
    resp = client.post("/notebooks/mynb/sources", json={"sources": [_FAIL_URL]})
    assert resp.status_code == 422


def test_add_sources_reports_409_on_a_corrupted_notebook_file(client, tmp_path):
    path = tmp_path / "notebooks" / "mynb.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"id": "mynb", "sources": [}', encoding="utf-8")

    resp = client.post("/notebooks/mynb/sources", json={"sources": []})
    assert resp.status_code == 409


@pytest.mark.parametrize("bad_id", ["!!!", "...", "---"])
def test_endpoints_report_400_not_500_on_a_notebook_id_that_reduces_to_an_empty_slug(
    client, monkeypatch, bad_id
):
    """`notebook.slug(bad_id)` reduces to an empty token, and `notebook_path` raises `ValueError` —
    found by an independent review: every endpoint reaching `load_notebook`/`load_or_create` used
    to catch `pydantic.ValidationError` only, so this `ValueError` escaped as an unhandled 500
    instead of a clean 4xx. Checks all four endpoints that take a notebook id, not just one.
    (`"////"` is deliberately NOT in this list: Starlette's default path converter doesn't match a
    literal `/` inside a single path segment, so that payload 404s at the ROUTING layer before
    ever reaching a handler — a different, already-safe code path, not this one.)"""
    _live_env(monkeypatch)
    assert client.get(f"/notebooks/{bad_id}").status_code == 400
    assert client.post(f"/notebooks/{bad_id}/sources", json={"sources": []}).status_code == 400
    assert client.post(f"/notebooks/{bad_id}/ask", json={"question": "x"}).status_code == 400
    assert client.post(f"/notebooks/{bad_id}/guide/summary").status_code == 400


def test_get_notebook_404_when_missing(client):
    resp = client.get("/notebooks/does-not-exist")
    assert resp.status_code == 404


def test_get_notebook_returns_sources_and_turn_count(client):
    _add_a_source(client)

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


def test_ask_runs_isolated_and_returns_verified_citations(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)

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


def test_ask_persists_the_turn_to_the_notebook(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"text": "the answer", "citations": []})

    client.post("/notebooks/mynb/ask", json={"question": "what?"})

    notebook = load_notebook("mynb")
    assert len(notebook.turns) == 1
    assert notebook.turns[0].question == "what?"
    assert notebook.turns[0].answer.text == "the answer"


def test_ask_translates_a_run_error_into_502(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)

    async def _fake_start_run(run_id, trace_dir, dotted_task, kwargs):
        return _FakeRun(run_id)

    async def _fake_wait_result(run, *, timeout=None):
        raise api.runner.RunError("simulated crash")

    monkeypatch.setattr(api.runner, "start_run", _fake_start_run)
    monkeypatch.setattr(api.runner, "wait_result", _fake_wait_result)

    resp = client.post("/notebooks/mynb/ask", json={"question": "what?"})
    assert resp.status_code == 502
    assert "simulated crash" in resp.json()["detail"]


def test_ask_reports_a_clean_500_when_the_server_is_misconfigured(client, monkeypatch):
    """`NotebookConfig.from_env()` raises SystemExit when RN_MAIN_MODEL is unset — `_config()` must
    convert that into an HTTP response, not let SystemExit escape the request handler."""
    monkeypatch.delenv("RN_MAIN_MODEL", raising=False)
    _add_a_source(client)

    resp = client.post("/notebooks/mynb/ask", json={"question": "what?"})
    assert resp.status_code == 500
    assert "RN_MAIN_MODEL" in resp.json()["detail"]


# --- /notebooks/{id}/guide/{kind} ----------------------------------------------------------------


def test_guide_404_on_unknown_kind(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)

    resp = client.post("/notebooks/mynb/guide/not-a-real-kind")
    assert resp.status_code == 404


def test_guide_summary(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, Summary(text="a summary", citations=[]).model_dump())

    resp = client.post("/notebooks/mynb/guide/summary")

    assert resp.status_code == 200
    assert resp.json()["text"] == "a summary"


def test_guide_faq(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    faq = FAQ(items=[{"question": "q?", "answer": "a.", "citations": []}])
    _mock_runner(monkeypatch, faq.model_dump())

    resp = client.post("/notebooks/mynb/guide/faq")

    assert resp.status_code == 200
    assert resp.json()["items"][0]["question"] == "q?"


def test_guide_timeline(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    timeline = Timeline(events=[{"when": "ch.1", "description": "it happens", "citations": []}])
    _mock_runner(monkeypatch, timeline.model_dump())

    resp = client.post("/notebooks/mynb/guide/timeline")

    assert resp.status_code == 200
    assert resp.json()["events"][0]["when"] == "ch.1"


def test_guide_insight(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, KeyInsight(text="the one thing", citations=[]).model_dump())

    resp = client.post("/notebooks/mynb/guide/insight")

    assert resp.status_code == 200
    assert resp.json()["text"] == "the one thing"


def test_guide_dispatches_the_correct_task_per_kind(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)

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
