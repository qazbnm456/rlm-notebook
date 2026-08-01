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
