from __future__ import annotations

import pytest

from rlm_notebook.corpus import Corpus, CorpusTooLargeError
from rlm_notebook.schema import Source, SourceBlock


def _source(id_: str, text: str = "hello") -> Source:
    return Source(id=id_, kind="text", origin=id_, blocks=[SourceBlock(locator="whole", text=text)])


def test_blob_contains_every_marker_and_text():
    corpus = Corpus()
    corpus.add(_source("s1", "apples"))
    corpus.add(_source("s2", "oranges"))
    blob = corpus.blob()
    assert "[[SRC:s1|whole]]" in blob
    assert "apples" in blob
    assert "[[SRC:s2|whole]]" in blob
    assert "oranges" in blob


def test_add_rejects_duplicate_id():
    corpus = Corpus()
    corpus.add(_source("s1"))
    with pytest.raises(ValueError):
        corpus.add(_source("s1"))


def test_get_returns_none_for_unknown_id():
    corpus = Corpus()
    corpus.add(_source("s1"))
    assert corpus.get("s2") is None
    assert corpus.get("s1") is not None


def test_blob_raises_over_max_chars():
    corpus = Corpus()
    corpus.add(_source("s1", "x" * 1000))
    with pytest.raises(CorpusTooLargeError):
        corpus.blob(max_chars=10)


def test_blob_no_cap_when_max_chars_none():
    corpus = Corpus()
    corpus.add(_source("s1", "x" * 1000))
    assert len(corpus.blob(max_chars=None)) > 10


def test_filtered_keeps_only_named_sources_in_order():
    corpus = Corpus()
    corpus.add(_source("s1"))
    corpus.add(_source("s2"))
    corpus.add(_source("s3"))
    sub = corpus.filtered(["s3", "s1"])
    assert [s.id for s in sub.sources] == ["s1", "s3"]


def test_filtered_raises_on_unknown_id():
    corpus = Corpus()
    corpus.add(_source("s1"))
    with pytest.raises(ValueError):
        corpus.filtered(["s1", "nope"])


def test_an_excerpt_samples_every_source_not_just_the_first():
    """`blob()[:n]` is what this replaced, and a user reported the consequence: a four-source
    notebook was titled by transliterating source ONE's own paper title, because source one alone
    was 69,859 characters against a 4,000-character window — sources two to four were never seen.
    Language resolution read the same prefix, which is worse: later sources in another language
    would have resolved the wrong one."""
    from rlm_notebook.corpus import Corpus
    from rlm_notebook.schema import Source, SourceBlock

    sources = [
        Source(
            id=f"s{i}",
            kind="web",
            origin=f"https://example.com/{i}",
            blocks=[SourceBlock(locator="whole", text=f"SOURCE-{i}-OPENING " + "x" * 20_000)],
        )
        for i in (1, 2, 3, 4)
    ]
    corpus = Corpus(sources)

    excerpt = corpus.excerpt(4000)
    assert len(excerpt) <= 4000
    for i in (1, 2, 3, 4):
        assert f"SOURCE-{i}-OPENING" in excerpt, f"source {i} is invisible to the excerpt"

    # ...and the prefix this replaced genuinely could not see them, so the test is not vacuous.
    prefix = corpus.blob(max_chars=None)[:4000]
    assert "SOURCE-2-OPENING" not in prefix


def test_an_excerpt_of_one_source_is_still_its_opening():
    from rlm_notebook.corpus import Corpus
    from rlm_notebook.schema import Source, SourceBlock

    corpus = Corpus([
        Source(id="s1", kind="text", origin="o",
               blocks=[SourceBlock(locator="whole", text="THE OPENING LINE. " + "y" * 9000)])
    ])
    excerpt = corpus.excerpt(500)
    assert "THE OPENING LINE." in excerpt
    assert len(excerpt) <= 500


def test_an_excerpt_of_an_empty_corpus_is_empty():
    from rlm_notebook.corpus import Corpus

    assert Corpus([]).excerpt(4000) == ""
