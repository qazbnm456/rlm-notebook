"""Text-to-speech synthesis for the Audio Overview — host-side, provider-abstracted.

CLAUDE.md's Audio Overview invariant: synthesis runs entirely host-side, on an already-generated,
already schema-validated `PodcastScript` (`audio.py`) — never inside the RLM sandbox, and never a
tool the model can call. The provider is selected by `RN_TTS_PROVIDER` (default `"edge-tts"`, a
free service needing no API key) so the tool works with no paid credentials out of the box —
mirroring the OCR default (CLAUDE.md invariant 7): a capability this project's core value
proposition depends on must not be pluggable-but-unusable by default.

Two providers ship. `EdgeTTSProvider` is the default and concatenates raw MP3 streams;
`ChatterboxProvider` (invariant 43, the `chatterbox` extra) is fully local, multilingual and emits
WAV. A provider therefore owns its own
OUTPUT FORMAT and its own language→voice map — a voice name is provider-specific, and forcing a
WAV-emitting model through an MP3 encoder would need the `ffmpeg`/`pydub` dependency invariant 17
deliberately refused.
"""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .citations import strip_markers
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
    `zh-TW-YunJheNeural` and Chatterbox wants one of its shipped reference-clip names. Keeping the
    cast on the provider is what stops one provider's names leaking into another's request — and so
    does `fallback_voices`, the LAST resort when no language matches. An independent audit found the
    map had moved onto the provider while the last resort had not, so an unknown language on the
    local provider still fell through to an edge-tts name.
    """

    #: File extension and MIME type of what `synthesize` writes.
    suffix: str
    media_type: str

    def default_voices(self, language: str | None) -> tuple[str, str] | None:
        """This provider's cast for `language`, or `None` if it does not know that language —
        `None` means "leave the configured voices alone" (invariant 40: substituting a voice for a
        language nobody asked for is worse than a wrong-language voice)."""
        ...

    def fallback_voices(self) -> tuple[str, str]:
        """This provider's own shipped cast, used only when nothing else resolved. Distinct from
        `default_voices(None)` on purpose: that one must keep returning `None` so an unknown
        language does not silently overrule a configured voice."""
        ...

    def supported_languages(self) -> set[str]:
        """Every language name this provider can actually speak, lowercase.

        On the PROVIDER for the same reason `default_voices` is (invariant 43): the sets genuinely
        differ. An independent review found the settings page offering Thai, Vietnamese and
        Indonesian — which live in edge-tts's voice map — to a `chatterbox` deployment that has no
        language id for any of them, while hiding the eleven chatterbox DOES speak. Picking one
        persisted a GLOBAL `output_language` (it drives chat and every guide artifact too) and then
        made every `/audio` request fail at `validate`. Invariant 19 saved the model call; the page
        is what offered the broken value.
        """
        ...

    def validate(self, language: str | None, voice_map: dict[str, str]) -> None:
        """Refuse a language or a voice this provider cannot serve, BEFORE anything expensive runs.

        Invariant 19's discipline, applied one level deeper: resolving the PROVIDER early already
        stops a typo'd `RN_TTS_PROVIDER` from wasting a model call, but an independent review found
        both of `ChatterboxProvider`'s own checks — an unmapped language, an unknown voice name —
        happening inside `synthesize`, i.e. after the full script-generation run. On a language the
        provider has no id for, every `/audio` request burned a whole RLM run and could never
        succeed. Callers invoke this where they already resolve the provider.

        A no-op is a valid implementation: `EdgeTTSProvider` has nothing to check that
        `get_tts_provider` and the voice ids themselves do not already cover.
        """
        ...

    def synthesize(
        self,
        script: PodcastScript,
        voice_map: dict[str, str],
        out_path: Path,
        language: str | None = None,
    ) -> list[float]:
        """Write the audio and return each utterance's START OFFSET in seconds.

        `language` is the resolved output language (invariant 39). A CROSS-LINGUAL provider needs
        it as a separate input, because its voice and its language are independent —
        `ChatterboxProvider` maps it to a `language_id`. A per-language-cast provider like
        `EdgeTTSProvider` ignores it: its voice names already carry the locale.

        The offsets are what let the transcript behave like subtitles — highlight the line being
        spoken, click a line to seek to it. Every provider here already synthesizes utterance by
        utterance, so it knows them; returning them costs nothing and asking the browser to guess
        would be impossible.

        Returning `[]` is allowed and means "no timing available": the UI then renders a plain
        transcript rather than breaking. A caller must never assume `len(offsets) == len(utterances)`.
        """
        ...


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
    the API slice that DID call this routes around it via `asyncio.to_thread` (invariant 29);
    should any future caller directly rather than off-loading it to a worker
    thread/process) would need to route around this, not call `synthesize()` as-is. Flagging now
    so that future slice doesn't have to rediscover it.
    """

    _communicate_factory: CommunicateFactory = field(default=_default_communicate_factory)

    suffix = ".mp3"
    media_type = "audio/mpeg"

    def default_voices(self, language: str | None) -> tuple[str, str] | None:
        return default_voices_for(language)

    def fallback_voices(self) -> tuple[str, str]:
        return ("en-US-GuyNeural", "en-US-JennyNeural")

    def supported_languages(self) -> set[str]:
        return set(_LANGUAGE_VOICES)

    def validate(self, language: str | None, voice_map: dict[str, str]) -> None:
        # Nothing to pre-flight: a bad voice id is caught by the service itself, and there is no
        # language input to map — an edge-tts voice name already carries its locale.
        return

    def synthesize(
        self,
        script: PodcastScript,
        voice_map: dict[str, str],
        out_path: Path,
        language: str | None = None,
    ) -> list[float]:
        # `language` is unused here on purpose: an edge-tts voice name already carries its locale
        # (`zh-TW-YunJheNeural`), so the cast IS the language. See the Protocol's docstring.
        if not script.utterances:
            raise TTSError("script has no utterances to synthesize")
        try:
            audio, offsets = asyncio.run(self._synthesize_all(script, voice_map))
            out_path.write_bytes(audio)
            return offsets
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

    async def _synthesize_all(
        self, script: PodcastScript, voice_map: dict[str, str]
    ) -> tuple[bytes, list[float]]:
        """The concatenated audio, plus each utterance's start offset in seconds.

        Timing comes from edge-tts's own boundary events rather than from measuring the MP3: their
        `offset`/`duration` are in 100-nanosecond units RELATIVE to the utterance being synthesized,
        so the last boundary's end APPROXIMATES that utterance's duration, and a running sum gives
        the offsets. Approximates, not equals: an independent review measured the per-utterance error
        at -0.049s..+0.066s against durations recovered from the MP3 frame headers, non-systematic in
        sign and cumulating to about +/-0.11s over five or six lines — fine for highlighting a line,
        and not a drift that grows in one direction. The drift-free alternative sits in the same
        function (edge-tts emits fixed-bitrate MP3, so a stream's own frame headers give its exact
        duration) and is a follow-up if a long episode ever visibly desynchronises; it is written
        down here rather than left as a thing to rediscover.

        **Matches ANY `*Boundary` event, not `WordBoundary` specifically.** The first version keyed
        on `WordBoundary`; the installed edge-tts defaults to `boundary="SentenceBoundary"` and emits
        only that, so every offset came back 0.0 — caught by generating a real episode and reading
        the numbers, not by the offsets being obviously absent. Requesting word boundaries instead
        would work too, but sentence-level is all this needs (one offset per utterance) and asking
        for less data is the cheaper fix.

        A provider (or a fake) that emits no boundary at all yields offsets that stop advancing —
        `[0.0, 0.0, ...]`, which is exactly as long as `utterances` and therefore CANNOT be caught by
        a length check. An independent review found the docstring here claiming otherwise, and
        simulated the consequence: every line stamped `0:00`, the SECOND row highlighted for the
        whole episode and the first never, every click seeking to 0. So the real guard is
        monotonicity, applied by the consumer (`app.js`'s `timed`), not length alone. The default
        provider does not reach this state today — verified live, edge-tts raises `NoAudioReceived`
        (surfacing as `TTSError`) for punctuation-only text rather than returning boundary-less
        audio — but a guard that rests on that is a guard resting on someone else's error handling.
        """
        chunks: list[bytes] = []
        offsets: list[float] = []
        elapsed = 0.0
        for utterance in script.utterances:
            voice = voice_map.get(utterance.speaker)
            if not voice:
                raise TTSError(f"no voice configured for speaker {utterance.speaker!r}")
            communicate = self._communicate_factory(utterance.text, voice)
            buf = bytearray()
            end_ticks = 0
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.extend(chunk["data"])
                elif chunk["type"].endswith("Boundary"):
                    end_ticks = max(end_ticks, chunk.get("offset", 0) + chunk.get("duration", 0))
            chunks.append(bytes(buf))
            offsets.append(elapsed)
            elapsed += end_ticks / 10_000_000  # 100ns ticks -> seconds
        return b"".join(chunks), offsets


def sequence_offsets(lengths: Sequence[int], gap: int, sample_rate: int) -> list[float]:
    """Each utterance's start offset in seconds, when `lengths` samples are concatenated with `gap`
    samples of silence BETWEEN them (never before the first, never after the last).

    **The gap belongs to the line BEFORE it**, so an offset is where its own line's audio starts and
    a click lands on that line rather than in the preceding pause. Its own leading silence is the
    provider's business: the local provider emits about 0.39s of it per utterance, measured live,
    which is why "lands on the speech" is really "lands at the start of this line's audio".

    A pure function rather than bookkeeping inlined in `ChatterboxProvider.synthesize` so CI can check
    invariant 44's gap-before-offset claim without the local-TTS extra, a model download, or any
    audio — an independent review found the claim rested on a hand-verification and nothing else.
    """
    offsets: list[float] = []
    samples = 0
    for index, length in enumerate(lengths):
        if index:
            samples += gap
        offsets.append(samples / sample_rate)
        samples += length
    return offsets


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

#: Chatterbox is CROSS-LINGUAL: the voice and the language are separate inputs, so unlike edge-tts
#: there is no per-language cast to pick — the same two hosts speak every language. What it needs
#: instead is a `language_id`, which this maps our own language NAMES onto (`config.output_language`
#: yields things like "Traditional Chinese", never a BCP-47 tag). An unknown language raises rather
#: than guessing: synthesizing Korean with `language_id="en"` produces confident nonsense, and a
#: loud failure before the audio is written beats a wrong-language episode nobody asked for.
_CHATTERBOX_LANGUAGES: dict[str, str] = {
    "english": "en",
    "en": "en",
    "chinese": "zh",
    "mandarin": "zh",
    "traditional chinese": "zh",
    "simplified chinese": "zh",
    "zh": "zh",
    "zh-tw": "zh",
    "zh-cn": "zh",
    "japanese": "ja",
    "ja": "ja",
    "korean": "ko",
    "ko": "ko",
    "german": "de",
    "de": "de",
    "french": "fr",
    "fr": "fr",
    "spanish": "es",
    "es": "es",
    "italian": "it",
    "it": "it",
    "portuguese": "pt",
    "brazilian portuguese": "pt",
    "pt": "pt",
    "russian": "ru",
    "ru": "ru",
    "hindi": "hi",
    "hi": "hi",
    "arabic": "ar",
    "ar": "ar",
    "dutch": "nl",
    "polish": "pl",
    "turkish": "tr",
    "greek": "el",
    "hebrew": "he",
    "danish": "da",
    "finnish": "fi",
    "norwegian": "no",
    "swedish": "sv",
    "malay": "ms",
    "swahili": "sw",
}

#: The two shipped reference clips, resolved to real paths at call time. A voice NAME rather than a
#: path is what reaches `config` and the settings page, deliberately: a path arriving through the
#: unauthenticated settings file (invariant 25/41) would be a brand-new arbitrary-file-read surface,
#: which invariant 26 spent a whole slice closing on the ingestion side. An operator can still point
#: at their own clip, but only through the ENVIRONMENT, never through the settings file.
_VOICE_DIR = Path(__file__).parent / "voices"
_SHIPPED_VOICES: dict[str, str] = {"host-a": "host_a.wav", "host-b": "host_b.wav"}

#: Chatterbox's own single built-in voice. Usable, but it is ONE voice — naming both hosts this
#: turns a two-host episode into a monologue in two halves.
BUILTIN_VOICE = "built-in"


def shipped_voice_path(name: str) -> Path | None:
    """Resolve a voice NAME to a shipped reference clip, or `None` for the built-in voice.

    An absolute path is passed through unchanged (the environment-only override above); anything
    else that is not a known name raises, because a typo silently falling back to the built-in voice
    would give both hosts the same voice and nothing would say why.
    """
    if name == BUILTIN_VOICE:
        return None
    if name in _SHIPPED_VOICES:
        return _VOICE_DIR / _SHIPPED_VOICES[name]
    candidate = Path(name)
    if candidate.is_absolute() and candidate.is_file():
        return candidate
    raise TTSError(
        f"unknown chatterbox voice {name!r}; shipped voices: {sorted(_SHIPPED_VOICES)} "
        f"or {BUILTIN_VOICE!r}, or an absolute path to a reference .wav"
    )


#: Roughly how many characters of each script a speaker gets through per second. Only used to bound
#: a runaway (below), never to report timing — the real offsets come from the samples.
#:
#: CALIBRATED against real Chatterbox output, not guessed: four measured utterances (Traditional
#: Chinese with and without embedded Latin, English, Japanese) land within a few percent of these
#: rates, and `tests/test_tts.py` pins them so a later edit cannot quietly detune the guard. The
#: first draft used 15 for Latin, which under-estimated a real English line by a third and would
#: have made the runaway ceiling tighter than a correct take.
_CHARS_PER_SECOND_CJK = 5.1
_CHARS_PER_SECOND_LATIN = 10.0


def _is_cjk(ch: str) -> bool:
    """Whether `ch` should be counted at the CJK rate.

    Covers Hiragana/Katakana/Bopomofo/CJK Ext-A/Unified (U+3040-9FFF), Hangul syllables and Jamo,
    AND the CJK punctuation and fullwidth forms an independent audit found silently excluded —
    `。、「」，！？` are ubiquitous in exactly these languages and were being counted at the Latin
    rate. Widening improved the estimate against all four calibration utterances rather than
    degrading it, which is why it was taken rather than merely disclosed.
    """
    code = ord(ch)
    return (
        0x3040 <= code <= 0x9FFF  # kana, Bopomofo, CJK Ext-A, CJK Unified
        or 0xAC00 <= code <= 0xD7AF  # Hangul syllables
        or 0x1100 <= code <= 0x11FF  # Hangul Jamo
        or 0x3000 <= code <= 0x303F  # CJK punctuation
        or 0xFF00 <= code <= 0xFFEF  # fullwidth forms
    )


def expected_seconds(text: str) -> float:
    """A rough spoken duration for `text`, used ONLY as the ceiling a runaway is measured against.

    Deliberately crude and deliberately generous: CJK characters carry far more time each than Latin
    ones, so the two are counted separately, and the result is a floor of one second so a very short
    line cannot produce a near-zero ceiling.
    """
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    return max(1.0, cjk / _CHARS_PER_SECOND_CJK + other / _CHARS_PER_SECOND_LATIN)


class ChatterboxProvider:
    """`RN_TTS_PROVIDER=chatterbox` — a fully local, multilingual provider (the `chatterbox` extra).

    **Replaces `KokoroProvider`, and the reason is the language matrix, not audio quality.** Kokoro's
    Chinese G2P passes Latin text through UNCONVERTED (its "phonemes" for `NASA` are the literal
    string `NASA`), it has no Korean at all, and its own model card grades every Chinese voice D on
    10-100 minutes of data. MeloTTS was measured as the replacement first and rejected: its Japanese
    module DELETES embedded Latin, its Korean needs `python-mecab-ko` which destructively overwrites
    the `MeCab` module its Japanese needs, and its `transformers==4.27.4` pin would roll this
    project's ML stack back two years. Chatterbox is the only local engine measured here that covers
    English, Chinese (both scripts), Japanese and Korean AND handles a foreign word inside a
    sentence — which it gets for free by having no G2P stage to fail at.

    **Three costs, all measured on Apple Silicon rather than assumed, and none of them hidden:**

    1. It is ~20x slower than Kokoro (RTF ~4.5 against ~0.2). Measured end to end through the real
       product: a 3.4-minute episode took 16.1 minutes of wall clock, 15.0 of them synthesis, where
       Kokoro took about forty seconds. `/audio` was already the slowest action in the product, and
       only its script half is cancellable (invariant 29).
    2. Its output LENGTH is unstable. The identical Traditional Chinese sentence produced 34.80s,
       5.48s and 11.68s across three runs, against an expected ~7s; the 34.8s take held 25.1s of
       actual speech, i.e. the autoregressive decoder looping, not trailing silence. `_generate_one`
       below retries against `expected_seconds`, which is the whole reason that function exists.
    3. It ships ONE built-in voice, so two distinguishable hosts need reference clips. See
       `rlm_notebook/voices/README.md` for where the two shipped clips come from and why.
    """

    suffix = ".wav"
    media_type = "audio/wav"

    #: A short silence between utterances, same as Kokoro had it: free here because we hold raw
    #: samples, and back-to-back turns with no gap sound unnatural in a two-host script.
    _GAP_SECONDS = 0.35

    #: A take longer than this multiple of `expected_seconds` is treated as a runaway and retried.
    #: Set from the measured failure: the reproduced loop was 5x its expected length, so 2x catches
    #: it with room to spare while leaving natural variation alone. **Stated limitation**: a
    #: MODERATE overshoot is not caught — one of the three reproduction runs came back 1.7x
    #: expected, which is a padded reading rather than a loop, and tightening the factor far enough
    #: to catch it would start rejecting correct takes at the cost of a whole slow regeneration.
    _RUNAWAY_FACTOR = 2.0

    #: How many times to re-roll a runaway before giving up and keeping the SHORTEST take.
    #: **The undisclosed cost, stated**: three attempts is up to 3x the synthesis time on the ONE
    #: phase invariant 29 says is uncancellable — a 15-minute episode could become 45. Only a
    #: runaway pays it (a good first take costs exactly one generation, pinned by a test), and the
    #: measured live episode needed 16 loops for 16 utterances, i.e. none.
    _MAX_ATTEMPTS = 3

    def default_voices(self, language: str | None) -> tuple[str, str] | None:
        # No per-language cast exists: one pair of cloned voices speaks every language, which is the
        # point of a cross-lingual model. Returning `None` lets an explicitly configured voice stand
        # (invariant 40) and hands the default to `fallback_voices` below.
        return None

    def fallback_voices(self) -> tuple[str, str]:
        return ("host-a", "host-b")

    def supported_languages(self) -> set[str]:
        return set(_CHATTERBOX_LANGUAGES)

    def validate(self, language: str | None, voice_map: dict[str, str]) -> None:
        # Both of these used to raise inside `synthesize`, i.e. after a full script-generation run.
        # A language with no id here (Thai and Vietnamese are in edge-tts's map but not in
        # `_CHATTERBOX_LANGUAGES`) could never succeed, so every attempt burned a model call; and a
        # stale edge-tts voice left in the settings file after switching providers cost a model load
        # before failing. Found by an independent review against invariant 19's own discipline.
        self._language_id(language)
        for voice in voice_map.values():
            shipped_voice_path(voice)

    def synthesize(
        self,
        script: PodcastScript,
        voice_map: dict[str, str],
        out_path: Path,
        language: str | None = None,
    ) -> list[float]:
        try:
            import numpy as np
            import soundfile as sf
            import torch

            # Imported for its side effect: fail HERE, with an actionable message, rather than
            # several seconds later inside `_model_factory`.
            importlib.import_module("chatterbox.mtl_tts")
        except ImportError as exc:  # pragma: no cover — exercised only with the extra absent
            raise TTSError(
                "the 'chatterbox' provider needs the optional extra: uv sync --extra chatterbox"
            ) from exc

        language_id = self._language_id(language)
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        try:
            model = self._model_factory(device)
            sample_rate = model.sr

            # Each speaker's conditioning is prepared ONCE and swapped, never re-prepared per
            # utterance: `prepare_conditionals` mutates the model in place and runs the voice
            # encoder over the whole clip, so doing it on every speaker change would pay that cost
            # once per line of the script.
            #
            # The BUILT-IN voice has to be captured FIRST, because it exists only as `model.conds`
            # and the first `prepare_conditionals` overwrites it. An independent review reproduced
            # what happens without this: a mixed map (one host `built-in`, the other a clip) left
            # the built-in speaker with "no conditioning to assign", so it inherited whichever clip
            # was prepared last and BOTH hosts came out in one voice — the exact monologue-in-two-
            # halves the shipped clips exist to prevent, failing silently after ~15 minutes of
            # synthesis. Every speaker gets a real conditioning object and the assignment below is
            # unconditional.
            builtin = model.conds
            conds = {}
            for speaker, voice in voice_map.items():
                path = shipped_voice_path(voice)
                if path is None:
                    conds[speaker] = builtin
                    continue
                model.prepare_conditionals(str(path))
                conds[speaker] = model.conds

            per_utterance = []
            for utterance in script.utterances:
                if utterance.speaker not in voice_map:
                    raise TTSError(f"no voice configured for speaker {utterance.speaker!r}")
                model.conds = conds[utterance.speaker]
                per_utterance.append(
                    self._generate_one(model, utterance.text, language_id, sample_rate, np)
                )

            if not any(len(part) for part in per_utterance):
                raise TTSError("chatterbox produced no audio for this script")
            gap = np.zeros(int(self._GAP_SECONDS * sample_rate), dtype="float32")
            offsets = sequence_offsets(
                [len(part) for part in per_utterance], len(gap), sample_rate
            )
            chunks = []
            for index, part in enumerate(per_utterance):
                if index:
                    chunks.append(gap)
                chunks.append(part)
            sf.write(out_path, np.concatenate(chunks), sample_rate)
            return offsets
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"chatterbox synthesis failed: {type(exc).__name__}: {exc}") from exc

    def _generate_one(self, model, text: str, language_id: str, sample_rate: int, np):
        """One utterance, re-rolled if the decoder runs away.

        Not defensive programming for a hypothetical: reproduced live, the same Traditional Chinese
        sentence came back at 34.80s / 5.48s / 11.68s across three runs against an expected ~7s, and
        the long take was looping speech rather than silence. A run that never converges keeps the
        SHORTEST take rather than raising — a slightly clipped line is a far better outcome for a
        paid-for episode than losing the whole thing (the same "never lose what already succeeded"
        rule invariants 19 and 37 apply to a failed TTS call and a failed title).
        """
        ceiling = expected_seconds(text) * self._RUNAWAY_FACTOR
        takes = []
        for _ in range(self._MAX_ATTEMPTS):
            wav = model.generate(text, language_id=language_id)
            audio = wav.detach().cpu().numpy().reshape(-1).astype("float32")
            takes.append(audio)
            if len(audio) / sample_rate <= ceiling:
                return audio
        return min(takes, key=len)

    @staticmethod
    def _model_factory(device: str):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        return ChatterboxMultilingualTTS.from_pretrained(device=device)

    @staticmethod
    def _language_id(language: str | None) -> str:
        if not language:
            return "en"
        key = " ".join(language.lower().split())
        found = _CHATTERBOX_LANGUAGES.get(key) or _CHATTERBOX_LANGUAGES.get(key.split("-")[0])
        if not found:
            raise TTSError(
                f"chatterbox has no language id for {language!r}; known: "
                f"{sorted(set(_CHATTERBOX_LANGUAGES.values()))}"
            )
        return found


_PROVIDERS: dict[str, Callable[[], TTSProvider]] = {
    "edge-tts": EdgeTTSProvider,
    "chatterbox": ChatterboxProvider,
}


def spoken_script(script: PodcastScript) -> PodcastScript:
    """`script` with every `[[SRC:...]]` marker removed from what the voices will read.

    The model is told a marker belongs in a `Citation` and never in a spoken line, and a real run
    ignored that in 19 of 47 utterances — so the episode said "S R C S one" out loud. The transcript
    was already clean, because the API strips markers on the way out (invariant 62); synthesis reads
    the script object directly and so had its own copy of the problem.

    Applied HERE, once, rather than inside each provider: there are two implementations and a third
    would silently ship without it. Utterance COUNT and order are untouched, so the offsets
    invariant 44 defines still line up one-to-one with the transcript the reader sees.
    """
    def spoken(text: str) -> str:
        stripped = strip_markers(text)
        # A line that was NOTHING but a coordinate strips to "" or to a lone piece of punctuation,
        # and neither provider survives that: `EdgeTTSProvider` raises `NoAudioReceived` for
        # punctuation-only text (verified live, recorded in `_synthesize_all`'s own docstring), and
        # `ChatterboxProvider` burns every re-roll before failing. The TTSError becomes a 502 and the
        # whole paid-for RLM run is discarded — so this net, added to stop a marker being READ
        # aloud, would have turned a survivable defect into a lost episode.
        #
        # Falling back to the original is the lesser harm and the discipline invariants 19/37/43
        # already encode: never lose what already succeeded. A garbled line ships; a 502 does not.
        return stripped if any(ch.isalnum() for ch in stripped) else text

    return script.model_copy(
        update={
            "utterances": [
                u.model_copy(update={"text": spoken(u.text)}) for u in script.utterances
            ]
        }
    )


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
