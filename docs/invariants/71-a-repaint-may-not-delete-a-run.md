# Invariant 71 — A repaint may not delete a run

**A repaint may not delete a RUN — and `#chat-overview` is owned by its generation while one is in
flight (`overviewRunning`).** Invariant 60 fixed this for the pending chat turn; the overview's OWN run
had the mirror-image hole. `renderChatOverview` clears the element holding the run's pulsing dot, its
elapsed counter and its only Stop, and several callers invoke it for reasons unrelated to the run. The
guard sits at the TOP of `renderChatOverview`, so every caller is covered without anyone maintaining a
list. Worse than it sounds because of a deliberate decision one line away: `sources:changed` does NOT
bump `overviewToken` — stranding a generation the server has already paid for would be the bigger bug —
so the run stays live with no way to see or stop it. Both decisions are individually right and were
never checked together.

**A notebook SWITCH must release the flag, not just bump the token**, or the new notebook's panel keeps
the previous run's status node. **And `!live()` covers two situations, only ONE of which belongs to this
panel**: a second press of Generate is a supersede and must SAY so (invariant 47 — a silent `return`
reads as a hang), while a notebook switch is not, because `#chat-overview` belongs to a different
notebook by then and `supersededNote` would overwrite ITS overview. Both call sites guard on
`generation === notebookGeneration`.

**Regenerate is UNCONDITIONAL once an overview exists; `offerRegenerate` picks its LABEL and WEIGHT
instead of its existence.** Gating it on stale-or-incomplete left an overview that is current and
complete but WRONG — the state a reader most wants out of — with no control on the page at all. Quiet and
short when nothing is wrong (regenerating costs two real RLM runs, so it must not be the loudest thing on
a panel that already holds what it makes), louder and explicit when stale or incomplete. That is the
three-state treatment invariant 42 gave the podcast's button.

**`/overview` runs TWO tasks and its ticker follows ONE**, so forwarding the summary run's terminal event
made the shared status line say "Finished" beside a live Stop while the FAQ half was still running —
invariant 60's rule broken by a second RUN rather than by a phase, which is why the fix reuses `setPhase`.
It stays STOPPABLE: `runIds` carries both ids and the FAQ run is genuinely cancellable.

**The chat composer IS frozen while an overview generates — a product decision, NOT a race**, and the
COMPOSER only, never the thread. The two runs are independent, `mutate_notebook` makes both writes land,
`rebuildHistory` re-appends the SAME `overviewEl` node, and invariant 60 makes the reverse safe. Nothing
is lost either way; the reason is that a question asked into a thread whose overview is being rewritten
READS as two things fighting whether or not they are. Recorded so a later reader does not "simplify" it
away as redundant with the locking. **Clearing the conversation was offered as the alternative and is
the one thing NOT to do**: it would destroy history to signal a transient state. Every exit thaws it —
cancel, success, error, and a notebook switch, which strands the run rather than ending it and would
otherwise freeze the NEW notebook's composer.

**A chat answer can be regenerated, and only the LAST one.** Every later answer was produced with this
one in its `history` (invariant 11), so redoing a turn in the middle would leave the answers after it
derived from a conversation that no longer exists. Gated by a STYLESHEET rule
(`.turn:not(:last-child)`), because turns reach the DOM through two paths (`rebuildHistory` and the
`chat:turnAdded` replay) and a rule that reads the DOM is right for both without either having to
remember — and it hides the control during a pending question for free. The SERVER re-checks
independently: `AskRequest.regenerate` replaces `turns[-1]` only when its question still matches, inside
the lock, so a request landing after someone else asked something new appends instead. **Replacing
rather than appending**, because the reason a reader regenerates is that the answer was wrong, and
keeping it in the thread keeps it in `history` for every future turn. Both entry points share ONE flow
(`askQuestion`) — the pending row, the ticker, Stop, the cancel path and the rebuild are what would
drift between two copies.

**A conversation can be CLEARED (`DELETE /notebooks/{id}/turns`), which is the other end of the same
fact**: regenerate reaches the last answer only, so clearing is the only honest way to undo a turn in
the middle, and turns were otherwise the one thing here that could only grow. Sources, notes, the
overview and the podcast are untouched and nothing is marked stale — an overview's `source_ids` are
about the CORPUS, which has not moved. The confirmation names what SURVIVES as well as what goes, since
losing sources is the fear a destructive control in the chat panel invites.

**The control hides itself when there is no conversation, kept in sync from the EXISTING
`chat:turnAdded`/`chat:rerender`/`notebook:switched` handlers rather than three new ones.** A second
subscription to one event inside one init is what `test_no_event_is_subscribed_twice_inside_one_init_function`
forbids: four inits in `app.js` spell the same event names, so a duplicate handler runs twice and reads
as a race that isn't one. That test is the only enforcement, which is why the rule lives here.

**Clearing is DISABLED while a question is in flight**: the server would delete the turns and then
`ask`'s own persist would append its answer to the now-empty list, so the conversation the reader just
cleared comes back with one entry in it. Stop is the control for a run in flight. The handler must also
pass the pending turn to `rebuildHistory` (or it deletes a running question's only Stop), must not null
`pendingTurn` (or `askQuestion`'s catch throws on a null and a failed run renders nothing at all), and
must capture `notebookGeneration` like every other awaiting flow here (or a notebook switch during the
DELETE wipes the NEW notebook's conversation).

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
