from __future__ import annotations

import json
from pathlib import Path

from rlm_notebook.parsers import _ocr


def _quad(x0: float, x1: float, y: float) -> list[list[float]]:
    """A detected region's bounding box in the shape RapidOCR reports it: four corner points,
    clockwise from top-left."""
    return [[x0, y - 5], [x1, y - 5], [x1, y + 5], [x0, y + 5]]


def _tall_quad(x0: float, x1: float, top: float, bottom: float) -> list[list[float]]:
    """Same, with the vertical span given explicitly — for fixtures where a region's top edge and
    its vertical centre disagree about the order."""
    return [[x0, top], [x1, top], [x1, bottom], [x0, bottom]]


# --- reading_order (invariant 73) ------------------------------------------------------------
# These drive the pure ordering function with synthetic coordinates rather than a real page: the
# same reason `tts.sequence_offsets` is extracted out of `synthesize` (invariant 44) — it lets CI
# check the bookkeeping with no model, no image and no OCR run.


def test_reading_order_reads_two_columns_down_each_side():
    regions = [
        (_quad(0, 100, 10), "left one"),
        (_quad(200, 300, 10), "right one"),
        (_quad(0, 100, 30), "left two"),
        (_quad(200, 300, 30), "right two"),
    ]
    assert _ocr.reading_order(regions) == "left one left two right one right two"


def test_reading_order_treats_a_full_width_region_as_a_band_boundary():
    """A caption spanning both columns closes the band above it, so the columns above and below it
    are each read on their own instead of being run together."""
    regions = [
        (_quad(0, 100, 10), "left one"),
        (_quad(200, 300, 10), "right one"),
        (_quad(0, 100, 30), "left two"),
        (_quad(200, 300, 30), "right two"),
        (_quad(0, 300, 50), "a caption spanning both columns"),
        (_quad(0, 100, 70), "left three"),
        (_quad(200, 300, 70), "right three"),
        (_quad(0, 100, 90), "left four"),
        (_quad(200, 300, 90), "right four"),
    ]
    assert _ocr.reading_order(regions) == (
        "left one left two right one right two a caption spanning both columns "
        "left three left four right three right four"
    )


def test_reading_order_is_not_vetoed_by_one_small_centred_region():
    """The bug this was found on: a page number centred in the footer is the ONLY region crossing
    the centre of a real two-column page, and a rule that let a centre-crosser veto the column
    split cost that whole page its column order."""
    regions = [
        (_quad(0, 100, 10), "left one"),
        (_quad(200, 300, 10), "right one"),
        (_quad(0, 100, 30), "left two"),
        (_quad(200, 300, 30), "right two"),
        (_quad(0, 100, 50), "left three"),
        (_quad(200, 300, 50), "right three"),
        (_quad(0, 100, 70), "left four"),
        (_quad(200, 300, 70), "right four"),
        (_quad(140, 160, 200), "7"),
    ]
    assert _ocr.reading_order(regions) == (
        "left one left two left three left four right one right two right three right four 7"
    )


def test_reading_order_leaves_a_single_column_page_exactly_as_detected():
    """Nearly every body line of a single-column page crosses the centre, which is what tells the
    page apart from a two-column one — it must come back untouched, in detection order."""
    regions = [
        (_quad(0, 300, 10), "first line"),
        (_quad(0, 290, 30), "second line"),
        (_quad(0, 295, 50), "third line"),
        (_quad(0, 280, 70), "fourth line"),
    ]
    assert _ocr.reading_order(regions) == "first line second line third line fourth line"


def test_reading_order_keeps_detection_order_when_too_many_regions_span_the_centre():
    """The page-level guard, checked against an input whose detection order is NOT its vertical
    order — so the assertion fails if the page is silently re-sorted instead of left alone."""
    regions = [
        (_quad(0, 300, 90), "spanning four"),
        (_quad(0, 300, 10), "spanning one"),
        (_quad(0, 100, 50), "short left"),
        (_quad(0, 300, 30), "spanning two"),
        (_quad(200, 300, 55), "short right"),
        (_quad(0, 300, 70), "spanning three"),
    ]
    assert _ocr.reading_order(regions) == (
        "spanning four spanning one short left spanning two short right spanning three"
    )


def test_reading_order_does_not_split_a_band_that_only_occupies_one_side():
    """A band with nothing in the right column is left as it is rather than being read as a column
    of its own — the left/right split only fires when both sides are actually occupied."""
    regions = [
        (_quad(0, 100, 10), "left one"),
        (_quad(0, 100, 20), "left two"),
        (_quad(0, 100, 30), "left three"),
        (_quad(0, 300, 50), "a caption spanning both columns"),
        (_quad(200, 300, 70), "right one"),
        (_quad(200, 300, 80), "right two"),
        (_quad(200, 300, 90), "right three"),
    ]
    assert _ocr.reading_order(regions) == (
        "left one left two left three a caption spanning both columns "
        "right one right two right three"
    )


def test_reading_order_assigns_bands_by_vertical_position_not_by_detection_order():
    """WHICH band a region lands in is decided by where it sits, not by when it was detected.

    This needs a band boundary to be observable at all: inside a single band the regions are
    re-sorted into detection order anyway, so a fixture without a centre-crosser cannot tell the
    two sort keys apart — which is why every earlier fixture here left that mutation alive."""
    regions = [
        (_quad(0, 100, 90), "left below one"),
        (_quad(0, 300, 50), "the divider"),
        (_quad(0, 100, 10), "left above one"),
        (_quad(200, 300, 10), "right above one"),
        (_quad(200, 300, 90), "right below one"),
        (_quad(0, 100, 30), "left above two"),
        (_quad(200, 300, 30), "right above two"),
        (_quad(0, 100, 110), "left below two"),
    ]
    assert _ocr.reading_order(regions) == (
        "left above one left above two right above one right above two the divider "
        "left below one left below two right below one"
    )


def test_reading_order_places_a_region_by_its_vertical_centre_not_its_top_edge():
    """`_Region` carries a quad's vertical CENTRE so a skewed or unusually tall line still sorts by
    where it sits. `the tall block` starts ABOVE the divider and sits BELOW it; measuring by the top
    edge would file it in the wrong band."""
    regions = [
        (_quad(0, 100, 10), "left above one"),
        (_quad(200, 300, 10), "right above one"),
        (_quad(0, 100, 30), "left above two"),
        (_quad(200, 300, 30), "right above two"),
        (_quad(0, 300, 50), "the divider"),
        (_tall_quad(0, 100, 40, 90), "the tall block"),
        (_quad(200, 300, 80), "right below one"),
        (_quad(200, 300, 100), "right below two"),
    ]
    assert _ocr.reading_order(regions) == (
        "left above one left above two right above one right above two the divider "
        "the tall block right below one right below two"
    )


def test_reading_order_uses_the_content_midpoint_not_the_page_midpoint():
    """A page whose content sits far from the middle of its own bounding box still splits at the
    gutter. Measuring the centre any other way was the specific bug that made the first draft of
    this ordering wrong on a real page."""
    regions = [
        (_quad(1000, 1100, 10), "left one"),
        (_quad(1200, 1300, 10), "right one"),
        (_quad(1000, 1100, 30), "left two"),
        (_quad(1200, 1300, 30), "right two"),
        (_quad(1000, 1100, 50), "left three"),
        (_quad(1200, 1300, 50), "right three"),
    ]
    assert _ocr.reading_order(regions) == (
        "left one left two left three right one right two right three"
    )


def test_reading_order_on_a_real_two_column_page():
    """The one test here driven by REAL detector geometry rather than hand-built quads — 105 boxes
    from a rendered two-column paper, measured once and frozen (`tests/fixtures/`). Text is not in
    the fixture; only the layout is, which is the part `reading_order` reads.

    The assertion is STRUCTURAL rather than a frozen output list, so it says what correct means
    instead of merely locking in today's answer: the whole left column, then the whole right column,
    each in detection order, with the centred page number last because it spans the measure. The
    gutter bounds come from the fixture, read off the measurement rather than computed by the code
    under test.

    What it adds, and what it does not. It is the only evidence here that the algorithm produces the
    right SHAPE on output a real detector really emitted — ragged edges, a stray footer, boxes that
    do not line up — and it is the ONLY test that kills `_order_band`'s within-column sort key, since
    the left column's detection order matches neither its x order nor its vertical order, which no
    hand-built fixture reproduces. It does not subsume the synthetic ones: this page is a single band
    whose only centre-crosser is the LAST detection, so the band-assignment key, the vertical-centre
    choice and the spanning special case are all invisible in it (mutating any of the three leaves
    this test green). Those are pinned above, where a fixture can be built to expose them."""
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "ocr_two_column_page.json").read_text()
    )
    left_ends, right_starts = fixture["left_column_ends_before"], fixture["right_column_starts_after"]

    left, right, spanning = [], [], []
    regions = []
    for index, box in enumerate(fixture["boxes"]):
        label = f"r{index:03d}"
        regions.append((box, label))
        x0 = min(point[0] for point in box)
        x1 = max(point[0] for point in box)
        if x1 <= left_ends:
            left.append(label)
        elif x0 >= right_starts:
            right.append(label)
        else:
            spanning.append(label)

    # The page really is two columns with one centred footer; if that stops holding the fixture has
    # been edited and every assertion below would be measuring something else.
    assert len(left) > 40 and len(right) > 40, (len(left), len(right))
    assert len(spanning) == 1, spanning

    assert _ocr.reading_order(regions).split() == left + right + spanning


def test_reading_order_tolerates_a_degenerate_box():
    """A zero-width region sitting exactly on the centre satisfies both the left and the right
    test; it must be emitted once, not into both columns."""
    assert _ocr.reading_order([([[0, 0]], "a"), ([[0, 0]], "b")]) == "a b"


# --- wordlike_ratio (invariant 74) -----------------------------------------------------------


def test_wordlike_ratio_scores_ordinary_prose_near_one():
    text = "The encoder is composed of a stack of identical layers with residual connections"
    assert _ocr.wordlike_ratio(text) == 1.0


def test_wordlike_ratio_penalises_vowelless_tokens():
    """`CNC`, `TTT`, `HDS` — what a chart's gridlines leave behind in a mis-decoded text layer.
    Five real words against five vowelless runs is exactly half, which pins the rule rather than
    merely asserting it went down."""
    assert _ocr.wordlike_ratio("alpha beta gamma delta epsilon CNC TTT HDS THT NBS") == 0.5


def test_wordlike_ratio_penalises_case_flipping_inside_a_token():
    """`BEANseGE` is not typography, it is glyph-level mis-mapping."""
    ratio = _ocr.wordlike_ratio("alpha BEANseGE gamma dELTa epsilon ZEta eta theta")
    assert ratio is not None and ratio < 0.75


def test_wordlike_ratio_exempts_all_caps_tokens():
    """A heading is real text; only case flipping WITHIN a token is the signal."""
    assert _ocr.wordlike_ratio("THE INCOMPLETE TORONTO FUNCTION AND ITS USE IN RADAR") == 1.0


def test_wordlike_ratio_returns_none_below_the_token_floor():
    """Too few tokens to judge is a real answer, not a failure — a diagram page of numeric labels
    must not be handed a confident-looking score computed from three words."""
    assert _ocr.wordlike_ratio("0.5 1.0 2.0 Fig 10 R/Ro 299") is None
    assert _ocr.wordlike_ratio("") is None


def test_wordlike_ratio_does_not_condemn_accented_latin_scripts():
    """`[A-Za-z]` split every accented word into ASCII fragments, so correct German scored 0.82 and
    correct Vietnamese 0.38 — both under the suspicion gate, both then beatable by an OCR pass that
    simply DROPPED the accents and scored 1.0. Healthy text must score healthy."""
    german = "Größere Anstrengungen müssen für die Qualität während der Überprüfung erfolgen"
    vietnamese = "Chúng tôi đề xuất một phương pháp mới để cải thiện độ chính xác của mô hình"
    assert _ocr.wordlike_ratio(german) == 1.0
    assert _ocr.wordlike_ratio(vietnamese) == 1.0


def test_wordlike_ratio_does_not_reward_stripping_the_accents():
    """The corruption path, stated as an ordering rather than as two numbers: mangling a word by
    dropping its diacritic must never score BETTER than the word itself."""
    correct = "Chúng tôi đề xuất một phương pháp mới để cải thiện độ chính xác của mô hình"
    stripped = "Chung toi de xuat mot phuong phap moi de cai thien do chinh xac cua mo hinh"
    assert _ocr.wordlike_ratio(correct) >= _ocr.wordlike_ratio(stripped)


def test_wordlike_ratio_treats_y_as_a_vowel():
    """`gym`, `sky`, `myth` are words. Dropping `y` from the vowel set condemns them, and English
    prose containing them would start reading as garble."""
    assert _ocr.wordlike_ratio("the gym and the sky and a myth and rhythm by my hymn") == 1.0


def test_wordlike_ratio_ignores_one_letter_tokens():
    """A single letter carries no shape to judge, and mis-decoded text is full of them — counting
    them would let a page of stray letters vote on its own score."""
    scattered = "a b c d e f g h i j k l m n o p q r s t u v"
    assert _ocr.wordlike_ratio(scattered) is None
    with_prose = "the encoder is composed of a stack of identical layers " + scattered
    assert _ocr.wordlike_ratio(with_prose) == 1.0


def test_scoreable_tokens_counts_what_the_ratio_speaks_for():
    assert _ocr.scoreable_tokens("alpha beta CNC") == 3
    assert _ocr.scoreable_tokens("Größere Qualität") == 2
    assert _ocr.scoreable_tokens("0.5 1.0 這是中文") == 0


def test_wordlike_ratio_declines_a_page_whose_latin_text_is_a_minority():
    """The CJK protection is a SHARE of the page, not the absence of Latin text. A garbled Chinese
    body carrying a clean English reference list scored 1.000 — computed entirely from the minority
    that happened to be readable — and was therefore never challenged."""
    garbled_body = "這是一段被錯誤解碼的中文內容" * 6
    clean_references = (
        "References Vaswani et al Attention is all you need in Advances in Neural Information"
    )
    assert _ocr.wordlike_ratio(garbled_body + " " + clean_references) is None


def test_wordlike_ratio_still_scores_a_latin_page_carrying_some_cjk():
    """The other direction: an English page quoting a few Chinese words is still an English page,
    and must not be excused from judgement by their presence."""
    text = (
        "The encoder is composed of a stack of identical layers and each layer has two sub-layers "
        "which the authors call 自注意力 in the Chinese edition of this paper"
    )
    assert _ocr.wordlike_ratio(text) == 1.0


def test_wordlike_ratio_returns_none_for_cjk_rather_than_condemning_it():
    """The rules are written for alphabets with vowels. A Chinese page has no Latin tokens, so it
    scores None and is never judged by them — the failure a bundled English dictionary would
    have caused."""
    assert _ocr.wordlike_ratio("這是一段完全沒有拉丁字母的中文文字，用來確認評分函式會回傳 None。") is None


def test_reading_order_drops_blank_regions_and_strips_each():
    regions = [(_quad(0, 300, 10), "  kept  "), (_quad(0, 300, 30), "   ")]
    assert _ocr.reading_order(regions) == "kept"


def test_ocr_image_uses_rapidocr_result_when_available(monkeypatch):
    monkeypatch.setattr(_ocr, "_try_rapidocr", lambda image: "rapid result")
    monkeypatch.setattr(_ocr, "_try_tesseract", lambda image: "tesseract result")
    assert _ocr.ocr_image(object()) == "rapid result"


def test_ocr_image_falls_back_to_tesseract_when_rapidocr_yields_nothing(monkeypatch):
    monkeypatch.setattr(_ocr, "_try_rapidocr", lambda image: None)
    monkeypatch.setattr(_ocr, "_try_tesseract", lambda image: "tesseract result")
    assert _ocr.ocr_image(object()) == "tesseract result"


def test_ocr_image_returns_empty_string_when_both_backends_yield_nothing(monkeypatch):
    monkeypatch.setattr(_ocr, "_try_rapidocr", lambda image: None)
    monkeypatch.setattr(_ocr, "_try_tesseract", lambda image: None)
    assert _ocr.ocr_image(object()) == ""


def test_try_rapidocr_returns_none_on_a_runtime_failure_never_raises(monkeypatch):
    """An OCR engine choking on an unusual rendered page must fall through, never take down
    ingestion of an otherwise-fine multi-page PDF."""

    class _FakeEngine:
        def __call__(self, arr):
            raise RuntimeError("simulated OCR engine crash")

    monkeypatch.setattr("rapidocr_onnxruntime.RapidOCR", lambda: _FakeEngine())

    class _FakeImage:
        def convert(self, mode):
            return self

    assert _ocr._try_rapidocr(_FakeImage()) is None


def test_try_rapidocr_returns_none_when_result_is_empty(monkeypatch):
    class _FakeEngine:
        def __call__(self, arr):
            return [], None

    monkeypatch.setattr("rapidocr_onnxruntime.RapidOCR", lambda: _FakeEngine())

    class _FakeImage:
        def convert(self, mode):
            return self

    assert _ocr._try_rapidocr(_FakeImage()) is None


def test_try_rapidocr_joins_multiple_text_regions(monkeypatch):
    class _FakeEngine:
        def __call__(self, arr):
            return [
                ([[0, 0]], "hello", 0.9),
                ([[0, 0]], "world", 0.8),
                ([[0, 0]], "   ", 0.1),  # whitespace-only region, excluded
            ], None

    monkeypatch.setattr("rapidocr_onnxruntime.RapidOCR", lambda: _FakeEngine())

    class _FakeImage:
        def convert(self, mode):
            return self

    assert _ocr._try_rapidocr(_FakeImage()) == "hello world"


def test_try_rapidocr_orders_regions_by_layout_not_by_detection_order(monkeypatch):
    """The wiring, not the geometry: RapidOCR reports a two-column page roughly line-by-line ACROSS
    both columns, and `_try_rapidocr` must pass those quads through `reading_order` rather than
    joining them in the order they arrived."""

    class _FakeEngine:
        def __call__(self, arr):
            return [
                (_quad(0, 100, 10), "left one", 0.9),
                (_quad(200, 300, 10), "right one", 0.9),
                (_quad(0, 100, 30), "left two", 0.9),
                (_quad(200, 300, 30), "right two", 0.9),
            ], None

    monkeypatch.setattr("rapidocr_onnxruntime.RapidOCR", lambda: _FakeEngine())

    class _FakeImage:
        def convert(self, mode):
            return self

    assert _ocr._try_rapidocr(_FakeImage()) == "left one left two right one right two"


def test_try_rapidocr_returns_none_when_the_detector_result_has_an_unexpected_shape(monkeypatch):
    """`ocr_image` documents that it never raises, and `reading_order` reads coordinates straight
    out of whatever the detector returned — so the ordering call belongs INSIDE the try. The pin on
    `rapidocr-onnxruntime` has no upper bound; a future box format must degrade, not crash."""

    class _FakeImage:
        def convert(self, mode):
            return self

    for label, rows in [
        ("None box", [(None, "text", 0.9)]),
        ("flat xyxy box", [([0, 0, 1, 1], "text", 0.9)]),
        ("two-element rows", [([[0, 0]], "text")]),
        ("non-numeric coordinate", [([["a", "b"]], "text", 0.9)]),
    ]:

        class _FakeEngine:
            def __init__(self, rows):
                self.rows = rows

            def __call__(self, arr):
                return self.rows, None

        monkeypatch.setattr("rapidocr_onnxruntime.RapidOCR", lambda rows=rows: _FakeEngine(rows))
        assert _ocr._try_rapidocr(_FakeImage()) is None, label
        assert _ocr.ocr_image(_FakeImage()) == "", label


def test_try_tesseract_returns_none_on_a_runtime_failure_never_raises(monkeypatch):
    def _boom(image):
        raise RuntimeError("simulated tesseract crash")

    monkeypatch.setattr("pytesseract.image_to_string", _boom)
    assert _ocr._try_tesseract(object()) is None


def test_try_tesseract_returns_none_on_blank_result(monkeypatch):
    monkeypatch.setattr("pytesseract.image_to_string", lambda image: "   \n")
    assert _ocr._try_tesseract(object()) is None


def test_try_tesseract_returns_stripped_text(monkeypatch):
    monkeypatch.setattr("pytesseract.image_to_string", lambda image: "real text")
    assert _ocr._try_tesseract(object()) == "real text"
