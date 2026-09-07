# Invariant 57 — The overview is the threads first entry

**The chat overview is the THREAD's first entry, inside the scroller — not a panel pinned above it.**
As a sibling of `.chat-history` with `flex: 0 0 auto` and `max-height: 45%` it permanently owned up to
half the chat column; inside the scroller it simply scrolls away as the conversation grows. The
`max-height` was there for a real reason — as a sibling it was a flex item whose automatic minimum
size is its content, which would have collapsed `.chat-history` — and that reason evaporates once
there is no competing flex item.

**A returning reader must not LAND scrolled past it**: `chat:turnAdded` scrolls to the bottom, and
replaying a saved conversation fired it once per turn, so the overview started far above the fold.
Only a genuinely new turn scrolls now.

**Every path that redraws the thread goes through `rebuildHistory`**, which re-appends the overview
node; a `history.innerHTML = ""` that forgot to would silently delete it.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
