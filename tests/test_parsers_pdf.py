from __future__ import annotations

import logging

import pytest
from _pdf_fixtures import make_blank_pdf, make_image_only_pdf, make_text_pdf

from rlm_notebook.parsers import _ocr
from rlm_notebook.parsers import pdf as pdf_module
from rlm_notebook.parsers.pdf import (
    _OCR_REPLACES_TEXT_BY,
    _SUSPECT_TEXT_BELOW,
    parse_pdf,
)

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
    this is what makes a generous suspicion threshold cost only time, never quality.

    The OCR fixture shares NO token with the layer, deliberately. A first version reused `ELTN` in
    both and asserted on it, so the assertion held whichever text was returned: deleting the whole
    comparison from `_page_text` left the suite green."""
    pdf_path = tmp_path / "garbled.pdf"
    make_text_pdf(pdf_path, [_GARBLED])
    ocr = "QQR MMPF ZXCV KLPN WRTB VVGH JJKD PPLM"
    monkeypatch.setattr(pdf_module, "ocr_image", lambda image: ocr)

    source = parse_pdf(str(pdf_path), "s1")

    assert source.blocks[0].text != ocr
    assert "ELTN" in source.blocks[0].text


def test_parse_pdf_requires_the_margin_not_merely_a_higher_score(tmp_path, monkeypatch):
    """`_OCR_REPLACES_TEXT_BY` pinned from both sides: beating the layer is not enough, beating it
    by the margin is. A bare `>` once flipped a healthy page on a rounding-level difference."""
    pdf_path = tmp_path / "garbled.pdf"
    make_text_pdf(pdf_path, [_GARBLED])
    layer_score = _ocr.wordlike_ratio(_GARBLED)

    def _ocr_scoring(target: float) -> str:
        """Alphabetic tokens, `target` of them wordlike — same token count as the layer, so only
        the score decides."""
        total = _ocr.scoreable_tokens(_GARBLED)
        good = round(target * total)
        return " ".join(["alpha"] * good + ["CNC"] * (total - good))

    just_over = _ocr_scoring(layer_score + _OCR_REPLACES_TEXT_BY / 2)
    monkeypatch.setattr(pdf_module, "ocr_image", lambda image: just_over)
    assert "ELTN" in parse_pdf(str(pdf_path), "s1").blocks[0].text

    clears_it = _ocr_scoring(min(1.0, layer_score + _OCR_REPLACES_TEXT_BY * 2))
    monkeypatch.setattr(pdf_module, "ocr_image", lambda image: clears_it)
    assert "ELTN" not in parse_pdf(str(pdf_path), "s1").blocks[0].text


def test_parse_pdf_will_not_trade_a_page_of_prose_for_a_short_ocr_win(tmp_path, monkeypatch):
    """Both scores are RATIOS. Without a volume term, a page carrying one garbled figure block is
    replaced wholesale by an OCR pass that recovered only the caption.

    The OCR fixture must clear `_MIN_SCORED_TOKENS`, or this exits through the `ocr_score is None`
    arm one line earlier and pins nothing — the first version had six tokens and stayed green with
    the whole volume guard deleted. Check WHICH branch a test leaves through, not just that it
    passes."""
    pdf_path = tmp_path / "mostly-prose.pdf"
    prose = (
        "The encoder is composed of a stack of identical layers and each layer has two sub-layers "
        "which are applied in turn to every position of the input sequence in the usual way. "
    )
    layer = prose + _GARBLED + " " + _GARBLED
    caption = "Figure one shows the residual building block used here"

    # Every condition the volume guard needs in order to be the thing that decides. Asserted rather
    # than assumed: the first two versions of this test each exited through an earlier arm — one
    # below the token floor, one above the suspicion gate — and stayed green with the guard deleted.
    layer_score = _ocr.wordlike_ratio(layer)
    assert layer_score < _SUSPECT_TEXT_BELOW, "layer must be suspected, or no OCR is even run"
    assert _ocr.scoreable_tokens(caption) >= _ocr._MIN_SCORED_TOKENS, "OCR must be scoreable"
    assert _ocr.wordlike_ratio(caption) >= layer_score + _OCR_REPLACES_TEXT_BY, "OCR must win on score"

    make_text_pdf(pdf_path, [layer])
    monkeypatch.setattr(pdf_module, "ocr_image", lambda image: caption)

    source = parse_pdf(str(pdf_path), "s1")

    assert "encoder" in source.blocks[0].text
    assert source.blocks[0].text != caption


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


def test_parse_pdf_reports_what_the_second_opinions_cost(tmp_path, monkeypatch, caplog):
    """A suspect page costs a full OCR pass, and from the outside that is indistinguishable from a
    hang. One line per document, only when it happened, naming how many pages paid and how many the
    payment changed."""
    pdf_path = tmp_path / "garbled.pdf"
    # Three pages, two of them suspect, one of those replaced — four DIFFERENT numbers, so swapping
    # any two of them in the format string fails. Equal counts made the first version unable to tell
    # "pages" from "suspected" from "replaced" (the same reasoning invariant 44 records for offsets).
    # A BLANK page too, so `len(pdf)` and `len(blocks)` differ: the line counts the document's
    # pages, not the ones that yielded text, and swapping them would misreport every scan that has
    # an empty leaf in it.
    healthy = "The encoder is composed of a stack of identical layers in the usual way"
    make_text_pdf(pdf_path, [_GARBLED, _GARBLED, healthy, ""])
    recovered = "The incomplete Toronto function and its use in radar range calculation"
    calls = {"n": 0}

    def _ocr_once(image):
        """Wins on the first suspect page, loses on the second, and finds nothing on the blank one —
        so `pages`, `suspected` and `replaced` are three different numbers. The blank page reaches
        OCR through the NO-text-layer arm and must come back empty, or the stub hands it text a real
        OCR pass would never find and `len(blocks)` silently equals `len(pdf)` again."""
        calls["n"] += 1
        if calls["n"] == 1:
            return recovered
        if calls["n"] == 2:
            return "QQR MMPF ZXCV KLPN WRTB VVGH JJKD PPLM"
        return ""

    monkeypatch.setattr(pdf_module, "ocr_image", _ocr_once)

    with caplog.at_level(logging.INFO, logger=pdf_module.__name__):
        parse_pdf(str(pdf_path), "s1")

    assert "2 of 4 page(s) had a suspect text layer" in caplog.text
    assert "1 replaced" in caplog.text


def test_parse_pdf_reports_a_second_opinion_even_when_nothing_was_replaced(tmp_path, monkeypatch, caplog):
    """The line answers "why was that slow", so it must fire on the case that dominates a real
    document: pages that PAID for an OCR pass and kept their own text anyway. On the 260-page scan
    this feature was built for, most of the 61 suspected pages were not replaced — gating the log on
    `replaced` would silence it exactly there."""
    pdf_path = tmp_path / "garbled.pdf"
    make_text_pdf(pdf_path, [_GARBLED])
    monkeypatch.setattr(pdf_module, "ocr_image", lambda image: "QQR MMPF ZXCV KLPN WRTB VVGH JJKD")

    with caplog.at_level(logging.INFO, logger=pdf_module.__name__):
        source = parse_pdf(str(pdf_path), "s1")

    assert "ELTN" in source.blocks[0].text, "precondition: the layer must have been KEPT"
    assert "1 of 1 page(s) had a suspect text layer" in caplog.text
    assert "0 replaced" in caplog.text


def test_parse_pdf_says_nothing_about_an_ordinary_document(tmp_path, caplog):
    """The line is evidence that something unusual happened, so a healthy PDF must not emit it."""
    pdf_path = tmp_path / "fine.pdf"
    make_text_pdf(pdf_path, ["The encoder is composed of a stack of identical layers."])

    with caplog.at_level(logging.INFO, logger=pdf_module.__name__):
        parse_pdf(str(pdf_path), "s1")

    # Scoped to THIS module's logger: `caplog.text` collects every logger, so an unrelated
    # warning from the OCR stack would fail this for the wrong reason.
    assert [r for r in caplog.records if r.name == pdf_module.__name__] == []


def test_parse_pdf_does_not_count_a_page_with_no_text_layer_as_a_second_opinion(tmp_path, caplog):
    """OCR on a textless page is the only source of text, not a speculative second reading — its
    cost is unavoidable and counting it would make the report meaningless."""
    scanned_pdf = tmp_path / "scanned.pdf"
    make_image_only_pdf(scanned_pdf, "Apples are red or green.")

    with caplog.at_level(logging.INFO, logger=pdf_module.__name__):
        parse_pdf(str(scanned_pdf), "s1")

    # Scoped to THIS module's logger: `caplog.text` collects every logger, so an unrelated
    # warning from the OCR stack would fail this for the wrong reason.
    assert [r for r in caplog.records if r.name == pdf_module.__name__] == []


def test_parse_pdf_raises_when_every_page_is_empty(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    make_blank_pdf(pdf_path)

    with pytest.raises(ValueError):
        parse_pdf(str(pdf_path), "s1")
