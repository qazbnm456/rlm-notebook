"""Notebook persistence: sources + chat history that survive across `ask` invocations.

A notebook is one JSON file, `<notebooks_dir>/<slug(id)>.json`, holding a `schema.Notebook` — the
sources ingested so far and every prior (question, answer) turn. One file, no database.

**Every mutation goes through `mutate_notebook`, which re-loads from disk inside a per-notebook
lock.** This module used to say "no locking, no concurrent-writer story — there is exactly one
writer at a time," which was true when `cli.py` was the only entry point and has been false since
`api.py` started serving concurrent HTTP requests. A whole-file `save_notebook` of an object read
minutes earlier silently destroys everything written in between — reproduced live over real HTTP
(a source and a note added while an `ask` was running, both returning 200, both gone afterwards);
see CLAUDE.md's notebook-durability invariant. Read the `mutate_notebook`/`notebook_lock`
docstrings before adding a new write path.
"""

from __future__ import annotations

import hashlib
import re
import threading
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from .atomic import atomic_write_text
from .corpus import Corpus
from .ingest import ingest_new, ingest_pasted_text, with_injection_flags
from .schema import Note, Notebook, Source

try:
    import fcntl
except ImportError:  # pragma: no cover — POSIX only; see `notebook_lock` for the fallback
    fcntl = None  # type: ignore[assignment]

DEFAULT_NOTEBOOKS_DIR = "notebooks"

#: Notebook id used when the caller (CLI/API) doesn't ask for persistence — never actually
#: persisted, so it never collides with a real notebook file on disk regardless of this string.
EPHEMERAL_ID = "_ephemeral"

#: Cap on a slugged notebook id, matching ctx-distillery's `cli._slug`/`_RUN_ID_MAX` reasoning: the
#: id becomes a filename, and most filesystems cap one path component at 255 bytes.
_SLUG_MAX = 120


def slug(raw: str) -> str:
    """A filesystem-safe FILENAME for a notebook id: keep `[A-Za-z0-9._-]`, fold the rest to `-`,
    strip leading and trailing `.`/`-` so it can never become a traversal segment (`..`, an absolute
    path, a nested directory), and cap at `_SLUG_MAX` characters — re-stripping after the cut so a
    truncation landing on a `-`/`.` never leaves a trailing separator. `--notebook` and the API's
    `{notebook_id}` are user input that becomes a path component; see CLAUDE.md's notebook-id
    invariant.

    **An id with no Latin characters at all falls back to a content hash rather than failing.** The
    whitelist reduces `"模型要睡覺"` — or any Chinese/Japanese/Korean/Arabic/emoji-only name — to
    the empty string, which `notebook_path` then rejects as an invalid id. A user reported exactly
    that: naming a notebook in Chinese returned `400 invalid notebook id … reduces to an empty
    token`, with nothing to suggest the name was the problem rather than the request. The hash is
    deterministic (same name, same file), collision-resistant across different names, and stays
    inside the same whitelist, so none of the traversal or length reasoning above changes.

    This only ever affects the FILENAME. `Notebook.id` stores the id the user actually typed, and
    `list_notebook_summaries` already reports that stored value rather than the filename stem — a
    property it was given for this exact reason (`slug` being lossy), which is why non-Latin names
    now round-trip through the UI with no further change.

    A genuinely empty or whitespace-only id still returns `""`, and still fails loudly: "you gave me
    nothing" is a real error, unlike "you gave me a name in your own language".
    """
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", raw or "").strip("-.")
    token = token[:_SLUG_MAX].rstrip("-.")
    if token:
        return token
    if not (raw or "").strip():
        return ""
    # NFC first: the same visible name typed in a browser (NFC) and pasted from a macOS filename
    # (NFD) are different byte strings, so an un-normalized hash would silently give one user two
    # notebooks with identical-looking names and no way to tell them apart.
    #
    # `surrogatepass`, not plain `encode()`: this function MUST be total. An unpaired surrogate
    # (well-formed JSON per RFC 8259, accepted by `json.loads`, and produced by argv's
    # `surrogateescape` decoding) otherwise raises `UnicodeEncodeError` here — and `api._derive_run_id`
    # calls `slug()` DIRECTLY, outside every `notebook_path` error wrapper, so that surfaced as an
    # unauthenticated 500 on `ask`/`guide`/`audio` via the `run_id` body field. Found and reproduced
    # by an independent review of this very fallback; `slug` never raised before it existed.
    normalized = unicodedata.normalize("NFC", raw)
    return "nb-" + hashlib.sha256(normalized.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def notebook_path(notebook_id: str, *, base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR) -> Path:
    return Path(base_dir) / f"{slug_or_raise(notebook_id)}.json"


#: Every audio format a provider may write. A reader has to find whichever one is actually there,
#: because the provider that produced it may not be the one currently configured — `edge-tts` writes
#: `.mp3` and the local provider writes `.wav`, and switching `RN_TTS_PROVIDER` must not make an
#: already-generated episode unreachable.
AUDIO_SUFFIXES = (".mp3", ".wav")


def find_audio(notebook_id: str, *, base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR) -> Path | None:
    """The notebook's generated audio, whatever format wrote it, or `None`."""
    for suffix in AUDIO_SUFFIXES:
        candidate = audio_path(notebook_id, base_dir=base_dir, suffix=suffix)
        if candidate.exists():
            return candidate
    return None


def clear_audio(notebook_id: str, *, base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR) -> None:
    """Remove every format's file, so regenerating with a DIFFERENT provider can't leave the old
    one behind for `find_audio` to serve instead of the new one."""
    for suffix in AUDIO_SUFFIXES:
        audio_path(notebook_id, base_dir=base_dir, suffix=suffix).unlink(missing_ok=True)


def audio_path(
    notebook_id: str, *, base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR, suffix: str = ".mp3"
) -> Path:
    """Where a notebook's generated Audio Overview lives: `<base_dir>/audio/<slug>.mp3`.

    A subdirectory, so `list_notebook_summaries`' `*.json` glob never sees it, and ONE file per
    notebook — regenerating replaces it rather than accumulating, so the disk cost is bounded by how
    many notebooks exist. Derives from the same validated `slug` every other path here does, so an
    id that reduces to nothing raises before any file is touched."""
    return Path(base_dir) / "audio" / f"{slug_or_raise(notebook_id)}{suffix}"


def slug_or_raise(notebook_id: str) -> str:
    safe = slug(notebook_id)
    if not safe:
        raise ValueError(f"notebook id {notebook_id!r} reduces to an empty token")
    return safe


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
    fully-old or fully-new file, never a partial one — which is also why READS need no lock.

    **Application code must not call this directly — use `mutate_notebook`.** It writes the WHOLE
    notebook, so writing an object read any earlier than "just now, under the lock" silently
    destroys whatever else was written in between. `mutate_notebook` is the only caller inside this
    package for exactly that reason; tests building fixtures on disk are the legitimate exception."""
    atomic_write_text(notebook_path(notebook.id, base_dir=base_dir), notebook.model_dump_json(indent=2))


#: Per-lock-path `threading.Lock`s, used ONLY on a platform without `fcntl` (see `notebook_lock`).
#: Never consulted on POSIX, where `flock` already serializes threads as well as processes.
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(key: str) -> threading.Lock:
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def notebook_lock(notebook_id: str, *, base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR) -> Iterator[None]:
    """Exclusive advisory lock on one notebook, held across a read-modify-write cycle.

    `fcntl.flock` on a sidecar `<base_dir>/.<slug>.json.lock`. Two properties this design leans on,
    both verified empirically rather than assumed:

    - **One mechanism covers threads AND processes.** `flock` locks attach to the *open file
      description*, so a separate `open()` per acquirer serializes two threads of one process just
      as it does two processes. Do NOT swap this for `fcntl.lockf` (POSIX record locks): those are
      per-PROCESS, so two threads of one `uvicorn` server would pass straight through each other.
    - **It releases the GIL while blocked**, so a waiting thread doesn't stall the interpreter.

    A SIDECAR file rather than the notebook itself: `load_or_create` legitimately runs for a
    notebook that doesn't exist yet, and pre-creating the real path would break `load_notebook`'s
    `path.exists()` contract. The lock file is never unlinked — deleting it would race with an
    acquirer that already opened it — so one zero-byte file per notebook accumulates;
    `list_notebook_summaries` globs `*.json`, so these stay invisible to it.

    **NOT reentrant.** A second acquisition from the same thread blocks forever (a different open
    file description, so `flock` sees a genuine second acquirer). Nothing passed to
    `mutate_notebook` may itself call `mutate_notebook`/`notebook_lock`.

    **POSIX only, stated rather than papered over.** Without `fcntl` (Windows), this degrades to a
    process-local `threading.Lock`: still correct for the single-process `uvicorn` deployment
    invariant 23 already describes as the only supported one, with no cross-process guarantee. A
    portable create-exclusive lockfile protocol would need stale-lock recovery after a crash — more
    failure modes than this buys.

    Raises `ValueError` for an id that slugs to nothing, from `notebook_path` — same as every other
    function here, so an invalid id fails identically whether or not it reaches a lock.
    """
    path = notebook_path(notebook_id, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")

    if fcntl is None:  # pragma: no cover — POSIX-only fallback
        with _thread_lock_for(str(lock_path)):
            yield
        return

    with open(lock_path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def mutate_notebook(
    notebook_id: str,
    apply: Callable[[Notebook], None],
    *,
    base_dir: str | Path = DEFAULT_NOTEBOOKS_DIR,
    create: bool = False,
) -> Notebook:
    """Apply a mutation to a notebook under `notebook_lock`, and return the notebook as saved.

    **`apply` receives a notebook re-loaded from disk INSIDE the lock — never a snapshot the caller
    read earlier.** That is the whole point: it makes it impossible to express "write back the
    object I built minutes ago," which is the defect this exists to close (see the module
    docstring). A caller does its expensive work — ingestion, a model run — unlocked, against a
    snapshot, then passes a closure applying only the resulting DELTA. Critical sections stay
    bounded by a JSON load plus a JSON write.

    `apply` must therefore not assume ids/indices it computed against its own snapshot are still
    right (`append_sources` exists for exactly that re-derivation), and must not call
    `mutate_notebook`/`save_notebook` itself (`notebook_lock` is not reentrant).

    Nothing is written if `apply` raises — the exception propagates with the on-disk file untouched.
    `create=False` raises `FileNotFoundError` for a notebook that doesn't exist; `create=True`
    starts a fresh one, matching `load_or_create`. Raises `ValueError` (invalid id) /
    `pydantic.ValidationError` (corrupted file) exactly where the unlocked readers do.

    The `create=False` miss is checked BEFORE taking the lock as well as inside it. Not an
    optimisation: `notebook_lock` creates its sidecar file just by being entered, so without this
    every 404-ing request (`DELETE /notebooks/<anything>/notes/n1` — unauthenticated, invariant 25)
    left a permanent zero-byte file behind, invisible to `list_notebook_summaries`' `*.json` glob.
    Found by an independent security review, which reproduced 503 files from 503 requests against
    notebooks that never existed. The check inside the lock is what makes it correct; this one only
    keeps the miss from writing anything.
    """
    if not create and not notebook_path(notebook_id, base_dir=base_dir).exists():
        raise FileNotFoundError(f"no notebook {notebook_id!r}")

    with notebook_lock(notebook_id, base_dir=base_dir):
        notebook = load_notebook(notebook_id, base_dir=base_dir)
        if notebook is None:
            if not create:
                raise FileNotFoundError(f"no notebook {notebook_id!r}")
            notebook = Notebook(id=notebook_id)
        apply(notebook)
        save_notebook(notebook, base_dir=base_dir)
        return notebook


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


def ingest_sources_for(notebook: Notebook, new_values: list[str]) -> list[Source]:
    """Ingest the `new_values` not already present in `notebook` (by origin) and return them —
    WITHOUT touching `notebook`. The expensive half: a network fetch, a PDF parse plus OCR, a
    YouTube caption download. Runs UNLOCKED, against a snapshot; `append_sources` then merges the
    result under `mutate_notebook`'s lock.

    Raises `parsers.web.FetchError`/`ValueError`/`OSError` on an ingestion failure, same as
    `ingest.ingest_new` (which this wraps).

    This and `append_sources` replace the former single `extend_with_sources`, which ingested and
    appended in one breath and so forced its caller to hold a snapshot across ingestion — the exact
    shape of the lost-update defect (module docstring). Deleted rather than kept alongside these
    two, so a later caller can't silently reintroduce it.

    `notebook` is used only to pre-filter already-present origins and to pick starting ids, both of
    which `append_sources` re-derives authoritatively. A stale snapshot therefore costs at worst a
    wasted re-fetch of something a concurrent request added in the meantime, never a wrong result.
    """
    return ingest_new(
        new_values, start_index=len(notebook.sources) + 1, skip_origins=existing_origins(notebook)
    )


def append_sources(notebook: Notebook, sources: list[Source]) -> list[Source]:
    """Append already-ingested, already-injection-scanned `sources` to `notebook.sources` IN PLACE,
    deduped by origin and RENUMBERED against THIS notebook. Returns just what was actually appended
    (so a caller can report which, if any, are flagged).

    The cheap half, meant to run inside `mutate_notebook`'s lock. Both re-derivations matter: a
    source ingested against a snapshot was numbered from *its* `len(sources) + 1` and deduped
    against *its* origins, and a concurrent write may have invalidated both.

    Renumbering an as-yet-unpersisted source does NOT touch invariant 12 (which forbids reassigning
    an id a SAVED notebook already uses): `Source.marker()` derives the citation marker from `.id`
    at `Corpus.blob()` time, so no id is ever baked into stored block text. Callers that hand the
    result to a model must use the RETURNED objects, not the ones they passed in.
    """
    seen = existing_origins(notebook)
    appended: list[Source] = []
    for source in sources:
        if source.origin in seen:
            continue
        seen.add(source.origin)
        renumbered = source.model_copy(update={"id": f"s{len(notebook.sources) + 1}"})
        notebook.sources.append(renumbered)
        appended.append(renumbered)
    return appended


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


def _next_note_id(notebook: Notebook) -> str:
    """`n{max existing numeric suffix among CURRENTLY LIVE notes + 1}` — NOT `n{len(notes) + 1}`.
    Found by an independent review: `len(notes) + 1` reuses an id that's still held by ANOTHER
    live note the moment a non-last note is deleted (e.g. notes `[n1, n2]`, delete `n1` — the list
    is now length 1, so the next add computes `n2` again, colliding with the surviving note that's
    STILL called `n2`). Two live notes sharing one id is a real, silent-data-loss bug, not a
    cosmetic one: `delete_note`/`promote_note` filter/match BY id, so a collision makes either one
    act on both notes at once — reproduced live, promoting one of a colliding pair silently
    discarded the other with no source ever created for it and no error raised. Deriving the next
    id from the MAX id actually in use (not the count) guarantees no new id can ever collide with
    a note that's still alive, regardless of which note got deleted. An id CAN still be reused
    once NO live note holds it anymore (e.g. every note is deleted, then a new one is added) — that
    case is genuinely safe, unlike the one this function fixes."""
    if not notebook.notes:
        return "n1"
    return f"n{max(int(n.id[1:]) for n in notebook.notes) + 1}"


def add_note(notebook: Notebook, text: str) -> Note:
    """Create and append a new `Note` to `notebook.notes` IN PLACE (see `_next_note_id` for the id
    scheme). Raises `ValueError` on blank text, same discipline `parsers.text.parse_text` already
    applies to a blank text SOURCE. Deliberately does NOT call `save_notebook` itself — same
    convention every other mutator in this module follows (`append_sources` doesn't save either);
    persistence is `mutate_notebook`'s job, and a mutator that saved would deadlock inside it."""
    if not text.strip():
        raise ValueError("note text is empty")
    note = Note(id=_next_note_id(notebook), text=text)
    notebook.notes.append(note)
    return note


def delete_note(notebook: Notebook, note_id: str) -> None:
    """Removes the note with id `note_id` from `notebook.notes` IN PLACE. Raises `ValueError` if no
    such note exists, rather than a silent no-op on a typo'd id — the same "raise on a request that
    named something that doesn't exist" discipline `corpus.Corpus.filtered` already applies to an
    unknown source id. Removes exactly the FIRST matching note by index, not every id-equal match —
    defense in depth alongside `_next_note_id`'s own collision fix, in case a duplicate id is ever
    produced by a future code path this function doesn't control."""
    for index, note in enumerate(notebook.notes):
        if note.id == note_id:
            del notebook.notes[index]
            return
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
    Raises `ValueError` if `note_id` doesn't exist, same as `delete_note`. Pops exactly the FIRST
    matching note by index (same defense-in-depth reasoning as `delete_note`), not every id-equal
    match."""
    index = next((i for i, n in enumerate(notebook.notes) if n.id == note_id), None)
    if index is None:
        raise ValueError(f"no note {note_id!r} in this notebook")
    note = notebook.notes.pop(index)
    candidate = ingest_pasted_text(note.text, source_id=f"s{len(notebook.sources) + 1}")
    if candidate.origin in existing_origins(notebook):
        return None
    source = with_injection_flags(candidate)
    notebook.sources.append(source)
    return source
