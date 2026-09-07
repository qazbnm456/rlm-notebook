# Invariant 33 — YouTube ingestion is captions only

**YouTube source ingestion (`parsers/youtube.py`) fetches CAPTIONS ONLY — never the video or
audio stream.** A deliberate, user-confirmed MVP scope decision: no `ffmpeg`, no Whisper, no
transcription API key. A video with neither official nor auto-generated captions is a clean,
loud ingestion-time error (`CaptionError`), never a silent empty/partial source.

**Accepted ToS caveat**: YouTube's Terms prohibit automated access outside its own interfaces;
`yt-dlp` (a core dependency, same "ship a working default" reasoning as invariants 7 and 15)
operates in the same grey area every YouTube-downloading tool does. Fetching only captions is
narrower than downloading media but is not risk-free — the risk is accepted by whoever DEPLOYS
this, and `README.md` states it.

**`CaptionError` is a `ValueError` subclass.** `cli._prepare` and `api.add_sources` both catch
ingestion failures as `except (FetchError, ValueError, OSError)`; a bare `RuntimeError` would
land a captionless video as an unhandled 500 / raw traceback — verified live and pinned by
`test_api.py::test_add_sources_reports_422_not_500_on_a_captionless_youtube_video`. Don't give a future
ingestion-failure exception a base class outside that tuple without updating both call sites.

**`_parse_vtt` flattens EVERY non-blank line into its own `(start, text)` entry — one per LINE,
never one per cue — and leaves ALL deduplication to `_dedupe_consecutive`.** Cue-level
classification was tried twice and under-collapsed on real auto-caption data both times: a
rolling-karaoke cue advancing by exactly ONE new word carries no `<...>` tag, so tag-presence
misclassifies it. Line-level flattening sidesteps classification entirely — a transition cue's
settled line is always identical to a line the preceding cue already emitted, so plain adjacent
dedup collapses it, while a genuine multi-line official dialogue cue's lines are both new and
both survive (`_chunk`, not `_parse_vtt`, rejoins them). **The cue-boundary check is separate and
still correct**: a whitespace-only line is part of a cue's OWN payload (real auto-caption VTT
uses a single-space line for exactly this), so ending a cue tests EXACT emptiness
(`lines[i] != ""`) while extracting text still treats whitespace-only content as blank — two
notions of "blank" at two steps, not one check reused. `tests/test_parsers_youtube.py`'s
fixtures are real captured dumps for this reason.

**A `"ts:<mm:ss>"` locator prefix, widening to `"ts:<h:mm:ss>"` past the one-hour mark** (a
fixed `_CHUNK_SECONDS = 120` window, coarser than one cue), alongside `"whole"` (text/web) and
`"page:<n>"` (pdf). Locator is fully opaque everywhere
it matters — `citations.py` and `CITATION_RULES` never parse it — so a new prefix breaks nothing.

**`_fetch_caption_track` reuses `parsers/web.py`'s hardened `_opener`** rather than a bespoke
unguarded fetch. The caption URL comes from YouTube's own `timedtext` API, not from untrusted
source content, so invariant 2's threat model doesn't apply — but reusing the hardened opener
costs nothing and removes the residual risk instead of reasoning it away. `web.py` is UNCHANGED.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
