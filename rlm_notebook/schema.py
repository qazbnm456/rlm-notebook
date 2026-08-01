"""dspy-free data shapes shared across ingestion, the corpus blob, and the RLM task.

Kept separate from `task.py` (which imports `rlm_kit.RLMTask`, and therefore `dspy`) for the same
reason ctx-distillery split its own `schema.py` out of `task.py`: importing these shapes from
`corpus.py`/`citations.py`/a future CLI-only code path should never drag `dspy` in.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SourceKind = Literal["text", "web", "pdf"]


class SourceBlock(BaseModel):
    """One citable unit of a source's text, tagged with the locator a citation must echo verbatim.

    A `text`/`web` source has exactly one block, `locator="whole"` — see CLAUDE.md's Scope note:
    finer-grained (paragraph/char-offset) citation within a text/web source is a deferred follow-up.
    A `pdf` source has one block per page, `locator="page:<n>"` (1-indexed) — pymupdf4llm's natural
    per-page granularity, which also gives OCR'd pages the same citable grain as text-layer ones.
    """

    locator: str
    text: str


class Source(BaseModel):
    """One ingested source, already parsed into citable blocks (CLAUDE.md invariant 3 — parsing
    happens before this object exists; nothing here does any I/O)."""

    id: str
    kind: SourceKind
    #: Human-readable origin for display (a file path or a URL) — never used as a locator.
    origin: str
    blocks: list[SourceBlock]
    #: Deterministic prompt-injection heuristic flags from `injection_scan.py` (CLAUDE.md invariant
    #: 5) — additive metadata, never a gate. Empty means "not flagged", not "verified clean".
    flags: list[str] = Field(default_factory=list)

    def marker(self, locator: str) -> str:
        """The literal `[[SRC:<id>|<locator>]]` marker text for one of this source's blocks."""
        return f"[[SRC:{self.id}|{locator}]]"

    def block_text(self, locator: str) -> str | None:
        """The text of the block at `locator`, or `None` if this source has no such block."""
        for block in self.blocks:
            if block.locator == locator:
                return block.text
        return None


class Citation(BaseModel):
    """A claimed citation. `source_id`/`locator` MUST be copied verbatim from a marker the model
    actually saw in the corpus blob (see `task.py`'s instructions) — `citations.py` verifies this
    coordinate exists; it does not verify `quote` is a faithful summary of that block's text (see
    CLAUDE.md invariant 5)."""

    source_id: str
    locator: str
    quote: str


class Answer(BaseModel):
    """`AnswerQuestion`'s SUBMIT shape."""

    text: str
    citations: list[Citation] = Field(default_factory=list)


class Summary(BaseModel):
    """`GenerateSummary`'s SUBMIT shape (`guide.py`) — the key points across a notebook's sources."""

    text: str
    citations: list[Citation] = Field(default_factory=list)


class FAQItem(BaseModel):
    """One question-and-answer pair within a `FAQ`."""

    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)


class FAQ(BaseModel):
    """`GenerateFAQ`'s SUBMIT shape (`guide.py`)."""

    items: list[FAQItem] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    """One entry in a `Timeline`. `when` is free text on purpose: an explicit date if the sources
    give one, otherwise a descriptive position ("before the trial began", "Chapter 3") — never a
    fabricated date standing in for one the sources don't state."""

    when: str
    description: str
    citations: list[Citation] = Field(default_factory=list)


class Timeline(BaseModel):
    """`GenerateTimeline`'s SUBMIT shape (`guide.py`). `events` may legitimately be empty — sources
    that describe no sequence of events at all should produce an empty timeline, not a fabricated
    one."""

    events: list[TimelineEvent] = Field(default_factory=list)


class KeyInsight(BaseModel):
    """`GenerateKeyInsight`'s SUBMIT shape (`guide.py`) — the single most important, non-obvious
    takeaway across a notebook's sources, in one sentence."""

    text: str
    citations: list[Citation] = Field(default_factory=list)


class VerifiedCitation(BaseModel):
    """A `Citation` after `citations.py` has checked it against the corpus (see `verify_citations`).
    `verified=False` means the coordinate did not resolve — the citation is surfaced as unverified,
    never silently dropped (CLAUDE.md invariant 5)."""

    citation: Citation
    verified: bool
    reason: str | None = None


class ChatTurn(BaseModel):
    """One past (question, answer) exchange in a `Notebook`'s history."""

    question: str
    answer: Answer


class Notebook(BaseModel):
    """Sources plus chat history that survive across `ask` invocations (see `notebook.py`). This is
    the whole persisted unit — one JSON file per notebook, no database."""

    id: str
    sources: list[Source] = Field(default_factory=list)
    turns: list[ChatTurn] = Field(default_factory=list)
