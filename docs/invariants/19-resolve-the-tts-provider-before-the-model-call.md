# Invariant 19 — Resolve the TTS provider before the model call

**`cli._cmd_audio` resolves the TTS provider before running the (potentially expensive)
script-generation model call, not after.** The original ordering wasted a real model call
whenever `RN_TTS_PROVIDER` was misconfigured — the error surfaced only once the transcript had
already been generated. Don't move `get_tts_provider(...)` back after
`GeneratePodcastScript().run(...)`. Relatedly, `EdgeTTSProvider.synthesize` wraps its file WRITE
in the same try/except as the network call: both are one "make this file exist" operation as far
as any caller is concerned, and a bad `--out` directory must not raise after synthesis has
already spent a real network call.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
