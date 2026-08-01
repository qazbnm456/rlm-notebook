from __future__ import annotations

import pytest

from rlm_notebook.notebook import (
    corpus_of,
    existing_origins,
    history_text,
    load_notebook,
    notebook_path,
    save_notebook,
    slug,
)
from rlm_notebook.schema import Answer, ChatTurn, Notebook, Source, SourceBlock


def _source(id_: str, origin: str = "x") -> Source:
    return Source(id=id_, kind="text", origin=origin, blocks=[SourceBlock(locator="whole", text="hi")])


def test_slug_keeps_safe_characters():
    assert slug("my notebook 1") == "my-notebook-1"


def test_slug_strips_traversal_segments():
    assert ".." not in slug("../../etc/passwd")
    assert slug("../../etc/passwd").startswith("etc") or "/" not in slug("../../etc/passwd")


def test_slug_caps_length():
    assert len(slug("x" * 500)) <= 120


def test_notebook_path_raises_on_empty_slug(tmp_path):
    with pytest.raises(ValueError):
        notebook_path("...", base_dir=tmp_path)


def test_load_notebook_returns_none_when_missing(tmp_path):
    assert load_notebook("nope", base_dir=tmp_path) is None


def test_save_then_load_round_trips(tmp_path):
    notebook = Notebook(
        id="mynb",
        sources=[_source("s1", "a.txt")],
        turns=[ChatTurn(question="what?", answer=Answer(text="this.", citations=[]))],
    )
    save_notebook(notebook, base_dir=tmp_path)
    loaded = load_notebook("mynb", base_dir=tmp_path)

    assert loaded is not None
    assert loaded.id == "mynb"
    assert loaded.sources[0].origin == "a.txt"
    assert loaded.turns[0].question == "what?"


def test_save_notebook_creates_base_dir(tmp_path):
    base = tmp_path / "does" / "not" / "exist"
    notebook = Notebook(id="mynb")
    save_notebook(notebook, base_dir=base)
    assert notebook_path("mynb", base_dir=base).exists()


def test_corpus_of_reflects_notebook_sources():
    notebook = Notebook(id="mynb", sources=[_source("s1", "a.txt"), _source("s2", "b.txt")])
    corpus = corpus_of(notebook)
    assert [s.id for s in corpus.sources] == ["s1", "s2"]


def test_existing_origins():
    notebook = Notebook(id="mynb", sources=[_source("s1", "a.txt"), _source("s2", "b.txt")])
    assert existing_origins(notebook) == {"a.txt", "b.txt"}


def test_history_text_empty_conversation():
    notebook = Notebook(id="mynb")
    assert "no prior turns" in history_text(notebook)


def test_history_text_includes_prior_turns_in_order():
    notebook = Notebook(
        id="mynb",
        turns=[
            ChatTurn(question="first?", answer=Answer(text="first answer.")),
            ChatTurn(question="second?", answer=Answer(text="second answer.")),
        ],
    )
    text = history_text(notebook)
    assert text.index("first?") < text.index("second?")
    assert "first answer." in text
    assert "second answer." in text
