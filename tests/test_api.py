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

import asyncio
import base64
import json
import os
import time
import types
from typing import ClassVar

import pytest
from pydantic import ValidationError

fastapi = pytest.importorskip("fastapi")
# Only the two concurrency tests at the bottom need a real ASGI client (TestClient serialises
# requests, so it cannot interleave two runs on one notebook). Skipped with fastapi if absent.
httpx = pytest.importorskip("httpx")

from _pdf_fixtures import make_text_pdf_bytes
from fastapi.testclient import TestClient

from rlm_notebook import api, cli
from rlm_notebook.notebook import load_notebook, notebook_path
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


class _FakeRequest:
    """Just the `headers` a handler reads. `ask`/`guide`/`audio`/`title`/`overview` all take a
    `Request` now, for `Accept-Language` — the handlers driven as bare coroutines (rather than
    through TestClient) have to supply one."""

    headers: ClassVar[dict[str, str]] = {}


class _FakeProcess:
    """Just enough of `asyncio.subprocess.Process` for `_RUN_PROCESSES` bookkeeping — Phase 3
    stashes `run.process` there, so `_FakeRun` needs one even though these tests never exercise the
    trace-stream endpoint's liveness check that actually reads `.returncode`."""

    returncode: int | None = None


class _FakeRun:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.cancelled = False
        self.process = _FakeProcess()

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
    # A forced language SKIPS `_resolve_language`'s model run entirely, which keeps every test that
    # isn't about language to exactly the runs it means to exercise. The resolution path has its own
    # tests below, which unset this.
    monkeypatch.setenv("RN_OUTPUT_LANGUAGE", "English")


def _add_a_source(client) -> None:
    resp = client.post("/notebooks/mynb/sources", json={"sources": ["https://example.com/a"]})
    assert resp.status_code == 200, resp.text


# --- GET /notebooks (list) ----------------------------------------------------------------------


def test_list_notebooks_empty_when_none_exist(client):
    resp = client.get("/notebooks")
    assert resp.status_code == 200
    assert resp.json() == {"notebooks": [], "unreadable": []}


def test_list_notebooks_reports_the_notebooks_own_id_not_the_slugged_filename(client):
    """`slug()` is lossy — a notebook id with characters outside `[A-Za-z0-9._-]` is folded before
    becoming a filename, so the listing must report the `id` stored INSIDE the file, not derive one
    from the filename stem (found during the pre-implementation blueprint audit)."""
    resp = client.post("/notebooks/My Notebook!/sources", json={"sources": ["https://example.com/a"]})
    assert resp.status_code == 200, resp.text

    resp = client.get("/notebooks")

    assert resp.status_code == 200
    body = resp.json()
    assert body["unreadable"] == []
    assert len(body["notebooks"]) == 1
    assert body["notebooks"][0]["id"] == "My Notebook!"
    assert body["notebooks"][0]["source_count"] == 1
    assert body["notebooks"][0]["turn_count"] == 0


def test_list_notebooks_flags_a_corrupted_file_without_breaking_the_rest(client, tmp_path):
    _add_a_source(client)
    corrupt_path = tmp_path / "notebooks" / "broken.json"
    corrupt_path.write_text('{"id": "broken", "sources": [}', encoding="utf-8")

    resp = client.get("/notebooks")

    assert resp.status_code == 200
    body = resp.json()
    assert body["unreadable"] == ["broken"]
    assert [nb["id"] for nb in body["notebooks"]] == ["mynb"]


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


def test_add_sources_accepts_pasted_text(client):
    resp = client.post("/notebooks/mynb/sources", json={"texts": ["some pasted text"]})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sources"]) == 1
    assert body["sources"][0]["kind"] == "text"
    assert body["sources"][0]["origin"].startswith("pasted:some pasted text #")


def test_add_sources_dedupes_identical_pasted_text_within_one_call(client):
    resp = client.post(
        "/notebooks/mynb/sources", json={"texts": ["same text", "same text", "same text"]}
    )
    assert resp.status_code == 200
    assert len(resp.json()["sources"]) == 1


def test_add_sources_dedupes_identical_pasted_text_across_calls(client):
    client.post("/notebooks/mynb/sources", json={"texts": ["same text"]})
    resp = client.post("/notebooks/mynb/sources", json={"texts": ["same text", "different text"]})

    assert resp.status_code == 200
    assert len(resp.json()["sources"]) == 2


def test_add_sources_rejects_blank_pasted_text(client):
    resp = client.post("/notebooks/mynb/sources", json={"texts": ["real text", "   "]})

    assert resp.status_code == 422
    assert load_notebook("mynb") is None  # rejected before anything was persisted


def test_add_sources_combines_urls_and_pasted_text_in_one_call(client):
    resp = client.post(
        "/notebooks/mynb/sources",
        json={"sources": ["https://example.com/a"], "texts": ["pasted content"]},
    )

    assert resp.status_code == 200
    kinds = {s["kind"] for s in resp.json()["sources"]}
    assert kinds == {"web", "text"}


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


def test_add_sources_reports_422_not_500_on_a_captionless_youtube_video(client, monkeypatch):
    """`CaptionError` (`parsers/youtube.py`) is a `ValueError` subclass specifically so this lands
    as the SAME clean 422 `add_sources` already gives any other ingestion failure — found by this
    feature's own pre-implementation audit before any code was written: a bare `RuntimeError`
    would satisfy neither `add_sources`'s nor `cli._prepare`'s `except (FetchError, ValueError,
    OSError)`, escaping as an unhandled 500 instead."""
    from rlm_notebook.parsers.youtube import CaptionError

    def _fake_parse_youtube(url, source_id, **kwargs):
        raise CaptionError(f"no captions available for {url!r}")

    monkeypatch.setattr("rlm_notebook.ingest.parse_youtube", _fake_parse_youtube)

    resp = client.post(
        "/notebooks/mynb/sources", json={"sources": ["https://www.youtube.com/watch?v=none"]}
    )
    assert resp.status_code == 422


def test_add_sources_reports_409_on_a_corrupted_notebook_file(client, tmp_path):
    path = tmp_path / "notebooks" / "mynb.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"id": "mynb", "sources": [}', encoding="utf-8")

    resp = client.post("/notebooks/mynb/sources", json={"sources": []})
    assert resp.status_code == 409


@pytest.mark.parametrize("odd_id", ["!!!", "...", "---", "\u6a21\u578b\u8981\u7761\u89ba"])
def test_an_id_outside_the_latin_whitelist_is_a_usable_notebook_not_a_400(
    client, monkeypatch, odd_id
):
    """These used to reduce to an empty slug and 400. A user reported the consequence: naming a
    notebook in Chinese returned `400 invalid notebook id … reduces to an empty token`. `slug` now
    falls back to `nb-<hash>` for any id the whitelist empties, so all of these are ordinary
    notebooks — the read endpoints 404 (nothing there yet) and the write endpoints succeed.

    This SUPERSEDES the earlier "400 not 500" test for these payloads; the 500 that invariant 27
    was created to fix is still gone, it is just no longer reachable by this input at all. Only a
    genuinely empty id still raises, which `test_an_empty_notebook_id_is_still_a_400` covers.
    (`"////"` is deliberately absent: Starlette's path converter doesn't match a literal `/` inside
    one segment, so it 404s at the ROUTING layer, a different and already-safe path.)"""
    _live_env(monkeypatch)
    assert client.get(f"/notebooks/{odd_id}").status_code == 404
    assert client.post(f"/notebooks/{odd_id}/sources", json={"texts": ["hi"]}).status_code == 200
    assert client.get(f"/notebooks/{odd_id}").json()["id"] == odd_id  # the id round-trips verbatim


def test_an_empty_notebook_id_is_still_a_400_on_every_id_taking_endpoint(client, monkeypatch):
    """"You gave me nothing" stays a real client error — only "you gave me a name in your own
    language" stopped being one. Invariant 27's mapping (`ValueError` -> 400, never an unhandled
    500) is what this pins, and it sweeps every id-taking endpoint that existed when this was written — NOT `/audio`, `/title`,
    `/overview`, `/sources/upload` or `/audio/file`, which an independent audit probed live and
    found correctly returning 400 too. The invariant holds; this list is the stale part rather than a sample: an
    independent review pointed out that rewriting the old test for the new rule had quietly dropped
    `ask`/`guide`/`sources/{id}`/`promote` from the sweep, which is the coverage invariant 27 was
    created by (a review finding four endpoints that had each independently forgotten the arm)."""
    _live_env(monkeypatch)
    blank = "%20%20"
    assert client.get(f"/notebooks/{blank}").status_code == 400
    assert client.post(f"/notebooks/{blank}/sources", json={"texts": ["hi"]}).status_code == 400
    assert client.post(f"/notebooks/{blank}/ask", json={"question": "x"}).status_code == 400
    assert client.post(f"/notebooks/{blank}/guide/summary").status_code == 400
    assert client.get(f"/notebooks/{blank}/sources/s1").status_code == 400
    assert client.post(f"/notebooks/{blank}/notes", json={"text": "x"}).status_code == 400
    assert client.delete(f"/notebooks/{blank}/notes/n1").status_code == 400
    assert client.post(f"/notebooks/{blank}/notes/n1/promote").status_code == 400


def test_a_lone_surrogate_run_id_is_not_a_500(client, monkeypatch):
    """`run_id` is a plain JSON body field, and RFC 8259 permits unpaired surrogate escapes that
    `json.loads` accepts. `_derive_run_id` calls `notebook.slug()` DIRECTLY, outside every
    `notebook_path` error wrapper — so when `slug` gained a `raw.encode("utf-8")` it stopped being
    total and this became an unauthenticated 500, reproduced by an independent review. `slug` must
    never raise for any `str`."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"text": "an answer", "citations": []})

    # Sent as raw bytes, not `json=`: httpx refuses to ENCODE a lone surrogate, so the escape has
    # to travel as JSON source text and be decoded server-side by `json.loads`, which accepts it.
    resp = client.post(
        "/notebooks/mynb/ask",
        content=rb'{"question": "x", "run_id": "\ud800"}',
        headers={"Content-Type": "application/json"},
    )

    assert resp.status_code != 500, resp.text


def test_get_notebook_404_when_missing(client):
    resp = client.get("/notebooks/does-not-exist")
    assert resp.status_code == 404


def test_get_notebook_returns_sources_and_turns(client):
    _add_a_source(client)

    resp = client.get("/notebooks/mynb")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "mynb"
    assert body["turns"] == []
    assert len(body["sources"]) == 1


def test_get_notebook_includes_full_turn_history_with_freshly_verified_citations(client, monkeypatch):
    """The web UI's Chat panel needs a re-opened notebook's past turns to render immediately, not
    just a count — added when building the Phase 1 web UI. Citations are re-verified against the
    CURRENT corpus at read time, same discipline as a brand-new answer (CLAUDE.md invariant 11)."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(
        monkeypatch,
        {
            "text": "the answer",
            "citations": [{"source_id": "s1", "locator": "whole", "quote": "hello"}],
        },
    )
    client.post("/notebooks/mynb/ask", json={"question": "what?"})

    resp = client.get("/notebooks/mynb")

    assert resp.status_code == 200
    turns = resp.json()["turns"]
    assert len(turns) == 1
    assert turns[0]["question"] == "what?"
    assert turns[0]["answer"] == "the answer"
    assert turns[0]["citations"][0]["verified"] is True


# --- GET /notebooks/{id}/sources/{source_id} -----------------------------------------------------


def test_get_source_404_when_notebook_missing(client):
    resp = client.get("/notebooks/does-not-exist/sources/s1")
    assert resp.status_code == 404


def test_get_source_404_when_source_id_unknown(client):
    _add_a_source(client)
    resp = client.get("/notebooks/mynb/sources/does-not-exist")
    assert resp.status_code == 404


def test_get_source_returns_full_text_every_block(client):
    """The web UI's source viewer (blueprint's "Post-launch addendum 2") needs the WHOLE source,
    not just a citation's short `quote` — this is the endpoint that closes NotebookLM's most basic
    loop: click a citation, see the highlighted original passage."""
    _add_a_source(client)

    resp = client.get("/notebooks/mynb/sources/s1")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "id": "s1",
        "kind": "web",
        "origin": "https://example.com/a",
        "flags": [],
        "blocks": [{"locator": "whole", "text": "content of https://example.com/a"}],
    }


# --- /notebooks/{id}/notes -----------------------------------------------------------------------


def test_add_note_creates_and_persists_a_notebook(client):
    """Mirrors `add_sources`: a brand-new notebook can start life by adding a note."""
    resp = client.post("/notebooks/mynb/notes", json={"text": "a first note"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["notes"] == [{"id": "n1", "text": "a first note"}]

    reloaded = client.get("/notebooks/mynb")
    assert reloaded.json()["notes"] == [{"id": "n1", "text": "a first note"}]


def test_add_note_rejects_blank_text(client):
    resp = client.post("/notebooks/mynb/notes", json={"text": "   "})
    assert resp.status_code == 422


def test_delete_note_404_when_notebook_missing(client):
    resp = client.delete("/notebooks/does-not-exist/notes/n1")
    assert resp.status_code == 404


def test_delete_note_404_when_note_id_unknown(client):
    client.post("/notebooks/mynb/notes", json={"text": "a note"})
    resp = client.delete("/notebooks/mynb/notes/does-not-exist")
    assert resp.status_code == 404


def test_delete_note_removes_it_and_persists(client):
    client.post("/notebooks/mynb/notes", json={"text": "a note"})
    resp = client.delete("/notebooks/mynb/notes/n1")
    assert resp.status_code == 200
    assert resp.json()["notes"] == []

    reloaded = client.get("/notebooks/mynb")
    assert reloaded.json()["notes"] == []


def test_promote_note_404_when_notebook_missing(client):
    resp = client.post("/notebooks/does-not-exist/notes/n1/promote")
    assert resp.status_code == 404


def test_promote_note_404_when_note_id_unknown(client):
    client.post("/notebooks/mynb/notes", json={"text": "a note"})
    resp = client.post("/notebooks/mynb/notes/does-not-exist/promote")
    assert resp.status_code == 404


def test_promote_note_turns_it_into_a_source_and_persists(client):
    client.post("/notebooks/mynb/notes", json={"text": "promote this text"})

    resp = client.post("/notebooks/mynb/notes/n1/promote")

    assert resp.status_code == 200
    body = resp.json()
    assert body["notes"] == []
    assert len(body["sources"]) == 1
    assert body["sources"][0]["kind"] == "text"

    reloaded = client.get("/notebooks/mynb")
    assert reloaded.json()["notes"] == []
    assert len(reloaded.json()["sources"]) == 1


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


# --- /notebooks/{id}/audio -----------------------------------------------------------------------


class _FakeTTSProvider:
    """A `TTSProvider` double: writes fixed bytes to `out_path` (or raises `TTSError`, if
    `boom` is set), so these tests never touch the real `edge-tts` network service — the same
    seam `test_tts.py` uses at a lower level (an injectable `_communicate_factory`), just faked one
    layer up since `api.py` only ever calls `provider.synthesize(...)`, never `edge-tts` directly."""
    # A `TTSProvider` now also declares its output FORMAT and its own language->voice defaults, so a
    # local model emitting WAV isn't forced through an MP3 encoder and one provider's voice names
    # can't leak into another's request (CLAUDE.md invariant 43).
    suffix = ".mp3"
    media_type = "audio/mpeg"

    def default_voices(self, language):
        return None

    def validate(self, language=None, voice_map=None):
        # Tracks `tts.TTSProvider`: the pre-flight that stops a bad language or voice from wasting
        # a real model run (invariant 19). A double that omits it would let a caller drop the call.
        self.validated = (language, voice_map)

    def fallback_voices(self):
        # Tracks `tts.TTSProvider`: a double that does not implement the whole Protocol lets a real
        # gap hide (an independent audit found the LAST-RESORT cast had never moved onto the
        # provider, so an unknown language on the local one fell through to an edge-tts name).
        return ("fake-voice-a", "fake-voice-b")


    def __init__(
        self,
        *,
        boom: str | None = None,
        payload: bytes = b"fake-mp3-bytes",
        offsets: list[float] | None = None,
    ) -> None:
        self.boom = boom
        self.payload = payload
        #: Per-utterance start offsets, as the real Protocol returns (`tts.TTSProvider.synthesize`
        #: is `-> list[float]`). This double used to return None, so nothing on the API side could
        #: carry timing at all — found by an independent review, which then showed by mutation that
        #: deleting every `offsets=` in `api.py` left the whole suite green.
        self.offsets = offsets
        self.calls: list[tuple] = []

    def synthesize(self, script, voice_map, out_path, language=None):
        self.calls.append((script, voice_map, out_path, language))
        if self.boom:
            raise api.TTSError(self.boom)
        out_path.write_bytes(self.payload)
        if self.offsets is not None:
            return self.offsets
        return [float(i) for i in range(len(script.utterances))]


def _fake_tts_provider(monkeypatch, provider: _FakeTTSProvider) -> None:
    monkeypatch.setattr(api, "get_tts_provider", lambda name: provider)


def _podcast_script_result(utterances: list[dict] | None = None) -> dict:
    return {"utterances": utterances or []}


def test_audio_404_when_notebook_missing(client, monkeypatch):
    _live_env(monkeypatch)
    resp = client.post("/notebooks/does-not-exist/audio")
    assert resp.status_code == 404


def test_audio_runs_isolated_and_returns_base64_encoded_audio(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    dotted_tasks: list[str] = []
    _mock_runner(
        monkeypatch,
        _podcast_script_result(
            [{"speaker": "host_a", "text": "hello", "citations": [
                {"source_id": "s1", "locator": "whole", "quote": "hello"}
            ]}]
        ),
        dotted_tasks=dotted_tasks,
    )
    provider = _FakeTTSProvider(payload=b"real-mp3-payload")
    _fake_tts_provider(monkeypatch, provider)

    resp = client.post("/notebooks/mynb/audio")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert dotted_tasks == ["rlm_notebook.audio:GeneratePodcastScript"]
    assert len(body["utterances"]) == 1
    assert body["utterances"][0]["speaker"] == "host_a"
    assert body["utterances"][0]["citations"][0]["verified"] is True
    assert base64.b64decode(body["audio_base64"]) == b"real-mp3-payload"
    # The temp file synthesize() wrote to must not survive the request.
    tmp_path = provider.calls[0][2]
    assert not tmp_path.exists()


def test_notebook_response_carries_the_slug_so_client_run_ids_match_the_servers(client):
    """The client builds its own run ids to open a live ticker on, and `_derive_run_id` prefixes
    them with `slug(notebook_id)`. Building them from the RAW id left every trace link dead for any
    id the slug changes — `"my notebook"`, or any non-Latin id, which invariant 10 exists to
    support (found by an independent audit; the server-side guard had been fixed, the client had
    not). Returned by the server rather than re-implemented in JS, hash fallback and all."""
    from rlm_notebook.notebook import slug

    for notebook_id in ("plain", "my notebook", "模型要睡覺"):
        created = client.post(
            f"/notebooks/{notebook_id}/notes", json={"text": "seed"}
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["id"] == notebook_id  # the handle a person typed is unchanged
        assert body["slug"] == slug(notebook_id)
        # This is the exact prefix `_derive_run_id` builds, so a client id can match a server one.
        assert not slug(notebook_id).startswith("-")


def test_audio_carries_offsets_through_response_persistence_and_reopen(client, monkeypatch):
    """The subtitle transcript is only as good as the offsets reaching the client, and there are
    THREE places they can be dropped: the POST response, the persisted `Podcast`, and the
    `GET /notebooks/{id}` reopen path. An independent review deleted each in turn and the whole
    suite stayed green, so all three are pinned here rather than trusting one to imply the others.
    """
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(
        monkeypatch,
        _podcast_script_result(
            [
                {"speaker": "host_a", "text": "one", "citations": []},
                {"speaker": "host_b", "text": "two", "citations": []},
                {"speaker": "host_a", "text": "three", "citations": []},
            ]
        ),
    )
    _fake_tts_provider(monkeypatch, _FakeTTSProvider(offsets=[0.0, 5.25, 7.5]))

    posted = client.post("/notebooks/mynb/audio")
    assert posted.status_code == 200, posted.text
    assert posted.json()["offsets"] == [0.0, 5.25, 7.5]

    reopened = client.get("/notebooks/mynb")
    assert reopened.status_code == 200
    podcast = reopened.json()["podcast"]
    assert podcast["offsets"] == [0.0, 5.25, 7.5]
    # Parallel to `utterances`, never a field on one — a consumer pairs them by index.
    assert len(podcast["offsets"]) == len(podcast["utterances"])


def test_audio_passes_the_resolved_language_to_synthesize(client, monkeypatch):
    """`TTSProvider.synthesize` takes the resolved language because a CROSS-LINGUAL provider's voice
    and language are independent axes — chatterbox maps it to a `language_id`. An independent review
    mutation-proved this had zero coverage: passing `None` from BOTH call sites left the whole suite
    green, and the consequence is a Chinese script synthesized with `language_id="en"`, i.e. the
    confident nonsense `_language_id`'s raise exists to prevent."""
    _live_env(monkeypatch)  # pins RN_OUTPUT_LANGUAGE=English
    _add_a_source(client)
    _mock_runner(
        monkeypatch,
        _podcast_script_result([{"speaker": "host_a", "text": "hi", "citations": []}]),
    )
    provider = _FakeTTSProvider()
    _fake_tts_provider(monkeypatch, provider)

    assert client.post("/notebooks/mynb/audio").status_code == 200
    assert provider.calls[0][3] == "English"
    # ...and the same language reached the pre-flight, which is what makes invariant 19's ordering
    # meaningful rather than decorative.
    assert provider.validated[0] == "English"


def test_audio_returns_null_audio_when_script_has_no_utterances(client, monkeypatch):
    """A source with nothing worth discussing is a legitimate output (audio.py's instructions
    allow it) — must not call synthesize() on an empty script (EdgeTTSProvider raises TTSError for
    exactly that), and must not leave the frontend guessing with a missing field."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, _podcast_script_result([]))
    provider = _FakeTTSProvider()
    _fake_tts_provider(monkeypatch, provider)

    resp = client.post("/notebooks/mynb/audio")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"utterances": [], "audio_base64": None, "offsets": [], "audio_suffix": None}
    assert provider.calls == []  # synthesize() never called for an empty script


def test_audio_with_an_empty_script_clears_the_previously_persisted_episode(client, monkeypatch):
    """Invariant 42's "replaced on regenerate" has to cover the empty case: an independent audit
    found this arm returning early with the previous episode untouched, so `GET .../audio/file`
    kept serving audio for a script the notebook no longer had while the UI said there was none."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, _podcast_script_result([{"speaker": "host_a", "text": "hi",
                                                      "citations": []}]))
    _fake_tts_provider(monkeypatch, _FakeTTSProvider(payload=b"first-episode"))
    assert client.post("/notebooks/mynb/audio").status_code == 200
    assert client.get("/notebooks/mynb/audio/file").status_code == 200

    _mock_runner(monkeypatch, _podcast_script_result([]))
    _fake_tts_provider(monkeypatch, _FakeTTSProvider())
    resp = client.post("/notebooks/mynb/audio")

    assert resp.status_code == 200
    assert resp.json()["utterances"] == []
    assert client.get("/notebooks/mynb/audio/file").status_code == 404
    assert client.get("/notebooks/mynb").json()["podcast"] is None


def test_upload_reports_a_clean_500_when_the_size_cap_env_var_is_malformed(client, monkeypatch):
    """Invariant 24 claimed every `SystemExit` in `config.py` was reachable only through
    `from_env()`, so `_config()` covered them all. `max_upload_bytes` has one of its own and is the
    FIRST statement of this handler — an independent audit reproduced a raw 500 with a traceback."""
    monkeypatch.setenv("RN_MAX_UPLOAD_BYTES", "not-an-int")
    resp = client.post(
        "/notebooks/mynb/sources/upload",
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 500
    assert "server misconfigured" in resp.json()["detail"]


def test_audio_reports_a_clean_500_when_tts_provider_misconfigured_before_running_the_model(
    client, monkeypatch
):
    """The TTS provider must be resolved BEFORE the expensive model call, not after — CLAUDE.md
    invariant 19's ordering, extended to the API. Asserts BOTH the status code and that the
    subprocess was never started, so a bad RN_TTS_PROVIDER never wastes a real model call."""
    _live_env(monkeypatch)
    _add_a_source(client)
    monkeypatch.setenv("RN_TTS_PROVIDER", "not-a-real-provider")
    dotted_tasks: list[str] = []
    _mock_runner(monkeypatch, _podcast_script_result([]), dotted_tasks=dotted_tasks)

    resp = client.post("/notebooks/mynb/audio")

    assert resp.status_code == 500
    assert "not-a-real-provider" in resp.json()["detail"]
    assert dotted_tasks == []  # the model was never run


def test_audio_translates_a_synthesis_failure_into_502_and_cleans_up_the_temp_file(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(
        monkeypatch,
        _podcast_script_result([{"speaker": "host_a", "text": "hi", "citations": []}]),
    )
    provider = _FakeTTSProvider(boom="simulated network failure")
    _fake_tts_provider(monkeypatch, provider)

    resp = client.post("/notebooks/mynb/audio")

    assert resp.status_code == 502
    assert "audio synthesis failed" in resp.json()["detail"]
    assert "simulated network failure" in resp.json()["detail"]
    # The temp file created before synthesize() raised must not survive the failed request either
    # (audit round 2's fix: the finally must cover the failure path, not just the success path).
    tmp_path = provider.calls[0][2]
    assert not tmp_path.exists()


# --- /notebooks/{id}/sources/upload ----------------------------------------------------------------


class _FakeRequestDeclaredOversized:
    """A minimal request double with a declared Content-Length already over the cap, and a
    `.form()` that fails the test if it's ever called — the exact thing the audit found the
    original design DIDN'T actually prevent (FastAPI's own `File(...)` binding parses the whole
    body before the handler runs, regardless of any in-handler check). Taking `request: Request`
    directly is what lets this test prove the body is never touched at all."""

    headers: ClassVar = {"content-length": "999999999"}

    async def form(self):
        raise AssertionError("form() must not be called once Content-Length already exceeds the cap")


def test_upload_source_rejects_before_ever_reading_the_body_when_content_length_exceeds_cap():
    with pytest.raises(api.HTTPException) as exc_info:
        asyncio.run(api.upload_source("mynb", _FakeRequestDeclaredOversized()))
    assert exc_info.value.status_code == 413


class _FakeRequestNoContentLength:
    headers: ClassVar = {}

    async def form(self):
        raise AssertionError("form() must not be called when Content-Length is missing")


def test_upload_source_rejects_a_missing_content_length_with_411():
    with pytest.raises(api.HTTPException) as exc_info:
        asyncio.run(api.upload_source("mynb", _FakeRequestNoContentLength()))
    assert exc_info.value.status_code == 411


def test_upload_source_creates_and_persists_a_notebook(client):
    resp = client.post(
        "/notebooks/mynb/sources/upload",
        files={"file": ("notes.txt", b"hello from an uploaded file", "text/plain")},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "mynb"
    assert body["sources"][0]["kind"] == "text"
    assert body["sources"][0]["origin"] == "notes.txt"
    assert load_notebook("mynb") is not None


def test_upload_source_pdf():
    data = make_text_pdf_bytes(["hello uploaded pdf"])
    client = TestClient(api.app)

    resp = client.post(
        "/notebooks/mynb/sources/upload",
        files={"file": ("report.pdf", data, "application/pdf")},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sources"][0]["kind"] == "pdf"
    assert body["sources"][0]["origin"] == "report.pdf"


def test_upload_source_dedupes_by_filename(client):
    client.post(
        "/notebooks/mynb/sources/upload",
        files={"file": ("notes.txt", b"first version", "text/plain")},
    )
    resp = client.post(
        "/notebooks/mynb/sources/upload",
        files={"file": ("notes.txt", b"a different version, same filename", "text/plain")},
    )

    assert resp.status_code == 200
    assert len(resp.json()["sources"]) == 1  # second upload was a no-op — same origin


def test_upload_source_rejects_an_unsupported_file_type(client):
    resp = client.post(
        "/notebooks/mynb/sources/upload",
        files={"file": ("image.png", b"not really an image", "image/png")},
    )

    assert resp.status_code == 422
    assert load_notebook("mynb") is None  # rejected before anything was persisted


def test_upload_source_rejects_a_body_that_exceeds_the_declared_cap(client, monkeypatch):
    monkeypatch.setenv("RN_MAX_UPLOAD_BYTES", "10")

    resp = client.post(
        "/notebooks/mynb/sources/upload",
        files={"file": ("notes.txt", b"this is much longer than ten bytes", "text/plain")},
    )

    assert resp.status_code == 413


def test_upload_source_reports_400_not_500_on_an_empty_notebook_id(client):
    """`"!!!"` is a valid notebook id since the non-Latin fix, so the payload that exercises this
    handler's `ValueError` -> 400 arm is now a genuinely empty one."""
    resp = client.post(
        "/notebooks/%20%20/sources/upload",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


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


# --- Phase 3: client-supplied run_id + reasoning-trace endpoints ----------------------------------


def test_derive_run_id_uses_the_client_token_when_given():
    assert api._derive_run_id("mynb", "abc123") == "mynb-abc123"


def test_derive_run_id_sanitizes_the_client_token():
    """Reuses notebook.slug()'s whitelist — a client-supplied token becomes a filename component
    too, and an unsanitized value would be the same class of path-traversal vector invariant 10
    already closed for notebook ids."""
    assert api._derive_run_id("mynb", "../../etc/passwd") == "mynb-etc-passwd"


def test_derive_run_id_falls_back_to_a_server_random_token_when_none_given():
    run_id = api._derive_run_id("mynb", None)
    assert run_id.startswith("mynb-")
    assert len(run_id) == len("mynb-") + 8  # uuid4().hex[:8], byte-for-byte the old scheme


def test_ask_persists_the_client_supplied_run_id_on_the_chat_turn(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"text": "the answer", "citations": []})

    resp = client.post("/notebooks/mynb/ask", json={"question": "what?", "run_id": "myrun"})

    assert resp.status_code == 200, resp.text
    notebook = load_notebook("mynb")
    assert notebook.turns[0].run_id == "mynb-myrun"
    assert (api._TRACE_DIR / "mynb-myrun.jsonl").exists()


def test_ask_persists_a_server_generated_run_id_when_none_supplied(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"text": "the answer", "citations": []})

    client.post("/notebooks/mynb/ask", json={"question": "what?"})

    notebook = load_notebook("mynb")
    assert notebook.turns[0].run_id.startswith("mynb-")


def test_get_notebook_echoes_the_persisted_run_id_per_turn(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"text": "the answer", "citations": []})
    client.post("/notebooks/mynb/ask", json={"question": "what?", "run_id": "myrun"})

    resp = client.get("/notebooks/mynb")

    assert resp.json()["turns"][0]["run_id"] == "mynb-myrun"


def test_ask_reports_409_when_the_run_id_collides_with_one_already_in_use(client, monkeypatch):
    """The exclusive-create gate must reject a reused run_id BEFORE spawning a second subprocess:
    TraceRecorder's own lock is process-local and can't stop two independent workers from
    appending interleaved events to one file — found during this phase's own design audit, not
    discovered as a runtime bug."""
    _live_env(monkeypatch)
    _add_a_source(client)
    api._TRACE_DIR.mkdir(parents=True, exist_ok=True)
    (api._TRACE_DIR / "mynb-dupe.jsonl").touch()  # simulates an already-in-flight (or used) run_id

    resp = client.post("/notebooks/mynb/ask", json={"question": "what?", "run_id": "dupe"})

    assert resp.status_code == 409
    assert "dupe" in resp.json()["detail"]


def test_run_isolated_cleans_up_the_reserved_trace_file_when_start_run_fails(monkeypatch, tmp_path):
    """A failed subprocess spawn must not permanently occupy the run id — otherwise a later retry
    of the exact same notebook+token pair gets a false 409 forever instead of the real error."""
    monkeypatch.chdir(tmp_path)

    async def _boom(run_id, trace_dir, dotted_task, kwargs):
        raise OSError("simulated spawn failure")

    monkeypatch.setattr(api.runner, "start_run", _boom)

    with pytest.raises(OSError, match="simulated spawn failure"):
        asyncio.run(
            api._run_isolated("mynb", "some:Task", {}, api.NotebookConfig(), "mynb-willfail")
        )

    assert not (api._TRACE_DIR / "mynb-willfail.jsonl").exists()


def test_run_isolated_tracks_and_clears_run_processes(monkeypatch, tmp_path):
    """`_RUN_PROCESSES` (keyed by run_id, NOT notebook_id) must be populated while the run is in
    flight and cleared afterward — the whole point of adding it separately from `_ACTIVE_RUNS` was
    a precise per-run liveness signal for the trace-stream endpoint."""
    monkeypatch.chdir(tmp_path)
    _mock_runner(monkeypatch, {"ok": True})

    async def _run():
        return await api._run_isolated("mynb", "some:Task", {}, api.NotebookConfig(), "mynb-tracked")

    asyncio.run(_run())
    assert "mynb-tracked" not in api._RUN_PROCESSES  # cleared once the (fake) run finished


def _write_trace(run_id: str, events: list[dict]) -> None:
    api._TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = api._TRACE_DIR / f"{run_id}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for i, event in enumerate(events):
            full = {"schema": "rlm-harness/trace/v1", "run_id": run_id, "step_id": i, "ts": 0.0, **event}
            fh.write(json.dumps(full) + "\n")


def test_translate_trace_event_carries_a_headline_a_specific_and_a_fact():
    """The `{kind, primary, detail, meta}` shape `cve-reverser`/`diff-sentry`'s feeds use. An earlier
    version emitted one fixed sentence per event type and threw the payload away — a user pointed at
    those siblings and asked why ours said so much less, and the answer was that it was discarding
    `reasoning`, `turn` and `output` on every single step."""
    step = api._translate_trace_event(
        {
            "type": "main_step",
            "step_id": 1,
            "payload": {"turn": 0, "reasoning": "Reading s1 before answering", "output": "x" * 2048},
        }
    )
    assert step["kind"] == "thinking"
    assert step["primary"] == "Step 1"  # 1-based: `turn` is 0-based and nobody reads "Step 0"
    assert step["detail"] == "Reading s1 before answering"
    assert step["meta"] == "2.0 KB read"

    tool = api._translate_trace_event({"type": "tool_call", "step_id": 1, "payload": {"tool": "read"}})
    assert (tool["kind"], tool["detail"]) == ("tool", "read")
    assert api._translate_trace_event({"type": "sub_call", "step_id": 2, "payload": {}})["kind"] == "escalation"

    # A failed run is its own kind, so the UI can end the stream AND say which way it ended.
    assert api._translate_trace_event({"type": "run_end", "step_id": 3, "payload": {"ok": True}})["kind"] == "done"
    assert api._translate_trace_event({"type": "run_end", "step_id": 4, "payload": {"ok": False}})["kind"] == "failed"

    # `summary` survives for any consumer written against the older one-line shape.
    assert step["summary"].startswith("Step 1 ")

    # The step's OUTPUT is never streamed, only its size: that is where whole corpus spans land,
    # and this stream is already a materially different exposure (invariant 29).
    assert "x" * 100 not in json.dumps(step)


def test_a_long_reasoning_is_clipped_before_it_reaches_the_stream():
    """One event per step, down an SSE connection: a REPL turn's reasoning can run to thousands of
    characters and the full text is in the trace file the citation lookup already reads."""
    event = api._translate_trace_event(
        {"type": "main_step", "step_id": 1, "payload": {"turn": 0, "reasoning": "word " * 500}}
    )
    assert len(event["detail"]) <= api._DETAIL_CHARS + 1
    assert event["detail"].endswith("\u2026")


def test_stream_run_replays_a_finished_trace_without_waiting(client, monkeypatch):
    _write_trace(
        "mynb-done",
        [
            {"type": "run_start", "payload": {}},
            {"type": "main_step", "payload": {"reasoning": "thinking"}},
            {"type": "run_end", "payload": {"ok": True}},
        ],
    )

    resp = client.get("/notebooks/mynb/runs/mynb-done/stream")

    assert resp.status_code == 200
    body = resp.text
    assert body.count("data: ") == 3
    # A terminal kind, not specifically the happy one — a crash with no `run_end` is a FAILURE, and
    # calling it "done" told a reader the run had completed normally.
    assert '"failed"' in body or '"done"' in body


def test_stream_run_reports_not_found_when_run_id_does_not_belong_to_the_notebook(client):
    """Mirrors citation_turn's same ownership check — a mismatched notebook_id must not stream a
    trace that belongs to a different notebook, found as a non-blocking gap during this phase's
    own completion check (citation_turn already had this check, stream_run didn't yet)."""
    _write_trace("othernb-run", [{"type": "run_start", "payload": {}}])

    resp = client.get("/notebooks/mynb/runs/othernb-run/stream")

    assert resp.status_code == 200  # SSE has already committed headers
    assert "not_found" in resp.text


def test_stream_run_reports_not_found_after_the_grace_period_when_no_trace_ever_appears(
    client, monkeypatch
):
    monkeypatch.setattr(api, "_TRACE_FILE_WAIT_GRACE", 0.05)
    monkeypatch.setattr(api, "_TRACE_POLL_INTERVAL", 0.01)

    resp = client.get("/notebooks/mynb/runs/mynb-nonexistent/stream")

    assert resp.status_code == 200  # SSE has already committed headers — the error is IN the stream
    assert "not_found" in resp.text


def test_stream_run_keeps_waiting_for_an_announced_run_whose_trace_does_not_exist_yet(
    client, monkeypatch, tmp_path
):
    """A user reported `no run '…-summary' found` on their first-ever overview, and it reproduced
    first try. The window is NOT the one invariant 29 closed (between the exclusive-create and the
    `_RUN_PROCESSES` registration) — it is much larger and sits BEFORE the exclusive-create happens
    at all: every run-taking handler calls `_resolve_language` first, and on a new notebook that is
    always a real model round trip, always longer than the grace period.

    `_announced` marks the id as coming; this pins that the stream then waits INDEFINITELY rather
    than reporting the run missing. Grace is set far below the delay so a regression fails fast
    rather than by timing luck.
    """
    monkeypatch.setattr(api, "_TRACE_FILE_WAIT_GRACE", 0.05)
    monkeypatch.setattr(api, "_TRACE_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(api, "_TRACE_DIR", tmp_path)

    run_id = "mynb-late"
    trace = tmp_path / f"{run_id}.jsonl"

    async def _write_the_trace_late():
        # Far longer than the grace: without the announcement this is guaranteed to have given up.
        await asyncio.sleep(0.5)
        trace.write_text(
            json.dumps({"type": "run_start", "step_id": 0, "payload": {}}) + "\n"
            + json.dumps({"type": "run_end", "step_id": 1, "payload": {}}) + "\n",
            encoding="utf-8",
        )

    async def _go():
        with api._announced(run_id):
            writer = asyncio.create_task(_write_the_trace_late())
            events = [event async for event in api._tail_trace_events(run_id)]
            await writer
        return events

    events = asyncio.run(_go())

    assert not any(e.get("kind") == "not_found" for e in events), events
    assert events[-1]["kind"] in {"done", "failed"}


def test_overview_announces_its_runs_before_the_language_call(client, monkeypatch, tmp_path):
    """The reported bug, end to end. Pinning the `_announced` MECHANISM was not enough — deleting
    the announcement from `/overview` itself left that green, which is exactly the hollow-test shape
    this project keeps catching. Here the language resolution is made slow on purpose and a ticker
    is opened alongside the request, the way the browser does it.
    """
    _live_env(monkeypatch)
    _add_a_source(client)
    monkeypatch.setattr(api, "_TRACE_FILE_WAIT_GRACE", 0.05)
    monkeypatch.setattr(api, "_TRACE_POLL_INTERVAL", 0.01)

    async def _slow_language(notebook, request, config, run_id):
        # Stands in for the real model round trip, which on a NEW notebook always happens and
        # always outlasts the grace period.
        await asyncio.sleep(0.4)
        return "English"

    monkeypatch.setattr(api, "_resolve_language", _slow_language)
    _mock_runner(monkeypatch, {"text": "an overview", "citations": []})

    token = "ticker"
    summary_run = f"mynb-{token}-summary"

    async def _go():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            async def _stream():
                async with ac.stream(
                    "GET", f"/notebooks/mynb/runs/{summary_run}/stream"
                ) as resp:
                    return "".join([chunk async for chunk in resp.aiter_text()])

            streamed, posted = await asyncio.gather(
                _stream(),
                ac.post("/notebooks/mynb/overview", json={"run_id": token}),
            )
            return streamed, posted

    streamed, posted = asyncio.run(_go())

    assert posted.status_code == 200, posted.text
    assert "not_found" not in streamed, streamed[:300]


def test_cancel_run_targets_one_run_id_not_the_whole_notebook(client, monkeypatch):
    """`/overview` fires TWO runs and invariant 23's `_ACTIVE_RUNS` holds one slot per NOTEBOOK, so
    the notebook-scoped cancel reaches only whichever registered last — the user asks to stop and
    the other run keeps burning a model call. This one kills exactly the id asked for."""
    killed: list = []
    monkeypatch.setattr(api.os, "killpg", lambda pid, sig: killed.append(pid))

    api._RUN_PROCESSES["mynb-a"] = types.SimpleNamespace(pid=4242)
    api._RUN_PROCESSES["mynb-b"] = None  # announced, not spawned yet
    try:
        assert client.post("/notebooks/mynb/runs/mynb-a/cancel").json()["cancelled"] == "mynb-a"
        assert killed == [4242]

        # Reserved-but-not-spawned is reported honestly, not as a 404 reading "already finished".
        body = client.post("/notebooks/mynb/runs/mynb-b/cancel").json()
        assert body["cancelled"] is None and "not spawned" in body["detail"]
        assert killed == [4242]

        # A run belonging to another notebook is refused, same guard `stream_run` applies.
        assert client.post("/notebooks/other/runs/mynb-a/cancel").status_code == 404
        assert client.post("/notebooks/mynb/runs/mynb-nope/cancel").status_code == 404
    finally:
        api._RUN_PROCESSES.pop("mynb-a", None)
        api._RUN_PROCESSES.pop("mynb-b", None)


def test_every_run_taking_handler_announces_before_resolving_the_language():
    """A source-tree assertion covering the four handlers the behavioural test above cannot each
    afford a slow-language integration run for. The rule is uniform on purpose: a rule with one
    silent exception is the kind that gets rediscovered as a bug report."""
    from pathlib import Path as _Path

    lines = (
        _Path(__file__).resolve().parent.parent / "rlm_notebook" / "api.py"
    ).read_text().splitlines()
    calls = [i for i, line in enumerate(lines) if "await _resolve_language(" in line]
    assert len(calls) == 5, calls  # ask, title, overview, guide, audio

    for index in calls:
        depth = len(lines[index]) - len(lines[index].lstrip())
        # Walk up to the nearest ENCLOSING block header. Indentation, not a fixed column: `/title`
        # sits one level deeper than the rest because it is also inside a `try:`.
        for j in range(index - 1, -1, -1):
            candidate = lines[j]
            if not candidate.strip() or candidate.lstrip().startswith("#"):
                continue
            if len(candidate) - len(candidate.lstrip()) < depth:
                assert "with _announced(" in candidate, (index + 1, candidate.strip())
                break
        else:
            raise AssertionError(f"no enclosing block found for line {index + 1}")


def test_announced_release_does_not_steal_a_run_that_actually_started(client):
    """`_announced` must not pop an id `_run_isolated` has taken ownership of — that entry is how
    `stream_run` tells "still writing" from "the writer exited", and `_run_isolated`'s own `finally`
    is what clears it."""
    run_id = "mynb-owned"
    sentinel = object()
    with api._announced(run_id):
        assert api._RUN_PROCESSES[run_id] is None
        api._RUN_PROCESSES[run_id] = sentinel  # stands in for the spawned process
    assert api._RUN_PROCESSES.get(run_id) is sentinel
    api._RUN_PROCESSES.pop(run_id, None)

    # And an id that never started IS released, so a failed request cannot make the stream wait
    # forever for a run that will never come.
    with api._announced(run_id):
        pass
    assert run_id not in api._RUN_PROCESSES


def test_stream_run_synthesizes_a_terminal_event_for_a_dead_process_with_no_run_end(client, monkeypatch):
    """A killpg-cancelled run's TraceRecorder never reaches __exit__, so no run_end is ever
    written — the stream must still reach a terminal state instead of hanging forever."""
    monkeypatch.setattr(api, "_TRACE_POLL_INTERVAL", 0.01)
    _write_trace("mynb-killed", [{"type": "run_start", "payload": {}}])
    # No entry in _RUN_PROCESSES at all == "no longer tracked as alive", the same state a
    # finished-and-cleaned-up (or never-tracked) run would be in.

    resp = client.get("/notebooks/mynb/runs/mynb-killed/stream")

    assert resp.status_code == 200
    # A crash with no `run_end` is a FAILURE. It used to be reported as "done", which told a reader
    # the run had completed normally.
    assert "failed" in resp.text


def test_citation_turn_finds_the_first_event_containing_the_marker(client):
    _write_trace(
        "mynb-cit",
        [
            {"type": "main_step", "payload": {"reasoning": "reading around", "output": "nothing here"}},
            {"type": "main_step", "payload": {"output": "found [[SRC:s1|whole]] right here"}},
            {"type": "main_step", "payload": {"output": "[[SRC:s1|whole]] appears again later"}},
        ],
    )

    resp = client.get("/notebooks/mynb/runs/mynb-cit/citation-turn?source_id=s1&locator=whole")

    assert resp.status_code == 200
    body = resp.json()
    assert body["step_id"] == 1  # the FIRST matching event, not the second


def test_citation_turn_finds_the_marker_in_a_sub_call_event_not_just_main_step(client):
    """Regression coverage for the exact bug audit round 1 found: a hardcoded
    reasoning/code/output field list misses a sub_call event's real payload keys
    (input/raw/processed/etc). Searching the whole serialized payload must not repeat that."""
    _write_trace(
        "mynb-sub",
        [
            {
                "type": "sub_call",
                "payload": {
                    "kind": "escalation", "name": "summarize", "model": "test/model",
                    "input": "please summarize [[SRC:s1|page:2]]", "raw": "...", "processed": "...",
                },
            }
        ],
    )

    resp = client.get("/notebooks/mynb/runs/mynb-sub/citation-turn?source_id=s1&locator=page:2")

    assert resp.status_code == 200
    assert resp.json()["type"] == "sub_call"


def test_citation_turn_404s_when_the_trace_file_does_not_exist():
    client = TestClient(api.app)
    resp = client.get("/notebooks/mynb/runs/mynb-never-ran/citation-turn?source_id=s1&locator=whole")
    assert resp.status_code == 404


def test_citation_turn_404s_when_no_event_contains_the_marker(client):
    _write_trace("mynb-nomatch", [{"type": "main_step", "payload": {"output": "nothing relevant"}}])

    resp = client.get("/notebooks/mynb/runs/mynb-nomatch/citation-turn?source_id=s1&locator=whole")

    assert resp.status_code == 404


def test_citation_turn_404s_when_run_id_does_not_belong_to_the_notebook(client):
    _write_trace("othernb-run", [{"type": "main_step", "payload": {"output": "[[SRC:s1|whole]]"}}])

    resp = client.get("/notebooks/mynb/runs/othernb-run/citation-turn?source_id=s1&locator=whole")

    assert resp.status_code == 404


# --- durable writes (slice 14) -------------------------------------------------------------------


def test_a_source_and_a_note_added_during_an_ask_both_survive_it(monkeypatch, client):
    """THE regression test for this slice's defect, reproduced live over real HTTP against a real
    uvicorn server before the fix: a user keeps working while the model runs — adds a source, saves
    a note — and `ask` then persists its turn on top. Both writes used to return 200 and both were
    silently destroyed, because `ask` wrote back a whole notebook it had read minutes earlier."""
    _live_env(monkeypatch)
    _add_a_source(client)

    gate = asyncio.Event()

    async def _fake_start_run(run_id, trace_dir, dotted_task, kwargs):
        return _FakeRun(run_id)

    async def _gated_wait_result(run, *, timeout=None):
        await gate.wait()  # stands in for a real RLM loop: seconds to minutes
        return {"text": "an answer", "citations": []}

    monkeypatch.setattr(api.runner, "start_run", _fake_start_run)
    monkeypatch.setattr(api.runner, "wait_result", _gated_wait_result)

    async def _scenario():
        asking = asyncio.create_task(
            api.ask("mynb", api.AskRequest(question="what?"), _FakeRequest())
        )
        await asyncio.sleep(0.05)  # let `ask` load the notebook and park on the run

        await api.add_sources("mynb", api.SourcesRequest(texts=["added while asking"]))
        await api.add_note_endpoint("mynb", api.NoteRequest(text="a note taken while asking"))

        gate.set()
        await asking

    asyncio.run(_scenario())

    saved = load_notebook("mynb")
    assert len(saved.sources) == 2, "the source added mid-run was destroyed"
    assert saved.sources[1].origin.startswith("pasted:added while asking")
    assert [n.id for n in saved.notes] == ["n1"], "the note added mid-run was destroyed"
    assert len(saved.turns) == 1, "the ask's own turn was lost"


def test_two_concurrent_source_adds_both_land(client):
    """Invariant 31's originally-documented case (two writers on one notebook). Weaker than the
    test above — before this slice both handlers were fully synchronous, so `gather` would have
    run them one after the other anyway — but now that each dispatches its merge to a thread they
    genuinely overlap, and it pins that the lock plus the re-read keeps both."""

    async def _scenario():
        await asyncio.gather(
            api.add_sources("nb2", api.SourcesRequest(texts=["first"])),
            api.add_sources("nb2", api.SourcesRequest(texts=["second"])),
        )

    asyncio.run(_scenario())

    saved = load_notebook("nb2")
    assert len(saved.sources) == 2
    assert sorted(s.id for s in saved.sources) == ["s1", "s2"]


def test_delete_note_404s_on_a_note_a_concurrent_request_already_removed(client):
    """`delete_note`'s `ValueError` must still reach the client as a 404 now that it is raised
    inside `mutate_notebook`'s worker thread — and must NOT be mistaken for `notebook_path`'s
    same-typed invalid-id `ValueError`, which would report a 400 naming the wrong thing."""
    client.post("/notebooks/mynb/notes", json={"text": "a note"})

    assert client.delete("/notebooks/mynb/notes/n1").status_code == 200
    resp = client.delete("/notebooks/mynb/notes/n1")

    assert resp.status_code == 404
    assert "n1" in resp.json()["detail"]


def _stale_trace(run_id: str, *, age_days: float):
    """Writes a REAL trace line (with `rlm_harness.trace`'s schema marker) — `traces._is_ours`
    refuses to delete anything it can't recognise as this project's own, so a fixture writing a
    bare `{"type": ...}` would be silently un-prunable and make these tests vacuous."""
    api._TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = api._TRACE_DIR / f"{run_id}.jsonl"
    _write_trace(run_id, [{"type": "run_end", "payload": {"ok": True}}])
    when = time.time() - age_days * 86_400
    os.utime(path, (when, when))
    return path


def test_a_finished_run_prunes_old_trace_files(monkeypatch, client):
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"text": "an answer", "citations": []})
    stale = _stale_trace("mynb-ancient", age_days=30)

    assert client.post("/notebooks/mynb/ask", json={"question": "what?"}).status_code == 200

    assert not stale.exists()


def test_a_finished_run_leaves_its_own_fresh_trace_alone(monkeypatch, client):
    """The just-finished run's trace is exactly what the answer now on screen links to through
    `citation-turn` — `prune_traces`'s young-file floor must keep it, even though its process is
    already gone from the protected set by the time the sweep runs."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"text": "an answer", "citations": []})
    monkeypatch.setenv("RN_TRACE_RETENTION_DAYS", "1")
    monkeypatch.setenv("RN_MAX_TRACE_FILES", "1")

    resp = client.post("/notebooks/mynb/ask", json={"question": "what?", "run_id": "keepme"})

    assert resp.status_code == 200
    assert (api._TRACE_DIR / "mynb-keepme.jsonl").exists()


def test_the_startup_lifespan_prunes_old_traces():
    stale = _stale_trace("mynb-ancient", age_days=30)

    with TestClient(api.app):
        pass

    assert not stale.exists()


def test_a_malformed_retention_setting_refuses_startup(monkeypatch):
    """The other half of the split: `_prune_traces` swallows everything so a completed run can't be
    turned into a 500, which would also make a typo'd retention value mean "silently never prune."
    The lifespan reads the settings itself so that case refuses startup instead.

    Drives `_lifespan` directly rather than through `TestClient`: anyio's portal re-raises a
    startup failure wrapped in a `BaseExceptionGroup`, so asserting on it there would pin
    TestClient's wrapping rather than this project's behavior. The end-to-end effect was verified
    against a REAL uvicorn server instead — it logs "Application startup failed. Exiting." and the
    process exits nonzero."""
    monkeypatch.setenv("RN_MAX_TRACE_FILES", "not-a-number")

    async def _enter_lifespan():
        async with api._lifespan(api.app):
            pass

    with pytest.raises(SystemExit, match="RN_MAX_TRACE_FILES"):
        asyncio.run(_enter_lifespan())


def test_a_broken_retention_setting_does_not_take_down_a_run(monkeypatch, client):
    """`config.py` raises `SystemExit` on a malformed `RN_*` value. That is right for a CLI and for
    `_config()`, and wrong for housekeeping in a `finally` — a completed, paid-for `ask` must not
    become a 500 because a retention knob was typo'd."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"text": "an answer", "citations": []})
    monkeypatch.setenv("RN_MAX_TRACE_FILES", "not-a-number")

    assert client.post("/notebooks/mynb/ask", json={"question": "what?"}).status_code == 200


def test_prune_never_deletes_the_trace_of_a_run_still_in_flight(monkeypatch):
    """`_prune_traces` must pass the REAL `_RUN_PROCESSES` keys, not an empty set. Deleting a live
    run's trace would break its SSE stream and free a run id `_run_isolated`'s exclusive-create
    gate is still relying on being taken, letting a second request append into the same file. An
    independent test-quality review found this wiring had no coverage: replacing the protected set
    with `set()` left the whole suite green."""
    live = _stale_trace("mynb-stillrunning", age_days=30)
    dead = _stale_trace("mynb-finished", age_days=30)
    monkeypatch.setitem(api._RUN_PROCESSES, "mynb-stillrunning", _FakeProcess())
    try:
        asyncio.run(api._prune_traces())
    finally:
        api._RUN_PROCESSES.pop("mynb-stillrunning", None)

    assert live.exists(), "an in-flight run's trace was deleted"
    assert not dead.exists()


def test_the_stream_does_not_declare_a_reserved_run_dead(monkeypatch):
    """`_run_isolated` creates the trace file BEFORE spawning, so there is a window — the whole
    `await runner.start_run(...)`, a real subprocess spawn — where the file exists and no process is
    tracked yet. `stream_run` read exactly that pair as "the writer has exited" and immediately
    emitted `run ended without a final event`, for a run that was about to start perfectly well.

    Reported by a user clicking "Generate overview" and reproduced 3/3 against a live server the
    moment two guide runs were fired concurrently on one notebook (which interleaves the event loop
    and widens the window). The reservation placeholder (`_RUN_PROCESSES[run_id] = None`) is what
    distinguishes "starting" from "gone"; this pins that an ABSENT key still means gone."""
    monkeypatch.setattr(api, "_TRACE_POLL_INTERVAL", 0.01)
    run_id = "mynb-reserved"
    _write_trace(run_id, [])  # the exclusively-created, still-empty trace file

    async def _drain(limit):
        out = []
        async for event in api._tail_trace_events(run_id):
            out.append(event)
            if len(out) >= limit:
                break
        return out

    async def _scenario():
        api._RUN_PROCESSES[run_id] = None  # reserved, spawn in flight
        task = asyncio.create_task(_drain(1))
        await asyncio.sleep(0.1)  # several poll intervals
        still_waiting = not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        del api._RUN_PROCESSES[run_id]  # the run is genuinely over now
        return still_waiting, await _drain(1)

    still_waiting, events = asyncio.run(_scenario())

    assert still_waiting, "the stream declared a reserved-but-not-yet-spawned run dead"
    assert events[0]["summary"] == "run ended without a final event"


# --- persistent overview --------------------------------------------------------------------


def _overview_notebook(client, monkeypatch, result=None):
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, result if result is not None else {"text": "an overview", "citations": []})


def test_the_overview_persists_and_is_returned_on_read(client, monkeypatch):
    """The defect this fixed: the overview lived only as a front-end flag, so EVERY notebook opened
    showing the first-run button — even one mid-conversation (reported with a screenshot)."""
    _overview_notebook(client, monkeypatch)

    resp = client.post("/notebooks/mynb/overview", json={"run_id": "tok"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["overview"]["text"] == "an overview"

    reopened = client.get("/notebooks/mynb").json()["overview"]
    assert reopened is not None
    assert reopened["stale"] is False


def test_adding_a_source_marks_the_overview_stale_rather_than_deleting_it(client, monkeypatch):
    """Confiscating an overview the user just paid an RLM run for, because they added a source, is
    worse than showing it with a marker — it is still true about the sources it was computed from.
    Before this, "never generated" and "generated but the sources changed" rendered identically."""
    _overview_notebook(client, monkeypatch)
    client.post("/notebooks/mynb/overview", json={"run_id": "tok"})

    client.post("/notebooks/mynb/sources", json={"texts": ["a second source"]})

    overview = client.get("/notebooks/mynb").json()["overview"]
    assert overview is not None, "the overview was deleted instead of marked stale"
    assert overview["stale"] is True


def test_the_overview_run_id_is_suffixed_after_derivation(client, monkeypatch):
    """Both halves of a blocker the pre-implementation audit found. Forming `<token>-summary` and
    THEN slugging breaks twice: an absent `run_id` yields the literal deterministic `None-summary`
    (so the first anonymous request wins the exclusive-create gate and every later one 409s until
    retention collects the trace), and `slug`'s 120-char cap merges the two suffixes for a long
    client-chosen token, 409ing one run as a confusing half-failure."""
    _overview_notebook(client, monkeypatch)

    first = client.post("/notebooks/mynb/overview", json={})
    second = client.post("/notebooks/mynb/overview", json={})
    assert first.status_code == 200 and second.status_code == 200, "an anonymous retry 409'd"
    assert "None" not in (first.json()["overview"]["run_id"] or "")

    long_token = "a" * 200
    resp = client.post("/notebooks/mynb/overview", json={"run_id": long_token})
    assert resp.status_code == 200, resp.text
    assert resp.json()["overview"]["run_id"].endswith("-summary")


def test_an_overview_is_refused_for_a_notebook_with_no_sources(client, monkeypatch):
    _live_env(monkeypatch)
    client.post("/notebooks/empty/notes", json={"text": "just a note"})
    assert client.post("/notebooks/empty/overview", json={}).status_code == 422


def test_the_persisted_overviews_citations_are_reverified_on_read(client, monkeypatch):
    """Same discipline every ChatTurn already gets: a stored citation is a claim about a corpus that
    may have changed since, so it is re-verified against the CURRENT one rather than trusted."""
    _overview_notebook(
        client,
        monkeypatch,
        {"text": "x", "citations": [{"source_id": "s99", "locator": "whole", "quote": "q"}]},
    )

    client.post("/notebooks/mynb/overview", json={"run_id": "tok"})

    citation = client.get("/notebooks/mynb").json()["overview"]["citations"][0]
    assert citation["verified"] is False
    assert "s99" in citation["reason"]


# --- output language ------------------------------------------------------------------------


def _mock_runner_by_run(monkeypatch, dotted, *, lang, other):
    """Like `_mock_runner`, but answers the LANGUAGE run differently from the artifact run — they
    return different shapes, so one canned result cannot serve both."""

    async def _start(run_id, trace_dir, dotted_task, kwargs):
        dotted.append(dotted_task)
        return _FakeRun(run_id)

    async def _wait(run, *, timeout=None):
        return lang if "-lang" in run.run_id else other

    monkeypatch.setattr(api.runner, "start_run", _start)
    monkeypatch.setattr(api.runner, "wait_result", _wait)


def test_every_grounded_task_declares_output_language():
    """A tripwire, not tidiness. A MISSING required signature input surfaces as the opaque
    `RLMTaskError: Failed to produce a valid 'answer'` (a 502) — indistinguishable from any other
    run failure — and an UNDECLARED extra kwarg is silently accepted and injected as a REPL variable
    anyway, so a partial rollout fails silently in BOTH directions. Verified empirically by this
    slice's pre-implementation audit against the installed rlm-harness.

    `GeneratePodcastScript` was deliberately ABSENT for one slice — the podcast was excluded from
    the forced language because `tts.py` mapped no language to a voice, so a Chinese script would
    have been read by the en-US default cast (invariant 15's "works out of the box"). It is included
    now that `tts.default_voices_for` closes that. The exclusion being pinned is what made changing
    it a deliberate act: this assertion failed the moment the field was added, rather than the
    scope cut silently eroding."""
    from rlm_notebook.audio import GeneratePodcastScript
    from rlm_notebook.task import AnswerQuestion

    grounded = (AnswerQuestion, GeneratePodcastScript, *(t for t, _ in api._GUIDE_TASKS.values()))
    for task_cls in grounded:
        assert "output_language: str" in task_cls.signature, task_cls.__name__


def test_a_forced_language_skips_the_resolution_run_entirely(client, monkeypatch):
    """`RN_OUTPUT_LANGUAGE` is a hard override, so there is nothing to resolve — and it applies to
    CHAT as well as artifacts (NotebookLM's equivalent setting does; scoping it to artifacts would
    leave an operator who set it wondering why answers stayed in the sources' language)."""
    _live_env(monkeypatch)
    monkeypatch.setenv("RN_OUTPUT_LANGUAGE", "Traditional Chinese")
    _add_a_source(client)
    dotted: list[str] = []
    _mock_runner(monkeypatch, {"text": "an answer", "citations": []}, dotted_tasks=dotted)

    assert client.post("/notebooks/mynb/ask", json={"question": "q"}).status_code == 200

    assert dotted == ["rlm_notebook.task:AnswerQuestion"], "a resolution run fired despite the override"
    assert load_notebook("mynb").output_language is None, "the override must not be persisted"


def test_the_language_is_resolved_once_and_persisted(client, monkeypatch):
    _live_env(monkeypatch)
    monkeypatch.delenv("RN_OUTPUT_LANGUAGE", raising=False)
    _add_a_source(client)
    dotted: list[str] = []
    _mock_runner_by_run(monkeypatch, dotted, lang="Japanese", other={"text": "x", "citations": []})

    client.post("/notebooks/mynb/guide/summary")
    assert dotted[0] == "rlm_notebook.naming:SuggestLanguage", dotted
    assert load_notebook("mynb").output_language == "Japanese"

    dotted.clear()
    client.post("/notebooks/mynb/guide/faq")
    assert "rlm_notebook.naming:SuggestLanguage" not in dotted, "resolved a second time"


def test_the_overview_resolves_the_language_once_not_once_per_run(client, monkeypatch):
    """`/overview` gathers two runs. Calling `_resolve_language` inside each branch would fire two
    concurrent resolutions deriving the SAME `-lang` run id — one 409s on the exclusive-create gate
    and both race to persist. Caught by the pre-implementation audit; pinned here."""
    _live_env(monkeypatch)
    monkeypatch.delenv("RN_OUTPUT_LANGUAGE", raising=False)
    _add_a_source(client)
    dotted: list[str] = []
    _mock_runner_by_run(
        monkeypatch, dotted, lang="Japanese", other={"text": "x", "citations": [], "items": []}
    )

    resp = client.post("/notebooks/mynb/overview", json={"run_id": "tok"})

    assert resp.status_code == 200, resp.text
    assert dotted.count("rlm_notebook.naming:SuggestLanguage") == 1, dotted


def test_a_failed_resolution_never_costs_the_caller_their_artifact(client, monkeypatch):
    """A language guess is a convenience. `_resolve_language` returns None on failure and the caller
    substitutes its literal default."""
    _live_env(monkeypatch)
    monkeypatch.delenv("RN_OUTPUT_LANGUAGE", raising=False)
    _add_a_source(client)

    async def _fail_language(run, *, timeout=None):
        raise api.runner.RunError("simulated resolution failure")

    real_wait = api.runner.wait_result

    async def _dispatch(run, *, timeout=None):
        if "-lang" in run.run_id:
            return await _fail_language(run, timeout=timeout)
        return {"text": "an answer", "citations": []}

    async def _start(run_id, trace_dir, dotted_task, kwargs):
        return _FakeRun(run_id)

    monkeypatch.setattr(api.runner, "start_run", _start)
    monkeypatch.setattr(api.runner, "wait_result", _dispatch)
    try:
        resp = client.post("/notebooks/mynb/ask", json={"question": "q"})
    finally:
        monkeypatch.setattr(api.runner, "wait_result", real_wait)

    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "an answer"


# --- settings -----------------------------------------------------------------------------------


def test_settings_never_calls_config_and_works_without_a_model(client, monkeypatch):
    """`NotebookConfig.from_env()` raises SystemExit (a 500) whenever RN_MAIN_MODEL is unset — and a
    settings page is exactly what an operator opens when the server is misconfigured. The same
    reasoning invariant 30 already applies to `max_upload_bytes`."""
    monkeypatch.delenv("RN_MAIN_MODEL", raising=False)
    monkeypatch.delenv("RN_OUTPUT_LANGUAGE", raising=False)

    resp = client.get("/settings")

    assert resp.status_code == 200, resp.text
    assert resp.json()["output_language"]["source"] == "default"


def test_settings_refuses_an_unknown_key_and_a_crafted_voice(client, monkeypatch):
    monkeypatch.delenv("RN_MAIN_MODEL", raising=False)

    assert client.put("/settings", json={"output_language": "Traditional Chinese"}).status_code == 200
    # An unknown key is REFUSED, not dropped. Pydantic's default drops it before the handler's
    # validator sees it — and combined with full-replacement semantics that made a request carrying
    # only a typo'd key silently WIPE every setting, which a live check caught after this very test
    # (asserting only that nothing extra is persisted) had passed while missing it.
    resp = client.put("/settings", json={"RN_API_KEY": "sk-x", "output_language": "Japanese"})
    assert resp.status_code == 422, resp.text
    assert client.get("/settings").json()["output_language"]["value"] == "Traditional Chinese", (
        "a rejected write must leave the previous settings intact"
    )

    resp = client.put(
        "/settings",
        json={"tts_voice_host_a": "en-US-x'/><audio src=" + chr(34) + "http://e/x" + chr(34) + "/><a b='Neural"},
    )
    assert resp.status_code == 422, resp.text


def test_no_safety_bound_or_credential_is_readable_or_writable(client, monkeypatch):
    """"Non-secret" was the wrong filter. Trace retention DELETES files that can hold ingested
    source text, the upload cap bounds what an unauthenticated caller can push, and a writable
    RN_BASE_URL would exfiltrate RN_API_KEY on the next run without anyone reading it."""
    monkeypatch.delenv("RN_MAIN_MODEL", raising=False)

    exposed = set(client.get("/settings").json())
    assert exposed == {"error", "output_language", "tts_voice_host_a", "tts_voice_host_b"}

    client.put("/settings", json={"output_language": "Japanese"})
    for forbidden in ("max_upload_bytes", "trace_retention_days", "main_model", "api_key", "base_url"):
        assert client.put("/settings", json={forbidden: "1"}).status_code == 422, forbidden
        assert forbidden not in client.get("/settings").json()
    # and none of those refused writes wiped what was already there
    assert client.get("/settings").json()["output_language"]["value"] == "Japanese"


def test_the_settings_language_beats_a_notebooks_cached_resolution(client, monkeypatch):
    """The ladder is env -> settings file -> Notebook.output_language -> default. The first two are
    STATED preferences; the third is a CACHED GUESS that exists only so a resolution isn't paid for
    per artifact. Below the cache, a language chosen in the settings page would be inert for every
    notebook that has ever generated anything — the notebooks a user is looking at when they open
    settings."""
    _live_env(monkeypatch)
    monkeypatch.delenv("RN_OUTPUT_LANGUAGE", raising=False)
    _add_a_source(client)
    dotted: list[str] = []
    _mock_runner_by_run(monkeypatch, dotted, lang="Japanese", other={"text": "x", "citations": []})
    client.post("/notebooks/mynb/guide/summary")
    assert load_notebook("mynb").output_language == "Japanese"

    client.put("/settings", json={"output_language": "Traditional Chinese"})

    from rlm_notebook.config import output_language

    assert output_language() == "Traditional Chinese"


def test_the_podcast_persists_and_is_served_as_a_file(client, monkeypatch, tmp_path):
    """Phase 2 deliberately kept no audio past one request. That cost the user their episode on
    every reload — reported after they asked where the mp3 was — so it is persisted now: one file
    per notebook, replaced on regenerate, served as a real file the browser can range-request."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"utterances": [{"speaker": "host_a", "text": "hi", "citations": []}]})

    class _FakeProvider:
        suffix = ".mp3"
        media_type = "audio/mpeg"

        def default_voices(self, language):
            return None

        def fallback_voices(self):
            return ("fake-voice-a", "fake-voice-b")

        def validate(self, language=None, voice_map=None):
            return None

        def synthesize(self, script, voice_map, out_path, language=None):
            out_path.write_bytes(b"ID3fake-mp3-bytes")

    monkeypatch.setattr(api, "get_tts_provider", lambda name: _FakeProvider())

    resp = client.post("/notebooks/mynb/audio", json={"run_id": "pod"})
    assert resp.status_code == 200, resp.text

    # the transcript comes back on a plain notebook read...
    podcast = client.get("/notebooks/mynb").json()["podcast"]
    assert podcast is not None
    assert podcast["utterances"][0]["text"] == "hi"
    assert podcast["stale"] is False

    # ...and the audio is a separate file endpoint, so a multi-MB blob never rides along on it
    assert "audio_base64" not in str(podcast)
    audio = client.get("/notebooks/mynb/audio/file")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/mpeg"
    assert audio.content == b"ID3fake-mp3-bytes"


def test_adding_a_source_marks_the_podcast_stale(client, monkeypatch):
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"utterances": [{"speaker": "host_a", "text": "hi", "citations": []}]})

    class _FakeProvider:
        suffix = ".mp3"
        media_type = "audio/mpeg"

        def default_voices(self, language):
            return None

        def fallback_voices(self):
            return ("fake-voice-a", "fake-voice-b")

        def validate(self, language=None, voice_map=None):
            return None

        def synthesize(self, script, voice_map, out_path, language=None):
            out_path.write_bytes(b"x")

    monkeypatch.setattr(api, "get_tts_provider", lambda name: _FakeProvider())
    client.post("/notebooks/mynb/audio", json={"run_id": "pod"})

    client.post("/notebooks/mynb/sources", json={"texts": ["a second source"]})

    assert client.get("/notebooks/mynb").json()["podcast"]["stale"] is True


def test_the_audio_file_endpoint_404s_and_400s_cleanly(client):
    assert client.get("/notebooks/never-generated/audio/file").status_code == 404
    assert client.get("/notebooks/%20%20/audio/file").status_code == 400


# --- the two in-memory run registries -----------------------------------------------------------


def test_run_id_is_reserved_in_run_processes_before_the_subprocess_is_spawned(client, monkeypatch):
    """The user-reported "run ended without a final event" bug: `_run_isolated` used to register in
    `_RUN_PROCESSES` only AFTER `runner.start_run` returned, leaving the whole spawn `await` as a
    window in which the trace file existed and nothing was tracked — which `stream_run` reads as
    "the writer has exited". An independent audit mutation-proved nothing pinned the fix: deleting
    both writes left the suite green, because the only existing assertion checks the key is absent
    AFTERWARDS, which an unregistered run also satisfies."""
    _live_env(monkeypatch)
    _add_a_source(client)
    seen: list = []

    async def _start(run_id, trace_dir, dotted_task, kwargs):
        # By the time a spawn is even attempted, the id must already be claimed with the "starting"
        # placeholder — that is what stops the ticker concluding the run is over.
        seen.append((run_id in api._RUN_PROCESSES, api._RUN_PROCESSES.get(run_id)))
        return _FakeRun(run_id)

    async def _wait(run, *, timeout=None):
        return {"text": "a", "citations": []}

    monkeypatch.setattr(api.runner, "start_run", _start)
    monkeypatch.setattr(api.runner, "wait_result", _wait)

    assert client.post("/notebooks/mynb/ask", json={"question": "q"}).status_code == 200
    assert seen == [(True, None)]


def test_a_finishing_run_never_clears_a_LATER_runs_active_entry(client, monkeypatch):
    """Invariant 23 claims this was "confirmed with an interleaved-`asyncio` test"; an independent
    audit found no such test, and the first attempt at one here did not catch the bug either —
    asserting both entries are gone afterwards is satisfied by a plain `pop` too.

    The property that actually distinguishes them: two runs share one notebook slot (the documented
    capacity limit), so the SECOND overwrites the FIRST. When the FIRST then finishes while the
    second is still in flight, its `finally` must leave the slot alone — `_ACTIVE_RUNS.get(id) is
    run` is false for it. A plain `pop` deletes the second run's entry instead, and `/cancel` for a
    run that is still going silently reaches nothing.
    """
    _live_env(monkeypatch)
    _add_a_source(client)

    second_registered = asyncio.Event()
    runs: dict = {}
    observed: list = []

    async def _start(run_id, trace_dir, dotted_task, kwargs):
        run = _FakeRun(run_id)
        runs[run_id] = run
        return run

    async def _wait(run, *, timeout=None):
        if run.run_id.endswith("-first"):
            await second_registered.wait()  # let the second run take the slot first
        else:
            second_registered.set()
            # Yield until the first run has finished AND run its `finally`.
            for _ in range(20):
                await asyncio.sleep(0)
            observed.append(api._ACTIVE_RUNS.get("mynb"))
        return {"text": "a", "citations": []}

    monkeypatch.setattr(api.runner, "start_run", _start)
    monkeypatch.setattr(api.runner, "wait_result", _wait)

    async def _go():
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
            return await asyncio.gather(
                ac.post("/notebooks/mynb/ask", json={"question": "q", "run_id": "first"}),
                ac.post("/notebooks/mynb/ask", json={"question": "q", "run_id": "second"}),
            )

    responses = asyncio.run(_go())

    assert [r.status_code for r in responses] == [200, 200]
    # The still-running second run's entry survived the first run's cleanup.
    assert observed and observed[0] is runs["mynb-second"], observed
    # And both are cleaned up once they have each finished.
    assert "mynb" not in api._ACTIVE_RUNS
    assert not [k for k in api._RUN_PROCESSES if k.startswith("mynb-")]


# --- Removing a source, renaming a notebook, and what the picker shows ---------------------------


def test_deleting_a_source_never_renumbers_the_survivors(client):
    """CLAUDE.md invariant 12: an existing source's id is never reassigned. This is the property
    that makes removal safe to offer at all — a citation in a saved turn either still resolves to
    the text it was written against, or fails verification loudly."""
    for url in ("https://example.com/a", "https://example.com/b", "https://example.com/c"):
        client.post("/notebooks/mynb/sources", json={"sources": [url]})
    assert [s["id"] for s in client.get("/notebooks/mynb").json()["sources"]] == ["s1", "s2", "s3"]

    resp = client.delete("/notebooks/mynb/sources/s2")
    assert resp.status_code == 200
    assert [s["id"] for s in resp.json()["sources"]] == ["s1", "s3"]

    # And the NEXT source must not land on `s3` — the collision `next_source_id` exists to prevent.
    client.post("/notebooks/mynb/sources", json={"sources": ["https://example.com/d"]})
    ids = [s["id"] for s in client.get("/notebooks/mynb").json()["sources"]]
    assert ids == ["s1", "s3", "s4"]
    assert len(ids) == len(set(ids))


def test_deleting_a_source_leaves_its_citations_unverified_rather_than_repointed(client):
    """The honest outcome, and the reason nothing needs renumbering: `citations.py` re-verifies
    every stored citation against the CURRENT corpus on every read (invariants 5 and 11)."""
    for url in ("https://example.com/a", "https://example.com/b"):
        client.post("/notebooks/mynb/sources", json={"sources": [url]})
    from rlm_notebook.notebook import mutate_notebook
    from rlm_notebook.schema import Answer, ChatTurn, Citation

    mutate_notebook(
        "mynb",
        lambda nb: nb.turns.append(
            ChatTurn(
                question="q",
                answer=Answer(
                    text="An answer.",
                    citations=[
                        Citation(
                            source_id="s2",
                            locator="whole",
                            quote="content of https://example.com/b",
                        )
                    ],
                ),
            )
        ),
    )

    assert client.get("/notebooks/mynb").json()["turns"][0]["citations"][0]["verified"] is True
    client.delete("/notebooks/mynb/sources/s2")
    citation = client.get("/notebooks/mynb").json()["turns"][0]["citations"][0]
    assert citation["verified"] is False
    assert citation["source_id"] == "s2"  # still says where it pointed, not repointed at s1
    assert citation["reason"]


def test_deleting_a_source_404s_for_an_unknown_id(client):
    client.post("/notebooks/mynb/sources", json={"sources": ["https://example.com/a"]})
    assert client.delete("/notebooks/mynb/sources/s99").status_code == 404
    assert client.delete("/notebooks/nope/sources/s1").status_code == 404


def test_renaming_normalises_the_same_way_a_generated_title_does(client):
    client.post("/notebooks/mynb/sources", json={"sources": ["https://example.com/a"]})
    resp = client.put("/notebooks/mynb/title", json={"title": '  "Voyager   notes."  '})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Voyager notes"
    assert load_notebook("mynb").title == "Voyager notes"


def test_renaming_refuses_an_empty_title_instead_of_deriving_one(client):
    """The one way rename differs from generation: substituting a derived label for what someone
    typed would be the UI lying about what it did."""
    client.post("/notebooks/mynb/sources", json={"sources": ["https://example.com/a"]})
    assert client.put("/notebooks/mynb/title", json={"title": "   "}).status_code == 422
    assert client.put("/notebooks/mynb/title", json={"title": "x" * 500}).status_code == 422
    assert load_notebook("mynb").title is None


def test_renaming_rejects_an_unknown_field_rather_than_dropping_it(client):
    """`extra="forbid"`, for the reason invariant 41 records: pydantic's default DROPS unknown keys,
    so a typo'd field would arrive as a rename to nothing."""
    client.post("/notebooks/mynb/sources", json={"sources": ["https://example.com/a"]})
    assert client.put("/notebooks/mynb/title", json={"titel": "oops"}).status_code == 422
    assert client.put("/notebooks/nope/title", json={"title": "x"}).status_code == 404


def test_the_picker_falls_back_to_the_same_derived_label_in_both_places(client):
    """The header reads `NotebookResponse.derived_title` and the picker row reads
    `NotebookSummary.derived_title`. They used to disagree — one said "Untitled notebook" while the
    other showed a derived label for the same notebook, which reads as two different notebooks."""
    client.post("/notebooks/mynb/sources", json={"sources": ["https://example.com/voyager"]})
    from_get = client.get("/notebooks/mynb").json()
    from_list = next(n for n in client.get("/notebooks").json()["notebooks"] if n["id"] == "mynb")

    assert from_get["title"] is None and from_list["title"] is None
    assert from_get["derived_title"] == from_list["derived_title"] != ""


def test_the_picker_lists_the_most_recently_touched_notebook_first(client):
    """Model-authored titles are NOT unique — a user hit three notebooks with near-identical
    generated names — so "which did I touch last" has to be answerable."""
    for name in ("first", "second", "third"):
        client.post(f"/notebooks/{name}/sources", json={"sources": [f"https://example.com/{name}"]})
        time.sleep(0.01)  # mtime resolution
    assert [n["id"] for n in client.get("/notebooks").json()["notebooks"]] == [
        "third",
        "second",
        "first",
    ]

    client.post("/notebooks/first/notes", json={"text": "touched"})
    listed = client.get("/notebooks").json()["notebooks"]
    assert listed[0]["id"] == "first"
    assert listed[0]["updated_at"] > listed[-1]["updated_at"]


def test_settings_choices_works_on_a_server_with_no_model_configured(client, monkeypatch):
    """Invariant 41's reason, one endpoint further: a settings page is what an operator opens WHEN
    the server is misconfigured, so nothing on it may go through `_config()`."""
    monkeypatch.delenv("RN_MAIN_MODEL", raising=False)
    monkeypatch.delenv("RN_TTS_PROVIDER", raising=False)

    resp = client.get("/settings/choices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "edge-tts"
    assert "English" in body["output_languages"]
    # Menu entries only — the map's BCP-47 aliases (`en`, `zh-tw`) exist for matching a hand-set
    # env var, and a dropdown offering both "English" and "En" reads as a bug.
    assert not any(len(name) <= 3 or "-" in name for name in body["output_languages"])
    assert all(voice.endswith("Neural") for voice in body["voices"])


def test_settings_choices_offers_the_configured_providers_own_voice_names(client, monkeypatch):
    """A voice NAME is provider-specific (invariant 43), so offering edge-tts ids to a chatterbox
    deployment would name voices that fail at synthesis — after a real model call was spent."""
    monkeypatch.setenv("RN_TTS_PROVIDER", "chatterbox")
    body = client.get("/settings/choices").json()
    assert body["provider"] == "chatterbox"
    assert not any(voice.endswith("Neural") for voice in body["voices"])

    # Chatterbox speaks a DIFFERENT set, not a subset: it has no id for Thai or Vietnamese, and does
    # speak eleven the voice map has no entry for. Reading the menu off the voice map offered the
    # first group and hid the second — and picking one persists a GLOBAL `output_language` that then
    # makes every /audio request fail at `validate`.
    monkeypatch.setenv("RN_TTS_PROVIDER", "edge-tts")
    edge_languages = set(client.get("/settings/choices").json()["output_languages"])
    assert "Thai" in edge_languages and "Danish" not in edge_languages
    assert "Thai" not in set(body["output_languages"])
    assert "Danish" in set(body["output_languages"])

    monkeypatch.setenv("RN_TTS_PROVIDER", "not-a-real-provider")
    unknown = client.get("/settings/choices").json()
    assert unknown["voices"] == []  # renders, rather than raising
    # The language row still works: `output_language` drives chat and every guide artifact, so a
    # server whose podcast cannot run at all must still be able to set the language of its prose.
    assert unknown["output_languages"] == sorted(edge_languages)


# --- `answer_span`: the wiring, not just the function ------------------------------------------


def test_an_answer_span_survives_the_ask_endpoint_and_a_bogus_one_does_not(client, monkeypatch):
    """`citations.locate_answer_spans` is well covered on its own; the WIRING was not. An
    independent review removed the `prose` argument from all eight `_citation_responses` call sites
    — completely disabling the highlighter strokes — and the whole suite stayed green, which is
    exactly the drift this project uses tripwires for (invariants 28, 39)."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(
        monkeypatch,
        {
            "text": "Voyager left the heliosphere in 2012. It still transmits.",
            "citations": [
                {
                    "source_id": "s1",
                    "locator": "whole",
                    "quote": "content of https://example.com/a",
                    "answer_span": "Voyager left the heliosphere in 2012.",
                },
                {
                    "source_id": "s1",
                    "locator": "whole",
                    "quote": "content of https://example.com/a",
                    "answer_span": "a sentence the model never actually wrote",
                },
            ],
        },
    )

    citations = client.post("/notebooks/mynb/ask", json={"question": "q"}).json()["citations"]
    assert citations[0]["answer_span"] == "Voyager left the heliosphere in 2012."
    assert citations[1]["answer_span"] is None  # dropped, but the citation itself survives
    assert citations[1]["verified"] is True

    # And it survives the round trip, checked against the SAME text on read.
    reread = client.get("/notebooks/mynb").json()["turns"][0]["citations"]
    assert reread[0]["answer_span"] == "Voyager left the heliosphere in 2012."
    assert reread[1]["answer_span"] is None


def test_every_citation_response_is_checked_against_its_own_artifacts_text():
    """A source-tree assertion, because passing the WRONG text is invisible at runtime: the spans
    simply stop being found and the page renders with no strokes. `prose` is a required parameter
    now (an omitted one used to skip validation and return the model's RAW span — a fail-OPEN
    default under a docstring promising the opposite), so a MISSING argument is a TypeError; this
    covers the other half, that each call site passes something artifact-specific rather than a
    parent object's text."""
    import inspect
    import re as _re

    source = inspect.getsource(api)
    # The DEFINITION is excluded by its type annotations, not by looking for "def" — that word sits
    # before the paren the regex captures, so the obvious filter never matched it. The older sibling
    # of this test has the same hole and passes only because a def line happens to satisfy its
    # assertion; both are fixed here.
    calls = _re.findall(r"_citation_responses\(([^)]*)\)", source)
    calls = [c for c in calls if ": " not in c]
    assert len(calls) >= 8, f"call sites went missing, so this would pass vacuously: {calls}"

    for call in calls:
        args = [a.strip() for a in call.split(",")]
        assert len(args) == 3, f"_citation_responses({call}) does not pass the prose it checks against"
        assert args[2] not in ("", '""', "None"), call


def test_follow_up_questions_come_back_with_the_answer_and_survive_a_reload(client, monkeypatch):
    """`Answer.follow_ups` rides the SAME run that wrote the answer — no second model call — so the
    only thing that can break is the wiring: a field declared on the schema and never returned looks
    exactly like a model that offered none."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(
        monkeypatch,
        {
            "text": "Voyager 1 crossed in 2012.",
            "citations": [],
            "follow_ups": ["What powers it?", "Where is Voyager 2?"],
        },
    )

    asked = client.post("/notebooks/mynb/ask", json={"question": "q"}).json()
    assert asked["follow_ups"] == ["What powers it?", "Where is Voyager 2?"]

    turn = client.get("/notebooks/mynb").json()["turns"][0]
    assert turn["follow_ups"] == ["What powers it?", "Where is Voyager 2?"]


def test_a_turn_saved_before_follow_ups_existed_still_loads(client, monkeypatch):
    """Same backward-compatible precedent `ChatTurn.run_id`, `Notebook.notes` and
    `Citation.answer_span` set: an older notebook file has no such key at all."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(monkeypatch, {"text": "an answer", "citations": []})
    client.post("/notebooks/mynb/ask", json={"question": "q"})

    path = notebook_path("mynb")
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["turns"][0]["answer"]["follow_ups"]
    path.write_text(json.dumps(raw), encoding="utf-8")

    turn = client.get("/notebooks/mynb").json()["turns"][0]
    assert turn["follow_ups"] == []


def test_follow_ups_are_not_citation_verified():
    """A question is a prompt, not a claim, so invariant 5 has nothing to check — and nothing in the
    schema should suggest otherwise. Pinned because "citations everywhere" is the house style here,
    and adding them to this field would imply a guarantee that cannot exist."""
    from rlm_notebook.schema import Answer

    assert Answer.model_fields["follow_ups"].annotation == list[str]
    assert Answer(text="x").follow_ups == []
    # A model that returns objects here is rejected at the schema boundary rather than silently
    # producing chips that claim a grounding they do not have.
    with pytest.raises(ValidationError):
        Answer(text="x", follow_ups=[{"question": "q", "citations": []}])


def test_the_podcast_task_really_does_carry_the_longest_instructions():
    """Invariant 59 explains why a token-cap failure hit the podcast FIRST while every other task
    survived on the same model, and the explanation rests on a measurement. Pinned so the claim
    cannot quietly stop being true — and because the numbers in an early draft of it were taken from
    a report rather than from the code."""
    from rlm_notebook.audio import GeneratePodcastScript
    from rlm_notebook.guide import (
        GenerateFAQ,
        GenerateKeyInsight,
        GenerateSummary,
        GenerateTimeline,
    )
    from rlm_notebook.task import AnswerQuestion

    others = [
        len(cls.instructions)
        for cls in (
            AnswerQuestion,
            GenerateSummary,
            GenerateFAQ,
            GenerateTimeline,
            GenerateKeyInsight,
        )
    ]
    assert len(GeneratePodcastScript.instructions) > max(others), (
        "the podcast no longer has the longest instructions, so invariant 59's account of why the "
        "token cap bit it first is no longer the explanation"
    )


def test_no_response_ships_a_corpus_marker_in_its_prose(client, monkeypatch):
    """Behavioural: every artifact's text goes through `_prose`, and the SAME value is handed to
    `_citation_responses`, so the string on screen and the string the spans were located in can
    never be different."""
    _live_env(monkeypatch)
    _add_a_source(client)
    _mock_runner(
        monkeypatch,
        {
            "text": "Voyager left in 2012.[[SRC:s1|whole]]",
            "citations": [
                {
                    "source_id": "s1",
                    "locator": "whole",
                    "quote": "content of https://example.com/a",
                    "answer_span": "Voyager left in 2012.[[SRC:s1|whole]]",
                }
            ],
        },
    )

    asked = client.post("/notebooks/mynb/ask", json={"question": "q"}).json()
    assert "[[SRC:" not in asked["text"]
    # ...and the span still locates against the stripped prose, so the stroke survives.
    assert asked["citations"][0]["answer_span"] == "Voyager left in 2012."

    turn = client.get("/notebooks/mynb").json()["turns"][0]
    assert "[[SRC:" not in turn["answer"]
    assert turn["citations"][0]["answer_span"] == "Voyager left in 2012."


def test_every_artifact_text_in_a_response_goes_through_the_same_stripper():
    """A source-tree assertion for the sites a mocked test cannot all reach at once (guide kinds,
    podcast utterances). Passing the RAW text to one of the two arguments and the stripped text to
    the other is silent: the markers vanish from screen and every highlighter stroke stops being
    found, which is the failure invariant 49 already records one layer up."""
    import inspect
    import re as _re

    source = inspect.getsource(api)
    # The DEFINITION is excluded by its type annotations, not by looking for "def" — that word sits
    # before the paren the regex captures, so the obvious filter never matched it. The older sibling
    # of this test has the same hole and passes only because a def line happens to satisfy its
    # assertion; both are fixed here.
    calls = _re.findall(r"_citation_responses\(([^)]*)\)", source)
    calls = [c for c in calls if ": " not in c]
    assert len(calls) >= 8, f"call sites went missing, so this would pass vacuously: {calls}"
    for call in calls:
        prose_arg = [a.strip() for a in call.split(",")][2]
        assert prose_arg.startswith("_prose("), (
            f"_citation_responses({call}) is given prose that has not been stripped of corpus "
            f"markers, while the text beside it has"
        )


def test_the_podcast_length_reaches_the_task(client, monkeypatch):
    """A tier the request carries but the task never receives is the `RN_OCR_PROVIDER` shape
    (invariant 7): validated on the way in, then ignored. And invariant 39 records the asymmetry
    that makes it invisible — a MISSING required input surfaces only as an opaque
    `RLMTaskError`, while an UNDECLARED extra kwarg is silently accepted."""
    _live_env(monkeypatch)
    _add_a_source(client)
    seen: list[dict] = []

    async def _fake_start_run(run_id, trace_dir, dotted_task, kwargs):
        seen.append(kwargs)
        return _FakeRun(run_id)

    async def _fake_wait_result(run, *, timeout=None):
        return {"utterances": []}

    monkeypatch.setattr(api.runner, "start_run", _fake_start_run)
    monkeypatch.setattr(api.runner, "wait_result", _fake_wait_result)

    client.post("/notebooks/mynb/audio", json={"length": "long"})
    assert seen and seen[-1]["target_length"] == "long"

    seen.clear()
    client.post("/notebooks/mynb/audio", json={})
    assert seen[-1]["target_length"] == "default", "an absent length must not become empty"


def test_the_podcast_length_refuses_an_unknown_tier_and_a_typo(client, monkeypatch):
    """`extra="forbid"` for the same reason `SettingsRequest` has it (invariant 41): pydantic DROPS
    unknown keys, so `{"len": "long"}` would quietly produce a default-length episode after a real
    model run."""
    _live_env(monkeypatch)
    _add_a_source(client)
    assert client.post("/notebooks/mynb/audio", json={"length": "epic"}).status_code == 422
    assert client.post("/notebooks/mynb/audio", json={"len": "long"}).status_code == 422


def test_the_podcast_task_declares_the_length_it_is_given():
    """The signature is a class-level string composed at import time, so a per-request value can
    only reach the model as a FIELD. Declared but never passed, or passed but never declared, both
    fail silently in the directions invariant 39 documents."""
    from rlm_notebook.audio import GeneratePodcastScript

    assert "target_length: str" in GeneratePodcastScript.signature
    for tier in ("short", "default", "long"):
        assert f"`{tier}`" in GeneratePodcastScript.instructions, (
            f"the prompt does not say what `{tier}` means, so the field is a word with no effect"
        )


def test_every_rlm_task_gets_the_skills_by_injection():
    """One helper, six tasks. The wiring lived in `audio.py` first and was hand-rolled there; six
    copies of it is exactly the drift invariant 13 factors `CITATION_RULES` out to prevent.

    `read_skill` and NOT `list_skills`: the catalog is already in the prompt, so a discovery
    round-trip would spend a planner turn learning what it was told at startup.
    """
    from rlm_harness import RLMConfig
    from rlm_harness import runtime as rt

    from rlm_notebook.audio import GeneratePodcastScript
    from rlm_notebook.guide import (
        GenerateFAQ,
        GenerateKeyInsight,
        GenerateSummary,
        GenerateTimeline,
    )
    from rlm_notebook.task import AnswerQuestion

    # Instantiating an RLMTask needs the harness configured; nothing here runs a model. Snapshot and
    # RESTORE, because `configure` is global: leaving a dummy config behind makes every test that
    # follows depend on this one having run, which is the ordering coupling a suite is least able to
    # see. Found by this test's own sibling failing when run alone.
    previous = getattr(rt, "_CONFIG", None)
    rt.configure(RLMConfig(main_model="x", sub_model="x", interpreter="pyodide", observe=False))

    tasks = (
        AnswerQuestion,
        GenerateSummary,
        GenerateFAQ,
        GenerateTimeline,
        GenerateKeyInsight,
        GeneratePodcastScript,
    )
    for cls in tasks:
        task = cls()
        names = {getattr(tool, "__name__", "") for tool in task.tools}
        assert "read_skill" in names, f"{cls.__name__} has no skills"
        assert "list_skills" not in names, f"{cls.__name__} pays for a discovery round-trip"
        assert "corpus-navigation" in task.instructions, f"{cls.__name__} got no catalog"
        # The class-level prompt is untouched; only the instance carries the catalog.
        assert "corpus-navigation" not in cls.instructions
        # ...and it is still switchable off, which a caller needs: a stale skill is worse than none.
        assert {getattr(t, "__name__", "") for t in cls(skills_dir=None).tools} == {
            f"validate_{cls.output_model.__name__.lower()}"
        }

    if previous is not None:
        rt._CONFIG = previous


def test_the_skills_wiring_exists_once():
    """A source-tree assertion: six tasks calling `load_skills_as_tools` themselves would each own
    a header, and the headers would drift."""
    import inspect

    from rlm_notebook import audio, guide, instructions, task

    for module in (audio, guide, task):
        source = inspect.getsource(module)
        assert "load_skills_as_tools" not in source, (
            f"{module.__name__} wires skills itself instead of calling `instructions.apply_skills`"
        )
        assert "render_skills_manifest" not in source
    assert inspect.getsource(instructions).count("render_skills_manifest(") == 1


def test_every_task_validator_rejects_a_marker_in_its_own_prose():
    """The check was written for the podcast, whose failure was LOUD — the voice read the markers
    aloud. `GenerateSummary` had produced exactly the same defect silently: four markers printed in
    an overview a user reported as a broken render. A guard on the one task that made a noise is a
    guard on the symptom.

    Not a schema validator, deliberately: notebooks already on disk hold artifacts with markers in
    them, and a field-level reject would make those files fail to LOAD — untidy data turned into a
    corrupt-notebook 409.
    """
    import json

    from rlm_notebook.instructions import make_grounded_validator
    from rlm_notebook.schema import FAQ, Answer, KeyInsight, PodcastScript, Summary, Timeline

    cases = {
        Answer: {"text": "A claim.[[SRC:s1|whole]]", "citations": []},
        Summary: {"text": "A claim.[[SRC:s1|whole]]", "citations": []},
        KeyInsight: {"text": "A claim.[[SRC:s1|whole]]", "citations": []},
        FAQ: {"items": [{"question": "q?", "answer": "a [[SRC:s1|whole]]", "citations": []}]},
        Timeline: {"events": [{"when": "2012", "description": "x [[SRC:s1|whole]]", "citations": []}]},
        PodcastScript: {"utterances": [{"speaker": "host_a", "text": "x [[SRC:s1|whole]]", "citations": []}]},
    }
    for model, payload in cases.items():
        verdict = make_grounded_validator(model)(json.dumps(payload))
        assert verdict.startswith("Validation failed"), f"{model.__name__} accepts a marker in prose"
        assert "[[SRC:" in verdict, "the message does not name what is wrong"

    # A quote is EXEMPT: it is copied verbatim from a source, which could itself contain the text.
    quoted = json.dumps({
        "text": "A claim.",
        "citations": [{"source_id": "s1", "locator": "whole", "quote": "the source wrote [[SRC:x|y]]"}],
    })
    assert make_grounded_validator(Summary)(quoted).startswith("Validation successful")


def test_the_validator_factory_exists_once():
    """Six tasks hand-rolling a schema-plus-marker check would drift, which is what happened: the
    podcast had one and the other five did not."""
    import inspect

    from rlm_notebook import audio, guide, instructions, task

    for module in (audio, guide, task):
        assert "make_schema_validator" not in inspect.getsource(module), (
            f"{module.__name__} builds a bare schema validator, so its prose is unguarded"
        )
    assert inspect.getsource(instructions).count("def make_grounded_validator") == 1


def test_the_skills_catalog_keeps_its_header():
    """A bare `- name: description` list tells the model nothing about what `read_skill` is or that
    it should consult one. `_SKILLS_HEADER`'s own comment says it exists to prevent that drift, and
    an independent review dropped the argument and watched the whole suite stay green."""
    from rlm_harness import RLMConfig
    from rlm_harness import runtime as rt

    from rlm_notebook.task import AnswerQuestion

    previous = getattr(rt, "_CONFIG", None)
    rt.configure(RLMConfig(main_model="x", sub_model="x", interpreter="pyodide", observe=False))
    try:
        instructions = AnswerQuestion().instructions
        assert "<available_skills>" in instructions
        assert "read_skill(name)" in instructions, "the catalog no longer says how to open one"
        # An element that is opened must be closed, or every rule after it reads as being inside.
        assert "</available_skills>" in instructions
        assert instructions.index("<available_skills>") < instructions.index("</available_skills>")
    finally:
        if previous is not None:
            rt._CONFIG = previous


def test_an_empty_skills_directory_wires_nothing_at_all(tmp_path):
    """`load_skills_as_tools` returns `read_skill` whether or not anything was discovered, and that
    tool's description tells the model to pick "the ones listed in the skills manifest in your
    instructions". Gating the TOOL on the directory existing rather than on the manifest handed the
    model a tool pointing at a list that was not there — found by an independent fact-check of the
    documentation, which claimed this was already the behaviour."""
    from rlm_harness import RLMConfig
    from rlm_harness import runtime as rt

    from rlm_notebook.task import AnswerQuestion

    previous = getattr(rt, "_CONFIG", None)
    rt.configure(RLMConfig(main_model="x", sub_model="x", interpreter="pyodide", observe=False))
    try:
        empty = tmp_path / "no-skills"
        empty.mkdir()
        task = AnswerQuestion(skills_dir=str(empty))
        names = [getattr(t, "__name__", str(t)) for t in task.tools]
        assert "read_skill" not in names, f"a skill-less directory still wired a tool: {names}"
        assert "<available_skills>" not in task.instructions

        # And with a real skill present, both halves ARE wired — or the guard above is vacuous.
        (empty / "a-skill.md").write_text(
            "---\nname: a-skill\ndescription: something\n---\n\n# body\n", encoding="utf-8"
        )
        wired = AnswerQuestion(skills_dir=str(empty))
        assert "read_skill" in [getattr(t, "__name__", str(t)) for t in wired.tools]
        assert "<available_skills>" in wired.instructions
    finally:
        if previous is not None:
            rt._CONFIG = previous


def test_every_podcast_tier_has_a_wall_clock_allowance():
    """A tier added without deciding its budget is a tier that ships unable to finish under the
    default backstop — which is exactly what `long` did: it timed out at 300s with a trace holding
    three events, on a notebook whose ordinary chat answer took 77s. Keeping the factors NEXT TO
    the literal only helps if something fails when they drift apart."""
    from typing import get_args

    from rlm_notebook.schema import PODCAST_TIMEOUT_FACTOR, PodcastLength

    assert set(get_args(PodcastLength)) == set(PODCAST_TIMEOUT_FACTOR)
    factors = [PODCAST_TIMEOUT_FACTOR[t] for t in get_args(PodcastLength)]
    assert factors == sorted(factors), factors
    assert factors[0] >= 1.0, "no tier may get a SHORTER backstop than a chat turn"
    # NON-DEGENERATE. Monotonicity alone is true of an all-equal table — i.e. of no scaling at all,
    # which is precisely the state that 502'd the reported `long` episode. An independent review
    # flattened this table to {1.0, 1.0, 1.0} and watched the whole suite stay green.
    assert factors[-1] > factors[0], (
        f"every tier gets the same backstop ({factors}) — that is the bug invariant 68 fixed"
    )


def test_the_podcast_run_gets_the_tier_scaled_backstop_not_the_default():
    """Pins the WIRING. The factor table existing proves nothing if the handler still passes the
    unscaled `config.run_timeout_seconds` — the reported 502 came from precisely that value
    reaching `wait_result`."""
    import inspect

    from rlm_notebook import api

    src = inspect.getsource(api.audio)
    assert "PODCAST_TIMEOUT_FACTOR[body.length]" in src, (
        "the podcast run no longer scales its wall-clock backstop by the requested tier"
    )
    # And the override actually reaches wait_result rather than being computed and dropped.
    isolated = inspect.getsource(api._run_isolated)
    assert "timeout=timeout or config.run_timeout_seconds" in isolated, isolated[-400:]


def test_the_interface_language_reaches_language_resolution_as_a_signal():
    """A user set the interface to Traditional Chinese and their notebook still came back titled
    "LLM Harnesses for Bug Hunting". The chosen interface language is a real signal about what a
    person reads and it was not being sent at all — only `Accept-Language`, which the OS chose."""
    import inspect

    from rlm_notebook import api, naming

    src = inspect.getsource(api._resolve_language)
    assert '"interface_language": request.headers.get("x-rlm-interface-language", "")' in src, src

    # The receiving end must actually declare it, or the kwarg is silently accepted and ignored
    # (invariant 39 records that exact asymmetry as the reason its own tripwire exists).
    sig = inspect.signature(naming.SuggestLanguage.arun)
    assert "interface_language" in sig.parameters
    body = inspect.getsource(naming.SuggestLanguage.arun)
    assert "interface_language: str -> language: str" in body, "not declared on the dspy signature"
    assert "interface_language=interface_language" in body, "declared but never passed"


def test_every_grounded_task_tells_the_model_to_keep_proper_nouns():
    """"Trinity" must not become a translation of the word "trinity" — a translated name is the one
    term a reader then cannot search for. Shared from ONE constant like every other language rule
    (invariant 13), so it cannot land on some tasks and not others."""
    from rlm_notebook.instructions import PROPER_NOUNS, artifact_language_rule, chat_language_rule

    assert "Trinity" in PROPER_NOUNS
    for rule in (chat_language_rule("Traditional Chinese"), artifact_language_rule("Japanese")):
        assert PROPER_NOUNS in rule, "a language rule dropped the proper-noun paragraph"


def _trace_events():
    """A run with two turns, a skill read, a FAILED validate and a passing one — the shape a real
    failed-then-fixed run has, which is exactly what a reader opens the drawer to understand."""
    return [
        {"type": "run_start", "step_id": 0, "ts": 1000.0, "payload": {"meta": {"task": "x:Y"}}},
        {
            "type": "main_step",
            "step_id": 1,
            "ts": 1002.0,
            "payload": {"turn": 0, "reasoning": "look for it", "code": "find(...)", "output": "hit"},
        },
        {
            "type": "tool_call",
            "step_id": 2,
            "ts": 1003.0,
            "payload": {"tool": "read_skill", "args": {"name": "corpus-navigation"}, "result_len": 9},
        },
        {
            "type": "tool_call",
            "step_id": 3,
            "ts": 1005.0,
            "payload": {"tool": "validate_summary", "result": "Validation failed: bad coordinate"},
        },
        {
            "type": "main_step",
            "step_id": 4,
            "ts": 1010.0,
            "payload": {"turn": 1, "reasoning": "fix it", "code": "SUBMIT", "output": ""},
        },
        {"type": "run_end", "step_id": 5, "ts": 1014.0, "payload": {"ok": True, "error": None}},
    ]


def test_the_trajectory_separates_the_two_clocks_a_run_actually_has():
    from rlm_notebook.trajectory import build_trajectory

    traj = build_trajectory(_trace_events())
    assert traj["total_s"] == 14.0
    assert traj["ok"] is True
    assert traj["per_turn_timing"] is True, "two turns 8s apart is live timing, not finalize-flush"

    turns = traj["iterations"]
    assert [t["index"] for t in turns] == [0, 1]
    # Turn 0 runs until turn 1 starts; the LAST turn runs until the run ends.
    assert turns[0]["duration_s"] == 8.0
    assert turns[1]["duration_s"] == 4.0
    assert turns[0]["rel_s"] == 2.0

    line = traj["timeline"]
    assert [e["label"] for e in line] == ["skill", "validate"]
    # A call is attributed to the turn whose code produced it, never to the next one.
    assert {e["turn_index"] for e in line} == {0}
    # `duration_s` is the gap since the PREVIOUS live event, so three equal values would hide a bug.
    assert [e["duration_s"] for e in line] == [3.0, 2.0]
    assert [e["rel_s"] for e in line] == [3.0, 5.0]


def test_a_failed_validate_surfaces_its_verdict_because_that_is_the_useful_part():
    """A failed run's single most useful fact is what the validator told the model to fix — an
    invented coordinate, a marker in prose, a shape error — and how many rounds it took."""
    from rlm_notebook.trajectory import build_trajectory

    entry = next(
        e for e in build_trajectory(_trace_events())["timeline"] if e["label"] == "validate"
    )
    assert entry["passed"] is False
    assert entry["verdict"] == "Validation failed: bad coordinate"
    assert entry["target"] == "summary"


def test_a_trace_with_no_run_end_still_decomposes():
    """A run that was cancelled or timed out has no `run_end` — and is exactly the run someone most
    wants to look at. The reported 502 produced precisely this shape: run_start, two tool calls,
    then nothing."""
    from rlm_notebook.trajectory import build_trajectory

    traj = build_trajectory(_trace_events()[:4])
    assert traj["ok"] is None and traj["total_s"] is None
    assert len(traj["timeline"]) == 2
    assert traj["iterations"][0]["turn"] == 0


def test_finalize_flushed_timestamps_are_not_reported_as_per_turn_timing():
    """An older trace wrote every `main_step` at finalize, so their timestamps cluster at one
    instant. Reporting those as durations would invent numbers; the tool timeline is still real."""
    from rlm_notebook.trajectory import build_trajectory

    events = _trace_events()
    for event in events:
        if event["type"] == "main_step":
            event["ts"] = 1013.9
    traj = build_trajectory(events)
    assert traj["per_turn_timing"] is False
    assert all("duration_s" not in t for t in traj["iterations"])
    assert all("turn_index" not in e for e in traj["timeline"])
    assert [e["duration_s"] for e in traj["timeline"]] == [3.0, 2.0], "tool timing is still real"


def test_the_trajectory_endpoint_refuses_a_run_id_from_another_notebook(tmp_path, monkeypatch):
    """Same ownership check `stream_run`/`citation_turn` apply, and applied on the SLUG — invariant
    38 records that comparing the raw id made every trace link dead for a non-Latin notebook."""
    from fastapi.testclient import TestClient

    from rlm_notebook import api

    monkeypatch.setattr(api, "_TRACE_DIR", tmp_path)
    with TestClient(api.app) as client:
        resp = client.get("/notebooks/mine/runs/theirs-abc/trajectory")
        assert resp.status_code == 404
        assert "does not belong" in resp.json()["detail"]


def test_the_trajectory_endpoint_reads_a_trace_that_is_still_being_written(tmp_path, monkeypatch):
    """The drawer is how a reader watches a LONG run, not only how they inspect a finished one — a
    `long` podcast is minutes of wall clock. The writer is appending while this reads, so a
    half-written final line is the normal case, not an error."""
    from fastapi.testclient import TestClient

    from rlm_notebook import api
    from rlm_notebook.notebook import slug

    monkeypatch.setattr(api, "_TRACE_DIR", tmp_path)
    run_id = f"{slug('nb1')}-abc"
    lines = [json.dumps(e) for e in _trace_events()[:3]]
    # ...plus a torn final line, exactly as a concurrent flush leaves it.
    (tmp_path / f"{run_id}.jsonl").write_text("\n".join(lines) + '\n{"type": "main_ste', "utf-8")

    with TestClient(api.app) as client:
        body = client.get(f"/notebooks/nb1/runs/{run_id}/trajectory").json()
    assert body["run_id"] == run_id
    assert body["ok"] is None, "an unfinished run must not report an outcome"
    assert len(body["iterations"]) == 1 and len(body["timeline"]) == 1


def test_every_grounded_task_carries_the_build_across_turns_rule():
    """Invariant 64's mechanic is must-apply BY ITS OWN ACCOUNT — skipping it loses the whole run —
    and it spent a slice living only in `GeneratePodcastScript`'s prompt, with the other five tasks
    relying on the OPTIONAL `corpus-navigation` skill that a model may simply never open.

    Invariant 65 recorded that as the one unclean line of the prompt/skill split and named
    promoting it as a real follow-up. This is the tripwire for the promotion: a must-apply rule
    reaching five of six tasks is exactly the drift invariant 13 exists to prevent."""
    from rlm_harness import RLMConfig
    from rlm_harness import runtime as rt

    from rlm_notebook.audio import GeneratePodcastScript
    from rlm_notebook.guide import GenerateFAQ, GenerateKeyInsight, GenerateSummary, GenerateTimeline
    from rlm_notebook.instructions import ACCUMULATE_LARGE_OUTPUTS
    from rlm_notebook.task import AnswerQuestion

    previous = getattr(rt, "_CONFIG", None)
    rt.configure(RLMConfig(main_model="x", sub_model="x", interpreter="pyodide", observe=False))
    try:
        tasks = [
            AnswerQuestion,
            GenerateSummary,
            GenerateFAQ,
            GenerateTimeline,
            GenerateKeyInsight,
            GeneratePodcastScript,
        ]
        for task_cls in tasks:
            assert ACCUMULATE_LARGE_OUTPUTS in task_cls(skills_dir=None).instructions, (
                f"{task_cls.__name__} does not carry the build-across-turns rule"
            )
        # ONE copy, not six near-copies: the podcast's own tier paragraph must point at the shared
        # rule rather than restate it (invariant 13's discipline, which this promotion is applying).
        podcast = GeneratePodcastScript(skills_dir=None).instructions
        assert podcast.count("Never print the thing you are") == 1, "the rule was hand-duplicated"
    finally:
        if previous is not None:
            rt._CONFIG = previous


def test_the_web_assets_tell_the_browser_to_revalidate():
    """Starlette's `StaticFiles` sends `ETag`/`Last-Modified` but NO `Cache-Control`, which leaves a
    browser on HEURISTIC caching — free to reuse a stale copy without asking. This is a zero-build
    app whose assets carry no content hash in their filenames (invariant 29), so there is no
    cache-busting URL to fall back on either.

    A user hit exactly that: after an update they pressed the steps pill and got the OLD inline
    reasoning log, the very thing the Trajectory drawer had replaced, because their browser was
    still running the previous `app.js`. The server was serving the new one and nothing on the page
    could have told them otherwise.
    """
    from fastapi.testclient import TestClient

    from rlm_notebook import api

    with TestClient(api.app) as client:
        for path in ("/", "/app.js", "/style.css", "/i18n.js"):
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert resp.headers.get("cache-control") == "no-cache", (
                f"{path} may be served from a browser cache without revalidating"
            )
            # `no-cache` is NOT `no-store`: the copy stays cached and the ETag short-circuits the
            # transfer, so revalidation costs a 304 with no body. Losing the ETag would turn every
            # navigation into a full re-download of a 190KB script.
            assert resp.headers.get("etag"), f"{path} has no ETag, so revalidation re-sends the body"

        etag = client.get("/app.js").headers["etag"]
        assert client.get("/app.js", headers={"If-None-Match": etag}).status_code == 304


def test_the_run_records_what_it_was_configured_with_and_no_secrets():
    """The Trajectory drawer's "Initial state" panel is built from `run_start`'s meta. With only
    `task` in it, that panel repeated the drawer's own headline and said nothing else — while
    "which model, and how much rope did it have" are the first two questions anyone asks of a run
    that went wrong, and `config.py` cannot answer them after the fact because the environment
    moves.

    A trace is already the most exposed artifact this project writes (invariant 29), so what goes
    into it is a decision: model NAMES and budgets, never credentials."""
    import inspect

    from rlm_notebook import worker

    src = inspect.getsource(worker.main)
    meta = src[src.index("meta = {") : src.index("}", src.index("meta = {")) + 1]
    for key in ("task", "main_model", "sub_model", "max_iterations", "max_tokens", "max_retries"):
        assert f'"{key}"' in meta, f"{key} is no longer recorded: {meta}"
    for secret in ("api_key", "base_url", "RN_API_KEY"):
        assert secret not in meta, f"{secret} would be written into a world-readable trace"


def test_a_runs_inputs_reach_its_trace_but_the_corpus_never_does():
    """The Trajectory drawer's "Initial state" held the task name and the budgets and nothing about
    what THIS run was asked to do. The question, the language, the requested podcast length — each
    is one short string, each answers "why did it produce that", and none is derivable afterwards
    from a notebook that has since moved on.

    The corpus itself is megabytes and a trace is the most exposed artifact this project writes
    (invariant 29), so its SIZE goes in and its TEXT never does — the same reasoning invariant 52
    gives for streaming a step's output size rather than its text."""
    from rlm_notebook.worker import _input_meta

    blob = "[[SRC:s1|whole]]\n" + ("corpus " * 20_000)
    meta = _input_meta(
        {
            "sources": blob,
            "history": "a very long prior conversation " * 400,
            "question": "How do harnesses change bug hunting?",
            "output_language": "Traditional Chinese",
        }
    )
    assert meta["source_chars"] == len(blob)
    assert meta["question"] == "How do harnesses change bug hunting?"
    assert meta["output_language"] == "Traditional Chinese"
    # The blob and the history are never carried, at any size.
    assert "sources" not in meta and "history" not in meta
    assert not any(isinstance(v, str) and "corpus " in v for v in meta.values())

    # A long free-text argument is prose, not a setting: it belongs in the run, not in the header.
    assert "question" not in _input_meta({"question": "q" * 500})
    # An empty one is noise.
    assert "output_language" not in _input_meta({"output_language": "   "})
    # And the podcast's tier, which is exactly the "why is this 80 turns" answer.
    assert _input_meta({"target_length": "long"})["target_length"] == "long"


def test_every_grounded_task_forbids_the_model_numbering_its_own_citations():
    """A real overview came back with `[1]`..`[8]` written into its prose while carrying six
    citations. The interface numbers citations itself, from the order it renders them in, so the
    reader saw two numbering systems side by side — a superscript 3 next to a literal `[5]`.

    Prompt-only, deliberately. A display-layer strip is what invariant 62 does for `[[SRC:...]]`,
    which is unambiguous; a bare `[1]` is not — `arr[1]` is ordinary prose in this project's own
    subject matter, and stripping it would corrupt a quote or a code snippet to tidy a number.
    """
    from rlm_harness import RLMConfig
    from rlm_harness import runtime as rt

    from rlm_notebook.audio import GeneratePodcastScript
    from rlm_notebook.guide import GenerateFAQ, GenerateKeyInsight, GenerateSummary, GenerateTimeline
    from rlm_notebook.task import AnswerQuestion

    previous = getattr(rt, "_CONFIG", None)
    rt.configure(RLMConfig(main_model="x", sub_model="x", interpreter="pyodide", observe=False))
    try:
        for task_cls in (
            AnswerQuestion,
            GenerateSummary,
            GenerateFAQ,
            GenerateTimeline,
            GenerateKeyInsight,
            GeneratePodcastScript,
        ):
            instructions = task_cls(skills_dir=None).instructions
            assert "Do NOT number your citations in your own prose" in instructions, (
                f"{task_cls.__name__} does not carry the no-self-numbering rule"
            )
    finally:
        if previous is not None:
            rt._CONFIG = previous


def test_clearing_a_conversation_keeps_everything_that_is_not_the_conversation(tmp_path, monkeypatch):
    """Turns were append-only: a source could be deleted and a note could be deleted, but a
    conversation could only grow. Regenerate replaces the LAST answer and deliberately cannot reach
    further back (invariant 11); clearing is the other end of that same fact.

    Sources, notes, the overview and the podcast are NOT part of the conversation — a reader
    starting a chat over is not asking to lose their corpus."""
    from fastapi.testclient import TestClient

    from rlm_notebook import api
    from rlm_notebook import notebook as nbmod
    from rlm_notebook.schema import Answer, ChatTurn, Note, Notebook, Overview, Source, SourceBlock

    # The notebooks dir resolves against the process cwd (`DEFAULT_NOTEBOOKS_DIR`), which is
    # how every other notebook-writing test in this file isolates itself.
    monkeypatch.chdir(tmp_path)
    nb = Notebook(
        id="nb1",
        sources=[Source(id="s1", origin="x", kind="text", blocks=[SourceBlock(locator="whole", text="t")])],
        notes=[Note(id="n1", text="kept")],
        overview=Overview(text="kept", citations=[], source_ids=["s1"]),
        turns=[
            ChatTurn(question="q1", answer=Answer(text="a1", citations=[])),
            ChatTurn(question="q2", answer=Answer(text="a2", citations=[])),
        ],
    )
    nbmod.save_notebook(nb)

    with TestClient(api.app) as client:
        body = client.delete("/notebooks/nb1/turns").json()
    assert body["turns"] == []
    assert [s["id"] for s in body["sources"]] == ["s1"], "clearing a chat took the sources with it"
    assert [n["id"] for n in body["notes"]] == ["n1"], "clearing a chat took the notes with it"
    assert body["overview"] and body["overview"]["text"] == "kept"
    # The corpus has not moved, so nothing derived from it becomes stale.
    assert body["overview"]["stale"] is False

    # Persisted, not just echoed.
    assert nbmod.load_notebook("nb1").turns == []


def test_clearing_a_conversation_on_a_missing_notebook_is_a_404(tmp_path, monkeypatch):
    """`create=False`, matching every other existing-notebook-only mutator — clearing the chat of a
    notebook that does not exist must not conjure one."""
    from fastapi.testclient import TestClient

    from rlm_notebook import api

    monkeypatch.chdir(tmp_path)
    with TestClient(api.app) as client:
        assert client.delete("/notebooks/ghost/turns").status_code == 404
    assert not list((tmp_path / "notebooks").glob("*.json")), "a 404 left a notebook file behind"


# --- run_end budgets/usage (rlm-harness 1.10.0) -----------------------------------------------
# `trajectory.budget_summary` is a pure function over trace events, so these need no server, no
# model and no run — the same seam `tts.sequence_offsets` uses (invariant 44).


def _budget_events(usage, *, budgets=None):
    """A minimal two-event trace carrying whatever `run_end` payload a case needs."""
    payload = {"ok": True}
    if budgets is not None:
        payload["budgets"] = budgets
    if usage is not None:
        payload["usage"] = usage
    return [
        {"type": "run_start", "ts": 0.0, "payload": {"meta": {"task": "AnswerQuestion"}}},
        {"type": "run_end", "ts": 9.0, "payload": payload},
    ]


_CAPS = {
    "main": {"cap": 16384, "key": "max_tokens"},
    "sub": {"cap": 16384, "key": "max_tokens"},
    "iterations": {
        "max_iterations": 25,
        "max_llm_calls": None,
        "max_output_chars": 40000,
        "dropped": False,
    },
}


def test_budget_summary_is_none_for_a_trace_written_before_the_fields_existed():
    """The cross-boundary rule, as code: `run_end.budgets`/`usage` arrived with rlm-harness 1.10.0,
    so an older trace must read UNMEASURED. Returning a zeroed summary would let a reader average a
    truncation rate across the upgrade and see corpus composition as a property of the code."""
    from rlm_notebook.trajectory import budget_summary

    assert budget_summary(_budget_events(None)) is None
    assert budget_summary([]) is None


def test_budget_summary_flags_a_turn_truncated_at_the_cap():
    from rlm_notebook.trajectory import budget_summary

    usage = [{"attempt": 0, "calls": {"anthropic/x": [{"completion_tokens": 16384}]}}]
    summary = budget_summary(_budget_events(usage, budgets=_CAPS))

    assert summary["truncated"] is True
    assert (summary["peak_completion"], summary["cap"], summary["ratio"]) == (16384, 16384, 1.0)


def test_budget_summary_reports_a_ratio_for_a_run_that_stayed_under():
    """The proximity reading. Kept as a NUMBER rather than ruled out: the measured "the ratio is
    never an early warning" came from a corpus running at twice the cap its model needed."""
    from rlm_notebook.trajectory import budget_summary

    usage = [{"attempt": 0, "calls": {"m": [{"completion_tokens": 3200}, {"completion_tokens": 90}]}}]
    summary = budget_summary(_budget_events(usage, budgets=_CAPS))

    assert summary["truncated"] is False
    assert summary["peak_completion"] == 3200
    assert summary["ratio"] == 0.195


def test_budget_summary_takes_the_peak_across_retry_attempts():
    """`usage` is per ATTEMPT, and a retry is exactly the run whose fatal call matters most."""
    from rlm_notebook.trajectory import budget_summary

    usage = [
        {"attempt": 0, "calls": {"m": [{"completion_tokens": 900}]}},
        {"attempt": 1, "calls": {"m": [{"completion_tokens": 16384}]}},
    ]
    summary = budget_summary(_budget_events(usage, budgets=_CAPS))

    assert summary["peak_completion"] == 16384
    assert summary["truncated"] is True
    assert [a["truncated"] for a in summary["attempts"]] == [False, True]


def test_budget_summary_does_not_guess_truncation_without_a_cap():
    """With no cap reported there is nothing to be at, so a large number is just a large number."""
    from rlm_notebook.trajectory import budget_summary

    usage = [{"attempt": 0, "calls": {"m": [{"completion_tokens": 99999}]}}]
    summary = budget_summary(_budget_events(usage, budgets={"iterations": _CAPS["iterations"]}))

    assert summary["cap"] is None
    assert summary["truncated"] is False
    assert summary["ratio"] is None


def test_budget_summary_surfaces_the_dropped_iteration_caps():
    """`dropped` means dspy rejected the budget kwargs and every cap reverted to its own default —
    without it the three numbers beside it read as applied when they were not."""
    from rlm_notebook.trajectory import budget_summary

    caps = {**_CAPS, "iterations": {**_CAPS["iterations"], "dropped": True}}
    summary = budget_summary(_budget_events([], budgets=caps))

    assert summary["iterations"]["dropped"] is True


def test_budget_summary_never_raises_on_a_malformed_usage_payload():
    """Same promise the rest of this module makes: a partial or malformed trace is exactly the run
    someone most wants to look at."""
    from rlm_notebook.trajectory import budget_summary

    usage = [{"attempt": 0, "calls": {"m": ["not-a-dict", {"completion_tokens": "many"}]}}, "junk"]
    summary = budget_summary(_budget_events(usage, budgets=_CAPS))

    assert summary["truncated"] is False
    assert summary["peak_completion"] is None
