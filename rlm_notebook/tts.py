"""Text-to-speech synthesis for the Audio Overview — host-side, provider-abstracted.

CLAUDE.md's Audio Overview invariant: synthesis runs entirely host-side, on an already-generated,
already citation-checked `PodcastScript` (`audio.py`) — never inside the RLM sandbox, and never a
tool the model can call. The provider is selected by `RN_TTS_PROVIDER` (default `"edge-tts"`, a
free service needing no API key) so the tool works with no paid credentials out of the box —
mirroring the OCR default (CLAUDE.md invariant 7): a capability this project's core value
proposition depends on must not be pluggable-but-unusable by default.

Two providers ship. `EdgeTTSProvider` is the default and concatenates raw MP3 streams; `kokoro`
(invariant 43, the `kokoro` extra) is fully local and emits WAV. A provider therefore owns its own
OUTPUT FORMAT and its own language→voice map — a voice name is provider-specific, and forcing a
WAV-emitting model through an MP3 encoder would need the `ffmpeg`/`pydub` dependency invariant 17
deliberately refused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .schema import PodcastScript


class TTSError(RuntimeError):
    """Synthesis failed: a network/provider error, or an unconfigured/unknown voice or provider."""


class TTSProvider(Protocol):
    """Minimal TTS interface: one script in, one audio file out. A provider may internally
    synthesize per-utterance and concatenate (see `EdgeTTSProvider`) or natively generate a whole
    multi-speaker conversation in one call — callers only see "script in, audio file out".

    `suffix`/`media_type` are the provider's, not the caller's: a local model that emits WAV must not
    be forced through an MP3 encoder just because the first provider happened to produce MP3 — that
    would drag in the `ffmpeg`/`pydub` dependency invariant 17 deliberately avoided.

    `default_voices` belongs here too, because a voice NAME is provider-specific: edge-tts wants
    `zh-TW-YunJheNeural` and Kokoro wants `zf_xiaobei`. Keeping the language→voice map on the
    provider is what stops one provider's names leaking into another's request.
    """

    #: File extension and MIME type of what `synthesize` writes.
    suffix: str
    media_type: str

    def synthesize(self, script: PodcastScript, voice_map: dict[str, str], out_path: Path) -> None: ...

    def default_voices(self, language: str | None) -> tuple[str, str] | None: ...


#: A factory `(text, voice) -> an object with an async .stream()` yielding edge-tts-shaped chunks.
#: The production default lazily constructs a real `edge_tts.Communicate`; tests inject a fake one
#: so the offline suite never makes a network call — the same seam shape as `parsers/web.py`'s
#: `fetcher` parameter.
CommunicateFactory = Callable[[str, str], object]


def _default_communicate_factory(text: str, voice: str) -> object:
    import edge_tts

    return edge_tts.Communicate(text, voice)


@dataclass
class EdgeTTSProvider:
    """Default `TTSProvider`: Microsoft Edge's free, no-API-key TTS service via the `edge-tts`
    package. `edge-tts` synthesizes one voice per call, so a multi-speaker script is synthesized
    one utterance at a time and the resulting MP3 byte streams are concatenated — a well-known
    "good enough" trick for MP3 concatenation without re-encoding (most players treat concatenated
    MP3 frames as one continuous stream). Not perfectly gapless; real re-encoding (via `pydub` +
    `ffmpeg`) is a deferred follow-up, not pulled in for this slice to avoid a system-binary
    dependency (`ffmpeg` isn't pip-installable) for a cosmetic improvement.

    **Residual risk, not yet an issue for this slice**: `synthesize()` is a SYNC method that calls
    `asyncio.run(...)` internally. `asyncio.run()` raises `RuntimeError: cannot be called from a
    running event loop` if invoked from inside one — fine for today's synchronous CLI call site
    (`cli._cmd_audio`), but a future caller inside an async context (e.g. a FastAPI async handler,
    the API slice that DID call this routes around it via `asyncio.to_thread` (invariant 29); should any future caller directly rather than off-loading it to a worker
    thread/process) would need to route around this, not call `synthesize()` as-is. Flagging now
    so that future slice doesn't have to rediscover it.
    """

    _communicate_factory: CommunicateFactory = field(default=_default_communicate_factory)

    suffix = ".mp3"
    media_type = "audio/mpeg"

    def default_voices(self, language: str | None) -> tuple[str, str] | None:
        return default_voices_for(language)

    def synthesize(self, script: PodcastScript, voice_map: dict[str, str], out_path: Path) -> None:
        if not script.utterances:
            raise TTSError("script has no utterances to synthesize")
        try:
            audio = asyncio.run(self._synthesize_all(script, voice_map))
            out_path.write_bytes(audio)
        except TTSError:
            raise
        except Exception as exc:
            # Found by an independent review: `out_path.write_bytes(...)` used to sit OUTSIDE this
            # try/except, so a bad `--out` path (a nonexistent parent directory, most commonly —
            # reproduced with a real network synthesis that succeeded and then crashed on the
            # write) raised a raw, uncaught OSError after already spending a real TTS network call.
            # Both the synthesis call and the write are "make this audio file exist" as far as the
            # caller is concerned, so both share one error boundary.
            raise TTSError(f"TTS synthesis failed: {type(exc).__name__}: {exc}") from exc

    async def _synthesize_all(self, script: PodcastScript, voice_map: dict[str, str]) -> bytes:
        chunks: list[bytes] = []
        for utterance in script.utterances:
            voice = voice_map.get(utterance.speaker)
            if not voice:
                raise TTSError(f"no voice configured for speaker {utterance.speaker!r}")
            communicate = self._communicate_factory(utterance.text, voice)
            buf = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.extend(chunk["data"])
            chunks.append(bytes(buf))
        return b"".join(chunks)


#: Language name (or BCP-47 tag) -> a (host_a, host_b) edge-tts voice pair. Every id here was read
#: out of a real `edge_tts.list_voices()` response, not written from memory — a plausible-looking but
#: nonexistent voice fails only at synthesis time, after a real model call has already been spent.
#:
#: Keys are matched loosely (see `default_voices_for`) because the language can arrive either as a
#: model-authored NAME ("Traditional Chinese") or as whatever an operator typed into
#: `RN_OUTPUT_LANGUAGE` ("zh-TW"). An unknown language returns None and the configured defaults
#: stand — a wrong-language voice is bad, but silently substituting a voice for a language nobody
#: asked for is worse.
_LANGUAGE_VOICES: dict[str, tuple[str, str]] = {
    "traditional chinese": ("zh-TW-YunJheNeural", "zh-TW-HsiaoChenNeural"),
    "zh-tw": ("zh-TW-YunJheNeural", "zh-TW-HsiaoChenNeural"),
    "zh-hant": ("zh-TW-YunJheNeural", "zh-TW-HsiaoChenNeural"),
    "simplified chinese": ("zh-CN-YunjianNeural", "zh-CN-XiaoxiaoNeural"),
    "chinese": ("zh-CN-YunjianNeural", "zh-CN-XiaoxiaoNeural"),
    "mandarin": ("zh-CN-YunjianNeural", "zh-CN-XiaoxiaoNeural"),
    "zh-cn": ("zh-CN-YunjianNeural", "zh-CN-XiaoxiaoNeural"),
    "zh": ("zh-CN-YunjianNeural", "zh-CN-XiaoxiaoNeural"),
    "japanese": ("ja-JP-KeitaNeural", "ja-JP-NanamiNeural"),
    "ja": ("ja-JP-KeitaNeural", "ja-JP-NanamiNeural"),
    "korean": ("ko-KR-HyunsuMultilingualNeural", "ko-KR-SunHiNeural"),
    "ko": ("ko-KR-HyunsuMultilingualNeural", "ko-KR-SunHiNeural"),
    "english": ("en-US-GuyNeural", "en-US-JennyNeural"),
    "en": ("en-US-GuyNeural", "en-US-JennyNeural"),
    "german": ("de-DE-FlorianMultilingualNeural", "de-DE-SeraphinaMultilingualNeural"),
    "de": ("de-DE-FlorianMultilingualNeural", "de-DE-SeraphinaMultilingualNeural"),
    "french": ("fr-FR-RemyMultilingualNeural", "fr-FR-VivienneMultilingualNeural"),
    "fr": ("fr-FR-RemyMultilingualNeural", "fr-FR-VivienneMultilingualNeural"),
    "spanish": ("es-ES-AlvaroNeural", "es-ES-XimenaNeural"),
    "es": ("es-ES-AlvaroNeural", "es-ES-XimenaNeural"),
    "brazilian portuguese": ("pt-BR-AntonioNeural", "pt-BR-ThalitaMultilingualNeural"),
    "portuguese": ("pt-BR-AntonioNeural", "pt-BR-ThalitaMultilingualNeural"),
    "pt": ("pt-BR-AntonioNeural", "pt-BR-ThalitaMultilingualNeural"),
    "italian": ("it-IT-GiuseppeMultilingualNeural", "it-IT-ElsaNeural"),
    "it": ("it-IT-GiuseppeMultilingualNeural", "it-IT-ElsaNeural"),
    "russian": ("ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"),
    "ru": ("ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural"),
    "thai": ("th-TH-NiwatNeural", "th-TH-PremwadeeNeural"),
    "vietnamese": ("vi-VN-NamMinhNeural", "vi-VN-HoaiMyNeural"),
    "indonesian": ("id-ID-ArdiNeural", "id-ID-GadisNeural"),
    "arabic": ("ar-SA-HamedNeural", "ar-SA-ZariyahNeural"),
    "hindi": ("hi-IN-MadhurNeural", "hi-IN-SwaraNeural"),
}


def default_voices_for(language: str | None) -> tuple[str, str] | None:
    """The `(host_a, host_b)` pair for a language, or `None` if it isn't one we have voices for.

    **This is the gap that kept the podcast out of the previous slice's language work**: nothing in
    this module ever mapped a language to a voice — `voice_map` came straight from
    `RN_TTS_VOICE_HOST_A/B` and `synthesize` spoke whatever it was handed — so a correct Chinese
    script would have been read by the en-US default cast. That hole is provider-independent; it was
    never "edge-tts is the wrong TTS".

    Matching is deliberately loose: the value arrives either as a model-authored name ("Traditional
    Chinese") or as whatever an operator typed ("zh-TW"). A bare BCP-47 tag also falls back to its
    primary subtag, so "pt-PT" finds "pt" rather than nothing.
    """
    if not language:
        return None
    key = " ".join(language.lower().split())
    if key in _LANGUAGE_VOICES:
        return _LANGUAGE_VOICES[key]
    return _LANGUAGE_VOICES.get(key.split("-")[0])


#: Kokoro's own voice names, which look nothing like edge-tts's — `zf_xiaobei`, not
#: `zh-TW-HsiaoChenNeural`. Keeping the map on the provider is exactly why `default_voices` moved
#: onto the protocol: one provider's names must never leak into another's request.
#:
#: The leading letter is Kokoro's own convention (language then gender: `zf` = Chinese female,
#: `am` = American male), and `KPipeline` additionally needs a one-character `lang_code`, so both
#: are stored. Every id here was taken from a working local synthesis, not from documentation.
_KOKORO_VOICES: dict[str, tuple[str, str, str]] = {
    # language key -> (lang_code, host_a voice, host_b voice)
    "chinese": ("z", "zm_yunjian", "zf_xiaobei"),
    "mandarin": ("z", "zm_yunjian", "zf_xiaobei"),
    "traditional chinese": ("z", "zm_yunjian", "zf_xiaobei"),
    "simplified chinese": ("z", "zm_yunjian", "zf_xiaobei"),
    "zh": ("z", "zm_yunjian", "zf_xiaobei"),
    "english": ("a", "am_adam", "af_heart"),
    "en": ("a", "am_adam", "af_heart"),
    "japanese": ("j", "jm_kumo", "jf_alpha"),
    "ja": ("j", "jm_kumo", "jf_alpha"),
    "spanish": ("e", "em_alex", "ef_dora"),
    "french": ("f", "ff_siwis", "ff_siwis"),
    "italian": ("i", "im_nicola", "if_sara"),
    "brazilian portuguese": ("p", "pm_alex", "pf_dora"),
    "portuguese": ("p", "pm_alex", "pf_dora"),
    "hindi": ("h", "hm_omega", "hf_alpha"),
}


class KokoroProvider:
    """A fully LOCAL provider: no network, no API key, no third-party terms of service.

    Exists because `edge-tts`, the default, reaches an undocumented Microsoft consumer endpoint with
    a hardcoded client token — it works and needs no credentials (invariant 15), but it is network-
    dependent and operates in the same grey area every Edge-Read-Aloud client does. This is the
    offline answer.

    **Chosen after two wrong recommendations, and only once it had been RUN on the target machine.**
    NeuTTS has no CJK at all, which is the language the whole output-language work exists for.
    Qwen3-TTS was recommended from a blog summary claiming CPU inference; the repository documents
    `device_map="cuda:0"` and never mentions CPU, so it would not run on the Apple Silicon machine
    this project is developed on. Kokoro was verified by installing it and synthesizing Mandarin
    before a line of this class was written: 17.4s one-time pipeline load, then 4.4s for 8.9s of
    audio on CPU.

    **Writes WAV, not MP3, and that is why `suffix`/`media_type` live on the provider.** Kokoro
    emits raw 24kHz samples; converting to MP3 would need the `ffmpeg`/`pydub` dependency invariant
    17 deliberately refused for a purely cosmetic gain. A browser plays WAV natively, so nothing
    downstream needs an encoder.

    Optional dependency (`uv sync --extra kokoro`), imported lazily so a default install never pays
    for torch — 87 packages, measured, not estimated. Weights download on first use.
    """

    suffix = ".wav"
    media_type = "audio/wav"

    #: Kokoro's native sample rate.
    _SAMPLE_RATE = 24_000

    def default_voices(self, language: str | None) -> tuple[str, str] | None:
        entry = self._entry(language)
        return (entry[1], entry[2]) if entry else None

    @staticmethod
    def _entry(language: str | None) -> tuple[str, str, str] | None:
        if not language:
            return None
        key = " ".join(language.lower().split())
        return _KOKORO_VOICES.get(key) or _KOKORO_VOICES.get(key.split("-")[0])

    def synthesize(self, script: PodcastScript, voice_map: dict[str, str], out_path: Path) -> None:
        try:
            import numpy as np
            import soundfile as sf
            from kokoro import KPipeline
        except ImportError as exc:  # pragma: no cover — exercised only with the extra absent
            raise TTSError(
                "the 'kokoro' provider needs the optional extra: uv sync --extra kokoro"
            ) from exc

        # The lang_code is a property of the VOICE, and both hosts speak the same language here, so
        # it is derived from host_a's voice rather than passed separately.
        lang_code = next(
            (entry[0] for entry in _KOKORO_VOICES.values() if entry[1] == voice_map.get("host_a")),
            "a",
        )
        try:
            pipeline = KPipeline(lang_code=lang_code)
            chunks = []
            for utterance in script.utterances:
                voice = voice_map.get(utterance.speaker)
                if not voice:
                    raise TTSError(f"no voice configured for speaker {utterance.speaker!r}")
                for _, _, audio in pipeline(utterance.text, voice=voice):
                    chunks.append(audio.numpy() if hasattr(audio, "numpy") else audio)
            if not chunks:
                raise TTSError("kokoro produced no audio for this script")
            sf.write(out_path, np.concatenate(chunks), self._SAMPLE_RATE)
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"kokoro synthesis failed: {exc}") from exc


_PROVIDERS: dict[str, Callable[[], TTSProvider]] = {
    "edge-tts": EdgeTTSProvider,
    "kokoro": KokoroProvider,
}


def get_tts_provider(name: str) -> TTSProvider:
    """Look up a `TTSProvider` by `RN_TTS_PROVIDER` name. Raises `TTSError` (not `KeyError`) on an
    unknown name, naming the known providers — consistent with this project's other "refuse loudly
    on a bad config value" behavior (`config.py`'s interpreter/OCR-provider checks)."""
    try:
        return _PROVIDERS[name]()
    except KeyError:
        raise TTSError(
            f"unknown TTS provider {name!r}; known providers: {sorted(_PROVIDERS)}"
        ) from None
