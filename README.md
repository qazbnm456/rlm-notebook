# rlm-notebook

`rlm-notebook` reads sources of any kind — plain text, web pages, PDFs (including scanned/OCR'd
ones) — and uses an RLM ([`rlm-kit`](https://github.com/qazbnm456/rlm-kit)) to answer questions
grounded in them, with a citation you can check back against the original text yourself.

**Status: three slices in.** Ingestion (text/web/PDF, with local hybrid OCR for scanned pages),
citation-grounded chat, a persistent multi-turn notebook, and a Notebook Guide (summary/FAQ/
timeline/key-insight generation) are implemented and driveable from the command line. Not yet
built: an Audio Overview and an API/UI. See `CLAUDE.md` for the hard invariants this project is
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

## What this is not (yet)

This is not the whole design. In particular: there is no generated Podcast-style audio overview,
no provider-swappable TTS/LLM configuration beyond what `rlm-kit`'s own environment variables
already give you, and no web UI or API. Those are follow-up work.
