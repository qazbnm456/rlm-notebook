from __future__ import annotations

import pytest
from _pdf_fixtures import make_blank_pdf, make_image_only_pdf, make_text_pdf

from rlm_notebook.parsers.pdf import parse_pdf


def test_parse_pdf_one_block_per_page_with_page_locator(tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    make_text_pdf(pdf_path, ["Apples are red or green.", "Oranges are orange."])

    source = parse_pdf(str(pdf_path), "s1")

    assert source.kind == "pdf"
    assert source.origin == str(pdf_path)
    assert [b.locator for b in source.blocks] == ["page:1", "page:2"]
    assert "Apples" in source.blocks[0].text
    assert "Oranges" in source.blocks[1].text


def test_parse_pdf_ocrs_an_image_only_page(tmp_path):
    """A page with NO text layer (rendered to an image, no embedded text) is still extracted via
    `parsers/_ocr.py`'s hybrid OCR — CLAUDE.md invariant 7. Slower than the text-layer test (loads
    a local OCR model), but this is the one guarantee this module exists to make."""
    scanned_pdf = tmp_path / "scanned.pdf"
    make_image_only_pdf(scanned_pdf, "Apples are red or green.")

    source = parse_pdf(str(scanned_pdf), "s1")

    assert len(source.blocks) == 1
    assert source.blocks[0].locator == "page:1"
    assert "Apples" in source.blocks[0].text


def test_parse_pdf_raises_when_every_page_is_empty(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    make_blank_pdf(pdf_path)

    with pytest.raises(ValueError):
        parse_pdf(str(pdf_path), "s1")
