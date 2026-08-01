"""THE entry point for this slice: sources in, one grounded answer out — optionally as a
multi-turn conversation.

    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --source https://example.com

    # a persistent, continuing conversation:
    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --notebook mynb
    rlm-notebook ask "and what about Y?" --notebook mynb

Needs model credentials (`RN_*`, see `.env.example`) and a sandbox (`brew install deno`). Without
`--notebook`, every invocation ingests its `--source` list from scratch and runs exactly one
question — nothing is persisted (the sibling projects' "offline unless you ask" shape). See
CLAUDE.md's Scope note for what is not built yet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .citations import verify_citations
from .config import NotebookConfig, setup
from .corpus import CorpusTooLargeError
from .injection_scan import scan_source
from .notebook import corpus_of, existing_origins, history_text, load_notebook, save_notebook
from .parsers.pdf import parse_pdf
from .parsers.text import parse_text
from .parsers.web import FetchError, parse_web
from .schema import ChatTurn, Notebook, Source
from .task import AnswerQuestion

_CLI_DESCRIPTION = """\
Ask a question grounded in one or more sources, with citations you can verify.

    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --source ./notes.txt
    rlm-notebook ask "..." --source https://example.com/article

Add --notebook <id> to persist sources and history across invocations, turning repeated `ask`
calls into a continuing conversation:

    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --notebook mynb
    rlm-notebook ask "and what about Y?" --notebook mynb    # no --source needed to continue

`--source` accepts a path to a text file, a path to a PDF (scanned pages are OCR'd automatically),
or an http(s) URL. Needs RN_* model credentials (see .env.example) and a sandbox (brew install
deno) for a live run.
"""

#: Notebook id used when `--notebook` is omitted — never persisted (see `_cmd_ask`), so it never
#: collides with a real notebook file on disk regardless of what this string is.
_EPHEMERAL_ID = "_ephemeral"


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _ingest_one(value: str, source_id: str) -> Source:
    if _is_url(value):
        return parse_web(value, source_id)
    path = Path(value)
    if path.suffix.lower() == ".pdf":
        return parse_pdf(str(path), source_id)
    return parse_text(path.read_text(encoding="utf-8"), source_id, origin=str(path))


def _ingest_new(values: list[str], *, start_index: int, skip_origins: set[str]) -> list[Source]:
    """Ingest `values` not already in `skip_origins` (a notebook's existing source origins — see
    `notebook.existing_origins`), numbering ids from `start_index` so they never collide with a
    notebook's existing sources. Re-passing the same `--source` on a later turn against the same
    notebook is therefore a cheap no-op, not a duplicate ingestion."""
    sources: list[Source] = []
    next_index = start_index
    for value in values:
        if value in skip_origins:
            continue
        source = _ingest_one(value, source_id=f"s{next_index}")
        flags = sorted({flag for block in source.blocks for flag in scan_source(block.text)})
        if flags:
            source = source.model_copy(update={"flags": flags})
        sources.append(source)
        next_index += 1
    return sources


def _cmd_ask(args) -> int:
    notebook = load_notebook(args.notebook) if args.notebook else None
    if notebook is None:
        notebook = Notebook(id=args.notebook or _EPHEMERAL_ID)

    if not args.source and not notebook.sources:
        print(
            "no sources: pass --source at least once (or point --notebook at one that already "
            "has sources)",
            file=sys.stderr,
        )
        return 1

    try:
        new_sources = _ingest_new(
            args.source or [],
            start_index=len(notebook.sources) + 1,
            skip_origins=existing_origins(notebook),
        )
    except (FetchError, ValueError, OSError) as exc:
        print(f"could not ingest a source: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    notebook.sources.extend(new_sources)

    # Every source currently in the notebook, not just ones just added — a flag stays visible on
    # every subsequent turn, not only the turn that ingested the flagged source (CLAUDE.md's
    # injection-flag invariant: additive metadata, surfaced for as long as it's part of the active
    # context, never a one-time notice).
    flagged = [s for s in notebook.sources if s.flags]
    if flagged:
        print("warning: possible prompt-injection patterns flagged (answer proceeds anyway):",
              file=sys.stderr)
        for s in flagged:
            print(f"  - {s.id} ({s.origin}): {', '.join(s.flags)}", file=sys.stderr)

    config = setup(NotebookConfig.from_env())
    corpus = corpus_of(notebook)
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = AnswerQuestion().run(sources=blob, history=history_text(notebook), question=args.question)
    verified = verify_citations(result.citations, corpus)

    print(result.text)
    if verified:
        print("\nCitations:")
        for v in verified:
            mark = "✓" if v.verified else "✗ UNVERIFIED"
            print(f"  [{mark}] {v.citation.source_id}|{v.citation.locator}: {v.citation.quote}")
            if not v.verified:
                print(f"        ({v.reason})")

    notebook.turns.append(ChatTurn(question=args.question, answer=result))
    if args.notebook:
        save_notebook(notebook)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rlm-notebook",
        description=_CLI_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("ask", help="ask one question grounded in one or more sources")
    a.add_argument("question", help="the question to ask")
    a.add_argument(
        "--source", action="append", dest="source",
        help="a text file path, a PDF path, or an http(s) URL — repeatable. Required unless "
             "--notebook points at one that already has sources",
    )
    a.add_argument(
        "--notebook", default=None,
        help="persist sources and history under this id across invocations (default: ephemeral, "
             "nothing is saved)",
    )
    a.set_defaults(func=_cmd_ask)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
