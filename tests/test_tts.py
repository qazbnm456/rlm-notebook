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
    """A voice NAME is provider-specific — edge-tts wants `zh-TW-YunJheNeural`, Kokoro wants
    `zf_xiaobei` — so the language->voice map lives on the provider. Keeping it there is what stops
    one provider's names leaking into another's request. The FORMAT is on the provider for the same
    reason: Kokoro emits WAV, and forcing it through an MP3 encoder would drag in the ffmpeg/pydub
    dependency invariant 17 deliberately refused."""
    from rlm_notebook.tts import get_tts_provider

    edge, kokoro = get_tts_provider("edge-tts"), get_tts_provider("kokoro")

    assert (edge.suffix, edge.media_type) == (".mp3", "audio/mpeg")
    assert (kokoro.suffix, kokoro.media_type) == (".wav", "audio/wav")

    assert edge.default_voices("Traditional Chinese")[0].startswith("zh-TW-")
    assert kokoro.default_voices("Traditional Chinese") == ("zm_yunjian", "zf_xiaobei")
    assert kokoro.default_voices("Klingon") is None


def test_kokoro_is_registered_but_never_imported_by_default():
    """The extra is optional, so `import rlm_notebook.tts` must not pull in torch. Registering the
    class is free; only `synthesize` imports anything."""
    import sys

    from rlm_notebook.tts import _PROVIDERS, get_tts_provider

    assert "kokoro" in _PROVIDERS
    get_tts_provider("kokoro")  # constructing it must also be free
    assert "torch" not in sys.modules or "kokoro" not in sys.modules


def test_finding_audio_survives_a_provider_switch(tmp_path):
    """An episode generated by edge-tts must keep playing after someone switches RN_TTS_PROVIDER to
    kokoro — so the reader looks for whichever format is actually there, and a regenerate clears
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
    """Invariant 44 says kokoro's gap is added BEFORE the offset is recorded, so a click lands at
    the start of its own line rather than inside the preceding silence. An independent review
    verified that by hand and flagged that NOTHING in CI checked it — hence a pure function to
    check, needing no `kokoro` extra, no model download and no audio.

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


def test_kokoro_provider_offsets_come_from_sequence_offsets(tmp_path, monkeypatch):
    """The provider end of the same claim, with FAKE `kokoro` AND `soundfile` modules injected
    through `sys.modules`, so this genuinely runs on a CI install that has neither. Pins that
    `synthesize` returns one offset per utterance, spaced by the gap, and that the written file is
    exactly as long as the last offset plus the last line — which is what a running-total bug
    breaks and an equality assert against `sequence_offsets` alone could not detect."""
    np = pytest.importorskip("numpy")
    import sys
    import types

    from rlm_notebook.tts import KokoroProvider, sequence_offsets

    seconds = {"one": 1.0, "two": 2.0, "three": 0.5}

    class _FakeKPipeline:
        def __init__(self, lang_code="a"):
            self.lang_code = lang_code

        def __call__(self, text, voice=None, **kwargs):
            n = int(seconds[text] * KokoroProvider._SAMPLE_RATE)
            yield ("gs", "ps", np.full(n, 0.25, dtype="float32"))

    module = types.ModuleType("kokoro")
    module.KPipeline = _FakeKPipeline
    monkeypatch.setitem(sys.modules, "kokoro", module)

    # `soundfile` is declared ONLY in the `kokoro` extra, which CI does not sync — an independent
    # audit blocked the module and watched this test SKIP while its docstring claimed it ran without
    # the extra. Faked with the stdlib `wave` writer so the assertion below reads a real WAV header.
    def _write(path, samples, rate):
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes((np.asarray(samples) * 32767).astype("<i2").tobytes())

    sound = types.ModuleType("soundfile")
    sound.write = _write
    monkeypatch.setitem(sys.modules, "soundfile", sound)

    script = _script(speakers_texts=[("host_a", "one"), ("host_b", "two"), ("host_a", "three")])
    out = tmp_path / "episode.wav"
    offsets = KokoroProvider().synthesize(
        script, {"host_a": "zf_xiaoxiao", "host_b": "zm_yunxi"}, out
    )

    rate, gap = KokoroProvider._SAMPLE_RATE, int(KokoroProvider._GAP_SECONDS * 24_000)
    assert offsets == sequence_offsets([int(seconds[t] * rate) for t in seconds], gap, rate)
    assert len(offsets) == len(script.utterances)
    with wave.open(str(out)) as handle:
        total = handle.getnframes() / handle.getframerate()
    assert total == pytest.approx(offsets[-1] + 0.5, abs=0.01)


def test_an_unknown_language_falls_back_to_the_providers_own_cast_not_another_providers(
    monkeypatch, tmp_path
):
    """An independent audit found the language MAP had moved onto the provider (invariant 43) while
    the LAST RESORT had not: kokoro plus a language it does not know fell straight through to
    `config`'s shipped `en-US-GuyNeural`, an edge-tts name handed to `KPipeline` — a synthesis
    failure after a real model call had already been spent, the waste invariant 19 exists to
    prevent. Pinned for BOTH providers so neither can regain the other's names."""
    from rlm_notebook.config import NotebookConfig, tts_voice_map
    from rlm_notebook.tts import KokoroProvider

    monkeypatch.setenv("RN_NOTEBOOKS_DIR", str(tmp_path))
    for name in ("RN_TTS_VOICE_HOST_A", "RN_TTS_VOICE_HOST_B"):
        monkeypatch.delenv(name, raising=False)
    config = NotebookConfig(main_model="m", sub_model="m")

    kokoro = tts_voice_map(config, "Klingon", KokoroProvider())
    assert set(kokoro.values()) == {"am_adam", "af_heart"}
    assert not any("Neural" in voice for voice in kokoro.values())

    edge = tts_voice_map(config, "Klingon", EdgeTTSProvider())
    assert all(voice.endswith("Neural") for voice in edge.values())

    # A language each provider DOES know still wins over its own fallback.
    assert set(tts_voice_map(config, "Chinese", KokoroProvider()).values()) == {
        "zm_yunjian",
        "zf_xiaobei",
    }


def test_the_settings_voice_pattern_accepts_both_providers_naming_schemes():
    """One edge-tts-shaped pattern rejected EVERY kokoro voice id, so the settings page could not
    name a voice for the provider a user had actually configured. Widening the SHAPES is not
    widening the CHARACTERS — the SSML hole invariant 41 closed stays closed."""
    from rlm_notebook.config import _VOICE_PATTERN

    for voice in ("zh-TW-YunJheNeural", "en-US-GuyNeural", "zf_xiaobei", "am_adam"):
        assert _VOICE_PATTERN.match(voice), voice
    for bad in (
        "en-US-x'/><audio src=\"http://evil/x.mp3\"/><a b='Neural",
        "zf xiaobei",
        "ZF_Xiaobei",
        "zf_xiaobei<script>",
        "",
    ):
        assert not _VOICE_PATTERN.match(bad), bad

