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

#: A two-column page's columns, as the fixture builder draws them. Kept as data rather than inline
#: so a test can assert the ORDER the columns should come back in without restating the strings.
TWO_COLUMN_LEFT = [
    "The encoder is composed of a stack of",
    "identical layers and each layer has two",
    "sub layers which are applied in turn to",
    "every position of the input sequence in",
    "the usual way described by the authors",
    "of the original paper on this subject",
]
TWO_COLUMN_RIGHT = [
    "Experimental results on the benchmark",
    "show that the proposed method improves",
    "accuracy while reducing the number of",
    "parameters required to reach the same",
    "level of performance as the strongest",
    "baseline reported in the literature",
]


def make_two_column_pdf(path: str | Path) -> None:
    """One page laid out in TWO COLUMNS, with a real text layer and a clean gutter.

    Prose this project owns, so the page an OCR claim is measured on can live in the repo — the
    accuracy figures recorded for invariant 73 came from real papers that cannot be redistributed,
    which left the headline claim unreproducible in CI. Drawn at coordinates rather than flowed, so
    the gutter is a property of the fixture and not of a layout engine's decisions.
    """
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica", 11)
    for i, line in enumerate(TWO_COLUMN_LEFT):
        c.drawString(60, 700 - i * 20, line)
    for i, line in enumerate(TWO_COLUMN_RIGHT):
        c.drawString(330, 700 - i * 20, line)
    c.showPage()
    c.save()

#: One column's worth of lines, wide enough that each crosses the page's horizontal centre — which
#: is what makes a single-column page recognisable to `_ocr.reading_order`'s page-level guard.
SINGLE_COLUMN_LINES = [
    "The encoder is composed of a stack of identical layers and each layer",
    "has two sub layers which are applied in turn to every position of the",
    "input sequence in the usual way described by the original authors of",
    "the paper that first introduced this particular arrangement of parts",
    "together with the experiments they ran to justify each of its pieces",
]


def make_single_column_pdf(path: str | Path) -> None:
    """One page of ordinary single-column prose, as SEVERAL drawn lines.

    `make_text_pdf` draws one unwrapped string per page, so OCR returns a single region and
    `reading_order` short-circuits before any layout rule runs — a test written against that fixture
    passes without reaching the guard it names.
    """
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica", 11)
    for i, line in enumerate(SINGLE_COLUMN_LINES):
        c.drawString(60, 700 - i * 20, line)
    c.showPage()
    c.save()

