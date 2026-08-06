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

from .config import clean_language

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
- Write the title in the language named by `language`. If that is empty, use the sources' own
  language: if they are in Chinese, write a Chinese title.
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


_LANGUAGE_INSTRUCTIONS = """\
Decide which language this person wants their research notebook WRITTEN IN.

You are given three signals, and they often disagree:
- `accept_language`: the reader's browser preference. Useful, but it answers "what language should
  this browser's interface be in", NOT "what language does this person want to read research in" —
  an English-locale machine reading Japanese papers is exactly where the two diverge. Do not treat
  it as decisive on its own.
- `sources_excerpt`: what the documents are written in. The WEAKEST signal — reading a paper in one
  language says nothing about wanting notes in it.
- `questions`: anything this person has actually typed. The STRONGEST signal when present, because
  it is the one place they chose a language for themselves rather than inheriting one.

Answer with the language's name in English, two or three words at most: "Traditional Chinese",
"Japanese", "Brazilian Portuguese", "English". No explanation, no punctuation, no alternatives.
"""


class SuggestLanguage:
    """Which language to write this notebook's artifacts in — `worker.py`-compatible, like
    `SuggestTitle`, and a plain `dspy.Predict` for the same reason (one word does not justify a
    sandbox boot and a planner loop).

    **Why a model call rather than ranking `Accept-Language` first.** The sibling project a sibling project
    shipped exactly that class of bug in its ASR: it seeded the recogniser from `Locale.current`,
    which answers "what language should this app's UI be in", while ASR was asking "what language is
    this person speaking" — and transcribed Chinese speech as syllable-by-syllable English gibberish.
    `Accept-Language` is the same shape of wrong API for "what language does this person want their
    research written in". Weighing the signals together is a judgement, not a lookup.

    Returns `None` on any failure — falling back to today's behaviour. A language guess must never
    cost the user the artifact they asked for.
    """

    async def arun(
        self, *, accept_language: str = "", sources_excerpt: str = "", questions: str = ""
    ) -> str | None:
        try:
            import dspy

            predictor = dspy.Predict(
                dspy.Signature(
                    "accept_language: str, sources_excerpt: str, questions: str -> language: str",
                    _LANGUAGE_INSTRUCTIONS,
                )
            )
            result = await predictor.acall(
                accept_language=accept_language or "(not provided)",
                sources_excerpt=(sources_excerpt or "")[:_EXCERPT_CHARS],
                questions=questions or "(none asked yet)",
            )
            return clean_language(getattr(result, "language", ""))
        except Exception:  # noqa: BLE001 — a language guess is never worth failing the request
            return None


class SuggestTitle:
    """`worker.py`-compatible: one `arun(**kwargs)` coroutine, nothing else.

    `arun(sources=<corpus excerpt>, origins=<list[str]>, language=<resolved language>) -> str`.
    """

    async def arun(
        self, *, sources: str = "", origins: list[str] | None = None, language: str = ""
    ) -> str:
        origins = origins or []
        excerpt = (sources or "")[:_EXCERPT_CHARS]
        if not excerpt.strip():
            return fallback_title(origins)
        try:
            import dspy

            predictor = dspy.Predict(
                dspy.Signature("sources: str, language: str -> title: str", _INSTRUCTIONS)
            )
            result = await predictor.acall(sources=excerpt, language=language or "")
            return clean_title(getattr(result, "title", ""), origins)
        except Exception:  # noqa: BLE001 — a title is never worth failing the request that wanted it
            return fallback_title(origins)
