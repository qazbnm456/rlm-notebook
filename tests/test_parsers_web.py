from __future__ import annotations

import pytest

from rlm_notebook.parsers.web import FetchError, parse_web

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
