from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from rlm_notebook.notebook import (
    EPHEMERAL_ID,
    corpus_of,
    existing_origins,
    extend_with_sources,
    history_text,
    list_notebook_summaries,
    load_notebook,
    load_or_create,
    notebook_path,
    save_notebook,
    slug,
)
from rlm_notebook.schema import Answer, ChatTurn, Notebook, Source, SourceBlock


def _source(id_: str, origin: str = "x") -> Source:
    return Source(id=id_, kind="text", origin=origin, blocks=[SourceBlock(locator="whole", text="hi")])


def test_slug_keeps_safe_characters():
    assert slug("my notebook 1") == "my-notebook-1"


@pytest.mark.parametrize(
    "raw",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "..",
        "....",
        "////",
        "a/../../b",
        "..\\..\\windows",
    ],
)
def test_slug_never_produces_a_path_separator(raw):
    """The whitelist (`[A-Za-z0-9._-]`, everything else folds to `-`) makes a path SEPARATOR
    structurally impossible in the output, regardless of how the input tries to sneak one in — a
    single-example test can't demonstrate that, so this parametrizes over the payloads an
    independent review tried by hand when auditing this function. Note this does NOT assert `".."`
    is absent from the output: a slug like `"a-..-..-b"` is safe precisely because it has no
    separator to make those dots mean anything — `notebook_path()` always treats the whole slug as
    ONE path component (`Path(base_dir) / f"{safe}.json"`), never multiple segments."""
    result = slug(raw)
    assert "/" not in result
    assert "\\" not in result
    # The real safety property: joining `result` onto base_dir can never escape it. An
    # all-separator/all-dot input reduces to an empty slug, which `notebook_path` refuses outright
    # rather than silently writing to `base_dir` itself.
    if not result:
        with pytest.raises(ValueError):
            notebook_path(raw, base_dir="notebooks")
    else:
        assert notebook_path(raw, base_dir="notebooks").parent == Path("notebooks")


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


def test_save_notebook_leaves_no_tmp_file_behind_on_success(tmp_path):
    save_notebook(Notebook(id="mynb"), base_dir=tmp_path)
    assert list(tmp_path.iterdir()) == [notebook_path("mynb", base_dir=tmp_path)]


def test_save_notebook_is_atomic_an_interrupted_write_never_corrupts_the_real_file(tmp_path, monkeypatch):
    """A crash/Ctrl+C during `save_notebook` must never leave a truncated, unparseable file at the
    real path — found by an independent review: the first version wrote directly to the real path
    with no temp file, so an interruption mid-write corrupted it with no recovery. Simulates the
    interruption by making `os.fsync` raise partway through a save that is EXTENDING an existing,
    previously-saved notebook, and confirms the original file is untouched and no `.tmp` litter is
    left in the directory."""
    original = Notebook(id="mynb", sources=[_source("s1", "a.txt")])
    save_notebook(original, base_dir=tmp_path)
    before = notebook_path("mynb", base_dir=tmp_path).read_bytes()

    def _boom(_fd):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(os, "fsync", _boom)
    updated = original.model_copy(update={"sources": [*original.sources, _source("s2", "b.txt")]})
    with pytest.raises(OSError, match="simulated crash"):
        save_notebook(updated, base_dir=tmp_path)

    assert notebook_path("mynb", base_dir=tmp_path).read_bytes() == before
    assert list(tmp_path.iterdir()) == [notebook_path("mynb", base_dir=tmp_path)]  # no .tmp litter


def test_load_notebook_raises_a_clear_error_on_a_corrupted_file(tmp_path):
    """Not this project's own writer (which is atomic — see the test above), but a hand-edited or
    otherwise externally-corrupted file must still fail with a specific, catchable error rather
    than an assertion or a silent wrong answer. `cli._cmd_ask` catches exactly this (`ValidationError`)
    to print a clear message instead of a raw traceback."""
    path = notebook_path("mynb", base_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"id": "mynb", "sources": [}', encoding="utf-8")  # truncated JSON

    with pytest.raises(ValidationError):
        load_notebook("mynb", base_dir=tmp_path)


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


def test_load_or_create_loads_an_existing_notebook(tmp_path):
    save_notebook(Notebook(id="mynb", sources=[_source("s1", "a.txt")]), base_dir=tmp_path)
    notebook = load_or_create("mynb", base_dir=tmp_path)
    assert notebook.id == "mynb"
    assert notebook.sources[0].origin == "a.txt"


def test_load_or_create_returns_a_fresh_notebook_when_id_is_missing(tmp_path):
    notebook = load_or_create("does-not-exist-yet", base_dir=tmp_path)
    assert notebook.id == "does-not-exist-yet"
    assert notebook.sources == []
    assert not notebook_path("does-not-exist-yet", base_dir=tmp_path).exists()  # not persisted


def test_load_or_create_returns_an_ephemeral_notebook_when_no_id_given(tmp_path):
    notebook = load_or_create(None, base_dir=tmp_path)
    assert notebook.id == EPHEMERAL_ID


def test_load_or_create_raises_on_a_corrupted_file(tmp_path):
    path = notebook_path("mynb", base_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"id": "mynb", "sources": [}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_or_create("mynb", base_dir=tmp_path)


def test_extend_with_sources_mutates_the_notebook_in_place(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    notebook = Notebook(id="mynb")

    new_sources = extend_with_sources(notebook, [str(a)])

    assert notebook.sources == new_sources
    assert notebook.sources[0].origin == str(a)
    assert notebook.sources[0].id == "s1"


def test_extend_with_sources_skips_already_present_origins(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("hello b", encoding="utf-8")
    notebook = Notebook(id="mynb", sources=[_source("s1", str(a))])

    new_sources = extend_with_sources(notebook, [str(a), str(b)])

    assert [s.origin for s in new_sources] == [str(b)]
    assert [s.origin for s in notebook.sources] == [str(a), str(b)]
    assert notebook.sources[1].id == "s2"  # continues numbering from the existing source, not s1


def test_extend_with_sources_appends_nothing_when_ingestion_fails(tmp_path):
    notebook = Notebook(id="mynb", sources=[_source("s1", "a.txt")])
    with pytest.raises(OSError):
        extend_with_sources(notebook, [str(tmp_path / "does-not-exist.txt")])
    assert len(notebook.sources) == 1  # unchanged


def test_list_notebook_summaries_empty_dir_that_does_not_exist_yet(tmp_path):
    assert list_notebook_summaries(base_dir=tmp_path / "does-not-exist") == ([], [])


def test_list_notebook_summaries_reports_the_stored_id_not_the_slugged_filename(tmp_path):
    """A notebook id with characters outside the slug whitelist is folded before becoming a
    filename — the listing must report the `id` stored INSIDE the file, not derive one from the
    filename stem, or the two could read back differently for the same file."""
    save_notebook(Notebook(id="My Notebook!", sources=[_source("s1", "a.txt")]), base_dir=tmp_path)

    notebooks, unreadable = list_notebook_summaries(base_dir=tmp_path)

    assert unreadable == []
    assert [nb.id for nb in notebooks] == ["My Notebook!"]


def test_list_notebook_summaries_flags_a_corrupted_file_without_breaking_the_rest(tmp_path):
    save_notebook(Notebook(id="good"), base_dir=tmp_path)
    (tmp_path / "broken.json").write_text('{"id": "broken", "sources": [}', encoding="utf-8")

    notebooks, unreadable = list_notebook_summaries(base_dir=tmp_path)

    assert [nb.id for nb in notebooks] == ["good"]
    assert unreadable == ["broken"]
