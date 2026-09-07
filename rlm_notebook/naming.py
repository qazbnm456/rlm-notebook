"""Suggest a human title for a notebook from the sources already in it.

A user should not have to invent an id before they can add their first source. They did have to —
the web UI refused with "Open or name a notebook first" — which made the very first interaction
with this product a naming puzzle about a thing that did not exist yet. The id is now minted
automatically and this module supplies the LABEL a person actually reads.

**Deliberately NOT an `RLMTask`.** Every other model-facing task here runs the full rlm-harness REPL
loop in the pyodide sandbox, which is right when the model must explore a multi-MB corpus and
produce verifiable citations, and absurd for five words of title: it would cost a sandbox
boot plus several planner turns. This is one plain `dspy.Predict` over a short excerpt.

It still runs inside the API's isolated subprocess, so AGENTS.md invariant 21 is untouched —
`worker.py` only ever calls `.arun(**kwargs)` on whatever class it is handed, so satisfying that
one method is the entire contract. (Invariant 21's guarantee is about EXECUTION, not imports —
`api.py` does import both `dspy` and `rlm_harness` transitively, and that invariant forbids
restating otherwise.) Nothing here is reachable from the model's own REPL either (invariants 1/3/14's
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
- Name what the COLLECTION is about, not what one source is called. `sources` is a sample of EVERY
  source in the notebook, separated by `[[SRC:...]]` markers — read past the first one. Copying or
  translating source one's own title is the failure mode here: a notebook holding a paper, a lab
  announcement, a product page and a geopolitics report is not "Trinity: An Evolved LLM
  Coordinator", it is what those four have in common.
- If the sources genuinely share no theme, say what the biggest one is about rather than inventing
  a connection between them.
- Keep proper nouns as the sources write them. A project, product, person or standard called
  "Trinity" stays "Trinity" in a Chinese title — translating the WORD gives a reader a term they
  cannot search for, and a name that is not a common word in the target language reads as a
  mistranslation. Everything around the name still follows `language`.
- Ignore the `[[SRC:...]]` markers themselves; they are separators, never part of the title.
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


def normalize_title(raw: str) -> str:
    """Collapse whitespace, strip surrounding quotes and a trailing period, cap the length. Returns
    `""` when nothing usable is left.

    Split out of `clean_title` because the two callers need OPPOSITE things from an unusable value:
    a GENERATED title falls back to something derived from the origins (a notebook must end up with
    a label), while a user RENAMING it must be refused — silently substituting a derived title for
    what someone typed would be the UI lying about what it did.
    """
    # Control characters are STRIPPED, not just collapsed: `str.split()` drops ASCII whitespace but
    # keeps `\x1b`, `\x00` and the bidi overrides, and this is the only guard on a value an
    # UNAUTHENTICATED `PUT /notebooks/{id}/title` writes (invariants 25 and 53). It is the same
    # thing invariant 41 already requires of `clean_language`, for a value with a smaller blast
    # radius. Not exploitable through today's sinks — every one renders with `textContent` — which
    # is exactly why it should not be left to depend on that staying true.
    cleaned = "".join(ch for ch in (raw or "") if ch.isprintable() or ch.isspace())
    title = " ".join(cleaned.split()).strip().strip("\"'“”「」").rstrip(".")
    if not title or len(title) > _MAX_TITLE_CHARS * 2:
        return ""
    return title[:_MAX_TITLE_CHARS]


def clean_title(raw: str, origins: list[str]) -> str:
    """Normalise whatever the model returned into something a switcher row can show. Falls back
    rather than displaying an empty or absurd string — the model is unsupervised here (no schema
    validation, unlike every `RLMTask` output in this project), so this is the only guard."""
    return normalize_title(raw) or fallback_title(origins)


_LANGUAGE_INSTRUCTIONS = """\
Decide which language this person wants their research notebook WRITTEN IN.

You are given four signals, and they often disagree:
- `interface_language`: the language this person explicitly PICKED for the app's interface. A
  strong signal, because they chose it — someone who set the interface to Traditional Chinese is
  telling you which language they read comfortably. Not decisive on its own either: a reader may
  deliberately want an English interface over Japanese papers, or the reverse.
- `accept_language`: the reader's browser preference. Weaker than the one above, because it was
  INHERITED from the operating system rather than chosen here. It answers "what language should
  this browser's interface be in", NOT "what language does this person want to read research in" —
  an English-locale machine reading Japanese papers is exactly where the two diverge.
- `sources_excerpt`: what the documents are written in. The WEAKEST signal — reading a paper in one
  language says nothing about wanting notes in it.
- `questions`: anything this person has actually typed. The STRONGEST signal when present, because
  it is the one place they chose a language for THIS notebook rather than for the app in general.

When `interface_language` and `questions` agree, that is as clear as this gets. When only
`interface_language` is present, prefer it over the documents' own language: a reader who set the
interface to their own language is unlikely to want their notes in a foreign one.

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
        self,
        *,
        accept_language: str = "",
        sources_excerpt: str = "",
        questions: str = "",
        interface_language: str = "",
    ) -> str | None:
        try:
            import dspy

            predictor = dspy.Predict(
                dspy.Signature(
                    "accept_language: str, sources_excerpt: str, questions: str, "
                    "interface_language: str -> language: str",
                    _LANGUAGE_INSTRUCTIONS,
                )
            )
            result = await predictor.acall(
                accept_language=accept_language or "(not provided)",
                sources_excerpt=(sources_excerpt or "")[:_EXCERPT_CHARS],
                questions=questions or "(none asked yet)",
                interface_language=interface_language or "(not provided)",
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
