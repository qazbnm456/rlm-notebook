"""A deterministic, additive prompt-injection heuristic scan over ingested source text.

CLAUDE.md invariant 6: this module never gates or blocks anything. `scan_source` returns a list of
flag strings; the caller (`Source.flags`) attaches them as metadata, and the answer for a flagged
source still returns normally with the flags surfaced alongside it. This is a transparency
mechanism, not a filter — do not wire its output to refuse a run.
"""

from __future__ import annotations

import re

#: Phrases that look like an attempt to redirect an LLM reading this text, not a claim about what
#: the source is actually about. Deliberately broad and English-centric for this slice — a source
#: written to look like it is addressing "the AI" / "the assistant" rather than a human reader is
#: itself the signal, independent of whether the embedded instruction is followed.
_INSTRUCTION_PATTERNS = [
    re.compile(r"\bignore (all|any|the) (previous|prior|above) instructions\b", re.IGNORECASE),
    re.compile(r"\byou are now\b.{0,40}\b(assistant|ai|model)\b", re.IGNORECASE),
    re.compile(r"\bsystem\s*:\s*", re.IGNORECASE),
    re.compile(r"\bdisregard\b.{0,20}\b(instructions|rules|guidelines)\b", re.IGNORECASE),
    re.compile(r"\b(reveal|output|print)\b.{0,20}\b(system prompt|api key|credentials)\b", re.IGNORECASE),
]

#: A run of base64-alphabet characters long enough to plausibly carry an encoded payload rather
#: than an incidental short token/id.
_LONG_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


def scan_source(text: str) -> list[str]:
    """Return a list of human-readable flags for `text` (empty = nothing matched). Deterministic —
    same input always yields the same flags, no model call involved."""
    flags: list[str] = []
    for pattern in _INSTRUCTION_PATTERNS:
        if pattern.search(text):
            flags.append(f"instruction-like phrase matching {pattern.pattern!r}")
    if _LONG_BASE64_RUN.search(text):
        flags.append("long base64-alphabet run (possible encoded payload)")
    return flags
