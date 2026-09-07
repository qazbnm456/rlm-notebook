# Invariant 38 — The overview is persisted and marked stale

**The chat overview is the ONE guide artifact persisted onto a notebook (`schema.Overview`,
`Notebook.overview`), and it is marked STALE rather than deleted when the sources change.**
Before, it lived only as a front-end flag on a DOM node, so re-opening a notebook showed the
first-run button again, and adding a source DELETED an overview that cost a real RLM run — with
"never generated" and "generated but the sources moved" rendering identically. Three states now:
never generated → the button; current → the overview; stale → the overview, marked, plus
`↻ Regenerate`.

A deliberately NARROW cut of "guide artifacts aren't cached onto a notebook": the overview only,
never the four Studio guide kinds. The overview is the notebook's front page and is what a
returning user expects to still be there; a Studio tab is an on-demand tool. It does not make
`+ Save as note` redundant — the field holds the CURRENT overview and is replaced on
regeneration, while a note is a copy the user chose to keep and the only thing `promote_note` can
turn into a citable source.

**`Overview.source_ids` is captured at RUN START, never at persist time.** Building the object
inside the `mutate_notebook` closure reads as tidy and is silently wrong: a source added while
the run was in flight would be listed as covered by an overview the model never read, and the
staleness key would then claim "current" when it isn't. Honest consequence, not a bug: adding a
source mid-generation makes the overview land ALREADY STALE — the same reasoning `ask` uses for
verifying against the snapshot corpus.

**Staleness is SET-EQUALITY on source ids computed SERVER-side**, never by a client (which would
need `source_ids` exposed and would be re-implemented in every future consumer). It is one small
comparison each in `_podcast_response` and `_overview_response`. A set rather than a length check
because a future source-removal path would then break it in the SAFE direction — that path exists
now (invariant 50) and the foresight paid.

**`/overview` suffixes its two run ids AFTER derivation** — `base = _derive_run_id(id, token)`
then `f"{base}-summary"`/`f"{base}-faq"`, with `token = body.run_id or uuid4().hex` capped at
`_RUN_TOKEN_MAX`. Forming `<token>-summary` first and slugging the result breaks twice: `run_id`
is OPTIONAL, so an anonymous request yields the literal deterministic `None-summary` and every
request after the first 409s until retention collects the trace; and `slug`'s 120-character cap
MERGES the two suffixes for a long client-chosen token. The cap also keeps the filename clear of
a 255-byte `NAME_MAX`.

**Generation is server-side, not a `PUT` of what the client already has.** The reason is not
provenance (invariant 25 already lets any caller store arbitrary prose) — it is that closing the
tab between the guide response and a store call would LOSE a paid-for run. An FAQ failure
persists the summary with no starter questions; a summary failure persists nothing, because there
is no overview without it.

**Run-id guards compare `slug(notebook_id)`, not the raw id**, on BOTH ends: `stream_run` and
`citation_turn` server-side, and `app.js` client-side via `NotebookResponse.slug`. Guarding with
the raw form makes every trace link dead for any id the slug changes — `"my notebook"`, or any
non-Latin id, which invariant 10 exists to support. The slug is RETURNED rather than
re-implemented in JS, because the hash fallback would have to be duplicated too.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
