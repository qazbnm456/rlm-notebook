"""Text-to-speech synthesis for the Audio Overview — host-side, provider-abstracted.

CLAUDE.md's Audio Overview invariant: synthesis runs entirely host-side, on an already-generated,
already citation-checked `PodcastScript` (`audio.py`) — never inside the RLM sandbox, and never a
tool the model can call. The provider is selected by `RN_TTS_PROVIDER` (default `"edge-tts"`, a
free service needing no API key) so the tool works with no paid credentials out of the box —
mirroring the OCR default (CLAUDE.md invariant 7): a capability this project's core value
proposition depends on must not be pluggable-but-unusable by default.
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
    multi-speaker conversation in one call — callers only see "script in, audio file out"."""

    def synthesize(self, script: PodcastScript, voice_map: dict[str, str], out_path: Path) -> None: ...


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
    should the planned API/UI slice call this directly rather than off-loading it to a worker
    thread/process) would need to route around this, not call `synthesize()` as-is. Flagging now
    so that future slice doesn't have to rediscover it.
    """

    _communicate_factory: CommunicateFactory = field(default=_default_communicate_factory)

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


_PROVIDERS: dict[str, Callable[[], TTSProvider]] = {
    "edge-tts": EdgeTTSProvider,
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
