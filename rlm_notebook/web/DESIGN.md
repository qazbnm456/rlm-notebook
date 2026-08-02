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
- **JetBrains Mono** — reserved ONLY for the (currently unbuilt, blueprint §5.5) reasoning-trace
  panel, the one deliberate callback to the sibling studios' technical identity, kept exactly where
  the product intentionally echoes a developer-console reading and nowhere else (`.trace-face` class
  reserved for it, unused in Phase 1).

## 5. Components

### 5.1 Header
Wordmark (`rlm-notebook`) left. Center: the notebook switcher — a text input with a `<datalist>`
populated from `GET /notebooks`, an `Open` button (Enter also submits). A notebook that doesn't exist
yet opens as an empty, unpersisted one, matching `notebook.load_or_create`'s own semantics — it becomes
real the first time a source is added. Right: the Paper/Study theme toggle (`☀`/`☾`).

### 5.2 Sources (left rail, ~280px)
A kind-agnostic "Add source" form: URL / paste-text / file tabs (blueprint §7 — built extensible now
so a future video/audio ingestion slice doesn't need a UI rework). Only the URL tab is wired to the
API in Phase 1 (`POST /notebooks/{id}/sources` accepts http(s) URLs only, CLAUDE.md invariant 26);
paste-text and file both surface an honest "not wired yet" message rather than silently failing or
pretending to work. Below: the source list, one `.source-item` per source — kind, origin (word-broken,
never truncated into an unreadable middle), and any `flags` from `injection_scan.py` shown as an amber
warning line, never hidden and never blocking (CLAUDE.md invariant 6).

### 5.3 Chat (center, fills remaining width)
Turn history, oldest first, scrolled to bottom on append. A question renders as a right-aligned
accent-filled bubble; an answer renders left-aligned in a bordered well, with citations rendered inline
per §2 plus a compact citation list below (source id + locator, a checkmark or an "unverified" flag).
A pending turn (the model is still running — this is a real, potentially tens-of-seconds-long RLM
loop, invariant 21) shows "Thinking…" in muted italic rather than a blank gap. An error surfaces
in-place as `(error) <message>`, never a silent disappearance of the question the user just asked.

### 5.4 Studio (right rail, ~340px)
Two sections, Phase 2: Guide tabs (`Summary | FAQ | Timeline | Insight`, matching `guide/{kind}`'s
four kinds) above a fixed "Audio Overview" section below. A tab's content is fetched ONLY on first
activation or an explicit `↻ Regenerate` click — never automatically, including on notebook open —
since a guide run is a real RLM loop and re-running it for free would burn a model call for
nothing; results are cached client-side per notebook, invalidated on both a notebook switch AND a
source being added (a cached Guide result is stale the instant the corpus it was computed from
changes). `summary`/`insight` reuse `renderAnswerWithCitations` verbatim (same citation-highlighter
treatment as Chat); `faq` renders one `.guide-item` block per Q/A pair; `timeline` renders one
`.guide-item` per `{when, description}` event. Below: a `Generate podcast` button — `POST
.../audio` runs a real RLM script-generation loop THEN a real network TTS call in series, so this
is now the single slowest action in the product, with its own pending copy saying so — producing an
`<audio controls>` element (backed by a `Blob`/`ObjectURL`, not a `data:` URI, so a multi-MB episode
doesn't sit fully base64-encoded in a DOM attribute for its whole lifetime) plus a transcript below
it, one `.podcast-utterance` per line with the same citation-highlighter treatment. Does not yet
collapse-when-empty (still deferred — no phase has needed it yet).

### 5.5 States
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

## 6. Depth / motion

Minimal: 1px hairline borders between surface steps, `var(--radius)` (6px) on interactive elements,
no glassmorphism, no marketing gradients. The header uses a subtle `backdrop-filter: blur` over a
translucent background, matching the sibling studios' sticky-header treatment. No motion beyond
default browser focus/hover states in Phase 1 — Phase 3's live reasoning ticker (deferred, blueprint
§5.5) is where a real motion signature belongs, not this phase's static panels.

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
citation's surrounding prose is faithful to the source, only that its coordinates resolve; don't build
the reasoning-trace/live-ticker surface here — it's deliberately deferred (blueprint §5.5) until its
own redesign lands; don't collapse the Studio panel yet — no phase has needed it yet; don't
auto-fetch a Guide kind on notebook open or on a bare tab switch — only first activation or an
explicit regenerate; don't use a `data:` URI for the podcast player — a `Blob`/`ObjectURL` instead,
revoked in the correct order (assign the new URL before revoking the old one, never the reverse).

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
