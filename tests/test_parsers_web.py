from __future__ import annotations

import pytest

from rlm_notebook.parsers import web
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



def test_a_preview_is_scraped_from_the_html_already_in_hand():
    """No second request: `parse_web` hands `extract_preview` the SAME html it fetched once.
    Invariant 1 allows exactly one host-side fetch per source, and a preview that fetched anything
    of its own would quietly break that."""
    html = """
    <html><head>
      <title>Fallback title</title>
      <meta property="og:title" content="Voyager 1 leaves the heliosphere">
      <meta name="description" content="ignored, og wins">
      <meta property="og:description" content="  A  probe   crosses  a boundary. ">
      <meta property="og:site_name" content="NASA">
    </head><body>x</body></html>
    """
    preview = web.extract_preview(html)
    assert preview["title"] == "Voyager 1 leaves the heliosphere"
    assert preview["description"] == "A probe crosses a boundary."  # whitespace collapsed
    assert preview["site"] == "NASA"


def test_the_title_tag_is_the_fallback_when_no_meta_carries_one():
    preview = web.extract_preview("<html><head><title> Plain <b>page</b> </title></head></html>")
    assert preview["title"] == "Plain page"
    assert "description" not in preview


def test_attribute_order_inside_a_meta_tag_does_not_matter():
    """`content` before `property` is just as valid, and a page that writes it that way is not
    trying to hide anything — a one-sided regex would simply lose the preview."""
    html = '<meta content="Reversed order" property="og:title">'
    assert web.extract_preview(html)["title"] == "Reversed order"


def test_a_preview_never_carries_an_image():
    """`og:image` is deliberately absent. Rendering one makes the READER's browser fetch a URL the
    page author chose, handing that third party an IP and a request to log — every pasted link
    would become a beacon, in exchange for a thumbnail. Pinned because adding it back looks like an
    obvious improvement."""
    html = (
        '<meta property="og:image" content="https://tracker.example/pixel.png">'
        '<meta property="og:title" content="A page">'
    )
    preview = web.extract_preview(html)
    assert preview == {"title": "A page"}
    assert not any("tracker.example" in value for value in preview.values())


def test_a_preview_is_display_only_and_never_reaches_the_corpus():
    """The blob is built from `blocks` alone, so a page controlling its own `<meta>` tags can
    influence what a Sources row LOOKS like and nothing the model reads."""
    from rlm_notebook.corpus import Corpus

    html = '<meta property="og:title" content="INJECTED-INTO-PREVIEW"><p>real body text</p>'
    source = web.parse_web(
        "https://example.com/a", "s1", fetcher=lambda url, timeout=15.0: html
    )
    assert source.preview["title"] == "INJECTED-INTO-PREVIEW"
    assert "INJECTED-INTO-PREVIEW" not in Corpus([source]).blob()


def test_a_hostile_page_cannot_stall_the_preview_scraper():
    """`re` does not release the GIL, so a slow match freezes the event loop and every other thread
    — `asyncio.to_thread` buys nothing. An independent security review measured the unbounded
    version taking 38s on a 19.7KB page of UNCLOSED `<meta` tags (cubic, and `_default_fetcher`
    reads a response of any size), reachable by anyone who can paste a URL into this no-auth API.

    Asserts a CONSTANT bound, not a fast one: the point is that the worst case stops depending on
    what the server was served. A generous ceiling on purpose — this must not flake on a loaded CI
    box, and the defect it guards against was three orders of magnitude away from it.
    """
    import time

    hostile = "<html><head><title>t</title>" + '<meta name="a" ' * 200_000  # ~2.9 MB, never closed
    start = time.perf_counter()
    web.extract_preview(hostile)
    hostile_seconds = time.perf_counter() - start
    assert hostile_seconds < 5.0, f"{hostile_seconds:.1f}s — the input window is not bounding it"

    # And a WELL-FORMED page of the same shape stays fast, which is why the bounds cost nothing
    # real: every genuine `<meta …>` closes its `>`.
    benign = "<html><head>" + '<meta name="x" content="y">' * 5000 + "</head>"
    start = time.perf_counter()
    web.extract_preview(benign)
    assert time.perf_counter() - start < 1.0
