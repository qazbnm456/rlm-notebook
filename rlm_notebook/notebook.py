"""Notebook persistence: sources + chat history that survive across `ask` invocations.

A notebook is one JSON file, `<notebooks_dir>/<slug(id)>.json`, holding a `schema.Notebook` — the
sources ingested so far and every prior (question, answer) turn. This is deliberately the simplest
thing that lets `ask` be called more than once against the same accumulated context: one file, no
database, no locking, no concurrent-writer story — CLAUDE.md's Scope note already says there is no
API/UI yet, so there is exactly one writer at a time.
"""

from __future__ import annotations

import re
from pathlib import Path

from .corpus import Corpus
from .schema import Notebook

DEFAULT_NOTEBOOKS_DIR = "notebooks"

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
    path = notebook_path(notebook.id, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(notebook.model_dump_json(indent=2), encoding="utf-8")


def corpus_of(notebook: Notebook) -> Corpus:
    """A `Corpus` view over a notebook's accumulated sources, for `Corpus.blob()`/citation
    verification — a plain read, no persistence side effect."""
    return Corpus(sources=list(notebook.sources))


def existing_origins(notebook: Notebook) -> set[str]:
    """Origins (file paths/URLs) already ingested into `notebook` — the caller (`cli.py`) skips any
    `--source` value already in this set BEFORE parsing it, so re-passing the same source on a
    later `ask` against the same notebook is a cheap no-op rather than a duplicate re-ingestion."""
    return {s.origin for s in notebook.sources}


def history_text(notebook: Notebook) -> str:
    """Every prior turn as plain text, oldest first, for the RLM task's `history` field. Context
    only — the task must still ground every citation in `sources` fresh each turn (`citations.py`
    verifies regardless of what a prior turn cited), never treat a past answer as its own source of
    truth. See CLAUDE.md's history invariant."""
    if not notebook.turns:
        return "(no prior turns in this conversation)"
    parts = [f"Q{i}: {turn.question}\nA{i}: {turn.answer.text}" for i, turn in enumerate(notebook.turns, start=1)]
    return "\n\n".join(parts)
