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
  // The server-side `notebook.slug(id)`, which is what `_derive_run_id` actually prefixes a run id
  // with. Building run ids from the raw id left every trace link dead for `"my notebook"` or any
  // non-Latin id (invariant 10) — found by an independent audit.
  notebookSlug: null,
  title: null,
  overview: null,
  podcast: null,
  //: The Studio guide artifacts, keyed by kind, as `{result, runId}`. On `state` rather than in a
  //: closure inside `initStudioPanel` because the References view has to collect citations from
  //: them: an independent review found every citation in a summary/FAQ/timeline/insight — and in
  //: the podcast transcript — was clickable and led to a References list that structurally could
  //: not contain it. It only LOOKED like it worked when the same `source_id|locator` happened to
  //: be cited in chat too, which for text/web sources (all locator `"whole"`) is most of the time.
  guides: {},
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
  // U+FE0E forces TEXT presentation. Without it macOS draws these from the colour-emoji font,
  // which ignores `color` entirely (so the hover tint did nothing) and renders at its own
  // scale (so the glyph looked small however large `font-size` was). That is the whole
  // explanation for "the icon is still too small and the hover has no effect".
  // GEOMETRIC glyphs (U+25D0/U+25D1), not `☀`/`☾`. Those live in the Miscellaneous Symbols block
  // and macOS draws them from the colour-emoji font, which ignores `color` outright and sizes them
  // itself — the reason two rounds of "the icon is small and the hover does nothing" were about the
  // font, not the CSS. U+FE0E asks for text presentation, but a glyph that was never emoji in the
  // first place is one less thing depending on the platform honouring it. Same family
  // `bugcademy/studio` uses (`◐`).
  toggle.textContent = current === "dark" ? "\u25d1" : "\u25d0";
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

//: Kinds that end a stream. Written down once so the ticker, the tests and any later consumer
//: share one answer — adding a terminal kind and missing a call site leaves a stream open forever.
const TERMINAL_KINDS = new Set(["done", "failed", "not_found"]);

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
      // EVERY terminal kind, not just the happy one. `failed` was added when the trace mapping
      // grew a failure headline, and a check that only knew `done` would have left the stream open
      // forever on exactly the runs a user most wants to see end. Caught by a test asserting the
      // old vocabulary, which is the whole reason to pin an event vocabulary in the first place.
      if (TERMINAL_KINDS.has(event.kind)) {
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

// A shared "something is running" surface: a pulsing dot, the live action, a ticking elapsed
// counter, and a Stop button. Same shape `nuclei-forge/studio`'s `.live-status` uses, and it exists
// because of a real report: a generation takes a minute or more, the only feedback was one line of
// text that ended on "finished" and then sat there, so the natural move is to press the button
// again — which strands the first generation behind a staleness guard and looks like nothing
// happened at all.
//
// `runIds` is a LIST because `/overview` fires two runs; cancelling per run id rather than per
// notebook is what makes Stop actually stop everything (see `cancel_run`'s docstring).
// The server's `summary` is an English convenience; `kind` is the stable thing and `detail` is the
// one specific that differs every run. Translating the KIND and keeping the detail verbatim is what
// makes the status line readable in the interface language without inventing a translation for a
// tool name or a model id.
//: The event headlines, in the interface language. The server sends `primary` in English and
//: `detail`/`meta` as the run's own specifics — a headline is a fixed vocabulary worth translating,
//: a piece of the model's reasoning or a tool's name is not.
const TRACE_HEADLINES = {
  Starting: () => t("trace.start", "Starting"),
  Step: () => t("trace.stepBare", "Step"),
  Tool: () => t("trace.tool", "Tool"),
  "Sub-model": () => t("trace.escalation", "Sub-model"),
  Finalising: () => t("trace.final", "Finalising"),
  Result: () => t("trace.result", "Result"),
  Finished: () => t("trace.done", "Finished"),
  Failed: () => t("trace.failed", "Failed"),
};

function traceHeadline(event) {
  const primary = event.primary || "";
  // `Step 3` -> the `Step` headline plus its number, so the count survives translation.
  // Interpolated, not concatenated: a translation that puts the number in the middle ("第 3 步")
  // cannot be produced by gluing a number onto a translated prefix, and the zh-Hant table had
  // duly rendered "第 3" with the counter missing.
  const numbered = primary.match(/^Step (\d+)$/);
  if (numbered) return t("trace.step", `Step ${numbered[1]}`, { n: numbered[1] });
  const known = TRACE_HEADLINES[primary];
  return known ? known() : primary;
}

// One line, the shape `cve-reverser`/`diff-sentry`'s feeds use: a translated headline, the run's own
// specific, and a compact fact. It used to be a fixed sentence per event type with the payload
// thrown away, which is why ours said so much less than theirs.
function traceLabel(event) {
  if (!event) return "";
  if (event.kind === "not_found") return t("trace.notFound", "No live progress for this run");
  // A kind with no headline at all (an event type this build has no name for): keep whatever is on
  // screen rather than overwriting a meaningful line with an internal event name — which is how
  // `run_start` once reached a user's screen as the literal string `run_start`.
  if (event.kind === "other" && !event.primary) return "";
  const parts = [traceHeadline(event)];
  if (event.detail) parts.push(event.detail);
  return parts.filter(Boolean).join(" \u00b7 ");
}

//: notebook id -> how many runs this TAB currently has in flight against it. Answers "which
//: notebook is generating" in the picker, which is otherwise unknowable once you switch away.
//:
//: Client-side on purpose, and honest about its limit: it counts runs THIS tab started. A run
//: started in another tab (or before a reload) is invisible here. The server's own registries are
//: single-process, in-memory maps (invariant 23) with no endpoint to read them, and adding one is
//: a bigger change than the question needs.
const activeRuns = new Map();

function noteRunStarted(notebookId) {
  activeRuns.set(notebookId, (activeRuns.get(notebookId) || 0) + 1);
  store.emit("runs:changed", { activeRuns });
}

function noteRunFinished(notebookId) {
  const left = (activeRuns.get(notebookId) || 1) - 1;
  if (left > 0) activeRuns.set(notebookId, left);
  else activeRuns.delete(notebookId);
  store.emit("runs:changed", { activeRuns });
}

//: How long a single step may go without news before the wait itself becomes the message. Long
//: enough that an ordinary step never trips it, short enough to answer "is it stuck" before someone
//: has to ask. A model's FIRST response on the Claude-subscription path was measured at four
//: minutes, which is the case this exists for.
const WAITING_AFTER_SECONDS = 20;

function runStatus({ notebookId, runIds, label, onCancel }) {
  noteRunStarted(notebookId);
  const node = document.createElement("div");
  node.className = "run-status";

  const dot = document.createElement("span");
  dot.className = "run-dot";
  node.appendChild(dot);

  const text = document.createElement("span");
  text.className = "run-text";
  text.textContent = label;
  node.appendChild(text);

  const elapsed = document.createElement("span");
  elapsed.className = "run-elapsed";
  elapsed.textContent = "0:00";
  node.appendChild(elapsed);

  const stop = document.createElement("button");
  stop.type = "button";
  stop.className = "btn run-stop";
  stop.textContent = t("run.stop", "\u23f9 Stop");
  node.appendChild(stop);

  // An expandable LOG of every step, under the counters. "Starting up…" sitting alone for a minute
   // was reported as uninformative — a single current-activity line cannot say which stage is slow,
   // only which one is now. The log answers "where is it stuck": each step keeps its own elapsed
   // stamp, so a long gap is visible rather than inferred. Collapsed by default, because the whole
   // point of the one-line summary is that most of the time nobody needs the rest.
  const log = document.createElement("div");
  log.className = "run-log";
  log.hidden = true;

  const logToggle = document.createElement("button");
  logToggle.type = "button";
  logToggle.className = "run-log-toggle";
  logToggle.hidden = true;
  logToggle.addEventListener("click", () => {
    log.hidden = !log.hidden;
    logToggle.classList.toggle("is-open", !log.hidden);
  });

  function appendLog(event) {
    const headline = traceHeadline(event);
    if (!headline) return;
    const line = document.createElement("div");
    line.className = `run-log-line kind-${event.kind || "other"}`;

    const at = document.createElement("span");
    at.className = "run-log-at";
    at.textContent = formatTimecode((Date.now() - started) / 1000);
    line.appendChild(at);

    const what = document.createElement("span");
    what.className = "run-log-what";
    const primary = document.createElement("b");
    primary.textContent = headline;
    what.appendChild(primary);
    if (event.meta) {
      // Inside `what`, immediately after the label. It used to be a third grid column pinned to the
      // right edge, which on a wide panel left a hand's width of empty box between "啟動" and
      // "GenerateSummary" and read as a broken layout rather than as one log line.
      const meta = document.createElement("span");
      meta.className = "run-log-meta";
      meta.textContent = event.meta;
      what.appendChild(meta);
    }
    if (event.detail) {
      // The model's own words. This is the part that makes the log worth opening — and the part
      // the previous version discarded entirely.
      //
      // Named `reasoningText`, not `detail`: the hidden-toggle tripwire matches variable names
      // across the whole file, and a `detail` here collides with the reference panel's own
      // `detail.hidden = …`. It fails loudly, which is the safe direction — so the fix is the name.
      const reasoningText = document.createElement("span");
      reasoningText.className = "run-log-detail";
      reasoningText.textContent = event.detail;
      what.appendChild(reasoningText);
    }
    line.appendChild(what);
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
    logToggle.hidden = false;
    logToggle.textContent = t("run.logToggle", `${log.children.length} steps`, {
      n: log.children.length,
    });
  }

  // A typed COUNT per kind of work, not a scrolling log. `nuclei-forge/studio` settled this shape
  // and its own comment says why the framing matters: a raw count climbing forever reads as
  // runaway, while a small set of named counters reads as progress. Three kinds is all our trace
  // has (`_translate_trace_event`), and three is about the ceiling before a status line becomes
  // noise — the thing the user asked to avoid.
  const counts = { tool: 0, escalation: 0 };
  const meter = document.createElement("span");
  meter.className = "run-meter";
  meter.hidden = true;
  node.appendChild(meter);

  // No `thinking` cell: the log toggle right below already says "N steps", and two counters one
  // line apart saying the same number reads as a bug. These are the kinds a step count does NOT
  // cover.
  const COUNT_LABELS = {
    tool: () => t("run.count.tool", "tools"),
    escalation: () => t("run.count.escalation", "sub-model"),
  };

  function renderMeter() {
    meter.textContent = "";
    let any = false;
    Object.entries(counts).forEach(([kind, n]) => {
      if (!n) return;  // a kind that has not happened is not information, it is clutter
      any = true;
      const cell = document.createElement("span");
      cell.className = "run-count";
      const num = document.createElement("b");
      num.textContent = String(n);
      cell.appendChild(num);
      cell.appendChild(document.createTextNode(" " + COUNT_LABELS[kind]()));
      meter.appendChild(cell);
    });
    meter.hidden = !any;
  }

  const started = Date.now();
  node.appendChild(logToggle);
  node.appendChild(log);

  // "Is it stuck?" — a user had to ask, and the honest answer was no: the run finished fine, but
  // the model's FIRST response took four minutes and the trace has nothing to emit until a step
  // completes, so the panel looked identical to a hang for four minutes.
  //
  // The interface has to answer that question itself, and the only fact it has is how long the
  // current step has been running. Below the threshold this says nothing (a step taking six
  // seconds is not news); above it, the wait becomes the message.
  let lastEventAt = started;
  let currentPhrase = label;
  let stepsSeen = 0;

  function paint() {
    elapsed.textContent = formatTimecode((Date.now() - started) / 1000);
    const waiting = (Date.now() - lastEventAt) / 1000;
    if (waiting < WAITING_AFTER_SECONDS) {
      text.textContent = currentPhrase;
      node.classList.remove("is-waiting");
      return;
    }
    node.classList.add("is-waiting");
    // BEFORE the first step, "waiting" says nothing a reader did not already know — that stage IS
    // waiting. What they cannot see is WHAT it is waiting for, and that the first model response
    // is the slow one. After a step has landed, the elapsed time is the information: it is the
    // difference between a slow step and a stuck one.
    text.textContent = stepsSeen
      ? `${currentPhrase} \u00b7 ${t("run.waiting", `waiting ${formatTimecode(waiting)}`, { time: formatTimecode(waiting) })}`
      : t("run.awaitingModel", `waiting for the model's first response \u00b7 ${formatTimecode(waiting)}`, { time: formatTimecode(waiting) });
  }

  const timer = setInterval(paint, 1000);

  let stopped = false;
  function finish() {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);
    node.classList.add("is-done");
    noteRunFinished(notebookId);
  }

  stop.addEventListener("click", async () => {
    stop.disabled = true;
    text.textContent = t("run.stopping", "Stopping\u2026");
    // Cancel every run this action started, not "whatever this notebook is doing" — a notebook-
    // scoped cancel would leave `/overview`'s second run burning a model call to completion.
    await Promise.all(
      runIds.map((runId) =>
        api(
          `/notebooks/${encodeURIComponent(notebookId)}/runs/${encodeURIComponent(runId)}/cancel`,
          { method: "POST" }
        ).catch(() => {})
      )
    );
    finish();
    if (onCancel) onCancel();
  });

  return {
    node,
    // The whole event, not just its text: the KIND is what the counters are made of, and the
    // summary alone threw it away.
    onEvent(event) {
      if (stopped || !event) return;
      if (counts[event.kind] !== undefined) {
        counts[event.kind] += 1;
        renderMeter();
      }
      if (event.kind === "thinking") stepsSeen += 1;
      const phrase = traceLabel(event);
      if (phrase) {
        currentPhrase = phrase;
        lastEventAt = Date.now();
        paint();
        appendLog(event);
      }
    },
    setSummary(summary) {
      if (stopped || !summary) return;
      currentPhrase = summary;
      lastEventAt = Date.now();
      paint();
    },
    finish,
  };
}

function renderTickerAffordance(runId) {
  const events = tickerLogs.get(runId) || [];
  const wrapper = document.createElement("div");
  wrapper.className = "ticker-affordance";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "ticker-toggle trace-face";
  toggle.textContent = t("err.steps", `⌁ ${events.length} step${events.length === 1 ? "" : "s"}`, { n: events.length });

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
  // Clicking the SAME citation again collapses the panel, rather than blanking it to t("cite.loading", "Loading…")
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
  detailArea.textContent = t("cite.loading", "Loading…");
  try {
    const params = new URLSearchParams({ source_id: citation.source_id, locator: citation.locator });
    const data = await api(
      `/notebooks/${encodeURIComponent(state.notebookId)}/runs/${encodeURIComponent(runId)}/citation-turn?${params}`
    );
    if (detailArea._requestToken !== token) return; // superseded by a newer click
    detailArea.textContent = "";
    const note = document.createElement("div");
    note.className = "citation-detail-note";
    note.textContent = t("cite.traceHead", "Where the model read this source (not proof the surrounding prose is faithful):");
    detailArea.appendChild(note);
    detailArea.appendChild(renderTraceStep(data.payload));
  } catch (err) {
    if (detailArea._requestToken !== token) return;
    detailArea.textContent = "";
    const note = document.createElement("div");
    note.className = "citation-detail-note";
    // A 404 here is the ORDINARY outcome, not a fault: the lookup is a marker search through one
    // run's trace (invariant 29), and a marker the model only ever handled inside a truncated
    // sub-call field, or a trace already collected by retention, simply is not findable. Showing
    // `404: marker for source 's3' locator 'whole' not found in this trace` was reported, fairly,
    // as unintelligible — it reads as a broken feature rather than as "no record of this".
    note.textContent = /\b404\b/.test(String(err.message))
      ? t(
          "cite.traceMissing",
          "No step in this run's record shows the model reading that exact passage. The record only covers what it echoed while working, and old records are cleared after a while."
        )
      : t("err.generic", `(error) ${err.message}`, { message: err.message });
    detailArea.appendChild(note);
  }
}

// A trace step, in the same visual language as the source viewer: reasoning is prose, code is a
// code block, output is the source text it read. It used to be `JSON.stringify(payload, null, 2)`
// in a `<pre>` — a wall containing an entire article, which a user called unreadable, correctly.
function renderTraceStep(payload) {
  const wrap = document.createElement("div");
  wrap.className = "trace-step";
  const data = payload || {};

  if (data.reasoning || data.final_reasoning) {
    const prose = document.createElement("p");
    prose.className = "trace-reasoning";
    prose.textContent = data.reasoning || data.final_reasoning;
    wrap.appendChild(prose);
  }

  if (data.code) {
    wrap.appendChild(traceBlock(t("trace.code", "Code it ran"), data.code, "trace-code", false));
  }

  // COLLAPSED: the output is whatever the model printed, which for a read step is a whole source.
  // That is the part that made the old panel a wall.
  if (data.output) {
    const text = typeof data.output === "string" ? data.output : JSON.stringify(data.output, null, 2);
    wrap.appendChild(traceBlock(t("trace.output", "What came back"), text, "trace-output", true));
  }

  // Anything this renderer has no shape for, rather than dropping it silently.
  const known = new Set(["reasoning", "final_reasoning", "code", "output", "turn"]);
  const rest = Object.fromEntries(Object.entries(data).filter(([k]) => !known.has(k)));
  if (Object.keys(rest).length) {
    wrap.appendChild(
      traceBlock(t("trace.other", "Other fields"), JSON.stringify(rest, null, 2), "trace-code", true)
    );
  }
  return wrap;
}

function traceBlock(label, text, className, collapsed) {
  const section = document.createElement("details");
  section.className = "trace-block";
  section.open = !collapsed;

  const summary = document.createElement("summary");
  summary.textContent = `${label} \u00b7 ${text.length.toLocaleString()}`;
  section.appendChild(summary);

  const pre = document.createElement("pre");
  pre.className = `${className} trace-face`;
  pre.textContent = text;
  section.appendChild(pre);
  return section;
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

// A source's ORIGIN is a machine string: a URL, or `pasted:<first words>#<hash>` for pasted text.
// Showing it raw as the modal's title produced the thing a user called too rough — a header reading
// `text · pasted:Voyager 1 launched on September 5, 1977. Voyager 2 launched #b2ad719a`.
function sourceDisplayName(source) {
  const origin = source.origin || "";
  if (origin.startsWith("pasted:")) {
    // Everything between the marker and the content hash IS the readable snippet `ingest_pasted_
    // text` deliberately puts there (invariant 30 — a bare hash was found to be a real regression).
    const snippet = origin.slice("pasted:".length).replace(/#[0-9a-f]+$/, "").trim();
    return snippet || t("source.pasted", "Pasted text");
  }
  try {
    const url = new URL(origin);
    // The host is what identifies a page at a glance; the path is detail, and it belongs in the
    // metadata rows below rather than in the title.
    return url.hostname.replace(/^www\./, "");
  } catch {
    return origin;
  }
}

// The metadata block above the text: what this source IS, where it came from, and how big it is.
// Every value goes in through `textContent` — an origin can carry attacker-supplied text from a
// page that was fetched (invariants 6 and 29).
function renderSourceMeta(source) {
  const meta = document.createElement("dl");
  meta.className = "source-meta";

  const rows = [];
  rows.push([t("source.kind", "Kind"), String(source.kind || "").toUpperCase()]);

  const origin = source.origin || "";
  if (/^https?:\/\//.test(origin)) {
    rows.push([t("source.url", "Address"), origin, origin]);
  } else if (origin.startsWith("pasted:")) {
    rows.push([t("source.origin", "Origin"), t("source.pastedIn", "Pasted into this notebook")]);
  } else {
    rows.push([t("source.origin", "Origin"), origin]);
  }

  const chars = (source.blocks || []).reduce((n, b) => n + (b.text ? b.text.length : 0), 0);
  rows.push([
    t("source.size", "Size"),
    t("source.sizeValue", `${source.blocks.length} blocks · ${chars.toLocaleString()} characters`, {
      blocks: source.blocks.length,
      chars: chars.toLocaleString(),
    }),
  ]);

  if (source.flags && source.flags.length) {
    rows.push([t("source.flags", "Flagged"), source.flags.join("; ")]);
  }

  rows.forEach(([term, value, href]) => {
    const dt = document.createElement("dt");
    dt.textContent = term;
    meta.appendChild(dt);
    const dd = document.createElement("dd");
    if (href) {
      const link = document.createElement("a");
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = value;
      dd.appendChild(link);
    } else {
      dd.textContent = value;
    }
    meta.appendChild(dd);
  });

  return meta;
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
  body.textContent = t("cite.loading", "Loading…");

  try {
    const source = await api(
      `/notebooks/${encodeURIComponent(state.notebookId)}/sources/${encodeURIComponent(sourceId)}`,
      { signal: controller.signal }
    );
    if (controller.signal.aborted) return;
    title.textContent = sourceDisplayName(source);
    body.innerHTML = "";
    body.appendChild(renderSourceMeta(source));
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
    body.textContent = t("err.generic", `(error) ${err.message}`, { message: err.message });
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

// Notebooks are located by TITLE. The id never appears — it is an internal handle (invariant 37),
// and putting it in front of the name (with `N sources, M turns` beside it) was the whole problem:
// a user could not tell which notebook was which without reading machine metadata.
async function refreshNotebookList() {
  const menu = document.getElementById("notebook-menu");
  let data;
  try {
    data = await api("/notebooks");
  } catch {
    return; // the picker keeps whatever it last showed; opening it will retry
  }
  menu.innerHTML = "";

  data.notebooks.forEach((nb) => {
    menu.appendChild(renderNotebookRow(nb));
  });

  const create = document.createElement("button");
  create.type = "button";
  create.className = "notebook-row notebook-row-new";
  create.textContent = t("app.newNotebookRow", "\uff0b New notebook");
  create.addEventListener("click", () => {
    closeNotebookMenu();
    resetToNewNotebook();
  });
  menu.appendChild(create);

  if (data.unreadable.length) {
    console.warn("unreadable notebook files (flagged, not hidden):", data.unreadable);
  }
}

// Coarse on purpose: the row needs "which of these is recent", not a timestamp. Anything older
// than a week falls back to a real date, because "37 days ago" is not something anyone can place.
function relativeTime(epochSeconds) {
  const seconds = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (seconds < 90) return t("time.justNow", "just now");
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return t("time.minutes", `${minutes}m ago`, { n: minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t("time.hours", `${hours}h ago`, { n: hours });
  const days = Math.round(hours / 24);
  if (days <= 7) return t("time.days", `${days}d ago`, { n: days });
  return new Date(epochSeconds * 1000).toLocaleDateString(uiLang());
}

function renderNotebookRow(nb) {
  const row = document.createElement("div");
  row.className = "notebook-row";
  if (nb.id === state.notebookId) row.classList.add("is-current");
  if (activeRuns.has(nb.id)) row.classList.add("is-running");

  const open = document.createElement("button");
  open.type = "button";
  open.className = "notebook-row-open";
  open.setAttribute("role", "option");

  if (activeRuns.has(nb.id)) {
    const dot = document.createElement("span");
    dot.className = "run-dot notebook-row-dot";
    dot.dataset.tip = t("app.generating", "Generating something in this notebook");
    open.appendChild(dot);
  }

  const title = document.createElement("span");
  title.className = "notebook-row-title";
  // textContent, never innerHTML: a title is model-authored text derived from source content a
  // prompt-injected source could influence (invariants 6 and 29).
  //
  // `derived_title` is the server's own fallback (from the notebook's origins, no model call), so a
  // notebook someone has only put sources into reads as its subject rather than as "Untitled" —
  // titling is lazy now, so that is the common case, not a rare one.
  title.textContent = nb.title || nb.derived_title || t("app.untitled", "Untitled notebook");
  open.appendChild(title);

  const meta = document.createElement("span");
  meta.className = "notebook-row-meta";
  const parts = [
    t("app.rowMeta", `${nb.source_count} sources · ${nb.turn_count} turns`, {
      sources: nb.source_count,
      turns: nb.turn_count,
    }),
  ];
  // Model-authored titles are NOT unique — a user hit three notebooks with near-identical generated
  // names. With the id no longer shown anywhere, "which did I touch last" is the only thing left to
  // tell them apart, so it goes on the row rather than being something to work out.
  if (nb.updated_at) parts.push(relativeTime(nb.updated_at));
  meta.textContent = parts.join(" \u00b7 ");
  open.appendChild(meta);

  open.addEventListener("click", () => {
    closeNotebookMenu();
    openNotebook(nb.id);
  });
  row.appendChild(open);

  const rename = document.createElement("button");
  rename.type = "button";
  rename.className = "notebook-row-rename";
  rename.textContent = "\u270e\ufe0e";
  rename.dataset.tip = t("app.rename", "Rename");
  rename.addEventListener("click", (event) => {
    event.stopPropagation();
    startRename(row, nb);
  });
  row.appendChild(rename);

  return row;
}

// Rename in place. A PUT, never the generate endpoint: setting a title is an instant write that
// always succeeds, generating one is a model run that can fail and be superseded.
function startRename(row, nb) {
  row.innerHTML = "";
  const input = document.createElement("input");
  input.className = "notebook-rename-input";
  input.value = nb.title || "";
  input.maxLength = 120;
  row.appendChild(input);

  async function commit() {
    const value = input.value.trim();
    if (!value || value === nb.title) {
      refreshNotebookList();
      return;
    }
    try {
      const updated = await api(`/notebooks/${encodeURIComponent(nb.id)}/title`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: value }),
      });
      if (nb.id === state.notebookId) {
        state.title = updated.title;
        store.emit("notebook:titled", { title: state.title, notebookId: nb.id });
      }
    } catch (err) {
      alert(t("err.rename", `Could not rename: ${err.message}`, { message: err.message }));
    }
    refreshNotebookList();
  }

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commit();
    }
    if (event.key === "Escape") {
      // Detach the blur handler FIRST. Escape used to call the async refresh with `commit` still
      // listening on a focused input, so any focus change while that request was in flight sent the
      // typed value as a real rename — a cancel that could commit.
      input.removeEventListener("blur", commit);
      refreshNotebookList();
    }
  });
  input.addEventListener("blur", commit);
  input.focus();
  input.select();
}

function closeNotebookMenu() {
  const menu = document.getElementById("notebook-menu");
  const button = document.getElementById("notebook-current");
  menu.hidden = true;
  button.setAttribute("aria-expanded", "false");
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
  state.notebookSlug = notebook.slug || notebook.id;
  state.title = notebook.title || null;
  state.derivedTitle = notebook.derived_title || null;
  state.overview = notebook.overview || null;
  state.podcast = notebook.podcast || null;
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
// Title on DEMAND. Called by the actions that already run a model, never by adding a source.
// Fire-and-forget on purpose: a title must never delay or fail the thing the user actually asked
// for (the same "never lose what already succeeded" rule invariants 19 and 37 encode).
function ensureTitle() {
  if (!state.notebookId || state.title || !state.sources.length) return;
  void suggestTitle(state.notebookId, notebookGeneration);
}

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

// --- Settings ---------------------------------------------------------------------------------
//
// PRESENTATION settings only: the language the model writes in, and the voices that read it.
// Trace retention, the upload cap and every model/credential variable are deliberately absent —
// "non-secret" is the wrong filter, since lowering retention DELETES traces holding ingested source
// text and raising the upload cap is a DoS lever. Those are safety bounds, and this API has no
// authentication (invariant 25).
//
// Every row shows where its value comes from. A row pinned by an environment variable is DISABLED
// and says which one: a form that accepts a value and then quietly loses to the env would be a UI
// that lies, which is worse than not having the control.

// A FUNCTION, not a module-level const: the labels go through `t()`, and a const would freeze
// whatever language was active when the script loaded.
function settingRows() {
  const voiceHelp = t(
    "settings.voiceHelp",
    "Leave empty for the provider's default: edge-tts follows the notebook's language, chatterbox uses its shipped host-a / host-b voices."
  );
  return [
    {
      key: "output_language",
      choicesKey: "output_languages",
      label: t("settings.outputLanguage", "Output language"),
      placeholder: t("settings.outputLanguagePlaceholder", "e.g. Traditional Chinese"),
      help: t(
        "settings.outputLanguageHelp",
        "Leave empty to let each notebook resolve its own from your browser, its sources and your questions."
      ),
    },
    // Provider-aware on purpose: with chatterbox `default_voices` returns null for EVERY language,
    // so "empty" means its two shipped clips, not "follow the language" (invariant 43).
    {
      key: "tts_voice_host_a",
      choicesKey: "voices",
      label: t("settings.voiceA", "Podcast voice — host A"),
      placeholder: "e.g. zh-TW-YunJheNeural or host-a",
      help: voiceHelp,
    },
    {
      key: "tts_voice_host_b",
      choicesKey: "voices",
      label: t("settings.voiceB", "Podcast voice — host B"),
      placeholder: "e.g. zh-TW-HsiaoChenNeural or host-b",
      help: voiceHelp,
    },
  ];
}

// The INTERFACE language row. Client-side only — it never reaches the server, because it is not a
// server setting: `RN_OUTPUT_LANGUAGE` decides what the MODEL writes, this decides what the buttons
// say, and a reader who wants a Chinese interface over English papers needs both to be expressible.
function renderUiLanguageRow(body) {
  const wrap = document.createElement("div");
  wrap.className = "setting-row";

  const label = document.createElement("label");
  label.textContent = t("settings.uiLanguage", "Interface language");
  label.htmlFor = "setting-ui-language";
  wrap.appendChild(label);

  const select = document.createElement("select");
  select.id = "setting-ui-language";
  const current = uiLang();
  UI_LANGUAGES.forEach((lang) => {
    const option = document.createElement("option");
    option.value = lang.code;
    option.textContent = lang.label;
    option.selected = lang.code === current;
    select.appendChild(option);
  });
  select.addEventListener("change", () => setUiLang(select.value));
  wrap.appendChild(select);

  const help = document.createElement("div");
  help.className = "setting-help";
  help.textContent = t(
    "settings.uiLanguageHelp",
    "Only affects the text on this screen, never what the model writes."
  );
  wrap.appendChild(help);

  body.appendChild(wrap);
}

//: What the server says each setting may be set to, for the provider actually configured. Empty
//: until `initSettings` fetches it; a row with no choices falls back to a free-text input, so the
//: page still works if this request fails.
let settingsChoices = {};

function renderSettings(state_) {
  const body = document.getElementById("settings-body");
  body.textContent = "";

  if (state_.error) {
    // Surfaced, never swallowed — the reader falls back to defaults on a corrupt file, and the one
    // place that can say so is here (the same "flag, never silently drop" shape the notebook
    // listing already uses for an unparseable file).
    const warn = document.createElement("div");
    warn.className = "setting-source";
    warn.textContent = t(
      "settings.readError",
      `Settings file could not be read (${state_.error}); showing defaults.`,
      { error: state_.error },
    );
    body.appendChild(warn);
  }

  const inputs = new Map();
  renderUiLanguageRow(body);

  settingRows().forEach((row) => {
    const entry = state_[row.key] || { value: null, source: "default", env_var: "" };
    const wrap = document.createElement("div");
    wrap.className = "setting-row";

    const label = document.createElement("label");
    label.textContent = row.label;
    label.htmlFor = `setting-${row.key}`;
    wrap.appendChild(label);

    // A SELECT when the server told us what the valid values are, a text box otherwise. Free text
    // here was a way to typo an env-var value into a setting that then fails at synthesis time —
    // and `config._VOICE_PATTERN` has to refuse a bad one anyway, so offering the choices is both
    // safer and less work for the person. The options come from `GET /settings/choices` rather than
    // a list in this file, because the answer is provider-specific and a second copy would drift.
    const choices = settingsChoices[row.choicesKey] || [];
    const current = entry.source === "default" ? "" : entry.value || "";
    let input;
    if (choices.length) {
      input = document.createElement("select");
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = t("settings.useDefault", "Use the default");
      input.appendChild(blank);
      // A value already stored that is NOT in the list (an env var, or a voice from another
      // provider left behind by a switch) still has to be selectable, or opening the page and
      // pressing Save would silently clear it.
      const options = choices.includes(current) || !current ? choices : [current, ...choices];
      options.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        option.selected = value === current;
        input.appendChild(option);
      });
    } else {
      input = document.createElement("input");
      input.type = "text";
      input.placeholder = row.placeholder;
      // textContent/value, never innerHTML — these are server-echoed, caller-writable strings.
      input.value = current;
    }
    input.id = `setting-${row.key}`;
    input.disabled = entry.source === "env";
    wrap.appendChild(input);
    inputs.set(row.key, input);

    const note = document.createElement("div");
    note.className = "setting-source";
    note.textContent =
      entry.source === "env"
        ? t("settings.pinnedBy", `Pinned by ${entry.env_var} — unset it to edit here.`, { env: entry.env_var })
        : row.help;
    wrap.appendChild(note);

    body.appendChild(wrap);
  });

  const save = document.createElement("button");
  save.type = "button";
  save.className = "btn btn-primary";
  save.textContent = t("settings.save", "Save");
  save.addEventListener("click", async () => {
    save.disabled = true;
    const payload = {};
    inputs.forEach((input, key) => {
      if (!input.disabled && input.value.trim()) payload[key] = input.value.trim();
    });
    try {
      renderSettings(await api("/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }));
    } catch (err) {
      alert(t("settings.saveFailed", `Could not save settings: ${err.message}`, { message: err.message }));
    } finally {
      save.disabled = false;
    }
  });
  body.appendChild(save);
}

function initSettings() {
  const overlay = document.getElementById("settings-overlay");
  const close = () => {
    overlay.hidden = true;
  };

  document.getElementById("settings-open").addEventListener("click", async () => {
    closeSourceViewer(); // one overlay at a time — both carry z-index 1000, so DOM order would decide
    overlay.hidden = false;
    document.getElementById("settings-body").textContent = t("cite.loading", "Loading…");
    try {
      // Fetched alongside the settings themselves, and tolerated failing: a row with no choices
      // falls back to free text, so a page that cannot reach this still works.
      settingsChoices = await api("/settings/choices").catch(() => ({}));
      renderSettings(await api("/settings"));
    } catch (err) {
      document.getElementById("settings-body").textContent = t("err.generic", `(error) ${err.message}`, { message: err.message });
    }
  });
  document.getElementById("settings-close").addEventListener("click", close);
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close();
  });
  // The source viewer's Escape handler is its own; without this one Escape would close that and
  // leave this open.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !overlay.hidden) close();
  });
}

function initNotebookTitle() {
  const el = document.getElementById("notebook-title");
  const button = document.getElementById("notebook-current");
  // The header says whether the notebook you are LOOKING at is busy; the picker says which of the
  // others are. Between them "where is that generation I started" has an answer.
  const runDot = document.getElementById("notebook-run-dot");
  store.on("runs:changed", () => {
    runDot.hidden = !activeRuns.has(state.notebookId);
    const menu = document.getElementById("notebook-menu");
    if (!menu.hidden) refreshNotebookList();
  });
  store.on("notebook:titled", ({ title, notebookId }) => {
    // textContent, never innerHTML — a title is model-authored text derived from source content
    // a prompt-injected source could influence (CLAUDE.md invariants 6 and 29).
    // The SAME fallback the picker row uses. They disagreed — the header said "Untitled notebook"
    // while the row showed the server's derived label for the same notebook, which reads as two
    // different notebooks.
    el.textContent = notebookId
      ? title || state.derivedTitle || t("app.untitled", "Untitled notebook")
      : t("app.noNotebook", "No notebook yet");
  });
}

function initNotebookSwitch() {
  const button = document.getElementById("notebook-current");
  const menu = document.getElementById("notebook-menu");

  button.addEventListener("click", (event) => {
    event.stopPropagation();
    const opening = menu.hidden;
    menu.hidden = !opening;
    button.setAttribute("aria-expanded", String(opening));
    if (opening) refreshNotebookList(); // always fresh: titles change, notebooks appear
  });

  // Click-away and Escape both close it. Without these the panel stays open over the workspace and
  // the only way out is clicking the button again, which reads as broken.
  document.addEventListener("click", (event) => {
    if (!menu.hidden && !menu.contains(event.target)) closeNotebookMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !menu.hidden) closeNotebookMenu();
  });

  document.getElementById("new-notebook").addEventListener("click", () => {
    closeNotebookMenu();
    resetToNewNotebook();
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
  state.notebookSlug = null;
  state.title = null;
  state.derivedTitle = null;
  state.overview = null;
  state.podcast = null;
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
// A URL, shortened to what identifies it at a glance once the title is carrying the meaning.
function prettyOrigin(origin) {
  try {
    const url = new URL(origin);
    const path = url.pathname === "/" ? "" : url.pathname;
    return url.hostname.replace(/^www\./, "") + path;
  } catch {
    return origin;
  }
}

function renderSourceItem(source) {
  const li = document.createElement("li");
  li.className = "source-item";
  li.addEventListener("click", () => showSourceViewer(source.id, null, null));

  const kind = document.createElement("div");
  kind.className = "src-kind";
  kind.textContent = source.kind;
  li.appendChild(kind);

  // A PREVIEW CARD when the page told us what it is: its own title, a line of its own description,
  // and its site name. Falls back to the bare origin, which is all a pasted-text or file source
  // has. Every value goes in through `textContent` — a page controls its own `<meta>` tags, so this
  // is attacker-influenceable display text (invariants 6 and 29), and it is never citable: the
  // corpus is built from `blocks` alone. Deliberately NO image: rendering `og:image` would make the
  // reader's browser fetch a URL the page author chose, handing that third party an IP and a
  // request to log, for a thumbnail.
  const preview = source.preview || {};
  if (preview.title) {
    const heading = document.createElement("div");
    heading.className = "src-title";
    heading.textContent = preview.title;
    li.appendChild(heading);
  }

  const origin = document.createElement("div");
  origin.className = "src-origin";
  origin.textContent = preview.title ? prettyOrigin(source.origin) : source.origin;
  li.appendChild(origin);

  if (preview.description) {
    const description = document.createElement("div");
    description.className = "src-description";
    description.textContent = preview.description;
    li.appendChild(description);
  }

  if (source.flags && source.flags.length) {
    const flags = document.createElement("div");
    flags.className = "src-flags";
    // The flag is advisory and gates nothing (invariant 6), so it says what was seen and — via the
    // tooltip — what that means. It used to print the raw regex, which a user reasonably asked
    // about; a warning nobody can act on teaches people to ignore the ones that matter.
    flags.textContent = `\u26a0 ${source.flags.join(", ")}`;
    flags.dataset.tip = t(
      "sources.flagHelp",
      "Found in this source's own text, not in your question. It is not blocked and answers still cite it — this is a heads-up that the source contains something shaped like an instruction to a model."
    );
    li.appendChild(flags);
  }

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "src-remove";
  remove.textContent = "\u2715\ufe0e";
  remove.dataset.tip = t("sources.remove", "Remove this source");
  remove.addEventListener("click", async (event) => {
    // The row itself opens the source viewer; without this the remove click would do both.
    event.stopPropagation();
    if (!confirm(t("sources.removeConfirm", `Remove "${source.origin}" from this notebook?`, { origin: source.origin }))) {
      return;
    }
    remove.disabled = true;
    try {
      const notebook = await api(
        `/notebooks/${encodeURIComponent(state.notebookId)}/sources/${encodeURIComponent(source.id)}`,
        { method: "DELETE" }
      );
      state.sources = notebook.sources;
      state.overview = notebook.overview || null;
      state.podcast = notebook.podcast || null;
      // `sources:changed` is what marks the overview and podcast stale and re-offers the Guide
      // tabs — removing a source moves the corpus exactly as adding one does.
      store.emit("sources:changed", { sources: state.sources });
      renderChatOverview();
    } catch (err) {
      remove.disabled = false;
      alert(t("err.removeSource", `Could not remove source: ${err.message}`, { message: err.message }));
    }
  });
  li.appendChild(remove);

  return li;
}

function initSourcesPanel() {
  const tabs = document.querySelectorAll("#source-kind-tabs .tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((tab) => tab.classList.remove("is-active"));
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
      // Already inside the slug whitelist, so it is its own slug until the
      // server confirms one on the next notebook response.
      state.notebookSlug = state.notebookId;
      notebookGeneration += 1;
    }
    const activeKind = document.querySelector("#source-kind-tabs .tab.is-active").dataset.kind;
    const nb = encodeURIComponent(state.notebookId);

    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    // Ingestion is a network fetch, a parse, and possibly OCR — seconds to tens of seconds, with
    // nothing on screen saying so. Disabling one button is not feedback: the panel simply stopped
    // responding, which a user described as feeling stuck. `is-busy` spins the button and dims the
    // form, so the pause reads as work rather than as a hang.
    form.classList.add("is-busy");
    const submitLabel = submitBtn.textContent;
    submitBtn.textContent = t("sources.adding", "Adding\u2026");
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
      state.derivedTitle = notebook.derived_title || state.derivedTitle;
      store.emit("sources:changed", { sources: state.sources });
      store.emit("notebook:titled", { title: state.title, notebookId: state.notebookId });
      // Titling used to fire HERE, on the first source. That spent a real model call the moment
      // someone added a source, before they had asked for anything — a user called it too
      // aggressive and they were right. It now runs lazily, from `ensureTitle()`, which the
      // generate actions call: by then the user has already committed to a model run, so the
      // title costs nothing they were not already paying.
    } catch (err) {
      alert(t("err.addSource", `Could not add source: ${err.message}`, { message: err.message }));
    } finally {
      form.classList.remove("is-busy");
      submitBtn.textContent = submitLabel;
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
// A BOOKMARK in the answer's top-right corner, not a labelled button under the text. A full-width
// "+ Save as note" bar under every answer competed with the answer for attention and pushed the
// next turn down; a bookmark is the gesture people already know for "keep this", and it lives where
// they expect to find it. The label survives as the tooltip, so what it does is still one hover
// away — and it still says the part nobody could guess (promotion is what makes a note citable).
function saveAsNoteButton(text) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "save-as-note";
  btn.setAttribute("aria-label", t("chat.saveAsNote", "Save as note"));
  btn.textContent = "\u2606";  // U+2606 WHITE STAR — geometric, never emoji (see the theme toggle)
  btn.dataset.tip = t(
    "chat.saveAsNoteHelp",
    "Keep a copy in Notes (Studio, right). A note can later be PROMOTED into a source, which is what makes it citable by a later question."
  );
  btn.addEventListener("click", async (event) => {
    event.stopPropagation();
    btn.disabled = true;
    try {
      await addNote(text);
      btn.classList.add("is-saved");
      btn.textContent = "\u2605";  // filled
      btn.dataset.tip = t("chat.saved", "Saved to Notes");
    } finally {
      setTimeout(() => {
        btn.classList.remove("is-saved");
        btn.textContent = "\u2606";
        btn.disabled = false;
        btn.dataset.tip = t(
          "chat.saveAsNoteHelp",
          "Keep a copy in Notes (Studio, right). A note can later be PROMOTED into a source, which is what makes it citable by a later question."
        );
      }, 1800);
    }
  });
  return btn;
}

function renderAnswerWithCitations(text, citations, runId) {
  const container = document.createElement("div");

  // One number per distinct source span, shared by the inline strokes and the reference list, so
  // "this sentence" and "reference 2" are visibly the same thing.
  const numbers = new Map();
  citations.forEach((citation) => {
    const key = `${citation.source_id}\u0000${citation.locator}`;
    if (!numbers.has(key)) numbers.set(key, numbers.size + 1);
  });
  const referenceNumberFor = (citation) =>
    numbers.get(`${citation.source_id}\u0000${citation.locator}`) || 0;

  // Locate each citation's quote as a literal substring of the RAW answer text (never
  // pre-escaped — a DOM text node needs no escaping, only innerHTML does). The model may
  // paraphrase around a quote rather than reproducing it verbatim; when a quote can't be located,
  // the citation still surfaces in the citation list below, just not inline.
  const matches = [];
  citations.forEach((citation) => {
    // `answer_span` FIRST: the model's own words, in the reader's language, already confirmed
    // server-side to occur in this exact text (`citations.locate_answer_spans`). `quote` is the
    // fallback for turns saved before that field existed — it only ever matched when the answer and
    // the source shared a language, which stopped being the common case at invariant 39, and that
    // is why the strokes vanished.
    const needle = citation.answer_span || citation.quote;
    if (!needle) return;
    const at = text.indexOf(needle);
    if (at !== -1) matches.push({ start: at, end: at + needle.length, citation });
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
    // A number, so a stroke can be matched to its entry in the reference list below — and so the
    // page reads as annotated prose rather than as a block of highlighter. Set as a CSS counter
    // rather than injected text, which keeps the answer's own words exactly as the model wrote
    // them (a copy-paste must not pick up UI furniture).
    span.dataset.reference = String(referenceNumberFor(match.citation));
    // The coordinate this stroke points at, so `focusReference` can light up every stroke sharing
    // it. `.citation.is-focused` has been in the stylesheet promising that since the References
    // view landed, with nothing ever setting it — found by an independent review.
    span.dataset.refKey = referenceKey(match.citation);
    span.title = `${match.citation.source_id} · ${match.citation.locator}`;
    span.textContent = text.slice(match.start, match.end);
    if (runId) {
      span.classList.add("citation-clickable");
      // The inline stroke, when a quote CAN be located (same-language answers). Its detail panel
      // is created here so it belongs to this span rather than to a shared slot.
      // Opens the References view and takes the reader to that entry, rather than expanding a
      // panel inside the paragraph they are reading — which pushed the rest of the answer down and
      // made a crowded column worse.
      span.addEventListener("click", () => focusReference(match.citation));
    }
    container.appendChild(span);
    cursor = match.end;
  });
  if (cursor < text.length) {
    container.appendChild(document.createTextNode(text.slice(cursor)));
  }

  if (citations.length) {
    container.appendChild(renderReferenceLink(citations));
  }
  return container;
}

// One line under an answer, not a second copy of the reference list. The list itself lives in the
// References view now, where it is shared across every turn instead of repeating per answer.
function renderReferenceLink(citations) {
  const keys = new Set(citations.map(referenceKey));
  const link = document.createElement("button");
  link.type = "button";
  link.className = "reference-link";
  link.textContent = t("cite.references", `${keys.size} references`, { n: keys.size });
  link.addEventListener("click", () => focusReference(citations[0]));
  return link;
}

// A REFERENCE LIST, the way a paper carries one. It replaced a row of `✓ s3 · whole` repeated once
// per citation — four identical lines carrying no information, because a text or web source has a
// single block whose locator is literally "whole" — with one entry per DISTINCT source span,
// numbered, named, and showing the quoted evidence, which is the thing a reader actually wants to
// check.
//
// **The inline highlighter stroke (blueprint §2) cannot be drawn in cross-language mode, and this
// is the honest fallback rather than a workaround.** That stroke is located by finding the
// citation's `quote` as a substring of the answer. Since invariant 39 the answer follows the
// READER's language while the quote stays verbatim in the SOURCE's, so the two never share a
// substring and no span can be located. Restoring it needs the model to mark which part of its own
// answer each citation supports — a schema and instruction change, not something this renderer can
// recover.
// The readable name for a source, shared by the reference list and the viewer modal.
function sourceLabel(source) {
  const preview = source.preview || {};
  if (preview.title) return preview.title;
  return sourceDisplayName(source);
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
    el.appendChild(overviewStarter(t("chat.generateOverview", "\u2728 Generate overview"), t("chat.orJustAsk", "\u2026or just ask a question below.")));
    return;
  }

  const head = document.createElement("div");
  head.className = "chat-overview-head";
  head.textContent = overview.stale
    ? t("chat.overviewStale", "Overview \u00b7 sources have changed since this")
    : t("chat.overview", "Overview");
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
    label.textContent = t("chat.startWith", "Start with");
    el.appendChild(label);
    el.appendChild(starterQuestionRow(overview.starter_questions));
  }

  if (overview.stale) {
    el.appendChild(overviewStarter(t("chat.regenerateOverview", "\u21bb Regenerate overview"), ""));
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

  // The server appends `-summary`/`-faq` to the run id it derives, so both targets are predictable:
  // the ticker follows the summary, and Stop cancels BOTH (a notebook-scoped cancel would leave the
  // FAQ run burning a model call to completion).
  ensureTitle();
  const runToken = crypto.randomUUID();
  const base = `${state.notebookSlug || notebookId}-${runToken}`;
  let cancelled = false;
  const status = runStatus({
    notebookId,
    runIds: [`${base}-summary`, `${base}-faq`],
    label: t("chat.readingSources", "Reading your sources\u2026"),
    onCancel: () => {
      cancelled = true;
      overviewToken += 1; // strand this generation's own response
      renderChatOverview(); // straight back to the pre-run state, nothing half-written left behind
    },
  });
  el.appendChild(status.node);

  void openTicker(notebookId, `${base}-summary`, (event) => {
    if (live()) status.onEvent(event);
  });

  try {
    const notebook = await api(`/notebooks/${encodeURIComponent(notebookId)}/overview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runToken }),
    });
    status.finish();
    if (cancelled) return;
    if (!live()) {
      // SUPERSEDED, not lost. Saying nothing here is what made a real report read as "pressed
      // generate, it said Finished, then nothing ever appeared": the response arrived, this guard
      // dropped it silently, and the last ticker line just sat there looking stuck.
      supersededNote(el);
      return;
    }
    state.overview = notebook.overview;
    refreshReferenceView();
    renderChatOverview();
  } catch (err) {
    status.finish();
    if (cancelled) return;
    if (!live()) {
      supersededNote(el);
      return;
    }
    el.textContent = "";
    const note = document.createElement("div");
    note.textContent = t("chat.overviewFailed", `(could not generate an overview: ${err.message})`, { message: err.message });
    el.appendChild(note);
    el.appendChild(overviewStarter(t("chat.tryAgain", "\u21bb Try again"), ""));
  }
}

// A generation whose result is no longer the current one (the user regenerated, or switched
// notebooks and back). The old code returned silently, which is indistinguishable from a hang.
function supersededNote(el) {
  el.textContent = "";
  const note = document.createElement("div");
  note.className = "empty-note";
  note.textContent = t("chat.overviewSuperseded", "That overview was superseded by a newer one.");
  el.appendChild(note);
  el.appendChild(overviewStarter(t("chat.generateOverview", "\u2728 Generate overview"), ""));
}

function initChatPanel() {
  const history = document.getElementById("chat-history");
  const empty = document.getElementById("chat-empty");
  const form = document.getElementById("ask-form");
  const input = document.getElementById("ask-input");
  const submitBtn = document.getElementById("ask-submit");

  // Enter sends, Shift+Enter breaks a line. The convention every chat composer uses, and the reason
  // the hint row exists at all: without it this is a rule you can only find by accident.
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    // Never steal Enter mid-composition: an IME is still assembling a character, and submitting
    // there would send a half-typed word. `isComposing` is exactly what that flag is for, and this
    // matters far more here than in an English-only UI.
    if (event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    form.requestSubmit();
  });

  // The box grows with the question and stops at the CSS ceiling, then scrolls. Driven from the
  // real scrollHeight rather than a line count, so it is right for wrapped text too.
  const autoGrow = () => {
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
    form.classList.toggle("has-text", input.value.trim().length > 0);
  };
  input.addEventListener("input", autoGrow);
  autoGrow();

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
      alert(t("err.openNotebookFirst", "Open or name a notebook first."));
      return;
    }
    const question = input.value.trim();
    if (!question) return;

    // The CLIENT picks the run id (blueprint P3.1) — a server-generated one would never reach us
    // until the request was already over, too late to open a live ticker against it.
    const generation = notebookGeneration;
    const askedNotebookId = state.notebookId;
    const token = crypto.randomUUID();
    const runId = `${state.notebookSlug || state.notebookId}-${token}`;

    ensureTitle();
    const pendingTurn = { question, pending: true, run_id: runId };
    store.emit("chat:turnAdded", { turn: pendingTurn });
    store.emit("chat:pending", { pending: true });
    input.value = "";
    input.style.height = "auto";
    form.classList.remove("has-text");

    // The same live surface the Studio actions use, mounted into the pending answer row. Chat had
    // no way to stop a question either, and a question against a large corpus is not quick.
    let cancelled = false;
    const answerEl = history.querySelector(`.turn-answer[data-run-id="${CSS.escape(runId)}"]`);
    const status = runStatus({
      notebookId: askedNotebookId,
      runIds: [runId],
      label: t("chat.thinking", "Thinking\u2026"),
      onCancel: () => {
        cancelled = true;
        store.emit("chat:pending", { pending: false });
        const row = history.querySelector(`.turn-answer[data-run-id="${CSS.escape(runId)}"]`);
        if (row) {
          row.classList.remove("is-pending");
          row.textContent = t("chat.stopped", "(stopped)");
        }
      },
    });
    if (answerEl) {
      answerEl.textContent = "";
      answerEl.appendChild(status.node);
    }

    openTicker(state.notebookId, runId, (evt) => status.onEvent(evt));

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
      status.finish();
      if (cancelled) return;
      if (generation !== notebookGeneration) return;
      const notebook = await api(`/notebooks/${encodeURIComponent(askedNotebookId)}`);
      if (generation !== notebookGeneration) return;
      state.turns = notebook.turns;
      refreshReferenceView();
      history.innerHTML = "";
      history.appendChild(empty);
      empty.hidden = state.turns.length > 0;
      state.turns.forEach((turn) => history.appendChild(renderTurn(turn)));
      void result; // already folded into notebook.turns above
    } catch (err) {
      status.finish();
      if (cancelled) return;
      pendingTurn.pending = false;
      pendingTurn.answer = t("err.generic", `(error) ${err.message}`, { message: err.message });
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
      container.textContent = t("studio.noFaq", "(no FAQ items — the sources didn't produce enough to ask about)");
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
    container.textContent = t("studio.noTimeline", "(no timeline events — the sources didn't produce enough to place in time)");
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

//: What each Studio tab is FOR. Shown as the tab's own hover title and as the hint beside its
//: generate button, so the panel explains itself without a permanent paragraph of prose taking up
//: rail space — the pattern `toolscout`/`cve-reverser` already use for their own controls.
const GUIDE_LABELS = {
  summary: "summary",
  faq: "FAQ",
  timeline: "timeline",
  insight: "key insight",
};

function guideLabel(kind) {
  return t(`studio.kind.${kind}`, GUIDE_LABELS[kind] || kind);
}

const GUIDE_HINTS = {
  summary: "A few paragraphs covering what all your sources say, with citations you can check.",
  faq: "The questions your sources actually answer, each with its answer and a citation.",
  timeline: "Dated events pulled out of your sources and put in order.",
  insight: "The single most important takeaway, in one sentence.",
};

function guideHint(kind) {
  return t(`studio.tip.${kind}`, GUIDE_HINTS[kind] || "");
}

function initStudioPanel() {
  const tabs = document.querySelectorAll("#guide-tabs .tab");
  const body = document.getElementById("guide-body");
  const regenerateBtn = document.getElementById("guide-regenerate");
  // Cache VALUE widened to {result, runId} — storing the result alone (an earlier draft's shape)
  // would lose the run id the moment a user switches tabs and back, breaking citation-turn lookup
  // for a tab already left (found during this phase's own pre-implementation audit).
  // Keyed by kind, VALUE `{result, runId}` — storing the result alone would lose the run id the
  // moment a user switches tabs and back, breaking citation-turn lookup for a tab already left.
  const cache = {
    has: (kind) => kind in state.guides,
    get: (kind) => state.guides[kind],
    set: (kind, value) => {
      state.guides[kind] = value;
    },
    clear: () => {
      state.guides = {};
    },
  };
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
      note.textContent = t("studio.noNotebook", "Open a notebook with sources, then pick a tab to generate it.");
      body.appendChild(note);
      return;
    }
    ensureTitle();
    const generation = notebookGeneration;
    const token = crypto.randomUUID();
    const runId = `${state.notebookSlug || state.notebookId}-${token}`;
    body.classList.add("is-pending");
    body.innerHTML = "";
    let cancelled = false;
    const status = runStatus({
      notebookId: state.notebookId,
      runIds: [runId],
      label: t("studio.generating", `Generating the ${guideLabel(kind)}\u2026`, { kind: guideLabel(kind) }),
      onCancel: () => {
        cancelled = true;
        body.classList.remove("is-pending");
        showKind(kind); // straight back to the offer, nothing half-written left behind
      },
    });
    body.appendChild(status.node);
    openTicker(state.notebookId, runId, (evt) => status.onEvent(evt));
    try {
      const data = await api(`/notebooks/${encodeURIComponent(state.notebookId)}/guide/${kind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: token }),
      });
      status.finish();
      if (cancelled) return;
      if (generation !== notebookGeneration) return;  // switched away — never cache into the new one
      cache.set(kind, { result: data, runId });
      refreshReferenceView();
      body.classList.remove("is-pending");
      renderCached(kind, cache.get(kind));
    } catch (err) {
      status.finish();
      if (cancelled) return;
      body.classList.remove("is-pending");
      body.textContent = t("err.generic", `(error) ${err.message}`, { message: err.message });
    }
  }

  // Selecting a tab SHOWS it; it never starts a run. Switching tabs used to fire a real RLM call
  // immediately, so browsing the four kinds to see what they were cost four model runs and a user
  // could not tell which click had committed them to one. The offer is explicit now, matching the
  // chat overview's own "✨ Generate" affordance.
  function showKind(kind) {
    setActiveKind(kind);
    if (cache.has(kind)) {
      renderCached(kind, cache.get(kind));
      return;
    }
    body.innerHTML = "";
    if (!state.notebookId || !state.sources.length) {
      const note = document.createElement("p");
      note.className = "empty-note";
      note.textContent = t("studio.addSourceFirst", "Add a source first, then generate this.");
      body.appendChild(note);
      return;
    }
    const offer = document.createElement("div");
    offer.className = "chat-starter";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-primary";
    btn.textContent = t("studio.generate", `\u2728 Generate ${guideLabel(kind)}`, { kind: guideLabel(kind) });
    btn.addEventListener("click", () => fetchKind(kind));
    offer.appendChild(btn);
    const hint = document.createElement("p");
    hint.className = "empty-note";
    hint.textContent = guideHint(kind);
    offer.appendChild(hint);
    body.appendChild(offer);
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
  // opening a notebook. Neither does SELECTING a tab any more (see `showKind`); every run is an
  // explicit button press.
  store.on("notebook:switched", () => {
    invalidateCache();
    showKind("summary");
  });
  // A source changing invalidates the cache AND re-renders, so the panel goes back to offering a
  // fresh generation rather than silently holding a result computed from a corpus that has moved.
  store.on("sources:changed", () => {
    invalidateCache();
    showKind(activeKind);
  });

  showKind("summary");
}

// --- Studio panel: podcast player ------------------------------------------------------------

function formatTimecode(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const ss = String(total % 60).padStart(2, "0");
  const mm = Math.floor(total / 60) % 60;
  const hh = Math.floor(total / 3600);
  // An hour component only when there is one, so a three-minute episode stays `2:41` rather than
  // `0:02:41` — but a long one no longer renders `63:05`.
  return hh ? `${hh}:${String(mm).padStart(2, "0")}:${ss}` : `${mm}:${ss}`;
}

function renderPodcastUtterance(utterance, runId, { start = null, onSeek = null } = {}) {
  const div = document.createElement("div");
  div.className = "podcast-utterance";

  const speaker = document.createElement("div");
  speaker.className = "podcast-speaker";
  speaker.textContent = utterance.speaker === "host_a" ? "Host A" : "Host B";

  // A timecode only when the provider actually reported one. Without it the line stays a plain
  // transcript entry rather than showing a made-up 0:00 or becoming a seek target that lies.
  if (start !== null) {
    const stamp = document.createElement("button");
    stamp.type = "button";
    stamp.className = "podcast-timecode";
    stamp.textContent = formatTimecode(start);
    stamp.addEventListener("click", () => onSeek && onSeek(start));
    speaker.appendChild(stamp);
    div.classList.add("is-seekable");
    div.addEventListener("click", (event) => {
      // The line itself seeks, but never when the click was meant for something inside it — a
      // citation span opens its reference, the timecode has its own handler, and
      // `.reference-link` is the "N references" button `renderAnswerWithCitations` appends as a
      // SIBLING inside this same utterance. That one was MISSING while two dead classes from the
      // replaced citation-list markup were still listed — found by an independent review, and it
      // meant clicking "2 references" both jumped the player and switched the panel away.
      if (event.target.closest(".citation, .reference-link, .podcast-timecode")) {
        return;
      }
      // `click` also fires on the mouseup that ends a drag-selection, so selecting transcript prose
      // to quote it would otherwise seek and autoplay.
      const selection = window.getSelection();
      if (selection && !selection.isCollapsed && selection.toString().trim()) return;
      if (onSeek) onSeek(start);
    });
  }

  div.appendChild(speaker);
  div.appendChild(renderAnswerWithCitations(utterance.text, utterance.citations || [], runId));
  return div;
}

// Renders an episode: player, download, transcript. ONE function for both the just-generated case
// and the reopened-notebook case, so a persisted episode can never render differently from a fresh
// one — the shape the podcast was missing before it was persisted at all.
//
// `audioSrc` is a URL on this server (`GET .../audio/file`), not an object URL: the browser can
// range-request it, so seeking in a long episode doesn't re-download it, and reopening a notebook
// costs no re-synthesis. The `cacheBust` token is what makes REGENERATING visible — the path is
// stable per notebook, so without it the browser would keep serving the previous episode.
function renderPodcast(body, { utterances, runId, audioSrc, stale, suffix, offsets }) {
  body.innerHTML = "";

  if (stale) {
    const note = document.createElement("div");
    note.className = "chat-overview-head";
    note.textContent = t("podcast.stale", "Podcast · sources have changed since this");
    body.appendChild(note);
  }

  const player = document.createElement("audio");
  player.controls = true;
  player.preload = "none"; // don't pull a multi-MB episode on every notebook open
  player.src = audioSrc;
  body.appendChild(player);

  const download = document.createElement("a");
  download.className = "btn podcast-download";
  download.href = audioSrc;
  // A model-authored title reaches a filename here, so it is slugged rather than interpolated:
  // `download` is an attribute the browser turns into a path component.
  const stem = (state.title || state.notebookId || "notebook")
    .replace(/[^\w\u4e00-\u9fff-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  // The extension follows the SERVED file, not a hardcoded guess: chatterbox writes WAV and edge-tts
  // writes MP3, so naming the download `.mp3` unconditionally would mislabel half of them. An audit
  // found this listed among invariant 43's "handled" consequences when it was not.
  const ext = (suffix || "").replace(/^\./, "");
  download.download = ext ? `${stem || "notebook"}.${ext}` : stem || "notebook";
  download.textContent = ext
    ? t("podcast.download", `\u2913 Download ${ext}`, { ext })
    : t("podcast.downloadPlain", "\u2913 Download audio");
  body.appendChild(download);

  if (runId && tickerLogs.has(runId)) body.appendChild(renderTickerAffordance(runId));

  const transcript = document.createElement("div");
  transcript.className = "podcast-transcript";

  // Timing is usable only when there is exactly one offset per utterance AND the offsets actually
  // advance. The length check alone is not enough: a provider that reports no boundaries at all
  // yields `[0.0, 0.0, ...]`, which is the RIGHT LENGTH and would stamp every line `0:00`, highlight
  // the second row for the whole episode and seek every click to zero (an independent review
  // simulated exactly that). A persisted episode from before offsets existed has none and falls
  // back here too — mis-aligned subtitles are worse than none, and `schema.Podcast.offsets` says so.
  const timed =
    Array.isArray(offsets) &&
    offsets.length === utterances.length &&
    offsets.every((v, i) => Number.isFinite(v) && v >= 0 && (i === 0 || v > offsets[i - 1]));
  const seek = (seconds) => {
    player.currentTime = t;
    // The play promise rejects when the media cannot start (the persisted file was cleared and
    // `audio/file` 404s, or autoplay policy blocks it). Seeking still worked; swallow it rather
    // than leaving an unhandled rejection in the console.
    const played = player.play();
    if (played && typeof played.catch === "function") played.catch(() => {});
  };
  const rows = utterances.map((u, i) => {
    const row = renderPodcastUtterance(u, runId, {
      start: timed ? offsets[i] : null,
      onSeek: timed ? seek : null,
    });
    transcript.appendChild(row);
    return row;
  });
  body.appendChild(transcript);

  if (!timed) return;
  // Only a timed transcript becomes its own scroll box; an untimed one has nothing following it and
  // reads better inline.
  transcript.classList.add("is-timed");

  // Subtitle behaviour: the line whose window contains the playhead is current. `timeupdate` fires
  // ~4x a second, so this runs often — it does an O(n) scan over a transcript of a few dozen lines
  // and touches the DOM only when the index actually changes.
  let current = -1;
  player.addEventListener("timeupdate", () => {
    const t = player.currentTime;
    let index = -1;
    for (let i = 0; i < offsets.length; i += 1) {
      if (offsets[i] <= t) index = i;
      else break;
    }
    if (index === current) return;
    if (rows[current]) rows[current].classList.remove("is-speaking");
    current = index;
    const row = rows[current];
    if (!row) return;
    row.classList.add("is-speaking");
    // Scroll the transcript's OWN box (it has `overflow-y: auto`), never `scrollIntoView` — that
    // walks EVERY scrollable ancestor, so a listener who had scrolled the studio column away to
    // read something else got dragged back to the podcast panel every few seconds. Measured with
    // rects rather than `offsetTop`, which is relative to whatever the offsetParent happens to be
    // and would silently mis-scroll if this box ever stops being positioned. Only move when the
    // line is actually outside the box.
    const rowBox = row.getBoundingClientRect();
    const viewBox = transcript.getBoundingClientRect();
    if (rowBox.top < viewBox.top) {
      transcript.scrollTop -= viewBox.top - rowBox.top;
    } else if (rowBox.bottom > viewBox.bottom) {
      transcript.scrollTop += rowBox.bottom - viewBox.bottom;
    }
  });
}

function initPodcastPlayer() {
  const generateBtn = document.getElementById("podcast-generate");
  const body = document.getElementById("podcast-body");

  // No object-URL bookkeeping any more: the audio is a real URL on this server, so there is nothing
  // to revoke and no revocation ORDER to get right (blueprint P2.6's fix is moot rather than wrong).
  function clearPlayer() {
    body.innerHTML = "";
  }

  // A persisted episode renders on open, which is the whole point of persisting it.
  store.on("notebook:switched", () => {
    clearPlayer();
    const podcast = state.podcast;
    if (!podcast || !state.notebookId) return;
    renderPodcast(body, {
      utterances: podcast.utterances,
      runId: podcast.run_id,
      audioSrc: `/notebooks/${encodeURIComponent(state.notebookId)}/audio/file`,
      suffix: podcast.audio_suffix,
      offsets: podcast.offsets,
      stale: podcast.stale,
    });
  });

  generateBtn.addEventListener("click", async () => {
    if (!state.notebookId) {
      alert(t("err.openNotebookFirst", "Open or name a notebook first."));
      return;
    }
    generateBtn.disabled = true;
    ensureTitle();
    const generation = notebookGeneration;
    const token = crypto.randomUUID();
    const runId = `${state.notebookSlug || state.notebookId}-${token}`;
    body.classList.add("is-pending");
    body.innerHTML = "";
    let cancelled = false;
    const status = runStatus({
      notebookId: state.notebookId,
      runIds: [runId],
      label: t("podcast.writing", "Writing the script\u2026"),
      onCancel: () => {
        cancelled = true;
        body.classList.remove("is-pending");
        clearPlayer();
        generateBtn.disabled = false;
      },
    });
    body.appendChild(status.node);
    openTicker(state.notebookId, runId, (evt) => status.onEvent(evt));
    try {
      const data = await api(`/notebooks/${encodeURIComponent(state.notebookId)}/audio`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: token }),
      });
      status.finish();
      if (cancelled) return;
      if (generation !== notebookGeneration) return;  // switched away — the old episode is not theirs
      body.classList.remove("is-pending");
      body.innerHTML = "";

      if (!data.utterances.length) {
        body.textContent = t("podcast.empty", "(no podcast script — the sources didn't produce enough to discuss)");
        return;
      }

      state.podcast = {
        utterances: data.utterances,
        run_id: runId,
        offsets: data.offsets,
        stale: false,
      };
      renderPodcast(body, {
        utterances: data.utterances,
        runId,
        // Cache-busted: the path is stable per notebook, so without this the browser would keep
        // serving the episode it already has and "Regenerate" would look like it did nothing.
        audioSrc: `/notebooks/${encodeURIComponent(state.notebookId)}/audio/file?v=${token}`,
        stale: false,
        suffix: data.audio_suffix,
        offsets: data.offsets,
      });
    } catch (err) {
      status.finish();
      if (cancelled) return;
      body.classList.remove("is-pending");
      body.innerHTML = "";
      body.textContent = t("err.generic", `(error) ${err.message}`, { message: err.message });
    } finally {
      generateBtn.disabled = false;
    }
  });

  // NO second `notebook:switched` subscriber here. There used to be one (`clearPlayer`), registered
  // AFTER the render handler above — and `store.emit` runs subscribers in registration order, so it
  // blanked the panel the render handler had just filled. A persisted episode therefore never
  // appeared on notebook open, which is the entire point of persisting it. The render handler
  // clears first itself.
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
  promoteBtn.textContent = t("notes.promote", "→ Promote to source");
  // `data-tip`, not the native `title`: this project's own tooltip is instant and styled, and the
  // native one's ~1s delay is what made hover help feel disconnected from the hover effect.
  promoteBtn.dataset.tip = t(
    "notes.promoteHelp",
    "Turn this note into a real source. Only then can a later question cite it — a note on its own "
    + "is just text, with no citations of its own.",
  );
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
      alert(t("err.promoteNote", `Could not promote note: ${err.message}`, { message: err.message }));
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
      alert(t("err.deleteNote", `Could not delete note: ${err.message}`, { message: err.message }));
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
    alert(t("err.saveNote", `Could not save note: ${err.message}`, { message: err.message }));
  }
}

function initNotesPanel() {
  const form = document.getElementById("add-note-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.notebookId) {
      alert(t("err.openNotebookFirst", "Open or name a notebook first."));
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

// --- Studio rail: four views behind one switcher, collapsible ------------------------------------
//
// It used to be three sections stacked in one scrolling column, each with its own heading and body.
// A notebook with a generated guide, an episode and a few notes became a column nobody could find
// anything in — and there was nowhere to put a fourth thing. Views also give References a home.

const STUDIO_VIEW_KEY = "rlmnb-studio-view";
const STUDIO_COLLAPSED_KEY = "rlmnb-studio-collapsed";
const STUDIO_WIDTH_KEY = "rlmnb-studio-width";

//: The panel's size limits. Below `STUDIO_COLLAPSE_AT` a drag means "put it away" rather than "make
//: it very narrow" — a 90px panel is useless, so snapping to the icon rail is what the gesture
//: actually meant.
const STUDIO_MIN_WIDTH = 240;
const STUDIO_MAX_WIDTH = 720;
const STUDIO_COLLAPSE_AT = 170;
//: HYSTERESIS, and the ORDER is the whole point: a two-state toggle driven by one continuous value
//: is stable only while the "open" threshold is at or above the "close" one. An earlier attempt put
//: it BELOW (expand at 90, collapse at 170) to make re-opening from the rail cheap, which turned
//: 90–170 into a band where every single pointermove flipped the state — the panel visibly
//: shuddering between two widths. Expanding at exactly the minimum width is the value that both
//: satisfies the ordering AND opens the panel with no jump at all: at the crossing the pointer and
//: the panel are the same number. The dead band [170, 240) is then precisely the range the panel
//: could not have honoured anyway, and `--studio-rail` below keeps it from feeling dead.
const STUDIO_EXPAND_AT = STUDIO_MIN_WIDTH;
//: 2.9rem, the collapsed track in `style.css`. Repeated here because JS has to clamp against it.
const STUDIO_RAIL_WIDTH = 46;

function initStudioRail() {
  const col = document.getElementById("col-studio");
  const tabs = [...document.querySelectorAll(".studio-view-tab")];
  const bodies = [...document.querySelectorAll("[data-view-body]")];

  function show(view) {
    tabs.forEach((tab) => tab.classList.toggle("is-active", tab.dataset.view === view));
    bodies.forEach((body) => {
      body.hidden = body.dataset.viewBody !== view;
    });
    localStorage.setItem(STUDIO_VIEW_KEY, view);
    // Expanding on selection: picking a view while collapsed can only mean "show me that".
    setCollapsed(false);
    if (view === "references") renderReferenceView();
  }

  // No separate collapse BUTTON any more: the grip resizes and collapses, and a second control for
  // the same thing was eating the width the four labels needed — they were truncating to one
  // character each.
  function setCollapsed(value) {
    // Only on an actual CHANGE: `pointermove` calls this on every event, and an unconditional
    // synchronous `localStorage` write there is 60-120 writes a second during a drag.
    if (col.classList.contains("is-collapsed") === value) return;
    col.classList.toggle("is-collapsed", value);
    localStorage.setItem(STUDIO_COLLAPSED_KEY, value ? "1" : "");
  }

  // APPLYING a width and REMEMBERING one are deliberately separate. Persisting on every pointermove
  // is what made dragging the panel away overwrite the user's own width with the 240px clamp; the
  // previous fix for that (skip `setWidth` below the minimum) then left the CSS variable holding a
  // stale width, so re-opening snapped to the OLD size before catching up to the pointer — the
  // "彈回前一次設置的寬度再快速閃現" half of the report. A drag now always follows the pointer and
  // only commits when it ends.
  let appliedWidth = STUDIO_MIN_WIDTH;

  function applyWidth(px) {
    appliedWidth = Math.min(STUDIO_MAX_WIDTH, Math.max(STUDIO_MIN_WIDTH, px));
    document.documentElement.style.setProperty("--studio-width", `${appliedWidth}px`);
    return appliedWidth;
  }

  function rememberWidth() {
    localStorage.setItem(STUDIO_WIDTH_KEY, String(appliedWidth));
  }

  // Drag the edge to size the panel; drag it past the threshold to put it away. `setPointerCapture`
  // is what keeps the drag alive when the cursor outruns the 6px handle, which it always does.
  const handle = document.getElementById("studio-resize");
  let dragging = false;
  handle.addEventListener("pointerdown", (event) => {
    dragging = true;
    handle.setPointerCapture(event.pointerId);
    document.body.classList.add("is-resizing");  // suppress the width transition and text selection
    event.preventDefault();
  });
  handle.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    // The panel is on the RIGHT, so its width grows as the pointer moves left.
    const width = window.innerWidth - event.clientX;
    const collapsed = col.classList.contains("is-collapsed");
    if (width < (collapsed ? STUDIO_EXPAND_AT : STUDIO_COLLAPSE_AT)) {
      setCollapsed(true);
      // The panel cannot open below its minimum, but the HANDLE can still follow you: the rail
      // stretches under the pointer through the dead band, so pulling always does something
      // visible. Without it the ordering above costs ~194px of motionless drag before the panel
      // opens, which is the "卡住" this replaced.
      const rail = Math.min(STUDIO_MIN_WIDTH, Math.max(STUDIO_RAIL_WIDTH, width));
      document.documentElement.style.setProperty("--studio-rail", `${rail}px`);
      return;
    }
    setCollapsed(false);
    document.documentElement.style.removeProperty("--studio-rail");
    applyWidth(width);
  });
  const endDrag = (event) => {
    if (!dragging) return;
    dragging = false;
    try {
      handle.releasePointerCapture(event.pointerId);
    } catch {
      // the pointer was already gone; nothing to release
    }
    document.body.classList.remove("is-resizing");
    // The stretch is a drag affordance, never a persisted size.
    document.documentElement.style.removeProperty("--studio-rail");
    // Only a drag that ended OPEN was the user choosing a width. One that ended collapsed passed
    // through the clamp on its way out, and committing that would lose the size they had picked.
    if (!col.classList.contains("is-collapsed")) rememberWidth();
  };
  handle.addEventListener("pointerup", endDrag);
  handle.addEventListener("pointercancel", endDrag);
  // Double-click the grip toggles, the shortcut every resizable panel has.
  handle.addEventListener("dblclick", () => setCollapsed(!col.classList.contains("is-collapsed")));
  // Keyboard: the handle is focusable, so it has to be operable without a pointer.
  handle.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      // Ignored while collapsed: the collapsed track reads `--studio-rail`, not `--studio-width`,
      // so this used to walk the REMEMBERED width down to the 240 clamp with nothing moving on
      // screen — and re-opening then landed at 240 instead of the size the user had chosen.
      // `endDrag` already has the equivalent guard.
      if (col.classList.contains("is-collapsed")) return;
      // No drag to end, so a key press commits immediately.
      applyWidth(appliedWidth + (event.key === "ArrowLeft" ? 24 : -24));
      rememberWidth();
    } else if (event.key === "Enter" || event.key === " ") {
      setCollapsed(!col.classList.contains("is-collapsed"));
    } else return;
    event.preventDefault();
  });

  tabs.forEach((tab) => tab.addEventListener("click", () => show(tab.dataset.view)));

  applyWidth(parseInt(localStorage.getItem(STUDIO_WIDTH_KEY) || "340", 10));
  const stored = localStorage.getItem(STUDIO_VIEW_KEY);
  show(tabs.some((tab) => tab.dataset.view === stored) ? stored : "studio");
  // AFTER `show`, which expands on purpose — restoring a collapsed panel must win over that.
  setCollapsed(localStorage.getItem(STUDIO_COLLAPSED_KEY) === "1");

  // A reference is only interesting while it exists; both of these change what there is to show.
  store.on("chat:turnAdded", () => renderReferenceView());
  store.on("sources:changed", () => renderReferenceView());
  window.addEventListener("ui-lang-changed", () => renderReferenceView());
}

function showStudioView(view) {
  const tab = document.querySelector(`.studio-view-tab[data-view="${view}"]`);
  if (tab) tab.click();
}

// Every passage cited ANYWHERE in this notebook, deduplicated and numbered — the thing a reader
// wants when they are checking work rather than reading it. Collected from the turns and the
// overview, which is everything the client holds that carries citations.
function collectReferences() {
  const byCoordinate = new Map();
  const add = (citation) => {
    const key = `${citation.source_id}\u0000${citation.locator}`;
    const existing = byCoordinate.get(key);
    if (!existing) {
      byCoordinate.set(key, { ...citation, quotes: citation.quote ? [citation.quote] : [], uses: 1 });
      return;
    }
    existing.uses += 1;
    if (citation.quote && !existing.quotes.includes(citation.quote)) existing.quotes.push(citation.quote);
    existing.verified = existing.verified && citation.verified;
  };
  (state.overview?.citations || []).forEach(add);
  (state.turns || []).forEach((turn) => (turn.citations || []).forEach(add));
  // Every OTHER surface that renders a clickable citation has to be here too, or clicking one
  // opens a list that cannot contain it — see `state.guides`.
  (state.podcast?.utterances || []).forEach((u) => (u.citations || []).forEach(add));
  Object.values(state.guides || {}).forEach(({ result }) => {
    if (!result) return;
    (result.citations || []).forEach(add);                                   // summary / insight
    (result.items || []).forEach((item) => (item.citations || []).forEach(add));       // faq
    (result.events || []).forEach((event) => (event.citations || []).forEach(add));    // timeline
  });
  return [...byCoordinate.values()];
}

// The References view is built from a snapshot of `state`, so anything that ADDS a citation has to
// ask for a rebuild. Cheap and idempotent; a no-op when the reader is looking at another view.
function refreshReferenceView() {
  const host = document.getElementById("reference-view");
  if (host && !host.closest("[data-view-body]")?.hidden) renderReferenceView();
}

function referenceKey(citation) {
  return `${citation.source_id}\u0000${citation.locator}`;
}

function renderReferenceView() {
  const host = document.getElementById("reference-view");
  const empty = document.getElementById("references-empty");
  if (!host) return;
  const references = collectReferences();
  host.innerHTML = "";
  empty.hidden = references.length > 0;

  references.forEach((reference, index) => {
    const item = document.createElement("div");
    item.className = reference.verified ? "ref-card" : "ref-card is-unverified";
    item.dataset.refKey = referenceKey(reference);

    const head = document.createElement("button");
    head.type = "button";
    head.className = "ref-card-head";

    const number = document.createElement("span");
    number.className = "reference-number";
    number.textContent = String(index + 1);
    head.appendChild(number);

    const name = document.createElement("span");
    name.className = "ref-card-name";
    const source = (state.sources || []).find((s) => s.id === reference.source_id);
    name.textContent = source ? sourceLabel(source) : reference.source_id;
    head.appendChild(name);

    if (reference.locator && reference.locator !== "whole") {
      const locator = document.createElement("span");
      locator.className = "reference-locator";
      locator.textContent = reference.locator;
      head.appendChild(locator);
    }

    const uses = document.createElement("span");
    uses.className = "ref-card-uses";
    uses.textContent = t("references.uses", `${reference.uses}\u00d7`, { n: reference.uses });
    head.appendChild(uses);

    const passage = document.createElement("div");
    passage.className = "ref-card-passage";
    passage.hidden = true;

    // The card opens INTO the original passage: click the reference, the source text slides out
    // beneath it, with the quoted span highlighted. That is the whole loop the user asked for, and
    // it stays inside this view rather than throwing a modal over the page.
    head.addEventListener("click", async () => {
      if (!passage.hidden) {
        passage.hidden = true;
        item.classList.remove("is-open");
        return;
      }
      item.classList.add("is-open");
      passage.hidden = false;
      if (passage.dataset.loaded) return;
      passage.textContent = t("cite.loading", "Loading…");
      try {
        const data = await api(
          `/notebooks/${encodeURIComponent(state.notebookId)}/sources/${encodeURIComponent(reference.source_id)}`
        );
        passage.textContent = "";
        passage.appendChild(renderSourceMeta(data));
        (data.blocks || [])
          .filter((block) => block.locator === reference.locator)
          .forEach((block) => {
            passage.appendChild(
              renderTextWithOptionalHighlight(block.text, reference.quotes[0] || null)
            );
          });
        passage.dataset.loaded = "1";
      } catch (err) {
        passage.textContent = t("err.generic", `(error) ${err.message}`, { message: err.message });
      }
    });

    item.appendChild(head);
    reference.quotes.forEach((quote) => {
      const blockquote = document.createElement("blockquote");
      blockquote.className = "reference-quote";
      blockquote.textContent = quote;
      item.appendChild(blockquote);
    });
    item.appendChild(passage);
    host.appendChild(item);
  });
}

// Clicking a citation in the chat opens the References view and takes the reader to that entry,
// rather than expanding a panel inside the answer they are reading.
function focusReference(citation) {
  showStudioView("references");
  const key = referenceKey(citation);
  const card = document.querySelector(`.ref-card[data-ref-key="${CSS.escape(key)}"]`);
  if (!card) return;
  document.querySelectorAll(".ref-card.is-focused, .citation.is-focused")
    .forEach((el) => el.classList.remove("is-focused"));
  card.classList.add("is-focused");
  // ...and every stroke pointing at the SAME coordinate lights up with it. `.citation.is-focused`
  // has always existed in the stylesheet promising exactly this; nothing ever set it.
  document.querySelectorAll(`.citation[data-ref-key="${CSS.escape(key)}"]`)
    .forEach((el) => el.classList.add("is-focused"));
  card.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// --- Boot -------------------------------------------------------------------------------------

// Static markup FIRST, before any panel renders: every `init*` below writes copy of its own, and a
// panel that rendered against the English strings would keep them until something re-rendered it.
document.documentElement.lang = uiLang();
applyStaticI18n();

// A language change re-applies the static markup (in `setUiLang`) and re-renders every panel that
// holds generated copy. Cheaper and far less error-prone than threading a language argument through
// each renderer — and it means a renderer added later is translated by construction rather than by
// somebody remembering to subscribe.
window.addEventListener("ui-lang-changed", () => {
  renderChatOverview();
  store.emit("sources:changed", { sources: state.sources });
  store.emit("notes:changed", { notes: state.notes });
  const settingsOverlay = document.getElementById("settings-overlay");
  if (settingsOverlay && !settingsOverlay.hidden) {
    document.getElementById("settings-open").click();
  }
});

initTheme();
initSettings();
initNotebookTitle();
initNotebookSwitch();
initSourcesPanel();
initChatPanel();
initStudioPanel();
initPodcastPlayer();
initSourceViewer();
initNotesPanel();
initStudioRail();
