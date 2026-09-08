"""THE entry point for this slice: sources in, a grounded answer, a whole-notebook artifact, or a
podcast-style Audio Overview out — optionally as a multi-turn conversation. `serve` starts the
HTTP API and the web UI instead, which is a different execution model (invariant 21) reached
through the same command.

    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --source https://example.com
    rlm-notebook guide summary --source ./paper.pdf
    rlm-notebook audio --source ./paper.pdf

    # a persistent, continuing conversation / notebook:
    rlm-notebook ask "what does it say about X?" --source ./paper.pdf --notebook mynb
    rlm-notebook ask "and what about Y?" --notebook mynb
    rlm-notebook guide faq --notebook mynb

Needs model credentials (`RN_*`, see `.env.example`) and a sandbox (`brew install deno`). Without
`--notebook`, every invocation ingests its `--source` list from scratch and runs exactly once —
nothing is persisted (the sibling projects' "offline unless you ask" shape). See AGENTS.md's Scope
note for what is not built yet.
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from . import __version__
from .audio import GeneratePodcastScript
from .citations import verify_citations
from .config import NotebookConfig, output_language, setup, tts_voice_map
from .corpus import Corpus, CorpusTooLargeError
from .guide import GenerateFAQ, GenerateKeyInsight, GenerateSummary, GenerateTimeline
from .notebook import (
    append_sources,
    corpus_of,
    history_text,
    ingest_sources_for,
    load_or_create,
    mutate_notebook,
)
from .parsers.web import FetchError
from .schema import ChatTurn, Citation, Notebook
from .task import AnswerQuestion
from .tts import TTSError, get_tts_provider, spoken_script

_SPEAKER_LABELS = {"host_a": "Host A", "host_b": "Host B"}

#: `--out`'s default. Named so `_cmd_audio` can tell "the user chose this path" from "nobody did",
#: and correct the extension only in the latter case — a provider may emit WAV rather than MP3.
_DEFAULT_AUDIO_OUT = "podcast.mp3"

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

#: `guide <kind>` -> the RLMTask that produces it. Shared by `build_parser` (as `choices`) and
#: `_cmd_guide` (to look up which task to run) so the two can never drift apart.
_GUIDE_TASKS: dict[str, type] = {
    "summary": GenerateSummary,
    "faq": GenerateFAQ,
    "timeline": GenerateTimeline,
    "insight": GenerateKeyInsight,
}


#: What a task is told when nothing better is known — a literal, never empty (see `api.py`'s copies
#: for why). The CLI has no `Accept-Language` and never runs the resolver, so it uses whatever
#: `RN_OUTPUT_LANGUAGE` says, else the language already resolved and PERSISTED on the notebook by
#: the API (the notebook is the unit both entry points share — invariant 20), else these.
_DEFAULT_ARTIFACT_LANGUAGE = "the language the sources are written in"
_DEFAULT_CHAT_LANGUAGE = "the language the question was asked in"


def _language_for(notebook, default: str) -> str:
    return output_language() or notebook.output_language or default


def _prepare(args) -> tuple[Notebook, Corpus] | None:
    """Load-or-create the notebook named by `args.notebook` (or an ephemeral one — see
    `notebook.load_or_create`), ingest any new `args.source` values, merge and PERSIST them, print
    prompt-injection flag warnings, and return `(notebook, corpus)` — shared by
    `_cmd_ask`/`_cmd_guide`/`_cmd_audio`, which all need identical sources-in-hand setup before
    running their own RLMTask. Returns `None` (an error already printed to stderr) if loading or
    ingestion failed, or if there are no sources at all; the caller should return 1 in that case.
    `api.py` uses the same `notebook.py` functions directly rather than this
    argparse-`Namespace`-shaped wrapper.

    **Ingestion is persisted HERE, before the model runs, rather than in a single save at the end
    of the command.** Two reasons, both consequences of the read-modify-write fix this slice
    landed: an RLM run is a minutes-long window in which another writer (a second CLI invocation,
    the API server) can legitimately touch the same notebook, and holding a snapshot across it is
    the defect itself; and a run that fails or is Ctrl+C'd partway no longer discards ingestion the
    user already paid for in OCR or network time.

    **Returns the notebook `mutate_notebook` produced, NOT the local snapshot** — `append_sources`
    renumbers ids against the freshly-loaded notebook, and handing the model a corpus built from
    the pre-merge objects would make it cite `s2` for a source persisted as `s4`. Every citation in
    the run would silently point at the wrong source."""
    try:
        notebook = load_or_create(args.notebook)
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

    if not args.source and not notebook.sources:
        print(
            "no sources: pass --source at least once (or point --notebook at one that already "
            "has sources)",
            file=sys.stderr,
        )
        return None

    try:
        ingested = ingest_sources_for(notebook, args.source or [])
    except (FetchError, ValueError, OSError) as exc:
        print(f"could not ingest a source: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None

    # Nothing new to merge (the common "keep asking an existing notebook" case) takes neither the
    # lock nor a write: the snapshot above is already exactly as fresh as any reader ever gets.
    if ingested and args.notebook:
        notebook = mutate_notebook(
            args.notebook, lambda nb: append_sources(nb, ingested), create=True
        )
    elif ingested:
        # Ephemeral: nothing is persisted, so there's nothing to lock against and no fresh copy to
        # re-read — the same `append_sources` merge, applied to the in-memory notebook directly.
        append_sources(notebook, ingested)

    # Every source currently in the notebook, not just ones just added — a flag stays visible on
    # every subsequent turn, not only the turn that ingested the flagged source (AGENTS.md's
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


@contextlib.contextmanager
def _traced(args, task: Any, config: Any, kwargs: dict) -> Iterator[None]:
    """Record this run to `--trace` if one was asked for, otherwise do nothing at all.

    **OPT-IN with an EXPLICIT path, and both halves are the design.** The API's `traces/` is a bare
    relative directory resolved against the server's working directory, swept by `prune_traces` at
    startup and after every run — neither of which a CLI has. Writing there by default would
    scatter a `traces/` directory into whatever directory the command was invoked from and leave
    files nobody ever collects, and a trace is the one artifact here that can hold FULL ingested
    source text (invariant 34). A path the caller named is a path the caller owns.

    The recorder is entered BEFORE the model call, so an unwritable path fails for free rather than
    after a run has been paid for — invariant 19's discipline, which is also why `_cmd_audio`
    resolves its TTS provider first. **A missing directory is not unwritable**: `TraceRecorder`
    calls `os.makedirs(..., exist_ok=True)`, so `--trace new/dir/run.jsonl` creates the path. That
    is a side effect of naming a path, not of running the command, and it is stated because a first
    reading of this assumed the opposite.
    """
    if not args.trace:
        yield
        return

    from rlm_harness.trace import TraceRecorder

    from .traces import run_meta

    dotted = f"{type(task).__module__}:{type(task).__name__}"
    run_id = f"cli-{uuid4().hex[:12]}"
    recorder = TraceRecorder(args.trace, run_id=run_id, meta=run_meta(dotted, config, kwargs))
    # ONLY `__enter__` is wrapped. A `try:` around the `yield` also catches an `OSError` raised by
    # the MODEL RUN — and `TimeoutError`, `BrokenPipeError` and `ConnectionResetError` are all
    # `OSError` subclasses, so a dying sandbox pipe or a timed-out call was reported as
    # "cannot write the trace to ...". The path was fine, the trace was on disk and complete with
    # `run_end ok=false` in it, and the operator re-ran and paid for the model call again.
    try:
        recorder.__enter__()
    except OSError as exc:
        raise SystemExit(f"cannot write the trace to {args.trace!r}: {exc}") from exc
    try:
        yield
    finally:
        recorder.__exit__(*sys.exc_info())


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

    task = AnswerQuestion()
    kwargs = {
        "sources": blob,
        "history": history_text(notebook),
        "question": args.question,
        "output_language": _language_for(notebook, _DEFAULT_CHAT_LANGUAGE),
    }
    with _traced(args, task, config, kwargs):
        result = task.run(**kwargs)

    print(result.text)
    _print_citations(result.citations, corpus)

    if args.notebook:
        # Appended to a notebook re-loaded fresh after the run, not to the snapshot `_prepare`
        # returned before it — see `notebook.mutate_notebook`. `_prepare` already persisted any
        # newly ingested sources, so this critical section carries only the turn.
        turn = ChatTurn(question=args.question, answer=result)
        mutate_notebook(args.notebook, lambda nb: nb.turns.append(turn), create=True)
    return 0


def _cmd_guide(args) -> int:
    prepared = _prepare(args)
    if prepared is None:
        return 1
    _notebook, corpus = prepared  # guide/audio persist nothing; only the corpus is used

    config = setup(NotebookConfig.from_env())
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    task = _GUIDE_TASKS[args.kind]()
    kwargs = {
        "sources": blob,
        "output_language": _language_for(_notebook, _DEFAULT_ARTIFACT_LANGUAGE),
    }
    with _traced(args, task, config, kwargs):
        result = task.run(**kwargs)

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
    # see CHANGELOG), and `_prepare` has already persisted any --source values just ingested, so
    # there is nothing left for this command to write. The trailing `save_notebook` that used to
    # sit here existed only for that ingestion; keeping it would be a second write path holding a
    # pre-run snapshot — the exact shape this slice removed.
    return 0


def _cmd_audio(args) -> int:
    prepared = _prepare(args)
    if prepared is None:
        return 1
    _notebook, corpus = prepared  # guide/audio persist nothing; only the corpus is used

    config = setup(NotebookConfig.from_env())
    try:
        blob = corpus.blob(max_chars=config.max_corpus_chars)
    except CorpusTooLargeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Resolve the TTS provider BEFORE the (potentially expensive) script-generation model call,
    # not after — found by an independent review: a mistyped RN_TTS_PROVIDER used to only surface
    # as an uncaught TTSError once the model had already run and the transcript had already
    # printed, wasting that model call on a config mistake that was knowable up front.
    try:
        provider = get_tts_provider(config.tts_provider)
    except TTSError as exc:
        print(f"cannot generate audio: {exc}", file=sys.stderr)
        return 1

    language = _language_for(_notebook, _DEFAULT_ARTIFACT_LANGUAGE)
    # BEFORE the (expensive) script run: a language this provider has no id for, or a voice it does
    # not know, can never produce audio (invariant 19, extended from the provider NAME to its own
    # inputs). `get_tts_provider` above already covers a typo'd RN_TTS_PROVIDER.
    voice_map = tts_voice_map(config, language, provider)
    try:
        provider.validate(language, voice_map)
    except TTSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    task = GeneratePodcastScript()
    kwargs = {"sources": blob, "output_language": language, "target_length": args.length}
    with _traced(args, task, config, kwargs):
        script = task.run(**kwargs)

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
        # `--out` defaults to `podcast.mp3`, but a provider may emit another format (the local provider writes
        # WAV). Correct the extension rather than writing WAV bytes into a file named `.mp3` —
        # unless the user named the path themselves, in which case their choice stands.
        if args.out == _DEFAULT_AUDIO_OUT and out_path.suffix != provider.suffix:
            out_path = out_path.with_suffix(provider.suffix)
        try:
            provider.synthesize(spoken_script(script), voice_map, out_path, language)
        except TTSError as exc:
            # The transcript above already printed successfully — a synthesis failure (network,
            # bad voice config, an --out path whose parent doesn't exist — see tts.py's own fix)
            # must not make it look like NOTHING happened; the script is still useful on its own
            # even without audio.
            print(f"transcript generated above, but audio synthesis failed: {exc}", file=sys.stderr)
            return 1
        print(f"-> {out_path}")

    # Nothing to persist here either — see `_cmd_guide`'s note above.
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
    sub.add_argument(
        "--trace", default=None, metavar="PATH",
        help="write this run's reasoning trace to PATH (JSONL). Off by default; the API writes "
             "traces of its own and prunes them, this one is yours to keep or delete",
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
        "--length", choices=("short", "default", "long"), default="default",
        help="how long an episode to aim for: short (~3-5 min), default (~8-12), long (~18-25). "
             "The web UI offers the same three; both feed the task's `target_length` field",
    )
    au.add_argument(
        "--out", default=_DEFAULT_AUDIO_OUT,
        help="output audio file path (default: podcast.mp3). Only written if the script is "
             "non-empty and synthesis succeeds; the transcript is always printed regardless",
    )
    au.set_defaults(func=_cmd_audio)

    s = sub.add_parser("serve", help="run the HTTP API and the web UI (needs the `api` extra)")
    s.add_argument(
        "--host", default="127.0.0.1",
        help="interface to bind (default: 127.0.0.1, loopback only). This API has NO "
             "AUTHENTICATION of any kind (AGENTS.md invariant 25), so any other value is a "
             "deliberate decision to let everyone who can reach that interface read, rewrite and "
             "delete every notebook on this machine",
    )
    s.add_argument(
        "--port", type=_port, default=8000,
        help="port to bind (default: 8000)",
    )
    s.add_argument(
        "--reload", action="store_true",
        help="restart when the files under the CURRENT DIRECTORY change. Only useful from a source "
             "checkout: uvicorn watches the working directory, never the installed package, so on "
             "a `uv tool install`/`pipx`/container install this watches your notebooks and never "
             "the code. Without `uvicorn[standard]`'s watchfiles it also degrades to polling every "
             "file under that directory",
    )
    s.set_defaults(func=_cmd_serve)

    return p


#: Whether a host is a promise to stay on this machine. Parsed as an ADDRESS rather than compared
#: as a string, so `::1`, `127.0.0.2` and an IPv4-mapped loopback all read as loopback without
#: anyone enumerating spellings.
#:
#: It decides whether to PRINT A WARNING, so it is allowed to be wrong in one direction only. It
#: over-warns on forms getaddrinfo accepts and `ipaddress` does not (`[::1]`, `127.1`, `LOCALHOST`,
#: `0177.0.0.1`): a spurious warning on a genuinely local bind costs a line. It under-warns in
#: exactly ONE case, stated rather than hidden: `"localhost"` is trusted unconditionally, so an
#: `/etc/hosts` entry pointing it at a LAN address binds non-loopback in silence. Resolving it here
#: would make the warning depend on the resolver, which is the worse trade.
def _port(value: str) -> int:
    """A port argparse rejects cleanly rather than letting `bind()` raise.

    `type=int` alone accepts 99999, and `socket.bind` then raises `OverflowError` — which is NOT an
    `OSError`, so uvicorn's own `except OSError: sys.exit(STARTUP_FAILURE)` never catches it and the
    user gets a twelve-line traceback for a typo.
    """
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port must be 0-65535, not {port}")
    return port


def _is_loopback(host: str) -> bool:
    # NOT the empty string, which is the trap: `bind("")` is `INADDR_ANY`, so `--host ""` is the
    # most exposed value there is. An earlier draft of this function listed it beside "localhost"
    # and would have suppressed the warning on exactly the binding that most needs it.
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A hostname we cannot classify without resolving it. Resolving here would make the warning
        # depend on DNS, so treat it as exposed: over-warning costs a line, under-warning costs
        # invariant 25.
        return False


def _cmd_serve(args: argparse.Namespace) -> int:
    """Run the API and the web UI it serves.

    The API is reachable ONLY from this machine by default, and that default is the point. It has
    no authentication of any kind (invariant 25): any caller can create, rename, query, cancel,
    irreversibly delete a source from, and read the FULL TEXT and reasoning traces of any notebook,
    and can change global settings for notebooks they never named. Until this grows auth, "which
    interface it binds" is the whole access-control story, so it belongs in the code rather than
    only in a warning in `README.md`.

    A non-loopback `--host` is allowed, because a genuinely trusted network is a use the README
    already sanctions, and refusing it would be this command deciding something the operator knows
    better. It is not allowed to be QUIET, though: the same reasoning invariant 9 uses for
    `RN_INTERPRETER`, where an operator who set the value believes something that has to be true.

    Deliberately does NOT read `NotebookConfig.from_env`: that raises `SystemExit` whenever
    `RN_MAIN_MODEL` is unset, and a server with no model configured must still start, or the
    settings page invariant 41 built for exactly that operator is unreachable.
    """
    try:
        import uvicorn
    except ImportError:
        print(
            "rlm-notebook serve needs the `api` extra (fastapi + uvicorn).\n"
            "  from a source checkout:  uv sync --extra api\n"
            "  otherwise, reinstall with the extra, e.g.\n"
            "      uv tool install 'rlm-notebook[api] @ git+"
            "https://github.com/qazbnm456/rlm-notebook'",
            file=sys.stderr,
        )
        return 2

    if not _is_loopback(args.host):
        print(
            f"WARNING: binding {args.host}, not loopback. This API has NO AUTHENTICATION: anyone "
            f"who can reach {args.host}:{args.port} can read every notebook's full source text and "
            "reasoning traces, delete sources, and change settings for notebooks they never named. "
            "Only do this on a network you fully trust.",
            file=sys.stderr,
        )
    # `notebooks/`, `traces/` and `audio/` are relative paths resolved against the working
    # directory (invariant 34), so where you START this decides where your notebooks live. That is
    # the one fact worth printing, and it is printed to STDERR: stdout is block-buffered off a TTY,
    # so on the containerised path this line never reached `docker logs` at all — the path a
    # reader most needs when their notebooks are inside a container that is about to be removed.
    #
    # The URL is NOT printed here. It used to be, one line BEFORE the bind, so an occupied port
    # announced an address it then failed to serve. uvicorn prints it after binding, which is the
    # only point at which it is true.
    print(f"rlm-notebook: notebooks, traces and audio under {Path.cwd()}", file=sys.stderr)
    uvicorn.run("rlm_notebook.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
