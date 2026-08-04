"""Subprocess entrypoint for `runner.py`: run one `RLMTask` (named by dotted `module:ClassName`)
with JSON inputs read from stdin, recording a full trace, and print exactly one JSON line to
stdout as the result.

    python -m rlm_notebook.worker <run_id> <trace_path> <module:ClassName>
    (JSON `{"kwargs": {...}}` on stdin)

This module is never invoked directly by a human — `runner.start_run` spawns it. It is the ONLY
thing that runs inside the isolated subprocess; `api.py` never imports `dspy`/`rlm_harness` itself.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys

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

    setup(NotebookConfig.from_env())

    from rlm_harness.trace import TraceRecorder

    try:
        with TraceRecorder(trace_path, run_id=run_id, meta={"task": dotted}):
            result = asyncio.run(_run(task_cls, kwargs))
    except Exception as exc:  # noqa: BLE001 — surfaced as a JSON error line, this is a process boundary
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1

    _emit({"ok": True, "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
