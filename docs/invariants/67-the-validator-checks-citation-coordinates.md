# Invariant 67 — The validator checks citation coordinates

**The pre-SUBMIT validator checks each citation's COORDINATE against the corpus this run was given, and
the six tasks share ONE base class instead of six identical `__init__`s.** The observed failure is
specific: every web source is one block with locator `whole`, and a model wrote the SECTION HEADING it
was citing into `locator`, turning every citation in an overview unverified.

**`citations.verify_citations` remains the guarantee (invariant 5); this is the early warning** — the
same ground truth, computed from the SAME blob, applied while the model can still fix it rather than
after the reader has found it. `instructions.coordinates_in` extracts every `source_id|locator` pair
that actually occurs as a marker; `_cited_coordinates` walks the output model STRUCTURALLY (anything
carrying both fields) rather than importing `Citation`, so a future citation-shaped model is covered
without anyone remembering this function.

**The rejection shows a REAL coordinate, not just which ones are wrong.** The failure is a model
composing a locator out of the passage's own wording, and a message that only says "wrong" invites it to
compose a different sentence.

**It fails OPEN when the blob yields no markers at all**, deliberately rather than as an oversight of
invariant 66's rule. An empty set means "we do not know what is valid here"; rejecting every citation of
a legitimate run is far worse than letting server-side verification catch an invented one. The trigger
is stated and tested, which is the difference from the silent kind.

**`instructions.GroundedTask` is the base all six tasks share.** The check needs a per-RUN value, which
a `ClassVar` tool list composed at import time cannot hold: `arun` captures the blob before the model
can cite anything, and the validator is built per instance from `output_model`. That deleted six
byte-identical `__init__`s AND six `tools: ClassVar = [...]` lines — six chances for one task to get a
weaker validator, which is exactly how the marker check spent a slice living only on the podcast.

**Consequence: `Task.tools` is now EMPTY at class level.** Tests asserting invariant 1 against that
ClassVar — and `rlm_harness.testing.assert_repl_safe` alongside it, which is half of what those tests
check — would pass against a tuple of nothing, checking precisely what a run does not use. They
construct an instance instead, which makes them stronger than before rather than merely repaired.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
