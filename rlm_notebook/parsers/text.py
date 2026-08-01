"""Plain pasted-text ingestion — the trivial parser, no I/O of its own."""

from __future__ import annotations

from ..schema import Source, SourceBlock


def parse_text(text: str, source_id: str, *, origin: str = "pasted text") -> Source:
    """Wrap already-in-hand text as a one-block `Source`. Raises on empty input rather than
    silently creating a citable-but-empty source."""
    if not text.strip():
        raise ValueError("text source is empty")
    return Source(
        id=source_id,
        kind="text",
        origin=origin,
        blocks=[SourceBlock(locator="whole", text=text)],
    )
