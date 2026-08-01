"""The HTTP API — an ADDITIONAL surface over the same notebooks `cli.py` drives, not a replacement
for it. Every endpoint that runs an `RLMTask` does so in an isolated subprocess (`runner.py`)
rather than in-process, so concurrent requests can't block each other and a long-running or stuck
request can be reliably cancelled (`killpg` on the whole process group) — see CLAUDE.md's
execution-model invariant. `cli.py`'s synchronous in-process invocation is completely unaffected.

Endpoints: `POST /notebooks/{id}/sources` (create/extend), `GET /notebooks/{id}`,
`POST /notebooks/{id}/ask`, `POST /notebooks/{id}/guide/{kind}`, `POST /notebooks/{id}/cancel`.
No `/audio` endpoint yet (deferred — see CHANGELOG): Audio Overview synthesis is slower and
heavier than the others, and wiring its own subprocess-run bookkeeping through this same
`_run_isolated` path deserved its own slice rather than being rushed into this one. No SSE/progress
streaming either — a request blocks until its subprocess finishes or the configured timeout hits;
also deferred (see CHANGELOG).

Run it with: `uvicorn rlm_notebook.api:app` (needs the `api` extra: `uv sync --extra api`).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from . import runner
from .citations import verify_citations
from .config import NotebookConfig
from .corpus import CorpusTooLargeError
from .guide import GenerateFAQ, GenerateKeyInsight, GenerateSummary, GenerateTimeline
from .notebook import (
    corpus_of,
    extend_with_sources,
    history_text,
    load_notebook,
    load_or_create,
    save_notebook,
)
from .parsers.web import FetchError
from .schema import FAQ, Answer, ChatTurn, Citation, KeyInsight, Notebook, Summary, Timeline
from .task import AnswerQuestion

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

#: In-flight runs, keyed by notebook id — a SINGLE-PROCESS in-memory map. CLAUDE.md's Scope note:
#: no multi-worker/multi-process deployment story yet; running `uvicorn` with more than one worker
#: would give each worker its own copy of this dict, and `/cancel` would only reach whichever
#: worker happens to hold the request — a known limitation of this slice, not a silent bug.
_ACTIVE_RUNS: dict[str, runner.Run] = {}


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
    if notebook is None:
        raise HTTPException(404, f"no notebook {notebook_id!r} — POST sources to it first")
    return notebook


class SourcesRequest(BaseModel):
    sources: list[str] = []


class NotebookResponse(BaseModel):
    id: str
    sources: list[dict]
    turn_count: int


def _notebook_response(notebook: Notebook) -> NotebookResponse:
    return NotebookResponse(
        id=notebook.id,
        sources=[
            {"id": s.id, "kind": s.kind, "origin": s.origin, "flags": s.flags}
            for s in notebook.sources
        ],
        turn_count=len(notebook.turns),
    )


@app.post("/notebooks/{notebook_id}/sources", response_model=NotebookResponse)
async def add_sources(notebook_id: str, body: SourcesRequest) -> NotebookResponse:
    """Create `notebook_id` if it doesn't exist yet, and ingest+merge `body.sources` into it
    (deduped by origin — see `notebook.extend_with_sources`). Always persists, unlike `cli.py`'s
    ephemeral-by-default `ask`/`guide`/`audio`: an API caller has no other way to keep a notebook
    around between requests."""
    try:
        notebook = load_or_create(notebook_id)
    except ValidationError as exc:
        raise HTTPException(
            409,
            f"notebooks/{notebook_id}.json exists but is not a valid notebook file "
            f"({type(exc).__name__}) — fix or remove it by hand before continuing.",
        ) from exc
    try:
        extend_with_sources(notebook, body.sources)
    except (FetchError, ValueError, OSError) as exc:
        raise HTTPException(422, f"could not ingest a source: {type(exc).__name__}: {exc}") from exc
    save_notebook(notebook)
    return _notebook_response(notebook)


@app.get("/notebooks/{notebook_id}", response_model=NotebookResponse)
async def get_notebook(notebook_id: str) -> NotebookResponse:
    notebook = _load_notebook_or_404(notebook_id)
    return _notebook_response(notebook)


class AskRequest(BaseModel):
    question: str


class CitationResponse(BaseModel):
    source_id: str
    locator: str
    quote: str
    verified: bool
    reason: str | None = None


class AskResponse(BaseModel):
    text: str
    citations: list[CitationResponse]


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


async def _run_isolated(notebook_id: str, dotted_task: str, kwargs: dict, config: NotebookConfig) -> dict:
    """Start an isolated subprocess run for `notebook_id`, track it in `_ACTIVE_RUNS` so
    `POST .../cancel` can reach it, and wait for its result — translating `runner.RunError` into a
    502 (the run failed/crashed/timed out) rather than an uncaught exception."""
    run_id = f"{notebook_id}-{uuid.uuid4().hex[:8]}"
    run = await runner.start_run(run_id, _TRACE_DIR, dotted_task, kwargs)
    _ACTIVE_RUNS[notebook_id] = run
    try:
        return await runner.wait_result(run, timeout=config.run_timeout_seconds)
    except runner.RunError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        # Only clear OUR OWN run — a slow cancel/finish race could otherwise clobber a NEWER run
        # that already replaced this one in _ACTIVE_RUNS for the same notebook_id.
        if _ACTIVE_RUNS.get(notebook_id) is run:
            del _ACTIVE_RUNS[notebook_id]


@app.post("/notebooks/{notebook_id}/ask", response_model=AskResponse)
async def ask(notebook_id: str, body: AskRequest) -> AskResponse:
    notebook = _load_notebook_or_404(notebook_id)
    corpus = corpus_of(notebook)
    config = _config()
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc

    result = await _run_isolated(
        notebook_id,
        _dotted(AnswerQuestion),
        {"sources": blob, "history": history_text(notebook), "question": body.question},
        config,
    )
    answer = Answer.model_validate(result)

    notebook.turns.append(ChatTurn(question=body.question, answer=answer))
    save_notebook(notebook)

    return AskResponse(text=answer.text, citations=_citation_responses(answer.citations, corpus))


@app.post("/notebooks/{notebook_id}/guide/{kind}")
async def guide(notebook_id: str, kind: str) -> dict:
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
    result = await _run_isolated(notebook_id, _dotted(task_cls), {"sources": blob}, config)
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


@app.post("/notebooks/{notebook_id}/cancel")
async def cancel(notebook_id: str) -> dict:
    run = _ACTIVE_RUNS.get(notebook_id)
    if run is None:
        raise HTTPException(404, f"no in-flight run for notebook {notebook_id!r}")
    run.cancel()
    return {"cancelled": run.run_id}
