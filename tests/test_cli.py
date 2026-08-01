from __future__ import annotations

import pytest

from rlm_notebook import cli
from rlm_notebook.cli import (
    _cmd_ask,
    _cmd_guide,
    _ingest_new,
    _ingest_one,
    _is_url,
    _print_citations,
    build_parser,
)
from rlm_notebook.corpus import Corpus
from rlm_notebook.schema import FAQ, Answer, Citation, Source, SourceBlock, Timeline


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


def test_guide_parses_kind_and_source():
    parser = build_parser()
    args = parser.parse_args(["guide", "summary", "--source", "a.pdf"])
    assert args.kind == "summary"
    assert args.source == ["a.pdf"]


def test_guide_rejects_an_unknown_kind():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["guide", "not-a-real-kind", "--source", "a.pdf"])


@pytest.mark.parametrize("kind", ["summary", "faq", "timeline", "insight"])
def test_guide_accepts_every_known_kind(kind):
    parser = build_parser()
    args = parser.parse_args(["guide", kind, "--source", "a.pdf"])
    assert args.kind == kind


def test_cmd_guide_refuses_with_no_sources_and_no_notebook(capsys):
    """Shares `_prepare` with `_cmd_ask` — this early-return path runs before any model
    config/call, so it's safe to exercise offline."""
    parser = build_parser()
    args = parser.parse_args(["guide", "summary"])
    assert _cmd_guide(args) == 1
    assert "no sources" in capsys.readouterr().err


def test_cmd_guide_reports_a_clear_error_on_a_corrupted_notebook_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notebooks").mkdir()
    (tmp_path / "notebooks" / "mynb.json").write_text('{"id": "mynb", "sources": [}', encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["guide", "summary", "--notebook", "mynb"])

    assert _cmd_guide(args) == 1
    err = capsys.readouterr().err
    assert "mynb" in err and "not a valid notebook file" in err


def _corpus_with_page1(source_id: str = "s1") -> Corpus:
    corpus = Corpus()
    corpus.add(
        Source(id=source_id, kind="pdf", origin="x.pdf", blocks=[SourceBlock(locator="page:1", text="hi")])
    )
    return corpus


def test_print_citations_prints_nothing_for_an_empty_list(capsys):
    _print_citations([], _corpus_with_page1())
    assert capsys.readouterr().out == ""


def test_print_citations_marks_verified_and_unverified(capsys):
    citations = [
        Citation(source_id="s1", locator="page:1", quote="hi"),
        Citation(source_id="s1", locator="page:99", quote="nope"),
    ]
    _print_citations(citations, _corpus_with_page1())
    out = capsys.readouterr().out
    assert "✓" in out
    assert "✗ UNVERIFIED" in out


def test_print_citations_leading_blank_line_is_its_own_output_not_the_caller_s():
    """`_print_citations` owns its own leading blank line — a citation-less call must print
    NOTHING, not a stray blank line a caller printed unconditionally before calling it (found by
    an independent review of an earlier version where every call site did exactly that)."""
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_citations([], _corpus_with_page1())
    assert buf.getvalue() == ""


class _FakeTask:
    """A stand-in RLMTask instance — `.run(**kwargs)` returns a canned result without touching
    dspy/rlm-kit at all, so these tests exercise `_cmd_ask`/`_cmd_guide`'s own output-formatting
    logic in isolation. `_fake_task(result)` below is the zero-arg factory `cli._GUIDE_TASKS[kind]`
    / `cli.AnswerQuestion` is called as (`SomeTask()`), returning an instance of this."""

    def __init__(self, result) -> None:
        self._result = result

    def run(self, **kwargs):
        del kwargs
        return self._result


def _fake_task(result):
    return lambda: _FakeTask(result)


def _live_env(monkeypatch) -> None:
    monkeypatch.setenv("RN_MAIN_MODEL", "test/model")
    monkeypatch.delenv("RN_INTERPRETER", raising=False)


def test_cmd_ask_prints_no_trailing_blank_line_when_there_are_no_citations(monkeypatch, tmp_path, capsys):
    _live_env(monkeypatch)
    monkeypatch.setattr(cli, "AnswerQuestion", _fake_task(Answer(text="the answer", citations=[])))
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["ask", "a question", "--source", str(a)])
    assert _cmd_ask(args) == 0
    assert capsys.readouterr().out == "the answer\n"


def test_cmd_guide_reports_an_empty_faq_explicitly_instead_of_printing_nothing(monkeypatch, tmp_path, capsys):
    """An empty FAQ is a legitimate answer (guide.py's instructions explicitly allow it) — it must
    not look identical to the command having silently produced no output at all."""
    _live_env(monkeypatch)
    monkeypatch.setitem(cli._GUIDE_TASKS, "faq", _fake_task(FAQ(items=[])))
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["guide", "faq", "--source", str(a)])
    assert _cmd_guide(args) == 0
    out = capsys.readouterr().out
    assert out.strip() != ""
    assert "no FAQ items" in out


def test_cmd_guide_reports_an_empty_timeline_explicitly_instead_of_printing_nothing(monkeypatch, tmp_path, capsys):
    _live_env(monkeypatch)
    monkeypatch.setitem(cli._GUIDE_TASKS, "timeline", _fake_task(Timeline(events=[])))
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["guide", "timeline", "--source", str(a)])
    assert _cmd_guide(args) == 0
    out = capsys.readouterr().out
    assert out.strip() != ""
    assert "no timeline" in out
