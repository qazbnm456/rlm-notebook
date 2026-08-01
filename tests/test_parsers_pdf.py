from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz")  # pymupdf; also what parse_pdf's pymupdf4llm dependency needs

from rlm_notebook.parsers.pdf import parse_pdf


def _make_text_pdf(path, pages: list[str]) -> None:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(str(path))


def test_parse_pdf_one_block_per_page_with_page_locator(tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    _make_text_pdf(pdf_path, ["Apples are red or green.", "Oranges are orange."])

    source = parse_pdf(str(pdf_path), "s1")

    assert source.kind == "pdf"
    assert source.origin == str(pdf_path)
    assert [b.locator for b in source.blocks] == ["page:1", "page:2"]
    assert "Apples" in source.blocks[0].text
    assert "Oranges" in source.blocks[1].text


def test_parse_pdf_ocrs_an_image_only_page(tmp_path):
    """A page with NO text layer (rendered to an image, no embedded text) is still extracted via
    pymupdf4llm's built-in hybrid OCR — CLAUDE.md invariant 6. Slower than the text-layer test
    (loads a local OCR model), but this is the one guarantee this module exists to make."""
    text_pdf = tmp_path / "source.pdf"
    _make_text_pdf(text_pdf, ["Apples are red or green."])
    pix = fitz.open(str(text_pdf))[0].get_pixmap(dpi=200)
    image_path = tmp_path / "page.png"
    pix.save(str(image_path))

    scanned_pdf = tmp_path / "scanned.pdf"
    doc = fitz.open()
    page = doc.new_page(width=pix.width, height=pix.height)
    page.insert_image(page.rect, filename=str(image_path))
    doc.save(str(scanned_pdf))
    assert not fitz.open(str(scanned_pdf))[0].get_text().strip()  # sanity: truly no text layer

    source = parse_pdf(str(scanned_pdf), "s1")

    assert len(source.blocks) == 1
    assert source.blocks[0].locator == "page:1"
    assert "Apples" in source.blocks[0].text


def test_parse_pdf_raises_when_every_page_is_empty(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))

    with pytest.raises(ValueError):
        parse_pdf(str(pdf_path), "s1")
