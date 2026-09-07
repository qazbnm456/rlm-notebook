# Invariant 32 — Notes are uncited until promoted

**Notes (`schema.Note`, `Notebook.notes`) are freeform, uncited text — grounded and citable only
once PROMOTED into a real `Source`, never before.** A note may have originated as a copy of a
citation-grounded answer, but the note itself carries no `citations` and is never re-verified —
invariant 5's guarantee doesn't extend to it. `notebook.promote_note` is the ONLY path a note's
text reaches `notebook.sources`, and it reuses `ingest.ingest_pasted_text` UNCHANGED, so a
promoted note gets the identical content-derived-origin, dedup-by-origin and injection-scan
treatment. Promotion removes the note regardless of whether a source was appended (a dedup hit
appends nothing) — promotion is a completed user action either way, and the endpoint returns the
full `NotebookResponse` so a client distinguishes outcomes by diffing, never by a status code.

**A note id is assigned from the MAX id among currently-live notes, never `len(notes) + 1`**
(`notebook._next_note_id`). With length-based ids, deleting a non-last note lets TWO LIVE notes
share one id, and since `delete_note`/`promote_note` both act BY id, that made either one
silently affect BOTH. `delete_note`/`promote_note` also remove exactly the first matching note
by index rather than filtering every id-equal match — defence in depth on top of the id fix.
Reusing an id once NO live note holds it is safe and unchanged.

**`POST /notebooks/{id}/notes` creates a notebook (`create=True`, like `add_sources`) so a new
notebook can start life with a note; `DELETE .../notes/{note_id}` requires an existing one
(`create=False`, matching `ask`/`guide`).**

**The "+ Save as note" button belongs to a CALL SITE that opts in, never to the shared
`renderAnswerWithCitations`**, which is called from six sites — putting it inside would leak it
onto every artifact. It is a small factory (`saveAsNoteButton`) so opting-in sites share one
implementation. **Two sites opt in: a Chat answer (`renderTurn`) and the chat overview
(`renderChatOverview`).** The line is about the SURFACE, not who authored the text: things
rendered IN the chat thread are the user's to curate; a Studio tab's artifact and a podcast
transcript are not part of that thread.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
