"""Notebook persistence: sources + chat history that survive across `ask` invocations.

A notebook is one JSON file, `<notebooks_dir>/<slug(id)>.json`, holding a `schema.Notebook` — the
sources ingested so far and every prior (question, answer) turn. This is deliberately the simplest
thing that lets `ask` be called more than once against the same accumulated context: one file, no
database, no locking, no concurrent-writer story — CLAUDE.md's Scope note already says there is no
API/UI yet, so there is exactly one writer at a time.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from pydantic import ValidationError

from .corpus import Corpus
from .ingest import ingest_new, ingest_pasted_text, with_injection_flags
from .schema import Note, Notebook, Source

DEFAULT_NOTEBOOKS_DIR = "notebooks"

#: Notebook id used when the caller (CLI/API) doesn't ask for persistence — never actually
#: persisted, so it never collides with a real notebook file on disk regardless of this string.
EPHEMERAL_ID = "_ephemeral"

#: Cap on a slugged notebook id, matching ctx-distillery's `cli._slug`/`_RUN_ID_MAX` reasoning: the
#: id becomes a filename, and most filesystems cap one path component at 255 bytes.
_SLUG_MAX = 120


def slug(raw: str) -> str:
    """A filesystem-safe notebook id: keep `[A-Za-z0-9._-]`, fold the rest to `-`, strip leading and
    trailing `.`/`-` so it can never become a traversal segment (`..`, an absolute path, a nested
    directory), and cap at `_SLUG_MAX` characters — re-stripping after the cut so a truncation
    landing on a `-`/`.` never leaves a trailing separator. `--notebook` is user input and becomes a
    path component; see CLAUDE.md's notebook-id invariant.
    """
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", raw or "").strip("-.")
    return token[:_SLUG_MAX].rstrip("-.")


def notebook_path(notebook_id: str, *, base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR) -> Path:
    safe = slug(notebook_id)
    if not safe:
        raise ValueError(f"notebook id {notebook_id!r} reduces to an empty token")
    return Path(base_dir) / f"{safe}.json"


def load_notebook(notebook_id: str, *, base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR) -> Notebook | None:
    """Load a notebook by id, or `None` if it doesn't exist yet — the caller decides whether that
    means "create a new one" or "error: no such notebook"."""
    path = notebook_path(notebook_id, base_dir=base_dir)
    if not path.exists():
        return None
    return Notebook.model_validate_json(path.read_text(encoding="utf-8"))


def save_notebook(notebook: Notebook, *, base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR) -> None:
    """Write `notebook` atomically: a same-directory temp file, `fsync`ed, then `os.replace`d onto
    the real path. Found by an independent review that a plain `path.write_text(...)` left a
    truncated, unparseable JSON file behind if the process was interrupted mid-write (Ctrl+C,
    crash, power loss) — the NEXT `load_notebook` call for that id would then raise an uncaught
    `pydantic.ValidationError` with no recovery but deleting the file, silently losing the whole
    conversation. `os.replace` is atomic on both POSIX and Windows, so a reader only ever sees the
    fully-old or fully-new file, never a partial one."""
    path = notebook_path(notebook.id, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(notebook.model_dump_json(indent=2))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def corpus_of(notebook: Notebook) -> Corpus:
    """A `Corpus` view over a notebook's accumulated sources, for `Corpus.blob()`/citation
    verification — a plain read, no persistence side effect."""
    return Corpus(sources=list(notebook.sources))


def existing_origins(notebook: Notebook) -> set[str]:
    """Origins (file paths/URLs) already ingested into `notebook` — the caller (`cli.py`) skips any
    `--source` value already in this set BEFORE parsing it, so re-passing the same source on a
    later `ask` against the same notebook is a cheap no-op rather than a duplicate re-ingestion."""
    return {s.origin for s in notebook.sources}


def load_or_create(
    notebook_id: str | None, *, base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR
) -> Notebook:
    """Load a notebook by id, or return a fresh, unpersisted one if it doesn't exist yet (or no id
    was given at all — an ephemeral notebook). Shared by `cli._prepare` and `api.py`'s endpoints,
    which both need the identical "get me a notebook to work with" step. Raises
    `pydantic.ValidationError` on a corrupted file, same as `load_notebook` — the caller decides
    how to report that (a CLI stderr message vs. an HTTP error response)."""
    notebook = load_notebook(notebook_id, base_dir=base_dir) if notebook_id else None
    if notebook is None:
        notebook = Notebook(id=notebook_id or EPHEMERAL_ID)
    return notebook


def extend_with_sources(notebook: Notebook, new_values: list[str]) -> list[Source]:
    """Ingest `new_values` not already present in `notebook` (by origin — see
    `existing_origins`), append them to `notebook.sources` IN PLACE, and return just the
    newly-added `Source` objects (so the caller can report which, if any, are flagged). Raises
    `parsers.web.FetchError`/`ValueError`/`OSError` on an ingestion failure, same as
    `ingest.ingest_new` (which this wraps) — nothing is appended if it raises."""
    new_sources = ingest_new(
        new_values, start_index=len(notebook.sources) + 1, skip_origins=existing_origins(notebook)
    )
    notebook.sources.extend(new_sources)
    return new_sources


def list_notebook_summaries(
    *, base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR
) -> tuple[list[Notebook], list[str]]:
    """Every notebook file under `base_dir`, for the web UI's notebook switcher — there is no other
    way to discover what notebooks exist than listing the directory, since a notebook's `id` (what a
    caller would look it up by) is only known once its file has already been parsed. Returns
    `(notebooks, unreadable)`: `unreadable` holds the filename STEM of any file that fails to parse
    as a `Notebook`, so one corrupted file is flagged rather than either silently dropped or breaking
    every other notebook's listing (the same "flag, never silently drop" discipline invariants 5/6
    already use elsewhere). Each returned `Notebook.id` is the value stored INSIDE the file, never
    the slugged filename stem — `slug()` is lossy, so the two can read back differently for the same
    file (see `notebook_path`'s docstring)."""
    base = Path(base_dir)
    if not base.exists():
        return [], []
    notebooks: list[Notebook] = []
    unreadable: list[str] = []
    for path in sorted(base.glob("*.json")):
        try:
            notebooks.append(Notebook.model_validate_json(path.read_text(encoding="utf-8")))
        except ValidationError:
            unreadable.append(path.stem)
    return notebooks, unreadable


def history_text(notebook: Notebook) -> str:
    """Every prior turn as plain text, oldest first, for the RLM task's `history` field. Context
    only — the task must still ground every citation in `sources` fresh each turn (`citations.py`
    verifies regardless of what a prior turn cited), never treat a past answer as its own source of
    truth. See CLAUDE.md's history invariant."""
    if not notebook.turns:
        return "(no prior turns in this conversation)"
    parts = [f"Q{i}: {turn.question}\nA{i}: {turn.answer.text}" for i, turn in enumerate(notebook.turns, start=1)]
    return "\n\n".join(parts)


def add_note(notebook: Notebook, text: str) -> Note:
    """Create and append a new `Note` to `notebook.notes` IN PLACE, numbered `n{len+1}` (mirrors
    `s{n}`'s sequential, human-legible source-id scheme). Raises `ValueError` on blank text, same
    discipline `parsers.text.parse_text` already applies to a blank text SOURCE. Deliberately does
    NOT call `save_notebook` itself — same convention every other mutator in this module already
    follows (`extend_with_sources` doesn't save either); the caller persists once, after the
    mutation.

    Unlike a source id (`notebook.sources` only ever grows, so `s{n}` is collision-free for the
    notebook's whole lifetime), a note id CAN be reused after `delete_note`/`promote_note` shrinks
    `notebook.notes` — e.g. deleting `"n2"` then adding a new note makes THAT note `"n2"` too. This
    is accepted, not fixed: nothing in this project holds a note id across such a gap (unlike
    `run_id`, which is embedded in a trace file path) — every note id is read fresh from the same
    `NotebookResponse` a UI action was rendered from, in the same request/response round trip."""
    if not text.strip():
        raise ValueError("note text is empty")
    note = Note(id=f"n{len(notebook.notes) + 1}", text=text)
    notebook.notes.append(note)
    return note


def delete_note(notebook: Notebook, note_id: str) -> None:
    """Removes the note with id `note_id` from `notebook.notes` IN PLACE. Raises `ValueError` if no
    such note exists, rather than a silent no-op on a typo'd id — the same "raise on a request that
    named something that doesn't exist" discipline `corpus.Corpus.filtered` already applies to an
    unknown source id."""
    before = len(notebook.notes)
    notebook.notes = [n for n in notebook.notes if n.id != note_id]
    if len(notebook.notes) == before:
        raise ValueError(f"no note {note_id!r} in this notebook")


def promote_note(notebook: Notebook, note_id: str) -> Source | None:
    """Turns a note into a real, independently-citable `Source`, reusing `ingest_pasted_text`
    UNCHANGED — the exact function pasted-text sources already go through — rather than a parallel
    code path, so a promoted note gets the IDENTICAL content-derived-origin, dedup, and
    injection-scan treatment `add_sources`'s pasted-text branch already gives any other pasted
    text (as far as ingestion is concerned, a note's text IS pasted text).

    Removes the note from `notebook.notes` REGARDLESS of outcome — promotion is a completed user
    action either way — then checks the candidate source's origin against
    `existing_origins(notebook)` (the same dedup-by-content-hash check `add_sources`'s pasted-text
    loop already performs): if identical text is already a source in this notebook, returns `None`
    and appends nothing new; otherwise appends the new (injection-scanned) `Source` and returns it.
    Raises `ValueError` if `note_id` doesn't exist, same as `delete_note`."""
    note = next((n for n in notebook.notes if n.id == note_id), None)
    if note is None:
        raise ValueError(f"no note {note_id!r} in this notebook")
    notebook.notes = [n for n in notebook.notes if n.id != note_id]
    candidate = ingest_pasted_text(note.text, source_id=f"s{len(notebook.sources) + 1}")
    if candidate.origin in existing_origins(notebook):
        return None
    source = with_injection_flags(candidate)
    notebook.sources.append(source)
    return source
