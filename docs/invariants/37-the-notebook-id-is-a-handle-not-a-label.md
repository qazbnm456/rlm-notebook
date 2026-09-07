# Invariant 37 — The notebook id is a handle, not a label

**A notebook's `id` is a HANDLE; `schema.Notebook.title` is the label a person reads. The UI
mints the id itself and never asks for one.** Requiring a name before the first source made the
very first interaction a naming puzzle about a thing that did not exist yet. The id still backs
every filename, `ChatTurn.run_id` prefix and URL, so it must stay stable; the title is free to be
anything, which is why they are two fields. `title` is optional and defaults to `None`, so
notebooks written before it existed still load.

**`naming.SuggestTitle` is deliberately NOT an `RLMTask`.** The full REPL loop is right when the
model must explore a multi-MB corpus and produce verifiable citations, and absurd for five words
— it would cost a sandbox boot plus several planner turns. This is one plain `dspy.Predict` over
a corpus excerpt (invariant 61). It STILL runs inside the API's isolated subprocess, so invariant
21 is untouched: `worker.py` only calls `.arun(**kwargs)` on the class it is handed.

**Titling is a separate endpoint (`POST /notebooks/{id}/title`), never folded into
`add_sources`** — ingestion must not wait on, or fail because of, a model call.

**It is LAZY**: `app.js`'s `ensureTitle()` is called from actions that ALREADY run a model
(generating an overview, asking, opening a Studio tab, generating a podcast), never from
ingestion (pinned by `test_web_assets.py::test_titling_never_fires_from_adding_a_source`, which
slices `app.js` around the add-source path and asserts `suggestTitle(` is absent from it). Its
`ensureTitle();` count is a FLOOR (`>= 4`), so it catches a call site being deleted and NOT a
fifth action forgetting to add one — the useful half is the slice. Lazy, because pasting a link
should not spend a model call naming something nobody has
started working on. The consequence — a notebook with sources and no title — is why
`derived_title` exists (invariant 53).

**Nothing about a title may cost the user their source**: `SuggestTitle.arun` catches every
exception and `suggest_title` catches the `HTTPException` a failed/timed-out run raises, both
falling back to `naming.fallback_title`. An existing title is never overwritten — re-titling on
every source add would rename a notebook under a user who had already learned its name — so the
endpoint is idempotent. `clean_title` is the ONLY guard on what reaches the UI, since this is the
one model output with no schema validation behind it; the UI renders it with `textContent`,
never `innerHTML`, for the same reason every other model-derived string is (invariants 6 and 29).

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
