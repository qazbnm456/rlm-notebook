# Invariant 40 — Language decides the podcast voice

**`tts.default_voices_for` maps a language to a voice, which is what let the podcast join
invariant 39's language story.** Nothing here previously mapped language to voice: `voice_map`
came straight from `RN_TTS_VOICE_HOST_A`/`_B` and `synthesize` spoke whatever it was handed. Any
provider would have had the same hole — a correct Chinese script read by the en-US default cast
is a routing bug, not a synthesis one.

**Every voice id in the table was read out of a real `edge_tts.list_voices()` response, never
written from memory** — a plausible-looking but nonexistent voice id fails only at SYNTHESIS
time, after a real model call has been spent on the script, which is the waste invariant 19
exists to prevent. A test asserts the shape of every id as a guard against hand-editing.

**Precedence: an explicitly set `RN_TTS_VOICE_HOST_A`/`_B` beats the settings file (invariant
41), which beats the language default, which beats the shipped en-US cast.** The file rung sits
above the language default because both it and the env are a human saying "use this voice".
Explicitness is read from the RAW environment, never by comparing against the default VALUE: an
operator who deliberately sets the en-US default on a Chinese notebook is making a choice. The
two voices resolve independently. An unknown language returns `None` from `default_voices` and
the configured voices stand — a wrong-language voice is bad, but substituting a voice for a
language nobody asked for is worse.

**`fallback_voices` is a SECOND, separate provider method**, sitting BELOW the language default
and ABOVE the shipped `config` value, so an explicit env var still wins and a known language
still wins over a generic cast. It exists because a non-edge-tts provider plus an unknown
language otherwise falls through to an edge-tts voice name, failing at synthesis after a real
model call. Deliberately not `default_voices(None)`, which must keep returning `None`.
`_VOICE_PATTERN` accepts BOTH naming schemes — widening the accepted SHAPES, never the accepted
CHARACTERS, so the SSML hole invariant 41 closed stays closed.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
