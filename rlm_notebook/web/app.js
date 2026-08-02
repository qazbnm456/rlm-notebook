// rlm-notebook web UI — zero-build vanilla JS, no framework, no build step (see DESIGN.md).
//
// State: a small hand-rolled evented store, not a state-management library. Event vocabulary is
// PINNED (blueprint §3.1) so later phases don't invent an incompatible convention:
//   notebook:switched  { notebookId }
//   sources:changed    { sources }
//   chat:turnAdded     { turn }
//   chat:pending       { pending }
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
  sources: [],
  turns: [],
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
    notebook = { id: trimmed, sources: [], turns: [] };
  }
  state.notebookId = notebook.id;
  state.sources = notebook.sources;
  state.turns = notebook.turns;
  store.emit("notebook:switched", { notebookId: notebook.id });
  store.emit("sources:changed", { sources: state.sources });
  state.turns.forEach((turn) => store.emit("chat:turnAdded", { turn }));
  refreshNotebookList();
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
  refreshNotebookList();
}

// --- Sources panel --------------------------------------------------------------------------------

// Built with createElement/textContent throughout, never innerHTML — `source.origin` is an
// ingested URL/path and, in principle, `source.flags` could one day carry excerpted source text
// (today's injection_scan.py flags don't, but nothing enforces that staying true), so nothing here
// assumes any of it is safe to treat as markup.
function renderSourceItem(source) {
  const li = document.createElement("li");
  li.className = "source-item";

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
    if (!state.notebookId) {
      alert("Open or name a notebook first.");
      return;
    }
    const activeKind = document.querySelector("#source-kind-tabs .tab.is-active").dataset.kind;
    let value = "";
    if (activeKind === "url") {
      value = document.getElementById("source-url").value.trim();
    } else if (activeKind === "text") {
      // The API only accepts http(s) URLs (CLAUDE.md invariant 26) — paste-text ingestion needs
      // its own backend affordance this phase doesn't add. The tab exists (blueprint §7) so the
      // layout doesn't need reworking once one does.
      alert("Paste-text ingestion isn't wired to the API yet.");
      return;
    } else {
      alert("File upload isn't wired to the API yet.");
      return;
    }
    if (!value) return;

    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    try {
      const notebook = await api(`/notebooks/${encodeURIComponent(state.notebookId)}/sources`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sources: [value] }),
      });
      state.sources = notebook.sources;
      store.emit("sources:changed", { sources: state.sources });
      document.getElementById("source-url").value = "";
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
function renderAnswerWithCitations(text, citations) {
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
      const mark = citation.verified ? "✓" : "⚠ unverified";
      row.textContent = `${mark} ${citation.source_id} · ${citation.locator}`;
      list.appendChild(row);
    });
    container.appendChild(list);
  }
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
  if (turn.pending) {
    answer.classList.add("is-pending");
    answer.textContent = "Thinking…";
  } else {
    answer.appendChild(renderAnswerWithCitations(turn.answer, turn.citations || []));
  }
  wrapper.appendChild(answer);

  return wrapper;
}

function initChatPanel() {
  const history = document.getElementById("chat-history");
  const empty = document.getElementById("chat-empty");
  const form = document.getElementById("ask-form");
  const input = document.getElementById("ask-input");
  const submitBtn = document.getElementById("ask-submit");

  store.on("notebook:switched", () => {
    history.innerHTML = "";
    history.appendChild(empty);
  });

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

    const pendingTurn = { question, pending: true };
    store.emit("chat:turnAdded", { turn: pendingTurn });
    store.emit("chat:pending", { pending: true });
    input.value = "";

    try {
      const result = await api(`/notebooks/${encodeURIComponent(state.notebookId)}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      // Re-render the whole history from the server's own record rather than mutating the
      // pending row in place — the server is the source of truth for what actually got persisted.
      const notebook = await api(`/notebooks/${encodeURIComponent(state.notebookId)}`);
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

// --- Boot -------------------------------------------------------------------------------------

initTheme();
initNotebookSwitch();
initSourcesPanel();
initChatPanel();
