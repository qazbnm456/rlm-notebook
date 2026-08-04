"""dspy-free data shapes shared across ingestion, the corpus blob, and the RLM task.

Kept separate from `task.py` (which imports `rlm_harness.RLMTask`, and therefore `dspy`) for the same
reason ctx-distillery split its own `schema.py` out of `task.py`: importing these shapes from
`corpus.py`/`citations.py`/a future CLI-only code path should never drag `dspy` in.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SourceKind = Literal["text", "web", "pdf", "youtube"]


class SourceBlock(BaseModel):
    """One citable unit of a source's text, tagged with the locator a citation must echo verbatim.

    A `text`/`web` source has exactly one block, `locator="whole"` — see CLAUDE.md's Scope note:
    finer-grained (paragraph/char-offset) citation within a text/web source is a deferred follow-up.
    A `pdf` source has one block per page, `locator="page:<n>"` (1-indexed) — a PDF's own natural
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


Speaker = Literal["host_a", "host_b"]


class Utterance(BaseModel):
    """One line of dialogue in a `PodcastScript`, spoken by a fixed two-host cast (`host_a`/
    `host_b` — see CLAUDE.md's Audio Overview invariant for why the cast is fixed rather than
    freely-named). Citation-grounded like everything else this project generates: `citations`
    verifies the same way `Answer.citations` does."""

    speaker: Speaker
    text: str
    citations: list[Citation] = Field(default_factory=list)


class PodcastScript(BaseModel):
    """`GeneratePodcastScript`'s SUBMIT shape (`audio.py`). `utterances` may legitimately be empty
    — sources with nothing worth discussing should produce an empty script, not a fabricated one,
    the same allowance `Timeline.events`/`FAQ.items` already make."""

    utterances: list[Utterance] = Field(default_factory=list)


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
    #: The run id `api.py` used for the RLMTask that produced this turn, if any — `None` for any
    #: turn saved before this field existed (backward-compatible: pydantic defaults it, no
    #: migration needed) or for a turn created outside the API (e.g. `cli.py`, which has no
    #: subprocess-per-run concept to name). Lets the web UI's Chat panel offer a "view reasoning"
    #: link back to `traces/{run_id}.jsonl` on a re-opened notebook's history, even long after the
    #: run finished — see `docs/design/web-ui-blueprint.md`'s Phase 3 addendum.
    run_id: str | None = None


class Note(BaseModel):
    """A user-curated note — written directly, or copied from a past `Answer`'s text (see the web
    UI's "Save as note" button, `docs/design/web-ui-blueprint.md`'s Notes addendum). Deliberately
    carries NO citations of its own: a note's text may have originated from a citation-grounded
    `Answer`, but the note itself is not re-verified against `sources` (CLAUDE.md invariant 5's
    coordinate-only guarantee doesn't extend to freeform notes) until/unless it's PROMOTED into a
    real `Source` (`notebook.promote_note`), at which point it's grounded and citable exactly like
    any other source, no differently."""

    id: str
    text: str


class Notebook(BaseModel):
    """Sources plus chat history that survive across `ask` invocations (see `notebook.py`). This is
    the whole persisted unit — one JSON file per notebook, no database."""

    id: str
    sources: list[Source] = Field(default_factory=list)
    turns: list[ChatTurn] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)
