"""assemble-on-read citation verification: confirm a `Citation`'s coordinate resolves to real text.

CLAUDE.md invariant 5: this checks coordinate existence ONLY — that `source_id` exists in the
corpus and `locator` matches one of that source's actual blocks. It does NOT, and cannot cheaply,
verify that a citation's `quote` faithfully represents that block's text. Never let a caller of
this module claim a stronger guarantee than "this citation points at a real block."
"""

from __future__ import annotations

from .corpus import Corpus
from .schema import Citation, VerifiedCitation


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
