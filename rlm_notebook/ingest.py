"""Source ingestion dispatch — shared by `cli.py` and `api.py` so neither depends on the other.

CLAUDE.md invariant 3: this all runs host-side, before any `RLMTask` exists.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from .injection_scan import scan_source
from .parsers.pdf import parse_pdf
from .parsers.text import parse_text
from .parsers.web import parse_web
from .parsers.youtube import is_youtube_url, parse_youtube
from .schema import Source

#: Suffixes `ingest_uploaded_file` will parse — anything else is refused loudly (a 422 naming this
#: set), not guessed at. Word/Slides/Docs native formats would need new parser dependencies and
#: aren't attempted here; this only wires up the two parsers that already exist.
_ALLOWED_UPLOAD_SUFFIXES = {".pdf", ".txt", ".md"}


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def with_injection_flags(source: Source) -> Source:
    """Deterministic prompt-injection heuristic flags (CLAUDE.md invariant 6) folded into
    `source.flags` — factored out of `ingest_new`'s own loop so every way a new source can enter a
    notebook (a batch of paths/URLs, an uploaded file, pasted text) applies the SAME scan, once."""
    flags = sorted({flag for block in source.blocks for flag in scan_source(block.text)})
    return source.model_copy(update={"flags": flags}) if flags else source


def ingest_one(value: str, source_id: str) -> Source:
    if is_youtube_url(value):
        return parse_youtube(value, source_id)
    if is_url(value):
        return parse_web(value, source_id)
    path = Path(value)
    if path.suffix.lower() == ".pdf":
        return parse_pdf(str(path), source_id)
    return parse_text(path.read_text(encoding="utf-8"), source_id, origin=str(path))


def ingest_new(values: list[str], *, start_index: int, skip_origins: set[str]) -> list[Source]:
    """Ingest `values` not already in `skip_origins` (an existing notebook's source origins — see
    `notebook.existing_origins`), numbering ids from `start_index` so they never collide with a
    notebook's existing sources. Re-ingesting an already-present origin, whether across two calls
    or repeated WITHIN `values` itself, is a no-op: `seen` starts as a copy of `skip_origins` and
    grows as this loop runs (found by an independent review: an earlier version only checked the
    caller's static set, so a duplicate value in the SAME call sailed through unfiltered)."""
    sources: list[Source] = []
    seen = set(skip_origins)
    next_index = start_index
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        source = with_injection_flags(ingest_one(value, source_id=f"s{next_index}"))
        sources.append(source)
        next_index += 1
    return sources


def ingest_uploaded_file(data: bytes, filename: str, source_id: str) -> Source:
    """Ingest raw bytes a client UPLOADED over HTTP — never a server-side path, which is what makes
    this safe unlike the local-path ingestion invariant 26 already closed off for `add_sources`
    (that vector was reachable because the server read an operator-controlled STRING as a
    filesystem path; here the server only ever sees opaque bytes the caller already had, plus a
    claimed filename used solely for extension-based kind detection and display).

    Dispatches on `filename`'s suffix against `_ALLOWED_UPLOAD_SUFFIXES` — anything else raises
    `ValueError` naming the allowed set, rather than guessing. `.pdf` writes `data` to a temp file
    (no `.pdf` suffix needed — `pypdfium2` sniffs content, not the path, re-verified against a real
    suffixless PDF after it replaced PyMuPDF, since the original evidence was the old backend's
    during this feature's design) and calls the EXISTING `parse_pdf` unchanged, then overrides the
    result's `.origin` from the temp path to the caller's `filename` (`Source` has no validators, so
    `model_copy` is a safe, non-revalidating shallow copy). The temp file is deleted in a `finally`
    that wraps the parse call itself, not just a success-path cleanup — the exact class of gap an
    earlier audit found and fixed for `/audio`'s synthesis temp file, applied here from the start.
    `.txt`/`.md` decode as UTF-8 (a clear `ValueError` on a decode failure, never a silent mangle)
    and call the EXISTING `parse_text` unchanged."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError(
            f"unsupported file type {suffix!r} — expected one of {sorted(_ALLOWED_UPLOAD_SUFFIXES)}"
        )
    if suffix == ".pdf":
        fd, tmp_name = tempfile.mkstemp()
        tmp_path = Path(tmp_name)
        try:
            with open(fd, "wb") as fh:
                fh.write(data)
            source = parse_pdf(str(tmp_path), source_id)
        finally:
            tmp_path.unlink(missing_ok=True)
        return source.model_copy(update={"origin": filename})
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{filename!r} is not valid UTF-8 text") from exc
    return parse_text(text, source_id, origin=filename)


def ingest_pasted_text(text: str, source_id: str) -> Source:
    """Pasted text has no natural origin (no path/URL). Uses a readable snippet PLUS a content
    hash, `f"pasted:{snippet} #{hash}"` — a bare hash alone was found, during this feature's design,
    to be a real UX regression: the Sources list renders `origin` verbatim as its only label, so
    two different pastes would show as two indistinguishable hash strings. The hash suffix still
    disambiguates two texts sharing the same first 60 characters, and still gives the dedup
    semantics a deliberate content-based identity: pasting the EXACT same text twice naturally
    dedupes via `existing_origins()` (same origin in, same origin out) — the same semantics
    re-adding an identical file path already has. Different text, even by one character, gets a
    different origin and is never treated as a duplicate."""
    snippet = text[:60].strip()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return parse_text(text, source_id, origin=f"pasted:{snippet} #{digest}")
