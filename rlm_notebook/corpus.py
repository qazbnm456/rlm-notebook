"""The corpus blob: every ingested `Source` concatenated into ONE string, tagged with
`[[SRC:<id>|<locator>]]` markers, that becomes the RLM's `sources` signature field.

This is rlm-kit's native mechanic, not a new indexing layer (see CHANGELOG.md's Unreleased entry):
an RLM signature field is injected into the sandboxed REPL as a plain variable, and the model
explores it with `.find()`/slicing rather than through embedding similarity search. `Corpus` only
ever produces a string — see CLAUDE.md invariant 2, ingestion (which produces the `Source` objects
this module assembles) happens entirely before any of this runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .schema import Source


class CorpusTooLargeError(ValueError):
    """Raised by `Corpus.blob()` when the assembled text exceeds `max_chars` (CLAUDE.md invariant 7)
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
