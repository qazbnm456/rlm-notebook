# Invariant 15 — Default TTS provider needs no key

**The default TTS provider (`RN_TTS_PROVIDER=edge-tts`) needs no API key or paid account, so
`rlm-notebook audio` works out of the box** — the same "ship a working default, not just a
pluggable interface" reasoning as OCR (invariant 7). The known-provider list lives in ONE place,
`tts.py`'s `_PROVIDERS` (`get_tts_provider` refuses loudly on an unknown name); `config.py`
deliberately keeps NO second copy to validate against, because a second list drifts.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
