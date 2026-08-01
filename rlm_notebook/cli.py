"""THE entry point for this slice: sources in, a grounded answer, a whole-notebook artifact, or a
podcast-style Audio Overview out — optionally as a multi-turn conversation.

    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --source https://example.com
    rlm-notebook guide summary --source ./paper.pdf
    rlm-notebook audio --source ./paper.pdf

    # a persistent, continuing conversation / notebook:
    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --notebook mynb
    rlm-notebook ask "and what about Y?" --notebook mynb
    rlm-notebook guide faq --notebook mynb

Needs model credentials (`RN_*`, see `.env.example`) and a sandbox (`brew install deno`). Without
`--notebook`, every invocation ingests its `--source` list from scratch and runs exactly once —
nothing is persisted (the sibling projects' "offline unless you ask" shape). See CLAUDE.md's Scope
note for what is not built yet.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from . import __version__
from .audio import GeneratePodcastScript
from .citations import verify_citations
from .config import NotebookConfig, setup
from .corpus import Corpus, CorpusTooLargeError
from .guide import GenerateFAQ, GenerateKeyInsight, GenerateSummary, GenerateTimeline
from .injection_scan import scan_source
from .notebook import corpus_of, existing_origins, history_text, load_notebook, save_notebook
from .parsers.pdf import parse_pdf
from .parsers.text import parse_text
from .parsers.web import FetchError, parse_web
from .schema import ChatTurn, Citation, Notebook, Source
from .task import AnswerQuestion
from .tts import TTSError, get_tts_provider

_SPEAKER_LABELS = {"host_a": "Host A", "host_b": "Host B"}

_CLI_DESCRIPTION = """\
Ask a question grounded in one or more sources, with citations you can verify — generate a
whole-notebook artifact (a summary, an FAQ, a timeline, or a single key insight) — or generate a
two-host podcast script + synthesized Audio Overview.

    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --source ./notes.txt
    rlm-notebook ask "..." --source https://example.com/article
    rlm-notebook guide summary --source ./paper.pdf
    rlm-notebook guide faq --source ./paper.pdf
    rlm-notebook audio --source ./paper.pdf --out episode.mp3

Add --notebook <id> to persist sources (and, for `ask`, history) across invocations:

    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --notebook mynb
    rlm-notebook ask "and what about Y?" --notebook mynb    # no --source needed to continue
    rlm-notebook guide timeline --notebook mynb
    rlm-notebook audio --notebook mynb

`--source` accepts a path to a text file, a path to a PDF (scanned pages are OCR'd automatically),
or an http(s) URL. Needs RN_* model credentials (see .env.example) and a sandbox (brew install
deno) for a live run. `audio` additionally needs network access to the TTS provider (edge-tts by
default — free, no API key).
"""

#: Notebook id used when `--notebook` is omitted — never persisted (see `_prepare`), so it never
#: collides with a real notebook file on disk regardless of what this string is.
_EPHEMERAL_ID = "_ephemeral"

#: `guide <kind>` -> the RLMTask that produces it. Shared by `build_parser` (as `choices`) and
#: `_cmd_guide` (to look up which task to run) so the two can never drift apart.
_GUIDE_TASKS: dict[str, type] = {
    "summary": GenerateSummary,
    "faq": GenerateFAQ,
    "timeline": GenerateTimeline,
    "insight": GenerateKeyInsight,
}


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
    notebook is therefore a cheap no-op, not a duplicate ingestion — and so is repeating one
    WITHIN the same `--source ... --source ...` list on a single invocation: `seen` starts as a
    copy of `skip_origins` and grows as this loop runs, so `--source a.txt --source a.txt` ingests
    `a.txt` once, not twice (found by an independent review: the first version only checked the
    caller's static set, so a duplicate value in the SAME invocation sailed through unfiltered)."""
    sources: list[Source] = []
    seen = set(skip_origins)
    next_index = start_index
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        source = _ingest_one(value, source_id=f"s{next_index}")
        flags = sorted({flag for block in source.blocks for flag in scan_source(block.text)})
        if flags:
            source = source.model_copy(update={"flags": flags})
        sources.append(source)
        next_index += 1
    return sources


def _prepare(args) -> tuple[Notebook, Corpus] | None:
    """Load-or-create the notebook named by `args.notebook` (or an ephemeral one), ingest and
    merge any new `args.source` values, print prompt-injection flag warnings, and return
    `(notebook, corpus)` — shared by `_cmd_ask` and `_cmd_guide`, which both need identical
    sources-in-hand setup before running their own RLMTask. Returns `None` (an error already
    printed to stderr) if loading or ingestion failed, or if there are no sources at all; the
    caller should return 1 in that case."""
    try:
        notebook = load_notebook(args.notebook) if args.notebook else None
    except ValidationError as exc:
        # `save_notebook` writes atomically (temp file + os.replace), so this should only happen
        # to a file this tool never wrote — hand-edited, or corrupted by something outside this
        # process. Fail with a clear message rather than an uncaught pydantic traceback; there is
        # no automatic recovery (see notebook.save_notebook's docstring).
        print(
            f"notebooks/{args.notebook}.json exists but is not a valid notebook file "
            f"({type(exc).__name__}) — fix or remove it by hand before continuing.",
            file=sys.stderr,
        )
        return None
    if notebook is None:
        notebook = Notebook(id=args.notebook or _EPHEMERAL_ID)

    if not args.source and not notebook.sources:
        print(
            "no sources: pass --source at least once (or point --notebook at one that already "
            "has sources)",
            file=sys.stderr,
        )
        return None

    try:
        new_sources = _ingest_new(
            args.source or [],
            start_index=len(notebook.sources) + 1,
            skip_origins=existing_origins(notebook),
        )
    except (FetchError, ValueError, OSError) as exc:
        print(f"could not ingest a source: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
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

    return notebook, corpus_of(notebook)


def _print_citations(citations: list[Citation], corpus: Corpus) -> None:
    """Print a blank-line-separated "Citations:" block, or nothing at all if `citations` is empty
    — the blank line is part of THIS function's output, not a separate `print()` each call site
    must remember, so "no citations" prints nothing rather than a stray trailing blank line (an
    independent review caught a version where every call site printed its own unconditional blank
    line first, so a citation-less answer ended in `"...text\\n\\n"` instead of `"...text\\n"`)."""
    verified = verify_citations(citations, corpus)
    if not verified:
        return
    print()
    print("Citations:")
    for v in verified:
        mark = "✓" if v.verified else "✗ UNVERIFIED"
        print(f"  [{mark}] {v.citation.source_id}|{v.citation.locator}: {v.citation.quote}")
        if not v.verified:
            print(f"        ({v.reason})")


def _cmd_ask(args) -> int:
    prepared = _prepare(args)
    if prepared is None:
        return 1
    notebook, corpus = prepared

    config = setup(NotebookConfig.from_env())
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = AnswerQuestion().run(sources=blob, history=history_text(notebook), question=args.question)

    print(result.text)
    _print_citations(result.citations, corpus)

    notebook.turns.append(ChatTurn(question=args.question, answer=result))
    if args.notebook:
        save_notebook(notebook)
    return 0


def _cmd_guide(args) -> int:
    prepared = _prepare(args)
    if prepared is None:
        return 1
    notebook, corpus = prepared

    config = setup(NotebookConfig.from_env())
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = _GUIDE_TASKS[args.kind]().run(sources=blob)

    if args.kind == "summary":
        print(result.text)
        _print_citations(result.citations, corpus)
    elif args.kind == "faq":
        if not result.items:
            # A source with nothing FAQ-worthy is a legitimate answer this task is explicitly
            # instructed to give (guide.py) — an empty list must not look identical to "this
            # silently produced no output," which an independent review found it did.
            print("(no FAQ items — the sources didn't raise anything worth asking)")
        for i, item in enumerate(result.items, start=1):
            print(f"Q{i}: {item.question}\nA{i}: {item.answer}")
            _print_citations(item.citations, corpus)
            print()
    elif args.kind == "timeline":
        if not result.events:
            print("(no timeline — the sources don't describe a sequence of events)")
        for event in result.events:
            print(f"[{event.when}] {event.description}")
            _print_citations(event.citations, corpus)
            print()
    else:  # "insight"
        print(result.text)
        _print_citations(result.citations, corpus)

    # Guide artifacts aren't cached onto the notebook or made citable as sources yet (deferred —
    # see CHANGELOG); this only persists any --source values just ingested, same as `ask` would.
    if args.notebook:
        save_notebook(notebook)
    return 0


def _cmd_audio(args) -> int:
    prepared = _prepare(args)
    if prepared is None:
        return 1
    notebook, corpus = prepared

    config = setup(NotebookConfig.from_env())
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    script = GeneratePodcastScript().run(sources=blob)

    if not script.utterances:
        # A source with nothing worth discussing is a legitimate answer (audio.py's instructions
        # explicitly allow it) — same "don't print silence and look broken" fix guide.py's empty
        # FAQ/timeline needed.
        print("(no podcast script — the sources didn't produce enough to discuss)")
    else:
        for utterance in script.utterances:
            print(f"{_SPEAKER_LABELS[utterance.speaker]}: {utterance.text}")
            _print_citations(utterance.citations, corpus)
            print()

        out_path = Path(args.out)
        provider = get_tts_provider(config.tts_provider)
        voice_map = {"host_a": config.tts_voice_host_a, "host_b": config.tts_voice_host_b}
        try:
            provider.synthesize(script, voice_map, out_path)
        except TTSError as exc:
            # The transcript above already printed successfully — a synthesis failure (network,
            # bad voice config) must not make it look like NOTHING happened; the script is still
            # useful on its own even without audio.
            print(f"transcript generated above, but audio synthesis failed: {exc}", file=sys.stderr)
            return 1
        print(f"-> {out_path}")

    if args.notebook:
        save_notebook(notebook)
    return 0


def _add_source_and_notebook_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--source", action="append", dest="source",
        help="a text file path, a PDF path, or an http(s) URL — repeatable. Required unless "
             "--notebook points at one that already has sources",
    )
    sub.add_argument(
        "--notebook", default=None,
        help="persist sources under this id across invocations (default: ephemeral, nothing is "
             "saved)",
    )


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
    _add_source_and_notebook_args(a)
    a.set_defaults(func=_cmd_ask)

    g = sub.add_parser("guide", help="generate a whole-notebook artifact from one or more sources")
    g.add_argument("kind", choices=sorted(_GUIDE_TASKS), help="which artifact to generate")
    _add_source_and_notebook_args(g)
    g.set_defaults(func=_cmd_guide)

    au = sub.add_parser(
        "audio", help="generate a two-host podcast script + synthesized audio (Audio Overview)"
    )
    _add_source_and_notebook_args(au)
    au.add_argument(
        "--out", default="podcast.mp3",
        help="output audio file path (default: podcast.mp3). Only written if the script is "
             "non-empty and synthesis succeeds; the transcript is always printed regardless",
    )
    au.set_defaults(func=_cmd_audio)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
