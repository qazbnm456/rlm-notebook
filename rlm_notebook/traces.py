"""Retention for the reasoning-trace files `worker.py` writes (`traces/{run_id}.jsonl`).

Until this slice there was no retention policy anywhere in this project — files accumulated
forever, stated as a known gap in CLAUDE.md invariant 29 and in `api.citation_turn`'s docstring.
They are also the one artifact here that can contain FULL ingested source text (the model echoes
spans of the corpus into its REPL output while reading it), so "keeps everything, forever, with no
authentication in front of it" (invariant 25) is a worse default than it would be for, say, logs.

Host-side housekeeping only: no `dspy`/`rlm_harness` import, nothing model-facing — the same posture
`tts.py` takes, so importing this from `api.py` doesn't reopen invariant 21.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

#: `rlm_harness.trace.SCHEMA` — stamped on EVERY event line `TraceRecorder.record()` writes.
#: Matched as a prefix so a future `/v2` still reads as ours.
_TRACE_SCHEMA_PREFIX = "rlm-harness/trace/"

#: A trace file younger than this is never pruned, whatever the age/count policy says. Covers the
#: two cases the caller's `protected` set cannot:
#:
#: 1. The window in `api._run_isolated` between the exclusive `O_CREAT|O_EXCL` reservation of
#:    `traces/{run_id}.jsonl` and `_RUN_PROCESSES[run_id] = ...` a few lines later. A file deleted
#:    in that gap frees the run id while a worker is still writing it — which would defeat the
#:    collision gate invariant 29 describes and let a second request append into the same file.
#: 2. A JUST-FINISHED run, whose trace is exactly what the answer currently on screen links to
#:    through `GET .../citation-turn`. Its process is gone from `protected` the instant it exits.
_MIN_AGE_SECONDS = 3600.0


def _is_ours(path: Path) -> bool:
    """Whether `path` is a trace THIS project wrote — checked before deleting anything.

    **`traces/` is a bare relative path (`api._TRACE_DIR`), resolved against whatever directory the
    server was started in**, and this project's siblings (`ctx-distillery` and friends) all write
    `.jsonl` traces of their own. An independent security review reproduced the consequence: a
    co-located `traces/` holding another tool's files was emptied by the startup sweep, on nothing
    but a filename glob and an mtime. Age and the protected set bound WHEN a file dies; neither
    says anything about WHOSE it is.

    Ours means: the first line parses as JSON carrying `rlm_harness.trace`'s schema marker — every
    line `TraceRecorder.record()` writes stamps it — or the file is empty, which is the reservation
    `api._run_isolated` creates with `O_CREAT|O_EXCL` before spawning a worker (that abandoned case
    still has to be collectable, and a zero-byte file carries no one's data either way).
    """
    try:
        if path.stat().st_size == 0:
            return True
        with path.open("r", encoding="utf-8") as fh:
            first = fh.readline()
    except (OSError, UnicodeDecodeError):
        return False
    try:
        schema = json.loads(first).get("schema")
    except (json.JSONDecodeError, AttributeError):
        return False
    return isinstance(schema, str) and schema.startswith(_TRACE_SCHEMA_PREFIX)


def prune_traces(
    trace_dir: Path,
    *,
    max_age_seconds: float,
    max_files: int,
    protected: set[str],
    min_age_seconds: float = _MIN_AGE_SECONDS,
) -> list[str]:
    """Delete old trace files, returning the run ids actually removed (for logging/tests).

    `max_age_seconds <= 0` disables the age sweep, `max_files <= 0` the count sweep. `protected`
    holds run ids that must survive regardless — `api.py` passes a snapshot of `_RUN_PROCESSES`'s
    keys, i.e. every run whose HTTP request is still attached. (A worker orphaned by a client
    disconnect is NOT in that map and leans on `min_age_seconds` instead; it would additionally
    have to stall past that floor before it were even at risk.)

    **Nothing is deleted unless `_is_ours` recognises it**, whatever the policy says.

    **`protected` and `min_age_seconds` outrank the count cap**, and the cap governs how many
    PRUNABLE traces are kept — a protected or too-young file never consumes a slot it couldn't
    yield anyway. `max_files` is therefore a SOFT cap on the directory total: a burst of runs
    exceeds it rather than deleting a trace something is still using. An independent security
    review caught the first version doing the exact OPPOSITE of that sentence — it charged
    protected and too-young files against the cap while drawing every deletion from the eligible
    ones, so N concurrent runs (a client-influenceable number: `_run_isolated` reserves the trace
    file before spawning anything) could force well-within-retention traces to be deleted early.
    `RN_TRACE_RETENTION_DAYS` is a floor again, not a function of load.

    **Never raises.** A missing directory is a no-op; a per-file `OSError` (a race with another
    sweep, a permissions problem) skips that file. This runs in a `finally` after a successful run
    and at server startup — housekeeping must never turn a completed `ask` into a 500.
    """
    try:
        entries = [p for p in trace_dir.glob("*.jsonl") if p.is_file()]
    except OSError:
        return []

    now = time.time()
    candidates: list[tuple[float, Path]] = []
    for path in entries:
        if path.stem in protected:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if now - mtime < min_age_seconds:
            continue
        if not _is_ours(path):
            continue
        candidates.append((mtime, path))

    candidates.sort()  # oldest first
    doomed: list[Path] = []

    if max_age_seconds > 0:
        cutoff = now - max_age_seconds
        doomed = [path for mtime, path in candidates if mtime < cutoff]

    if max_files > 0:
        still_eligible = [path for _, path in candidates if path not in doomed]
        surplus = len(still_eligible) - max_files
        if surplus > 0:
            doomed.extend(still_eligible[:surplus])  # oldest first

    removed: list[str] = []
    for path in doomed:
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path.stem)
    return removed
