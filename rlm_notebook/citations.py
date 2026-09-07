"""assemble-on-read citation verification: confirm a `Citation`'s coordinate resolves to real text.

AGENTS.md invariant 5: this checks coordinate existence ONLY — that `source_id` exists in the
corpus and `locator` matches one of that source's actual blocks. It does NOT, and cannot cheaply,
verify that a citation's `quote` faithfully represents that block's text. Never let a caller of
this module claim a stronger guarantee than "this citation points at a real block."
"""

from __future__ import annotations

import re

from .corpus import Corpus
from .schema import Citation, VerifiedCitation

#: The corpus marker, as it appears inside the blob. ONE spelling, exported because `audio.py`'s
#: pre-SUBMIT validator needs the same pattern and a second copy is exactly what drifts.
MARKER_PATTERN = re.compile(r"\[\[SRC:[^\]]*\]\]")

#: Punctuation that must not be preceded by a space once a marker between them is removed —
#: `claim . Next` is cosmetic on screen and audible in synthesis, where a voice pauses at the gap.
_TIGHT_AFTER = ".,;:!?)]}\u3001\u3002\uff0c\uff1b\uff1a\uff01\uff1f\uff09\u300d\u300f"


def strip_markers(text: str) -> str:
    """Remove any `[[SRC:<id>|<locator>]]` that leaked into model-authored prose.

    The marker is a coordinate the model is told to echo into a `Citation` (invariant 4), never into
    the sentence it is writing — but it is reading a corpus full of them, and a real run duly ended
    four of five paragraphs with a literal `[[SRC:s1|whole]]` on screen. A user reported it as a
    failed render, which is a fair reading: it looks exactly like a template that did not resolve.

    Stripped at the DISPLAY boundary rather than before persisting: the stored artifact is what the
    model actually produced, and rewriting it on the way in would make an old notebook and a new one
    disagree about their own history. Doing it on the way out also fixes every notebook already on
    disk, with no migration.

    Whitespace is tidied only where the marker left a hole — a marker on its own line takes the line
    with it, and one mid-sentence leaves a single space rather than two.
    """
    if "[[SRC:" not in (text or ""):
        return text or ""
    # The gap is closed WHERE THE MARKER WAS, not globally. A global rule normalises text that had
    # nothing to do with a marker — French typographic spacing (`vrai !`) is the case an independent
    # review found — and because `strip_markers` early-returns on a string with no marker, prose and
    # `answer_span` would then get DIFFERENT normalisation and the span would stop matching. That is
    # invariant 49's failure mode one layer down: the stroke silently disappears.
    def _close_gap(match: re.Match[str]) -> str:
        before, after = match.string[: match.start()], match.string[match.end() :]
        if not before or before[-1].isspace() or not after or after[0] in _TIGHT_AFTER:
            return ""
        return " " if match.group(0) != match.group("marker") else ""

    out = re.sub(rf"[ \t]*(?P<marker>{MARKER_PATTERN.pattern})[ \t]*", _close_gap, text)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def locate_answer_spans(citations: list[Citation], prose: str) -> list[Citation]:
    """Drop any `answer_span` that does not occur VERBATIM in `prose`, keeping the citation itself.

    The same coordinate-existence discipline invariant 5 already applies to `source_id`/`locator`,
    pointed at the model's own text instead of at the corpus: a span the interface cannot find is a
    claim about where a highlight belongs, and an unlocatable one would either silently do nothing
    or, worse, be fuzzily matched onto the wrong sentence. Dropping just the span leaves the
    citation intact — losing a highlight is a small cost, highlighting the wrong sentence is not.

    Deliberately EXACT matching, with one allowance: leading and trailing whitespace, because a
    model that copies a sentence tends to carry a stray space and that is not a different sentence.
    No case folding, no punctuation normalisation, no fuzzy match — every one of those buys a few
    more highlights at the price of sometimes underlining prose the citation does not support.
    """
    located: list[Citation] = []
    for citation in citations:
        # The SAME strip the prose gets, or a span that happens to include a marker stops matching
        # the text it was copied from.
        span = strip_markers(citation.answer_span or "").strip()
        if span and span in prose:
            located.append(citation.model_copy(update={"answer_span": span}))
        elif citation.answer_span:
            located.append(citation.model_copy(update={"answer_span": None}))
        else:
            located.append(citation)
    return located


def verify_citations(citations: list[Citation], corpus: Corpus) -> list[VerifiedCitation]:
    """Verify each citation's coordinate against `corpus`. Order and count are preserved — nothing
    is ever dropped (AGENTS.md invariant 5); a citation that fails is returned with
    `verified=False` and a `reason`, for the caller to surface as "unverified" rather than hide."""
    verified: list[VerifiedCitation] = []
    for citation in citations:
        source = corpus.get(citation.source_id)
        if source is None:
            verified.append(
                VerifiedCitation(
                    citation=citation,
                    verified=False,
                    reason=f"no source with id {citation.source_id!r} in this notebook",
                )
            )
            continue
        if source.block_text(citation.locator) is None:
            known = [b.locator for b in source.blocks]
            verified.append(
                VerifiedCitation(
                    citation=citation,
                    verified=False,
                    reason=(
                        f"source {citation.source_id!r} has no block at locator "
                        f"{citation.locator!r}; known locators: {known}"
                    ),
                )
            )
            continue
        verified.append(VerifiedCitation(citation=citation, verified=True))
    return verified
