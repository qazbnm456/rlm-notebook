from __future__ import annotations

import pytest
from _pdf_fixtures import make_blank_pdf, make_image_only_pdf, make_text_pdf

from rlm_notebook.parsers import pdf as pdf_module
from rlm_notebook.parsers.pdf import parse_pdf

#: A text layer that reads like mis-decoded glyphs — no vowels, case flipping mid-token. Taken from
#: the shape of a real one (an IRE scan whose chart pages decoded to `UN ELTN NII PIN COCO`).
_GARBLED = "UN ELTN NII PIN COCO CNC TTT BEANseGE THT Srasasege NBas HDS"


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


def test_parse_pdf_replaces_a_garbled_text_layer_when_ocr_is_clearly_better(tmp_path, monkeypatch):
    """Invariant 74: a page WITH a text layer that reads like mis-decoded glyphs is OCR'd as a
    second opinion, and OCR wins only when it clearly beats it."""
    pdf_path = tmp_path / "garbled.pdf"
    make_text_pdf(pdf_path, [_GARBLED])
    recovered = "The incomplete Toronto function and its use in radar range calculation"
    monkeypatch.setattr(pdf_module, "ocr_image", lambda image: recovered)

    source = parse_pdf(str(pdf_path), "s1")

    assert source.blocks[0].text == recovered


def test_parse_pdf_keeps_a_garbled_text_layer_when_ocr_is_no_better(tmp_path, monkeypatch):
    """A suspicion is not evidence. If OCR does not clearly beat the layer, the layer stands —
    this is what makes a generous suspicion threshold cost only time, never quality."""
    pdf_path = tmp_path / "garbled.pdf"
    make_text_pdf(pdf_path, [_GARBLED])
    monkeypatch.setattr(pdf_module, "ocr_image", lambda image: "NII CNC TTT ELTN PIN THT NBas HDS")

    source = parse_pdf(str(pdf_path), "s1")

    assert "ELTN" in source.blocks[0].text


def test_parse_pdf_keeps_a_garbled_layer_when_ocr_cannot_be_scored(tmp_path, monkeypatch):
    """A diagram page OCRs to a handful of numeric labels, which `wordlike_ratio` scores as None.
    An unscoreable second opinion must not displace the first."""
    pdf_path = tmp_path / "garbled.pdf"
    make_text_pdf(pdf_path, [_GARBLED])
    monkeypatch.setattr(pdf_module, "ocr_image", lambda image: "0.5 1.0 2.0 Fig 10")

    source = parse_pdf(str(pdf_path), "s1")

    assert "ELTN" in source.blocks[0].text


def test_parse_pdf_never_ocrs_a_healthy_text_layer(tmp_path, monkeypatch):
    """The gate, not just the comparison: a page whose layer reads fine must not even SPEND an OCR
    pass — that is the whole cost model, and a `>` comparison alone once flipped a good page on a
    rounding-level difference."""
    pdf_path = tmp_path / "fine.pdf"
    make_text_pdf(pdf_path, ["The encoder is composed of a stack of identical layers."])

    def _fail(image):
        raise AssertionError("a healthy text layer must not be sent to OCR")

    monkeypatch.setattr(pdf_module, "ocr_image", _fail)

    source = parse_pdf(str(pdf_path), "s1")

    assert "encoder" in source.blocks[0].text


def test_parse_pdf_raises_when_every_page_is_empty(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    make_blank_pdf(pdf_path)

    with pytest.raises(ValueError):
        parse_pdf(str(pdf_path), "s1")
