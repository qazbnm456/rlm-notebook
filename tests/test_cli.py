from __future__ import annotations

import pytest

from rlm_notebook.cli import _ingest_one, _is_url, build_parser


def test_is_url():
    assert _is_url("https://example.com/x")
    assert _is_url("http://example.com/x")
    assert not _is_url("./notes.txt")
    assert not _is_url("paper.pdf")


def test_ingest_one_text_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello world", encoding="utf-8")
    source = _ingest_one(str(path), "s1")
    assert source.kind == "text"
    assert source.blocks[0].text == "hello world"


def test_ingest_one_pdf(tmp_path):
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "hello pdf")
    doc.save(str(path))
    source = _ingest_one(str(path), "s1")
    assert source.kind == "pdf"
    assert source.blocks[0].locator == "page:1"


def test_ask_requires_source():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["ask", "a question"])


def test_ask_parses_repeated_sources():
    parser = build_parser()
    args = parser.parse_args(["ask", "a question", "--source", "a.txt", "--source", "b.pdf"])
    assert args.source == ["a.txt", "b.pdf"]
    assert args.question == "a question"
