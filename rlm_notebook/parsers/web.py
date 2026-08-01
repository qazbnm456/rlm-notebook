"""Web page ingestion: fetch (host-side, one-shot) + extract main content with trafilatura.

CLAUDE.md invariant 1: the fetch happens exactly ONCE, here, during ingestion — this module is
never handed to the RLM as a `tools=` entry. Reuses `rlm_kit.tools.fetch`'s pure SSRF-guard
functions (`is_safe_url`, `resolved_host_is_safe`), not `make_fetch_tool` itself — that factory
builds a live RLM *tool*, which is exactly what invariant 1 says this call site must never become.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import urlparse

import trafilatura
from rlm_kit.tools.fetch import is_safe_url, resolved_host_is_safe

from ..schema import Source, SourceBlock

Fetcher = "Callable[[str], str]"  # documented shape; see parse_web's `fetcher` param


class FetchError(RuntimeError):
    """A URL was unsafe to fetch, or the fetch/extraction otherwise failed."""


def _default_fetcher(url: str, *, timeout: float = 15.0) -> str:
    if not is_safe_url(url):
        raise FetchError(f"refused: {url!r} is not a permitted external http(s) URL")
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not resolved_host_is_safe(parsed.hostname or "", port):
        raise FetchError(f"refused: {url!r} resolves to a disallowed address")
    req = urllib.request.Request(url, headers={"User-Agent": "rlm-notebook/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise FetchError(f"fetch error for {url!r}: {exc}") from exc
    return raw.decode("utf-8", errors="replace")


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
    )
