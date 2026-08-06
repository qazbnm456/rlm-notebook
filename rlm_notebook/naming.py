"""Suggest a human title for a notebook from the sources already in it.

A user should not have to invent an id before they can add their first source. They did have to —
the web UI refused with "Open or name a notebook first" — which made the very first interaction
with this product a naming puzzle about a thing that did not exist yet. The id is now minted
automatically and this module supplies the LABEL a person actually reads.

**Deliberately NOT an `RLMTask`.** Every other model-facing task here runs the full rlm-harness REPL
loop in the pyodide sandbox, which is right when the model must explore a multi-MB corpus and
produce verifiable citations, and absurd for five words of title: it would cost a sandbox
boot plus several planner turns. This is one plain `dspy.Predict` over a short excerpt.

It still runs inside the API's isolated subprocess, so CLAUDE.md invariant 21 is untouched —
`worker.py` only ever calls `.arun(**kwargs)` on whatever class it is handed, so satisfying that
one method is the entire contract, and `api.py` continues to import neither `dspy` nor
`rlm_harness`. Nothing here is reachable from the model's own REPL either (invariants 1/3/14's
reasoning): titling happens host-side, after ingestion, on text the model never gets to steer.

A failure NEVER propagates. A title is a convenience; losing one must not cost the user the source
they just added, so `arun` falls back to a deterministic title derived from the origins.
"""

from __future__ import annotations

import re

#: How much of the corpus the model is shown. A title needs the topic, not the document — and this
#: is called right after the FIRST source lands, when the whole notebook is usually one file.
_EXCERPT_CHARS = 4000

#: Titles are a UI label, not an id. Long enough to be specific, short enough for a switcher row.
_MAX_TITLE_CHARS = 60

_INSTRUCTIONS = """\
Write a short, specific title for a research notebook containing these sources.

Rules:
- 2 to 6 words. No trailing period.
- Name the SUBJECT, not the format: "Voyager Interstellar Mission", never "Notes on a document"
  or "Summary of sources".
- Use the sources' own language: if they are in Chinese, write a Chinese title.
- If the sources are too fragmentary to tell what they are about, answer with their most concrete
  shared noun rather than inventing a theme.
"""


def fallback_title(origins: list[str]) -> str:
    """A title with no model involved — used when the model call fails, and by any caller that
    wants one without paying for a request. Deterministic, so the same notebook always gets the
    same fallback rather than a different one on each retry."""
    if not origins:
        return "Untitled notebook"
    first = origins[0]
    # A pasted-text origin already carries a readable snippet (`ingest.ingest_pasted_text`); a path
    # or URL is more useful as its last meaningful segment than in full.
    if first.startswith("pasted:"):
        first = first[len("pasted:") :].split(" #")[0]
    else:
        first = re.sub(r"^https?://(www\.)?", "", first).rstrip("/").split("/")[-1] or first
    title = first.strip() or "Untitled notebook"
    extra = len(origins) - 1
    if extra:
        title = f"{title} (+{extra})"
    return title[:_MAX_TITLE_CHARS]


def clean_title(raw: str, origins: list[str]) -> str:
    """Normalise whatever the model returned into something a switcher row can show. Falls back
    rather than displaying an empty or absurd string — the model is unsupervised here (no schema
    validation, unlike every `RLMTask` output in this project), so this is the only guard."""
    title = " ".join((raw or "").split()).strip().strip("\"'“”「」").rstrip(".")
    if not title or len(title) > _MAX_TITLE_CHARS * 2:
        return fallback_title(origins)
    return title[:_MAX_TITLE_CHARS]


class SuggestTitle:
    """`worker.py`-compatible: one `arun(**kwargs)` coroutine, nothing else.

    `arun(sources=<corpus excerpt>, origins=<list[str]>) -> str`.
    """

    async def arun(self, *, sources: str = "", origins: list[str] | None = None) -> str:
        origins = origins or []
        excerpt = (sources or "")[:_EXCERPT_CHARS]
        if not excerpt.strip():
            return fallback_title(origins)
        try:
            import dspy

            predictor = dspy.Predict(
                dspy.Signature("sources: str -> title: str", _INSTRUCTIONS)
            )
            result = await predictor.acall(sources=excerpt)
            return clean_title(getattr(result, "title", ""), origins)
        except Exception:  # noqa: BLE001 — a title is never worth failing the request that wanted it
            return fallback_title(origins)
