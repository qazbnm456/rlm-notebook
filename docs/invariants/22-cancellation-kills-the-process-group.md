# Invariant 22 — Cancellation kills the process group

**Cancellation works via `killpg` on the WHOLE process group (`start_new_session=True` when
spawning), not just the worker's own PID.** A stuck Deno grandchild must not survive as an
orphan after its parent worker is killed. **Verified by a real test that spawns an actual
grandchild and confirms it dies too** (`test_runner.py::test_cancel_kills_the_whole_process_group_not_just_the_leader`)
— one of the few claims here that is executable rather than a source-tree assertion, so breaking
it costs a red test, not a review catch. Don't simplify this to `process.kill()`, which only
signals the worker's own PID.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
