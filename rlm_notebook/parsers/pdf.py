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
from ._ocr import ocr_image

#: A page's own text layer below this many stripped characters is treated as needing OCR — a
#: deliberately simpler heuristic than pymupdf4llm's former ML-based classifier (which also caught
#: a GARBLED-but-present text layer, not just a missing one); this project's own scanned-PDF use
#: case is a missing text layer, not a garbled one, so this trade is accepted, not silently assumed
#: equivalent — see the design doc above.
_MIN_TEXT_CHARS = 1

#: Scale factor for rendering a textless page to an image before OCR — 2x roughly matches
#: pymupdf4llm's own former default of ~144-200 DPI at typical page sizes, verified to produce
#: OCR-legible output against a real rendered page during this feature's design.
_OCR_RENDER_SCALE = 2.0


def parse_pdf(path: str, source_id: str) -> Source:
    """Ingest a PDF. Each page becomes one citable `SourceBlock` at locator `"page:<n>"`
    (1-indexed). A page with no extractable text (OCR included) is skipped, not emitted as an
    empty block; the whole source is refused only if EVERY page comes back empty."""
    pdf = pdfium.PdfDocument(path)
    try:
        blocks: list[SourceBlock] = []
        for page_number, page in enumerate(pdf, start=1):
            text = page.get_textpage().get_text_range().strip()
            if len(text) < _MIN_TEXT_CHARS:
                text = ocr_image(page.render(scale=_OCR_RENDER_SCALE).to_pil()).strip()
            if text:
                blocks.append(SourceBlock(locator=f"page:{page_number}", text=text))
    finally:
        pdf.close()
    if not blocks:
        raise ValueError(f"no extractable text in {path!r}, even with OCR")
    return Source(id=source_id, kind="pdf", origin=path, blocks=blocks)
