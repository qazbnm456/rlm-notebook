from __future__ import annotations

import pytest

from rlm_notebook import cli
from rlm_notebook.cli import _cmd_ask, _cmd_guide, _print_citations, build_parser
from rlm_notebook.corpus import Corpus
from rlm_notebook.schema import FAQ, Answer, Citation, PodcastScript, Source, SourceBlock, Timeline, Utterance


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
    dspy/rlm-harness at all, so these tests exercise `_cmd_ask`/`_cmd_guide`'s own output-formatting
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


def test_speaker_labels_cover_every_known_speaker_value():
    """Tripwire: `cli._SPEAKER_LABELS` is a plain dict keyed by `schema.Speaker`'s literal values,
    with no type-checker enforcement that the two stay in sync (this project's CI runs ruff +
    pytest only, no mypy/pyright — an independent review confirmed a third `Speaker` value would
    raise an uncaught `KeyError` in `_cmd_audio` with nothing to catch it ahead of time). If this
    fails, `_SPEAKER_LABELS` is missing an entry for a `Speaker` value that now exists."""
    from typing import get_args

    from rlm_notebook.schema import Speaker

    assert set(get_args(Speaker)) <= set(cli._SPEAKER_LABELS)


def test_audio_parses_source_and_out():
    parser = build_parser()
    args = parser.parse_args(["audio", "--source", "a.pdf", "--out", "ep.mp3"])
    assert args.source == ["a.pdf"]
    assert args.out == "ep.mp3"


def test_audio_out_defaults_to_podcast_mp3():
    parser = build_parser()
    args = parser.parse_args(["audio", "--source", "a.pdf"])
    assert args.out == "podcast.mp3"


def test_cmd_audio_refuses_with_no_sources_and_no_notebook(capsys):
    parser = build_parser()
    args = parser.parse_args(["audio"])
    assert cli._cmd_audio(args) == 1
    assert "no sources" in capsys.readouterr().err


def test_cmd_audio_reports_an_empty_script_explicitly_instead_of_printing_nothing(monkeypatch, tmp_path, capsys):
    _live_env(monkeypatch)
    monkeypatch.setattr(cli, "GeneratePodcastScript", _fake_task(PodcastScript(utterances=[])))
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["audio", "--source", str(a)])
    assert cli._cmd_audio(args) == 0
    out = capsys.readouterr().out
    assert out.strip() != ""
    assert "no podcast script" in out


class _FakeTTSProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.calls: list = []

    def synthesize(self, script, voice_map, out_path):
        self.calls.append((script, voice_map, out_path))
        if self._fail:
            from rlm_notebook.tts import TTSError

            raise TTSError("simulated synthesis failure")
        out_path.write_bytes(b"fake mp3 bytes")


def test_cmd_audio_synthesizes_and_reports_the_output_path(monkeypatch, tmp_path, capsys):
    _live_env(monkeypatch)
    script = PodcastScript(
        utterances=[Utterance(speaker="host_a", text="hello", citations=[])]
    )
    monkeypatch.setattr(cli, "GeneratePodcastScript", _fake_task(script))
    fake_provider = _FakeTTSProvider()
    monkeypatch.setattr(cli, "get_tts_provider", lambda name: fake_provider)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")
    out = tmp_path / "ep.mp3"

    parser = build_parser()
    args = parser.parse_args(["audio", "--source", str(a), "--out", str(out)])
    assert cli._cmd_audio(args) == 0
    captured = capsys.readouterr().out
    assert "Host A: hello" in captured
    assert str(out) in captured
    assert out.read_bytes() == b"fake mp3 bytes"
    assert len(fake_provider.calls) == 1


def test_cmd_audio_reports_tts_failure_but_keeps_the_transcript_visible(monkeypatch, tmp_path, capsys):
    """The transcript is printed BEFORE synthesis is attempted — a network/provider failure must
    not make it look like nothing happened at all; the script itself is still useful without audio."""
    _live_env(monkeypatch)
    script = PodcastScript(
        utterances=[Utterance(speaker="host_a", text="hello", citations=[])]
    )
    monkeypatch.setattr(cli, "GeneratePodcastScript", _fake_task(script))
    monkeypatch.setattr(cli, "get_tts_provider", lambda name: _FakeTTSProvider(fail=True))
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["audio", "--source", str(a), "--out", str(tmp_path / "ep.mp3")])
    assert cli._cmd_audio(args) == 1
    out = capsys.readouterr()
    assert "Host A: hello" in out.out
    assert "synthesis failed" in out.err


def test_cmd_audio_rejects_a_bad_tts_provider_before_running_the_expensive_model_call(
    monkeypatch, tmp_path, capsys
):
    """Found by an independent review: `get_tts_provider(config.tts_provider)` used to be called
    AFTER `GeneratePodcastScript().run(...)` — a mistyped RN_TTS_PROVIDER only surfaced as an
    uncaught TTSError once the (potentially expensive) model call had already run and the
    transcript had already printed. Now it's resolved first; this asserts the model task is never
    even constructed when the provider name is bad."""
    _live_env(monkeypatch)
    monkeypatch.setenv("RN_TTS_PROVIDER", "not-a-real-provider")

    model_was_called = False

    def _tracking_task():
        nonlocal model_was_called
        model_was_called = True
        raise AssertionError("GeneratePodcastScript must not run when the TTS provider is invalid")

    monkeypatch.setattr(cli, "GeneratePodcastScript", _tracking_task)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["audio", "--source", str(a)])
    assert cli._cmd_audio(args) == 1
    assert not model_was_called
    err = capsys.readouterr().err
    assert "cannot generate audio" in err
    assert "not-a-real-provider" in err


def test_cmd_audio_passes_the_configured_provider_name_to_get_tts_provider(monkeypatch, tmp_path):
    """Found by an independent review: every prior audio test monkeypatched `get_tts_provider`
    wholesale, so none of them would have caught `_cmd_audio` accidentally passing the wrong
    config field (e.g. `config.ocr_provider` instead of `config.tts_provider`) — a spy on the
    NAME argument closes that gap."""
    _live_env(monkeypatch)
    monkeypatch.setenv("RN_TTS_PROVIDER", "edge-tts")
    script = PodcastScript(utterances=[Utterance(speaker="host_a", text="hello", citations=[])])
    monkeypatch.setattr(cli, "GeneratePodcastScript", _fake_task(script))

    received_names: list[str] = []

    def _spy(name):
        received_names.append(name)
        return _FakeTTSProvider()

    monkeypatch.setattr(cli, "get_tts_provider", _spy)
    a = tmp_path / "a.txt"
    a.write_text("hello", encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(["audio", "--source", str(a), "--out", str(tmp_path / "ep.mp3")])
    assert cli._cmd_audio(args) == 0
    assert received_names == ["edge-tts"]
