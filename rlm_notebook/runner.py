"""Subprocess-per-run task execution, for `api.py`'s concurrent request handling.

CLAUDE.md's execution-model decision: each run is its own OS process (`start_new_session=True`),
not a pre-warmed worker pool — trading a bit of per-run cold-start latency for a genuinely
reliable cancellation story (`killpg` on the whole process group, so a stuck Deno grandchild dies
with its parent rather than being orphaned). `cli.py`'s in-process, synchronous invocation is
completely unaffected by this module; it exists only for `api.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path


class RunError(RuntimeError):
    """A run failed to start, crashed, produced no parseable result, or timed out."""


class Run:
    """A handle to one in-flight (or finished) subprocess run."""

    def __init__(self, process: asyncio.subprocess.Process, run_id: str) -> None:
        self.process = process
        self.run_id = run_id

    def cancel(self) -> None:
        """Kill the WHOLE process group the worker leads (`start_new_session=True` in
        `start_run` made the worker its own group leader), not just the worker's own PID — a
        Deno grandchild the worker spawned shares that group and dies with it. A `ProcessLookupError`
        means the run already finished on its own; that's success, not a failure to report."""
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


async def start_run(
    run_id: str, trace_dir: Path, dotted_task: str, kwargs: dict, *, fresh: bool = False
) -> Run:
    """Spawn `python -m rlm_notebook.worker` as an isolated subprocess and hand it `kwargs` (the
    RLMTask's `arun()` keyword arguments) as JSON on stdin. Does not wait for it to finish — see
    `wait_result`.

    `fresh` asks the worker to run with dspy's LM cache OFF. It rides ALONGSIDE `kwargs` rather
    than inside them: `kwargs` are the task's `arun()` arguments and anything added there reaches
    the model as a signature field, which this is not.
    """
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace_path = trace_dir / f"{run_id}.jsonl"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "rlm_notebook.worker", run_id, str(trace_path), dotted_task,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdin is not None  # PIPE was requested above
    process.stdin.write(json.dumps({"kwargs": kwargs, "fresh": fresh}).encode("utf-8"))
    process.stdin.close()
    return Run(process, run_id)


async def wait_result(run: Run, *, timeout: float | None = None) -> dict:
    """Wait for `run` to finish and return its parsed `result` dict. Raises `RunError` on a
    crash, a timeout (the run is cancelled first — see `Run.cancel`), or output that isn't the
    one-JSON-line contract `worker.py` promises."""
    try:
        stdout, stderr = await asyncio.wait_for(run.process.communicate(), timeout=timeout)
    except TimeoutError:
        run.cancel()
        # Names the knob. "timed out after 300.0s and was cancelled" tells a reader what happened
        # and nothing about what to do, and the default is path-dependent (`config`'s
        # `_default_run_timeout`), so the number alone does not even identify which default was in
        # force.
        raise RunError(
            f"run {run.run_id!r} timed out after {timeout}s and was cancelled "
            f"(the wall-clock backstop; raise RN_RUN_TIMEOUT_SECONDS if the model is simply slow)"
        ) from None

    text = stdout.decode("utf-8", errors="replace")
    lines = [line for line in text.strip().splitlines() if line]
    if not lines:
        raise RunError(
            f"worker for run {run.run_id!r} produced no output (exit {run.process.returncode}); "
            f"stderr: {stderr.decode('utf-8', errors='replace')[:2000]}"
        )
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RunError(f"worker output for run {run.run_id!r} was not valid JSON: {exc}") from exc

    if not payload.get("ok"):
        raise RunError(payload.get("error") or f"worker for run {run.run_id!r} failed with no error message")
    return payload["result"]
