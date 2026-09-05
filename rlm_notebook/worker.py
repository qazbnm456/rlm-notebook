"""Subprocess entrypoint for `runner.py`: run one `RLMTask` (named by dotted `module:ClassName`)
with JSON inputs read from stdin, recording a full trace, and print exactly one JSON line to
stdout as the result.

    python -m rlm_notebook.worker <run_id> <trace_path> <module:ClassName>
    (JSON `{"kwargs": {...}}` on stdin)

This module is never invoked directly by a human — `runner.start_run` spawns it. It is the ONLY
thing that runs inside the isolated subprocess. (`api.py` DOES import both transitively — see
CLAUDE.md invariant 21, which records the stronger import claim as verified false. The
guarantee is about EXECUTION: `.arun()` is called here and nowhere else, so a crash deep in a
model run takes down a worker subprocess, never the API server.)
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys

# rlm-harness's own head+tail elider. Private, and deliberately borrowed rather than re-spelled:
# it already encodes WHERE an AdapterParseError keeps its diagnostics, which a slice gets wrong.
from rlm_harness import short_error

from .config import NotebookConfig, setup


def _resolve_task_class(dotted: str) -> type:
    module_name, _, class_name = dotted.partition(":")
    if not module_name or not class_name:
        raise ValueError(f"expected 'module:ClassName', got {dotted!r}")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def _emit(payload: dict) -> None:
    """Print exactly one JSON line — the ONLY thing `runner.wait_result` trusts. Never mix this
    with a stray `print()` elsewhere in this module; anything else belongs on stderr."""
    sys.stdout.write(json.dumps(payload, default=_default) + "\n")
    sys.stdout.flush()


def _default(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"cannot serialize {type(obj).__name__}")


async def _run(task_cls: type, kwargs: dict) -> object:
    return await task_cls().arun(**kwargs)


#: How much of each half of the message survives. Bounded because this ends up in an HTTP error
#: body and on screen, and an `AdapterParseError` embeds the model's ENTIRE completion.
_ERROR_CHARS = 600


def _describe(exc: BaseException) -> str:
    """`TypeName: message`, plus the ROOT cause when there is one, both head+tail elided.

    `RLMTaskError: Failed to produce a valid 'script' after N attempts` is what a user was shown for
    a run whose real fault was the model returning a schema fragment instead of the
    `reasoning`/`code` fields the adapter asked for. The wrapper names the symptom; the chain names
    the cause, and it was being discarded at exactly the boundary where a person starts reading.

    **Elision is rlm-harness's own `short_error`, not a `[:600]` slice.** dspy orders
    `AdapterParseError.__str__` as adapter-name, then the WHOLE LM completion, then the
    expected/actual field summary — so a head truncation deletes precisely the two lines worth
    having. An independent review measured the cutoff: past a ~534-character completion, a head
    slice ends in a wall of raw model output with `Actual: []` gone, i.e. it failed on the exact bug
    this function was added for. `short_error` keeps both ends and says how much it dropped; using
    it rather than re-implementing it is also why the numbers cannot drift apart.
    """
    root = exc
    seen = {id(exc)}
    while True:
        # `is not None`, not truthiness: an exception class with a falsy `__bool__`/`__len__` would
        # otherwise have its cause skipped. And `__suppress_context__` is honoured — `raise X from
        # None` is an explicit statement that the context is not to be shown, and resurfacing it
        # here would leak what someone deliberately suppressed.
        nxt = root.__cause__
        if nxt is None and not root.__suppress_context__:
            nxt = root.__context__
        # An ExceptionGroup hides the real fault in `.exceptions`; the subscription path's SDK runs
        # on anyio task groups, and this project has already been bitten by one (invariant 34).
        if nxt is None and not root.__suppress_context__:
            group = getattr(root, "exceptions", None)
            if isinstance(group, (list, tuple)) and group:
                nxt = group[0]
        if nxt is None or id(nxt) in seen:
            break
        seen.add(id(nxt))
        root = nxt

    head = _render(exc)
    if root is exc:
        return head
    return f"{head} \u2014 caused by {_render(root)}"


def _render(exc: BaseException) -> str:
    """One exception as a bounded single line. Never raises: `str(exc)` is arbitrary third-party
    code, and a raise HERE happens inside the handler that was about to emit the only JSON line the
    parent will ever see — the worker would die silently and `runner` would report "failed with no
    error message", losing even the wrapper."""
    try:
        return " ".join(short_error(exc, _ERROR_CHARS).split())
    except Exception:  # noqa: BLE001 — a broken __str__ must not cost us the whole report
        return f"{type(exc).__name__}: <unprintable>"


#: Kwargs whose VALUE must never reach a trace: the corpus blob and its relatives are megabytes,
#: and a trace is the most exposed artifact this project writes (CLAUDE.md invariant 29). Their SIZE
#: is recorded instead, which is the part that tells a reader what the run was working against —
#: the same reasoning invariant 52 gives for streaming a step's output size and not its text.
_BULKY_INPUTS = frozenset({"sources", "sources_excerpt", "history", "questions", "origins"})

#: Above this, a value is prose rather than a setting, and belongs in the run itself.
_INPUT_MAX = 200


def _input_meta(kwargs: dict) -> dict:
    """The run's own INPUTS, reduced to what a person needs to see in the Trajectory drawer's
    "Initial state": every short scalar argument by name, plus the size of the corpus it was given.

    Without this the panel held the task name and the budgets — nothing about what this PARTICULAR
    run was asked to do. The question that was asked, the language it was told to write in, the
    podcast length that was requested: each is one short string, each answers "why did it produce
    that", and none of them is derivable afterwards from a notebook that has since moved on.
    """
    meta: dict = {}
    sources = kwargs.get("sources") or kwargs.get("sources_excerpt")
    if isinstance(sources, str):
        meta["source_chars"] = len(sources)
    for name, value in kwargs.items():
        if name in _BULKY_INPUTS or not isinstance(value, (str, int, float, bool)):
            continue
        if isinstance(value, str) and (not value.strip() or len(value) > _INPUT_MAX):
            continue
        meta[name] = value
    return meta


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        _emit({"ok": False, "error": f"expected 3 args (run_id, trace_path, module:ClassName), got {argv!r}"})
        return 2
    run_id, trace_path, dotted = argv

    try:
        raw_stdin = sys.stdin.read()
        payload = json.loads(raw_stdin) if raw_stdin.strip() else {}
        kwargs = payload.get("kwargs", {})
    except json.JSONDecodeError as exc:
        _emit({"ok": False, "error": f"stdin was not valid JSON: {exc}"})
        return 2

    try:
        task_cls = _resolve_task_class(dotted)
    except (ImportError, AttributeError, ValueError) as exc:
        _emit({"ok": False, "error": f"cannot resolve task {dotted!r}: {type(exc).__name__}: {exc}"})
        return 2

    config = NotebookConfig.from_env()
    setup(config)

    from rlm_harness.trace import TraceRecorder

    # What the run was actually configured with, stamped once at the top of its own trace. The
    # Trajectory drawer's "Initial state" panel is built from this, and with only `task` in it that
    # panel said nothing the header did not already say. These are the answers to "which model, and
    # how much rope did it have" — the first two questions anyone asks of a run that went wrong, and
    # the ones the values in `config.py` cannot answer after the fact because the environment moves.
    #
    # No secrets: the model NAMES and the budgets, never `api_key` or `base_url`. A trace is already
    # the most exposed artifact this project writes (invariant 29), so what goes in it is a decision
    # rather than a convenience.
    meta = {
        "task": dotted,
        "main_model": config.main_model,
        "sub_model": config.sub_model,
        "max_iterations": config.max_iterations,
        "max_tokens": config.max_tokens,
        "max_retries": config.max_retries,
        **_input_meta(kwargs),
    }

    try:
        with TraceRecorder(trace_path, run_id=run_id, meta=meta):
            result = asyncio.run(_run(task_cls, kwargs))
    except Exception as exc:  # noqa: BLE001 — surfaced as a JSON error line, this is a process boundary
        _emit({"ok": False, "error": _describe(exc)})
        return 1

    _emit({"ok": True, "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
