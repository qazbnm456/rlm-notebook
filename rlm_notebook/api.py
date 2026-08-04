"""The HTTP API — an ADDITIONAL surface over the same notebooks `cli.py` drives, not a replacement
for it. Every endpoint that runs an `RLMTask` does so in an isolated subprocess (`runner.py`)
rather than in-process, so concurrent requests can't block each other and a long-running or stuck
request can be reliably cancelled (`killpg` on the whole process group) — see CLAUDE.md's
execution-model invariant. `cli.py`'s synchronous in-process invocation is completely unaffected.

Endpoints: `GET /notebooks` (list), `POST /notebooks/{id}/sources` (create/extend — URLs and/or
pasted text), `POST /notebooks/{id}/sources/upload` (a `.pdf`/`.txt`/`.md` file's raw bytes),
`GET /notebooks/{id}`, `GET /notebooks/{id}/sources/{source_id}` (one source's full text, every
block — the web UI's source viewer), `POST /notebooks/{id}/notes` (create a note),
`DELETE /notebooks/{id}/notes/{note_id}`, `POST /notebooks/{id}/notes/{note_id}/promote` (turn a
note into a real source), `POST /notebooks/{id}/ask`, `POST /notebooks/{id}/guide/{kind}`,
`POST /notebooks/{id}/audio`, `POST /notebooks/{id}/cancel`,
`GET /notebooks/{id}/runs/{run_id}/stream` (live reasoning-trace SSE), and
`GET /notebooks/{id}/runs/{run_id}/citation-turn` (a citation's trace-turn lookup). `/audio` is two
host-side steps, not one: `GeneratePodcastScript` runs in the same isolated subprocess `ask`/`guide`
already use, and TTS synthesis (`tts.py`) runs AFTER that subprocess returns, in-process here — see
`audio()`'s own docstring for why that split is safe and doesn't touch `worker.py`/`runner.py`
(`docs/design/web-ui-blueprint.md`'s Phase 2 addendum has the full reasoning). No audio is ever
persisted to disk past one request — no file-serving endpoint, no retention policy needed.
`/sources/upload` never accepts a local-path STRING (invariant 26 stays exactly as strict) — only
opaque bytes the caller already had, plus a claimed filename used for kind detection and display.

`ask`/`guide`/`audio` all accept an optional client-supplied `run_id` (a `RunOptions` body field) —
the CLIENT picks the run id, not the server, so it can open the trace stream before/alongside firing
the request that will populate it. `_run_isolated` exclusively creates the trace file before
spawning the subprocess (a hard uniqueness gate, mapped to a 409 on collision — see
`docs/design/web-ui-blueprint.md`'s Phase 3 addendum P3.1 for why this is a real, not merely
unlikely, concern once a client partly controls the id). See CLAUDE.md invariant 29 for why a
reasoning-trace SSE endpoint was originally deferred as unbuildable, and what changed.

This module also serves the web UI (`rlm_notebook/web/`, a zero-build static HTML/CSS/JS app) at
`/`, mounted AFTER every API route below so the API always wins on a path collision.

**This API has NO authentication or authorization of any kind** (CLAUDE.md invariant 25) — any
caller can create/extend/query/ask/cancel any `notebook_id`. It is meant for local/trusted-network
use only (the same posture ctx-distillery's studio takes); do not expose it to an untrusted network
without adding auth first, which this slice does not attempt. The trace stream and citation-turn
lookup endpoints are a MATERIALLY DIFFERENT exposure than every other endpoint here — unlike
`GET /notebooks/{id}` (metadata only) or `ask`/`guide` (model-authored prose and short citation
quotes), a trace can contain full ingested source text the model echoed while reading it. Treat
this as a sharper version of the same no-auth posture, not a new category of risk this project
hasn't already accepted, but never let documentation imply the trace endpoints are as low-exposure
as the rest.

Run it with: `uvicorn rlm_notebook.api:app` (needs the `api` extra: `uv sync --extra api`).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from . import runner
from .audio import GeneratePodcastScript
from .citations import verify_citations
from .config import NotebookConfig, max_upload_bytes
from .corpus import CorpusTooLargeError
from .guide import GenerateFAQ, GenerateKeyInsight, GenerateSummary, GenerateTimeline
from .ingest import ingest_pasted_text, ingest_uploaded_file, is_url, with_injection_flags
from .notebook import (
    add_note,
    corpus_of,
    delete_note,
    existing_origins,
    extend_with_sources,
    history_text,
    list_notebook_summaries,
    load_notebook,
    load_or_create,
    promote_note,
    save_notebook,
    slug,
)
from .parsers.web import FetchError
from .schema import (
    FAQ,
    Answer,
    ChatTurn,
    Citation,
    KeyInsight,
    Notebook,
    PodcastScript,
    Summary,
    Timeline,
)
from .task import AnswerQuestion
from .tts import TTSError, get_tts_provider

#: Same registry `cli.py` keeps (`_GUIDE_TASKS`) — kept as a SEPARATE copy rather than imported
#: from `cli.py`, since `api.py` must not depend on `cli.py` (see `ingest.py`'s docstring for why
#: the two entry points share `ingest.py`/`notebook.py` instead of one depending on the other).
_GUIDE_TASKS: dict[str, tuple[type, type]] = {
    "summary": (GenerateSummary, Summary),
    "faq": (GenerateFAQ, FAQ),
    "timeline": (GenerateTimeline, Timeline),
    "insight": (GenerateKeyInsight, KeyInsight),
}

#: Where subprocess runs record their trace — same directory `cli.py`'s live-run docs already
#: point at (see README/.env.example), just used here instead of left implicit.
_TRACE_DIR = Path("traces")

app = FastAPI(title="rlm-notebook API", description=__doc__)

#: In-flight runs, keyed by notebook id — a SINGLE-PROCESS in-memory map, and ONE SLOT per
#: notebook id. Two known, documented limitations (CLAUDE.md invariant 23), neither a silent bug:
#: (1) running `uvicorn` with more than one worker process gives each its own copy of this dict,
#: so `/cancel` only reaches whichever worker happens to hold the request; (2) two concurrent
#: requests against the SAME notebook id share one slot — the second overwrites the first's entry,
#: so `/cancel` can only ever reach the MOST RECENT of the two, and the first can't be cancelled
#: through this API at all (it still finishes or times out on its own). Verified this is not a
#: race in the overwrite/cleanup itself — each request's `finally` only clears its OWN entry (the
#: `is run` identity check below) — the limitation is purely "one cancellable slot per notebook
#: id," not a corruption risk. A per-run-id (rather than per-notebook-id) registry would remove
#: this limitation; deferred, not implemented here.
_ACTIVE_RUNS: dict[str, runner.Run] = {}

#: A SEPARATE, run-id-keyed map of in-flight subprocesses — deliberately NOT reused from
#: `_ACTIVE_RUNS` above. `stream_run`'s cancelled-run liveness check needs a per-RUN signal, and
#: `_ACTIVE_RUNS`'s single-slot-per-NOTEBOOK-id semantics would misfire: a second concurrent
#: request on the same notebook overwrites `_ACTIVE_RUNS`'s entry, which would make the FIRST run's
#: stream falsely conclude it was cancelled the moment a second one starts (found during this
#: phase's own pre-implementation audit). Keyed by the run id itself, which `_run_isolated`'s own
#: exclusive-create gate (below) guarantees is unique — two entries here can never collide.
_RUN_PROCESSES: dict[str, asyncio.subprocess.Process] = {}

#: How the trace-stream endpoint paces itself — see `_tail_trace_events`.
_TRACE_POLL_INTERVAL = 0.2
_TRACE_FILE_WAIT_GRACE = 5.0


def _dotted(cls: type) -> str:
    return f"{cls.__module__}:{cls.__qualname__}"


def _config() -> NotebookConfig:
    """`NotebookConfig.from_env()` raises `SystemExit` on a missing/invalid `RN_*` var — correct
    for a CLI invocation (`cli.py` lets it propagate and exit the process) but wrong for a request
    handler, where `SystemExit` would otherwise escape as an unhandled server error instead of a
    clean HTTP response. Converts it to a 500 with the same message."""
    try:
        return NotebookConfig.from_env()
    except SystemExit as exc:
        raise HTTPException(500, f"server misconfigured: {exc}") from exc


def _tts_provider(config: NotebookConfig):
    """Mirrors `_config()`'s `SystemExit`-to-500 shape for the analogous `TTSError` case: an
    unknown/misconfigured `RN_TTS_PROVIDER` is a SERVER misconfiguration (the value comes from the
    environment, not the request body), resolved BEFORE `audio()` runs the expensive model call,
    not after — the same ordering CLAUDE.md invariant 19 already requires of `cli._cmd_audio`, after
    an earlier independent review found the reverse order wasted a real model call on a bad value."""
    try:
        return get_tts_provider(config.tts_provider)
    except TTSError as exc:
        raise HTTPException(500, f"server misconfigured: {exc}") from exc


def _invalid_notebook_id(notebook_id: str, exc: ValueError) -> HTTPException:
    """`notebook.notebook_path` raises `ValueError` when `slug(notebook_id)` reduces to an empty
    token (e.g. `notebook_id` is all punctuation, like `"!!!"`) — a client input error, not a
    missing-notebook 404 or a corrupted-file 409. Found by an independent review: every endpoint
    that reaches `load_notebook`/`load_or_create` used to catch `ValidationError` only, so this
    `ValueError` escaped as an unhandled 500 instead of a clean 4xx — reproduced against a live
    `TestClient` request (`POST /notebooks/!!!/ask` etc.) before this fix, on all four endpoints
    that touch a notebook by id."""
    return HTTPException(400, f"invalid notebook id {notebook_id!r}: {exc}")


def _load_notebook_or_404(notebook_id: str) -> Notebook:
    """`ask`/`guide` operate on an EXISTING notebook only — unlike `add_sources`, which creates one
    on demand, there's nothing useful to run a question or a guide artifact against until sources
    have actually been added."""
    try:
        notebook = load_notebook(notebook_id)
    except ValidationError as exc:
        raise HTTPException(
            409,
            f"notebooks/{notebook_id}.json exists but is not a valid notebook file "
            f"({type(exc).__name__}) — fix or remove it by hand before continuing.",
        ) from exc
    except ValueError as exc:
        raise _invalid_notebook_id(notebook_id, exc) from exc
    if notebook is None:
        raise HTTPException(404, f"no notebook {notebook_id!r} — POST sources to it first")
    return notebook


class CitationResponse(BaseModel):
    source_id: str
    locator: str
    quote: str
    verified: bool
    reason: str | None = None


def _citation_responses(citations: list[Citation], corpus) -> list[CitationResponse]:
    return [
        CitationResponse(
            source_id=v.citation.source_id,
            locator=v.citation.locator,
            quote=v.citation.quote,
            verified=v.verified,
            reason=v.reason,
        )
        for v in verify_citations(citations, corpus)
    ]


class NotebookSummary(BaseModel):
    id: str
    source_count: int
    turn_count: int


class NotebookListResponse(BaseModel):
    notebooks: list[NotebookSummary]
    unreadable: list[str] = []


@app.get("/notebooks", response_model=NotebookListResponse)
async def list_notebooks() -> NotebookListResponse:
    """Every notebook that exists, for the web UI's notebook switcher. Reads the same
    `notebook.DEFAULT_NOTEBOOKS_DIR` constant every other notebook operation already uses — there is
    no separate config surface for this (checked: `NotebookConfig` has no notebooks-directory field
    at all; see `docs/design/web-ui-blueprint.md`'s audit note). Reports each notebook's own `id`
    field, never the slugged filename stem (`notebook.slug()` is lossy, so the two can differ for
    the same file). A corrupted notebook file is listed under `unreadable` by its filename stem
    rather than silently dropped or breaking the whole listing."""
    notebooks, unreadable = list_notebook_summaries()
    return NotebookListResponse(
        notebooks=[
            NotebookSummary(id=nb.id, source_count=len(nb.sources), turn_count=len(nb.turns))
            for nb in notebooks
        ],
        unreadable=unreadable,
    )


class SourcesRequest(BaseModel):
    sources: list[str] = []
    #: Pasted text, ingested via `ingest.ingest_pasted_text` — a content-derived origin, never a
    #: path or URL, so this never touches invariant 26's local-path restriction at all.
    texts: list[str] = []


class ChatTurnResponse(BaseModel):
    question: str
    answer: str
    citations: list[CitationResponse]
    run_id: str | None = None


class NoteResponse(BaseModel):
    id: str
    text: str


class NotebookResponse(BaseModel):
    id: str
    sources: list[dict]
    turns: list[ChatTurnResponse]
    notes: list[NoteResponse]


def _notebook_response(notebook: Notebook) -> NotebookResponse:
    """Includes full turn history, not just a count — the web UI's Chat panel (blueprint §1) needs
    to render a re-opened notebook's past turns, not just ones asked during the current session.
    Every historical turn's citations are re-verified against the CURRENT corpus at read time, same
    as a brand-new answer (CLAUDE.md invariant 11: history is never itself a trusted source of
    facts, and a citation is verified fresh every time regardless of what a past turn recorded).
    Also includes `notes` — every endpoint that returns a notebook gets them for free from this ONE
    conversion function, no per-endpoint change needed (blueprint's Notes addendum)."""
    corpus = corpus_of(notebook)
    return NotebookResponse(
        id=notebook.id,
        sources=[
            {"id": s.id, "kind": s.kind, "origin": s.origin, "flags": s.flags}
            for s in notebook.sources
        ],
        turns=[
            ChatTurnResponse(
                question=t.question,
                answer=t.answer.text,
                citations=_citation_responses(t.answer.citations, corpus),
                run_id=t.run_id,
            )
            for t in notebook.turns
        ],
        notes=[NoteResponse(id=n.id, text=n.text) for n in notebook.notes],
    )


@app.post("/notebooks/{notebook_id}/sources", response_model=NotebookResponse)
async def add_sources(notebook_id: str, body: SourcesRequest) -> NotebookResponse:
    """Create `notebook_id` if it doesn't exist yet, and ingest+merge `body.sources` into it
    (deduped by origin — see `notebook.extend_with_sources`). Always persists, unlike `cli.py`'s
    ephemeral-by-default `ask`/`guide`/`audio`: an API caller has no other way to keep a notebook
    around between requests.

    **Only http(s) URLs are accepted here — NOT local file paths**, unlike `cli.py`'s `--source`
    (CLAUDE.md invariant 26). `ingest.ingest_one` treats any non-URL string as a path on the
    machine running this process and reads it with no allowlist or directory boundary — correct
    for a CLI whose operator already trusts their own machine, an arbitrary-file-read
    vulnerability for an unauthenticated network endpoint (found and reproduced by an independent
    review: `POST {"sources": ["/etc/passwd"]}` read the file and a mocked `ask` echoed its
    contents back through a citation that passed verification). Local files still only reach a
    notebook through the CLI."""
    non_urls = [s for s in body.sources if not is_url(s)]
    if non_urls:
        raise HTTPException(
            422,
            f"the API only accepts http(s) URLs as sources, not local file paths — rejected: "
            f"{non_urls!r}. Use the CLI (`rlm-notebook ask --source <path>`) to add a local file.",
        )
    blank_texts = [i for i, t in enumerate(body.texts) if not t.strip()]
    if blank_texts:
        raise HTTPException(
            422, f"each entry in 'texts' must be non-empty pasted text (blank at index {blank_texts})"
        )
    try:
        notebook = load_or_create(notebook_id)
    except ValidationError as exc:
        raise HTTPException(
            409,
            f"notebooks/{notebook_id}.json exists but is not a valid notebook file "
            f"({type(exc).__name__}) — fix or remove it by hand before continuing.",
        ) from exc
    except ValueError as exc:
        raise _invalid_notebook_id(notebook_id, exc) from exc
    try:
        extend_with_sources(notebook, body.sources)
    except (FetchError, ValueError, OSError) as exc:
        raise HTTPException(422, f"could not ingest a source: {type(exc).__name__}: {exc}") from exc

    # Pasted text: same same-call-duplicate-guard discipline `ingest_new` already established for
    # URLs/paths (a `seen` set that grows as this loop runs, not just a static starting snapshot).
    seen = existing_origins(notebook)
    for text in body.texts:
        source = ingest_pasted_text(text.strip(), source_id=f"s{len(notebook.sources) + 1}")
        if source.origin in seen:
            continue
        seen.add(source.origin)
        notebook.sources.append(with_injection_flags(source))

    save_notebook(notebook)
    return _notebook_response(notebook)


class NoteRequest(BaseModel):
    text: str


@app.post("/notebooks/{notebook_id}/notes", response_model=NotebookResponse)
async def add_note_endpoint(notebook_id: str, body: NoteRequest) -> NotebookResponse:
    """Create a note — manual, or a copy of a past Chat answer's text (the web UI's "Save as note"
    button). Uses `load_or_create` like `add_sources`: a brand-new notebook can start life by
    adding a note, same as it can by adding a source."""
    try:
        notebook = load_or_create(notebook_id)
    except ValidationError as exc:
        raise HTTPException(
            409,
            f"notebooks/{notebook_id}.json exists but is not a valid notebook file "
            f"({type(exc).__name__}) — fix or remove it by hand before continuing.",
        ) from exc
    except ValueError as exc:
        raise _invalid_notebook_id(notebook_id, exc) from exc
    try:
        add_note(notebook, body.text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    save_notebook(notebook)
    return _notebook_response(notebook)


@app.delete("/notebooks/{notebook_id}/notes/{note_id}", response_model=NotebookResponse)
async def delete_note_endpoint(notebook_id: str, note_id: str) -> NotebookResponse:
    """Delete a note by id — an existing note can only be deleted from an EXISTING notebook (no
    `load_or_create` here, matching `ask`/`guide`'s existing-notebook-only precedent)."""
    notebook = _load_notebook_or_404(notebook_id)
    try:
        delete_note(notebook, note_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    save_notebook(notebook)
    return _notebook_response(notebook)


@app.post("/notebooks/{notebook_id}/notes/{note_id}/promote", response_model=NotebookResponse)
async def promote_note_endpoint(notebook_id: str, note_id: str) -> NotebookResponse:
    """Turn a note into a real, independently-citable source (`notebook.promote_note`) — reuses the
    same pasted-text ingestion path `add_sources`'s `texts` field already goes through. Returns the
    updated `NotebookResponse` either way (whether or not a new source was actually appended —
    ground truth is already visible in the returned `sources`/`notes` lists, no separate "did it
    dedupe" flag needed)."""
    notebook = _load_notebook_or_404(notebook_id)
    try:
        promote_note(notebook, note_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    save_notebook(notebook)
    return _notebook_response(notebook)


@app.post("/notebooks/{notebook_id}/sources/upload", response_model=NotebookResponse)
async def upload_source(notebook_id: str, request: Request) -> NotebookResponse:
    """Upload a file's raw bytes (`.pdf`/`.txt`/`.md`) as a new source — safe unlike a local-path
    string (invariant 26): the server only ever receives opaque bytes the caller already had, never
    a path it reads from its own filesystem.

    **Size-cap enforcement, empirically verified before landing this** (a prior draft's plan didn't
    actually enforce anything — see `docs/design/web-ui-blueprint.md`'s "Post-launch addendum" for
    the full audit finding). Deliberately does NOT declare `file: UploadFile = File(...)` as a
    parameter — FastAPI parses the ENTIRE multipart body itself, inside its own request-handling
    code, BEFORE any handler with a `File`/`Form` parameter ever runs, for ANY route shaped that
    way, regardless of `Content-Length` — confirmed live against the installed version. Taking
    `request: Request` instead means THIS code decides when (or whether) to parse the body at all:
    `Content-Length` is checked FIRST, and `request.form()` is only ever called once that check
    already cleared the cap. A missing `Content-Length` (chunked transfer encoding) is refused
    outright (411) rather than accepted with a disclosed gap — there's no safe way to bound an
    unknown-length body before reading it, so this project doesn't try to."""
    cap = max_upload_bytes()
    content_length = request.headers.get("content-length")
    if content_length is None:
        raise HTTPException(411, "Content-Length header is required for file uploads")
    try:
        declared_size = int(content_length)
    except ValueError:
        raise HTTPException(400, f"invalid Content-Length header {content_length!r}")
    if declared_size > cap:
        raise HTTPException(413, f"upload declares {declared_size} bytes, exceeding the {cap}-byte limit")

    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "filename"):
        raise HTTPException(422, "expected a multipart 'file' field")
    data = await upload.read()
    if len(data) > cap:
        raise HTTPException(413, f"upload is {len(data)} bytes, exceeding the {cap}-byte limit")
    filename = upload.filename or "upload"

    try:
        notebook = load_or_create(notebook_id)
    except ValidationError as exc:
        raise HTTPException(
            409,
            f"notebooks/{notebook_id}.json exists but is not a valid notebook file "
            f"({type(exc).__name__}) — fix or remove it by hand before continuing.",
        ) from exc
    except ValueError as exc:
        raise _invalid_notebook_id(notebook_id, exc) from exc

    if filename in existing_origins(notebook):
        return _notebook_response(notebook)  # no-op — same dedupe semantics as a re-added path/URL

    try:
        source = ingest_uploaded_file(data, filename, source_id=f"s{len(notebook.sources) + 1}")
    except ValueError as exc:
        raise HTTPException(422, f"could not ingest {filename!r}: {exc}") from exc

    notebook.sources.append(with_injection_flags(source))
    save_notebook(notebook)
    return _notebook_response(notebook)


@app.get("/notebooks/{notebook_id}", response_model=NotebookResponse)
async def get_notebook(notebook_id: str) -> NotebookResponse:
    notebook = _load_notebook_or_404(notebook_id)
    return _notebook_response(notebook)


class SourceBlockResponse(BaseModel):
    locator: str
    text: str


class SourceDetailResponse(BaseModel):
    id: str
    kind: str
    origin: str
    flags: list[str]
    blocks: list[SourceBlockResponse]


@app.get("/notebooks/{notebook_id}/sources/{source_id}", response_model=SourceDetailResponse)
async def get_source(notebook_id: str, source_id: str) -> SourceDetailResponse:
    """One source's full text, every block — the web UI's source viewer (blueprint's "Post-launch
    addendum 2") needs this to close NotebookLM's most basic loop: click a citation, see the
    highlighted original passage. Before this endpoint, no caller could read more of a source than
    the short `quote` strings a citation happens to include.

    **Materially different exposure than every other endpoint here except the trace stream/
    citation-turn lookup, said explicitly rather than folded silently into "same as everything
    else"** (CLAUDE.md invariant 25's no-auth posture already covers this in spirit — the model
    itself already has the whole corpus — but the ENDPOINT SURFACE returning full source text is
    new). Reuses `corpus.Corpus.get`, the same lookup `citations.py` already performs on every
    `ask`/`guide` request, rather than a second hand-rolled scan."""
    notebook = _load_notebook_or_404(notebook_id)
    source = corpus_of(notebook).get(source_id)
    if source is None:
        raise HTTPException(404, f"no source {source_id!r} in notebook {notebook_id!r}")
    return SourceDetailResponse(
        id=source.id,
        kind=source.kind,
        origin=source.origin,
        flags=source.flags,
        blocks=[SourceBlockResponse(locator=b.locator, text=b.text) for b in source.blocks],
    )


class RunOptions(BaseModel):
    """Shared optional body for every endpoint that runs an isolated RLMTask — a CLIENT-supplied
    run id, so the caller can open `GET .../runs/{run_id}/stream` before or alongside firing the
    request that will populate it (see `docs/design/web-ui-blueprint.md`'s Phase 3 addendum P3.1).
    `None` (the default — an absent body binds to this) reproduces today's exact behavior: a
    server-generated id, invisible to the caller until the response arrives."""

    run_id: str | None = None


#: A single shared default instance, rather than `= RunOptions()` inline at each call site —
#: `guide`/`audio` never had a body before this phase, and a fresh literal default expression in
#: every function signature is flagged (correctly, in general) as a mutable-default footgun; this
#: is read-only in practice (nothing here ever mutates `body`), but naming one module-level
#: instance is the idiomatic way to say so.
_NO_RUN_OPTIONS = RunOptions()


class AskRequest(RunOptions):
    question: str


class AskResponse(BaseModel):
    text: str
    citations: list[CitationResponse]


def _derive_run_id(notebook_id: str, client_token: str | None) -> str:
    """The run id THIS call will use. A client-supplied token is sanitized through the same
    whitelist `notebook.slug()` already uses for notebook ids (it becomes a filename component too)
    and prefixed with `notebook_id` — never the client's raw value alone, so two different
    notebooks' clients can never collide on a shared `traces/` directory. When no token is given,
    falls back to today's server-random scheme unchanged. Either way, `_run_isolated`'s own
    exclusive-create gate is what actually ENFORCES uniqueness — this function only picks the
    candidate id, it doesn't guarantee it's free."""
    token = slug(client_token) if client_token else uuid.uuid4().hex[:8]
    return f"{notebook_id}-{token}"


async def _run_isolated(
    notebook_id: str, dotted_task: str, kwargs: dict, config: NotebookConfig, run_id: str
) -> dict:
    """Start an isolated subprocess run for `notebook_id` under the given `run_id`, track it in
    `_ACTIVE_RUNS`/`_RUN_PROCESSES` so `POST .../cancel` and `GET .../stream` can each reach it, and
    wait for its result — translating `runner.RunError` into a 502 (the run failed/crashed/timed
    out) rather than an uncaught exception.

    **Exclusive-create gate, added for Phase 3**: `run_id` may now be partly client-chosen
    (`_derive_run_id`), so this opens `traces/{run_id}.jsonl` EXCLUSIVELY before spawning anything —
    `TraceRecorder`'s own lock is process-local and provides NO cross-process serialization, so two
    concurrent requests landing on the same run_id (two browser tabs, a retried request — nothing
    prevents this, invariant 25) would otherwise have two independent subprocesses append
    interleaved, duplicate-`step_id` events to one file. A collision raises `FileExistsError`,
    mapped to 409, telling the client to pick a fresh token. `_TRACE_DIR.mkdir` happens HERE, before
    the gate — `runner.start_run` also creates the directory, but only after the point this gate
    needs it to already exist, so relying on that would raise `FileNotFoundError` (a different,
    unhandled case) on a fresh checkout's very first run. If `runner.start_run` itself then fails
    AFTER the gate already succeeded, the just-reserved (still-empty) file is unlinked before the
    original error propagates — otherwise a failed spawn would permanently occupy that run id, and
    the client's natural retry of the same notebook+token pair would get a false 409 forever
    instead of the real underlying error."""
    _TRACE_DIR.mkdir(parents=True, exist_ok=True)
    trace_path = _TRACE_DIR / f"{run_id}.jsonl"
    try:
        fd = os.open(trace_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        raise HTTPException(409, f"run id {run_id!r} is already in use — retry with a fresh run_id") from None

    try:
        run = await runner.start_run(run_id, _TRACE_DIR, dotted_task, kwargs)
    except Exception:
        trace_path.unlink(missing_ok=True)
        raise

    _ACTIVE_RUNS[notebook_id] = run
    _RUN_PROCESSES[run_id] = run.process
    try:
        return await runner.wait_result(run, timeout=config.run_timeout_seconds)
    except runner.RunError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        # Only clear OUR OWN run — a slow cancel/finish race could otherwise clobber a NEWER run
        # that already replaced this one in _ACTIVE_RUNS for the same notebook_id.
        if _ACTIVE_RUNS.get(notebook_id) is run:
            del _ACTIVE_RUNS[notebook_id]
        _RUN_PROCESSES.pop(run_id, None)


@app.post("/notebooks/{notebook_id}/ask", response_model=AskResponse)
async def ask(notebook_id: str, body: AskRequest) -> AskResponse:
    notebook = _load_notebook_or_404(notebook_id)
    corpus = corpus_of(notebook)
    config = _config()
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc

    run_id = _derive_run_id(notebook_id, body.run_id)
    result = await _run_isolated(
        notebook_id,
        _dotted(AnswerQuestion),
        {"sources": blob, "history": history_text(notebook), "question": body.question},
        config,
        run_id,
    )
    answer = Answer.model_validate(result)

    notebook.turns.append(ChatTurn(question=body.question, answer=answer, run_id=run_id))
    save_notebook(notebook)

    return AskResponse(text=answer.text, citations=_citation_responses(answer.citations, corpus))


@app.post("/notebooks/{notebook_id}/guide/{kind}")
async def guide(notebook_id: str, kind: str, body: RunOptions = _NO_RUN_OPTIONS) -> dict:
    if kind not in _GUIDE_TASKS:
        raise HTTPException(404, f"unknown guide kind {kind!r}; known: {sorted(_GUIDE_TASKS)}")
    notebook = _load_notebook_or_404(notebook_id)
    corpus = corpus_of(notebook)
    config = _config()
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc

    task_cls, output_model = _GUIDE_TASKS[kind]
    run_id = _derive_run_id(notebook_id, body.run_id)
    result = await _run_isolated(notebook_id, _dotted(task_cls), {"sources": blob}, config, run_id)
    parsed = output_model.model_validate(result)

    if kind in ("summary", "insight"):
        return {"text": parsed.text, "citations": _citation_responses(parsed.citations, corpus)}
    if kind == "faq":
        return {
            "items": [
                {
                    "question": item.question,
                    "answer": item.answer,
                    "citations": _citation_responses(item.citations, corpus),
                }
                for item in parsed.items
            ]
        }
    # "timeline"
    return {
        "events": [
            {
                "when": event.when,
                "description": event.description,
                "citations": _citation_responses(event.citations, corpus),
            }
            for event in parsed.events
        ]
    }


class AudioUtteranceResponse(BaseModel):
    speaker: str
    text: str
    citations: list[CitationResponse]


class AudioResponse(BaseModel):
    utterances: list[AudioUtteranceResponse]
    audio_base64: str | None = None


@app.post("/notebooks/{notebook_id}/audio", response_model=AudioResponse)
async def audio(notebook_id: str, body: RunOptions = _NO_RUN_OPTIONS) -> AudioResponse:
    """Generate a two-host podcast script grounded in `notebook_id`'s sources and synthesize it to
    audio. Two host-side steps, not one (`docs/design/web-ui-blueprint.md`'s Phase 2 addendum):
    `GeneratePodcastScript` runs in the same isolated subprocess `ask`/`guide` already use — the
    only step that touches `dspy`/`rlm_harness`, and the only one cancellable via
    `POST .../cancel` — then TTS synthesis (`tts.py`) runs AFTER that subprocess returns, IN-PROCESS
    here, since `tts.py` imports neither `dspy` nor `rlm_harness` (same precedent as `api.py` already
    importing the Guide/`AnswerQuestion` RLMTask classes at module load, purely for `_dotted()`'s
    introspection — never calling `.arun()` on them itself; only `worker.py` does).

    `EdgeTTSProvider.synthesize()` is a SYNC method that internally calls `asyncio.run(...)`, which
    raises if invoked from a running event loop — this handler's own. Dispatched through
    `asyncio.to_thread` instead (a fresh OS thread has no event loop of its own, so `asyncio.run()`
    inside it never collides with this handler's loop) — `tts.py`'s own docstring already flagged
    this exact scenario as the CALLER's responsibility to route around, not something `synthesize()`
    itself should change.

    No audio is ever persisted past this one request — synthesis writes to a temp file, the bytes
    are read back and base64-encoded into the response, and the temp file is deleted whether
    synthesis succeeded or failed (the `try`/`finally` wraps the `synthesize()` call itself, not
    just the read-back — a synthesis failure after the file already exists on disk must not leak
    it). There is deliberately no `GET .../audio/{run_id}.mp3`-style file-serving endpoint and no
    retention policy to get right, unlike the reasoning-trace files Phase 3 left unresolved.

    **Known, stated limitation**: only the script-generation step is cancellable through
    `POST .../cancel` — `_run_isolated`'s `finally` clears this notebook's `_ACTIVE_RUNS` entry the
    moment the subprocess returns, so by the time synthesis begins there is nothing left to cancel.
    A stuck or slow synthesis call blocks this request until it finishes or the client gives up;
    `cli._cmd_audio` has no cancellation story for this phase either, so this isn't a regression,
    but it IS new that an API request's total latency now includes a real network TTS call
    serialized after an RLM run."""
    notebook = _load_notebook_or_404(notebook_id)
    corpus = corpus_of(notebook)
    config = _config()
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc

    provider = _tts_provider(config)

    run_id = _derive_run_id(notebook_id, body.run_id)
    result = await _run_isolated(
        notebook_id, _dotted(GeneratePodcastScript), {"sources": blob}, config, run_id
    )
    script = PodcastScript.model_validate(result)

    utterances = [
        AudioUtteranceResponse(
            speaker=u.speaker, text=u.text, citations=_citation_responses(u.citations, corpus)
        )
        for u in script.utterances
    ]

    if not script.utterances:
        # A source with nothing worth discussing is a legitimate output (audio.py's instructions
        # explicitly allow it) — same "don't try to synthesize silence" handling cli._cmd_audio
        # already has, rather than calling synthesize() and getting a TTSError for an empty script.
        return AudioResponse(utterances=[], audio_base64=None)

    voice_map = {"host_a": config.tts_voice_host_a, "host_b": config.tts_voice_host_b}
    fd, tmp_name = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        await asyncio.to_thread(provider.synthesize, script, voice_map, tmp_path)
        audio_bytes = tmp_path.read_bytes()
    except TTSError as exc:
        raise HTTPException(
            502, f"podcast script generated, but audio synthesis failed: {exc}"
        ) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return AudioResponse(
        utterances=utterances, audio_base64=base64.b64encode(audio_bytes).decode("ascii")
    )


@app.post("/notebooks/{notebook_id}/cancel")
async def cancel(notebook_id: str) -> dict:
    run = _ACTIVE_RUNS.get(notebook_id)
    if run is None:
        raise HTTPException(404, f"no in-flight run for notebook {notebook_id!r}")
    run.cancel()
    return {"cancelled": run.run_id}


def _translate_trace_event(event: dict) -> dict:
    """Raw `trace/v1` event -> a small, stable, product-facing shape for the web UI's live ticker.
    Kept in ONE function, the same discipline the sibling studios' own `mapper.to_event` already
    uses, so the raw-to-product translation lives in one place rather than being duplicated at
    every call site. Deliberately terse — the frontend owns presentation, this just names what
    kind of thing happened."""
    etype = event.get("type")
    payload = event.get("payload") or {}
    step = event.get("step_id")
    if etype == "main_step":
        return {"step": step, "kind": "thinking", "summary": "reasoning about the next step"}
    if etype == "tool_call":
        return {"step": step, "kind": "tool", "summary": f"calling {payload.get('tool', 'a tool')}"}
    if etype == "sub_call":
        return {"step": step, "kind": "escalation", "summary": "consulting a sub-model"}
    if etype == "run_end":
        ok = payload.get("ok")
        return {"step": step, "kind": "done", "summary": "finished" if ok else "finished with an error"}
    return {"step": step, "kind": "other", "summary": etype or "event"}


async def _tail_trace_events(run_id: str):
    """Yields translated event dicts as they appear in `traces/{run_id}.jsonl` — safe to poll while
    a worker subprocess is actively writing it: `TraceRecorder.record()` (rlm-harness) writes exactly
    one complete `json.dumps(event) + "\\n"` per call, flushed immediately, serialized under its
    own lock — verified directly against `rlm_harness/trace.py` during this phase's own
    pre-implementation audit, not assumed. Buffers any trailing partial line so a read that catches
    a write mid-flight never yields a torn line.

    One loop serves BOTH modes: **live tail** (the file is still growing — poll, forward each new
    event, stop at `run_end`) and **replay** (the file already has a `run_end` when this starts —
    the same loop just drains it immediately with no artificial pacing, since pacing-to-feel-live is
    only for a genuinely in-progress run).

    Cancelled-run detection deliberately does NOT reuse `_ACTIVE_RUNS` (see the module-level
    `_RUN_PROCESSES` docstring for why that would misfire under ordinary same-notebook
    concurrency) — it checks `_RUN_PROCESSES` instead, keyed by this exact `run_id`, which
    `_run_isolated`'s own exclusive-create gate guarantees is unique."""
    trace_path = _TRACE_DIR / f"{run_id}.jsonl"

    waited = 0.0
    while not trace_path.exists():
        if waited >= _TRACE_FILE_WAIT_GRACE:
            yield {"step": None, "kind": "not_found", "summary": f"no run {run_id!r} found"}
            return
        await asyncio.sleep(_TRACE_POLL_INTERVAL)
        waited += _TRACE_POLL_INTERVAL

    buffer = ""
    with trace_path.open("r", encoding="utf-8") as fh:
        while True:
            chunk = fh.read()
            if chunk:
                buffer += chunk
                *complete_lines, buffer = buffer.split("\n")
                for line in complete_lines:
                    line = line.strip()
                    if not line:
                        continue
                    event = json.loads(line)
                    yield _translate_trace_event(event)
                    if event.get("type") == "run_end":
                        return
                continue

            process = _RUN_PROCESSES.get(run_id)
            if process is None or process.returncode is not None:
                # The process that was writing this trace has exited (or was never tracked at
                # all) and no `run_end` ever arrived — a `killpg`-cancelled or crashed run.
                # Synthesize a terminal event so the stream reaches "done" instead of hanging,
                # the same fix `ctx-distillery-studio` already documents for the identical
                # failure mode (a hard-killed run whose recorder never reached `__exit__`).
                yield {"step": None, "kind": "done", "summary": "run ended without a final event"}
                return
            await asyncio.sleep(_TRACE_POLL_INTERVAL)


@app.get("/notebooks/{notebook_id}/runs/{run_id}/stream")
async def stream_run(notebook_id: str, run_id: str) -> StreamingResponse:
    """Live reasoning-trace ticker (see `docs/design/web-ui-blueprint.md`'s Phase 3 addendum P3.2).
    `run_id` already encodes `notebook_id`, by construction (`_derive_run_id`) — checked explicitly
    here too (mirroring `citation_turn`'s same check) rather than silently trusting the caller
    passed a matching pair, so a mismatched `notebook_id` can't be used to stream a trace that
    belongs to a different notebook."""

    async def _events():
        if not run_id.startswith(f"{notebook_id}-"):
            yield f"data: {json.dumps({'step': None, 'kind': 'not_found', 'summary': f'run {run_id!r} does not belong to notebook {notebook_id!r}'})}\n\n"
            return
        async for event in _tail_trace_events(run_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")


@app.get("/notebooks/{notebook_id}/runs/{run_id}/citation-turn")
async def citation_turn(notebook_id: str, run_id: str, source_id: str, locator: str) -> dict:
    """Which trace turn (if any) shows the model reading a specific citation's source span (see
    `docs/design/web-ui-blueprint.md`'s Phase 3 addendum P3.3). Searches the ENTIRE serialized
    payload of each event, in step order, for the first one containing the literal marker
    `[[SRC:<source_id>|<locator>]]` — not a fixed field list, which audit round 1 found misses real
    marker occurrences in a `sub_call` event's `input`/`raw`/`processed` fields (a hardcoded
    `reasoning`/`code`/`output` list, right for `main_step`, is simply wrong for `sub_call`).

    **This is a heuristic, not a faithfulness proof** (invariant 5 already establishes citation
    verification cannot make that stronger claim): finding the marker text proves the model's REPL
    saw it at some point, never that this specific occurrence is what the model relied on for the
    citation. A `sub_call`'s `input` field is also truncated to 4000 characters upstream
    (`rlm_harness.sub_lm`) — a marker beyond that point in a long escalation prompt won't be found in
    THAT event, though it may still turn up in another one.

    404s (never crashes) when the trace file doesn't exist at all — `traces/` has no retention
    policy anywhere in this project, so a citation's "view reasoning" link is only as durable as a
    file nobody has committed to keeping; a missing trace degrades this ONE affordance, not the
    rest of the page."""
    if not run_id.startswith(f"{notebook_id}-"):
        raise HTTPException(404, f"run {run_id!r} does not belong to notebook {notebook_id!r}")
    trace_path = _TRACE_DIR / f"{run_id}.jsonl"
    if not trace_path.exists():
        raise HTTPException(404, f"no trace found for run {run_id!r}")

    marker = f"[[SRC:{source_id}|{locator}]]"
    with trace_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            payload = event.get("payload") or {}
            if marker in json.dumps(payload, ensure_ascii=False):
                return {"step_id": event.get("step_id"), "type": event.get("type"), "payload": payload}
    raise HTTPException(404, f"marker for source {source_id!r} locator {locator!r} not found in this trace")


#: The web UI, mounted LAST so every explicit API route above wins a path collision — Starlette
#: matches routes in registration order, and a `Mount` is just another route in that same sequence.
#: `html=True` serves `index.html` for `/` and any other directory-shaped request, matching how a
#: single-page static app is normally served. Resolved relative to the INSTALLED PACKAGE directory
#: (`Path(__file__).parent`), not the process's current working directory — the same reasoning
#: `docs/design/web-ui-blueprint.md`'s audit note gives for why these assets live under
#: `rlm_notebook/web/` rather than a top-level `web/`: a wheel installed elsewhere on disk must still
#: find them.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")
