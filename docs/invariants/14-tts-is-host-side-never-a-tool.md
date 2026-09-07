# Invariant 14 — TTS is host-side, never a tool

**TTS synthesis (`tts.py`) runs entirely host-side, on an already-generated,
already-schema-validated `PodcastScript` — it is never a tool the model can call, and
`GeneratePodcastScript` (`audio.py`) has no dependency on `tts.py` at all.** Same reasoning as
invariants 1 and 3: synthesis is a real network call, and the model's job (writing a grounded
script) is finished long before any audio is generated.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
