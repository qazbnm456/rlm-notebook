from __future__ import annotations

from rlm_notebook.citations import verify_citations
from rlm_notebook.corpus import Corpus
from rlm_notebook.schema import Citation, Source, SourceBlock


def _corpus() -> Corpus:
    corpus = Corpus()
    corpus.add(
        Source(
            id="s1",
            kind="pdf",
            origin="paper.pdf",
            blocks=[
                SourceBlock(locator="page:1", text="Apples are red or green."),
                SourceBlock(locator="page:2", text="Oranges are orange."),
            ],
        )
    )
    return corpus


def test_valid_citation_verifies():
    result = verify_citations(
        [Citation(source_id="s1", locator="page:1", quote="Apples are red or green.")], _corpus()
    )
    assert result[0].verified is True
    assert result[0].reason is None


def test_unknown_source_id_is_unverified_not_dropped():
    result = verify_citations([Citation(source_id="nope", locator="page:1", quote="x")], _corpus())
    assert len(result) == 1
    assert result[0].verified is False
    assert "nope" in result[0].reason


def test_unknown_locator_is_unverified_not_dropped():
    result = verify_citations([Citation(source_id="s1", locator="page:99", quote="x")], _corpus())
    assert len(result) == 1
    assert result[0].verified is False
    assert "page:99" in result[0].reason


def test_order_and_count_preserved():
    citations = [
        Citation(source_id="s1", locator="page:1", quote="a"),
        Citation(source_id="s1", locator="page:99", quote="b"),
        Citation(source_id="s1", locator="page:2", quote="c"),
    ]
    result = verify_citations(citations, _corpus())
    assert [v.verified for v in result] == [True, False, True]


def test_does_not_check_quote_faithfulness():
    """CLAUDE.md invariant 4: coordinate existence only. A wildly wrong quote at a real
    coordinate still verifies — this module makes no claim about content faithfulness."""
    result = verify_citations(
        [Citation(source_id="s1", locator="page:1", quote="Oranges are purple dinosaurs.")],
        _corpus(),
    )
    assert result[0].verified is True
