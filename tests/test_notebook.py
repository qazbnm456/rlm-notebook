from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from rlm_notebook.notebook import (
    EPHEMERAL_ID,
    add_note,
    append_sources,
    corpus_of,
    delete_note,
    existing_origins,
    history_text,
    ingest_sources_for,
    list_notebook_summaries,
    load_notebook,
    load_or_create,
    mutate_notebook,
    notebook_lock,
    notebook_path,
    promote_note,
    save_notebook,
    slug,
)
from rlm_notebook.schema import Answer, ChatTurn, Note, Notebook, Source, SourceBlock


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


def test_ingest_then_append_adds_the_source(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    notebook = Notebook(id="mynb")

    new_sources = append_sources(notebook, ingest_sources_for(notebook, [str(a)]))

    assert notebook.sources == new_sources
    assert notebook.sources[0].origin == str(a)
    assert notebook.sources[0].id == "s1"


def test_ingest_sources_for_does_not_touch_the_notebook(tmp_path):
    """The split's whole point: ingestion (slow — network/OCR) must be runnable OUTSIDE the lock,
    which means it cannot be the thing that mutates the notebook."""
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    notebook = Notebook(id="mynb")

    ingested = ingest_sources_for(notebook, [str(a)])

    assert len(ingested) == 1
    assert notebook.sources == []


def test_append_sources_skips_already_present_origins(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("hello b", encoding="utf-8")
    notebook = Notebook(id="mynb", sources=[_source("s1", str(a))])

    new_sources = append_sources(notebook, ingest_sources_for(notebook, [str(a), str(b)]))

    assert [s.origin for s in new_sources] == [str(b)]
    assert [s.origin for s in notebook.sources] == [str(a), str(b)]
    assert notebook.sources[1].id == "s2"  # continues numbering from the existing source, not s1


def test_ingest_sources_for_appends_nothing_when_ingestion_fails(tmp_path):
    notebook = Notebook(id="mynb", sources=[_source("s1", "a.txt")])
    with pytest.raises(OSError):
        ingest_sources_for(notebook, [str(tmp_path / "does-not-exist.txt")])
    assert len(notebook.sources) == 1  # unchanged


def test_append_sources_renumbers_against_the_notebook_it_is_given(tmp_path):
    """A source ingested against a snapshot carries an id derived from THAT snapshot's length. If a
    concurrent write landed in between, reusing it would duplicate an id already in use — so
    `append_sources` renumbers against the notebook it's actually appending to."""
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    snapshot = Notebook(id="mynb")
    ingested = ingest_sources_for(snapshot, [str(a)])
    assert ingested[0].id == "s1"  # numbered against the (empty) snapshot

    fresh = Notebook(id="mynb", sources=[_source("s1", "added-by-someone-else")])
    appended = append_sources(fresh, ingested)

    assert appended[0].id == "s2"
    assert [s.id for s in fresh.sources] == ["s1", "s2"]


# --- mutate_notebook / notebook_lock ------------------------------------------------------------


def _turn(question: str = "q?") -> ChatTurn:
    return ChatTurn(question=question, answer=Answer(text="an answer"))


def test_mutate_notebook_applies_to_a_freshly_loaded_notebook_not_the_callers_snapshot(tmp_path):
    """THE regression test for this slice. A handler holds a snapshot across slow work (an RLM run,
    an OCR pass); something else writes in the meantime; the handler then persists its own delta.
    Before `mutate_notebook`, saving the snapshot destroyed the concurrent write outright —
    reproduced live over HTTP against a real server, not hypothesised."""
    save_notebook(Notebook(id="mynb", sources=[_source("s1")]), base_dir=tmp_path)
    stale = load_notebook("mynb", base_dir=tmp_path)  # what a slow handler is holding

    concurrent = load_notebook("mynb", base_dir=tmp_path)
    concurrent.notes.append(Note(id="n1", text="written while the handler was busy"))
    save_notebook(concurrent, base_dir=tmp_path)

    result = mutate_notebook("mynb", lambda nb: nb.turns.append(_turn()), base_dir=tmp_path)

    assert [n.id for n in result.notes] == ["n1"]  # the concurrent write survived
    assert len(result.turns) == 1  # and so did this one's own delta
    assert load_notebook("mynb", base_dir=tmp_path).notes[0].text.startswith("written while")
    assert stale.turns == []  # the snapshot was never written back


def test_mutate_notebook_writes_nothing_when_the_closure_raises(tmp_path):
    save_notebook(Notebook(id="mynb", sources=[_source("s1")]), base_dir=tmp_path)

    def _explode(nb):
        nb.turns.append(_turn())  # a mutation that must NOT reach disk
        raise ValueError("no such note")

    with pytest.raises(ValueError, match="no such note"):
        mutate_notebook("mynb", _explode, base_dir=tmp_path)

    assert load_notebook("mynb", base_dir=tmp_path).turns == []


def test_mutate_notebook_raises_file_not_found_without_create(tmp_path):
    with pytest.raises(FileNotFoundError):
        mutate_notebook("nope", lambda nb: None, base_dir=tmp_path)


def test_mutate_notebook_creates_when_asked(tmp_path):
    result = mutate_notebook(
        "fresh", lambda nb: nb.notes.append(Note(id="n1", text="hi")), base_dir=tmp_path, create=True
    )

    assert result.id == "fresh"
    assert load_notebook("fresh", base_dir=tmp_path).notes[0].id == "n1"


def test_mutate_notebook_still_rejects_an_id_that_slugs_to_nothing(tmp_path):
    """Invariant 27's 400s must survive the rewrite: an all-punctuation id has to fail the same way
    through the locked write path as it does through every unlocked reader."""
    with pytest.raises(ValueError):
        mutate_notebook("!!!", lambda nb: None, base_dir=tmp_path, create=True)


def test_the_notebook_lock_does_not_leave_a_json_file_the_listing_would_pick_up(tmp_path):
    with notebook_lock("mynb", base_dir=tmp_path):
        pass
    assert list_notebook_summaries(base_dir=tmp_path) == ([], [])
    assert (tmp_path / ".mynb.json.lock").exists()


_HOLDS_THE_LOCK = """
import sys, time
from rlm_notebook.notebook import notebook_lock
with notebook_lock("mynb", base_dir=sys.argv[1]):
    open(sys.argv[2], "w").write("held")
    time.sleep(1.0)
"""


def test_the_notebook_lock_serializes_two_real_processes(tmp_path):
    """Spawns a REAL second process holding the lock, rather than asserting on two threads — the
    cross-process guarantee is the whole reason `cli.py` and a running `api.py` can write the same
    notebook file safely, and only `flock` (not `fcntl.lockf`, which is per-process) provides it.
    Same "verify it against a real process" discipline `test_runner.py`'s grandchild-cancellation
    test already applies."""
    pytest.importorskip("fcntl")
    signal_path = tmp_path / "held.txt"
    child = subprocess.Popen(
        [sys.executable, "-c", _HOLDS_THE_LOCK, str(tmp_path), str(signal_path)]
    )
    try:
        deadline = time.monotonic() + 10
        while not signal_path.exists():
            assert time.monotonic() < deadline, "child never acquired the lock"
            assert child.poll() is None, "child exited before acquiring the lock"
            time.sleep(0.02)

        started = time.monotonic()
        with notebook_lock("mynb", base_dir=tmp_path):
            waited = time.monotonic() - started
    finally:
        child.wait(timeout=10)

    assert waited > 0.3, f"acquired the lock in {waited:.3f}s — it was not actually held"


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


# --- Notes ----------------------------------------------------------------------------------------


def test_add_note_appends_and_numbers_sequentially():
    notebook = Notebook(id="mynb")
    n1 = add_note(notebook, "first note")
    n2 = add_note(notebook, "second note")
    assert (n1.id, n1.text) == ("n1", "first note")
    assert (n2.id, n2.text) == ("n2", "second note")
    assert [n.id for n in notebook.notes] == ["n1", "n2"]


def test_add_note_rejects_blank_text():
    notebook = Notebook(id="mynb")
    with pytest.raises(ValueError, match="empty"):
        add_note(notebook, "   ")
    assert notebook.notes == []


def test_delete_note_removes_by_id():
    notebook = Notebook(id="mynb")
    add_note(notebook, "keep me")
    add_note(notebook, "delete me")
    delete_note(notebook, "n2")
    assert [n.id for n in notebook.notes] == ["n1"]


def test_delete_note_raises_on_unknown_id():
    notebook = Notebook(id="mynb")
    add_note(notebook, "a note")
    with pytest.raises(ValueError, match="no note 'does-not-exist'"):
        delete_note(notebook, "does-not-exist")
    assert len(notebook.notes) == 1  # unchanged


def test_promote_note_turns_it_into_a_source_and_removes_it_from_notes():
    notebook = Notebook(id="mynb")
    add_note(notebook, "promote this text")

    source = promote_note(notebook, "n1")

    assert notebook.notes == []
    assert source is not None
    assert source.id == "s1"
    assert source.blocks[0].text == "promote this text"
    assert notebook.sources == [source]


def test_promote_note_numbers_the_new_source_after_existing_sources():
    notebook = Notebook(id="mynb", sources=[_source("s1", "a.txt")])
    add_note(notebook, "promote this text")

    source = promote_note(notebook, "n1")

    assert source.id == "s2"
    assert [s.id for s in notebook.sources] == ["s1", "s2"]


def test_promote_note_dedupes_against_an_identical_existing_source_and_returns_none():
    """Same content-hash-based dedup `add_sources`'s pasted-text loop already applies — promoting a
    note whose text is byte-identical to text already pasted as a source appends nothing new, but
    the note is still removed from `notes` either way (promotion is a completed action). Adds a
    SECOND, pre-existing source first so the reused note id (see `add_note`'s own docstring: an id
    can be reused after a delete/promote shrinks `notes`) isn't what this test is actually about."""
    notebook = Notebook(id="mynb", sources=[_source("s1", "a.txt")])
    add_note(notebook, "duplicate text")
    promote_note(notebook, "n1")  # creates s2
    add_note(notebook, "duplicate text")  # same text again, a new note (id reused: also "n1")

    result = promote_note(notebook, "n1")

    assert result is None
    assert notebook.notes == []
    assert len(notebook.sources) == 2  # no third source appended


def test_promote_note_raises_on_unknown_id():
    notebook = Notebook(id="mynb")
    with pytest.raises(ValueError, match="no note 'does-not-exist'"):
        promote_note(notebook, "does-not-exist")


def test_add_note_can_reuse_an_id_once_no_live_note_holds_it():
    """Safe id reuse: deleting the note that WAS `"n2"` frees that id for reuse, since no other
    live note holds it afterward."""
    notebook = Notebook(id="mynb")
    add_note(notebook, "first")
    add_note(notebook, "second")  # id "n2"
    delete_note(notebook, "n2")
    reused = add_note(notebook, "third")
    assert reused.id == "n2"


def test_add_note_never_collides_with_a_still_live_note_after_deleting_an_earlier_one():
    """The real bug an independent review found in the original `len(notes) + 1` id scheme: adding
    notes n1/n2, deleting the EARLIER one (n1, not the most recent), then adding a third used to
    reuse "n2" — colliding with the note that was still alive under that exact id. Confirms the fix
    (`_next_note_id` deriving from the max id actually in use, not the count) never lets that
    happen, regardless of which note gets deleted."""
    notebook = Notebook(id="mynb")
    add_note(notebook, "first")  # n1
    add_note(notebook, "second")  # n2
    delete_note(notebook, "n1")  # n2 is still alive
    third = add_note(notebook, "third")
    assert third.id != "n2"  # must not collide with the still-live note
    assert [n.id for n in notebook.notes] == ["n2", third.id]
    assert len({n.id for n in notebook.notes}) == 2  # no duplicate ids


def test_delete_note_removes_only_the_first_matching_note_by_index():
    """Defense in depth, verified directly: even if two notes somehow shared an id (bypassing
    `add_note`'s own now-collision-free scheme), `delete_note` removes exactly one, not both."""
    notebook = Notebook(id="mynb")
    notebook.notes = [Note(id="n2", text="first"), Note(id="n2", text="second")]
    delete_note(notebook, "n2")
    assert [n.text for n in notebook.notes] == ["second"]


def test_promote_note_promotes_only_the_first_matching_note_by_index():
    """Same defense-in-depth guarantee as `delete_note`, for `promote_note`."""
    notebook = Notebook(id="mynb")
    notebook.notes = [Note(id="n2", text="first"), Note(id="n2", text="second")]
    source = promote_note(notebook, "n2")
    assert source.blocks[0].text == "first"
    assert [n.text for n in notebook.notes] == ["second"]
