from __future__ import annotations

import pytest

from rlm_notebook.parsers.text import parse_text


def test_parse_text_produces_one_whole_block():
    source = parse_text("hello world", "s1", origin="notes.txt")
    assert source.kind == "text"
    assert source.origin == "notes.txt"
    assert len(source.blocks) == 1
    assert source.blocks[0].locator == "whole"
    assert source.blocks[0].text == "hello world"


def test_parse_text_rejects_empty():
    with pytest.raises(ValueError):
        parse_text("   \n  ", "s1")
