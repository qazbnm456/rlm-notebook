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

    A `text`/`web` source has exactly one block, `locator="whole"` — see AGENTS.md's Scope note:
    finer-grained (paragraph/char-offset) citation within a text/web source is a deferred follow-up.
    A `pdf` source has one block per page, `locator="page:<n>"` (1-indexed) — a PDF's own natural
    per-page granularity, which also gives OCR'd pages the same citable grain as text-layer ones.
    """

    locator: str
    text: str


class Source(BaseModel):
    """One ingested source, already parsed into citable blocks (AGENTS.md invariant 3 — parsing
    happens before this object exists; nothing here does any I/O)."""

    id: str
    kind: SourceKind
    #: Human-readable origin for display (a file path or a URL) — never used as a locator.
    origin: str
    blocks: list[SourceBlock]
    #: Deterministic prompt-injection heuristic flags from `injection_scan.py` (AGENTS.md invariant
    #: 6) — additive metadata, never a gate. Empty means "not flagged", not "verified clean".
    flags: list[str] = Field(default_factory=list)
    #: DISPLAY-ONLY metadata scraped from the page that was already fetched (a title, a description,
    #: a site name). Never reaches a prompt and is never citable — the corpus blob is built from
    #: `blocks` alone — so a page controlling its own `<meta>` tags can influence only what a Sources
    #: row LOOKS like, which is the same trust level `origin` already has. Optional and defaulting
    #: to empty, so notebooks written before this field existed still load.
    preview: dict[str, str] = Field(default_factory=dict)

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
    coordinate exists; it does not verify `quote` is genuinely verbatim from that block (the model is
    INSTRUCTED to copy it exactly — see `instructions.CITATION_RULES` — but nothing checks it; see
    AGENTS.md invariant 5)."""

    source_id: str
    locator: str
    quote: str
    #: The stretch of the model's OWN prose that this citation supports, copied verbatim from it.
    #:
    #: This is what lets the UI draw its signature interaction — a citation as a highlighter stroke
    #: through the sentence it backs (`web/DESIGN.md` §2) — and it exists because that interaction
    #: BROKE. The stroke used to be located by finding `quote` inside the answer, which works only
    #: while both are in the same language; since invariant 39 the prose follows the READER and the
    #: quote stays in the SOURCE's language, so the two never share a substring and no span could
    #: ever be found. A user reported the strokes had simply disappeared.
    #:
    #: Optional and defaulting to `None`, so every citation persisted before this field existed
    #: still loads — the same backward-compatible precedent `ChatTurn.run_id` and `Notebook.notes`
    #: set. `citations.py` checks it really occurs in the prose and drops it if not, which is the
    #: same coordinate-existence discipline invariant 5 already describes: a claim that cannot be
    #: located is discarded rather than trusted, and the citation itself survives either way.
    answer_span: str | None = None


class Answer(BaseModel):
    """`AnswerQuestion`'s SUBMIT shape."""

    text: str
    citations: list[Citation] = Field(default_factory=list)
    #: Two or three questions THESE sources can answer next, in the reader's language.
    #:
    #: On the ANSWER rather than from a second model call, which is the whole point: the model has
    #: the corpus and its own answer in context already, so this costs nothing extra. Starter
    #: questions previously existed only on the overview (invariant 38), so the affordance a user
    #: found useful appeared exactly once per notebook and never again.
    #:
    #: NOT citation-grounded and deliberately not verified: a question is a prompt, not a claim, so
    #: invariant 5 has nothing to check. Optional and defaulting to empty, so every turn persisted
    #: before this field existed still loads.
    follow_ups: list[str] = Field(default_factory=list)


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


#: How long an episode should aim to be. Three tiers, the same shape NotebookLM offers (Shorter /
#: Default / Longer), chosen after MEASURING that this project's own episodes all landed at roughly
#: three minutes regardless of what was in the notebook: the instructions asked for "a natural
#: episode length" and never named a number, and the notebook with the MOST sources produced the
#: SHORTEST of the four measured — so "let the sources decide" demonstrably was not happening.
#: (The notebooks that measurement came from were cleared at the owner's request, so it is not
#: reproducible from what is on disk — and `notebooks/` cannot confirm or refute it either way.)
PodcastLength = Literal["short", "default", "long"]

#: How much WALL CLOCK each tier is allowed, as a multiple of `NotebookConfig.run_timeout_seconds`.
#:
#: Not a tuning knob — a defect report. A `long` episode timed out at the 300s default backstop with
#: a trace holding three events: the run started, the model read two skills at 6.8s, and nothing
#: else was ever written before `killpg`. On the same notebook and the same model, an ordinary chat
#: answer took 77s across 4-5 planner turns, with one single turn costing 54s. A tier asking for
#: 60-90 utterances ACCUMULATED ACROSS REPL TURNS (invariant 64) needs many more turns than that, so
#: 300s could not have been enough and the tier shipped unable to finish under its own default.
#:
#: The backstop exists to catch a RUNAWAY, not to cap work the reader explicitly asked for — so it
#: scales with what was asked for. Lives NEXT TO the tier literal on purpose: adding a fourth tier
#: without deciding its budget should be impossible, and a tripwire test asserts every tier has one.
PODCAST_TIMEOUT_FACTOR: dict[str, float] = {"short": 1.0, "default": 2.0, "long": 5.0}

Speaker = Literal["host_a", "host_b"]


class Utterance(BaseModel):
    """One line of dialogue in a `PodcastScript`, spoken by a fixed two-host cast (`host_a`/
    `host_b` — see AGENTS.md's Audio Overview invariant for why the cast is fixed rather than
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
    never silently dropped (AGENTS.md invariant 5)."""

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
    #: run finished — see `docs/invariants/29-the-web-ui-is-a-product-surface.md`.
    run_id: str | None = None


class Note(BaseModel):
    """A user-curated note — written directly, or copied from a past `Answer`'s text (see the web
    UI's "Save as note" button;
    `docs/invariants/32-notes-are-uncited-until-promoted.md`). Deliberately
    carries NO citations of its own: a note's text may have originated from a citation-grounded
    `Answer`, but the note itself is not re-verified against `sources` (AGENTS.md invariant 5's
    coordinate-only guarantee doesn't extend to freeform notes) until/unless it's PROMOTED into a
    real `Source` (`notebook.promote_note`), at which point it's grounded and citable exactly like
    any other source, no differently."""

    id: str
    text: str


class Overview(BaseModel):
    """The notebook's front page: a Summary plus the FAQ questions offered as follow-ups.

    The ONE guide artifact persisted onto a notebook (a deliberately narrow cut of the long-deferred
    "guide artifacts aren't cached" scope item). The overview is what a returning user expects to
    still be there; a Studio tab is an on-demand tool and stays on demand.
    """

    text: str
    citations: list[Citation] = Field(default_factory=list)
    starter_questions: list[str] = Field(default_factory=list)
    #: The SUMMARY run, for the trace affordance. Outlives its trace file once
    #: `RN_TRACE_RETENTION_DAYS` collects it — same as `ChatTurn.run_id`, degrading to no affordance
    #: rather than a broken page, but this is now the most visible instance of that.
    run_id: str | None = None
    #: The source ids this was computed from, captured at RUN START — never at persist time. That
    #: distinction is the whole staleness mechanism: a source added while the run was in flight was
    #: never read by the model, so listing it here would claim coverage that doesn't exist. The
    #: honest consequence is that such an overview lands ALREADY STALE. Same reasoning `ask` uses
    #: for verifying citations against the snapshot corpus — "the blob the model actually read".
    source_ids: list[str] = Field(default_factory=list)


class Podcast(BaseModel):
    """A generated Audio Overview, persisted so it survives a reload.

    **This deliberately reverses Phase 2's "no audio is ever persisted past one request".** That
    decision bought a real simplification — no file-serving endpoint, no retention to get right —
    and it cost the user the episode the moment they reloaded, which is what a user reported after
    asking where the mp3 was. The audio is stored as ONE file per notebook, replaced on regenerate,
    so the growth is bounded by the number of notebooks rather than by the number of generations.
    """

    utterances: list[Utterance] = Field(default_factory=list)
    #: Each utterance's start offset in seconds, PARALLEL to `utterances` — what lets the transcript
    #: behave like subtitles (highlight the line being spoken, click a line to seek). A separate
    #: list rather than a field on `Utterance` because `Utterance` is the MODEL's output shape and
    #: the model has no idea how long its own words take to say; this is measured at synthesis.
    #: May be empty, or a different length, when a provider reports no timing. A LENGTH check is
    #: not enough on its own: a provider that reports no boundaries at all returns one zero per
    #: utterance, which is the right length — consumers must also require the offsets to ADVANCE
    #: (`app.js`'s `timed`) and otherwise render a plain transcript rather than mis-aligning it.
    offsets: list[float] = Field(default_factory=list)
    run_id: str | None = None
    #: Same staleness key as `Overview`: the sources this was generated from, captured at RUN START.
    source_ids: list[str] = Field(default_factory=list)


class Notebook(BaseModel):
    """Sources plus chat history that survive across `ask` invocations (see `notebook.py`). This is
    the whole persisted unit — one JSON file per notebook, no database."""

    id: str
    #: A human label, suggested from the sources (`naming.py`) — NOT the id. The id stays a stable
    #: handle that filenames, `ChatTurn.run_id` prefixes and every URL are built from, so a notebook
    #: can be titled (and one day retitled) without moving a file or invalidating a run id. Optional
    #: and defaulting to None, so every notebook written before this field existed still loads —
    #: the same backward-compatible precedent `ChatTurn.run_id` and `Notebook.notes` already set.
    title: str | None = None
    #: The language model-authored prose is written in, resolved ONCE from the reader's signals and
    #: persisted (`naming.SuggestLanguage`). `None` = never resolved, which falls back to today's
    #: behaviour. `RN_OUTPUT_LANGUAGE` overrides it at generation time, so changing the env takes
    #: effect without re-resolving. Records the CURRENT setting only: an artifact generated before it
    #: changed carries no record of what it was written in — the same gap a sibling project had to
    #: close by adding a locale column to its transcripts, noted here rather than fixed.
    output_language: str | None = None
    #: The persisted Audio Overview, if one has been generated. The mp3 itself lives beside the
    #: notebook file (see `notebook.audio_path`), not in here — a multi-MB base64 blob inside the
    #: JSON would be re-parsed on every single read of this notebook.
    podcast: Podcast | None = None
    #: The persisted chat overview, if one has been generated. Optional and defaulting to None, so
    #: notebooks written before it existed still load (the precedent `run_id`/`notes`/`title` set).
    overview: Overview | None = None
    sources: list[Source] = Field(default_factory=list)
    turns: list[ChatTurn] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)
