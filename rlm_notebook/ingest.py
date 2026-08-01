"""Source ingestion dispatch — shared by `cli.py` and `api.py` so neither depends on the other.

CLAUDE.md invariant 3: this all runs host-side, before any `RLMTask` exists.
"""

from __future__ import annotations

from pathlib import Path

from .injection_scan import scan_source
from .parsers.pdf import parse_pdf
from .parsers.text import parse_text
from .parsers.web import parse_web
from .schema import Source


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def ingest_one(value: str, source_id: str) -> Source:
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
        source = ingest_one(value, source_id=f"s{next_index}")
        flags = sorted({flag for block in source.blocks for flag in scan_source(block.text)})
        if flags:
            source = source.model_copy(update={"flags": flags})
        sources.append(source)
        next_index += 1
    return sources
