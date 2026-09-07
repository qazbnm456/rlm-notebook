# Invariant 55 — Markdown builds nodes and links are inert

**Markdown in an answer is rendered by a HAND-WRITTEN renderer that builds DOM nodes, and a link in
it is shown but NOT navigable.** Answers arrive full of raw `**bold**`, `## heading` and `- list`
characters because the model writes markdown whether or not anyone asked.

**No library and no HTML strings**, which is invariant 29's rule stated where it costs the most.
Every string here came out of a model that has been reading source content an attacker may have
written (invariant 6); one missed `esc()` in a string-building renderer is an XSS sink, and building
nodes removes the failure mode instead of guarding it.
**`test_the_markdown_renderer_builds_nodes_rather_than_markup` pins the node-building rule.** The
NAVIGABLE-LINK rule below is a different test with a different sink list
(`test_the_markdown_renderer_never_creates_a_navigable_link`), and its coverage floor is part of
that rule: mutation testing got THREE links past its first version — `setAttribute("href", …)`, a
template-literal ``createElement(`a`)``, and a click handler assigning `window.location`. A future
widening must still catch all three. Do not merge the two in your head: widening the wrong one
leaves the XSS guard exactly as it was.

**A `[label](url)` renders its label with the URL revealed on hover and COPIED on click, never an
`<a href>`.** Invariant 1 refuses to let the MODEL reach a URL because a prompt-injected source could
steer it into exfiltrating notebook contents; a clickable link in an answer is the same hazard with
the READER's click as the transport, arriving dressed as a citation-grounded reference. A stated
trade — `createElement("a")` is exactly what a later edit reaches for, since the renderer has the URL
in hand. Copy-on-click exists because CSS generated content is not selectable, so "shown so a reader
can copy it" was not otherwise true.

**The renderer never creates a text node.** It walks RAW OFFSETS into the original string and appends
through `emit`, which is where a citation range is split out — that is what lets block structure and
citation strokes compose rather than one being applied on top of the other's output. A renderer that
made its own text nodes would silently produce prose no stroke can reach.

**`data-reference` is stamped AFTER the whole answer is built, not decided while emitting.** A stroke
crossing an inline `**bold**` is emitted as several fragments, and an `isLast` test of
`sliceTo === match.end` never fires when a span's final characters are syntax the renderer DROPS (a
closing `**`, a backtick, a link's `](url)`) — so the stroke got NO number while the References panel
numbered it anyway, which is the two-lists-to-join-by-eye that invariant 58 exists to remove.
Collecting the fragments and stamping the last one afterwards is decided where every fragment is
known.

**Emphasis follows a simplified CommonMark flanking rule**, without which `3 * 4 * 5` renders as
`3 <em>4</em> 5` and `my_var and other_var_name` mangles — multiplication and snake_case identifiers
both appear in this project's own subject matter.

**Known limits**: a blockquote does not nest other blocks; a `.md-link` tooltip inside a table is
clipped by `.md-table-wrap`'s scroller (invariant 54's uncovered ancestor case, mitigated by
copy-on-click working everywhere); and `renderMdList` recurses per indent level, bounded in practice
by the corpus cap.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
