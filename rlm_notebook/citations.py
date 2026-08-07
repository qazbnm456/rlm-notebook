"""assemble-on-read citation verification: confirm a `Citation`'s coordinate resolves to real text.

CLAUDE.md invariant 5: this checks coordinate existence ONLY — that `source_id` exists in the
corpus and `locator` matches one of that source's actual blocks. It does NOT, and cannot cheaply,
verify that a citation's `quote` faithfully represents that block's text. Never let a caller of
this module claim a stronger guarantee than "this citation points at a real block."
"""

from __future__ import annotations

from .corpus import Corpus
from .schema import Citation, VerifiedCitation


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
        span = (citation.answer_span or "").strip()
        if span and span in prose:
            located.append(citation.model_copy(update={"answer_span": span}))
        elif citation.answer_span:
            located.append(citation.model_copy(update={"answer_span": None}))
        else:
            located.append(citation)
    return located


def verify_citations(citations: list[Citation], corpus: Corpus) -> list[VerifiedCitation]:
    """Verify each citation's coordinate against `corpus`. Order and count are preserved — nothing
    is ever dropped (CLAUDE.md invariant 5); a citation that fails is returned with
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
