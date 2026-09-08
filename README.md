# rlm-notebook

`rlm-notebook` reads sources of any kind — plain text, web pages, PDFs (including scanned/OCR'd
ones), and YouTube video captions — and uses an RLM
([`rlm-harness`](https://github.com/qazbnm456/rlm-harness)) to answer questions grounded in them, with a
citation you can check back against the original text yourself.

**Status: twenty-four slices in.** Ingestion (text/web/PDF/YouTube captions, with local hybrid OCR
for scanned pages), citation-grounded chat, a persistent multi-turn notebook, notes that can be
promoted into citable sources, a Notebook Guide (summary/FAQ/timeline/key-insight generation), and
an Audio Overview (two-host podcast script + synthesized speech, with a subtitle-style transcript)
are all driveable from the command line — and also from an HTTP API (`ask`/`guide`/`audio`, each
run isolated in its own cancellable subprocess) and a full browser web UI (source management, chat,
a Studio panel, a podcast player, and a live reasoning ticker — see "Web UI" below).

A notebook names itself, model-authored prose follows the READER's language rather than the
documents', a settings page carries the presentation settings, and models can run on a Claude
Pro/Max subscription instead of an API key. See `AGENTS.md` for the hard invariants this project is
built against — it indexes each one in a line or two, with the argument, the evidence and the traps
behind it in `docs/invariants/<n>-<slug>.md`. Together they are the authoritative record; this file
is the tour.

## Install and run

`rlm-notebook` is an APPLICATION, not a library: nothing here is meant to be imported into your own
code, and installing it into a shared environment would drag numpy, an ONNX runtime and a PDF
engine in with it. Install it into its own:

```bash
uv tool install "rlm-notebook[api] @ git+https://github.com/qazbnm456/rlm-notebook"
# or: pipx install "rlm-notebook[api] @ git+https://github.com/qazbnm456/rlm-notebook"
```

Not on PyPI yet, hence the repository URL. Drop `[api]` if you only want the CLI.

**Python 3.11 or 3.12, not 3.13.** `rapidocr-onnxruntime` declares `Requires-Python <3.13`, so pip
refuses to resolve this project on 3.13 (`uv` will install it anyway, which is uv resolving past
that bound rather than the bound not being there).

**Two system dependencies no Python manifest can express**, which is also why there is a container:

```bash
brew install deno         # REQUIRED. Every live run executes in a Deno-hosted pyodide sandbox
brew install tesseract    # optional. The OCR fallback for scanned PDFs; RapidOCR is primary and
                          # ships as a normal dependency, so this only widens coverage
```

Then a model, in the environment. Nothing auto-loads `.env`:

```bash
export RN_MAIN_MODEL=...   # and RN_API_KEY, or use the subscription path below
rlm-notebook ask "what does it say about X?" --source ./paper.pdf
rlm-notebook serve         # the HTTP API and the web UI, on http://127.0.0.1:8000/
```

### In a container

The image carries deno and tesseract, so it is the one install that is complete by itself:

```bash
docker build -t rlm-notebook .
docker run --rm -p 127.0.0.1:8000:8000 -v "$PWD/data:/data" --env-file .env rlm-notebook
```

**Publish the port to loopback, as above.** A bare `-p 8000:8000` puts an API with no
authentication on every interface of your machine. The volume matters too: `notebooks/`, `traces/`
and `audio/` are relative to the working directory, so without it a removed container takes the
notebooks with it.

### To develop it

```bash
git clone https://github.com/qazbnm456/rlm-notebook && cd rlm-notebook
uv sync                       # installs the local OCR backends scanned PDFs need too — no extra flag
cp .env.example .env          # then fill in RN_MAIN_MODEL / RN_API_KEY
set -a; . ./.env; set +a      # nothing auto-loads .env
brew install deno             # the sandbox a live run executes in
```

Instead of an API key, a role can run on your **Claude Pro/Max subscription** — prefix the model
with `claude-agent-sdk/`:

```bash
uv sync --extra api --extra subscription   # plus the Claude Code CLI, installed and logged in
export RN_MAIN_MODEL=claude-agent-sdk/claude-sonnet-5
export RN_SUB_MODEL=claude-agent-sdk/claude-fable-5   # or leave unset to inherit the main model
```

No `RN_API_KEY`/`RN_BASE_URL` is used for a role on that path, and mixing is fine (one role on the
subscription, the other on a proxy). `ClaudeAgentLM` refuses to start when `ANTHROPIC_API_KEY` is
set, since the Claude Code CLI silently prefers it over subscription OAuth and would bill API
credit instead. See AGENTS.md invariant 35.

```bash
# ask a one-off question grounded in one or more sources — nothing is saved
uv run rlm-notebook ask "what does the source say about X?" \
    --source ./paper.pdf \
    --source https://example.com/article \
    --source https://www.youtube.com/watch?v=... \
    --source ./notes.txt
```

```bash
# a persistent, continuing conversation: --notebook saves sources + history to notebooks/<id>.json
uv run rlm-notebook ask "what does the source say about X?" --source ./paper.pdf --notebook mynb
uv run rlm-notebook ask "and what about Y?" --notebook mynb   # no --source needed to continue
uv run rlm-notebook ask "add this too" --source ./more.txt --notebook mynb   # extends it
```

Every answer comes back with citations of the form `source_id` + `locator` (a page number or a
whole-document reference, depending on the source type) that resolve to real text in the
notebook — verified against the source, not just claimed by the model. A citation that doesn't
resolve is marked unverified rather than silently dropped or silently trusted. Prior turns are
context for understanding a follow-up question only; every citation in every answer is re-verified
against the current sources regardless of what an earlier turn cited.

Sources with a flagged prompt-injection pattern (see `injection_scan.py`) still answer normally;
the flag is metadata on the source rather than a block. An ANSWER never carries one — `AskResponse`
has no flags field — but the SOURCE shows it everywhere: the CLI prints it, the API returns it on
each source, and the web UI puts an amber warning chip on the Sources row and a line in the source
viewer.

A YouTube URL ingests that video's captions — official if available, else auto-generated — never
the video or audio stream itself (no `ffmpeg`, no transcription model, no API key needed). A video
with no captions at all is a clear ingestion error, not a silent empty source. **Note**: YouTube's
Terms of Service prohibit automated access outside its own interfaces; fetching only captions is
narrower/lower-risk than downloading media, but this project doesn't pretend the risk is zero —
you accept it by using this feature, the same posture any `yt-dlp`-based tool's users already
carry (AGENTS.md invariant 33).

```bash
# generate a whole-notebook artifact instead of asking a question
uv run rlm-notebook guide summary --source ./paper.pdf
uv run rlm-notebook guide faq --notebook mynb
uv run rlm-notebook guide timeline --notebook mynb
uv run rlm-notebook guide insight --notebook mynb   # the single most important takeaway, one sentence
```

Guide artifacts are citation-verified the same way answers are, and aren't cached — each `guide`
call regenerates fresh from the notebook's current sources.

```bash
# generate a two-host podcast-style Audio Overview: a citation-grounded script + an MP3
uv run rlm-notebook audio --source ./paper.pdf --out episode.mp3
uv run rlm-notebook audio --notebook mynb
```

The transcript prints first (with citations, same as `ask`/`guide`) regardless of whether audio
synthesis succeeds — a TTS failure doesn't lose the script. The default TTS provider (`edge-tts`)
needs no API key and writes MP3; `RN_TTS_PROVIDER=chatterbox` (`uv sync --extra chatterbox`) is
fully local, no network at all, multilingual, and writes WAV — each provider owns its own format and
its own cast. Set `RN_TTS_VOICE_HOST_A`/`_B` in `.env` to override the cast (see `.env.example`).

Pick the local one when your sources must not leave the machine; it sounds better and needs no
network at all. Pick the default otherwise: on the same fourteen-second line of Chinese prose
carrying `NASA`, `CVE-2026-1234` and an English clause, edge-tts took **8.2s and 81KB** against
chatterbox's **273.4s and 749KB**, and handled the mixed script fine.

The local provider is **much slower** — measured on Apple Silicon, a 3.4-minute episode took 16
minutes end to end (15 of them synthesis) against edge-tts's network round trip — and its two hosts
come from two
ten-second reference clips shipped in `rlm_notebook/voices/`, because Chatterbox has exactly one
built-in voice. Those clips were synthesized rather than recorded from a person; where they came
from, and the one part of that chain worth knowing about, is written up in
`rlm_notebook/voices/README.md`.

**Everything the model writes follows the READER's language, not the documents'.** Set
`RN_OUTPUT_LANGUAGE` (a hard override, applying to chat as well as artifacts), or leave it unset and
the server resolves one per notebook — from your browser's `Accept-Language`, the sources, and any
questions already asked, with the questions weighted highest. Citation coordinates and quotes are
never translated: they are what makes a citation checkable. Podcast voices follow the resolved
language too.

## HTTP API

**No authentication of any kind.** Any caller that can reach this API can create, read, `ask`
against, cancel, RENAME or irreversibly DELETE any notebook id — sources, notes and the whole
conversation each have a live `DELETE` — and can change GLOBAL behaviour for notebooks it never
named through `PUT /settings`. There is no concept of an owner. Run it only on `localhost` or an
otherwise fully-trusted network; do not expose it to the internet or a shared network as-is.

```bash
rlm-notebook serve                      # binds 127.0.0.1:8000 — loopback, deliberately
rlm-notebook serve --host 0.0.0.0       # allowed, and it warns, because of the paragraph above
```

`serve` binds loopback by DEFAULT rather than by convention: with no authentication, which
interface it binds is the entire access-control story, so it belongs in the code. It starts
without a model configured, on purpose, since the settings page exists for exactly that operator.
From a source checkout: `uv run rlm-notebook serve` after `uv sync --extra api`.

```bash
# --source accepts URLs only here (not local paths — see AGENTS.md invariant 26); use the CLI
# above for a local file. -H is required — a POST body with no Content-Type: application/json
# gets rejected with a 422, not silently accepted.
curl -X POST localhost:8000/notebooks/mynb/sources -H "Content-Type: application/json" \
    -d '{"sources": ["https://example.com/article"]}'
curl -X POST localhost:8000/notebooks/mynb/ask -H "Content-Type: application/json" \
    -d '{"question": "what does it say about X?"}'
curl -X POST localhost:8000/notebooks/mynb/guide/summary
curl -X POST localhost:8000/notebooks/mynb/audio         # podcast script + base64-encoded audio
curl -X GET  localhost:8000/notebooks/mynb/audio/file    # ...and the persisted episode as a file
curl -X POST localhost:8000/notebooks/mynb/overview      # the chat overview, persisted on the notebook
curl -X POST localhost:8000/notebooks/mynb/title         # let the model name the notebook
curl -X GET  localhost:8000/settings                     # output language + the two podcast voices
curl -X PUT  localhost:8000/settings -H "Content-Type: application/json" \
    -d '{"output_language": "Traditional Chinese"}'      # replaces ALL settings; env still wins
curl -X POST localhost:8000/notebooks/mynb/cancel        # cancel that notebook's in-flight run

# Optional on ask/guide/audio: {"run_id": "my-token"} picks your OWN run id (sanitized, then
# prefixed with the notebook id) so you can open the trace stream below before/alongside firing
# the request that will populate it — omit it and the server picks one, same as before.
curl -X POST localhost:8000/notebooks/mynb/audio -H "Content-Type: application/json" \
    -d '{"run_id": "my-token"}'
curl -X GET  "localhost:8000/notebooks/mynb/runs/mynb-my-token/stream"           # live/replay SSE
curl -X GET  "localhost:8000/notebooks/mynb/runs/mynb-my-token/citation-turn?source_id=s1&locator=whole"

# Paste text (add_sources' texts field) and file upload (a separate multipart endpoint):
curl -X POST localhost:8000/notebooks/mynb/sources -H "Content-Type: application/json" \
    -d '{"texts": ["some text pasted straight in, no URL or path needed"]}'
curl -X POST localhost:8000/notebooks/mynb/sources/upload -F "file=@./paper.pdf"

# A source's full text, every block — the web UI's source-text viewer, not just a citation's
# short `quote`. A materially different exposure than most other endpoints here (AGENTS.md
# invariant 31).
curl -X GET localhost:8000/notebooks/mynb/sources/s1

# Notes: freeform, uncited text — write one directly, or save a Chat answer as one. Only grounded
# once promoted into a real source (AGENTS.md invariant 32).
curl -X POST localhost:8000/notebooks/mynb/notes -H "Content-Type: application/json" \
    -d '{"text": "a thought worth keeping around"}'
curl -X DELETE localhost:8000/notebooks/mynb/notes/n1
curl -X POST localhost:8000/notebooks/mynb/notes/n1/promote   # turns it into a real source
```

Every `ask`/`guide` request runs its `RLMTask` in its own isolated, killable subprocess — unlike
`cli.py`'s in-process invocation — so one slow or stuck request can't block another, and can be
cancelled outright. `/audio` is two host-side steps: script generation runs the same isolated-
subprocess way (and is the only half that's cancellable), then TTS synthesis runs in-process
afterward. A generated episode IS persisted (one file per notebook, replaced on regenerate) and
served by `GET .../audio/file`, so reopening a notebook plays it back without re-synthesising; the
POST response also carries the audio base64-encoded
in it. The trace stream and citation-turn lookup are a materially different exposure than every
other endpoint here (they can surface full ingested source text, not just metadata/prose). File
upload (`.pdf`/`.txt`/`.md`, capped at `RN_MAX_UPLOAD_BYTES`, default 50MB) never accepts a
local-path string — only bytes the caller already had — so it doesn't reopen the local-path
restriction `sources` already enforces. `GET .../sources/{source_id}` returns a source's full
text, every block, reusing the same `Corpus.get` lookup `citations.py` already performs — another
materially different exposure, alongside the trace stream and the Trajectory drawer. A note carries
no citations of its own until it is promoted into a real source (AGENTS.md invariant 32). See
`api.py`'s module docstring, and AGENTS.md invariants 20-47 and 70-72 for the API and web-UI rules.

**Behind a fake-IP proxy or split-DNS VPN?** Clash/Mihomo/Surge resolve every public hostname into
a reserved range (default `198.18.0.0/16`), so the SSRF guard refuses it and EVERY web/YouTube
ingestion fails with "resolves to a disallowed address". Set `RN_FETCH_ALLOW_CIDRS=198.18.0.0/16`
to the range your resolver actually hands out. A value that would cover loopback, cloud metadata or
RFC1918 is refused outright — see AGENTS.md invariant 76.

Every write to a notebook — a source, a note, a chat turn — re-reads the notebook from disk under a
per-notebook lock and applies just its own change, so a source you add while a question is still
being answered is no longer destroyed when that answer is saved (it was, before: both requests
returned 200 and one of them silently lost). Slow work — ingestion, the model run itself — happens
outside the lock. Trace files under `traces/` are pruned on a policy now
(`RN_TRACE_RETENTION_DAYS`, `RN_MAX_TRACE_FILES`) rather than accumulating forever; an in-flight
run's trace and anything written in the last hour are never touched.

## Web UI

Once `rlm-notebook serve` is running, open `http://127.0.0.1:8000/` in a browser: a real end-user
product surface (source management — URL, pasted text, or file upload — citation-grounded chat, a
Studio panel with Guide tabs, a podcast player, and Notes, and a live "what is the model doing
right now" reasoning ticker), not a developer trace console. Zero build step — it's served
directly out of `rlm_notebook/web/` by the same FastAPI app. Clicking a citation in an answer
lights up its entry in the References panel — number, source, provenance chip, use count and the
passage — and clicking a row in Sources opens the full original text in a viewer. That is
NotebookLM's most basic closed loop, and it is a transparency mechanism, never a stronger
faithfulness claim than `citations.py` itself already makes. Every Chat answer can be
saved as a note, and every note can later be promoted into a real, citable source — NotebookLM's
own research loop of reading, noting, and deepening a notebook over successive turns. A generated
podcast plays in-page (and downloads) with a subtitle-style transcript: a timecode per line, click
a line to seek to it, and the line being spoken is highlighted as it plays. A ⚙ settings page
carries the output language and the two podcast voices (presentation settings only — no keys, no
safety bounds). See `rlm_notebook/web/DESIGN.md` and AGENTS.md invariants 29-58, plus 70-72 for the
Trajectory drawer, where a run's reasoning lives: every planner turn in the model's own
words, a tool timeline scaled to real elapsed time, the token budget, and what the
validator rejected before accepting the answer.

## What this is not (yet)

This is not the whole design. In particular: there is no provider-swappable LLM configuration
beyond what `rlm-harness`'s own environment variables already give you, no generated Video Overview,
no directly-uploaded audio/video file ingestion or full audio transcription (YouTube's own
CAPTIONS are supported — see above — but that's captions only, never a transcribed audio track),
no ATLAS rubric/eval/RL-export member (unlike this project's sibling tools), no authentication of
any kind on the HTTP API (see above), and no desktop app packaging (Tauri is the intended eventual
shell, not yet built). Those are follow-up work.

## Licensing

`rlm-notebook` itself is MIT (`LICENSE`). PDF ingestion (`parsers/pdf.py`) uses `pypdfium2`
(BSD-3-Clause/Apache-2.0) — an earlier version of this project used `pymupdf`/`pymupdf4llm`
instead, which are dual-licensed AGPL-3.0-or-a-paid-Artifex-commercial-license; that dependency
was replaced, not merely disclosed, once the conflict with this project's own MIT license (and its
HTTP API, meant to run as a network service) was found — see AGENTS.md invariant 7.

The default TTS provider, `edge-tts` (`tts.py`), is LGPLv3. LGPL generally permits an unmodified
dependency relationship from a permissively-licensed program without forcing that program under
LGPL itself; this is common, low-risk practice, named here rather than left undisclosed.
