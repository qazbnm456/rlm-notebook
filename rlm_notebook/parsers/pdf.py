"""PDF ingestion: per-page text via `pymupdf4llm`, with automatic hybrid OCR for scanned pages.

CLAUDE.md invariant 6: `pymupdf4llm.to_markdown(path, page_chunks=True)` auto-detects a page with
no text layer and dispatches it to a locally-installed OCR backend (RapidOCR primary, Tesseract
fallback — the `ocr` extra) with no extra wiring needed here; verified end to end against a
real image-only PDF page before landing this. Ships enabled by default (the extra is not optional
at the dependency-resolution level for a source of this kind — see pyproject.toml), not merely
pluggable — the pitfall named in CLAUDE.md invariant 6.
"""

from __future__ import annotations

import pymupdf4llm

from ..schema import Source, SourceBlock


def parse_pdf(path: str, source_id: str) -> Source:
    """Ingest a PDF. Each page becomes one citable `SourceBlock` at locator `"page:<n>"`
    (1-indexed) — pymupdf4llm's natural per-page granularity, which gives an OCR'd page the same
    citable grain as a text-layer one. A page with no extractable text (OCR included) is skipped,
    not emitted as an empty block; the whole source is refused only if EVERY page comes back empty.
    """
    pages = pymupdf4llm.to_markdown(path, page_chunks=True)
    blocks: list[SourceBlock] = []
    for page in pages:
        text = (page.get("text") or "").strip()
        if not text:
            continue
        page_number = page.get("metadata", {}).get("page_number")
        blocks.append(SourceBlock(locator=f"page:{page_number}", text=text))
    if not blocks:
        raise ValueError(f"no extractable text in {path!r}, even with OCR")
    return Source(id=source_id, kind="pdf", origin=path, blocks=blocks)
