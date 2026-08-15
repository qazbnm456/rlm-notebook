"""OCR dispatch for a rendered PDF page image: RapidOCR primary, Tesseract fallback.

Extracted out of `parsers/pdf.py` (invariant 7's design record,
the pymupdf-replacement design record) so `parse_pdf` doesn't need to know which backend
actually produced a page's text — just whether OCR produced anything at all.

RapidOCR reports a bounding quad per detected region but no layout, and its regions arrive roughly
line-by-line ACROSS the full page — so a two-column scan comes back with its columns interleaved
mid-sentence. `reading_order` (invariant 73) puts the columns back in order using the coordinates
the detector already reported.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

#: Runs of at least two LATIN letters, accents included. Digits are excluded rather than tolerated:
#: a page of numeric chart labels says nothing about whether its text layer decoded correctly, and
#: letting digits into the denominator would drag every table's score toward whatever its letters
#: did. A one-letter token carries no shape to judge either.
#:
#: The ranges are Latin-1 Supplement, Latin Extended-A/B and Latin Extended Additional (where
#: Vietnamese lives), with the two mathematical operators sitting inside Latin-1 (× ÷) cut out.
#: **Plain `[A-Za-z]` was a bug, not a simplification**: a diacritic split every accented word into
#: ASCII fragments, so correctly-decoded Vietnamese scored 0.22 and German 0.90 — and stripping the
#: accents, which is exactly what a weak OCR does, RAISED both to 1.00. A degraded second opinion
#: could therefore beat a perfect text layer, inverting the one rule `pdf._page_text` exists to
#: enforce. Deliberately NOT `\w` or a general Unicode-letter class: CJK characters are letters
#: too, and matching them would end the `None` that keeps a Chinese page away from rules about
#: vowels.
#: One copy of the character class, because `_WORD_TOKEN` and `_LATIN_CHAR` must never disagree
#: about what counts as Latin — one decides what is scored, the other whether scoring applies.
_LATIN_LETTERS = "A-Za-zÀ-ÖØ-öø-ɏḀ-ỿ"
_WORD_TOKEN = re.compile(f"[{_LATIN_LETTERS}]{{2,}}")
_LATIN_CHAR = re.compile(f"[{_LATIN_LETTERS}]")

#: `wordlike_ratio` reads Latin tokens ONLY, so its verdict is worth nothing unless Latin text is the
#: bulk of the page. Below this share of the page's alphabetic characters it declines to judge.
#: Without it a page that is a garbled CJK body plus a clean English reference list scored 1.000 —
#: computed entirely from the minority that happened to be readable — and was never challenged.
#: Erring HIGH costs only a missed improvement; erring LOW lets a Latin-shaped rule pass sentence on
#: a page written in something else, so the uncertainty is spent upward.
_MIN_LATIN_SHARE = 0.7

#: Above this share of regions crossing the page's horizontal centre, the page is not laid out in
#: two columns and is left exactly as the detector reported it. A two-column page crosses the centre
#: only on the few elements that span the measure (a banner heading, a figure/table caption, a
#: centred page number); a single-column page crosses it on nearly every body line. Measured on two
#: real papers: the two-column one scored 0.00-0.11 per page (one title page at 0.41), the
#: single-column one 0.04-0.88. **Those ranges OVERLAP, so 0.15 does not separate them** — the
#: single-column pages measuring 0.04-0.08 are diagram pages, and they are reordered. That is the
#: -0.08/-0.06 those two pages cost, inspected and accepted rather than designed away. A value too
#: LOW only declines to improve a page while too HIGH reorders one that was already correct, so the
#: uncertainty from a two-document sample is spent downward; "safe" is the direction, not a
#: guarantee.
_MAX_SPANNING_FRACTION = 0.15

#: (left edge, right edge, vertical centre, detection index, text) — a detection flattened to the
#: only numbers ordering needs. The vertical CENTRE rather than the top edge, so a slightly skewed
#: scan (or a line whose quad is taller on one side) still sorts against its neighbours by where it
#: sits. The detection INDEX is carried because it is the order regions are ultimately emitted in
#: (see `reading_order`), not merely how they arrived.
_Region = tuple[float, float, float, int, str]


def _flatten(index: int, box: Sequence[Sequence[float]], text: str) -> _Region:
    xs = [float(point[0]) for point in box] or [0.0]
    ys = [float(point[1]) for point in box] or [0.0]
    return min(xs), max(xs), sum(ys) / len(ys), index, text.strip()


def _order_band(band: list[_Region], centre: float) -> list[str]:
    """One horizontal band containing no region that crosses `centre`: read it as two columns when
    both sides are occupied, otherwise leave it alone. Each side keeps its detection order."""
    left: list[_Region] = []
    right: list[_Region] = []
    for region in sorted(band, key=lambda r: r[3]):
        # The caller has already peeled off every region crossing `centre`, so "does not end left
        # of it" means "starts right of it". Partitioned rather than filtered twice, because a
        # zero-width region sitting exactly ON the centre satisfies both tests and would otherwise
        # be emitted into both columns.
        (left if region[1] <= centre else right).append(region)
    # No "is either side empty" special case is needed: with one side empty the concatenation IS
    # the band's own order, so the two-column reading and the leave-it-alone reading coincide. An
    # earlier draft branched on it, which read as a rule and was dead code.
    return [region[4] for region in left] + [region[4] for region in right]


def reading_order(regions: Sequence[tuple[Sequence[Sequence[float]], str]]) -> str:
    """Join OCR'd text regions in reading order (CLAUDE.md invariant 73), from the bounding quads
    the detector already reported. A region CROSSING the content's horizontal centre spans both
    columns and closes the band above it; a band with regions on both sides of the centre is read as
    two columns, all of the left then all of the right, instead of line-by-line across both.

    Within a band nothing is re-sorted — the detector's own order is kept, and only the two columns
    are separated out of it. Sorting a band by vertical position instead measured WORSE on both
    layouts (a two-column paper 0.756 -> 0.743 against its own text layer, a single-column one
    0.774 -> 0.751): RapidOCR already emits a column's lines in reading order, and re-sorting by a
    quad's vertical centre only disturbs near-ties like a superscript or a slightly skewed line.

    Every rule degrades to the detector's order rather than to a wrong one: a page that does not
    look two-column is returned untouched, and if the centre lands INSIDE a column (margins lopsided
    enough to drag the content midpoint off the gutter) that column crosses it on every line, which
    is exactly the "not two-column" case."""
    items = [_flatten(i, box, text) for i, (box, text) in enumerate(regions) if text.strip()]
    if len(items) < 2:
        return " ".join(region[4] for region in items)
    centre = (min(region[0] for region in items) + max(region[1] for region in items)) / 2
    spanning = [region for region in items if region[0] < centre < region[1]]
    if len(spanning) > len(items) * _MAX_SPANNING_FRACTION:
        return " ".join(region[4] for region in items)

    # Bands are delimited by vertical position — that is the one thing only the geometry knows —
    # but each band's CONTENTS are emitted in detection order by `_order_band`.
    ordered: list[str] = []
    band: list[_Region] = []
    for region in sorted(items, key=lambda r: (r[2], r[0])):
        if region[0] < centre < region[1]:
            ordered.extend(_order_band(band, centre))
            ordered.append(region[4])
            band = []
        else:
            band.append(region)
    ordered.extend(_order_band(band, centre))
    return " ".join(ordered)


#: A page needs this many scoreable tokens before `wordlike_ratio` returns a number at all, so the
#: score is never computed from a handful of chart axis labels, where it would be noise wearing a
#: number. Measured: the pure-diagram pages of a real scan fall under it and correctly score `None`.
_MIN_SCORED_TOKENS = 8

_VOWELS = frozenset("aeiouyAEIOUY")


def scoreable_tokens(text: str) -> int:
    """How many tokens `wordlike_ratio` would judge — i.e. how much of this text the score is
    actually speaking for. A ratio carries no volume, so a caller comparing two texts needs this
    separately to tell "better" from "shorter"."""
    return len(_WORD_TOKEN.findall(text))


def wordlike_ratio(text: str) -> float | None:
    """What share of `text`'s alphabetic tokens have the SHAPE of real words (invariant 74)?
    `None` when there are too few tokens to judge — which is a real answer, not a failure.

    Deliberately dictionary-free. A system word list is not portable (`/usr/share/dict/words` is
    absent on stock Debian, so CI could not rely on it) and a bundled one would only ever describe
    ONE language, quietly condemning every page this project is meant to read in another. Two
    shape rules carry it instead, both drawn from how a mis-decoded text layer actually reads:

    * **no vowel at all** — `CNC`, `TTT`, `HDS`, the residue of a chart's gridlines. Accents are
      folded away first, so `đề` and `Größere` are judged on `de` and `Grossere`;
    * **case flipping mid-token** — `BEANseGE`, which no typography produces and glyph-level
      mis-mapping produces constantly. An all-caps token is exempt, since headings are real.

    Note what this does NOT catch: `ELTN` contains a vowel and reads as wordlike. Real garble is
    full of such tokens, which is why the score is only ever read in aggregate and never per token.

    A CJK page scores `None`, so it is never judged by a rule written for alphabets that have vowels
    — the failure mode that makes a bundled dictionary the wrong tool. **That protection is a SHARE
    of the page, not the absence of Latin text**: scoring on whatever Latin happens to be present
    let a garbled Chinese body carrying a clean English reference list read as perfectly healthy.
    """
    # Is this rule even applicable to this page, before asking what it says about it?
    alphabetic = sum(1 for character in text if character.isalpha())
    if alphabetic and len(_LATIN_CHAR.findall(text)) < alphabetic * _MIN_LATIN_SHARE:
        return None
    tokens = _WORD_TOKEN.findall(text)
    if len(tokens) < _MIN_SCORED_TOKENS:
        return None
    return sum(1 for token in tokens if _is_wordlike(token)) / len(tokens)


def _is_wordlike(token: str) -> bool:
    # Fold accents before the vowel test, or every accented vowel reads as "no vowel here" and the
    # rule condemns the languages that use them. NFD splits `ề` into `e` + a combining mark; letters
    # that do not decompose (`ß`, `đ`) simply stay put, which is fine — their words carry other
    # vowels. Case is preserved by the normalisation, so the second rule still sees the original.
    folded = unicodedata.normalize("NFD", token)
    if not _VOWELS & {c for c in folded if not unicodedata.combining(c)}:
        return False
    # `token[1:].lower() != token[1:]` means an uppercase letter appears after the first character.
    # Ordinary prose does that only in an all-caps token, so anything else is a mis-decoded glyph.
    return token.isupper() or token[1:].lower() == token[1:]


def _try_rapidocr(image) -> str | None:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    try:
        import numpy as np

        result, _ = RapidOCR()(np.array(image.convert("RGB")))
        if not result:
            return None
        # INSIDE the try, deliberately. `reading_order` reads coordinates out of whatever the
        # detector returned, so it is exposed to the result's SHAPE — a future rapidocr changing
        # its box format or row arity (the pin is `>=1.3`, with no upper bound) would otherwise
        # raise straight through `ocr_image`, whose docstring promises it never does. Verified: a
        # `None` box, a flat xyxy box, a 2-tuple row and a non-numeric coordinate all escaped when
        # this line sat outside.
        text = reading_order([(box, text) for box, text, _ in result])
    except Exception:  # noqa: BLE001 — an OCR engine choking on an unusual rendered page must
        # fall through to the next backend (or to "no OCR text"), never take down ingestion of an
        # otherwise-fine multi-page PDF. Same "degrade, don't crash, at an extraction boundary"
        # posture this project's sibling family already uses at its own sandbox boundaries.
        return None
    return text or None


def _try_tesseract(image) -> str | None:
    try:
        import pytesseract
    except ImportError:
        return None
    try:
        # Tesseract does its own page segmentation (PSM 3 by default), columns included, so its
        # output needs no equivalent of `reading_order` — that reordering is specific to RapidOCR,
        # which reports regions without ever grouping them into a layout.
        text = pytesseract.image_to_string(image)
    except Exception:  # noqa: BLE001 — same reasoning as _try_rapidocr above.
        return None
    return text if text.strip() else None


def ocr_image(image) -> str:
    """RapidOCR primary, Tesseract fallback (CLAUDE.md invariant 7) — tried in that order, falling
    through on either an import failure OR a runtime failure/empty result, never raising from the
    first backend's own failure. Returns `""` (never raises) if NEITHER backend produces text —
    `parse_pdf` decides what an empty-after-OCR page means, this function doesn't."""
    return _try_rapidocr(image) or _try_tesseract(image) or ""
