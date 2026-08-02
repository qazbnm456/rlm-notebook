"""`runner.py`'s subprocess-per-run mechanics, tested against small throwaway `-c` scripts that
speak the same one-JSON-line-to-stdout contract `worker.py` does — not the real
`rlm_notebook.worker` module, which needs model credentials and a sandbox this offline suite
deliberately never has (see CLAUDE.md's Verify section). `test_api.py` covers the higher-level
behavior with a fully-mocked `runner` instead.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from rlm_notebook import runner

_ECHO_OK = """
import sys, json
data = json.loads(sys.stdin.read() or "{}")
print(json.dumps({"ok": True, "result": {"echo": data}}))
"""

_ECHO_FAIL = """
import json
print(json.dumps({"ok": False, "error": "simulated worker failure"}))
"""

_PRINTS_GARBAGE = "print('not json at all')"

_PRINTS_NOTHING = "pass"

_SLEEPS_FOREVER = "import time; time.sleep(9999)"


async def _spawn(script: str, *, stdin_text: str = "{}") -> runner.Run:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdin is not None
    process.stdin.write(stdin_text.encode())
    process.stdin.close()
    return runner.Run(process, "test-run")


def test_wait_result_parses_the_last_json_line():
    async def _go():
        run = await _spawn(_ECHO_OK, stdin_text='{"kwargs": {"x": 1}}')
        result = await runner.wait_result(run)
        assert result == {"echo": {"kwargs": {"x": 1}}}

    asyncio.run(_go())


def test_wait_result_raises_run_error_when_worker_reports_ok_false():
    async def _go():
        run = await _spawn(_ECHO_FAIL)
        with pytest.raises(runner.RunError, match="simulated worker failure"):
            await runner.wait_result(run)

    asyncio.run(_go())


def test_wait_result_raises_run_error_on_no_output():
    async def _go():
        run = await _spawn(_PRINTS_NOTHING)
        with pytest.raises(runner.RunError, match="produced no output"):
            await runner.wait_result(run)

    asyncio.run(_go())


def test_wait_result_raises_run_error_on_non_json_output():
    async def _go():
        run = await _spawn(_PRINTS_GARBAGE)
        with pytest.raises(runner.RunError, match="not valid JSON"):
            await runner.wait_result(run)

    asyncio.run(_go())


def test_wait_result_times_out_and_cancels_a_hanging_run():
    async def _go():
        run = await _spawn(_SLEEPS_FOREVER)
        with pytest.raises(runner.RunError, match="timed out"):
            await runner.wait_result(run, timeout=0.5)
        await asyncio.sleep(0.3)
        assert run.process.returncode is not None  # the timeout cancelled it

    asyncio.run(_go())


def test_cancel_on_an_already_finished_process_does_not_raise():
    async def _go():
        run = await _spawn(_ECHO_OK)
        await runner.wait_result(run)
        run.cancel()  # process already exited; must be a no-op, not ProcessLookupError leaking out

    asyncio.run(_go())


def test_cancel_kills_the_whole_process_group_not_just_the_leader(tmp_path):
    """The whole point of `start_new_session=True` + `killpg`: a subprocess the worker itself
    spawned (standing in for a stuck Deno grandchild in the real worker) must die too when the run
    is cancelled — not become an orphan the group leader's death leaves behind."""
    pid_file = tmp_path / "child.pid"
    script = f"""
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(9999)"])
with open({str(pid_file)!r}, "w") as f:
    f.write(str(child.pid))
time.sleep(9999)
"""

    async def _go():
        run = await _spawn(script)
        for _ in range(50):
            if pid_file.exists() and pid_file.read_text():
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("child process never reported its pid")
        child_pid = int(pid_file.read_text())

        run.cancel()
        await asyncio.sleep(0.3)

        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)  # signal 0: check existence without sending a real signal

    asyncio.run(_go())


def test_start_run_creates_the_trace_directory(tmp_path):
    async def _go():
        trace_dir = tmp_path / "does" / "not" / "exist"
        run = await runner.start_run("run1", trace_dir, "rlm_notebook.schema:Answer", {})
        run.cancel()
        assert trace_dir.exists()

    asyncio.run(_go())
