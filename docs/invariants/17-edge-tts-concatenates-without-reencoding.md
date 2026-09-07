# Invariant 17 — Edge TTS concatenates without reencoding

**`EdgeTTSProvider` synthesizes one utterance at a time (one voice per `edge-tts` call) and
concatenates the raw MP3 byte streams — it does not re-encode.** A deliberate tradeoff to avoid
an `ffmpeg`/`pydub` dependency (`ffmpeg` is a system binary, not pip-installable) for what would
only be a gapless-playback cosmetic improvement. Weigh that dependency cost before "fixing" it.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
