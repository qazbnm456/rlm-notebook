from __future__ import annotations

from rlm_notebook.parsers import _ocr


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
