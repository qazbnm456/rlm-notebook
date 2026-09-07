# Invariant 28 — Guide registries kept in sync by tripwire

**`cli._GUIDE_TASKS` and `api._GUIDE_TASKS` are two independent registries, kept in sync by the
tripwire `test_api.py::test_guide_task_registries_stay_in_sync_between_cli_and_api`, a
tripwire test, not by sharing code** (invariant 20 explains why `api.py` doesn't import from
`cli.py`). Add a new `guide` kind to BOTH dicts, or the tripwire fails immediately rather than
the two silently drifting.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
