# Invariant 50 — Removal ended append only source ids

**A source can be REMOVED now, which ended append-only id numbering — and the survivors are never
renumbered.** `notebook.next_source_id` derives from the MAX id in use; `len(sources) + 1` was
correct only while sources were append-only, and the moment removal existed it produced TWO live
sources under one id, with `Corpus.get` resolving whichever it reaches first, so a stored citation
reads the wrong text — exactly what invariant 12 forbids, and the identical bug `_next_note_id`
was written for (invariant 32) one field over.

**There are TWO append sites.** `promote_note` appends to `notebook.sources` DIRECTLY rather than
through `append_sources`, and it is the worse of the two, because promotion is the ONLY thing that
makes a note citable — a colliding promoted note is unreachable by any citation.

**`remove_source` deletes the first match by index rather than filtering every id-equal entry, and
RAISES on a miss.** `mutate_notebook` writes the file unless the delta raises, so returning `False`
meant a 404-ing DELETE still did a full save and bumped the mtime invariant 53 made the picker's
sort key.

**Nothing is renumbered on removal, and that is what makes removal safe to offer.** A citation
pointing at the removed source comes back UNVERIFIED with a reason (invariants 5 and 11) rather
than silently resolving to a different source's text, and persisted artifacts are marked STALE by
invariant 38's set-equality comparison.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
