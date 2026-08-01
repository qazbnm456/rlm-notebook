from __future__ import annotations

import pytest

from rlm_notebook.cli import _cmd_ask, _ingest_new, _ingest_one, _is_url, build_parser


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


def test_ask_source_is_optional_at_the_argparse_level():
    """`--source` is optional in argparse itself now — required or not depends on whether
    `--notebook` points at one with existing sources, which `_cmd_ask` checks at runtime, not
    argparse at parse time (see `test_cmd_ask_refuses_with_no_sources_and_no_notebook`)."""
    parser = build_parser()
    args = parser.parse_args(["ask", "a question"])
    assert args.source is None
    assert args.notebook is None


def test_ask_parses_repeated_sources():
    parser = build_parser()
    args = parser.parse_args(["ask", "a question", "--source", "a.txt", "--source", "b.pdf"])
    assert args.source == ["a.txt", "b.pdf"]
    assert args.question == "a question"


def test_ask_parses_notebook_flag():
    parser = build_parser()
    args = parser.parse_args(["ask", "a question", "--notebook", "mynb"])
    assert args.notebook == "mynb"


def test_cmd_ask_refuses_with_no_sources_and_no_notebook(capsys):
    """This early-return path runs before any model config/call, so it's safe to exercise offline
    (see the known gap noted in CLAUDE.md/CHANGELOG: `_cmd_ask`'s live-model path is untested)."""
    parser = build_parser()
    args = parser.parse_args(["ask", "a question"])
    assert _cmd_ask(args) == 1
    assert "no sources" in capsys.readouterr().err


def test_ingest_new_skips_existing_origins(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("hello b", encoding="utf-8")

    sources = _ingest_new([str(a), str(b)], start_index=3, skip_origins={str(a)})

    assert [s.origin for s in sources] == [str(b)]
    assert sources[0].id == "s3"


def test_ingest_new_numbers_ids_from_start_index(tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("hello b", encoding="utf-8")

    sources = _ingest_new([str(a), str(b)], start_index=5, skip_origins=set())

    assert [s.id for s in sources] == ["s5", "s6"]


def test_ingest_new_dedupes_a_value_repeated_within_the_same_call(tmp_path):
    """Found by an independent review: the first version only checked the caller's static
    `skip_origins` set, so `--source a.txt --source a.txt` in ONE invocation (not across two) sailed
    through and ingested `a.txt` twice under two different ids."""
    a = tmp_path / "a.txt"
    a.write_text("hello a", encoding="utf-8")

    sources = _ingest_new([str(a), str(a), str(a)], start_index=1, skip_origins=set())

    assert len(sources) == 1
    assert sources[0].id == "s1"


def test_cmd_ask_reports_a_clear_error_on_a_corrupted_notebook_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notebooks").mkdir()
    (tmp_path / "notebooks" / "mynb.json").write_text('{"id": "mynb", "sources": [}', encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["ask", "a question", "--notebook", "mynb"])

    assert _cmd_ask(args) == 1
    err = capsys.readouterr().err
    assert "mynb" in err and "not a valid notebook file" in err
