# Invariant 74 — A garbled text layer is decided by comparison

**A garbled text layer is decided by COMPARING against OCR, never by a threshold alone
(`pdf._page_text`, `_ocr.wordlike_ratio`).** Invariant 7 left "a bad-character-ratio heuristic" as
the follow-up for a text layer that is present but mis-decoded. Measurement killed the heuristic
on its own: across six documents the good pages' worst scores (0.79-0.99) OVERLAP the mis-decoded
pages' (0.63-0.80), on every metric tried — alphanumeric ratio, long-token ratio, dictionary hit
rate, and the shape score that shipped. **No threshold separates them, so no threshold may
decide.** A false positive is not free either: a good text layer beats any OCR of the same page,
so replacing one on suspicion is a downgrade.

**So the score only decides whether to SPEND an OCR pass, and the comparison decides what to
keep.** Below `_SUSPECT_TEXT_BELOW` (0.85) the page is OCR'd as a SECOND OPINION; the text layer
stands unless OCR beats it by `_OCR_REPLACES_TEXT_BY` (0.10). This makes a generous threshold
cost time and never quality — the gate is a budget, not a verdict. **The margin is not
decoration**: a bare `>` was tried and flipped a healthy page (0.97) to OCR (0.98) on a
rounding-level difference. Measured margins on genuinely mis-decoded pages were +0.20 and +0.27,
and the page where the layer was actually fine lost by 0.06.

**`wordlike_ratio` is deliberately DICTIONARY-FREE.** `/usr/share/dict/words` is absent on stock
Debian so CI cannot rely on it, and a bundled list would describe ONE language while quietly
condemning every page in another. Two shape rules do the work, both taken from how a mis-decoded
layer actually reads: no vowel anywhere in the token (`CNC`, `TTT`, `HDS`), and case flipping
mid-token (`BEANseGE`), with all-caps exempt because headings are real. Note that real garble
often DOES contain vowels — `ELTN` scores as wordlike — so this works in aggregate and never
per token.

**`None` is a real answer, not a failure, and it cuts BOTH ways.** Below `_MIN_SCORED_TOKENS`
(8) there is nothing to judge. An unscoreable SECOND opinion never displaces the first — the
accepted loss where a pure diagram page OCRs to a few numeric labels and keeps its garbled layer
even though the OCR was observed to be better. **And an unscoreable FIRST opinion is never
challenged at all**: a layer garbled down to four or five tokens spends no OCR and stands as it
is, which covers most of the short strings quoted as this invariant's own trigger. That is the
larger remaining gap and it is deliberate — a page with almost no letters gives the score
nothing to work from, and guessing off five tokens is how a good page gets thrown away.

**The CJK protection is a SHARE of the page (`_MIN_LATIN_SHARE`, 0.7), not the absence of Latin
text.** Scoring on whatever Latin happened to be present let a garbled Chinese body carrying a
clean English reference list score 1.000 — computed entirely from the readable minority — and
never be challenged. `wordlike_ratio` now asks whether the rule APPLIES before asking what it
says: below that share of the page's alphabetic characters it declines. Erring high costs only a
missed improvement, erring low lets a Latin-shaped rule pass sentence on a page written in
something else, so the uncertainty is spent upward. `_WORD_TOKEN` and `_LATIN_CHAR` are built
from ONE character-class constant, because the two must never disagree about what counts as
Latin — one decides what is scored, the other whether scoring applies.

**`_WORD_TOKEN` covers Latin ACCENTS, not just ASCII, and that is load-bearing.** With
`[A-Za-z]` a diacritic split every accented word into fragments — correct German scored 0.824
and correct Vietnamese 0.375, both under the gate — and stripping the accents, which is exactly
what a weak OCR does, raised both to 1.000. The metric REWARDED the degradation, so a correct
text layer could be replaced by a worse OCR of itself: the precise inversion of the rule above,
and the same "condemning every page in another language" this invariant rejects a bundled
dictionary to avoid. It is deliberately not a general Unicode-letter class, because CJK
characters are letters too and matching them would end the `None` that protects them.

**Neither score carries VOLUME, so `_OCR_MIN_TOKEN_SHARE` (0.25) is a separate gate.** Two
ratios compare quality and say nothing about how much of the page each one read; without it a
page of prose carrying one garbled figure block is replaced wholesale by an OCR pass that
recovered only the caption. Measured: the two pages a real scan genuinely needed replaced scored
0.39 and 0.45, a diagram page that must keep its layer 0.03, a constructed prose-for-a-caption
loss 0.10. **The separation is narrow and cannot be tightened** — a garbled layer fragments into
MORE tokens than a clean OCR of the same page, so a high share is exactly what a true
replacement does not look like.

**The trigger was real, not hypothetical**: an Internet Archive scan of a 1960 IRE monograph
whose chart pages were scanned upside-down or mirrored, so its embedded OCR decoded to
`UN ELTN NII PIN COCO` and `Zh *9td 3ONVY G3zMw30!` — the latter being "FIG.72 / ACTUAL RANGE"
reversed. `_MIN_TEXT_CHARS` sees characters and declines to run OCR, so that string is what
reached the corpus.

**The assumption that had to die first**: that re-OCRing such a page gains nothing because the
source is a chart. Measured false — on the same pages OCR recovered `FALSE ALARM INTERVAL`,
`PULSE REPETITION RATE` and `THE INCOMPLETE TORONTO FUNCTION`, because it reads the page as
rendered rather than as the original scanner mis-fed it.

**The cost is REPORTED, not capped, and `parse_pdf` logs one line per document when any page paid
it.** Measured on the 260-page scan that motivated this: 61 pages suspected, 4 unscoreable, 187
untouched — so about a QUARTER of the document pays a full OCR pass on top of reading its own
text layer, and on the API path that runs in the request's thread pool (invariant 34). (The three
figures cover the pages that HAD a text layer; the remaining 8 had none and took invariant 7's
unavoidable path.) From
outside, a slow ingestion is indistinguishable from a hang, which is the whole reason for the
line. **Not capped, deliberately**: a page with NO text layer already costs the same OCR pass
under invariant 7 with no cap and no complaint, so a cap here would be stricter than the
unavoidable case it sits beside — and it would silently leave garbled text on whichever pages
fell past it, which is the "no silent caps" failure this project keeps writing down. **Known
gap**: `uvicorn` configures the root logger so a server operator sees this, while a CLI user
sees only the wait — plumbing the counts back through `ingest` to `cli.py` was judged
disproportionate, not overlooked.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
