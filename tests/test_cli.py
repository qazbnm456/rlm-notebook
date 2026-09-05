from __future__ import annotations

import pytest

from rlm_notebook import cli
from rlm_notebook.cli import _cmd_ask, _cmd_guide, _print_citations, build_parser
from rlm_notebook.corpus import Corpus
from rlm_notebook.schema import (
    FAQ,
    Answer,
    Citation,
    PodcastScript,
    Source,
    SourceBlock,
    Summary,
    Timeline,
    Utterance,
)


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


def test_cmd_guide_reports_an_empty_timeline_explicitly_instead_of_printing_nothing(
    monkeypatch, tmp_path, capsys
):
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


def test_cmd_audio_reports_an_empty_script_explicitly_instead_of_printing_nothing(
    monkeypatch, tmp_path, capsys
):
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
    # A `TTSProvider` now also declares its output FORMAT and its own language->voice defaults, so a
    # local model emitting WAV isn't forced through an MP3 encoder and one provider's voice names
    # can't leak into another's request (CLAUDE.md invariant 43).
    suffix = ".mp3"
    media_type = "audio/mpeg"

    def default_voices(self, language):
        return None

    def validate(self, language=None, voice_map=None):
        # Tracks `tts.TTSProvider`: the pre-flight that stops a bad language or voice from wasting
        # a real model run (invariant 19). A double that omits it would let a caller drop the call.
        self.validated = (language, voice_map)

    def fallback_voices(self):
        # Tracks `tts.TTSProvider`: a double that does not implement the whole Protocol lets a real
        # gap hide (an independent audit found the LAST-RESORT cast had never moved onto the
        # provider, so an unknown language on the local one fell through to an edge-tts name).
        return ("fake-voice-a", "fake-voice-b")

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.calls: list = []

    def synthesize(self, script, voice_map, out_path, language=None):
        self.calls.append((script, voice_map, out_path, language))
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


def test_cmd_audio_passes_the_resolved_language_to_synthesize_and_validate(
    monkeypatch, tmp_path, capsys
):
    """The CLI half of the same claim. An independent review mutation-proved it uncovered: passing
    `None` from both call sites left the suite green, and a Chinese script synthesized with
    `language_id="en"` is exactly what `_language_id`'s raise exists to prevent."""
    _live_env(monkeypatch)
    monkeypatch.setenv("RN_OUTPUT_LANGUAGE", "Traditional Chinese")
    script = PodcastScript(utterances=[Utterance(speaker="host_a", text="hello", citations=[])])
    monkeypatch.setattr(cli, "GeneratePodcastScript", _fake_task(script))
    provider = _FakeTTSProvider()
    monkeypatch.setattr(cli, "get_tts_provider", lambda name: provider)
    source = tmp_path / "a.txt"
    source.write_text("hello", encoding="utf-8")

    args = build_parser().parse_args(
        ["audio", "--source", str(source), "--out", str(tmp_path / "ep.mp3")]
    )
    assert cli._cmd_audio(args) == 0

    assert provider.calls[0][3] == "Traditional Chinese"
    # ...and the same language reached the pre-flight, which is what makes invariant 19's ordering
    # meaningful rather than decorative.
    assert provider.validated[0] == "Traditional Chinese"


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


# --- durable writes (slice 14) -------------------------------------------------------------------


def _seed_notebook(monkeypatch, tmp_path, text: str = "the first source"):
    """A persisted notebook with one source, plus an isolated cwd. Returns the source file path so
    a caller can pass it as `--source` again (a no-op re-add) or add a different one."""
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "a.txt"
    src.write_text(text, encoding="utf-8")
    return src


def test_cmd_ask_appends_its_turn_without_destroying_a_concurrent_write(tmp_path, monkeypatch, capsys):
    """The CLI's half of this slice's defect, which the API's own regression test does not cover:
    `_cmd_ask` used to append its turn to the notebook `_prepare` returned — read BEFORE the model
    ran — and `save_notebook` the whole thing back, destroying anything written meanwhile. An
    independent test-quality review proved the gap by restoring exactly that code and watching the
    entire suite still pass.

    The concurrent write happens INSIDE the stubbed model call, i.e. in the same window a real
    `rlm-notebook ask` leaves open for minutes."""
    src = _seed_notebook(monkeypatch, tmp_path)

    from rlm_notebook.notebook import add_note, load_notebook, mutate_notebook

    class _StubTask:
        def run(self, **kwargs):
            # Something else writes to the same notebook while the model is "running".
            mutate_notebook("mynb", lambda nb: add_note(nb, "written during the run"), create=True)
            return Answer(text="an answer", citations=[])

    monkeypatch.setattr(cli, "AnswerQuestion", _StubTask)
    monkeypatch.setattr(cli, "setup", lambda config: config)
    monkeypatch.setattr(cli.NotebookConfig, "from_env", classmethod(lambda cls: cls()))

    args = build_parser().parse_args(["ask", "what?", "--source", str(src), "--notebook", "mynb"])
    assert _cmd_ask(args) == 0

    saved = load_notebook("mynb")
    assert [n.text for n in saved.notes] == ["written during the run"], "the concurrent note was destroyed"
    assert len(saved.turns) == 1, "the ask's own turn was lost"
    assert len(saved.sources) == 1


def test_prepare_persists_ingestion_before_the_model_runs(tmp_path, monkeypatch, capsys):
    """A run that dies mid-model must not discard ingestion the user already paid for in OCR or
    network time — so `_prepare` persists it in its own critical section, not in a single save at
    the end of the command."""
    src = _seed_notebook(monkeypatch, tmp_path)

    from rlm_notebook.notebook import load_notebook

    class _ExplodingTask:
        def run(self, **kwargs):
            raise RuntimeError("the model run died")

    monkeypatch.setattr(cli, "AnswerQuestion", _ExplodingTask)
    monkeypatch.setattr(cli, "setup", lambda config: config)
    monkeypatch.setattr(cli.NotebookConfig, "from_env", classmethod(lambda cls: cls()))

    args = build_parser().parse_args(["ask", "what?", "--source", str(src), "--notebook", "mynb"])
    with pytest.raises(RuntimeError, match="the model run died"):
        _cmd_ask(args)

    saved = load_notebook("mynb")
    assert saved is not None, "ingestion was discarded when the run failed"
    assert [s.origin for s in saved.sources] == [str(src)]
    assert saved.turns == []


def test_prepare_hands_the_model_the_ids_that_were_actually_persisted(tmp_path, monkeypatch):
    """`append_sources` renumbers against the freshly-loaded notebook, so `_prepare` must return
    THAT notebook, not its own pre-merge snapshot. Returning the snapshot would have the model cite
    `s2` for a source persisted as `s3` — every citation in the run silently wrong. Caught by this
    slice's pre-implementation audit; pinned here so it can't regress.

    The concurrent write is injected DURING ingestion, which is the only window where the two
    disagree — a mutation-test of a first version of this test (which wrote concurrently before
    `_prepare` ran) survived: snapshot and fresh notebook were identical, so nothing could tell
    them apart, and the test passed against the very defect it was named for."""
    monkeypatch.chdir(tmp_path)
    new_src = tmp_path / "b.txt"
    new_src.write_text("brand new content", encoding="utf-8")

    from rlm_notebook.notebook import append_sources, load_notebook, mutate_notebook

    real_ingest = cli.ingest_sources_for

    def _ingest_then_someone_else_writes(notebook, values):
        ingested = real_ingest(notebook, values)
        # Another writer lands while this invocation is still parsing/fetching its own sources.
        other = Source(
            id="s1", kind="text", origin="added-by-someone-else",
            blocks=[SourceBlock(locator="whole", text="theirs")],
        )
        mutate_notebook("mynb", lambda nb: append_sources(nb, [other]), create=True)
        return ingested

    monkeypatch.setattr(cli, "ingest_sources_for", _ingest_then_someone_else_writes)

    args = build_parser().parse_args(["ask", "q", "--source", str(new_src), "--notebook", "mynb"])
    prepared = cli._prepare(args)
    assert prepared is not None
    notebook, corpus = prepared

    persisted = load_notebook("mynb")
    assert [s.origin for s in persisted.sources] == ["added-by-someone-else", str(new_src)]
    assert [s.id for s in persisted.sources] == ["s1", "s2"]
    # What the model is handed must match what is on disk, id for id — otherwise it cites an id
    # that points at different text, or at nothing.
    assert [(s.id, s.origin) for s in notebook.sources] == [
        (s.id, s.origin) for s in persisted.sources
    ]
    assert "[[SRC:s2|" in corpus.blob()


def test_cmd_guide_does_not_write_a_second_time(tmp_path, monkeypatch, capsys):
    """`_prepare` already persisted any newly ingested sources, so `guide` has nothing left to
    write. A trailing `save_notebook` here would be a second write path holding a pre-run
    snapshot — exactly the shape this slice removed."""
    src = _seed_notebook(monkeypatch, tmp_path)

    from rlm_notebook.notebook import add_note, load_notebook, mutate_notebook

    class _StubGuide:
        def run(self, **kwargs):
            mutate_notebook("mynb", lambda nb: add_note(nb, "written during the guide run"), create=True)
            return Summary(text="a summary", citations=[])

    monkeypatch.setitem(cli._GUIDE_TASKS, "summary", _StubGuide)
    monkeypatch.setattr(cli, "setup", lambda config: config)
    monkeypatch.setattr(cli.NotebookConfig, "from_env", classmethod(lambda cls: cls()))

    args = build_parser().parse_args(["guide", "summary", "--source", str(src), "--notebook", "mynb"])
    assert _cmd_guide(args) == 0

    saved = load_notebook("mynb")
    assert [n.text for n in saved.notes] == ["written during the guide run"]


def test_the_audio_command_offers_the_same_three_lengths_as_the_web_ui():
    """Both entry points feed the same `target_length` field. A flag the CLI cannot pass is a
    capability that exists only in the browser — the entry-point divergence invariant 20 guards
    against one level down (it requires the two to SHARE code, not to have the same features).

    Reads the accepted CHOICES off the parser, not the help STRING: an independent review renamed
    them to ("s", "default", "l") and the first version of this test still passed, because every
    tier name also appears in the flag's own help sentence.
    """
    parser = build_parser()
    action = next(
        a
        for a in parser._subparsers._group_actions[0].choices["audio"]._actions
        if a.dest == "length"
    )
    assert tuple(action.choices) == ("short", "default", "long")
    assert action.default == "default"


def test_the_audio_command_passes_the_chosen_length_to_the_task(monkeypatch, tmp_path):
    """The CLI half of invariant 63. An independent review hardcoded `target_length="default"` at
    the call site and the WHOLE suite stayed green: the flag became inert — the `RN_OCR_PROVIDER`
    shape (invariant 7) on the entry point no test covered. The API half was pinned; this was not.
    """

    from rlm_notebook import cli
    from rlm_notebook.schema import PodcastScript, Source, SourceBlock

    source = Source(
        id="s1", kind="text", origin="o",
        blocks=[SourceBlock(locator="whole", text="content")],
    )
    seen: dict = {}

    class _FakeTask:
        def run(self, **kwargs):
            seen.update(kwargs)
            return PodcastScript(utterances=[])

    monkeypatch.setattr(cli, "_prepare", lambda args: (None, Corpus([source])))
    monkeypatch.setattr(cli, "GeneratePodcastScript", lambda *a, **kw: _FakeTask())
    monkeypatch.setenv("RN_MAIN_MODEL", "test/model")
    monkeypatch.setenv("RN_OUTPUT_LANGUAGE", "English")
    monkeypatch.delenv("RN_INTERPRETER", raising=False)

    for tier in ("short", "long"):
        seen.clear()
        # Parsed by the REAL parser rather than hand-built, so a flag added to the shared
        # `_add_source_and_notebook_args` cannot make this test fail for a reason unrelated to
        # what it checks — and so the namespace it drives is the one the product builds.
        args = cli.build_parser().parse_args(["audio", "--length", tier, "--out", str(tmp_path / "a.mp3")])
        cli._cmd_audio(args)
        assert seen.get("target_length") == tier, (
            f"--length {tier} never reached the task; the flag is inert"
        )


def _audio_cli(monkeypatch, seen, *, script=None):
    """The `audio` command with its model call faked, so a test can drive the real argument parsing
    and the real `_cmd_audio` body without a model, a network call or a sandbox."""
    from rlm_notebook import cli
    from rlm_notebook.schema import PodcastScript, Source, SourceBlock

    source = Source(
        id="s1", kind="text", origin="o", blocks=[SourceBlock(locator="whole", text="content")]
    )

    class _FakeTask:
        def run(self, **kwargs):
            seen["ran"] = True
            seen.update(kwargs)
            return script or PodcastScript(utterances=[])

    monkeypatch.setattr(cli, "_prepare", lambda args: (None, Corpus([source])))
    monkeypatch.setattr(cli, "GeneratePodcastScript", lambda *a, **kw: _FakeTask())
    monkeypatch.setenv("RN_MAIN_MODEL", "test/model")
    monkeypatch.setenv("RN_OUTPUT_LANGUAGE", "English")
    monkeypatch.delenv("RN_INTERPRETER", raising=False)
    return cli


def test_every_run_taking_subcommand_offers_trace():
    """On the SHARED argument helper, not per command. A rule with one silent exception is the kind
    that gets rediscovered as a bug report (invariant 46 records the same lesson for `/title`)."""
    from rlm_notebook import cli

    parser = cli.build_parser()
    for command in ("ask", "guide", "audio"):
        argv = {"ask": ["ask", "q"], "guide": ["guide", "summary"], "audio": ["audio"]}[command]
        assert parser.parse_args(argv).trace is None, f"{command} has no --trace"
        assert parser.parse_args([*argv, "--trace", "/tmp/x.jsonl"]).trace == "/tmp/x.jsonl"


def test_the_cli_writes_no_trace_unless_one_is_asked_for(monkeypatch, tmp_path):
    """OFF by default, and that is the design rather than caution.

    The API's `traces/` is a bare relative directory resolved against the server's working
    directory and swept by `prune_traces` at startup and after every run — a CLI has neither, so a
    default-on trace would scatter directories into whatever directory the command was invoked
    from and leave files nobody collects. A trace can hold FULL ingested source text (invariant 34).
    """
    seen: dict = {}
    cli = _audio_cli(monkeypatch, seen)
    monkeypatch.chdir(tmp_path)
    args = cli.build_parser().parse_args(["audio", "--out", str(tmp_path / "a.mp3")])
    cli._cmd_audio(args)

    assert seen.get("ran"), "the fake task never ran, so this proves nothing"
    assert not list(tmp_path.rglob("*.jsonl")), "a trace was written without being asked for"
    assert not (tmp_path / "traces").exists(), "a traces/ directory was scattered into the cwd"


def test_a_requested_trace_records_the_run_and_what_it_was_configured_with(monkeypatch, tmp_path):
    """The path the caller named is the path that gets written — no directory of its own choosing."""
    import json

    seen: dict = {}
    cli = _audio_cli(monkeypatch, seen)
    out = tmp_path / "nested" / "run.jsonl"
    out.parent.mkdir()
    args = cli.build_parser().parse_args(
        ["audio", "--length", "long", "--out", str(tmp_path / "a.mp3"), "--trace", str(out)]
    )
    cli._cmd_audio(args)

    events = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    start = next(e for e in events if e.get("type") == "run_start")
    meta = start["payload"]["meta"]
    assert meta["task"] == "test_cli:_FakeTask", (
        "the task is read off the object that actually RAN, not off a hardcoded name — which is "
        f"why the fake shows up here: {meta['task']}"
    )
    assert meta["target_length"] == "long", "the run's own inputs are what make a trace worth reading"
    assert meta["source_chars"] > 0
    # Same contract as the worker's traces: the corpus SIZE, never its text, and no credentials.
    assert "sources" not in meta and "api_key" not in meta and "base_url" not in meta


def test_an_unwritable_trace_path_fails_before_the_model_runs(monkeypatch, tmp_path):
    """Invariant 19's discipline, which is also why `_cmd_audio` resolves its TTS provider first: a
    knowable configuration mistake must not surface after a real model call has been paid for.

    A MISSING directory is not that mistake — `TraceRecorder.__enter__` calls `os.makedirs(...,
    exist_ok=True)`, so `--trace new/dir/run.jsonl` creates the path rather than failing, which a
    first version of this test assumed the opposite of. Genuinely unwritable is what this covers:
    here, a parent that is a regular file.
    """
    import pytest

    seen: dict = {}
    cli = _audio_cli(monkeypatch, seen)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    args = cli.build_parser().parse_args(
        ["audio", "--out", str(tmp_path / "a.mp3"), "--trace", str(blocker / "d.jsonl")]
    )
    with pytest.raises(SystemExit) as excinfo:
        cli._cmd_audio(args)

    assert "cannot write the trace" in str(excinfo.value)
    assert not seen.get("ran"), "the model ran anyway; the whole point is that it must not have"
