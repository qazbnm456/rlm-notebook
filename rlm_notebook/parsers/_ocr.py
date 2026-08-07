"""OCR dispatch for a rendered PDF page image: RapidOCR primary, Tesseract fallback.

Extracted out of `parsers/pdf.py` (invariant 7's design record,
the pymupdf-replacement design record) so `parse_pdf` doesn't need to know which backend
actually produced a page's text — just whether OCR produced anything at all.
"""

from __future__ import annotations


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
    text = " ".join(t for _, t, _ in result if t.strip())
    return text or None


def _try_tesseract(image) -> str | None:
    try:
        import pytesseract
    except ImportError:
        return None
    try:
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
