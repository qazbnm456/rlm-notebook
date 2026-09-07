# Invariant 25 — The API has no authentication

**This API has NO authentication or authorization of any kind.** Any caller can create, extend,
query, `ask`/`guide` against, cancel a run for, RENAME, or irreversibly DELETE A SOURCE FROM any
`notebook_id`, and can mutate GLOBAL state through `PUT /settings` (invariant 41). There is no
concept of an owner. Meant for local or otherwise fully-trusted-network use only; do not expose
it to an untrusted network without adding auth first. Both `api.py`'s module docstring and
`README.md` say so — don't let that warning quietly disappear in a later edit.

`GET /notebooks` makes every id enumerable without knowing it, and `NotebookSummary.title` is
model-authored prose derived from a corpus excerpt (invariant 37) — so an unauthenticated caller
enumerating it gets a one-line summary of every notebook's subject matter. Inside the same
accepted posture, but no longer "metadata only".

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
