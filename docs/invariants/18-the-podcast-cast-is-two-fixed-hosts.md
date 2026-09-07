# Invariant 18 — The podcast cast is two fixed hosts

**The Audio Overview's cast is a fixed two hosts, `host_a`/`host_b` (`schema.Speaker`), not
freely-named per episode.** Keeps `Utterance.speaker` a closed enum (`Literal[...]`, not an
`enum.Enum`) that citations and voice-mapping can rely on, and keeps `RN_TTS_VOICE_HOST_A`/`_B`
a fixed two-variable surface. A deliberate MVP scope cut. **Known gap**: `config.tts_voice_map`
hardcodes both speaker keys with no tripwire, unlike `cli._SPEAKER_LABELS`, which
`tests/test_cli.py`'s sibling assertion covers — so a third host would need BOTH updated and only
one of them would fail loudly.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
