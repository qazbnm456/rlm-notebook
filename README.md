# rlm-notebook

`rlm-notebook` reads sources of any kind — plain text, web pages, PDFs (including scanned/OCR'd
ones) — and uses an RLM ([`rlm-kit`](https://github.com/qazbnm456/rlm-kit)) to answer questions
grounded in them, with a citation you can check back against the original text yourself.

**Status: first slice.** Ingestion (text/web/PDF, with local hybrid OCR for scanned pages) and
citation-grounded chat are implemented and driveable from the command line. Not yet built: session
persistence across turns, a Notebook Guide (summary/FAQ/timeline), an Audio Overview, and an API/UI.
See `CLAUDE.md` for the hard invariants this project is built against.

## Install and run

```bash
git clone https://github.com/qazbnm456/rlm-notebook && cd rlm-notebook
uv sync --extra ocr           # the `ocr` extra installs the local OCR backends scanned PDFs need
cp .env.example .env          # then fill in RLM_MAIN_MODEL / RLM_API_KEY
set -a; . ./.env; set +a      # nothing auto-loads .env
brew install deno             # the sandbox a live run executes in
```

```bash
# ask a question grounded in one or more sources
uv run rlm-notebook ask "what does the source say about X?" \
    --source ./paper.pdf \
    --source https://example.com/article \
    --source ./notes.txt
```

Every answer comes back with citations of the form `source_id` + `locator` (a page number, a
paragraph, or a character offset, depending on the source type) that resolve to real text in the
notebook — verified against the source, not just claimed by the model. A citation that doesn't
resolve is marked unverified rather than silently dropped or silently trusted.

Sources with a flagged prompt-injection pattern (see `injection_scan.py`) still answer normally;
the flag is surfaced alongside the answer rather than blocking it.

## What this is not (yet)

This is a single vertical slice, not the whole design. In particular: there is no multi-turn
conversation memory (each `ask` is independent), no generated Podcast-style audio overview, no
provider-swappable TTS/LLM configuration beyond what `rlm-kit`'s own environment variables already
give you, and no web UI. Those are follow-up work.
