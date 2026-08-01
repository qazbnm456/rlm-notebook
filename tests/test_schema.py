from __future__ import annotations

import pytest
from pydantic import ValidationError

from rlm_notebook.schema import (
    FAQ,
    Answer,
    Citation,
    FAQItem,
    KeyInsight,
    PodcastScript,
    Source,
    SourceBlock,
    Summary,
    Timeline,
    TimelineEvent,
    Utterance,
)


def test_source_marker_and_block_text():
    source = Source(
        id="s1",
        kind="text",
        origin="notes.txt",
        blocks=[SourceBlock(locator="whole", text="hello world")],
    )
    assert source.marker("whole") == "[[SRC:s1|whole]]"
    assert source.block_text("whole") == "hello world"
    assert source.block_text("page:1") is None


def test_source_flags_default_empty():
    source = Source(id="s1", kind="text", origin="x", blocks=[SourceBlock(locator="whole", text="x")])
    assert source.flags == []


def test_answer_round_trips_citations():
    answer = Answer(
        text="X is Y.",
        citations=[Citation(source_id="s1", locator="whole", quote="Y is stated here")],
    )
    dumped = answer.model_dump()
    assert dumped["citations"][0]["source_id"] == "s1"


def test_summary_defaults_to_no_citations():
    assert Summary(text="a summary").citations == []


def test_faq_holds_items_with_their_own_citations():
    faq = FAQ(
        items=[
            FAQItem(
                question="what color are apples?",
                answer="red or green",
                citations=[Citation(source_id="s1", locator="page:1", quote="Apples are red or green.")],
            )
        ]
    )
    assert faq.items[0].citations[0].source_id == "s1"


def test_faq_defaults_to_no_items():
    assert FAQ().items == []


def test_timeline_events_default_to_empty_list():
    """A source describing no sequence of events must be representable as an empty timeline, not
    force a fabricated event into existence."""
    assert Timeline().events == []


def test_timeline_event_when_is_free_text_not_a_parsed_date():
    event = TimelineEvent(when="before the trial began", description="setup phase")
    assert event.when == "before the trial began"


def test_key_insight_round_trips_citations():
    insight = KeyInsight(
        text="the single most important thing",
        citations=[Citation(source_id="s1", locator="whole", quote="x")],
    )
    assert insight.model_dump()["citations"][0]["source_id"] == "s1"


def test_utterance_requires_a_known_speaker():
    with pytest.raises(ValidationError):
        Utterance(speaker="host_c", text="hello")


def test_utterance_round_trips_citations():
    utterance = Utterance(
        speaker="host_a",
        text="did you know...",
        citations=[Citation(source_id="s1", locator="page:1", quote="x")],
    )
    assert utterance.model_dump()["citations"][0]["source_id"] == "s1"


def test_podcast_script_defaults_to_no_utterances():
    """A source with nothing worth discussing must be representable as an empty script, not force
    a fabricated episode into existence — same allowance Timeline/FAQ already make."""
    assert PodcastScript().utterances == []
