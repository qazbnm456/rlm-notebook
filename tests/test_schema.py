from __future__ import annotations

from rlm_notebook.schema import Answer, Citation, Source, SourceBlock


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
