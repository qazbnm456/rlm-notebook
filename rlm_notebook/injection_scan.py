"""A deterministic, additive prompt-injection heuristic scan over ingested source text.

AGENTS.md invariant 6: this module never gates or blocks anything. `scan_source` returns a list of
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
#: (pattern, what a READER should be told). The second half exists because the flag is shown to a
#: person: the message used to be the raw regex — a user asked what
#: `instruction-like phrase matching '\\bsystem\\s*:\\s*'` meant, which is a fair question, because
#: it names an implementation detail and says nothing about what to do. Invariant 6's flags gate
#: nothing, so their entire value is whether a human can act on them.
_INSTRUCTION_PATTERNS = [
    (
        re.compile(r"\bignore (all|any|the) (previous|prior|above) instructions\b", re.IGNORECASE),
        "text telling a model to ignore its instructions",
    ),
    (
        re.compile(r"\byou are now\b.{0,40}\b(assistant|ai|model)\b", re.IGNORECASE),
        "text trying to reassign the model's role",
    ),
    # ANCHORED to the start of a line, and requiring what a real injected turn looks like: a role
    # label opening its own line. The unanchored `\bsystem\s*:\s*` fired on any ordinary sentence
    # containing the word — measured, after a user reported it on their own source: "The operating
    # system: a set of layers." and "The Voyager system: two probes" both matched. Invariant 6 says
    # these patterns trade recall for PRECISION on purpose; that one had neither.
    (
        re.compile(r"^\s*(system|assistant|user)\s*:\s*", re.IGNORECASE | re.MULTILINE),
        "a chat role label (System:/User:/Assistant:) opening a line",
    ),
    (
        re.compile(r"\bdisregard\b.{0,20}\b(instructions|rules|guidelines)\b", re.IGNORECASE),
        "text telling a model to disregard its rules",
    ),
    (
        re.compile(
            r"\b(reveal|output|print)\b.{0,20}\b(system prompt|api key|credentials)\b",
            re.IGNORECASE,
        ),
        "text asking a model to reveal its prompt or credentials",
    ),
]

#: A run of base64-alphabet characters long enough to plausibly carry an encoded payload rather
#: than an incidental short token/id.
_LONG_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


def scan_source(text: str) -> list[str]:
    """Return a list of human-readable flags for `text` (empty = nothing matched). Deterministic —
    same input always yields the same flags, no model call involved."""
    flags: list[str] = []
    for pattern, description in _INSTRUCTION_PATTERNS:
        if pattern.search(text):
            flags.append(description)
    if _LONG_BASE64_RUN.search(text):
        flags.append("a long run of base64-like characters (possibly an encoded payload)")
    return flags
