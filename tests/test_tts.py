"""`tts.py` — `EdgeTTSProvider` and the provider registry, driven with a FAKE `Communicate` factory
so the offline suite never makes a real network call to Microsoft's TTS service (the same
injection-seam pattern `parsers/web.py`'s `fetcher` parameter uses for the SSRF-guarded fetcher).
"""

from __future__ import annotations

import re
import tempfile
import wave
from pathlib import Path

import pytest

from rlm_notebook.schema import PodcastScript, Utterance
from rlm_notebook.tts import EdgeTTSProvider, TTSError, get_tts_provider


class _FakeCommunicate:
    """A `.stream()` that yields one canned audio chunk, mirroring edge-tts's chunk shape
    (`{"type": "audio", "data": bytes}` / `{"type": "WordBoundary", ...}`, which real synthesis
    also emits and this provider must filter out)."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def stream(self):
        yield {"type": "WordBoundary", "offset": 0, "duration": 1}  # must be filtered, not audio
        yield {"type": "audio", "data": self._payload}


def _fake_factory(calls: list):
    def factory(text: str, voice: str):
        calls.append((text, voice))
        return _FakeCommunicate(f"<audio for {text!r} in {voice!r}>".encode())

    return factory


def _fake_chatterbox_deps(monkeypatch, np):
    """Inject fake `soundfile` and `chatterbox.mtl_tts` modules.

    Both ship ONLY in the `chatterbox` extra, which CI does not sync — an independent audit
    previously caught a test whose docstring claimed it ran without the extra while it actually
    SKIPPED. Faking them keeps the assertion honest on a bare install. `soundfile` writes a real WAV
    through the stdlib so the file the test reads back is genuine; `chatterbox.mtl_tts` only has to
    EXIST, since `_model_factory` is monkeypatched and the provider's import is a guard whose job is
    to fail early with an actionable message.
    """
    import sys
    import types

    def _write(path, samples, rate):
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes((np.asarray(samples) * 32767).astype("<i2").tobytes())

    sound = types.ModuleType("soundfile")
    sound.write = _write
    monkeypatch.setitem(sys.modules, "soundfile", sound)

    # `torch` too: its ONLY root in this dependency graph is `chatterbox-tts`, so on a CI install
    # (`uv sync --extra api`) it is simply absent and `synthesize`'s import guard turns this test
    # into a TTSError. An independent review caught that with a meta-path blocker, after the
    # docstring above already claimed the test ran without the extra.
    torch = types.ModuleType("torch")
    backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False))
    torch.backends = backends
    monkeypatch.setitem(sys.modules, "torch", torch)

    package = types.ModuleType("chatterbox")
    mtl = types.ModuleType("chatterbox.mtl_tts")
    mtl.ChatterboxMultilingualTTS = object
    package.mtl_tts = mtl
    monkeypatch.setitem(sys.modules, "chatterbox", package)
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", mtl)


def _wav(np, samples: int, value: float = 0.25):
    """A stand-in for the torch tensor `model.generate` returns — only the three methods the
    provider actually calls."""

    class _Wav:
        def __init__(self, array):
            self._a = array

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self._a

    return _Wav(np.full(samples, value, dtype="float32"))


def _script(*, speakers_texts) -> PodcastScript:
    return PodcastScript(utterances=[Utterance(speaker=s, text=t) for s, t in speakers_texts])


def test_synthesize_concatenates_per_utterance_audio(tmp_path):
    calls: list = []
    provider = EdgeTTSProvider(_communicate_factory=_fake_factory(calls))
    script = _script(speakers_texts=[("host_a", "hello"), ("host_b", "hi there")])
    out = tmp_path / "episode.mp3"

    provider.synthesize(script, {"host_a": "voice-a", "host_b": "voice-b"}, out)

    assert out.exists()
    audio = out.read_bytes()
    assert b"<audio for 'hello' in 'voice-a'>" in audio
    assert b"<audio for 'hi there' in 'voice-b'>" in audio
    # Concatenated in utterance order, not interleaved or reordered.
    assert audio.index(b"'hello'") < audio.index(b"'hi there'")
    assert calls == [("hello", "voice-a"), ("hi there", "voice-b")]


def test_synthesize_filters_non_audio_chunks(tmp_path):
    provider = EdgeTTSProvider(_communicate_factory=_fake_factory([]))
    script = _script(speakers_texts=[("host_a", "hello")])
    out = tmp_path / "episode.mp3"

    provider.synthesize(script, {"host_a": "voice-a"}, out)

    # Only the "audio"-type chunk's bytes end up in the file — the WordBoundary chunk is metadata,
    # not audio, and must not be written.
    assert out.read_bytes() == b"<audio for 'hello' in 'voice-a'>"


def test_synthesize_raises_on_empty_script(tmp_path):
    provider = EdgeTTSProvider(_communicate_factory=_fake_factory([]))
    with pytest.raises(TTSError, match="no utterances"):
        provider.synthesize(PodcastScript(utterances=[]), {}, tmp_path / "x.mp3")


def test_synthesize_raises_on_missing_voice(tmp_path):
    provider = EdgeTTSProvider(_communicate_factory=_fake_factory([]))
    script = _script(speakers_texts=[("host_a", "hello")])
    with pytest.raises(TTSError, match="no voice configured"):
        provider.synthesize(script, {"host_b": "voice-b"}, tmp_path / "x.mp3")


def test_synthesize_raises_tts_error_not_a_raw_oserror_when_out_dir_is_missing(tmp_path):
    """Found by an independent review: `out_path.write_bytes(...)` used to sit OUTSIDE the
    try/except, so a bad `--out` path (most commonly a nonexistent parent directory) raised an
    uncaught `FileNotFoundError` after synthesis had already succeeded — reproduced with a REAL
    network call to edge-tts before this fix, not just this fake-factory test. Synthesis and the
    write are one "make this file exist" operation as far as the caller is concerned."""
    provider = EdgeTTSProvider(_communicate_factory=_fake_factory([]))
    script = _script(speakers_texts=[("host_a", "hello")])
    missing_dir_path = tmp_path / "does" / "not" / "exist" / "episode.mp3"
    with pytest.raises(TTSError, match="synthesis failed"):
        provider.synthesize(script, {"host_a": "voice-a"}, missing_dir_path)
    assert not missing_dir_path.exists()


def test_synthesize_wraps_an_unexpected_exception_as_tts_error(tmp_path):
    def _boom(text, voice):
        raise RuntimeError("network exploded")

    provider = EdgeTTSProvider(_communicate_factory=_boom)
    script = _script(speakers_texts=[("host_a", "hello")])
    with pytest.raises(TTSError, match="network exploded"):
        provider.synthesize(script, {"host_a": "voice-a"}, tmp_path / "x.mp3")


def test_get_tts_provider_returns_edge_tts_by_default():
    assert isinstance(get_tts_provider("edge-tts"), EdgeTTSProvider)


def test_get_tts_provider_raises_on_unknown_name():
    with pytest.raises(TTSError, match="unknown TTS provider"):
        get_tts_provider("not-a-real-provider")


# --- language-aware default voices ------------------------------------------------------------


def test_default_voices_cover_the_common_language_spellings():
    """The language arrives either as a model-authored NAME ("Traditional Chinese") or as whatever
    an operator typed into RN_OUTPUT_LANGUAGE ("zh-TW"), so matching is loose on purpose."""
    from rlm_notebook.tts import default_voices_for

    assert default_voices_for("Traditional Chinese") == default_voices_for("zh-TW")
    assert default_voices_for("Japanese")[0].startswith("ja-JP-")
    assert default_voices_for("  traditional   chinese  ") == default_voices_for("Traditional Chinese")
    # a BCP-47 tag falls back to its primary subtag rather than finding nothing
    assert default_voices_for("pt-PT") == default_voices_for("Portuguese")


def test_an_unknown_language_keeps_the_configured_voices():
    """A wrong-language voice is bad; silently substituting one for a language nobody asked for is
    worse. Unknown means "no opinion", and the configured defaults stand."""
    from rlm_notebook.tts import default_voices_for

    assert default_voices_for("Klingon") is None
    assert default_voices_for(None) is None
    assert default_voices_for("") is None


def test_every_mapped_voice_id_is_shaped_like_a_real_edge_tts_voice():
    """Every id in the table was read out of a real `edge_tts.list_voices()` response rather than
    written from memory — a plausible-looking but nonexistent voice fails only at synthesis time,
    after a real model call has already been spent on the script."""
    from rlm_notebook.tts import _LANGUAGE_VOICES

    for language, (host_a, host_b) in _LANGUAGE_VOICES.items():
        for voice in (host_a, host_b):
            assert re.fullmatch(r"[a-z]{2}-[A-Z]{2}-\w+Neural", voice), (language, voice)


def test_an_explicit_env_voice_beats_the_language_default(monkeypatch):
    """An operator who set a voice meant it, whatever language the notebook resolved to. Read from
    the RAW env, not by comparing against the default value: setting RN_TTS_VOICE_HOST_A to the
    en-US default on a Chinese notebook is a choice, and an equality check would overrule it."""
    from rlm_notebook.config import NotebookConfig, tts_voice_map

    config = NotebookConfig(main_model="x")
    monkeypatch.delenv("RN_TTS_VOICE_HOST_A", raising=False)
    monkeypatch.delenv("RN_TTS_VOICE_HOST_B", raising=False)
    assert tts_voice_map(config, "Traditional Chinese")["host_a"].startswith("zh-TW-")

    monkeypatch.setenv("RN_TTS_VOICE_HOST_A", "en-US-GuyNeural")
    resolved = tts_voice_map(config, "Traditional Chinese")
    assert resolved["host_a"] == "en-US-GuyNeural", "an explicit choice was overruled"
    assert resolved["host_b"].startswith("zh-TW-"), "the un-set voice should still follow the language"


def test_no_language_falls_back_to_the_shipped_cast(monkeypatch):
    from rlm_notebook.config import NotebookConfig, tts_voice_map

    monkeypatch.delenv("RN_TTS_VOICE_HOST_A", raising=False)
    monkeypatch.delenv("RN_TTS_VOICE_HOST_B", raising=False)
    config = NotebookConfig(main_model="x")
    assert tts_voice_map(config, None) == {
        "host_a": config.tts_voice_host_a,
        "host_b": config.tts_voice_host_b,
    }


# --- provider-owned format and voices -----------------------------------------------------------


def test_each_provider_declares_its_own_format_and_voices():
    """A voice NAME is provider-specific — edge-tts wants `zh-TW-YunJheNeural`, chatterbox wants one
    of its shipped reference-clip names — so the cast lives on the provider. Keeping it there is
    what stops one provider's names leaking into another's request. The FORMAT is on the provider
    for the same reason: chatterbox emits WAV, and forcing it through an MP3 encoder would drag in
    the ffmpeg/pydub dependency invariant 17 deliberately refused.

    The two providers answer `default_voices` DIFFERENTLY on purpose, and that is the shape worth
    pinning: edge-tts has a cast per language, chatterbox is cross-lingual and has none — one pair
    of cloned voices speaks everything, so it returns `None` and hands the default to
    `fallback_voices`."""
    from rlm_notebook.tts import get_tts_provider

    edge, chatterbox = get_tts_provider("edge-tts"), get_tts_provider("chatterbox")

    assert (edge.suffix, edge.media_type) == (".mp3", "audio/mpeg")
    assert (chatterbox.suffix, chatterbox.media_type) == (".wav", "audio/wav")

    assert edge.default_voices("Traditional Chinese")[0].startswith("zh-TW-")
    assert chatterbox.default_voices("Traditional Chinese") is None
    assert chatterbox.default_voices("Klingon") is None
    assert chatterbox.fallback_voices() == ("host-a", "host-b")


def test_chatterbox_is_registered_but_never_imported_by_default():
    """The extra is optional, so importing this package must not pull in torch. Registering the
    class is free; only `synthesize` imports anything.

    Checked by re-importing `rlm_notebook.tts` in a SUBPROCESS: an independent review mutation-
    proved the previous in-process version vacuous — it asserted a disjunction
    (`"torch" not in sys.modules or "chatterbox" not in sys.modules`) that a module-scope
    `import torch` in `tts.py` still satisfied, and in this process both are already imported by
    other tests anyway.
    """
    import subprocess
    import sys

    from rlm_notebook.tts import _PROVIDERS, get_tts_provider

    assert "chatterbox" in _PROVIDERS
    get_tts_provider("chatterbox")  # constructing it must also be free

    probe = (
        "import sys, rlm_notebook.tts as t;"
        "t.get_tts_provider('chatterbox');"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'torch','chatterbox','soundfile','librosa','transformers'}))"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]", out.stdout


def test_the_shipped_reference_clips_exist_and_are_what_the_model_will_read():
    """Two distinguishable hosts depend on these files being INSIDE the installed package —
    chatterbox has exactly one built-in voice, so without them both hosts sound identical. They live
    under `rlm_notebook/` for the same packaging reason the web assets do (invariant 29): a
    top-level directory has no entry in pyproject's wheel `packages` and would silently vanish.

    Also pins the ten-second trim: past `DEC_COND_LEN` (10s at 24kHz) only the speaker encoder reads
    the clip, so longer files would cost wheel size and buy nothing.
    """

    from rlm_notebook.tts import BUILTIN_VOICE, shipped_voice_path

    assert shipped_voice_path(BUILTIN_VOICE) is None
    for name in ("host-a", "host-b"):
        path = shipped_voice_path(name)
        assert path.is_file(), path
        with wave.open(str(path)) as handle:
            seconds = handle.getnframes() / handle.getframerate()
            assert handle.getframerate() == 24_000
            assert 5.0 < seconds <= 10.0, (name, seconds)

    # A typo must NOT quietly fall back to the built-in voice: that would give both hosts the same
    # voice with nothing saying why.
    with pytest.raises(TTSError):
        shipped_voice_path("host-c")
    # Nor may a relative path reach the filesystem.
    with pytest.raises(TTSError):
        shipped_voice_path("../../etc/passwd")


def test_expected_seconds_is_calibrated_against_real_measured_utterances():
    """`expected_seconds` is the ceiling a runaway is measured against, so a detuned estimate either
    lets a loop through or rejects correct takes. These four durations are REAL chatterbox output
    measured on Apple Silicon, and the estimate must stay within 15% of each — the first draft used
    15 chars/second for Latin, which under-estimated the English line by a third."""
    from rlm_notebook.tts import expected_seconds

    measured = [
        ("這兩艘探測器叫做 Voyager 1 和 Voyager 2，是 NASA 在一九七七年發射的。", 7.16),
        ("對，而且很多人以為航海家一號是先發射的那艘，其實順序有點反直覺。", 6.04),
        ("Voyager 1 was launched by NASA in 1977 and is still returning data.", 6.96),
        ("ボイジャー1号は NASA が1977年に打ち上げた探査機です。", 5.08),
    ]
    for text, actual in measured:
        assert 0.85 <= expected_seconds(text) / actual <= 1.15, (text[:20], expected_seconds(text))

    # And the reproduced 34.8s runaway on the first line must be over the ceiling.
    from rlm_notebook.tts import ChatterboxProvider

    assert 34.8 > expected_seconds(measured[0][0]) * ChatterboxProvider._RUNAWAY_FACTOR
    assert expected_seconds("") >= 1.0  # a floor, so a short line cannot give a near-zero ceiling


def test_finding_audio_survives_a_provider_switch(tmp_path):
    """An episode generated by edge-tts must keep playing after someone switches RN_TTS_PROVIDER to
    chatterbox — so the reader looks for whichever format is present, and a regenerate clears
    every format rather than leaving the stale one beside the new one."""
    from rlm_notebook.notebook import audio_path, clear_audio, find_audio

    mp3 = audio_path("nb", base_dir=tmp_path, suffix=".mp3")
    mp3.parent.mkdir(parents=True, exist_ok=True)
    mp3.write_bytes(b"old-mp3")
    assert find_audio("nb", base_dir=tmp_path) == mp3

    clear_audio("nb", base_dir=tmp_path)
    assert find_audio("nb", base_dir=tmp_path) is None

    wav = audio_path("nb", base_dir=tmp_path, suffix=".wav")
    wav.write_bytes(b"new-wav")
    assert find_audio("nb", base_dir=tmp_path) == wav


def test_offsets_come_from_any_boundary_event_and_track_each_utterance_separately():
    """Two regressions in one, because the fixture has to be shaped for both.

    (1) The first version keyed on `WordBoundary`; the installed edge-tts defaults to
    `boundary="SentenceBoundary"` and emits only that, so every offset came back 0.0 — a transcript
    that highlights nothing and seeks nowhere. Caught by generating a real episode and READING the
    numbers, not by them being obviously absent.

    (2) An independent review then found this test could not catch a per-utterance state bug,
    because its first fixture gave every utterance the SAME duration: hoisting `end_ticks = 0` out
    of the per-utterance loop (making it a running maximum) left all 18 tts tests green. Hence
    THREE DIFFERENT durations here — with equal ones, `[0, 5, 7]` and `[0, 5, 10]` are
    indistinguishable.
    """

    #: Seconds per utterance text, deliberately all different.
    durations = {"one": 5.0, "two": 2.0, "three": 8.0}

    class _Sentence:
        """Emits what the real service emits: audio plus one SentenceBoundary, in 100ns ticks."""

        def __init__(self, text, voice):
            self._ticks = int(durations[text] * 10_000_000)

        async def stream(self):
            yield {"type": "audio", "data": b"\x00" * 16}
            yield {"type": "SentenceBoundary", "offset": 0, "duration": self._ticks}

    provider = EdgeTTSProvider(_communicate_factory=_Sentence)
    script = _script(speakers_texts=[("host_a", "one"), ("host_b", "two"), ("host_a", "three")])

    with tempfile.TemporaryDirectory() as tmp:
        offsets = provider.synthesize(script, {"host_a": "x", "host_b": "y"}, Path(tmp) / "out.mp3")

    assert offsets == [0.0, 5.0, 7.0], offsets


def test_no_boundary_events_degrades_to_flat_offsets_rather_than_raising():
    """A provider that reports no timing must still produce audio. Note what this pins and what it
    does NOT: the offsets come back the RIGHT LENGTH and all zero, so a length check cannot catch
    them — rejecting them is the consumer's job, and `app.js`'s `timed` requires the offsets to
    strictly increase for exactly this reason (`tts.py`'s docstring used to claim a length check
    handled it, which an independent review disproved)."""

    class _Silent:
        def __init__(self, text, voice):
            pass

        async def stream(self):
            yield {"type": "audio", "data": b"\x00" * 8}

    script = _script(speakers_texts=[("host_a", "x"), ("host_a", "y")])
    with tempfile.TemporaryDirectory() as tmp:
        offsets = EdgeTTSProvider(_communicate_factory=_Silent).synthesize(
            script, {"host_a": "v"}, Path(tmp) / "o.mp3"
        )
    assert offsets == [0.0, 0.0]
    assert not all(offsets[i] < offsets[i + 1] for i in range(len(offsets) - 1))


def test_sequence_offsets_charges_the_inter_utterance_gap_to_the_previous_line():
    """Invariant 44 says the gap is added BEFORE the offset is recorded, so a click lands at
    the start of its own line rather than inside the preceding silence. An independent review
    verified that by hand and flagged that NOTHING in CI checked it — hence a pure function to
    check, needing no local-TTS extra, no model download and no audio.

    (`ChatterboxProvider` is the provider now; the rule predates it and is unchanged.)

    Durations are deliberately all different: with equal ones a running-total bug and a correct
    implementation produce the same list.
    """
    from rlm_notebook.tts import sequence_offsets

    rate, gap = 24_000, 8_400  # 0.35s at 24kHz, KokoroProvider's own gap
    lengths = [24_000, 48_000, 12_000]  # 1.0s, 2.0s, 0.5s

    assert sequence_offsets(lengths, gap, rate) == [0.0, 1.35, 3.7]
    # No gap before the first line or after the last: the total is the sum plus N-1 gaps.
    total = (sum(lengths) + gap * (len(lengths) - 1)) / rate
    assert total == pytest.approx(sequence_offsets(lengths, gap, rate)[-1] + 0.5)
    # Degenerate shapes stay sane rather than raising.
    assert sequence_offsets([], gap, rate) == []
    assert sequence_offsets([24_000], gap, rate) == [0.0]


def test_chatterbox_provider_offsets_and_runaway_guard(tmp_path, monkeypatch):
    """The provider end of invariant 44's gap-before-offset rule, plus the runaway retry that only
    exists because the decoder was measured looping: the same Traditional Chinese sentence came back
    at 34.80s / 5.48s / 11.68s across three runs against an expected ~7s.

    Driven with a FAKE model injected through `_model_factory`, so this runs on a CI install with
    neither the `chatterbox` extra nor a model download. `soundfile` is faked through `sys.modules`
    for the same reason (it ships only in the extra).
    """
    np = pytest.importorskip("numpy")

    from rlm_notebook.tts import ChatterboxProvider, sequence_offsets

    rate = 24_000
    seconds = {"one": 1.0, "two": 2.0, "three": 0.5}

    class _FakeModel:
        sr = rate

        def __init__(self):
            self.conds = None
            self.prepared: list = []
            self.calls: list = []

        def prepare_conditionals(self, path):
            self.prepared.append(path)
            self.conds = f"conds-for-{Path(path).stem}"

        def generate(self, text, language_id=None):
            self.calls.append((text, language_id, self.conds))
            n = int(seconds[text] * rate)
            return _FakeWav(np.full(n, 0.25, dtype="float32"))

    class _FakeWav:
        def __init__(self, array):
            self._a = array

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self._a

    model = _FakeModel()
    monkeypatch.setattr(ChatterboxProvider, "_model_factory", staticmethod(lambda device: model))
    _fake_chatterbox_deps(monkeypatch, np)

    script = _script(speakers_texts=[("host_a", "one"), ("host_b", "two"), ("host_a", "three")])
    out = tmp_path / "episode.wav"
    provider = ChatterboxProvider()
    offsets = provider.synthesize(
        script, {"host_a": "host-a", "host_b": "host-b"}, out, language="Traditional Chinese"
    )

    gap = int(ChatterboxProvider._GAP_SECONDS * rate)
    # Ordered by the SCRIPT, not by the `seconds` dict — matching only by how the literal happens
    # to be written is the kind of coincidence a later edit silently breaks.
    spoken = [u.speaker and t for u, t in zip(script.utterances, ["one", "two", "three"])]
    assert offsets == sequence_offsets([int(seconds[t] * rate) for t in spoken], gap, rate)
    # Each speaker's conditioning is prepared ONCE, not per utterance — `prepare_conditionals` runs
    # the voice encoder over the whole clip, so re-running it per line would pay that every turn.
    assert len(model.prepared) == 2
    assert [c[1] for c in model.calls] == ["zh", "zh", "zh"]
    # ...and the right host's conditioning was in place for each line.
    assert [c[2] for c in model.calls] == ["conds-for-host_a", "conds-for-host_b", "conds-for-host_a"]


def test_a_builtin_voice_mixed_with_a_clip_keeps_the_two_hosts_apart(tmp_path, monkeypatch):
    """The built-in voice exists ONLY as `model.conds`, and the first `prepare_conditionals`
    overwrites it — so it has to be captured before the prep loop.

    An independent review reproduced what happens otherwise: a mixed map left the built-in speaker
    with nothing to assign, so it inherited whichever clip was prepared last and BOTH hosts came out
    in one voice. That is the monologue-in-two-halves the shipped clips exist to prevent, it fails
    silently, and it only shows up after ~15 minutes of synthesis. Reachable from a configuration
    both `.env.example` and `voices/README.md` document.
    """
    np = pytest.importorskip("numpy")

    from rlm_notebook.tts import ChatterboxProvider

    class _Model:
        sr = 24_000

        def __init__(self):
            # What `from_local` leaves behind: the checkpoint's single built-in conditioning.
            self.conds = "built-in-conds"
            self.spoken: list = []

        def prepare_conditionals(self, path):
            # The real one ASSIGNS a fresh object rather than mutating in place.
            self.conds = f"clone-of-{Path(path).stem}"

        def generate(self, text, language_id=None):
            self.spoken.append((text, self.conds))
            return _wav(np, int(1.0 * self.sr))

    script = _script(speakers_texts=[("host_a", "one"), ("host_b", "two"), ("host_a", "three")])

    for voice_map, expected in (
        ({"host_a": "built-in", "host_b": "host-b"},
         ["built-in-conds", "clone-of-host_b", "built-in-conds"]),
        ({"host_a": "host-a", "host_b": "built-in"},
         ["clone-of-host_a", "built-in-conds", "clone-of-host_a"]),
        ({"host_a": "built-in", "host_b": "built-in"},
         ["built-in-conds", "built-in-conds", "built-in-conds"]),
    ):
        model = _Model()
        monkeypatch.setattr(
            ChatterboxProvider, "_model_factory", staticmethod(lambda d, m=model: m)
        )
        _fake_chatterbox_deps(monkeypatch, np)
        ChatterboxProvider().synthesize(
            script, voice_map, tmp_path / "e.wav", language="English"
        )
        assert [c for _, c in model.spoken] == expected, voice_map


def test_chatterbox_retries_a_runaway_take_and_keeps_the_shortest_if_it_never_converges(
    tmp_path, monkeypatch
):
    """A run that never converges must not RAISE: a slightly wrong line is a far better outcome for
    a paid-for episode than losing the whole thing (invariants 19 and 37's "never lose what already
    succeeded"). And a take within the ceiling must be accepted on the FIRST try, or every episode
    would pay three slow generations per line."""
    np = pytest.importorskip("numpy")

    from rlm_notebook.tts import ChatterboxProvider, expected_seconds

    rate = 24_000
    text = "Voyager 1 was launched by NASA in 1977 and is still returning data."
    ceiling = expected_seconds(text) * ChatterboxProvider._RUNAWAY_FACTOR

    class _Wav:
        def __init__(self, a):
            self._a = a

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self._a

    class _Runaway:
        sr = rate

        def __init__(self, lengths):
            self.lengths = list(lengths)
            self.calls = 0

        def generate(self, text, language_id=None):
            self.calls += 1
            return _Wav(np.zeros(int(self.lengths.pop(0) * rate), dtype="float32"))

    provider = ChatterboxProvider()

    # Converges on the second attempt: one re-roll, then accepted.
    model = _Runaway([ceiling * 3, ceiling * 0.8])
    audio = provider._generate_one(model, text, "en", rate, np)
    assert model.calls == 2
    assert len(audio) / rate <= ceiling

    # Never converges: keeps the SHORTEST take rather than raising, and stops at _MAX_ATTEMPTS.
    model = _Runaway([ceiling * 5, ceiling * 3, ceiling * 4])
    audio = provider._generate_one(model, text, "en", rate, np)
    assert model.calls == ChatterboxProvider._MAX_ATTEMPTS
    assert len(audio) / rate == pytest.approx(ceiling * 3, rel=0.01)

    # A good first take costs exactly one generation.
    model = _Runaway([ceiling * 0.5])
    provider._generate_one(model, text, "en", rate, np)
    assert model.calls == 1


def test_chatterbox_refuses_a_language_it_has_no_id_for(tmp_path, monkeypatch):
    """Synthesizing Korean with `language_id="en"` produces confident nonsense, so an unknown
    language fails loudly BEFORE any audio is written rather than guessing."""
    from rlm_notebook.tts import ChatterboxProvider

    with pytest.raises(TTSError) as excinfo:
        ChatterboxProvider._language_id("Klingon")
    assert "Klingon" in str(excinfo.value)
    for language, expected in (
        ("Traditional Chinese", "zh"),
        ("Simplified Chinese", "zh"),
        ("English", "en"),
        ("Japanese", "ja"),
        ("Korean", "ko"),
        ("zh-TW", "zh"),
        (None, "en"),
    ):
        assert ChatterboxProvider._language_id(language) == expected


def test_an_unknown_language_falls_back_to_the_providers_own_cast_not_another_providers(
    monkeypatch, tmp_path
):
    """An independent audit found the language MAP had moved onto the provider (invariant 43) while
    the LAST RESORT had not: the local provider plus an unknown language fell straight through to
    `config`'s shipped `en-US-GuyNeural`, an edge-tts name handed to a local model — a synthesis
    failure after a real model call had already been spent, the waste invariant 19 exists to
    prevent. Pinned for BOTH providers so neither can regain the other's names."""
    from rlm_notebook.config import NotebookConfig, tts_voice_map
    from rlm_notebook.tts import ChatterboxProvider

    monkeypatch.setenv("RN_NOTEBOOKS_DIR", str(tmp_path))
    for name in ("RN_TTS_VOICE_HOST_A", "RN_TTS_VOICE_HOST_B"):
        monkeypatch.delenv(name, raising=False)
    config = NotebookConfig(main_model="m", sub_model="m")

    # Chatterbox is cross-lingual and has NO per-language cast, so every language lands on its
    # fallback — which must be its own shipped clips, never edge-tts's `en-US-GuyNeural`.
    for language in ("Klingon", "Traditional Chinese", "Korean", None):
        cast = tts_voice_map(config, language, ChatterboxProvider())
        assert set(cast.values()) == {"host-a", "host-b"}, language
        assert not any("Neural" in voice for voice in cast.values())

    edge = tts_voice_map(config, "Klingon", EdgeTTSProvider())
    assert all(voice.endswith("Neural") for voice in edge.values())
    # A language edge-tts DOES know still wins over its own fallback.
    assert tts_voice_map(config, "Korean", EdgeTTSProvider())["host_b"].startswith("ko-KR-")


def test_the_settings_voice_pattern_accepts_both_providers_naming_schemes():
    """One edge-tts-shaped pattern rejected every local-provider voice, so the settings page could not
    name a voice for the provider a user had actually configured. Widening the SHAPES is not
    widening the CHARACTERS — the SSML hole invariant 41 closed stays closed."""
    from rlm_notebook.config import _VOICE_PATTERN

    for voice in ("zh-TW-YunJheNeural", "en-US-GuyNeural", "host-a", "host-b", "built-in"):
        assert _VOICE_PATTERN.match(voice), voice
    for bad in (
        "en-US-x'/><audio src=\"http://evil/x.mp3\"/><a b='Neural",
        "host a",
        "Host-A",
        "host-a<script>",
        "",
        # A PATH must be unreachable from the settings file even though chatterbox accepts one from
        # the ENVIRONMENT — otherwise this becomes an arbitrary-file-read surface on an
        # unauthenticated endpoint (invariants 26 and 41).
        "/etc/passwd",
        "../../etc/passwd",
        "ref.wav",
    ):
        assert not _VOICE_PATTERN.match(bad), bad


def test_chatterbox_validates_language_and_voices_before_anything_expensive_runs():
    """Invariant 19's discipline, one level deeper than the provider NAME.

    An independent review found both of chatterbox's own checks living inside `synthesize`, i.e.
    after the full script-generation run: on a language it has no id for — Thai and Vietnamese are
    in edge-tts's map but not in `_CHATTERBOX_LANGUAGES` — every `/audio` request burned a whole
    RLM run and could never succeed.
    """
    from rlm_notebook.tts import ChatterboxProvider, EdgeTTSProvider

    provider = ChatterboxProvider()
    cast = {"host_a": "host-a", "host_b": "host-b"}

    provider.validate("Traditional Chinese", cast)  # a supported language passes
    provider.validate(None, cast)  # unset means English, which is supported

    with pytest.raises(TTSError, match="Thai"):
        provider.validate("Thai", cast)
    with pytest.raises(TTSError, match="host-c"):
        provider.validate("English", {"host_a": "host-c", "host_b": "host-b"})
    # A stale edge-tts voice left in the settings file after switching providers is caught here,
    # not fifteen minutes into a synthesis.
    with pytest.raises(TTSError):
        provider.validate("English", {"host_a": "zh-TW-YunJheNeural", "host_b": "host-b"})

    # edge-tts has nothing to pre-flight and must not invent a reason to fail.
    EdgeTTSProvider().validate("Thai", {"host_a": "zz-ZZ-NobodyNeural"})


def test_both_audio_entry_points_validate_before_running_the_model():
    """A source-tree assertion, because the ordering is the whole point and neither call site has a
    seam to observe it through: `provider.validate(...)` must appear BEFORE the
    `GeneratePodcastScript` run in `cli.py`, and before `_run_isolated` in `api.py`."""
    # Anchored to THIS file, not the cwd — `tests/test_web_assets.py` already learned that lesson.
    root = Path(__file__).resolve().parent.parent / "rlm_notebook"

    cli = (root / "cli.py").read_text()
    # Anchored on the CONSTRUCTION, not on `().run(`: the run moved inside a `_traced(...)` block
    # when `--trace` was added, and an assertion keyed on the old spelling would have gone looking
    # for a substring that no longer exists rather than checking the ordering it names.
    assert cli.index("provider.validate(") < cli.index("GeneratePodcastScript()")

    api = (root / "api.py").read_text()
    audio = api[api.index("async def audio("):]
    # `await _run_isolated(`, not just the name: `audio`'s own docstring mentions `_run_isolated`
    # several paragraphs before either line of code, which made a first draft of this assertion
    # fail against correct source.
    assert audio.index("provider.validate(") < audio.index("await _run_isolated(")



def test_the_voices_never_read_a_corpus_marker_aloud():
    """The transcript was already clean — the API strips markers on the way out (invariant 62) —
    but synthesis reads the script OBJECT, so it had its own copy of the problem: a real run wrote
    markers into 19 of 47 utterances and the episode said "S R C S one" out loud.

    Applied once at the boundary rather than inside each provider: there are two implementations and
    a third would silently ship without it.
    """
    from rlm_notebook.schema import PodcastScript, Utterance
    from rlm_notebook.tts import spoken_script

    script = PodcastScript(
        utterances=[
            Utterance(speaker="host_a", text="Trinity coordinates models [[SRC:s1|whole]]."),
            Utterance(speaker="host_b", text="No marker here."),
        ]
    )
    spoken = spoken_script(script)

    assert "[[SRC:" not in " ".join(u.text for u in spoken.utterances)
    assert spoken.utterances[0].text == "Trinity coordinates models."
    # The gap the marker leaves is closed: a TTS voice pauses at "models ." otherwise.
    assert " ." not in spoken.utterances[0].text
    # COUNT and ORDER untouched, or the offsets invariant 44 defines stop lining up with the
    # transcript the reader sees.
    assert len(spoken.utterances) == len(script.utterances)
    assert [u.speaker for u in spoken.utterances] == [u.speaker for u in script.utterances]
    # And the stored script is not mutated — what the model produced stays what it produced.
    assert "[[SRC:" in script.utterances[0].text


def test_both_entry_points_synthesize_the_stripped_script():
    """A source-tree assertion: there are two call sites and no runtime seam that would notice one
    of them passing the raw script — the audio would simply speak the marker, as it did."""
    import re as _re

    for module in ("api", "cli"):
        # Resolved from THIS file: the suite chdirs into a tmp dir (conftest's isolation
        # fixture), so a relative path finds nothing.
        root = Path(__file__).resolve().parent.parent / "rlm_notebook"
        source = (root / f"{module}.py").read_text(encoding="utf-8")
        calls = _re.findall(r"provider\.synthesize[,(]\s*([^,)]+)", source)
        assert calls, f"the extraction no longer sees {module}'s synthesize call"
        for arg in calls:
            assert arg.strip().startswith("spoken_script("), (
                f"{module}.py synthesizes a raw script, so the voices read the markers aloud"
            )


def test_stripping_a_marker_only_line_does_not_lose_the_episode():
    """The net must not be able to destroy what it was protecting. A line that is NOTHING but a
    coordinate strips to `""` or a lone piece of punctuation, and `EdgeTTSProvider` raises
    `NoAudioReceived` for punctuation-only text (this module's own docstring records that, verified
    live) — which becomes a 502 and discards the whole paid-for RLM run.

    A garbled line ships; a 502 does not. Same discipline as invariants 19/37/43.
    """
    from rlm_notebook.schema import PodcastScript, Utterance
    from rlm_notebook.tts import spoken_script

    script = PodcastScript(
        utterances=[
            Utterance(speaker="host_a", text="[[SRC:s1|whole]]"),
            Utterance(speaker="host_b", text="[[SRC:s2|whole]]。"),
            Utterance(speaker="host_a", text="Real words [[SRC:s3|whole]]."),
        ]
    )
    spoken = spoken_script(script)
    assert all(any(c.isalnum() for c in u.text) for u in spoken.utterances), (
        "an utterance was left with nothing speakable, which is a TTSError and a lost episode"
    )
    # The line that HAS content still gets its marker removed.
    assert spoken.utterances[2].text == "Real words."
