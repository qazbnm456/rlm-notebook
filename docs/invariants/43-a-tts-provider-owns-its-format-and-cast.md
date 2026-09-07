# Invariant 43 — A TTS provider owns its format and cast

**A `TTSProvider` owns its OUTPUT FORMAT, its own cast, and — since it may be cross-lingual — is
handed the LANGUAGE as a separate input. None of the three is the caller's.**

A voice NAME is provider-specific (edge-tts wants `zh-TW-YunJheNeural`, chatterbox wants one of
its shipped reference-clip names), so `default_voices`/`fallback_voices` live on the protocol — a
shared map would leak one provider's names into the other's request. **The format is on the
provider for the same reason**: chatterbox emits 24kHz WAV, and forcing it through an MP3 encoder
would drag in the `ffmpeg`/`pydub` dependency invariant 17 refused. **`synthesize` takes
`language`** because a cross-lingual provider's voice and language are independent axes;
`EdgeTTSProvider` ignores it, because an edge-tts voice id already carries its locale. That same
fact makes `ChatterboxProvider.default_voices` return `None` for EVERY language, routing the
default to `fallback_voices` exactly as invariant 40's ladder intends. An unknown language RAISES
rather than falling back to `"en"`: synthesizing Korean with an English language id produces
confident nonsense, and failing before any audio is written beats a wrong-language episode.

**`tts.ChatterboxProvider` (`RN_TTS_PROVIDER=chatterbox`, the `chatterbox` extra) is the
local/privacy option, NOT the default.** No network, no API key. It sounds better and never
touches the network — exactly the trade a reader who cannot send their sources to a cloud service
wants, and exactly the trade nobody should be made to take by default: measured against edge-tts
on the same input, **33x the wall clock and 9x the bytes**, and a 3.4-minute episode took 16.1
minutes end to end, of which 15.0 was synthesis. Invariant 29's "only the script half is
cancellable" therefore covers a far longer window here.

Consequences handled rather than assumed: `notebook.find_audio` looks for WHICHEVER format is
present, because the provider that generated an episode may not be the one currently configured;
`clear_audio` removes every format before a regenerate; and `GET .../audio/file` derives its
media type from the FILE, never from the configured provider.

**`_generate_one` re-rolls against `expected_seconds`** because chatterbox's output LENGTH is
unstable (the identical sentence measured 34.80s / 5.48s / 11.68s against an expected ~7s, the
long take holding 25.1s of actual speech, i.e. the decoder looping). It keeps the SHORTEST take
if it never converges rather than raising — losing a paid-for episode is worse than a clipped
line (invariants 19 and 37). `expected_seconds` is CALIBRATED against real measured utterances
and pinned by a test; a moderate 1.7× overshoot is explicitly NOT caught, because tightening that
far would start rejecting correct takes.

**Two hosts need two reference clips**, because chatterbox's checkpoint carries a single
`conds.pt` and naming both hosts that voice turns a two-host episode into a monologue in two
halves. `rlm_notebook/voices/{host_a,host_b}.wav` are ten-second clips (the `DEC_COND_LEN` bound)
SYNTHESIZED by Kokoro (Apache-2.0) — no person was recorded, because cloning a real human's voice
raises a consent question a recording's licence does not answer. Kokoro's own model card says its
training data includes synthetic audio from closed TTS models, so the provenance chain is three
hops; `rlm_notebook/voices/README.md` carries the full statement and the escape hatch
(`RN_TTS_VOICE_HOST_A`/`_B` accept an absolute path to your own clip). Under `rlm_notebook/` for
invariant 29's packaging reason. **The built-in voice must be captured BEFORE the prep loop**,
since it exists only as `model.conds` and the first `prepare_conditionals` overwrites it — a
MIXED map (one host `built-in`, one clip, a documented configuration) otherwise leaves the
built-in speaker inheriting whichever clip was prepared last, so BOTH hosts come out in one
voice, silently, after fifteen minutes of synthesis.

**`validate(language, voice_map)` runs BEFORE the script generation, not inside `synthesize`** —
invariant 19's discipline one level deeper than the provider NAME. A language chatterbox has no
id for (Thai and Vietnamese are in edge-tts's map but not `_CHATTERBOX_LANGUAGES`) would
otherwise burn a whole model call on every attempt and could never succeed.
`EdgeTTSProvider.validate` is an explicit no-op. A source-tree test pins the ORDERING at both
call sites, because neither has a seam to observe it through.

**A PATH is reachable from the ENVIRONMENT only, never the settings file.** `_VOICE_PATTERN`
accepts edge-tts ids and short lowercase names and excludes `.` and `/`, so a path arriving
through the unauthenticated settings page — a brand-new arbitrary-file-read surface — cannot
happen. Invariant 26's reasoning applied to a second input channel.

**The extra is marked `python_full_version >= '3.13'`, and that marker is not tidiness.**
`chatterbox-tts` pins `numpy<2.0.0` below 3.13 and permits numpy 2 at and above it, while uv's
lock is UNIVERSAL — so an unmarked extra dragged numpy back to 1.26.4 for every 3.11 and 3.12
install of this project, whether chatterbox was requested or not. **numpy 1.x is broken with the
dspy this project now requires**: dspy 3.3.1 installs a lazy-import proxy for numpy
(`dspy/utils/lazy_import.py`) which, on numpy 1.x, re-executes numpy's `__init__` while it is
already partially imported the moment another extension module touches it — `import dspy;
import cv2` dies with a circular import of `numpy.core`, taking the whole OCR path
(rapidocr -> cv2) with it. That is why `numpy>=2` is a CORE dependency. Below 3.13 the extra now
resolves to nothing and `ChatterboxProvider`'s own import guard reports a `TTSError`, which is
the loud failure; the alternative was every 3.11 user's ingestion dying on an import they never
asked for.

**An EXTRA, never a core dependency**, and its two odd pins are load-bearing: `numba>=0.61`,
without which the resolver backtracks to a `llvmlite` supporting Python <3.10 and the install
FAILS on the 3.13 this project targets; and `setuptools<82`, because `perth` and `librosa` both
import `pkg_resources`, which setuptools removed in exactly 82.0.0 — and `perth` swallows that
ImportError and sets its watermarker to `None`, so the failure surfaces as an uninformative
`TypeError` seconds into model loading. The watermark is imperceptible and is KEPT: a provenance
marker on synthetic speech is a feature.

**Nothing is adopted here until it has been installed and run.** Three earlier recommendations
were wrong, all from unverified sources; the rejected alternatives and why are in `CHANGELOG.md`.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
