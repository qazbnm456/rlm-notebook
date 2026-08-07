"""Web page ingestion: fetch (host-side, one-shot) + extract main content with trafilatura.

CLAUDE.md invariant 1: the fetch happens exactly ONCE, here, during ingestion — this module is
never handed to the RLM as a `tools=` entry. Reuses `rlm_harness.tools.fetch`'s pure SSRF-guard
functions (`is_safe_url`, `resolved_host_is_safe`), not `make_fetch_tool` itself — that factory
builds a live RLM *tool*, which is exactly what invariant 1 says this call site must never become.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

import trafilatura
from rlm_harness.tools.fetch import is_safe_url, resolved_host_is_safe

from ..schema import Source, SourceBlock

Fetcher = "Callable[[str], str]"  # documented shape; see parse_web's `fetcher` param


class FetchError(RuntimeError):
    """A URL was unsafe to fetch, or the fetch/extraction otherwise failed."""


def _check_safe(url: str) -> None:
    if not is_safe_url(url):
        raise FetchError(f"refused: {url!r} is not a permitted external http(s) URL")
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not resolved_host_is_safe(parsed.hostname or "", port):
        raise FetchError(f"refused: {url!r} resolves to a disallowed address")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validates EVERY redirect hop against the SSRF guard before following it.

    The default opener follows a `Location` header unconditionally, which would let a single 3xx
    response bounce an initially-safe URL to an internal/loopback/metadata target with no further
    check — `rlm_harness.tools.fetch`'s own docstring calls this out explicitly ("call it INSIDE your
    fetcher at connection time, and on every redirect hop"); found by an independent review of the
    first version of this module, which fetched with the default opener and had no per-hop check.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_safe(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirectHandler)


def _default_fetcher(url: str, *, timeout: float = 15.0) -> str:
    _check_safe(url)
    req = urllib.request.Request(url, headers={"User-Agent": "rlm-notebook/0.1"})
    try:
        with _opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
    except FetchError:
        raise
    except (urllib.error.URLError, TimeoutError) as exc:
        raise FetchError(f"fetch error for {url!r}: {exc}") from exc
    return raw.decode("utf-8", errors="replace")


#: The `<meta>` tags worth showing in a Sources row, in the order they are preferred. Open Graph
#: first because a page that bothers to set it has written copy meant to be shown as a card.
_PREVIEW_META = {
    "title": ("og:title", "twitter:title"),
    "description": ("og:description", "twitter:description", "description"),
    "site": ("og:site_name",),
}

#: Every quantifier here is BOUNDED, and `extract_preview` windows its input as well. Both are
#: required, and neither is defensive tidying: with `[^>]*?` an independent security review measured
#: CATASTROPHIC BACKTRACKING on `'<meta name="a" ' * n` — unclosed tags, so `[^>]*?` never reaches a
#: `>` and every `<meta ` start position rescans the whole run. Cubic, measured end to end through
#: `parse_web`: 6.5KB took 0.50s, 15.3KB took 12.98s, 19.7KB took 38.08s. `re` does NOT release the
#: GIL — a watchdog thread saw a 14s hard pause — so `asyncio.to_thread` buys the event loop
#: nothing. On a no-auth API (invariant 25) where any caller can paste any URL, and where
#: `_default_fetcher` reads a response of any size, that is a one-request freeze of the whole
#: server. A WELL-FORMED 681KB page with 5000 meta tags parsed in 0.019s, because a real
#: `<meta …>` closes its `>`; the pathological input is the only one these bounds cost anything on.
_ATTR_GAP = r"[^>]{0,300}?"
_META_TAG = re.compile(
    rf"""<meta\s{_ATTR_GAP}(?:property|name)\s*=\s*["']([^"']{{1,200}})["']{_ATTR_GAP}"""
    rf"""content\s*=\s*["']([^"']{{0,2000}})["']"""
    rf"""|<meta\s{_ATTR_GAP}content\s*=\s*["']([^"']{{0,2000}})["']{_ATTR_GAP}"""
    rf"""(?:property|name)\s*=\s*["']([^"']{{1,200}})["']""",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_TAG = re.compile(r"<title[^>]{0,200}>(.{0,2000}?)</title>", re.IGNORECASE | re.DOTALL)

#: How much of the document the scraper looks at. A preview only ever lives in `<head>`, so this is a
#: WINDOW, not a truncation of the source: `parse_web` still hands the whole document to
#: `trafilatura`, and nothing a reader can cite is affected.
_PREVIEW_WINDOW = 64 * 1024


def extract_preview(html: str) -> dict[str, str]:
    """DISPLAY-ONLY page metadata, parsed from HTML this function was already handed.

    **No extra request is made, and no image is ever referenced.** `og:image` is deliberately absent:
    rendering one would make the reader's browser fetch a URL the page author chose, handing that
    third party the reader's IP and a request to log, for a thumbnail. The value of a preview is the
    title and the description; the picture is not worth turning every pasted link into a beacon.

    Regex rather than a parser because the whole point is to add no dependency to an ingestion path
    that already has `trafilatura` doing the real work. Values are whitespace-collapsed and
    truncated here and rendered with `textContent` in the UI (never `innerHTML` — invariant 29), so
    a malformed match is a cosmetic miss, never a hazard. No ESCAPING happens here, and an earlier
    draft of this docstring claimed it did.

    Every pattern above is bounded and the input is windowed — see `_META_TAG` for the measured
    denial-of-service that made both mandatory.
    """
    # Window FIRST. Everything below is bounded too, but bounding the INPUT is what makes the worst
    # case a constant rather than a function of what someone chose to serve.
    window = html[:_PREVIEW_WINDOW]
    head_end = window.lower().find("</head>")
    if head_end != -1:
        window = window[:head_end]

    found: dict[str, str] = {}
    tags: dict[str, str] = {}
    for match in _META_TAG.finditer(window):
        key = (match.group(1) or match.group(4) or "").strip().lower()
        value = match.group(2) if match.group(1) else match.group(3)
        if key and value and key not in tags:
            tags[key] = " ".join(value.split())

    for field, candidates in _PREVIEW_META.items():
        for candidate in candidates:
            if tags.get(candidate):
                found[field] = tags[candidate][:300]
                break

    if "title" not in found:
        match = _TITLE_TAG.search(window)
        if match:
            title = " ".join(re.sub(r"<[^>]+>", "", match.group(1)).split())
            if title:
                found["title"] = title[:300]
    return found


def parse_web(url: str, source_id: str, *, fetcher=None) -> Source:
    """Ingest a web page. `fetcher` is an injection seam for tests (a fake returning canned HTML);
    the default fetches over the real network with the SSRF guard applied first."""
    html = (fetcher or _default_fetcher)(url)
    text = trafilatura.extract(html, url=url)
    if not text or not text.strip():
        raise FetchError(f"no extractable text content at {url!r}")
    return Source(
        id=source_id,
        kind="web",
        origin=url,
        blocks=[SourceBlock(locator="whole", text=text)],
        # From the SAME html already in hand — one fetch, as invariant 1 requires.
        preview=extract_preview(html),
    )
