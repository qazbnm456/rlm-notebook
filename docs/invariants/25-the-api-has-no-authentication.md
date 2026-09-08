# Invariant 25 — The API has no authentication

**This API has NO authentication or authorization of any kind.** Any caller can create, extend,
query, `ask`/`guide` against, cancel a run for, RENAME, or irreversibly DELETE from any
`notebook_id` — THREE deletes, not one: a source (`DELETE .../sources/{id}`), a note
(`DELETE .../notes/{id}`) and the whole conversation (`DELETE .../turns`) — and can mutate GLOBAL
state through `PUT /settings` (invariant 41). There is no concept of an owner. Meant for local or
otherwise fully-trusted-network use only; do not expose it to an untrusted network without adding
auth first. Both `api.py`'s module docstring and `README.md` say so — don't let that warning
quietly disappear in a later edit.

**SO THE BINDING IS THE ACCESS CONTROL, AND IT LIVES IN CODE.** `rlm-notebook serve`
(`cli._cmd_serve`) binds `127.0.0.1` by default. With no authentication, which interface the
server listens on is not a deployment detail beside the real access control — it IS the access
control, entirely, and a rule that important cannot live only in a paragraph somebody has to read.
Before it, the documented way to start the server was `uvicorn rlm_notebook.api:app`, whose own
default is loopback but which invites a `--host 0.0.0.0` nobody warns about; `api.py`'s module
docstring named exactly that command, and FastAPI serves that docstring at `/docs`.

A non-loopback `--host` is ALLOWED, not refused. A genuinely trusted network is a use this
invariant already sanctions, and refusing would be the CLI overruling an operator who knows their
own network. It is not allowed to be QUIET, though: it prints what any reachable caller could do,
which is invariant 9's reasoning (an operator who sets a value believes something that had better
be true) applied to a value whose consequences are invisible until someone else finds the port.

**`cli._is_loopback` treats the EMPTY string as exposed, and that case is the one to keep.**
`bind("")` is `INADDR_ANY`, so `--host ""` is the most exposed value there is. A first draft listed
it beside `"localhost"` as obviously local, which would have silenced the warning on precisely the
binding that most needs it; found by printing the classifier's own table rather than by reading it.
A hostname that cannot be classified without DNS is treated as exposed too: resolving here would
make the warning depend on the resolver, and over-warning costs a line while under-warning costs
this invariant.

**The container binds `0.0.0.0`, deliberately.** Inside a container that is the only useful
binding, and the container boundary is what makes it safe — which is why `Dockerfile`'s documented
run command publishes to `127.0.0.1:8000:8000` rather than `8000:8000`. The warning still prints
on every start, and it is not wrong to: a bare `-p 8000:8000` really does put this on every
interface of the host.

`GET /notebooks` makes every id enumerable without knowing it, and `NotebookSummary.title` is
model-authored prose derived from a corpus excerpt (invariant 37) — so an unauthenticated caller
enumerating it gets a one-line summary of every notebook's subject matter. Inside the same
accepted posture, but no longer "metadata only".

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
