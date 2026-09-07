# Invariant 42 — The generated episode is persisted

**A generated Audio Overview from the API is PERSISTED — one file per notebook, served as a real
file.** Scoped to the API on purpose: `cli._cmd_audio` writes `--out` and returns, with no
`Podcast` record and no offsets, so a CLI-generated episode can never have subtitles — correct
for a one-shot CLI whose caller named the output path themselves. The web UI's episode previously
existed only as the browser tab's `Blob`, so a reload lost it.

**One file per notebook (`notebook.audio_path` → `<base_dir>/audio/<slug><suffix>`, the suffix
being the PROVIDER's — invariant 43), replaced on regenerate.** That is what makes retention a
non-question: growth is bounded by how many notebooks exist, not by how many times anyone pressed
the button — unlike `traces/`, which needed invariant 34's whole sweep. A SUBDIRECTORY so
`list_notebook_summaries`' `*.json` glob never sees it.

**The transcript persists on the notebook (`schema.Podcast`); the AUDIO does not go in the JSON.**
A multi-MB base64 blob inside the notebook file would be re-parsed on every read, including every
`GET /notebooks/{id}`. `GET /notebooks/{id}/audio/file` serves it instead, which also lets the
browser range-request it (a `Range` header returns `206`, so seeking does not re-download).

**The audio is written BEFORE the notebook record**, so a crash between the two leaves an orphan
file (harmless — the next generate overwrites it) rather than a notebook pointing at audio that
isn't there. **An empty script is a regenerate too**: that arm clears both the file and the
record, or `GET .../audio/file` keeps serving audio for a script the notebook no longer has.

Same staleness treatment as invariant 38, and citations re-verified against the current corpus on
every read. **`GET .../audio/file` is the FOURTH materially-different exposure in this API** —
with no authentication, anyone who can reach this server can play any notebook's episode.

**The generate button has the same three states the chat overview has**: no episode → a primary
offer; an episode → a QUIETER "Regenerate"; stale → the same button saying the sources moved.
Deliberately NOT primary once an episode exists, because regenerating costs a full model run plus
synthesis (invariant 43). Adding or removing a source re-syncs the BUTTON only — re-rendering the
panel would rebuild its `<audio>` and interrupt playback (invariant 60's `renumberStrokes`
reasoning).

**`renderPodcast` is ONE function serving both the just-generated and the reopened case**, so a
persisted episode can never render differently from a fresh one. It plays from the server URL,
not an object URL. `preload="none"` keeps a multi-MB episode from being fetched on every notebook
open, and the generate path cache-busts the stable URL, or "Regenerate" would look like it did
nothing because the browser still had the previous episode.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
