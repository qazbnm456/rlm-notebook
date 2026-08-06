# rlm-notebook web UI: visual & UX spec

The web frontend's design contract. Implementation (`index.html`/`style.css`/`app.js`) follows this
file. Architecture and the full decision record (why this exists, what was audited, what's deferred)
live in `docs/design/web-ui-blueprint.md` and `CLAUDE.md` — this file owns *look and feel* only, the
same split `ctx-distillery/studio/DESIGN.md` established for the sibling family.

**This is NOT a replay-only trace console, unlike every sibling's `studio/`.**
`ctx-distillery`/`cve-reverser`/`diff-sentry`/`toolscout` each ship a single-verdict security/review
console: one input, one derived-state card, a live action feed, a Trajectory replay drawer. This is a
persistent, multi-notebook, multi-turn knowledge workspace instead — many notebooks, many ingested
sources, a saved chat history, human-readable output artifacts meant to be read. The divergence from
the family pattern is a recorded decision (see the blueprint's §0), not an oversight.

## 1. Theme

A NotebookLM-shaped three-pane knowledge workspace, with an original visual identity rather than a
Material clone. Warm editorial calm: ink-on-paper in Paper (light, default), a reading-lamp-at-night
warmth in Study (dark) — never the siblings' cool blue-slate security-console dark. Energy: focused,
legible, unhurried. Not playful, not corporate, not a terminal.

Utility mode (no marketing hero): orient (header + notebook switcher) → sources (rail) → converse
(chat, center) → produce (Studio panel, right — Guide tabs + podcast player as of Phase 2).

## 2. The signature: citation as highlighter stroke

A citation renders as a highlighter-wash span (`.citation`, `--highlight-wash` + a 2px
`--highlight-border` underline), inline in the answer text itself, not a footnote number appended
after it. This is the literal visual expression of the product's core value: grounded, verifiable
text. The underline exists specifically because the wash's own luminance separation from an arbitrary
surface step is not reliably perceptible alone — verified computationally during the pre-implementation
design audit (Study mode's wash over `--surface-3` measured self-contrast ≈1.0, i.e. invisible, before
the fix) — so perceptibility never depends on the wash alone.

An unverified citation (`citations.py` could not resolve its coordinates against the current corpus)
gets a dashed `--bad`-colored underline instead of the solid accent one — flagged, never silently
dropped, the same discipline `injection_scan.py`'s flags already use elsewhere in this project.

## 3. Palette

Two full, first-class OKLCH palettes, `[data-theme="light"]` (Paper, default) and
`[data-theme="dark"]` (Study), toggled from the header, persisted in `localStorage`, seeded from
`prefers-color-scheme` on first visit — same mechanism the sibling studios already use. **Live tokens
are `style.css`'s `:root` blocks — source of truth**; the values below are design intent.

```
/* Paper (light, default) */
--bg:#f9f7f4(≈)  --surface-1..3 step down in warmth  --border / --border-strong
--text:(deep ink navy, oklch 22% 260)  --text-dim  --text-faint:(oklch 46% 260 — corrected, see below)
--accent:(copper, oklch 62% .16 55)  --highlight-wash:(warm cream wash)  --highlight-border:(=accent)
--studio-accent:(muted sage, oklch 55% .05 165)
--ok / --warn / --bad
```

```
/* Study (dark) — a reading lamp at night, not a security terminal */
--bg:(warm near-black, oklch 20% .015 55)  --surface-1..3 step up in warmth
--text:(warm cream, oklch 93% .015 75)  --text-dim  --text-faint:(oklch 70% 75 — corrected, see below)
--accent:(brightened copper, oklch 75% .15 55)  --highlight-wash:(oklch 50% .08 70 / .65 — corrected)
--studio-accent / --ok / --warn / --bad, same hue family as Paper for brand continuity
```

**Both `--text-faint` values and Study's `--highlight-wash` were corrected during the
pre-implementation audit** — the originals measured 3.08:1 (Paper) and 2.97:1 (Study) against
`--surface-3` (WCAG AA's floor is 4.5:1 for normal text), and the original wash was self-contrast ≈1.0
against an elevated panel. See `docs/design/web-ui-blueprint.md`'s audit round 1 for the computed
values behind the fix.

**Accent discipline** (same "do not cross-use" rule the siblings enforce): `--accent` only on
interactive elements and the citation highlighter; `--studio-accent` only inside the Studio panel,
separating "converse" mood from "produce" mood visually; surfaces step 1→2→3, never two same-tone
panels touching.

## 4. Typography

Font-selection procedure run explicitly (not a reflex pick — Fraunces/Inter/JetBrains-Mono-everywhere
were all considered and rejected first):

- **Literata** — content meant to be read at length: the full source-text viewer (still not built —
  see the deferred items below). Reserved via the `.reading-face` class; NOT yet applied to Guide/
  podcast content either, since Phase 2 reused `renderAnswerWithCitations`'s existing Public Sans
  treatment for consistency with Chat rather than introducing a font switch mid-panel — worth
  reconsidering once a dedicated long-form reading surface exists. Commissioned by Google originally
  for on-screen long-form reading (Google Play Books); the one typeface actually designed for what
  this product asks a reader to do, once something actually uses it.
- **Public Sans** — all UI chrome: nav, labels, buttons, form fields, the chat turns themselves. US
  Web Design System typeface, built around clarity/accessibility/trust — thematically aligned with a
  citation-verifiable-truth product. The body default (`body { font-family: "Public Sans", ... }`).
- **JetBrains Mono** — the one deliberate callback to the sibling studios' technical identity, kept
  exactly where the product intentionally echoes a developer-console reading: Phase 3's reasoning
  ticker (`.ticker-toggle`/`.ticker-detail`) and the citation-turn detail payload
  (`.citation-detail-payload`) — nowhere else. The `.trace-face` class reserved for it in Phase 1/2
  went unused until Phase 3 actually needed it.

## 5. Components

### 5.1 Header
Wordmark (`rlm-notebook`) left. Center: the notebook switcher — a text input with a `<datalist>`
populated from `GET /notebooks`, an `Open` button (Enter also submits). A notebook that doesn't exist
yet opens as an empty, unpersisted one, matching `notebook.load_or_create`'s own semantics — it becomes
real the first time a source is added. Right: the Paper/Study theme toggle (`☀`/`☾`).

### 5.2 Sources (left rail, ~280px)
A kind-agnostic "Add source" form: URL / paste-text / file tabs (blueprint §7 — built extensible so
a future video/audio ingestion slice doesn't need a UI rework). All three are wired to the API: URL
posts to `POST /notebooks/{id}/sources` (`{sources: [...]}`, http(s) only — CLAUDE.md invariant 26
stays exactly as strict; a YouTube link is ingested transparently by the SAME field, dispatched
server-side by `ingest.ingest_one` — no separate UI affordance needed, just a `<p class="hint">`
under the URL input naming that YouTube links work and are captions-only, per invariant 33),
paste-text posts to the SAME endpoint with `{texts: [...]}` (a post-launch addendum — see
`docs/design/web-ui-blueprint.md`'s "Post-launch addendum"), and file upload POSTs
`multipart/form-data` to `POST /notebooks/{id}/sources/upload` (`.pdf`/`.txt`/`.md`, one file per
request) — never a local-path string, which is what keeps it from reopening invariant 26's
local-path ban. Below: the source list, one `.source-item` per source — kind, origin
(word-broken, never truncated into an unreadable middle; a pasted text's origin is a readable
snippet plus a content hash, an uploaded file's origin is its filename, a YouTube source's origin
is the video URL itself), and any `flags` from `injection_scan.py` shown as an amber warning line,
never hidden and never blocking (CLAUDE.md invariant 6). Clicking a `.source-item` opens the
source-viewer modal (§5.7) for that source, no highlight target — a YouTube source's blocks render
there with their `"ts:<mm:ss>"` locators, the same as any other source's blocks.

### 5.3 Chat (center, fills remaining width)
Turn history, oldest first, scrolled to bottom on append. A question renders as a right-aligned
accent-filled bubble; an answer renders left-aligned in a bordered well, with citations rendered inline
per §2 plus a compact citation list below (source id + locator, a checkmark or an "unverified" flag).
Each citation-list row is itself clickable — opening the source-viewer modal (§5.7) with that
citation's block highlighted — regardless of whether its `quote` matched inline in the answer text;
a row also carries a secondary `⌁ trace` icon (only when a run id is known) that opens the Phase 3
trace detail (§5.5) instead, stopping the row's own click from also firing.
A pending turn (the model is still running — this is a real, potentially tens-of-seconds-long RLM
loop, invariant 21) shows LIVE, updating copy from the Phase 3 reasoning ticker (§5.6) in place of a
static "Thinking…" — the ticker is a secondary, opt-in layer; losing it (a dropped SSE connection)
never blocks the request, which remains the sole source of the final answer. An error surfaces
in-place as `(error) <message>`, never a silent disappearance of the question the user just asked.

### 5.4 Studio (right rail, ~340px)
Three sections: Guide tabs (`Summary | FAQ | Timeline | Insight`, matching `guide/{kind}`'s four
kinds, Phase 2) above a fixed "Audio Overview" section (Phase 2), above a "Notes" section
(Post-launch addendum 4) at the bottom. A tab's content is fetched ONLY on first activation or an
explicit `↻ Regenerate` click — never automatically, including on notebook open — since a guide
run is a real RLM loop and re-running it for free would burn a model call for nothing; results are
cached client-side per notebook, invalidated on both a notebook switch AND a source being added (a
cached Guide result is stale the instant the corpus it was computed from changes). `summary`/
`insight` reuse `renderAnswerWithCitations` verbatim (same citation-highlighter treatment as Chat);
`faq` renders one `.guide-item` block per Q/A pair; `timeline` renders one `.guide-item` per
`{when, description}` event. Below: a `Generate podcast` button — `POST .../audio` runs a real RLM
script-generation loop THEN a real network TTS call in series, so this is now the single slowest
action in the product, with its own pending copy saying so — producing an `<audio controls>`
element (backed by a `Blob`/`ObjectURL`, not a `data:` URI, so a multi-MB episode doesn't sit fully
base64-encoded in a DOM attribute for its whole lifetime) plus a transcript below it, one
`.podcast-utterance` per line with the same citation-highlighter treatment. Does not yet
collapse-when-empty (still deferred — no phase has needed it yet). Notes section: see §5.8.

### 5.5 Reasoning-trace ticker + citation-turn detail (Phase 3)

Every `ask`/Guide-tab/podcast-generate call picks its OWN run id client-side (`crypto.randomUUID()`,
prefixed with the notebook id — the client, never the server, since a server-generated id would
never reach the page until the request was already over) and opens a live SSE ticker against it
alongside the actual request. While pending, the ticker's translated `{kind, summary}` events
replace the static "Thinking…"/"Generating…" copy with live-updating copy in the SAME slot — this
is not a new UI element, just a livelier version of an existing one. Once the request settles, the
ticker log (already held in memory, nothing re-fetched) collapses into a small `⌁ N steps`
pill (`.ticker-toggle`) that expands a plain-text log (`.ticker-detail`) on click.

Every citation span with a known run id becomes clickable (`.citation-clickable`): clicking it
calls `GET .../citation-turn` and fills a single shared `.citation-detail` slot per answer (not one
per citation — clicking a different citation replaces the previous detail rather than
accumulating) with the raw trace-event payload, monospaced, and an explicit note that this shows
WHERE the model read the source, never a faithfulness proof (CLAUDE.md invariant 5's limit,
restated here rather than let the UI imply something stronger). A turn with no `run_id` (saved
before this field existed) simply has no clickable citations — a graceful, silent degradation, not
a broken link.

### 5.6 States
| state | what shows |
|---|---|
| no notebook opened | Sources: empty-note. Chat: empty-note. Studio: "pick a tab" prompt, no podcast section content. |
| notebook opened, no sources | Sources: empty-note under the add-source form. Chat: empty-note. |
| notebook opened, sources but no turns | Sources: list. Chat: empty-note ("ask a question…"). |
| a question in flight | Chat: the question bubble + a "Thinking…" pending answer; ask form disabled. |
| ask fails | Chat: the question bubble + an inline `(error) …` line; ask form re-enabled. |
| a Guide tab generating | Studio: "Generating…" in muted italic where the content will render. |
| a Guide tab's sources produced nothing (empty FAQ/timeline) | Studio: an explicit "(no … — the sources didn't produce enough to …)" message, never a blank body. |
| a Guide fetch fails | Studio: an inline `(error) …` line in the tab body. |
| podcast generating | Studio: "Generating script and synthesizing audio — this can take a while…" in muted italic; the Generate button is disabled. |
| podcast script has no utterances | Studio: "(no podcast script — the sources didn't produce enough to discuss)", no player. |
| podcast generation fails (script OR synthesis) | Studio: an inline `(error) …` line; the Generate button re-enables. |
| a run in flight, ticker connected | The pending slot's copy updates live from translated trace events instead of staying static. |
| a run's ticker drops (SSE error/close) | The pending slot simply stops updating — the request itself is unaffected and still resolves normally. |
| a completed turn/tab/episode with a known run id | A `⌁ N steps` pill appears; clicking expands the plain-text event log. |
| a citation clicked (run id known) | A shared detail slot below the answer fills with the matching trace turn's payload, or an inline `(error) …`/"not found" message. |
| a citation clicked (no run id — a pre-Phase-3 saved turn) | Nothing — the citation simply isn't clickable, no broken affordance shown. |
| a citation row or source item clicked | The source-viewer modal opens with "Loading…", then the source's full text with the matching block highlighted and scrolled into view (no highlight if opened from the Sources panel). |
| the source viewer's fetch fails | The modal body shows an inline `(error) …` message; the modal itself stays open (closable normally). |
| the source viewer is closed and reopened for a different source before the first fetch resolves | The first fetch is aborted; only the second open's response ever renders. |
| notebook opened, no notes | Notes section: empty-note under the add-note form. |
| a note added (manually, or via "+ Save as note") | Notes section: the new `.note-item` appears in the list; the add-note textarea clears on success. |
| a note promoted to a source | It disappears from Notes and a new item appears in Sources — both re-rendered from the same response; if the text was already an identical source, only the note disappears (no duplicate source). |
| a note deleted | It disappears from the Notes list; no confirmation prompt (matches every other non-destructive-feeling list-item removal in this UI). |
| a note action (promote/delete) fails | An `alert()` names the error, matching the Sources panel's own failure surface; the button re-enables. |

### 5.7 Source viewer modal (Post-launch addendum 2)

NotebookLM's most basic closed loop: click a citation, see the highlighted original passage — not
just the reasoning trace. The first stacking-context component in this codebase's `web/`
(`.modal-overlay`/`.modal`, an explicit `z-index` rather than relying on paint order), opened from
a citation-list row (§5.3, with a highlight target) or a `.source-item` (§5.2, no highlight
target). Fetches `GET /notebooks/{id}/sources/{source_id}` and renders every block as a labelled
`.source-block` section; the block whose `locator` matches the opening citation gets its `quote`
highlighted with the SAME `.citation` styling §2 uses inline, and is scrolled into view. Closes via
a `✕` button, a backdrop click, or `Esc` — the same family convention the sibling projects' own
`studio/`s already use for their trace-replay drawers. Each open aborts any still-in-flight fetch
from a PREVIOUS open (`AbortController`, module-level `sourceViewerAbort`) so a slower first
response can never overwrite a faster second one's render. Also closes on `notebook:switched`, like
every other stateful surface in this product. Does not paginate, cache across opens, or support
next/prev-citation navigation — each open is a fresh fetch, deliberately (§8's Don't list has the
same scope cut written out).

### 5.8 Notes section (Post-launch addendum 4)

NotebookLM's research-loop closing feature: a manual note, or a Chat answer saved as one, can
later be promoted into a real, independently-citable source. Lives at the bottom of the Studio
panel (§5.4), below Audio Overview — a `.notes-section` with the same `.panel-head` + form + list +
empty-state shape the other Studio sections already use, not a new fourth top-level column. A
`.note-item` shows the note's text plus two actions: `→ Promote to source`
(`POST .../notes/{id}/promote`) and `✕` delete (`DELETE .../notes/{id}`) — both re-render Sources
and/or Notes from the mutating endpoint's own returned `NotebookResponse`, the same "the response
IS the new state" pattern the Sources panel's add-source form already uses.

Every Chat answer (`renderTurn`, §5.3) carries a `+ Save as note` button — added by `renderTurn`
ITSELF, never inside the shared `renderAnswerWithCitations`, which five OTHER call sites (every
Guide kind, the podcast transcript) also use and must never show this button on. Posts the
answer's own already-in-hand text to `POST /notebooks/{id}/notes`, no DOM scraping or re-fetch.

A note carries no citations of its own and is never re-verified against `sources` (CLAUDE.md
invariant 5's coordinate-only guarantee doesn't extend to freeform notes) until it's promoted —
nothing in this section's UI should imply a note is "grounded" before that point.

### 5.9 Chat overview — the "generate the research artifact" action (Post-launch addendum 5)

`#chat-overview`, a block ABOVE `#chat-history` (never inside it: `ask` rebuilds the history list
wholesale from `state.turns` after every answer, which would wipe anything else in there).

Two states, one container:

- **No overview yet, sources present** — a primary `✨ Generate overview` button plus the hint
  "…or just ask a question below."
- **Generated** — `Overview` head, the Summary rendered through `renderAnswerWithCitations` (so its
  citations behave exactly like a Chat answer's), the trace affordance, then `Start with` and up to
  three clickable starter questions taken from the FAQ task.

Hidden entirely when the notebook has no sources. Bounded at `max-height: 45%` with its own scroll:
a Summary runs to several paragraphs, and as an unbounded flex item it would refuse to shrink,
collapse `.chat-history`, and push the ask box off screen.

**Why it exists.** Adding a source used to leave the screen doing nothing — Chat said "ask a
question once you've added a source", Studio said "pick a tab to generate it", and both waited on
the user to discover the next move. The guided feel of a notebook product comes from the artifact
appearing IN the conversation and being something to ask follow-ups about; a Summary buried in a
right-hand tab is disconnected from the thread, so even finding it leads nowhere.

**Still an explicit button, never auto-generated.** §5.4's rule (a guide run is a real RLM loop, so
never spend one nobody asked for) is unchanged — what changed is that the action is obvious rather
than hidden behind a tab.

**Not persisted**, matching every other guide artifact, and invalidated whenever the corpus changes
(the same rule the Studio cache follows: stale the moment the sources it was computed from change,
not just when the notebook does).

## 6. Depth / motion

Minimal: 1px hairline borders between surface steps, `var(--radius)` (6px) on interactive elements,
no glassmorphism, no marketing gradients. The header uses a subtle `backdrop-filter: blur` over a
translucent background, matching the sibling studios' sticky-header treatment. Phase 3's ticker is
deliberately NOT an animated signature — it's plain live-updating TEXT in an existing pending slot,
no spinner, no pulse, no sweep. The one new interaction affordance (`.ticker-toggle`,
`.citation-clickable`) uses only the existing hover/focus language already established for buttons
and tabs, not a new visual language of its own.

## 7. Responsive

Three columns (`280px minmax(0,1fr) 340px`) above 1024px. Two columns (Sources | Chat) with Studio
dropped to a full-width row under Chat between 640px and 1024px. Single-column stack (Sources, Chat,
Studio) below 640px. Matches the family's existing breakpoint convention.

## 8. Do / Don't

**Do**: key citation styling on `verified` (from `citations.py`, coordinate-existence only — see
CLAUDE.md invariant 5), never imply stronger faithfulness than that; flag an unverified citation and
an injection-scan hit, never hide either; show every state explicitly (pending, error, empty) rather
than a blank gap; keep `--accent`/`--studio-accent` non-cross-used.

**Don't**: no Inter, no Fraunces, no centered marketing hero, no purple/blue gradient; don't imply a
citation's surrounding prose is faithful to the source, only that its coordinates resolve, and don't
let the citation-turn detail panel imply a stronger claim either — it shows WHERE the model read
something, never that the surrounding prose is faithful to it; don't collapse the Studio panel yet
— no phase has needed it yet; don't auto-fetch a Guide kind on notebook open or on a bare tab switch
— only first activation or an explicit regenerate; don't use a `data:` URI for the podcast player —
a `Blob`/`ObjectURL` instead, revoked in the correct order (assign the new URL before revoking the
old one, never the reverse); don't let a dropped ticker connection block or alter the actual
request's own result — the ticker is strictly secondary; don't let the source-viewer modal's fetch
skip its `AbortController` guard — a stale response overwriting a fresher one's render is exactly
the class of bug the Phase 3 trace-detail retrofit (§5.5) had to fix after shipping once already;
don't add pagination, cross-open caching, or next/prev-citation navigation to the source viewer —
each open is a deliberately fresh, simple fetch; don't move the "+ Save as note" button into the
shared `renderAnswerWithCitations` — it must appear on Chat answers only, never on a Guide kind or
the podcast transcript, which also call that same function; don't imply a note is grounded or
citable before it's promoted into a real source.

## 9. Acceptance (in a browser)

1. First screen is unmistakably this product: `rlm-notebook` wordmark, a notebook switcher, three
   visible columns, no generic dashboard look.
2. Opening a fresh notebook id shows empty Sources/Chat; adding a URL source populates the Sources
   list and clears the input.
3. Asking a question shows the question bubble immediately, a "Thinking…" pending answer, then the
   real answer with inline highlighted citations and a citation list below it.
4. An unverified citation shows a dashed red underline, not the solid accent one.
5. The theme toggle flips Paper ↔ Study and survives a reload; neither palette shows invisible or
   near-invisible text against any surface step it's used on.
6. No horizontal overflow at 375px; below 640px the three columns stack in Sources → Chat → Studio
   order.
7. Clicking a Studio Guide tab for the first time shows "Generating…" then real content with
   inline citations; clicking a DIFFERENT tab and back shows the FIRST tab's content instantly (no
   second model call) until `↻ Regenerate` is clicked or a source is added.
8. Clicking `Generate podcast` on a notebook with substantive sources shows the "this can take a
   while" pending copy, then a working `<audio controls>` player plus a transcript below it, each
   line highlighted the same way a Chat citation is. Regenerating replaces the player without ever
   leaving two object URLs alive at once (check via a memory profiler or simply confirming the old
   `blob:` URL 404s after regenerating).
9. Asking a question shows LIVE, updating ticker copy in the pending slot (not static "Thinking…")
   while the run is in flight; once it settles, a `⌁ N steps` pill appears next to the answer, and
   clicking it expands a plain-text log of what the ticker showed.
10. Clicking a highlighted citation (in Chat, a Guide tab, or the podcast transcript) shows a
    detail panel with the trace turn where the model read that source — clicking a SECOND citation
    in the same answer replaces the panel rather than stacking a second one below it.
11. Reloading the page and reopening a notebook whose history predates Phase 3 (no `run_id` on
    those turns) shows those old turns with plain, non-clickable citations and no `⌁` pill — a
    graceful degradation, not a broken affordance.
12. Switching to the "Paste text" tab and submitting real text adds a source whose origin is a
    readable snippet, not a bare hash; switching to "File" and selecting a real `.pdf`/`.txt`/`.md`
    file uploads and ingests it, with the Sources list showing the original filename as the origin.
    Selecting an unsupported file type shows a clear `alert()` naming the problem — the same error
    surface every other Sources-panel failure already uses, not a silent failure.
13. Clicking a citation-list row (not just the inline highlighted span) opens the source-viewer
    modal with that source's full text, the matching block highlighted and scrolled into view;
    clicking the row's `⌁ trace` icon instead opens the Phase 3 trace detail, without also opening
    the source viewer. Clicking a `.source-item` in the Sources panel opens the same modal with no
    highlight. `Esc`, the backdrop, or the `✕` button all close it.
14. Typing a note into the Notes section's textarea and submitting adds it to the list and clears
    the textarea; clicking `+ Save as note` on a Chat answer adds a note with that answer's text,
    and the SAME button never appears on a Guide tab's or the podcast transcript's answers.
    Clicking `→ Promote to source` on a note removes it from Notes and adds a matching item to
    Sources; clicking `✕` on a note removes it with no confirmation prompt.
