"""`tts.py` — `EdgeTTSProvider` and the provider registry, driven with a FAKE `Communicate` factory
so the offline suite never makes a real network call to Microsoft's TTS service (the same
injection-seam pattern `parsers/web.py`'s `fetcher` parameter uses for the SSRF-guarded fetcher).
"""

from __future__ import annotations

import re

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
