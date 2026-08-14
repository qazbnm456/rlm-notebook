"""OCR dispatch for a rendered PDF page image: RapidOCR primary, Tesseract fallback.

Extracted out of `parsers/pdf.py` (invariant 7's design record,
the pymupdf-replacement design record) so `parse_pdf` doesn't need to know which backend
actually produced a page's text — just whether OCR produced anything at all.

RapidOCR reports a bounding quad per detected region but no layout, and its regions arrive roughly
line-by-line ACROSS the full page — so a two-column scan comes back with its columns interleaved
mid-sentence. `reading_order` (invariant 73) puts the columns back in order using the coordinates
the detector already reported.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Above this share of regions crossing the page's horizontal centre, the page is not laid out in
#: two columns and is left exactly as the detector reported it. A two-column page crosses the centre
#: only on the few elements that span the measure (a banner heading, a figure/table caption, a
#: centred page number); a single-column page crosses it on nearly every body line. Measured on two
#: real papers: the two-column one scored 0.00-0.11 per page (one title page at 0.41), the
#: single-column one 0.04-0.88. A value that is too LOW only declines to improve a page; too HIGH
#: reorders one that was already correct — so the uncertainty from a two-document sample is spent on
#: the safe side.
_MAX_SPANNING_FRACTION = 0.15

#: (left edge, right edge, vertical centre, detection index, text) — a detection flattened to the
#: only numbers ordering needs. The vertical CENTRE rather than the top edge, so a slightly skewed
#: scan (or a line whose quad is taller on one side) still sorts against its neighbours by where it
#: sits. The detection INDEX is carried because it is the order regions are ultimately emitted in
#: (see `reading_order`), not merely how they arrived.
_Region = tuple[float, float, float, int, str]


def _flatten(index: int, box: Sequence[Sequence[float]], text: str) -> _Region:
    xs = [float(point[0]) for point in box] or [0.0]
    ys = [float(point[1]) for point in box] or [0.0]
    return min(xs), max(xs), sum(ys) / len(ys), index, text.strip()


def _order_band(band: list[_Region], centre: float) -> list[str]:
    """One horizontal band containing no region that crosses `centre`: read it as two columns when
    both sides are occupied, otherwise leave it alone. Each side keeps its detection order."""
    left: list[_Region] = []
    right: list[_Region] = []
    for region in sorted(band, key=lambda r: r[3]):
        # The caller has already peeled off every region crossing `centre`, so "does not end left
        # of it" means "starts right of it". Partitioned rather than filtered twice, because a
        # zero-width region sitting exactly ON the centre satisfies both tests and would otherwise
        # be emitted into both columns.
        (left if region[1] <= centre else right).append(region)
    if not left or not right:
        return [region[4] for region in left + right]
    return [region[4] for region in left] + [region[4] for region in right]


def reading_order(regions: Sequence[tuple[Sequence[Sequence[float]], str]]) -> str:
    """Join OCR'd text regions in reading order (CLAUDE.md invariant 73), from the bounding quads
    the detector already reported. A region CROSSING the content's horizontal centre spans both
    columns and closes the band above it; a band with regions on both sides of the centre is read as
    two columns, all of the left then all of the right, instead of line-by-line across both.

    Within a band nothing is re-sorted — the detector's own order is kept, and only the two columns
    are separated out of it. Sorting a band by vertical position instead measured WORSE on both
    layouts (a two-column paper 0.756 -> 0.743 against its own text layer, a single-column one
    0.774 -> 0.751): RapidOCR already emits a column's lines in reading order, and re-sorting by a
    quad's vertical centre only disturbs near-ties like a superscript or a slightly skewed line.

    Every rule degrades to the detector's order rather than to a wrong one: a page that does not
    look two-column is returned untouched, and if the centre lands INSIDE a column (margins lopsided
    enough to drag the content midpoint off the gutter) that column crosses it on every line, which
    is exactly the "not two-column" case."""
    items = [_flatten(i, box, text) for i, (box, text) in enumerate(regions) if text.strip()]
    if len(items) < 2:
        return " ".join(region[4] for region in items)
    centre = (min(region[0] for region in items) + max(region[1] for region in items)) / 2
    spanning = [region for region in items if region[0] < centre < region[1]]
    if len(spanning) > len(items) * _MAX_SPANNING_FRACTION:
        return " ".join(region[4] for region in items)

    # Bands are delimited by vertical position — that is the one thing only the geometry knows —
    # but each band's CONTENTS are emitted in detection order by `_order_band`.
    ordered: list[str] = []
    band: list[_Region] = []
    for region in sorted(items, key=lambda r: (r[2], r[0])):
        if region[0] < centre < region[1]:
            ordered.extend(_order_band(band, centre))
            ordered.append(region[4])
            band = []
        else:
            band.append(region)
    ordered.extend(_order_band(band, centre))
    return " ".join(ordered)


def _try_rapidocr(image) -> str | None:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    try:
        import numpy as np

        result, _ = RapidOCR()(np.array(image.convert("RGB")))
    except Exception:  # noqa: BLE001 — an OCR engine choking on an unusual rendered page must
        # fall through to the next backend (or to "no OCR text"), never take down ingestion of an
        # otherwise-fine multi-page PDF. Same "degrade, don't crash, at an extraction boundary"
        # posture this project's sibling family already uses at its own sandbox boundaries.
        return None
    if not result:
        return None
    text = reading_order([(box, text) for box, text, _ in result])
    return text or None


def _try_tesseract(image) -> str | None:
    try:
        import pytesseract
    except ImportError:
        return None
    try:
        # Tesseract does its own page segmentation (PSM 3 by default), columns included, so its
        # output needs no equivalent of `reading_order` — that reordering is specific to RapidOCR,
        # which reports regions without ever grouping them into a layout.
        text = pytesseract.image_to_string(image)
    except Exception:  # noqa: BLE001 — same reasoning as _try_rapidocr above.
        return None
    return text if text.strip() else None


def ocr_image(image) -> str:
    """RapidOCR primary, Tesseract fallback (CLAUDE.md invariant 7) — tried in that order, falling
    through on either an import failure OR a runtime failure/empty result, never raising from the
    first backend's own failure. Returns `""` (never raises) if NEITHER backend produces text —
    `parse_pdf` decides what an empty-after-OCR page means, this function doesn't."""
    return _try_rapidocr(image) or _try_tesseract(image) or ""
