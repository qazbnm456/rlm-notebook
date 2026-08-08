"""The corpus blob: every ingested `Source` concatenated into ONE string, tagged with
`[[SRC:<id>|<locator>]]` markers, that becomes the RLM's `sources` signature field.

This is rlm-harness's native mechanic, not a new indexing layer (see CHANGELOG.md's Unreleased entry):
an RLM signature field is injected into the sandboxed REPL as a plain variable, and the model
explores it with `.find()`/slicing rather than through embedding similarity search. `Corpus` only
ever produces a string — see CLAUDE.md invariant 3, ingestion (which produces the `Source` objects
this module assembles) happens entirely before any of this runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import Source


class CorpusTooLargeError(ValueError):
    """Raised by `Corpus.blob()` when the assembled text exceeds `max_chars` (CLAUDE.md invariant 8)
    — a loud, ingestion-time failure rather than a silently slow/failing chat turn later."""


@dataclass
class Corpus:
    """An ordered collection of `Source`s for one notebook session."""

    sources: list[Source] = field(default_factory=list)

    def add(self, source: Source) -> None:
        if any(existing.id == source.id for existing in self.sources):
            raise ValueError(f"a source with id {source.id!r} is already in this corpus")
        self.sources.append(source)

    def get(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)

    def blob(self, *, max_chars: int | None = None) -> str:
        """Assemble every source's blocks into one marker-tagged string.

        Raises `CorpusTooLargeError` (not a silent truncation) if the result exceeds `max_chars`.
        `max_chars=None` skips the check — callers that already enforce it elsewhere (or are
        deliberately building an oversized fixture in a test) can opt out explicitly.
        """
        parts: list[str] = []
        for source in self.sources:
            for block in source.blocks:
                parts.append(f"{source.marker(block.locator)}\n{block.text}")
        text = "\n\n".join(parts)
        if max_chars is not None and len(text) > max_chars:
            raise CorpusTooLargeError(
                f"assembled corpus is {len(text)} chars, over the {max_chars} cap "
                f"(RN_MAX_CORPUS_CHARS) — remove a source or raise the cap explicitly."
            )
        return text

    def excerpt(self, max_chars: int) -> str:
        """A sample of EVERY source, for the cheap `dspy.Predict` callers that cannot read the whole
        corpus (`naming.SuggestTitle`, `naming.SuggestLanguage`).

        Not `blob()[:max_chars]`, which is what this replaced. The blob concatenates sources in
        order, so a prefix is whatever fits of source ONE — and a user reported the consequence
        exactly: a four-source notebook titled by transliterating the first source's own paper
        title, with sources two to four never seen, because source one alone was 69,859 characters
        against a 4,000-character window. Language resolution had the same blind spot, which is
        worse: a notebook whose later sources are in another language would resolve the wrong one.

        Each source gets an equal share, taken from its START — a paper, a page or a report states
        its subject in the opening lines, so the head is the most informative slice of a fixed
        budget. Markers are included so a reader of the excerpt can still tell where one source ends
        and the next begins; nothing downstream parses them.
        """
        if not self.sources or max_chars <= 0:
            return ""
        share = max(200, max_chars // len(self.sources))
        parts: list[str] = []
        for source in self.sources:
            text = "\n".join(block.text for block in source.blocks)
            head = text[:share]
            parts.append(f"{source.marker(source.blocks[0].locator if source.blocks else 'whole')}\n{head}")
        return "\n\n".join(parts)[:max_chars]

    def filtered(self, source_ids: list[str]) -> Corpus:
        """A new `Corpus` containing only the named sources, in their original order — the "ask
        about just these sources" subset selection a notebook UI can offer (see the design
        discussion this project was born from). Raises if a name doesn't exist, rather than
        silently dropping it."""
        wanted = set(source_ids)
        missing = wanted - {s.id for s in self.sources}
        if missing:
            raise ValueError(f"unknown source id(s): {sorted(missing)}")
        return Corpus(sources=[s for s in self.sources if s.id in wanted])
