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
from typing import ClassVar

import pytest

fastapi = pytest.importorskip("fastapi")

from _pdf_fixtures import make_text_pdf_bytes
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
    500) is what this pins, and it sweeps EVERY id-taking endpoint rather than a sample: an
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

    def __init__(self, *, boom: str | None = None, payload: bytes = b"fake-mp3-bytes") -> None:
        self.boom = boom
        self.payload = payload
        self.calls: list[tuple] = []

    def synthesize(self, script, voice_map, out_path):
        self.calls.append((script, voice_map, out_path))
        if self.boom:
            raise api.TTSError(self.boom)
        out_path.write_bytes(self.payload)


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
    assert body == {"utterances": [], "audio_base64": None}
    assert provider.calls == []  # synthesize() never called for an empty script


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


def test_translate_trace_event_covers_the_known_event_types():
    assert api._translate_trace_event({"type": "main_step", "step_id": 0, "payload": {}})["kind"] == "thinking"
    assert (
        api._translate_trace_event({"type": "tool_call", "step_id": 1, "payload": {"tool": "read"}})["kind"]
        == "tool"
    )
    assert api._translate_trace_event({"type": "sub_call", "step_id": 2, "payload": {}})["kind"] == "escalation"
    assert (
        api._translate_trace_event({"type": "run_end", "step_id": 3, "payload": {"ok": True}})["summary"]
        == "finished"
    )
    assert (
        api._translate_trace_event({"type": "run_end", "step_id": 4, "payload": {"ok": False}})["summary"]
        == "finished with an error"
    )


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
    assert '"kind": "done"' in body or '"kind":"done"' in body.replace(" ", "")


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


def test_stream_run_synthesizes_a_terminal_event_for_a_dead_process_with_no_run_end(client, monkeypatch):
    """A killpg-cancelled run's TraceRecorder never reaches __exit__, so no run_end is ever
    written — the stream must still reach a terminal state instead of hanging forever."""
    monkeypatch.setattr(api, "_TRACE_POLL_INTERVAL", 0.01)
    _write_trace("mynb-killed", [{"type": "run_start", "payload": {}}])
    # No entry in _RUN_PROCESSES at all == "no longer tracked as alive", the same state a
    # finished-and-cleaned-up (or never-tracked) run would be in.

    resp = client.get("/notebooks/mynb/runs/mynb-killed/stream")

    assert resp.status_code == 200
    assert "done" in resp.text


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
        def synthesize(self, script, voice_map, out_path):
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
        def synthesize(self, script, voice_map, out_path):
            out_path.write_bytes(b"x")

    monkeypatch.setattr(api, "get_tts_provider", lambda name: _FakeProvider())
    client.post("/notebooks/mynb/audio", json={"run_id": "pod"})

    client.post("/notebooks/mynb/sources", json={"texts": ["a second source"]})

    assert client.get("/notebooks/mynb").json()["podcast"]["stale"] is True


def test_the_audio_file_endpoint_404s_and_400s_cleanly(client):
    assert client.get("/notebooks/never-generated/audio/file").status_code == 404
    assert client.get("/notebooks/%20%20/audio/file").status_code == 400
