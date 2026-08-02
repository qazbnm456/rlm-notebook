# rlm-notebook

`rlm-notebook` reads sources of any kind — plain text, web pages, PDFs (including scanned/OCR'd
ones) — and uses an RLM ([`rlm-kit`](https://github.com/qazbnm456/rlm-kit)) to answer questions
grounded in them, with a citation you can check back against the original text yourself.

**Status: five slices in.** Ingestion (text/web/PDF, with local hybrid OCR for scanned pages),
citation-grounded chat, a persistent multi-turn notebook, a Notebook Guide (summary/FAQ/
timeline/key-insight generation), and an Audio Overview (two-host podcast script + synthesized
speech) are all driveable from the command line — and now also from an HTTP API (`ask`/`guide`,
each run isolated in its own cancellable subprocess). Not yet built: a browser UI, an `/audio` API
endpoint, and SSE/progress streaming. See `CLAUDE.md` for the hard invariants this project is
built against.

## Install and run

```bash
git clone https://github.com/qazbnm456/rlm-notebook && cd rlm-notebook
uv sync                       # installs the local OCR backends scanned PDFs need too — no extra flag
cp .env.example .env          # then fill in RN_MAIN_MODEL / RN_API_KEY
set -a; . ./.env; set +a      # nothing auto-loads .env
brew install deno             # the sandbox a live run executes in
```

```bash
# ask a one-off question grounded in one or more sources — nothing is saved
uv run rlm-notebook ask "what does the source say about X?" \
    --source ./paper.pdf \
    --source https://example.com/article \
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
the flag is surfaced alongside the answer rather than blocking it, for as long as that source
stays part of the notebook.

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
needs no API key; set `RN_TTS_PROVIDER`/`RN_TTS_VOICE_HOST_A`/`RN_TTS_VOICE_HOST_B` in `.env` to
change voices (see `.env.example`).

## HTTP API

**No authentication of any kind.** Any caller that can reach this API can create/read/ask/cancel
against ANY notebook id — there is no concept of an owner. Run it only on `localhost` or an
otherwise fully-trusted network; do not expose it to the internet or a shared network as-is.

```bash
uv sync --extra api                                    # installs fastapi + uvicorn
uv run uvicorn rlm_notebook.api:app
```

```bash
# --source accepts URLs only here (not local paths — see CLAUDE.md invariant 26); use the CLI
# above for a local file.
curl -X POST localhost:8000/notebooks/mynb/sources -d '{"sources": ["https://example.com/article"]}'
curl -X POST localhost:8000/notebooks/mynb/ask -d '{"question": "what does it say about X?"}'
curl -X POST localhost:8000/notebooks/mynb/guide/summary
curl -X POST localhost:8000/notebooks/mynb/audio         # podcast script + base64-encoded MP3
curl -X POST localhost:8000/notebooks/mynb/cancel        # cancel that notebook's in-flight run
```

Every `ask`/`guide` request runs its `RLMTask` in its own isolated, killable subprocess — unlike
`cli.py`'s in-process invocation — so one slow or stuck request can't block another, and can be
cancelled outright. `/audio` is two host-side steps: script generation runs the same isolated-
subprocess way (and is the only half that's cancellable), then TTS synthesis runs in-process
afterward — no audio is ever persisted to disk, the response is JSON with the audio base64-encoded
in it. No SSE/progress streaming yet — a request blocks until its subprocess finishes or
`RN_RUN_TIMEOUT_SECONDS` (default 300s) elapses. See `api.py`'s module docstring and CLAUDE.md
invariants 20-29.

## Web UI

Once the server above is running, open `http://localhost:8000/` in a browser: a real end-user
product surface (source management, citation-grounded chat, a Studio panel with Guide tabs and a
podcast player), not a developer trace console. Zero build step — it's served directly out of
`rlm_notebook/web/` by the same FastAPI app. Paste-text and file-upload source ingestion are
visible but say plainly they're not connected to the API yet, rather than silently failing. A live
view into a run's own reasoning (fused with citations) is designed but deliberately not built yet —
see `rlm_notebook/web/DESIGN.md` and CLAUDE.md invariant 29.

## What this is not (yet)

This is not the whole design. In particular: there is no provider-swappable LLM configuration
beyond what `rlm-kit`'s own environment variables already give you, no generated Video Overview,
no Guide/Audio panel in the web UI yet, no `/audio` API endpoint, and no progress streaming or a
live view into a run's reasoning. Those are follow-up work.
