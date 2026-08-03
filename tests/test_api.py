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
from typing import ClassVar

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
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "hello uploaded pdf")
    data = doc.tobytes()
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


def test_upload_source_reports_400_not_500_on_a_notebook_id_that_reduces_to_an_empty_slug(client):
    resp = client.post(
        "/notebooks/!!!/sources/upload",
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
            full = {"schema": "rlm-kit/trace/v1", "run_id": run_id, "step_id": i, "ts": 0.0, **event}
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
