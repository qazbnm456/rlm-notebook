"""THE entry point for this slice: sources in, one grounded answer out.

    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --source https://example.com

Needs model credentials (`RN_*`, see `.env.example`) and a sandbox (`brew install deno`). This
slice has no session persistence — every invocation ingests its `--source` list from scratch and
runs exactly one question. See CLAUDE.md's Scope note for what is not built yet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .citations import verify_citations
from .config import NotebookConfig, setup
from .corpus import Corpus, CorpusTooLargeError
from .injection_scan import scan_source
from .parsers.pdf import parse_pdf
from .parsers.text import parse_text
from .parsers.web import FetchError, parse_web
from .schema import Source
from .task import AnswerQuestion

_CLI_DESCRIPTION = """\
Ask a question grounded in one or more sources, with citations you can verify.

    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --source ./notes.txt
    rlm-notebook ask "..." --source https://example.com/article

`--source` accepts a path to a text file, a path to a PDF (scanned pages are OCR'd automatically),
or an http(s) URL. Needs RN_* model credentials (see .env.example) and a sandbox (brew install
deno) for a live run.
"""


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def _ingest_one(value: str, source_id: str) -> Source:
    if _is_url(value):
        return parse_web(value, source_id)
    path = Path(value)
    if path.suffix.lower() == ".pdf":
        return parse_pdf(str(path), source_id)
    return parse_text(path.read_text(encoding="utf-8"), source_id, origin=str(path))


def _ingest_all(values: list[str]) -> Corpus:
    corpus = Corpus()
    for i, value in enumerate(values, start=1):
        source = _ingest_one(value, source_id=f"s{i}")
        flags = sorted({flag for block in source.blocks for flag in scan_source(block.text)})
        if flags:
            source = source.model_copy(update={"flags": flags})
        corpus.add(source)
    return corpus


def _cmd_ask(args) -> int:
    try:
        corpus = _ingest_all(args.source)
    except (FetchError, ValueError, OSError) as exc:
        print(f"could not ingest a source: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    flagged = [s for s in corpus.sources if s.flags]
    if flagged:
        print("warning: possible prompt-injection patterns flagged (answer proceeds anyway):",
              file=sys.stderr)
        for s in flagged:
            print(f"  - {s.id} ({s.origin}): {', '.join(s.flags)}", file=sys.stderr)

    config = setup(NotebookConfig.from_env())
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = AnswerQuestion().run(sources=blob, question=args.question)
    verified = verify_citations(result.citations, corpus)

    print(result.text)
    if verified:
        print("\nCitations:")
        for v in verified:
            mark = "✓" if v.verified else "✗ UNVERIFIED"
            print(f"  [{mark}] {v.citation.source_id}|{v.citation.locator}: {v.citation.quote}")
            if not v.verified:
                print(f"        ({v.reason})")
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
        "--source", action="append", required=True, dest="source",
        help="a text file path, a PDF path, or an http(s) URL — repeatable",
    )
    a.set_defaults(func=_cmd_ask)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
