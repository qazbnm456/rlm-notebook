# Invariant 23 — Active runs is one slot per notebook

**`api._ACTIVE_RUNS` is a single-process, in-memory map with ONE SLOT PER NOTEBOOK ID — two
documented limitations, neither a silent bug.** (a) No multi-worker/multi-process `uvicorn`
story: each worker process gets its own dict, and `POST .../cancel` only reaches whichever holds
the request. (b) Two concurrent requests against the SAME notebook id share one slot, so
`/cancel` reaches only the most recent — the first still finishes on its own. The overwrite
itself never corrupts state (each request's `finally` clears only its OWN entry, an `is run`
identity check). A per-run-id registry would remove (b); `POST /runs/{run_id}/cancel`
(invariant 47) already does exactly that for the paths that have it.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
