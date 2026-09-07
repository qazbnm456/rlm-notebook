# Invariant 61 — Cheap Predict callers read an excerpt

**The cheap `dspy.Predict` callers read `Corpus.excerpt`, never `blob()[:n]` — a prefix is source ONE,
not the notebook.** `naming.SuggestTitle` and `naming.SuggestLanguage` cannot read a multi-MB corpus
(invariant 37), so they get a window; but the blob concatenates sources IN ORDER, so a 69,859-character
first source against a 4,000-character budget made sources two through four invisible — a four-source
notebook got titled by transliterating source one's own paper title. **Language resolution read the
same prefix, and that is the worse half**: a notebook whose later sources are in another language would
resolve the wrong one, and invariant 39 then persists that guess and stops re-resolving.

`excerpt(n)` gives every source an equal share taken from its START — a paper, a page or a report
states its subject in the opening lines. The prompt matches: name what the COLLECTION is about, with
"translate source one's title" as the named failure mode.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
