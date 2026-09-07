"""`traces.prune_traces` — the retention policy for `traces/{run_id}.jsonl`.

Every test passes an explicit `min_age_seconds`, because the real floor (`_MIN_AGE_SECONDS`, one
hour) exists precisely so a freshly written trace is never touched — which would otherwise make
every one of these fixtures ineligible.
"""

from __future__ import annotations

import json
import os
import time

from rlm_notebook.traces import _MIN_AGE_SECONDS, prune_traces

#: What `rlm_harness.trace.TraceRecorder.record()` actually writes — every line carries the schema
#: marker. The fixtures below used to write a bare `{"type": "run_end"}`, which the ownership gate
#: (`traces._is_ours`, added after a security review) correctly refuses to recognise as ours; that
#: made five of these tests fail the moment the gate landed, which is the fixture being unrealistic
#: rather than the gate being wrong.
_SCHEMA = "rlm-harness/trace/v1"


def _aged(path, age_seconds: float):
    if age_seconds:
        when = time.time() - age_seconds
        os.utime(path, (when, when))
    return path


def _trace(dir_path, run_id: str, *, age_seconds: float = 0.0):
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{run_id}.jsonl"
    path.write_text(
        json.dumps({"schema": _SCHEMA, "run_id": run_id, "step_id": 0, "type": "run_end"}) + "\n",
        encoding="utf-8",
    )
    return _aged(path, age_seconds)


def _foreign(dir_path, name: str, content: str, *, age_seconds: float = 10_000_000):
    """A `.jsonl` file this project did NOT write, in the same directory."""
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / name
    path.write_text(content, encoding="utf-8")
    return _aged(path, age_seconds)


def test_missing_directory_is_a_no_op(tmp_path):
    removed = prune_traces(
        tmp_path / "nope", max_age_seconds=1.0, max_files=1, protected=set()
    )
    assert removed == []


def test_age_sweep_removes_only_what_is_older_than_the_cutoff(tmp_path):
    old = _trace(tmp_path, "nb-old", age_seconds=10_000)
    young = _trace(tmp_path, "nb-young", age_seconds=100)

    removed = prune_traces(
        tmp_path, max_age_seconds=5_000, max_files=0, protected=set(), min_age_seconds=0
    )

    assert removed == ["nb-old"]
    assert not old.exists()
    assert young.exists()


def test_age_sweep_disabled_by_zero(tmp_path):
    old = _trace(tmp_path, "nb-old", age_seconds=10_000_000)

    removed = prune_traces(
        tmp_path, max_age_seconds=0, max_files=0, protected=set(), min_age_seconds=0
    )

    assert removed == []
    assert old.exists()


def test_count_sweep_removes_oldest_first_down_to_the_cap(tmp_path):
    for i, age in enumerate([500, 400, 300, 200, 100]):
        _trace(tmp_path, f"nb-{i}", age_seconds=age)

    removed = prune_traces(
        tmp_path, max_age_seconds=0, max_files=2, protected=set(), min_age_seconds=0
    )

    assert removed == ["nb-0", "nb-1", "nb-2"]  # oldest three
    assert sorted(p.stem for p in tmp_path.glob("*.jsonl")) == ["nb-3", "nb-4"]


def test_protected_run_ids_are_never_removed(tmp_path):
    """An in-flight run's trace must survive any policy: deleting it breaks its live SSE stream AND
    frees a run id `_run_isolated`'s exclusive-create gate is still relying on being taken, which
    would let a second request append into the same file (AGENTS.md invariant 29)."""
    live = _trace(tmp_path, "nb-live", age_seconds=10_000_000)
    dead = _trace(tmp_path, "nb-dead", age_seconds=10_000_000)

    removed = prune_traces(
        tmp_path, max_age_seconds=1.0, max_files=0, protected={"nb-live"}, min_age_seconds=0
    )

    assert removed == ["nb-dead"]
    assert live.exists()
    assert not dead.exists()


def test_a_file_younger_than_the_floor_survives_even_an_aggressive_policy(tmp_path):
    """The floor covers what `protected` cannot: the window between `_run_isolated`'s exclusive
    create and its `_RUN_PROCESSES` registration, and a just-finished run whose trace the answer
    now on screen links to.

    TWO fresh files against `max_files=1`, deliberately — an independent test-quality review
    proved the first version of this test (one file, cap of 1) was hollow: one file is AT the cap,
    not over it, so it passed with the floor removed from `prune_traces` entirely. This shape fails
    without the floor (it removes `nb-old`) and passes with it."""
    old = _trace(tmp_path, "nb-old")  # both mtime = now
    new = _trace(tmp_path, "nb-new")

    removed = prune_traces(tmp_path, max_age_seconds=1.0, max_files=1, protected=set())

    assert removed == []
    assert old.exists() and new.exists()


def test_the_count_cap_is_soft_when_everything_is_protected_or_too_young(tmp_path):
    """A stated tradeoff, asserted so it stays deliberate: the cap yields to rules 1-2 rather than
    deleting a trace something is still using."""
    for i in range(5):
        _trace(tmp_path, f"nb-{i}")  # all brand new

    removed = prune_traces(tmp_path, max_age_seconds=0, max_files=1, protected=set())

    assert removed == []
    assert len(list(tmp_path.glob("*.jsonl"))) == 5


def test_a_protected_file_does_not_consume_a_cap_slot(tmp_path):
    """The cap governs how many PRUNABLE traces are kept. An independent security review found the
    first version did the opposite of its own docstring — it charged protected and too-young files
    against the cap while drawing every deletion from the eligible ones, so N concurrent runs (a
    number a client influences, since `_run_isolated` reserves the trace file before spawning)
    could force well-within-retention traces to be deleted early. Retention days is a floor again,
    not a function of load."""
    _trace(tmp_path, "nb-live", age_seconds=10_000)
    _trace(tmp_path, "nb-a", age_seconds=9_000)
    _trace(tmp_path, "nb-b", age_seconds=8_000)

    removed = prune_traces(
        tmp_path, max_age_seconds=0, max_files=2, protected={"nb-live"}, min_age_seconds=0
    )

    assert removed == []  # two eligible files, cap of two — the in-flight run costs nobody a slot
    assert sorted(p.stem for p in tmp_path.glob("*.jsonl")) == ["nb-a", "nb-b", "nb-live"]


def test_concurrent_runs_cannot_force_an_early_deletion(tmp_path):
    """The scenario the review used to demonstrate the bug, pinned so it can't come back: traces
    well inside the retention window, plus a burst of in-flight reservations pushing the directory
    total far past the cap."""
    inside_retention = [_trace(tmp_path, f"nb-old-{i}", age_seconds=2 * 86_400) for i in range(10)]
    in_flight = {f"nb-live-{i}" for i in range(50)}
    for run_id in in_flight:
        _trace(tmp_path, run_id, age_seconds=2 * 86_400)

    removed = prune_traces(
        tmp_path,
        max_age_seconds=7 * 86_400,
        max_files=20,
        protected=in_flight,
        min_age_seconds=0,
    )

    assert removed == []
    assert all(p.exists() for p in inside_retention)


def test_only_this_projects_own_traces_are_ever_deleted(tmp_path):
    """`traces/` is a bare relative path resolved against the server's working directory, and this
    project's siblings all write `.jsonl` traces of their own. An independent security review
    reproduced a co-located directory being emptied at server startup on nothing but a filename
    glob and an mtime — age and `protected` bound WHEN a file dies, never WHOSE it is."""
    ours = _trace(tmp_path, "nb-ours", age_seconds=10_000_000)
    sibling = _foreign(tmp_path, "ctx-distillery-run-1.jsonl", '{"schema": "some-other/trace/v1"}\n')
    plain = _foreign(tmp_path, "my-important-data.jsonl", '{"rows": [1, 2, 3]}\n')
    garbage = _foreign(tmp_path, "not-even-json.jsonl", "hello, world\n")

    removed = prune_traces(
        tmp_path, max_age_seconds=1.0, max_files=0, protected=set(), min_age_seconds=0
    )

    assert removed == ["nb-ours"]
    assert not ours.exists()
    assert sibling.exists() and plain.exists() and garbage.exists()


def test_an_abandoned_empty_reservation_is_still_collectable(tmp_path):
    """`_run_isolated` creates the trace file empty (`O_CREAT|O_EXCL`) before spawning a worker. A
    run killed before its first event leaves that zero-byte file behind — the ownership gate has to
    keep it collectable, or the reservation leaks forever."""
    empty = _foreign(tmp_path, "nb-abandoned.jsonl", "")

    removed = prune_traces(
        tmp_path, max_age_seconds=1.0, max_files=0, protected=set(), min_age_seconds=0
    )

    assert removed == ["nb-abandoned"]
    assert not empty.exists()


def test_an_unremovable_file_is_skipped_not_raised(tmp_path, monkeypatch):
    """Housekeeping runs in a `finally` after a successful run — it must never turn a completed
    `ask` into a 500."""
    _trace(tmp_path, "nb-a", age_seconds=10_000)
    _trace(tmp_path, "nb-b", age_seconds=10_000)

    real_unlink = os.unlink

    def _fail_on_a(path, *args, **kwargs):
        if str(path).endswith("nb-a.jsonl"):
            raise PermissionError("simulated")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", _fail_on_a)

    removed = prune_traces(
        tmp_path, max_age_seconds=1.0, max_files=0, protected=set(), min_age_seconds=0
    )

    assert removed == ["nb-b"]  # nb-a was skipped, not fatal
    assert (tmp_path / "nb-a.jsonl").exists()


def test_the_default_floor_is_an_hour():
    """Pinned deliberately: it must comfortably exceed `RN_RUN_TIMEOUT_SECONDS`'s 300s default, so
    an ordinary in-flight run can never age past it."""
    assert _MIN_AGE_SECONDS == 3600.0
