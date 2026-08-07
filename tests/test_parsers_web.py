from __future__ import annotations

import pytest

from rlm_notebook.parsers.web import FetchError, _SafeRedirectHandler, parse_web

_HTML = """\
<html><body>
<article>
<h1>Migratory Birds</h1>
<p>Arctic terns migrate from pole to pole every year, covering enormous distances.</p>
<p>Their navigation relies on the earth's magnetic field and visual landmarks.</p>
</article>
</body></html>
"""


def test_parse_web_extracts_main_content_via_injected_fetcher():
    calls = []

    def fake_fetcher(url: str) -> str:
        calls.append(url)
        return _HTML

    source = parse_web("https://example.com/birds", "s1", fetcher=fake_fetcher)
    assert calls == ["https://example.com/birds"]
    assert source.kind == "web"
    assert source.origin == "https://example.com/birds"
    assert len(source.blocks) == 1
    assert "Arctic terns" in source.blocks[0].text


def test_parse_web_raises_on_empty_extraction():
    def empty_fetcher(url: str) -> str:
        return "<html><body></body></html>"

    with pytest.raises(FetchError):
        parse_web("https://example.com/empty", "s1", fetcher=empty_fetcher)


def test_default_fetcher_refuses_unsafe_url_before_any_network_call():
    # No fetcher injected: the real _default_fetcher path runs, and must refuse a loopback target
    # (the SSRF guard) before attempting any connection at all — this must not hang or hit the
    # network in a test environment.
    with pytest.raises(FetchError, match="refused"):
        parse_web("http://localhost:9999/", "s1")


def test_default_fetcher_refuses_metadata_target():
    with pytest.raises(FetchError, match="refused"):
        parse_web("http://169.254.169.254/latest/meta-data/", "s1")


def test_redirect_to_metadata_target_is_refused():
    """A single 3xx hop must not bypass the SSRF guard: an initially-safe-looking URL that
    redirects to an internal/metadata target must be refused at the redirect, not silently
    followed. Found by an independent review of an earlier version of this module that fetched
    with urllib's default opener (which follows Location headers unconditionally, unchecked)."""
    import urllib.request

    handler = _SafeRedirectHandler()
    req = urllib.request.Request("http://example.com/safe-looking-page")
    with pytest.raises(FetchError, match="refused"):
        handler.redirect_request(
            req, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data/"
        )


def test_redirect_to_loopback_is_refused():
    import urllib.request

    handler = _SafeRedirectHandler()
    req = urllib.request.Request("http://example.com/safe-looking-page")
    with pytest.raises(FetchError, match="refused"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1:8080/internal")


def test_default_fetcher_uses_the_guarded_opener_never_plain_urlopen(monkeypatch):
    """Invariant 2 ends "Do not swap back to plain `urllib.request.urlopen`" and, until an
    independent audit checked, nothing enforced it: swapping `_opener.open` for
    `urllib.request.urlopen` left the whole suite green, because the two redirect tests call
    `_SafeRedirectHandler.redirect_request` directly and never exercise WHICH opener does the
    fetching. `urlopen` uses the default opener, which follows redirects with no per-hop
    re-validation — the exact hole `_SafeRedirectHandler` exists to close.
    """
    import urllib.request

    from rlm_notebook.parsers import web

    def _explode(*args, **kwargs):
        raise AssertionError("the plain default opener must never be reached")

    monkeypatch.setattr(urllib.request, "urlopen", _explode)

    opened: list = []

    class _Response:
        def read(self):
            return b"<html><body>ok</body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        web._opener, "open", lambda req, timeout=None: opened.append(req) or _Response()
    )

    assert web._default_fetcher("https://example.com/a") == "<html><body>ok</body></html>"
    assert len(opened) == 1

