"""YouTube caption ingestion: fetch official/auto-generated captions via `yt-dlp` (no video/audio
download — AGENTS.md's captions-only MVP decision), then parse WebVTT into timestamped blocks.

AGENTS.md invariant 1/3: this all runs host-side, during ingestion, never inside the RLM sandbox
or reachable as a live tool — the same trust boundary `parsers/web.py` already establishes, just
for a different source kind. See
`docs/invariants/33-youtube-ingestion-is-captions-only.md` for
the full design record, including the real ToS/legal caveat this feature accepts rather than
hides, and the live-verified `yt-dlp` behavior this module's algorithms are built against.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

import yt_dlp
from rlm_harness.tools.fetch import is_safe_url, resolved_host_is_safe

from ..schema import Source, SourceBlock
from .web import _opener, allow_nets

#: Hostnames that route to `parse_youtube` instead of the generic `parse_web` fallback in
#: `ingest.ingest_one`. `music.youtube.com` deliberately excluded — a different product, not
#: attempted here.
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}

#: Citation-block granularity: coarser than a single caption cue, finer than "whole" — a
#: deliberate MVP grain (AGENTS.md's Scope note already applies this same "start coarse, refine
#: later if it turns out to matter" reasoning to text/web's own single `"whole"` locator).
_CHUNK_SECONDS = 120.0

_TAG_RE = re.compile(r"<[^>]+>")
_TS_LINE_RE = re.compile(r"^(\d+):(\d{2})(?::(\d{2}))?\.(\d{3})\s*-->")


class CaptionError(ValueError):
    """No usable captions were found for a YouTube video, or fetching/parsing them failed.

    A `ValueError` subclass, NOT a bare `RuntimeError` — `cli._prepare` and `api.add_sources` both
    catch ingestion failures as `except (FetchError, ValueError, OSError)`; only a `ValueError`
    subclass lands a captionless video as the clean ingestion-time error this module's own design
    record promises, rather than an unhandled 500 (API) / raw traceback (CLI). Found by this
    feature's own pre-implementation audit before any code was written, not live afterward.
    """


def is_youtube_url(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").lower()
    except ValueError:
        return False
    return host in _YOUTUBE_HOSTS


def _parse_vtt(raw: str) -> list[tuple[float, str]]:
    """Parse WebVTT into `(start_seconds, text)` entries — ONE PER NON-BLANK LINE, not one per
    cue. Every cue's payload lines are tag-stripped and flattened individually into the output,
    each sharing that cue's start timestamp; `_dedupe_consecutive` (below) then collapses adjacent
    identical entries. This is deliberately simpler than an earlier design that tried to classify
    each cue as either a "building" (auto-caption) or "ordinary" (official dialogue) cue and
    extract different lines accordingly — found, by an independent completion check running this
    against a REAL fetched caption track, to still under-collapse: a "building" cue that advances
    by exactly ONE new word often carries NO `<c>` tag at all (a tag wraps a word only when there
    are multiple new words to time within one line), so the tag-presence heuristic misclassified
    it as "ordinary" and left a duplicate word pair in the output (e.g. real auto-caption data
    produced `"...I'm thinking thinking of..."`). Line-level flattening + adjacent-dedup sidesteps
    that classification question entirely: a rolling-karaoke transition cue's settled line is
    ALWAYS identical to some line already emitted by the immediately preceding cue, so it always
    collapses via dedup regardless of whether that preceding cue had a tag; a genuine multi-line
    OFFICIAL dialogue cue's two lines are both genuinely NEW text, so neither line collides with
    anything and both survive. Verified against a real, live-fetched auto-caption track after
    this fix (no more adjacent duplicate lines) — see
    `docs/invariants/33-youtube-ingestion-is-captions-only.md` for the full account.

    A cue's payload ends at a TRULY empty line (VTT's own grammar) — NOT a whitespace-only-but-
    non-empty one; real auto-caption VTT uses a single-space line as part of a cue's OWN payload
    (found live against real data), so checking `.strip() != ""` here would misread that space
    line as the cue-ending separator and silently drop it. A line that strips to empty (blank OR
    tag-stripped-to-nothing) contributes no entry at all, never an empty string.
    """
    entries: list[tuple[float, str]] = []
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        match = _TS_LINE_RE.match(lines[i])
        if not match:
            i += 1
            continue
        h_or_m, m2, s, ms = match.groups()
        if s is None:
            start = int(h_or_m) * 60 + int(m2) + int(ms) / 1000
        else:
            start = int(h_or_m) * 3600 + int(m2) * 60 + int(s) + int(ms) / 1000
        i += 1
        while i < len(lines) and lines[i] != "":
            content = _TAG_RE.sub("", lines[i]).strip()
            if content:
                entries.append((start, content))
            i += 1
    return entries


def _dedupe_consecutive(cues: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Drops a cue whose text is IDENTICAL to the immediately preceding KEPT cue's text — this is
    what collapses auto-caption's "settled line re-appears as the next cue's first line"
    duplication. A no-op on already-clean official-subtitle input (consecutive cues are rarely
    byte-identical there), so one code path correctly handles both caption shapes."""
    result: list[tuple[float, str]] = []
    last_text: str | None = None
    for start, text in cues:
        if text == last_text:
            continue
        result.append((start, text))
        last_text = text
    return result


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def _chunk(cues: list[tuple[float, str]], *, window: float = _CHUNK_SECONDS) -> list[SourceBlock]:
    """Groups cues into fixed-size time windows, each becoming one `SourceBlock` with locator
    `f"ts:{mm:ss}"` (or `h:mm:ss` past the one-hour mark) — a NEW locator prefix alongside the
    existing `"whole"` (text/web) and `"page:<n>"` (pdf) conventions."""
    if not cues:
        return []
    blocks: list[SourceBlock] = []
    window_start = cues[0][0]
    buffer: list[str] = []
    for start, text in cues:
        if start - window_start >= window and buffer:
            blocks.append(SourceBlock(locator=f"ts:{_format_timestamp(window_start)}", text=" ".join(buffer)))
            window_start = start
            buffer = []
        buffer.append(text)
    if buffer:
        blocks.append(SourceBlock(locator=f"ts:{_format_timestamp(window_start)}", text=" ".join(buffer)))
    return blocks


def _select_language(available: dict, preferred: str | None) -> str | None:
    """Prefers `preferred` (the video's own detected language, `info["language"]`) if it's a key
    in `available`; else the alphabetically-first key, deterministic rather than dependent on
    dict-iteration order. `None` if `available` is empty."""
    if not available:
        return None
    if preferred and preferred in available:
        return preferred
    return min(available)


def _check_caption_url_safe(url: str) -> None:
    """The SAME SSRF-guard functions `parsers/web.py` already imports, applied here too for
    defense-in-depth consistency with every other host-side fetch in this codebase — even though
    this URL is RESOLVED BY `yt-dlp` from YouTube's own official `timedtext` API response, never
    extracted from untrusted source content, so it doesn't carry `parse_web`'s attacker-controlled-
    redirect threat model. The actual fetch below still routes through `web.py`'s already-hardened,
    already-audited `_opener` (built with `_SafeRedirectHandler`) rather than a bespoke unguarded
    one — recommended by this feature's own pre-implementation audit: reusing it costs nothing and
    removes the (already-judged-small) residual redirect risk entirely rather than reasoning it
    away. `web.py` itself is UNCHANGED by this reuse."""
    if not is_safe_url(url):
        raise CaptionError(f"refused: caption URL {url!r} is not a permitted external http(s) URL")
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not resolved_host_is_safe(parsed.hostname or "", port, allow_nets=allow_nets()):
        raise CaptionError(
            f"refused: caption URL {url!r} resolves to a disallowed address "
            "(if you are behind a fake-IP proxy or split-DNS VPN, set RN_FETCH_ALLOW_CIDRS)"
        )


def _fetch_caption_track(caption_url: str, *, timeout: float = 15.0) -> str:
    _check_caption_url_safe(caption_url)
    req = urllib.request.Request(caption_url, headers={"User-Agent": "rlm-notebook/0.1"})
    try:
        with _opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
    except CaptionError:
        raise
    except (urllib.error.URLError, TimeoutError) as exc:
        raise CaptionError(f"fetch error for caption URL {caption_url!r}: {exc}") from exc
    return raw.decode("utf-8", errors="replace")


def _default_downloader(url: str) -> str:
    """Real `yt-dlp`-backed caption fetch: resolve available caption tracks for `url` (NO video/
    audio download — `skip_download: True`), prefer official subtitles over auto-generated,
    prefer the video's own detected language, and return the raw WebVTT text of whichever track
    was selected. Raises `CaptionError` if the video has no captions in either category."""
    ydl_opts = {"skip_download": True, "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    preferred_lang = info.get("language")
    subtitles = info.get("subtitles") or {}
    automatic_captions = info.get("automatic_captions") or {}

    lang = _select_language(subtitles, preferred_lang)
    chosen = subtitles
    if lang is None:
        lang = _select_language(automatic_captions, preferred_lang)
        chosen = automatic_captions
    if lang is None:
        raise CaptionError(f"no captions (official or auto-generated) available for {url!r}")

    fmt = next((f for f in chosen[lang] if f.get("ext") == "vtt"), None)
    if fmt is None:
        raise CaptionError(f"no vtt-format caption track available for {url!r} in language {lang!r}")
    return _fetch_caption_track(fmt["url"])


def parse_youtube(url: str, source_id: str, *, downloader=None) -> Source:
    """Ingest a YouTube video's captions (official, else auto-generated) — never the video/audio
    itself (AGENTS.md's captions-only MVP decision). `downloader` is an injection seam for tests,
    mirroring `parse_web`'s `fetcher` parameter exactly: the default resolves and fetches a real
    caption track; a test-injected fake returns canned WebVTT text with no network access at all.
    """
    raw_vtt = (downloader or _default_downloader)(url)
    cues = _dedupe_consecutive(_parse_vtt(raw_vtt))
    if not cues:
        raise CaptionError(f"caption track for {url!r} parsed to no usable text")
    return Source(id=source_id, kind="youtube", origin=url, blocks=_chunk(cues))
