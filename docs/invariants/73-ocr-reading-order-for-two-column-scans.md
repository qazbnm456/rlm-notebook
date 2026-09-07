# Invariant 73 — OCR reading order for two column scans

**RapidOCR's region coordinates decide reading order (`_ocr.reading_order`) — joining its regions in
detection order interleaves the columns of a two-column scan.** RapidOCR reports a bounding quad per
region and no layout, and emits regions roughly line-by-line ACROSS the full page, so
`" ".join(text for _, text, _ in result)` produced prose that jumps between columns mid-sentence.
Measured against the same pages' own text layer, over two real papers: a two-column paper scored
**0.425 -> 0.756**, a single-column one 0.802 -> 0.792. **The text-layer path was never affected** —
`pypdfium2` reads a LaTeX two-column paper in correct column order already, because the content stream
is written a column at a time — so this is an OCR-path defect only, and only scanned/textless pages
reach it (invariant 7).

**Three rules, each degrading to the detector's own order rather than to a wrong one:**

- **A page is left EXACTLY as detected unless it looks two-column** — above `_MAX_SPANNING_FRACTION`
  (0.15) of regions crossing the content's horizontal centre, nothing is touched. A two-column page
  crosses the centre only on what spans the measure (a banner heading, a caption, a centred page
  number); a single-column page crosses it on nearly every body line. Too low a value merely declines
  to improve a page, too high reorders one that was already right, so it is set on the SAFE side.
  Calibrated on rendered digital PDFs, then confirmed against the population it actually serves — only
  a page with NO text layer reaches OCR — on a real two-column scan, and controlled skew does not
  reach the threshold. Figures in `CHANGELOG.md`.
- **A centre-crossing region is a band BOUNDARY, never a veto.** The first draft distrusted any band
  holding a centre-crosser, and a real two-column page's single crossing region — the page number
  centred in its footer — cost the whole page its column order. Boundaries cut the page into bands and
  each band is column-split on its own.
- **Within a band nothing is re-sorted; only the two columns are separated out of the detector's
  order.** Sorting a band by vertical position measured WORSE on BOTH layouts: RapidOCR already emits
  a column's lines in reading order, and re-sorting on a quad's vertical centre only disturbs
  near-ties like a superscript or a skewed line. This is the half that is counter-intuitive and the
  half a later reader is most likely to "fix".

**`_order_band` partitions rather than filtering twice**, because a zero-width region sitting exactly ON
the centre satisfies both the left and the right test and would be emitted into both columns.

**Tesseract is deliberately NOT given the same treatment**: it does its own page segmentation, columns
included, and reports text already in reading order.

**The claim is reproducible in CI, on two levels.** `tests/fixtures/ocr_two_column_page.json`
carries 105 boxes measured off a rendered two-column page, TEXT EXCLUDED so the fixture is a
layout and not someone's prose; it asserts the STRUCTURE — whole left column, whole right, then
the centred footer — rather than freezing an output list, with gutter bounds from the measurement
rather than from the code under test. Above that, two tests run the REAL OCR stack end to end over
a two-column page built by `_pdf_fixtures.make_two_column_pdf` from prose this project owns, since
the recorded accuracy figures were measured on papers that cannot be redistributed and were
therefore unreproducible. **They assert the STRUCTURE and the DIRECTION, never a figure**: an exact
ratio would move with an OCR version, while "every left-column line precedes every right-column
line" does not depend on how well the characters were read at all.

Neither subsumes the synthetic fixtures: the frozen page is a single band, so the band key and the
vertical-centre choice are invisible in it.

**The known cost, inspected rather than inferred**: a wide TABLE on a single-column page can be split
down the middle, and two attention-visualisation figure pages measured -0.08/-0.06. Both were read
directly — a flattened table and a scatter of figure labels are word soup under either ordering, which
is why that cost is accepted against a +0.331 gain on two-column prose.

**MORE than two columns is out of scope, and declines by two different mechanisms.** An ODD count
declines itself: a three-column scan puts its middle column across the centre, so it crosses on nearly
every line and the page-level guard fires — the same arithmetic that recognises a single-column page.
An EVEN count does NOT, and that gap was real: a four-column page has its centre in the middle gutter,
nothing spans it, and the split cut the page in half and then interleaved the rows inside each half —
the exact defect this module exists to prevent, at half scale. `_column_count` closes it by projecting
a band onto the x-axis and counting the runs a real gutter separates; above two, the band is returned
in detection order.

**`_MIN_GUTTER_SHARE` (0.02) has about 2x of margin, and the hazard of raising it runs UPWARD**:
the real two-column page in `tests/fixtures/` has a 38px gutter across 996px of content, i.e. 0.038.
A higher value merges runs and LOWERS the count — and since the only test is `> 2`, a count of 1
falls through to the split exactly as 2 does, so a two-column page keeps being reordered at any value.
What breaks is the DECLINE: a four-column page merges to two or fewer and is halved again. The count
is used only to ask "is this the two-column case", never to locate a column — that stays `centre`'s
job.

**Counted over the whole PAGE, never one band.** A sparse band — a few short fragments between two
spanning elements — reads its own intra-column whitespace as a gutter, counts 3 and declines,
returning the interleaved order this exists to remove. **The real fixture does not demonstrate this
and cannot**: it carries one spanning region, so that page is a single band of 104 and both schemes
agree on it. The supporting number is a claim about PLAUSIBLE bands rather than observed ones —
measured over contiguous windows of the fixture's own geometry — and carries that hedge in
`CHANGELOG.md`.

**A layout-detection MODEL was evaluated for this and rejected** (`PicoDet-S_layout_3cls`): its classes
are table/image/stamp with no text class, so it cannot do the one thing that was actually broken. See
`CHANGELOG.md` for the full evaluation, including which checkpoint would be the right one if this is
ever revisited.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
