# The playground: shipping your web UI as a static product page

`playground/` builds a **no-server, single-page, fully interactive demo** of `rlm-notebook` from the
web UI this repo already ships and the notebooks on the author's own machine. Output is a directory
of static files; it is deployed under a personal domain
([`www.boik.tw/rlm-notebook/`](https://www.boik.tw/rlm-notebook/)) so the product page and its author
share an origin.

```
uv run --extra api python playground/build.py     # -> playground/dist/
node playground/smoke.mjs                          # headless check, no browser needed
python3 -m http.server -d playground/dist 8899     # then open http://127.0.0.1:8899/
```

## Why this shape

`rlm-notebook` is hard to install for a curious stranger: Python, a model key, a Deno sandbox, an
optional OCR stack. Most people who would like it will never get far enough to see it. A product
page that only *describes* it converts almost nobody; a page they can **use** converts by letting
them do the thing.

The reference for the interaction model is [witr's playground](https://pranshuparmar.github.io/witr/):
a simulated product with a guided tour, a scenario switcher and an install modal, all honestly
labelled as simulated. That page is **hand-written** — a separate implementation of the real TUI.

**This one is not, and that is the whole design.** `app.js`, `style.css` and `i18n.js` are copied
BYTE-FOR-BYTE out of `rlm_notebook/web/`, and the demo runs them. Consequences:

- A screenshot of the playground is a screenshot of the product. It cannot flatter it.
- It cannot rot into a mock-up of a UI we no longer ship — the next build takes whatever the app
  currently is.
- New product features appear in the demo for free. The maintenance cost is a rebuild.

## How it works: three interception points

`app.js` reaches the network in exactly three ways, and `src/shim.js` replaces all three **before**
`app.js` is evaluated. That count is what makes this approach viable — at thirty entry points,
forking the UI would be cheaper.

| # | Surface | Why it needs its own seam |
|---|---|---|
| 1 | `window.fetch` | every `api()` call — ~18 endpoints |
| 2 | `window.EventSource` | the live reasoning-trace stream |
| 3 | `HTMLMediaElement.prototype.src` | the podcast `<audio>` — a browser-issued request `fetch` never sees |

**Script order is the contract.** `app.js` holds no reference to these globals; it calls them at
request time. Replacing them first is both sufficient and necessary. `build.py` injects
`tour.js` → `shim.js` → `i18n.js` → `app.js` → `chrome.js`; do not reorder.

## The rule that keeps it honest

**Nothing in the demo is invented.** Every pixel is either the shipped UI or output a model really
produced:

- **Notebooks** are real, and the API responses are computed at build time by the **real Python** —
  `api._notebook_response`, so every citation is verified by `citations.py` itself and every
  `answer_span` located by `locate_answer_spans`. The fixture *is* the response. No JavaScript
  re-implementation exists to drift from it.
- **Reasoning traces** are real `traces/*.jsonl` files from runs that actually happened, decomposed
  by the real `trajectory.build_trajectory` and translated by the real `api._translate_trace_event`.
  The ticker shows the model's own words.
- **Where there is no artifact, the demo says so.** Only the overview is persisted onto a notebook
  (invariant 38), so Studio's Timeline and Insight tabs have no recorded output — they render an
  honest note instead of a fabrication. A reader cannot tell a made-up artifact from a real one,
  which is exactly why there are none.
- **A source added in the playground is labelled simulated**, because nothing was fetched or parsed.

Two things are deliberately reduced rather than reproduced: ingested source text is capped
(`MAX_SOURCE_CHARS`) so a public page does not rehost whole third-party articles, and audio is
trimmed (`--audio-seconds`) so the page is not 14MB.

**Pick the default scenario deliberately.** `SCENARIOS[0]` is what a first-time visitor lands on. One
notebook here predates `instructions.NATURAL_REGISTER` and carries thirteen instances of the calque
that rule prevents; it still ships, but it does not greet anybody.

## What the build needs, and what it cannot reproduce

**`notebooks/` and `traces/` are gitignored** — they are run artifacts, not source — so `build.py`
reads data that exists only on the machine that generated it. A fresh clone can run `smoke.mjs`
against an existing `dist/`, but it cannot rebuild one without first generating notebooks of its own.

That is deliberate (committing them would put several megabytes of third-party article text into the
source repo), and it has a consequence worth stating: **the published `dist/` in the Pages repo is
the artifact of record.** Regenerating the demo data from scratch produces a different, equally real
playground, not a byte-identical one.

Two things follow for the demo data itself:

- **Generate through the API, not the CLI.** The CLI writes a trace only when asked (`--trace PATH`,
  invariant 34); the API always does. No trace means an empty Trajectory drawer, which is one of the
  three demos the page leads with. Three notebooks here were first built via the CLI and had to be
  given a traced run afterwards.
- **Cover the tiers on purpose.** A notebook holds ONE episode (invariant 42), so demonstrating
  short/default/long takes three notebooks per language. `smoke.mjs` asserts the matrix.

## Verifying without a browser

This repo has no JavaScript test runner (invariant 36's known gap) and the playground has no server,
so `smoke.mjs` stubs the handful of web globals, loads `tour.js` + `shim.js` exactly as the page
does, and drives every endpoint. **It extracts the endpoint list from `app.js` rather than hardcoding
one**, so a new `api()` call site in the product fails the smoke test instead of 404ing in front of a
reader.

It has already earned that: it caught note ids being strings (`n1`) where the shim assumed integers,
and `GET /notebooks` returning `sources`/`turns` where the picker reads `source_count`/`turn_count` —
a mismatch that renders "undefined sources" rather than failing, which no status-code check finds.

## Deploying

The output is plain static files with no build step and no absolute paths, so it drops into any
static host at any sub-path:

```
uv run --extra api python playground/build.py \
    --deploy ~/Documents/qazbnm456.github.io/rlm-notebook
```

`--deploy` MIRRORS rather than merges — it replaces the target directory, because a stale file left
from a previous build is exactly what makes a static site serve a mix of two versions.

`build_index()` rewrites `/style.css` → `./style.css`; the app's paths are absolute because the
server mounts assets at the root, and a Pages sub-directory is not the root.

## Reusing this for another project

The pattern transfers to any project with a web UI and a narrow client-server seam:

1. **Count the network entry points.** Grep for `fetch(`, `EventSource`, `WebSocket`, `.src =`,
   `XMLHttpRequest`. If it is a handful, shim them. If it is not, fix that first — a UI with one
   choke point is easier to test and to demo.
2. **Never fork the UI.** Copy it verbatim in the build. The moment you edit a copy, the demo starts
   lying and you own two codebases.
3. **Compute the fixtures with the real server code**, not by hand and not in the front-end language.
   That is what makes the demo's checkmarks mean the same thing the product's do.
4. **Ship recorded reality, and label every gap.** The value is that a stranger sees what the product
   actually does; one fabricated artifact costs the whole page its credibility.
5. **Write the headless smoke test**, and derive its endpoint list from the UI source.
