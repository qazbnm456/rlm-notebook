"""PDF ingestion: per-page text via `pypdfium2`, with hybrid OCR (`_ocr.py`) for scanned pages.

CLAUDE.md invariant 7: a page whose text layer extracts to (near-)nothing is rendered to an image
and dispatched to a locally-installed OCR backend (RapidOCR primary, Tesseract fallback — core
`dependencies` in pyproject.toml, always installed by a plain `uv sync`, not an opt-in extra).
`pypdfium2` (BSD-3-Clause/Apache-2.0, wraps Google's PDFium) replaces this project's former
`pymupdf`/`pymupdf4llm` dependency, which was dual-licensed AGPL-3.0-or-Artifex-commercial — see
the pymupdf-replacement design record for the full account of why that had to go.
"""

from __future__ import annotations

import pypdfium2 as pdfium

from ..schema import Source, SourceBlock
from ._ocr import ocr_image, scoreable_tokens, wordlike_ratio

#: A page's own text layer below this many stripped characters has nothing to compare and goes
#: straight to OCR. Literally 1, i.e. no text layer at all: this is the MISSING-layer test only.
#: pymupdf4llm's former ML classifier also caught a GARBLED-but-present layer; `_page_text` handles
#: that case separately now (invariant 74), and the two conditions stay distinct because one has no
#: alternative to weigh and the other has two readings to choose between.
_MIN_TEXT_CHARS = 1

#: Scale factor for rendering a textless page to an image before OCR — 2x roughly matches
#: pymupdf4llm's own former default of ~144-200 DPI at typical page sizes, verified to produce
#: OCR-legible output against a real rendered page during this feature's design.
_OCR_RENDER_SCALE = 2.0

#: A page whose text layer scores below this on `_ocr.wordlike_ratio` is SUSPECTED of having decoded
#: badly, and is OCR'd as well so the two can be compared (invariant 74). Not a verdict: it only
#: decides whether to spend the OCR. Measured — good documents' worst pages scored 0.79-0.99 while a
#: real scan's mis-decoded pages scored 0.63-0.80, so the two populations overlap and no threshold
#: can separate them. That is exactly why the decision is made by COMPARING afterwards.
_SUSPECT_TEXT_BELOW = 0.85

#: ...and the OCR result has to beat the text layer by this much to replace it. A bare `>` flipped a
#: perfectly good page on a rounding-level difference in testing. Measured margins on genuinely
#: mis-decoded pages were +0.20 and +0.27; the one page where the layer was fine lost by 0.06.
_OCR_REPLACES_TEXT_BY = 0.10

#: ...and it has to have READ a comparable amount of the page. Both scores are RATIOS with no
#: volume term, so without this a page of prose carrying one garbled figure block could be replaced
#: wholesale by an OCR pass that recovered only the caption — scoring 1.0 on nine words against 0.68
#: on ninety-two. Measured token shares: the two pages a real scan genuinely needed replaced scored
#: 0.39 and 0.45, a diagram page that must keep its layer scored 0.03, and the constructed
#: prose-for-a-caption loss scored 0.10. **The separation is narrow and cannot be tightened**: a
#: garbled layer fragments into MORE tokens than a clean OCR of the same page, so a high share is
#: exactly what a true replacement does NOT look like.
_OCR_MIN_TOKEN_SHARE = 0.25


def _page_text(page) -> str:
    """One page's text: its own layer when that is usable, OCR when it is not (invariants 7, 74).

    Two different conditions reach OCR here. A page with NO text layer has nothing to compare and
    OCR is simply the only source. A page WITH a text layer that reads like mis-decoded glyphs is
    OCR'd as a SECOND opinion, and the better of the two is kept — the text layer stays unless OCR
    clearly beats it, because a good text layer is better than any OCR of the same page and a
    suspicion is not evidence."""
    text = page.get_textpage().get_text_range().strip()
    if len(text) < _MIN_TEXT_CHARS:
        return ocr_image(page.render(scale=_OCR_RENDER_SCALE).to_pil()).strip()

    layer_score = wordlike_ratio(text)
    if layer_score is None or layer_score >= _SUSPECT_TEXT_BELOW:
        return text
    ocr_text = ocr_image(page.render(scale=_OCR_RENDER_SCALE).to_pil()).strip()
    ocr_score = wordlike_ratio(ocr_text)
    if ocr_score is None or ocr_score < layer_score + _OCR_REPLACES_TEXT_BY:
        return text
    if scoreable_tokens(ocr_text) < scoreable_tokens(text) * _OCR_MIN_TOKEN_SHARE:
        return text
    return ocr_text


def parse_pdf(path: str, source_id: str) -> Source:
    """Ingest a PDF. Each page becomes one citable `SourceBlock` at locator `"page:<n>"`
    (1-indexed). A page with no extractable text (OCR included) is skipped, not emitted as an
    empty block; the whole source is refused only if EVERY page comes back empty."""
    pdf = pdfium.PdfDocument(path)
    try:
        blocks: list[SourceBlock] = []
        for page_number, page in enumerate(pdf, start=1):
            text = _page_text(page)
            if text:
                blocks.append(SourceBlock(locator=f"page:{page_number}", text=text))
    finally:
        pdf.close()
    if not blocks:
        raise ValueError(f"no extractable text in {path!r}, even with OCR")
    return Source(id=source_id, kind="pdf", origin=path, blocks=blocks)
