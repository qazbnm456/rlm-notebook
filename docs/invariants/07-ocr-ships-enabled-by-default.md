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
challenged, which is most of the short strings the incident record quotes. **`tests/_pdf_fixtures.py` builds
test PDFs with `reportlab`, a `dev`-only
dependency** — never a runtime dependency of the shipped package.

**THE DISTRIBUTION IS `rapidocr`, NOT `rapidocr-onnxruntime`, and the models moved with it.**
Same upstream project (RapidAI/RapidOCR, Apache-2.0); the old distribution name was frozen at
1.4.4 in January 2025 and capped `Requires-Python <3.13`, which is what made `pip install` refuse
this whole project on 3.13 and 3.14 while uv resolved past the bound. Three consequences a later
reader needs:

- **`onnxruntime` is OURS to declare now.** `rapidocr` 3.x supports six engines and pulls none of
  them, so without an explicit dependency the OCR path imports fine and fails at first use.
- **The shipped models are PP-OCRv6 (`det_small` + `rec_small`) plus a v2.0 cls model**, in the
  wheel rather than downloaded at first use — checked in its `RECORD`, which is what keeps the
  container working with no network. The measurements below were taken on `ch_PP-OCRv4` and are
  therefore about a model this project no longer ships; they are kept because the DECISION they
  support (no second Chinese model) is unchanged, not because the figures still describe what runs.
- **The API changed and the adapter is `zip(out.boxes, out.txts, strict=True)`.** `strict` is not
  tidiness: the old return was one list of `(box, text, score)` rows, where a length mismatch was
  unrepresentable, and the new one is two PARALLEL sequences where a plain `zip` truncates to the
  shorter and returns a partial page as though it were whole. Invariant 44's `Podcast.offsets`
  lesson on a second pair. Found by a test case written for this migration, not in review.

**A measured accuracy GAIN, which is the part that made this more than a packaging fix.** On one
rendered two-column page, 7 of 12 regions differ and the new model is right in every one: the old
recogniser drops word spacing (`thebenchmark`, `sublayerswhichareapplied`), which for a project
whose citations are verified by exact `quote` matching (invariant 5) is worse than a wrong
character. On a three-line Traditional Chinese fixture, 3/3 exact against 2/3. That CJK sample is
far smaller than the one below and is a direction, not a replacement for it.

**CJK is covered by the DEFAULT backend and needs no second model.** RapidOCR then shipped
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
