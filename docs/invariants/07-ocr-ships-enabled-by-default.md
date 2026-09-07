# Invariant 7 — OCR ships enabled by default

**OCR ships enabled by default, not merely pluggable-but-off.** `parsers/pdf.py` extracts each
page's text via `pypdfium2`; a page below `_MIN_TEXT_CHARS` (literally 1, i.e. no text layer at
all) is rendered to an image and dispatched to `parsers/_ocr.py`'s hybrid OCR (RapidOCR primary,
Tesseract fallback, both Apache-2.0, both CPU-only). The backends are core `dependencies`, not
an opt-in extra — a plain `uv sync` installs them. **Qualifier**: `pytesseract` is a WRAPPER; the
`tesseract` binary is a system dependency no Python manifest can express, and `_ocr.py` swallows
`TesseractNotFoundError`, so the fallback silently is not there on a machine without it. A
`vision_llm` OCR mode is a deferred follow-up.

**`NotebookConfig.ocr_provider` / `RN_OCR_PROVIDER` has ZERO consumers** — `parse_pdf` takes no
config and calls `ocr_image` unconditionally. Validated on read, then ignored. Kept as the seam
the `vision_llm` follow-up will use; do not infer that anything dispatches on it today.

**`pypdfium2` replaced `pymupdf`/`pymupdf4llm` over a real licence conflict.** Those are
"AGPL v3 OR Artifex Commercial" with no free non-AGPL path, and `pymupdf-layout` carried a
second Polyform Noncommercial licence. This project is `license = "MIT"` and ships an HTTP API
meant to run as a network service (invariant 25), which is exactly what AGPL's network-use
clause binds. `Pillow` is an explicit DIRECT dependency: `pypdfium2` declares no runtime
dependencies of its own, so `.to_pil()` previously worked only by luck via a transitive.

**A deliberately simpler OCR-need heuristic than `pymupdf4llm`'s**: a plain
"extracted text below a small threshold" check does NOT detect a GARBLED-but-present text layer,
only a missing one. **Invariant 74 NARROWS that gap; it does not close it** — and not by the
bad-character-ratio heuristic this line used to promise, which measurement showed cannot work
alone. A layer too garbled to yield eight Latin tokens still scores `None` and is never
challenged, which is most of the short strings the incident record quotes. **`tests/_pdf_fixtures.py` builds test PDFs with `reportlab`, a `dev`-only
dependency** — never a runtime dependency of the shipped package.

**CJK is covered by the DEFAULT backend and needs no second model.** RapidOCR ships
`ch_PP-OCRv4`, which is Chinese-native. Measured on rendered text: Simplified 1.000 on a
paragraph and 20/21 per isolated character; Traditional 0.879-0.973 per paragraph and 16-17/21
isolated. PaddleOCR's `chinese_cht` recognition model was fetched, wired in through RapidOCR's
`rec_model_path`/`rec_keys_path` seam and measured head-to-head: a WASH (mean 0.929 against
0.922, winning two cases, losing three, tying one), so it is not worth 11MB, a doubled OCR pass
and a third-party conversion's provenance. Do not re-add it without a measurement that beats
this one.

**The trap that makes any such measurement worthless**: `PIL.ImageFont.truetype(path, size)`
loads face index 0 of a `.ttc` COLLECTION, and index 0 of macOS `Songti.ttc` is Songti **SC**,
which silently renders NOTHING for Traditional-only glyphs. A first pass through this scored
Traditional at 0.589 and 0/21 and read as a total failure of the backend; it was measuring the
font. **Render the fixture and LOOK at it before believing any OCR number** — the same
render-and-look step that separated a single-column monograph from the two-column journal its
name implied (invariant 73).

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
