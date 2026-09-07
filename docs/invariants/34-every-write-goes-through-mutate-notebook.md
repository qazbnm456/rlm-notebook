# Invariant 34 — Every write goes through mutate notebook

**Every write to a notebook goes through `notebook.mutate_notebook`, which re-loads the file
from disk INSIDE a per-notebook lock and applies a caller-supplied DELTA — never a snapshot the
caller read earlier.** `save_notebook` writes the whole `Notebook` model, so persisting an
object read minutes ago silently destroys everything written in between. Two distinct faults and
the fix needs both halves: a stale snapshot and interleaved critical sections — a lock alone
would not have helped, since the racing writes never overlapped in the file-writing instant.
Every mutating path is now: expensive work UNLOCKED against a snapshot → `mutate_notebook`
applying only the delta. **`save_notebook` has exactly one caller in the whole package
(`mutate_notebook`); application code calling it directly is the bug**, and `extend_with_sources`
was DELETED rather than kept beside `ingest_sources_for` + `append_sources`, because ingesting
and appending in one breath is exactly what forces a caller to hold a snapshot across ingestion.

- **`fcntl.flock` on a sidecar `<base_dir>/.<slug>.json.lock`, NOT `fcntl.lockf`.** `flock`
  attaches to the open file description, so one mechanism serializes two threads of one process
  AND two processes; POSIX record locks are per-process and two `uvicorn` threads would pass
  straight through each other. A SIDECAR because `load_or_create` legitimately runs for a
  notebook that doesn't exist yet. **Not reentrant** — nothing passed to `mutate_notebook` may
  call `mutate_notebook`/`save_notebook`. **POSIX only**; without `fcntl` it degrades to a
  process-local `threading.Lock`, still correct for the single-process deployment invariant 23
  describes as the only supported one.
- **`api.py` dispatches every call through `asyncio.to_thread`** (the shared `_mutate_or_http`,
  which holds the ONE copy of invariant 27's error mapping plus `FileNotFoundError`→404), because
  a blocking `flock` a CLI invocation holds must not stall the event loop. It validates the id
  BEFORE the thread, since `notebook_path`'s invalid-id `ValueError` and `delete_note`'s "no such
  note" `ValueError` are the same type and catching them together misreports one as the other.
- **READS take no lock** (`os.replace` is atomic, so a reader sees a complete old or new file,
  never a torn one), and **`ask` verifies citations against the SNAPSHOT corpus** — the blob the
  model actually read. Invariant 11 governs reading a turn BACK.
- **`cli._prepare` persists ingestion before the model runs and returns the notebook
  `mutate_notebook` produced, NOT its own snapshot.** `append_sources` renumbers ids against the
  fresh notebook, so a corpus built from pre-merge objects would make the model cite `s2` for a
  source persisted as `s4` — every citation in the run silently wrong. The API's `ask` is NOT
  exposed to this (its snapshot holds only already-persisted sources).
- **`mutate_notebook` checks the `create=False` miss BEFORE taking the lock as well as inside
  it.** Entering `notebook_lock` creates its sidecar file, so without the pre-check every 404-ing
  unauthenticated request leaves a permanent zero-byte file behind. The check INSIDE the lock is
  what makes it correct; the outer one only keeps a miss from writing anything.

**Trace retention (`traces.py`)** — `traces/{run_id}.jsonl` is the one artifact here that can
contain FULL ingested source text, in front of an API with no authentication. `prune_traces`
sweeps by age (`RN_TRACE_RETENTION_DAYS`, 7) and count (`RN_MAX_TRACE_FILES`, 500), `0` disabling
either, at startup and after every run.

- **Two rules OUTRANK both sweeps**: a run id in the caller-supplied `protected` set
  (`_RUN_PROCESSES`'s keys) and any file younger than a one-hour floor. Deleting a live run's
  trace would not just break its SSE stream — it would free a run id the exclusive-create gate
  (invariant 29) is still relying on being taken. The floor covers what `protected` cannot: the
  window before registration, and a JUST-finished run whose trace the answer on screen links to.
- **`traces._is_ours` gates every deletion, and this is not optional hardening.** `_TRACE_DIR` is
  a bare relative `Path("traces")` resolved against whatever directory the server started in, and
  sibling projects write `.jsonl` traces of their own — age and `protected` bound only WHEN a file
  dies, never WHOSE it is. Ours means its first line carries `rlm_harness.trace`'s schema marker,
  or it is EMPTY (an abandoned `O_CREAT|O_EXCL` reservation, which must stay collectable).
  `api._prune_traces` LOGS what it removed: the only destructive operation here must not be silent.
- **The count cap governs how many PRUNABLE traces are kept**, so `max_files` is a SOFT cap on the
  directory total. Charging protected and too-young files against it while deleting only from the
  eligible ones lets N concurrent runs — a client-influenceable number — force well-within-
  retention traces to die early. `RN_TRACE_RETENTION_DAYS` is a floor, not a function of load.
- **`prune_traces` never raises** (housekeeping must not turn a completed, paid-for `ask` into a
  500), which is why the **lifespan reads the retention settings itself** — otherwise a typo'd
  value means "silently never prune" — **a malformed one REFUSES STARTUP instead**, which is the
  half that makes the design coherent: reading it in the lifespan and then warning-and-defaulting
  would satisfy the sentence before this one and still leave a typo'd `RN_TRACE_RETENTION_DAYS`
  silently keeping files that hold ingested source text. Standalone readers, never
  `NotebookConfig` fields, for
  invariant 30's reason: a server with no model configured must still tidy up after itself.
- **`api._prune_traces` snapshots `set(_RUN_PROCESSES)` on the EVENT LOOP, before dispatching to
  the thread**, or it races the loop's own mutation of the dict.
- **The CLI writes a trace ONLY on request, to a path the caller names (`--trace PATH`), and
  NOTHING prunes it.** Everything above belongs to the server: `traces/` is a bare relative
  directory resolved against the process's working directory, and `prune_traces` runs from
  `api.py`'s lifespan and after every API run — a CLI has neither. Tracing by default would
  scatter a `traces/` directory into whatever directory the command was invoked from and leave
  files nobody ever collects, holding what invariant 34 calls the one artifact here that can
  contain FULL ingested source text. An explicit path is a path the caller owns, so retention
  is theirs and there is no directory to sweep. The flag lives on the SHARED
  `_add_source_and_notebook_args`, so no run-taking subcommand can be given it by accident and
  no other one can be forgotten (invariant 46's lesson). **A missing directory is CREATED, not
  refused** — `TraceRecorder.__enter__` calls `os.makedirs(..., exist_ok=True)` — so only a
  genuinely unwritable path fails, and it fails BEFORE the model call (invariant 19).

  **The gap this closed was measurable, not hypothetical**: a live measurement of the
  pre-SUBMIT script check could not say whether the validator had FIRED, because the cheap path
  for such a measurement is the CLI and the CLI produced no evidence at all.

**Accepted limitation**: every call shares the asyncio default `ThreadPoolExecutor` with ingestion
and TTS synthesis, so a lock held by an external process can queue writes for unrelated notebooks.
Availability only, on a trusted-network service. **NOT attempted**: a merging write, a multi-worker
story for the in-memory run registries, any retention policy for `notebooks/` itself.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
