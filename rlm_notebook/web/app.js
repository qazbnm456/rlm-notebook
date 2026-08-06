// rlm-notebook web UI — zero-build vanilla JS, no framework, no build step (see DESIGN.md).
//
// State: a small hand-rolled evented store, not a state-management library. Event vocabulary is
// PINNED (blueprint §3.1) so later phases don't invent an incompatible convention:
//   notebook:switched  { notebookId }
//   sources:changed    { sources }
//   chat:turnAdded     { turn }
//   chat:pending       { pending }
//   notes:changed      { notes }
//   notebook:titled    { title, notebookId }
// Each pane subscribes only to what it renders from; no pane writes another pane's state directly.

function createStore() {
  const listeners = new Map();
  return {
    on(event, handler) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(handler);
    },
    emit(event, payload) {
      (listeners.get(event) || new Set()).forEach((handler) => handler(payload));
    },
  };
}

const store = createStore();

const state = {
  notebookId: null,
  title: null,
  overview: null,
  sources: [],
  turns: [],
  notes: [],
};

// --- Theme ------------------------------------------------------------------------------------

function initTheme() {
  const toggle = document.getElementById("theme-toggle");
  const stored = localStorage.getItem("rlmnb-theme");
  if (stored) {
    document.documentElement.setAttribute("data-theme", stored);
  }
  updateToggleGlyph();

  toggle.addEventListener("click", () => {
    const current =
      document.documentElement.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("rlmnb-theme", next);
    updateToggleGlyph();
  });
}

function updateToggleGlyph() {
  const toggle = document.getElementById("theme-toggle");
  const current =
    document.documentElement.getAttribute("data-theme") ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  toggle.textContent = current === "dark" ? "☾" : "☀";
}

// --- API helpers --------------------------------------------------------------------------------

async function api(path, options) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.status === 204 ? null : resp.json();
}

// --- Reasoning-trace ticker (Phase 3) --------------------------------------------------------
//
// `ask`, each Guide-tab fetch, and the podcast generate call all pick their OWN run id
// client-side (never trust a server-generated one — it would never reach us until the request
// was already over) and open a live SSE ticker against it before/alongside firing the actual
// request. Reasoning-trace fusion is deliberately a SECONDARY, opt-in layer: the request's own
// response remains the sole source of the final answer/result (unchanged from Phase 1/2) — the
// ticker only replaces static "Thinking…"/"Generating…" copy with live-updating copy, and adds a
// small "view reasoning" affordance afterward. Losing the ticker (a network hiccup, the SSE
// connection dropping) never blocks or breaks the actual request.

//: One client-side log per run id, kept for the lifetime of the page (not just while a stream is
//: open) so a "⌁ N steps" affordance can expand instantly without re-fetching. Shared across
//: Chat/Guide/Podcast rather than three separate caches.
const tickerLogs = new Map();

function openTicker(notebookId, runId, onEvent) {
  const events = [];
  tickerLogs.set(runId, events);
  return new Promise((resolve) => {
    let source;
    try {
      source = new EventSource(
        `/notebooks/${encodeURIComponent(notebookId)}/runs/${encodeURIComponent(runId)}/stream`
      );
    } catch {
      resolve(events);
      return;
    }
    source.onmessage = (message) => {
      let event;
      try {
        event = JSON.parse(message.data);
      } catch {
        return;
      }
      events.push(event);
      onEvent(event);
      if (event.kind === "done" || event.kind === "not_found") {
        source.close();
        resolve(events);
      }
    };
    source.onerror = () => {
      // A dropped connection ends the TICKER, never the request itself — the POST this ticker is
      // attached to keeps running and its own response is still authoritative.
      source.close();
      resolve(events);
    };
  });
}

function renderTickerAffordance(runId) {
  const events = tickerLogs.get(runId) || [];
  const wrapper = document.createElement("div");
  wrapper.className = "ticker-affordance";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "ticker-toggle trace-face";
  toggle.textContent = `⌁ ${events.length} step${events.length === 1 ? "" : "s"}`;

  const detail = document.createElement("div");
  detail.className = "ticker-detail trace-face";
  detail.hidden = true;
  events.forEach((event) => {
    const row = document.createElement("div");
    row.className = "ticker-row";
    row.textContent = event.summary || event.kind || "event";
    detail.appendChild(row);
  });

  toggle.addEventListener("click", () => {
    detail.hidden = !detail.hidden;
  });

  wrapper.appendChild(toggle);
  wrapper.appendChild(detail);
  return wrapper;
}

// Which trace turn (if any) shows the model reading this citation's source span — a heuristic
// lookup (blueprint P3.3), never a faithfulness proof. `detailArea` is a shared slot inside the
// SAME renderAnswerWithCitations() call the clicked span belongs to, so only one detail shows at
// a time per answer rather than accumulating unboundedly.
//
// Staleness guard, added when the source-viewer addendum's own audit found this exact defect
// already present here: opening the trace view for citation A, then quickly for citation B in the
// SAME detailArea, could let A's slower response land after B's and overwrite it with the wrong
// citation's payload. A monotonic token stored directly on `detailArea` — bumped on every call,
// checked before writing the DOM — discards a stale response rather than an AbortController, since
// this is a plain GET with no cleanup the browser needs told about.
async function showCitationTurn(runId, citation, detailArea) {
  // Clicking the SAME citation again collapses the panel, rather than blanking it to "Loading…"
  // and re-fetching the identical payload — which is what it used to do, and read as a flash with
  // nothing ever closing. (An earlier version of this comment justified the change by saying the
  // ticker affordance in this same page "already toggles on re-click". It did not — `.ticker-detail`
  // carried the same display-vs-hidden defect, fixed alongside this. Both now toggle.)
  // Keyed on WHICH citation is showing: clicking a DIFFERENT one while open must switch to it, not
  // close the panel. `quote` is part of the key because `source_id|locator` alone is NOT unique —
  // text and web sources emit a single block with locator "whole", so every citation into one such
  // source shares that pair, and an answer citing it three times would have clicking the second
  // row CLOSE the panel instead of switching. Found by an independent review.
  const key = `${citation.source_id}|${citation.locator}|${citation.quote}`;
  if (!detailArea.hidden && detailArea._shownKey === key) {
    detailArea.hidden = true;
    detailArea._shownKey = null;
    // Bump the token on the way out so an in-flight response can't repopulate a panel the user
    // has just closed (the same staleness guard the fetch below relies on, applied to collapse).
    detailArea._requestToken = (detailArea._requestToken || 0) + 1;
    return;
  }

  const token = (detailArea._requestToken || 0) + 1;
  detailArea._requestToken = token;
  detailArea._shownKey = key;
  detailArea.hidden = false;
  detailArea.textContent = "Loading…";
  try {
    const params = new URLSearchParams({ source_id: citation.source_id, locator: citation.locator });
    const data = await api(
      `/notebooks/${encodeURIComponent(state.notebookId)}/runs/${encodeURIComponent(runId)}/citation-turn?${params}`
    );
    if (detailArea._requestToken !== token) return; // superseded by a newer click
    detailArea.textContent = "";
    const note = document.createElement("div");
    note.className = "citation-detail-note";
    note.textContent = "Where the model read this source (not proof the surrounding prose is faithful):";
    detailArea.appendChild(note);
    const pre = document.createElement("pre");
    pre.className = "citation-detail-payload trace-face";
    pre.textContent = JSON.stringify(data.payload, null, 2);
    detailArea.appendChild(pre);
  } catch (err) {
    if (detailArea._requestToken !== token) return;
    detailArea.textContent = `(error) ${err.message}`;
  }
}

// --- Source viewer modal ------------------------------------------------------------------------
//
// NotebookLM's most basic loop: click a citation, see the highlighted original passage. A modal
// (the first stacking-context component in this codebase's web/) rather than an inline slot —
// source text can run to a whole PDF's worth of pages, too long for the trace-detail slot pattern
// above. Opened from a citation's list row (always) or a Sources-panel list item (no highlight
// target). Each open aborts any still-in-flight fetch from a PREVIOUS open, so a slower first
// response can never overwrite a faster second one's render — the same class of defect just found
// and fixed in showCitationTurn above, guarded against here from the start with an AbortController
// instead (this fetch, unlike citation-turn's, is worth actually cancelling on the network level).
let sourceViewerAbort = null;

function closeSourceViewer() {
  document.getElementById("source-viewer-overlay").hidden = true;
  if (sourceViewerAbort) {
    sourceViewerAbort.abort();
    sourceViewerAbort = null;
  }
}

// Highlights AT MOST one quote inside one block's text — deliberately simpler than
// renderAnswerWithCitations's multi-citation overlap handling, since a source block only ever
// needs one highlight per viewer open.
function renderTextWithOptionalHighlight(text, quote) {
  const container = document.createElement("div");
  container.className = "source-block-text";
  if (!quote) {
    container.textContent = text;
    return container;
  }
  const at = text.indexOf(quote);
  if (at === -1) {
    container.textContent = text;
    return container;
  }
  container.appendChild(document.createTextNode(text.slice(0, at)));
  const mark = document.createElement("span");
  mark.className = "citation";
  mark.textContent = text.slice(at, at + quote.length);
  container.appendChild(mark);
  container.appendChild(document.createTextNode(text.slice(at + quote.length)));
  return container;
}

async function showSourceViewer(sourceId, locator, quote) {
  if (sourceViewerAbort) sourceViewerAbort.abort();
  const controller = new AbortController();
  sourceViewerAbort = controller;

  const overlay = document.getElementById("source-viewer-overlay");
  const title = document.getElementById("source-viewer-title");
  const body = document.getElementById("source-viewer-body");
  overlay.hidden = false;
  title.textContent = sourceId;
  body.textContent = "Loading…";

  try {
    const source = await api(
      `/notebooks/${encodeURIComponent(state.notebookId)}/sources/${encodeURIComponent(sourceId)}`,
      { signal: controller.signal }
    );
    if (controller.signal.aborted) return;
    title.textContent = `${source.kind} · ${source.origin}`;
    body.innerHTML = "";
    let targetSection = null;
    source.blocks.forEach((block) => {
      const section = document.createElement("div");
      section.className = "source-block";
      const label = document.createElement("div");
      label.className = "source-block-locator";
      label.textContent = block.locator;
      section.appendChild(label);
      const matches = locator && block.locator === locator;
      section.appendChild(renderTextWithOptionalHighlight(block.text, matches ? quote : null));
      body.appendChild(section);
      if (matches) targetSection = section;
    });
    if (targetSection) targetSection.scrollIntoView({ block: "center" });
  } catch (err) {
    if (controller.signal.aborted) return;
    body.textContent = `(error) ${err.message}`;
  }
}

function initSourceViewer() {
  document.getElementById("source-viewer-close").addEventListener("click", closeSourceViewer);
  document.getElementById("source-viewer-overlay").addEventListener("click", (event) => {
    if (event.target.id === "source-viewer-overlay") closeSourceViewer();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeSourceViewer();
  });
  store.on("notebook:switched", closeSourceViewer);
}

// --- Notebook switcher ---------------------------------------------------------------------------

async function refreshNotebookList() {
  const data = await api("/notebooks");
  const list = document.getElementById("notebook-list");
  list.innerHTML = "";
  data.notebooks.forEach((nb) => {
    const option = document.createElement("option");
    option.value = nb.id;
    option.label = `${nb.id} (${nb.source_count} sources, ${nb.turn_count} turns)`;
    list.appendChild(option);
  });
  if (data.unreadable.length) {
    console.warn("unreadable notebook files (flagged, not hidden):", data.unreadable);
  }
}

async function openNotebook(notebookId) {
  const trimmed = notebookId.trim();
  if (!trimmed) return;
  let notebook;
  try {
    notebook = await api(`/notebooks/${encodeURIComponent(trimmed)}`);
  } catch {
    // Doesn't exist yet — that's fine, it's created lazily on the first add-source call.
    notebook = { id: trimmed, sources: [], turns: [], notes: [] };
  }
  notebookGeneration += 1;
  state.notebookId = notebook.id;
  state.title = notebook.title || null;
  state.overview = notebook.overview || null;
  state.sources = notebook.sources;
  state.turns = notebook.turns;
  state.notes = notebook.notes || [];
  store.emit("notebook:switched", { notebookId: notebook.id });
  store.emit("notebook:titled", { title: state.title, notebookId: notebook.id });
  store.emit("sources:changed", { sources: state.sources });
  store.emit("notes:changed", { notes: state.notes });
  state.turns.forEach((turn) => store.emit("chat:turnAdded", { turn }));
  refreshNotebookList();
}

// Everything that mutates a notebook acts on `state.notebookId`, which is set only by
// `openNotebook`. The id box is a REQUEST, not the current state — typing a new name in it and
// pressing "Add source" without pressing Open used to silently write into whatever notebook was
// already open, with the box on screen showing a different name entirely. Reported by a user, who
// hit it as "I can't create a second notebook without reloading the page". Two fixes, together:
// the box is now rewritten from `state` on every switch so it can never disagree with what the app
// is acting on, and the wordmark is a real button that starts an empty one.
// Asks the server to name the notebook from the sources it now holds. Fired after the FIRST
// source lands, never blocking it: ingestion must not wait on (or fail because of) a model call,
// and the source list should render the moment it exists. The generation check drops the result if
// the user has moved to another notebook while it was in flight.
//
// Silent on failure by design — the endpoint already falls back to a deterministic title, and a
// missing title is a cosmetic loss, never worth an alert over a source that was added fine.
async function suggestTitle(notebookId, generation) {
  try {
    const notebook = await api(`/notebooks/${encodeURIComponent(notebookId)}/title`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: crypto.randomUUID() }),
    });
    if (generation !== notebookGeneration) return;
    state.title = notebook.title || null;
    store.emit("notebook:titled", { title: state.title, notebookId });
    refreshNotebookList();
  } catch {
    // keep whatever label is already on screen
  }
}

function initNotebookTitle() {
  const el = document.getElementById("notebook-title");
  store.on("notebook:titled", ({ title, notebookId }) => {
    // textContent, never innerHTML — a title is model-authored text derived from source content
    // a prompt-injected source could influence (CLAUDE.md invariants 6 and 29).
    el.textContent = title || (notebookId ? "Untitled notebook" : "");
    el.hidden = !notebookId;
  });
}

function initNotebookSwitch() {
  const input = document.getElementById("notebook-input");
  const openBtn = document.getElementById("notebook-open");
  openBtn.addEventListener("click", () => openNotebook(input.value));
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      openNotebook(input.value);
    }
  });
  document.getElementById("new-notebook").addEventListener("click", () => {
    input.value = "";
    input.focus();
    resetToNewNotebook();
  });
  store.on("notebook:switched", ({ notebookId }) => {
    input.value = notebookId;
  });
  refreshNotebookList();
}

// Bumped by EVERY notebook switch (open or reset). Async renders that resolve after a switch must
// check it and drop their result: an independent review found three that didn't, and the new
// one-click wordmark made them trivially reachable — asking a question then switching had the
// answer's follow-up GET build `/notebooks/null`, render `(error) 404 … 'null'` into the fresh
// blank notebook and kill the placeholder; the Guide fetch cached the OLD notebook's artifact
// UNDER the new one (so it reappeared on every later tab switch); and the podcast rendered the old
// episode after clearPlayer() had already run. The existing per-fetch guards (sourceViewerAbort,
// detailArea._requestToken) only protect against a newer request of the SAME kind, not against the
// notebook changing underneath.
let notebookGeneration = 0;

// A blank slate: no notebook selected, every panel cleared. Deliberately does NOT invent an id —
// `state.notebookId` stays null until the user names one (or, once auto-naming lands, until the
// first source is added), and every mutating call already refuses to run without one.
function resetToNewNotebook() {
  notebookGeneration += 1;
  state.notebookId = null;
  state.title = null;
  state.overview = null;
  state.sources = [];
  state.turns = [];
  state.notes = [];
  store.emit("notebook:switched", { notebookId: "" });
  store.emit("notebook:titled", { title: null, notebookId: "" });
  store.emit("sources:changed", { sources: [] });
  store.emit("notes:changed", { notes: [] });
}

// --- Sources panel --------------------------------------------------------------------------------

// Built with createElement/textContent throughout, never innerHTML — `source.origin` is an
// ingested URL/path and, in principle, `source.flags` could one day carry excerpted source text
// (today's injection_scan.py flags don't, but nothing enforces that staying true), so nothing here
// assumes any of it is safe to treat as markup.
function renderSourceItem(source) {
  const li = document.createElement("li");
  li.className = "source-item";
  li.addEventListener("click", () => showSourceViewer(source.id, null, null));

  const kind = document.createElement("div");
  kind.className = "src-kind";
  kind.textContent = source.kind;
  li.appendChild(kind);

  const origin = document.createElement("div");
  origin.className = "src-origin";
  origin.textContent = source.origin;
  li.appendChild(origin);

  if (source.flags && source.flags.length) {
    const flags = document.createElement("div");
    flags.className = "src-flags";
    flags.textContent = `⚠ ${source.flags.join(", ")}`;
    li.appendChild(flags);
  }

  return li;
}

function initSourcesPanel() {
  const tabs = document.querySelectorAll("#source-kind-tabs .tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("is-active"));
      tab.classList.add("is-active");
      document.querySelectorAll(".tab-body").forEach((body) => {
        body.hidden = body.dataset.kindBody !== tab.dataset.kind;
      });
    });
  });

  const form = document.getElementById("add-source-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    // No notebook open? Make one. Demanding a name before the first source made the very first
    // interaction with this product a naming puzzle about a thing that didn't exist yet — the user
    // hit "Open or name a notebook first" and had to invent an id. The id is a handle now, not a
    // label: it is minted here, never shown as the primary name, and `suggestTitle()` below fills
    // in something readable once there is a source to derive it from.
    const isFirstSource = !state.notebookId;
    if (isFirstSource) {
      state.notebookId = `nb-${crypto.randomUUID().slice(0, 8)}`;
      notebookGeneration += 1;
    }
    const activeKind = document.querySelector("#source-kind-tabs .tab.is-active").dataset.kind;
    const nb = encodeURIComponent(state.notebookId);

    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    try {
      let notebook;
      if (activeKind === "url") {
        const value = document.getElementById("source-url").value.trim();
        if (!value) return;
        notebook = await api(`/notebooks/${nb}/sources`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sources: [value] }),
        });
        document.getElementById("source-url").value = "";
      } else if (activeKind === "text") {
        const value = document.getElementById("source-text").value.trim();
        if (!value) return;
        notebook = await api(`/notebooks/${nb}/sources`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ texts: [value] }),
        });
        document.getElementById("source-text").value = "";
      } else {
        const fileInput = document.getElementById("source-file");
        const file = fileInput.files[0];
        if (!file) return;
        const formData = new FormData();
        formData.append("file", file);
        // Deliberately no `headers` here — the browser must set its own multipart boundary,
        // which a manually-set Content-Type would break. `api()` never sets one itself (it's a
        // thin `fetch` wrapper; each JSON call site sets its own headers explicitly), so this
        // reuses it exactly as-is rather than needing a second, bespoke fetch call.
        notebook = await api(`/notebooks/${nb}/sources/upload`, {
          method: "POST",
          body: formData,
        });
        fileInput.value = "";
      }
      state.sources = notebook.sources;
      state.title = notebook.title || state.title;
      store.emit("sources:changed", { sources: state.sources });
      store.emit("notebook:titled", { title: state.title, notebookId: state.notebookId });
      if (isFirstSource) void suggestTitle(state.notebookId, notebookGeneration);
    } catch (err) {
      alert(`Could not add source: ${err.message}`);
    } finally {
      submitBtn.disabled = false;
    }
  });

  store.on("sources:changed", ({ sources }) => {
    const list = document.getElementById("source-list");
    const empty = document.getElementById("sources-empty");
    list.innerHTML = "";
    sources.forEach((source) => list.appendChild(renderSourceItem(source)));
    empty.hidden = sources.length > 0;
  });
}

// --- Chat panel -----------------------------------------------------------------------------------

// The signature interaction (blueprint §2.3): a citation is a highlighter stroke woven into the
// answer text, not a footnote number appended after it.
//
// Built with createElement/textContent/setAttribute throughout, NEVER innerHTML or a raw HTML
// string — `text` is the model's own answer prose and `citation.quote`/`source_id`/`locator` could
// in principle echo attacker-supplied content from a prompt-injected source (CLAUDE.md invariant 6:
// a source's content is untrusted, and injection_scan.py's flags are advisory, not a filter). An
// early version of this function built a `<span title="...">` via string interpolation, which a
// `"` character inside `source_id`/`locator` could have broken out of; rewritten before this was
// ever shipped once that was noticed. Same discipline the sibling studios' own `app.js` files
// already enforce for exactly this reason (see rlm_notebook/web/DESIGN.md's Do/Don't).
// `runId` is optional (Phase 1/2 call sites that predate the trace fusion, or a loaded turn saved
// before `ChatTurn.run_id` existed, pass nothing) — when given, each citation span becomes
// clickable, calling `showCitationTurn` against a shared detail slot appended once per answer.
// The "+ Save as note" affordance, as a factory rather than a line inside
// `renderAnswerWithCitations`. NotebookLM's own model is that generated artifacts BECOME notes, and
// this project already has the whole mechanism (Note -> promote_note -> a real citable Source) —
// what it lacked was any way to get an overview into it.
//
// The rule this preserves (blueprint's Notes addendum, audit round 1): the button belongs to a CALL
// SITE that opts in, never to the shared renderer, which Guide tabs and the podcast transcript also
// use. The line is what the user is looking at when they click: things rendered IN the chat thread
// (an answer, the overview) are theirs to curate; a Studio tab's artifact and a podcast transcript
// are not part of that thread.
function saveAsNoteButton(text) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn save-as-note";
  btn.textContent = "+ Save as note";
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const original = btn.textContent;
    try {
      await addNote(text);
      btn.textContent = "\u2713 Saved";
    } finally {
      setTimeout(() => {
        btn.textContent = original;
        btn.disabled = false;
      }, 1500);
    }
  });
  return btn;
}

function renderAnswerWithCitations(text, citations, runId) {
  const container = document.createElement("div");

  // Locate each citation's quote as a literal substring of the RAW answer text (never
  // pre-escaped — a DOM text node needs no escaping, only innerHTML does). The model may
  // paraphrase around a quote rather than reproducing it verbatim; when a quote can't be located,
  // the citation still surfaces in the citation list below, just not inline.
  const matches = [];
  citations.forEach((citation) => {
    if (!citation.quote) return;
    const at = text.indexOf(citation.quote);
    if (at !== -1) matches.push({ start: at, end: at + citation.quote.length, citation });
  });
  matches.sort((a, b) => a.start - b.start);

  const detailArea = document.createElement("div");
  detailArea.className = "citation-detail";
  detailArea.hidden = true;

  let cursor = 0;
  matches.forEach((match) => {
    if (match.start < cursor) return; // overlapping quotes — keep the first, skip the rest
    if (match.start > cursor) {
      container.appendChild(document.createTextNode(text.slice(cursor, match.start)));
    }
    const span = document.createElement("span");
    span.className = match.citation.verified ? "citation" : "citation is-unverified";
    span.title = `${match.citation.source_id} · ${match.citation.locator}`;
    span.textContent = text.slice(match.start, match.end);
    if (runId) {
      span.classList.add("citation-clickable");
      span.addEventListener("click", () => showCitationTurn(runId, match.citation, detailArea));
    }
    container.appendChild(span);
    cursor = match.end;
  });
  if (cursor < text.length) {
    container.appendChild(document.createTextNode(text.slice(cursor)));
  }

  if (citations.length) {
    const list = document.createElement("div");
    list.className = "citation-list";
    citations.forEach((citation) => {
      const row = document.createElement("div");
      row.className = "citation-row";
      row.addEventListener("click", () =>
        showSourceViewer(citation.source_id, citation.locator, citation.quote)
      );

      const label = document.createElement("div");
      label.className = "citation-row-label";
      const mark = citation.verified ? "✓" : "⚠ unverified";
      label.textContent = `${mark} ${citation.source_id} · ${citation.locator}`;
      row.appendChild(label);

      if (runId) {
        const trace = document.createElement("button");
        trace.type = "button";
        trace.className = "citation-row-trace";
        trace.textContent = "⌁ trace";
        trace.addEventListener("click", (event) => {
          event.stopPropagation();
          showCitationTurn(runId, citation, detailArea);
        });
        row.appendChild(trace);
      }

      list.appendChild(row);
    });
    container.appendChild(list);
  }
  if (runId) container.appendChild(detailArea);
  return container;
}

function renderTurn(turn) {
  const wrapper = document.createElement("div");
  wrapper.className = "turn";

  const question = document.createElement("div");
  question.className = "turn-question";
  question.textContent = turn.question;
  wrapper.appendChild(question);

  const answer = document.createElement("div");
  answer.className = "turn-answer";
  if (turn.run_id) answer.dataset.runId = turn.run_id;
  if (turn.pending) {
    answer.classList.add("is-pending");
    answer.textContent = "Thinking…";
  } else {
    answer.appendChild(renderAnswerWithCitations(turn.answer, turn.citations || [], turn.run_id));
    // `turn.run_id` is `None`/absent for any turn saved before this field existed — degrades
    // gracefully to no affordance rather than a broken link (schema.ChatTurn.run_id's own doc).
    if (turn.run_id && tickerLogs.has(turn.run_id)) {
      answer.appendChild(renderTickerAffordance(turn.run_id));
    }
    // Appended HERE, by renderTurn itself — NOT inside renderAnswerWithCitations, which five OTHER
    // call sites (Guide/Podcast) also use and must never show this button (blueprint's Notes
    // addendum, audit round 1). `generateOverview` appends its own via the same factory, for the
    // same reason: a shared helper the CALL SITE opts into, never a button the shared renderer
    // grows on its own.
    answer.appendChild(saveAsNoteButton(turn.answer));
  }
  wrapper.appendChild(answer);

  return wrapper;
}

// --- The chat overview: the notebook's front page ---------------------------------------------
//
// Adding a source used to leave the screen doing nothing — Chat said "ask a question once you've
// added a source", Studio said "pick a tab to generate it", and both waited on the user to discover
// the next move. The guided feel of a notebook product comes from the artifact appearing IN the
// conversation and being something you ask follow-ups about; a Summary buried in a right-hand tab
// is disconnected from the thread, so even finding it leads nowhere.
//
// THREE states, not two. The first version had only "generated in this page session" vs "not", on a
// DOM flag — so every notebook opened showing the first-run button even mid-conversation (reported
// with a screenshot), and adding a source DELETED the overview and reverted to that same button, so
// "never generated" and "generated but the sources changed" rendered identically. Confiscating an
// overview the user just paid an RLM run for, because they added a source, is worse than showing it
// with a marker: it is still true about the sources it was computed from.
//
//   never generated          ->  the Generate button
//   generated, current       ->  the overview + Save as note
//   generated, sources moved ->  the overview, marked stale, + Regenerate  (+ Save as note: a stale
//                                overview is precisely the one worth keeping before regenerating)
//
// `state.overview` comes from the server, which owns both the artifact and the `stale` verdict.
// Deliberately still an explicit button, NOT auto-generated on open: a guide run is a real RLM loop
// and Phase 2's rule (never spend one nobody asked for) is unchanged.
let overviewToken = 0;

function renderChatOverview() {
  const el = document.getElementById("chat-overview");
  el.textContent = "";
  el.hidden = !state.sources.length;
  if (!state.sources.length) return;

  const overview = state.overview;
  if (!overview) {
    el.appendChild(overviewStarter("\u2728 Generate overview", "\u2026or just ask a question below."));
    return;
  }

  const head = document.createElement("div");
  head.className = "chat-overview-head";
  head.textContent = overview.stale ? "Overview \u00b7 sources have changed since this" : "Overview";
  el.appendChild(head);

  el.appendChild(renderAnswerWithCitations(overview.text, overview.citations || [], overview.run_id));
  // Guarded, as `renderTurn` already guards its own: on a fresh page load `tickerLogs` is empty, so
  // an unconditional call would render a dead "0 steps" pill for every reloaded overview.
  if (overview.run_id && tickerLogs.has(overview.run_id)) {
    el.appendChild(renderTickerAffordance(overview.run_id));
  }
  el.appendChild(saveAsNoteButton(overview.text));

  if (overview.starter_questions && overview.starter_questions.length) {
    const label = document.createElement("div");
    label.className = "chat-overview-head";
    label.textContent = "Start with";
    el.appendChild(label);
    el.appendChild(starterQuestionRow(overview.starter_questions));
  }

  if (overview.stale) {
    el.appendChild(overviewStarter("\u21bb Regenerate overview", ""));
  }
}

function overviewStarter(labelText, hintText) {
  const wrap = document.createElement("div");
  wrap.className = "chat-starter";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-primary";
  btn.textContent = labelText;
  btn.addEventListener("click", () => {
    btn.disabled = true;
    void generateOverview();
  });
  wrap.appendChild(btn);
  if (hintText) {
    const hint = document.createElement("div");
    hint.className = "hint";
    hint.textContent = hintText;
    wrap.appendChild(hint);
  }
  return wrap;
}

function starterQuestionRow(questions) {
  const row = document.createElement("div");
  row.className = "starter-questions";
  questions.forEach((question) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "starter-question";
    // textContent, never innerHTML — model-authored text derived from source content a
    // prompt-injected source could influence (invariants 6 and 29).
    chip.textContent = question;
    chip.addEventListener("click", () => {
      // `requestSubmit()` submits as if by the form, so a DISABLED submit button never blocks it;
      // the chips live outside the region `chat:pending` disables, so the guard has to be here.
      if (document.getElementById("ask-submit").disabled) return;
      document.getElementById("ask-input").value = question;
      document.getElementById("ask-form").requestSubmit();
    });
    row.appendChild(chip);
  });
  return row;
}

// One POST; the server runs Summary and FAQ concurrently and persists the result, so nothing is
// lost if this tab closes while it runs.
async function generateOverview() {
  const el = document.getElementById("chat-overview");
  const generation = notebookGeneration;
  const token = (overviewToken += 1);
  const notebookId = state.notebookId;
  if (!notebookId) return;
  const live = () => generation === notebookGeneration && token === overviewToken;

  el.hidden = false;
  el.textContent = "";
  const pending = document.createElement("div");
  pending.className = "chat-overview-head";
  pending.textContent = "Reading your sources\u2026";
  el.appendChild(pending);

  // The server appends `-summary` to the run id it derives, so the ticker's target is predictable.
  // Trace LINKS afterwards come from the server-returned `overview.run_id`, never a reconstruction.
  const runToken = crypto.randomUUID();
  void openTicker(notebookId, `${notebookId}-${runToken}-summary`, (event) => {
    if (live() && event.summary) pending.textContent = event.summary;
  });

  try {
    const notebook = await api(`/notebooks/${encodeURIComponent(notebookId)}/overview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runToken }),
    });
    if (!live()) return;
    state.overview = notebook.overview;
    renderChatOverview();
  } catch (err) {
    if (!live()) return;
    el.textContent = "";
    const note = document.createElement("div");
    note.textContent = `(could not generate an overview: ${err.message})`;
    el.appendChild(note);
    el.appendChild(overviewStarter("\u21bb Try again", ""));
  }
}

function initChatPanel() {
  const history = document.getElementById("chat-history");
  const empty = document.getElementById("chat-empty");
  const form = document.getElementById("ask-form");
  const input = document.getElementById("ask-input");
  const submitBtn = document.getElementById("ask-submit");

  store.on("notebook:switched", () => {
    overviewToken += 1; // a notebook switch strands any generation still in flight
    renderChatOverview();
    history.innerHTML = "";
    // Un-hide the placeholder too: `chat:turnAdded` hides it, and without this a switch FROM a
    // notebook with turns TO an empty one left a blank panel with no "ask a question" prompt at
    // all. Latent before the wordmark button made "go to an empty notebook" a one-click action.
    empty.hidden = false;
    history.appendChild(empty);
  });

  // Chat's own reaction to the corpus changing. Re-render only — deliberately NOT a token bump:
  // that would strand a generation the server has already persisted, leaving the user looking at
  // the button after paying for two RLM runs sitting on disk (adding a source while the model works
  // is the exact behaviour invariant 34 documents as real). The re-render flips the overview to
  // stale on its own, because the server's `source_ids` no longer match.
  store.on("sources:changed", () => renderChatOverview());
  renderChatOverview();

  store.on("chat:turnAdded", ({ turn }) => {
    empty.hidden = true;
    history.appendChild(renderTurn(turn));
    history.scrollTop = history.scrollHeight;
  });

  store.on("chat:pending", ({ pending }) => {
    submitBtn.disabled = pending;
    input.disabled = pending;
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.notebookId) {
      alert("Open or name a notebook first.");
      return;
    }
    const question = input.value.trim();
    if (!question) return;

    // The CLIENT picks the run id (blueprint P3.1) — a server-generated one would never reach us
    // until the request was already over, too late to open a live ticker against it.
    const generation = notebookGeneration;
    const askedNotebookId = state.notebookId;
    const token = crypto.randomUUID();
    const runId = `${state.notebookId}-${token}`;

    const pendingTurn = { question, pending: true, run_id: runId };
    store.emit("chat:turnAdded", { turn: pendingTurn });
    store.emit("chat:pending", { pending: true });
    input.value = "";

    openTicker(state.notebookId, runId, (evt) => {
      const el = history.querySelector(`.turn-answer[data-run-id="${CSS.escape(runId)}"]`);
      if (el && el.classList.contains("is-pending")) el.textContent = evt.summary || "Thinking…";
    });

    try {
      const result = await api(`/notebooks/${encodeURIComponent(state.notebookId)}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, run_id: token }),
      });
      // Re-render the whole history from the server's own record rather than mutating the
      // pending row in place — the server is the source of truth for what actually got persisted.
      // Capture the id BEFORE awaiting: re-reading `state.notebookId` here would build
      // `/notebooks/null` if the user started a new notebook while the answer was in flight.
      if (generation !== notebookGeneration) return;
      const notebook = await api(`/notebooks/${encodeURIComponent(askedNotebookId)}`);
      if (generation !== notebookGeneration) return;
      state.turns = notebook.turns;
      history.innerHTML = "";
      history.appendChild(empty);
      empty.hidden = state.turns.length > 0;
      state.turns.forEach((turn) => history.appendChild(renderTurn(turn)));
      void result; // already folded into notebook.turns above
    } catch (err) {
      pendingTurn.pending = false;
      pendingTurn.answer = `(error) ${err.message}`;
      pendingTurn.citations = [];
      history.innerHTML = "";
      history.appendChild(empty);
      empty.hidden = true;
      state.turns.forEach((turn) => history.appendChild(renderTurn(turn)));
      history.appendChild(renderTurn(pendingTurn));
    } finally {
      store.emit("chat:pending", { pending: false });
    }
  });
}

// --- Studio panel: Guide tabs -----------------------------------------------------------------

// Fetched ONLY on first tab activation or an explicit regenerate click, never on every tab
// switch — a guide run is a real RLM loop (same latency class as `ask`), so re-running it on every
// idle click would burn a model call for nothing. Cached per notebook, keyed by kind; cleared on
// BOTH a notebook switch AND a source being added — a cached result is stale the moment the corpus
// it was computed from changes, not just when the notebook itself changes.
function renderGuideContent(kind, data, runId) {
  const container = document.createElement("div");
  container.className = "guide-prose";

  if (kind === "summary" || kind === "insight") {
    container.appendChild(renderAnswerWithCitations(data.text, data.citations || [], runId));
    return container;
  }

  if (kind === "faq") {
    if (!data.items || !data.items.length) {
      container.textContent = "(no FAQ items — the sources didn't produce enough to ask about)";
      return container;
    }
    data.items.forEach((item) => {
      const div = document.createElement("div");
      div.className = "guide-item";
      const head = document.createElement("div");
      head.className = "guide-item-head";
      head.textContent = item.question;
      div.appendChild(head);
      div.appendChild(renderAnswerWithCitations(item.answer, item.citations || [], runId));
      container.appendChild(div);
    });
    return container;
  }

  // "timeline"
  if (!data.events || !data.events.length) {
    container.textContent = "(no timeline events — the sources didn't produce enough to place in time)";
    return container;
  }
  data.events.forEach((event) => {
    const div = document.createElement("div");
    div.className = "guide-item";
    const when = document.createElement("div");
    when.className = "guide-item-when";
    when.textContent = event.when;
    div.appendChild(when);
    div.appendChild(renderAnswerWithCitations(event.description, event.citations || [], runId));
    container.appendChild(div);
  });
  return container;
}

function initStudioPanel() {
  const tabs = document.querySelectorAll("#guide-tabs .tab");
  const body = document.getElementById("guide-body");
  const regenerateBtn = document.getElementById("guide-regenerate");
  // Cache VALUE widened to {result, runId} — storing the result alone (an earlier draft's shape)
  // would lose the run id the moment a user switches tabs and back, breaking citation-turn lookup
  // for a tab already left (found during this phase's own pre-implementation audit).
  const cache = new Map();
  let activeKind = "summary";

  function setActiveKind(kind) {
    activeKind = kind;
    tabs.forEach((tab) => tab.classList.toggle("is-active", tab.dataset.guideKind === kind));
  }

  function renderCached(kind, cached) {
    body.innerHTML = "";
    body.appendChild(renderGuideContent(kind, cached.result, cached.runId));
    body.appendChild(renderTickerAffordance(cached.runId));
  }

  async function fetchKind(kind) {
    if (!state.notebookId) {
      body.innerHTML = "";
      body.classList.remove("is-pending");
      const note = document.createElement("p");
      note.className = "empty-note";
      note.textContent = "Open a notebook with sources, then pick a tab to generate it.";
      body.appendChild(note);
      return;
    }
    const generation = notebookGeneration;
    const token = crypto.randomUUID();
    const runId = `${state.notebookId}-${token}`;
    body.classList.add("is-pending");
    body.textContent = "Generating…";
    openTicker(state.notebookId, runId, (evt) => {
      if (body.classList.contains("is-pending")) body.textContent = evt.summary || "Generating…";
    });
    try {
      const data = await api(`/notebooks/${encodeURIComponent(state.notebookId)}/guide/${kind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: token }),
      });
      if (generation !== notebookGeneration) return;  // switched away — never cache into the new one
      cache.set(kind, { result: data, runId });
      body.classList.remove("is-pending");
      renderCached(kind, cache.get(kind));
    } catch (err) {
      body.classList.remove("is-pending");
      body.textContent = `(error) ${err.message}`;
    }
  }

  function showKind(kind) {
    setActiveKind(kind);
    if (cache.has(kind)) {
      renderCached(kind, cache.get(kind));
      return;
    }
    fetchKind(kind);
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => showKind(tab.dataset.guideKind));
  });

  regenerateBtn.addEventListener("click", () => {
    cache.delete(activeKind);
    fetchKind(activeKind);
  });

  function invalidateCache() {
    cache.clear();
  }

  // Opening a notebook does NOT auto-fetch a Guide kind — that would burn a model call just from
  // opening a notebook, contradicting the "fetched only on first activation or explicit
  // regenerate" rule above. It only resets to a neutral state; the first real fetch happens when
  // the user actually clicks a tab (including re-clicking the already-active default one).
  store.on("notebook:switched", () => {
    invalidateCache();
    setActiveKind("summary");
    body.innerHTML = "";
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = "Pick a tab above to generate it.";
    body.appendChild(note);
  });
  store.on("sources:changed", invalidateCache);
}

// --- Studio panel: podcast player ------------------------------------------------------------

function renderPodcastUtterance(utterance, runId) {
  const div = document.createElement("div");
  div.className = "podcast-utterance";
  const speaker = document.createElement("div");
  speaker.className = "podcast-speaker";
  speaker.textContent = utterance.speaker === "host_a" ? "Host A" : "Host B";
  div.appendChild(speaker);
  div.appendChild(renderAnswerWithCitations(utterance.text, utterance.citations || [], runId));
  return div;
}

function initPodcastPlayer() {
  const generateBtn = document.getElementById("podcast-generate");
  const body = document.getElementById("podcast-body");
  let currentObjectUrl = null;

  function clearPlayer() {
    body.innerHTML = "";
    // Revoke only after nothing in the DOM still references it — the caller always assigns a new
    // src (or clears the body) before this runs, so a previous episode mid-playback is never
    // yanked out from under a live <audio> element (blueprint P2.6's revocation-order fix).
    if (currentObjectUrl) {
      URL.revokeObjectURL(currentObjectUrl);
      currentObjectUrl = null;
    }
  }

  generateBtn.addEventListener("click", async () => {
    if (!state.notebookId) {
      alert("Open or name a notebook first.");
      return;
    }
    generateBtn.disabled = true;
    const generation = notebookGeneration;
    const token = crypto.randomUUID();
    const runId = `${state.notebookId}-${token}`;
    body.classList.add("is-pending");
    body.textContent = "Generating script and synthesizing audio — this can take a while…";
    openTicker(state.notebookId, runId, (evt) => {
      if (body.classList.contains("is-pending")) {
        body.textContent = evt.summary || "Generating script and synthesizing audio…";
      }
    });
    try {
      const data = await api(`/notebooks/${encodeURIComponent(state.notebookId)}/audio`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: token }),
      });
      if (generation !== notebookGeneration) return;  // switched away — the old episode is not theirs
      body.classList.remove("is-pending");
      body.innerHTML = "";

      if (!data.utterances.length) {
        body.textContent = "(no podcast script — the sources didn't produce enough to discuss)";
        return;
      }

      const bytes = Uint8Array.from(atob(data.audio_base64), (c) => c.charCodeAt(0));
      const blob = new Blob([bytes], { type: "audio/mpeg" });
      const newUrl = URL.createObjectURL(blob);
      const oldUrl = currentObjectUrl;

      const player = document.createElement("audio");
      player.controls = true;
      player.src = newUrl; // assign the NEW url first...
      body.appendChild(player);
      currentObjectUrl = newUrl;
      if (oldUrl) URL.revokeObjectURL(oldUrl); // ...then revoke the OLD one, never the reverse
      body.appendChild(renderTickerAffordance(runId));

      const transcript = document.createElement("div");
      transcript.className = "podcast-transcript";
      data.utterances.forEach((utterance) =>
        transcript.appendChild(renderPodcastUtterance(utterance, runId))
      );
      body.appendChild(transcript);
    } catch (err) {
      body.classList.remove("is-pending");
      body.innerHTML = "";
      body.textContent = `(error) ${err.message}`;
    } finally {
      generateBtn.disabled = false;
    }
  });

  store.on("notebook:switched", clearPlayer);
}

// --- Notes section (Studio panel) ----------------------------------------------------------------
//
// NotebookLM's research-loop closing feature: a manual note, or a Chat answer saved as one
// (`addNote`, wired from `renderTurn`), can later be PROMOTED into a real, independently-
// citable source — the "read a source → note something → the note becomes a source → keep going"
// loop this project had no concept of at all before this. Built with createElement/textContent
// throughout, same discipline every other list in this file already follows — a note's `text` is
// user-authored (or copied from a model answer) and never assumed safe to treat as markup.

function renderNoteItem(note) {
  const li = document.createElement("li");
  li.className = "note-item";

  const text = document.createElement("div");
  text.className = "note-text";
  text.textContent = note.text;
  li.appendChild(text);

  const actions = document.createElement("div");
  actions.className = "note-actions";

  const promoteBtn = document.createElement("button");
  promoteBtn.type = "button";
  promoteBtn.className = "btn note-promote";
  promoteBtn.textContent = "→ Promote to source";
  promoteBtn.addEventListener("click", async () => {
    promoteBtn.disabled = true;
    try {
      const notebook = await api(
        `/notebooks/${encodeURIComponent(state.notebookId)}/notes/${encodeURIComponent(note.id)}/promote`,
        { method: "POST" }
      );
      state.sources = notebook.sources;
      state.notes = notebook.notes;
      store.emit("sources:changed", { sources: state.sources });
      store.emit("notes:changed", { notes: state.notes });
    } catch (err) {
      alert(`Could not promote note: ${err.message}`);
      promoteBtn.disabled = false;
    }
  });
  actions.appendChild(promoteBtn);

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "btn note-delete";
  deleteBtn.textContent = "✕";
  deleteBtn.addEventListener("click", async () => {
    deleteBtn.disabled = true;
    try {
      const notebook = await api(
        `/notebooks/${encodeURIComponent(state.notebookId)}/notes/${encodeURIComponent(note.id)}`,
        { method: "DELETE" }
      );
      state.notes = notebook.notes;
      store.emit("notes:changed", { notes: state.notes });
    } catch (err) {
      alert(`Could not delete note: ${err.message}`);
      deleteBtn.disabled = false;
    }
  });
  actions.appendChild(deleteBtn);

  li.appendChild(actions);
  return li;
}

async function addNote(text) {
  if (!state.notebookId) return;
  try {
    const notebook = await api(`/notebooks/${encodeURIComponent(state.notebookId)}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    state.notes = notebook.notes;
    store.emit("notes:changed", { notes: state.notes });
  } catch (err) {
    alert(`Could not save note: ${err.message}`);
  }
}

function initNotesPanel() {
  const form = document.getElementById("add-note-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.notebookId) {
      alert("Open or name a notebook first.");
      return;
    }
    const input = document.getElementById("note-text");
    const value = input.value.trim();
    if (!value) return;
    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    try {
      await addNote(value);
      input.value = "";
    } finally {
      submitBtn.disabled = false;
    }
  });

  store.on("notes:changed", ({ notes }) => {
    const list = document.getElementById("note-list");
    const empty = document.getElementById("notes-empty");
    list.innerHTML = "";
    notes.forEach((note) => list.appendChild(renderNoteItem(note)));
    empty.hidden = notes.length > 0;
  });
}

// --- Boot -------------------------------------------------------------------------------------

initTheme();
initNotebookSwitch();
initSourcesPanel();
initChatPanel();
initStudioPanel();
initPodcastPlayer();
initSourceViewer();
initNotesPanel();
