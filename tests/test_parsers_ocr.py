from __future__ import annotations

from rlm_notebook.parsers import _ocr


def _quad(x0: float, x1: float, y: float) -> list[list[float]]:
    """A detected region's bounding box in the shape RapidOCR reports it: four corner points,
    clockwise from top-left."""
    return [[x0, y - 5], [x1, y - 5], [x1, y + 5], [x0, y + 5]]


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


def test_reading_order_tolerates_a_degenerate_box():
    """A zero-width region sitting exactly on the centre satisfies both the left and the right
    test; it must be emitted once, not into both columns."""
    assert _ocr.reading_order([([[0, 0]], "a"), ([[0, 0]], "b")]) == "a b"


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
