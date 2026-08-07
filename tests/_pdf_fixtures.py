"""Shared PDF test-fixture builders using `reportlab` (BSD) — a `dev`-only dependency, never a
runtime dependency of the shipped package. Replaces this project's former `fitz` (pymupdf) based
fixture-building, which relied on pymupdf being present as a (now-removed) AGPL runtime
dependency — see CLAUDE.md invariant 7 / the pymupdf-replacement design record. Not a
`test_*.py` file itself, so pytest never collects it directly.
"""

from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def make_text_pdf(path: str | Path, pages: list[str]) -> None:
    """One page per string in `pages`, each with real, extractable text."""
    c = canvas.Canvas(str(path), pagesize=letter)
    for text in pages:
        c.drawString(72, 700, text)
        c.showPage()
    c.save()


def make_text_pdf_bytes(pages: list[str]) -> bytes:
    """Same as `make_text_pdf`, but returns raw PDF bytes — for call sites (e.g.
    `ingest_uploaded_file`) that take bytes directly rather than a file path."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    for text in pages:
        c.drawString(72, 700, text)
        c.showPage()
    c.save()
    return buffer.getvalue()


def make_image_only_pdf(path: str | Path, text: str, *, size: tuple[int, int] = (800, 200)) -> None:
    """One page with NO text layer at all — `text` is baked into pixels (a PIL-drawn image), the
    same "genuinely no text layer, needs OCR" shape a real scanned page has."""
    from PIL import Image, ImageDraw

    width, height = size
    image = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(image)
    draw.text((20, height // 2 - 10), text, fill="black")
    image_path = Path(path).with_suffix(".png")
    image.save(image_path)

    c = canvas.Canvas(str(path), pagesize=size)
    c.drawImage(str(image_path), 0, 0, width=width, height=height)
    c.showPage()
    c.save()


def make_blank_pdf(path: str | Path) -> None:
    """One page, no text, no image — genuinely empty."""
    c = canvas.Canvas(str(path), pagesize=letter)
    c.showPage()
    c.save()
