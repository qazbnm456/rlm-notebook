# Invariant 21 — API runs every task in a subprocess

**Every API request that runs an `RLMTask` does so in an isolated subprocess
(`runner.py`/`worker.py`), never in-process.** A SEPARATE execution model from `cli.py`'s
synchronous in-process one; the two coexist. **`worker.py` is the only place an `RLMTask` is
ever RUN** — `.arun()` is called there and nowhere else — so a crash deep in a model run takes
down a worker subprocess, never the API server. **Do not restate the claim that `api.py` never
imports `dspy`/`rlm_harness`; it is FALSE and was verified false** (it imports the task classes
for `_dotted()`, and those import `rlm_harness` at module scope). The guarantee is about
EXECUTION, not imports.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
