/* Headless smoke test for the playground shim.
 *
 * The playground has no server and this repo has no JS test runner (invariant 36's known gap), so
 * the one thing that CAN go silently wrong — a route `app.js` calls that the shim does not answer —
 * gets checked here instead of by opening a browser and clicking. Run:
 *
 *     node playground/smoke.mjs [dist-dir]
 *
 * It stubs the four browser globals the shim touches, loads `tour.js` + `shim.js` exactly as the
 * page does, and drives every endpoint `app.js` actually calls. The endpoint list is EXTRACTED from
 * `app.js`, not hand-written, so a new call site in the product fails this rather than 404ing in
 * front of a reader.
 */
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

// Minimal stand-ins for the handful of web globals the shim uses. Written out rather than
// requiring a modern Node: this repo ships no JavaScript toolchain (invariant 29's zero-build
// choice), so the smoke test must run on whatever `node` happens to be installed.
class R {
  constructor(body, init = {}) {
    this._body = body;
    this.status = init.status ?? 200;
    this.headers = new Map(Object.entries(init.headers || {}));
  }
  async json() { return JSON.parse(this._body); }
  async text() { return String(this._body); }
}
class Q {
  constructor(input, init = {}) {
    this.url = typeof input === "string" ? input : input.url;
    this.method = (init.method || (input && input.method) || "GET").toUpperCase();
    this._body = init.body ?? (input && input._body);
  }
  async json() { return JSON.parse(this._body || "{}"); }
}
class ME {
  constructor(type, init = {}) { this.type = type; this.data = init.data; }
}
const clone = (v) => JSON.parse(JSON.stringify(v));

const HERE = dirname(fileURLToPath(import.meta.url));
const DIST = resolve(process.argv[2] || join(HERE, "dist"));
const APP = readFileSync(join(DIST, "app.js"), "utf8");
const fixtures = JSON.parse(readFileSync(join(DIST, "fixtures.json"), "utf8"));

let failures = 0;
const ok = (cond, msg) => {
  if (!cond) failures++;
  console.log(`  ${cond ? "ok  " : "FAIL"}  ${msg}`);
};

// --- the browser surface the shim needs -----------------------------------------------------------
const listeners = new Map();
const sandbox = {
  console,
  URL,
  Request: Q,
  Response: R,
  MessageEvent: ME,
  EventTarget,
  structuredClone: clone,
  setTimeout,
  clearTimeout,
  JSON,
  Math,
  Object,
  Number,
  Map,
  Set,
  Promise,
  String,
  Array,
  Error,
  location: { href: `file://${DIST}/index.html`, hash: "" },
  document: { currentScript: { src: `file://${DIST}/shim.js` } },
  HTMLMediaElement: function () {},
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  addEventListener: (k, f) => listeners.set(k, f),
};
sandbox.window = sandbox;
sandbox.HTMLMediaElement.prototype = {};
Object.defineProperty(sandbox.HTMLMediaElement.prototype, "src", {
  configurable: true,
  get() { return this._src; },
  set(v) { this._src = v; },
});
// The real page fetches `fixtures.json` over HTTP; here the shim's own `realFetch` must resolve it
// off disk, so `fetch` is stubbed BEFORE the shim captures it.
sandbox.fetch = async (input) => {
  const url = String(input && input.url ? input.url : input);
  const path = url.replace(/^file:\/\//, "").split("?")[0];
  return new R(readFileSync(path, "utf8"), { headers: { "Content-Type": "application/json" } });
};

const ctx = vm.createContext(sandbox);
for (const f of ["tour.js", "shim.js"]) {
  vm.runInContext(readFileSync(join(DIST, f), "utf8"), ctx, { filename: f });
}

// --- every endpoint app.js actually calls ---------------------------------------------------------
function endpointsFromApp() {
  const found = new Set();
  // `api("…")` and `api(`…`)`, plus the method from an adjacent `method:` in the same call.
  const re = /api\(\s*(?:`([^`]*)`|"([^"]*)")\s*(?:,\s*\{([^}]*)\})?/g;
  for (const m of APP.matchAll(re)) {
    const raw = (m[1] || m[2] || "").replace(/\$\{[^}]*\}/g, "X");
    const method = (m[3] || "").match(/method:\s*"(\w+)"/);
    found.add(`${method ? method[1] : "GET"} ${raw}`);
  }
  return [...found].sort();
}

const nb = fixtures.scenarios[0].id;
const REQUESTS = [
  ["GET", "/notebooks"],
  ["GET", `/notebooks/${nb}`],
  ["GET", "/settings"],
  ["GET", "/settings/choices"],
  ["GET", `/notebooks/${nb}/sources/s1`],
  ["POST", `/notebooks/${nb}/sources`, { sources: ["https://example.com/x"] }],
  ["DELETE", `/notebooks/${nb}/turns`],
  ["PUT", `/notebooks/${nb}/title`, { title: "renamed" }],
  ["POST", `/notebooks/${nb}/ask`, { question: "test?", run_id: `${nb}-smoke` }],
  ["POST", `/notebooks/${nb}/overview`, { run_id: `${nb}-smoke2` }],
  ["POST", `/notebooks/${nb}/guide/summary`, { run_id: `${nb}-smoke3` }],
  ["POST", `/notebooks/${nb}/audio`, { run_id: `${nb}-smoke4`, length: "long" }],
  ["POST", `/notebooks/${nb}/runs/${nb}-smoke/cancel`, {}],
];

console.log("routes:");
for (const [method, path, body] of REQUESTS) {
  const init = { method };
  if (body) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  const resp = await ctx.fetch(new Q(`http://x${path}`, init));
  ok(resp.status === 200, `${method} ${path} -> ${resp.status}`);
}

console.log("\ncoverage of app.js's own call sites:");
const unrouted = [];
// One placeholder cannot stand in for a notebook id, a note id and a guide kind at once, so each
// signature is probed with several plausible fillings and passes if ANY is routed. The check is
// "does a route of this SHAPE exist", not "does this exact string resolve".
const FILLERS = ["s1", "n1", "summary", "1", nb];
for (const sig of endpointsFromApp()) {
  const [method, raw] = sig.split(" ");
  if (!raw.startsWith("/")) continue;
  let routed = false;
  for (const fill of FILLERS) {
    const resp = await ctx.fetch(new Q(`http://x${raw.replace(/X/g, fill)}`, { method }));
    const body = resp.status === 404 ? await resp.json() : null;
    if (!body || !String(body.detail).includes("no playground route")) { routed = true; break; }
  }
  if (!routed) unrouted.push(sig);
}
ok(unrouted.length === 0, `every api() path is routed${unrouted.length ? ` — missing: ${unrouted.join(", ")}` : ""}`);

// Notes are exercised as a SEQUENCE with ids read back from the responses, never hardcoded: a
// scenario may start with zero notes or with one, and an id baked into the test only proves the
// test agrees with itself.
console.log("\nnotes lifecycle:");
{
  const post = async (path, body) =>
    (await ctx.fetch(new Q(`http://x${path}`, {
      method: "POST", body: JSON.stringify(body || {}),
    }))).json();
  let state = await post(`/notebooks/${nb}/notes`, { text: "a playground note" });
  const added = state.notes[state.notes.length - 1];
  ok(/^n\d+$/.test(String(added.id)), `added note has an n-prefixed id (${added.id})`);
  const before = state.notes.length;
  const del = await ctx.fetch(new Q(`http://x/notebooks/${nb}/notes/${added.id}`, { method: "DELETE" }));
  ok(del.status === 200, `DELETE the note it just created -> ${del.status}`);
  state = await del.json();
  ok(state.notes.length === before - 1, `note removed (${before} -> ${state.notes.length})`);
  state = await post(`/notebooks/${nb}/notes`, { text: "promote me" });
  const target = state.notes[state.notes.length - 1];
  const srcBefore = state.sources.length;
  state = await post(`/notebooks/${nb}/notes/${target.id}/promote`, {});
  ok(state.sources.length === srcBefore + 1, "promote turns the note into a source (invariant 32)");
  ok(!state.notes.some((n) => n.id === target.id), "promote removes the note");
}

console.log("\nresponse shapes (a near-miss renders undefined, it does not 404):");
const listed = await (await ctx.fetch(new Q("http://x/notebooks"))).json();
const SUMMARY = ["id", "title", "derived_title", "source_count", "turn_count", "updated_at"];
ok(Array.isArray(listed.notebooks) && listed.notebooks.length > 0, `${listed.notebooks?.length} notebooks listed`);
ok(SUMMARY.every((k) => k in listed.notebooks[0]), `summary carries ${SUMMARY.join(", ")}`);

console.log("\ndata fidelity:");
const one = await (await ctx.fetch(new Q(`http://x/notebooks/${nb}`))).json();
ok(one.turns.length > 0, `notebook has ${one.turns.length} real turns`);
ok(one.overview && one.overview.text.length > 200, "overview carries real prose");
ok(one.podcast && one.podcast.utterances.length > 10, `podcast has ${one.podcast?.utterances.length} utterances`);
const cited = one.turns.flatMap((t) => t.citations);
ok(cited.length > 0 && cited.every((c) => c.verified), `${cited.length} citations, all verified by the real verifier`);
ok(Object.keys(fixtures.runs).length > 0, `${Object.keys(fixtures.runs).length} recorded runs available to replay`);
const withTicker = Object.values(fixtures.runs).filter((r) => r.ticker.some((e) => e && e.detail));
ok(withTicker.length > 0, `${withTicker.length} runs carry real reasoning text`);

// The product page leads with three demos — a grounded answer, the Trajectory drawer, and the
// podcast — so "does the page actually contain them" is a requirement, not a nicety. A scenario
// that quietly lost its overview or its trace would still render; it would just demo nothing.
console.log("\nheadline demos are present in every scenario:");
{
  // Tier boundaries are invariant 63's: short 12-18 turns, default 30-45, long 60-90.
  const tier = (n) => (n <= 20 ? "short" : n <= 50 ? "default" : "long");
  const seen = new Map();
  for (const s of fixtures.scenarios) {
    const nbf = fixtures.notebooks[s.id];
    const turns = nbf.turns.length;
    const pod = nbf.podcast;
    const runs = Object.keys(fixtures.runs).filter((r) => r.startsWith(`${s.id}-`)).length;
    const label = `${s.lang.slice(0, 2)}/${s.id.replace(/^nb-(en-)?/, "")}`;
    ok(turns >= 1, `${label}: ${turns} Q&A turn(s)`);
    ok(!!nbf.overview, `${label}: has an overview`);
    ok(!!pod && pod.utterances.length > 0, `${label}: ${pod?.utterances.length || 0}-turn podcast`);
    ok(
      !!pod && (pod.offsets || []).length === (pod.utterances || []).length,
      `${label}: offsets match utterances (timed transcript + click-to-seek)`
    );
    ok(runs > 0, `${label}: ${runs} recorded run(s) for the Trajectory drawer`);
    if (pod) {
      const key = `${s.lang} ${tier(pod.utterances.length)}`;
      seen.set(key, (seen.get(key) || 0) + 1);
    }
  }
  for (const lang of ["English", "Traditional Chinese"]) {
    for (const want of ["short", "default", "long"]) {
      ok(seen.has(`${lang} ${want}`), `tier covered: ${lang} ${want}`);
    }
  }
}

// The director spotlights the product's OWN controls by selector. That is the one thing this whole
// approach risks: `app.js` is copied verbatim and can rename a class at any time, and a selector
// that stops matching produces NO error — the spotlight just never appears and the demo stalls on a
// step the reader cannot complete. So every anchor is checked against the shipped source.
// The chrome is DOM code, and DOM code fails in ways no string check can see. This mounts it
// against a mini-DOM that reproduces the one browser contract it got wrong: `insertBefore` throws
// when the reference node is not a child of the node you called it on. `#settings-open` lives
// inside `<div class="header-actions">`, so inserting into `<header>` threw NotFoundError, mount()
// died, and `openInitial()` and the director never ran — the page rendered as the bare product.
// driver.js disables the whole page with `.driver-active * { pointer-events: none }` and re-enables
// only the spotlit element and its own popover. Anything of ours that must stay usable while the
// tour runs has to opt back in with a rule that BEATS that one on specificity — comparing by string
// would accept a rule that loses the cascade, so this computes it, the way the product's own
// stylesheet tripwires do.
// "Do it for me" has to leave the workspace in the state pressing the button would have produced.
// When it only advanced the script, skipping step 1 left the notebook with no sources, so
// `renderChatOverview` returned early, `#chat-overview` stayed hidden, and step 2 hunted for a
// button that had never been built. Every later step inherited that.
console.log("\nskipping a step fulfils it, and never strands a later one:");
{
  const s = { console: { log() {}, warn() {} }, JSON, Math, Object };
  s.window = s;
  vm.createContext(s);
  vm.runInContext(readFileSync(join(DIST, "tour.js"), "utf8"), s);
  const SCRIPT = s.rlmPlayground.SCRIPT;

  // A fresh shim instance so this walk cannot be satisfied by earlier tests' mutations.
  const sh = { console: { log() {}, warn() {} }, URL, Request: Q, Response: R, MessageEvent: ME,
    EventTarget, structuredClone: clone, setTimeout, clearTimeout, JSON, Math, Object, Number,
    Map, Set, Promise, String, Array, Error,
    location: { href: `file://${DIST}/index.html`, hash: "" },
    document: { currentScript: { src: `file://${DIST}/shim.js` } },
    HTMLMediaElement: function () {}, addEventListener() {},
    fetch: async (input) => {
      const path = String(input && input.url ? input.url : input).replace(/^file:\/\//, "").split("?")[0];
      return new R(readFileSync(path, "utf8"), { headers: { "Content-Type": "application/json" } });
    } };
  sh.window = sh;
  sh.HTMLMediaElement.prototype = {};
  Object.defineProperty(sh.HTMLMediaElement.prototype, "src", {
    configurable: true, get() { return this._src; }, set(v) { this._src = v; },
  });
  const shc = vm.createContext(sh);
  vm.runInContext(readFileSync(join(DIST, "tour.js"), "utf8"), shc, { filename: "tour.js" });
  vm.runInContext(readFileSync(join(DIST, "shim.js"), "utf8"), shc, { filename: "shim.js" });
  const SPG = sh.rlmPlayground;

  // The tour builds ONE notebook up from nothing, and only that one starts empty. Every other
  // notebook opens complete, because the product's own picker switches in place with no reload to
  // re-stage anything, so a reader who finished the tour and went browsing must not be handed a
  // blank workspace.
  const nbId = fixtures.scenarios[0].id;
  SPG.beginTour(nbId);
  let p0 = await SPG.progress(nbId);
  ok(p0.sources === 0 && !p0.overview && p0.turns === 0,
     "the tour's own notebook starts empty (nothing pre-loaded)");
  const other = await SPG.progress(fixtures.scenarios[1].id);
  ok(other.sources > 0 && other.overview && other.turns > 0,
     `another notebook opens complete (${other.sources} sources, ${other.turns} turns)`);

  const fulfilling = SCRIPT.filter((st) => st.fulfil);
  ok(fulfilling.length >= 4, `${fulfilling.length} steps declare what they fulfil`);
  const stranded = [];
  for (const step of fulfilling) {
    await SPG.fulfil(nbId, step.fulfil);
    const p = await SPG.progress(nbId);
    let satisfied = false;
    try { satisfied = !!step.done(p); } catch { satisfied = false; }
    if (!satisfied) stranded.push(`${step.id} (fulfil: ${step.fulfil})`);
  }
  ok(stranded.length === 0,
     `every fulfillable step reports done after being fulfilled${stranded.length ? ` — stranded: ${stranded.join(", ")}` : ""}`);

  const end = await SPG.progress(nbId);
  ok(end.sources === end.sourcesTotal, `sources fully revealed (${end.sources}/${end.sourcesTotal})`);
  ok(end.overview, "overview revealed");
  ok(end.turns >= 1, `${end.turns} turn(s) revealed`);
  ok(!!end.podcast, "podcast revealed");
}

// A dwell step holds the reader on a run while it happens. Two ways it can go wrong and both are
// silent: handing over too late (the run is already finished, so there is nothing to watch) and
// holding unconditionally (no run is coming, so it never releases).
// The interface language is detected from the browser; the DEMO has to follow it, or a Chinese
// reader gets Chinese buttons around English answers. And the rule has one exception that must not
// be lost: a hash the reader ARRIVED with is a shared link naming a specific notebook.
// A step that is already `done` when the reader arrives is a frame nobody sees, and it cascades:
// step 7 reported done because `#podcast-generate:not([hidden])` matched a button whose STUDIO VIEW
// was hidden rather than the button itself, so step 8 (`done: () => true`) fell through as well and
// step 9 spotlit a control inside a closed panel.
// The product records this twice — invariant 60 ("a repaint may not delete a RUN") and invariant 71
// — and the playground reintroduced it: "Do it for me" called `openNotebook`, a full repaint, while
// a run was still in flight, and the answer and the overview vanished off the screen.
// One global "is a run going" flag made every step's own check true at once: while the overview was
// generating, the ask step reported itself done and the script fell through it, so one press of
// Skip jumped two steps. Each step has to ask about ITS OWN kind.
// Skipping a step that WAITS on a run has to end the run, or the tour advances while the previous
// step's screen is still up: a status strip counting, and the result the next step needs missing.
// The outcome must still land, though — the reader skipped the wait, not the result.
// The product sets `scrollTop` by hand rather than calling `scrollIntoView`, because that walks
// EVERY scrollable ancestor and drags the whole page (invariant 44). The director brings its target
// into view the same way, and must not reach for the easy call.
// A trace is the one artifact here that can carry text nobody chose to publish: the planner's own
// reasoning, the code it wrote, and whatever it read. This page goes on the open web, so the audit
// runs every build rather than once. The line is at the MACHINE, not at the project: this
// repository is public, so the model quoting its own skill files is the drawer working.
console.log("\nnothing local or private reaches the published fixture:");
{
  const blob = readFileSync(join(DIST, "fixtures.json"), "utf8");
  const FORBIDDEN = {
    "absolute home paths": /\/Users\/[\w.-]+|\/home\/[\w.-]+|C:\\\\Users/,
    "credentials": /sk-[A-Za-z0-9]{8,}|Bearer\s+\S{12,}|RN_API_KEY|RN_BASE_URL/,
    "email addresses": /[\w.+-]+@[\w-]+\.[\w.]{2,}/,
    "loopback or hostnames": /127\.0\.0\.1|localhost:\d+|\.local\b/,
    "python tracebacks": /File "[^"]+", line \d+/,
  };
  for (const [what, re_] of Object.entries(FORBIDDEN)) {
    const hit = blob.match(re_);
    ok(!hit, `no ${what}${hit ? ` — found ${JSON.stringify(hit[0]).slice(0, 50)}` : ""}`);
  }

  // Model identifiers are replaced with neutral labels: which models this runs against is nobody's
  // business on a public page, and the names reach past the one field that holds them.
  const fx = JSON.parse(blob);
  const metas = Object.values(fx.runs)
    .map((r) => ((r.trajectory || {}).initial || {}).meta || {})
    .filter((m) => m.main_model);
  ok(metas.length > 0, `${metas.length} runs report a model`);
  ok(metas.every((m) => /^model-[a-z]$/.test(m.main_model)),
     "every main_model is an anonymous label");
  ok(metas.every((m) => !m.sub_model || /^model-[a-z]$/.test(m.sub_model)),
     "every sub_model is an anonymous label");

  // The other direction, and the one an over-eager scrub fails: the reasoning has to SURVIVE. A
  // pass that blanked every string mentioning this project's own skill files removed 100 of them
  // and left the drawer showing placeholders, which is the failure this assertion exists to catch.
  ok(!/omitted here/.test(blob), "no blanket redaction placeholder survives");
  const skillProse = (blob.match(/corpus-navigation|podcast-craft|read_skill/g) || []).length;
  ok(skillProse > 20, `${skillProse} mentions of the run's own skill reads are intact`);

  // Redaction must not have gutted what the drawer exists to show.
  const richest = Object.values(fx.runs)
    .map((r) => (r.trajectory || {}).iterations || [])
    .sort((a, b) => b.length - a.length)[0] || [];
  ok(richest.length >= 5, `the richest run still has ${richest.length} planner turns`);
}

// The popover is placed from the target's rect, so the scroll has to happen FIRST. The bug this
// pins had the two the wrong way round AND gated the scroll on `target === this.lastTarget`, which
// is the one case `highlight` refuses to act on: a new step was placed against the unscrolled rect,
// then scrolled out from under its own popover, which stayed behind pointing at nothing.
// `POST /audio` is the ONE endpoint whose reply is not a `NotebookResponse`: the real API answers
// with a flat `AudioResponse`, and the shim was nesting the episode under `{podcast}`. `app.js`
// reads `data.utterances.length` straight off it, so Generate died with "Cannot read properties of
// undefined" and the demo's headline artifact never rendered. Read what app.js expects, then check
// the shim's audio handler actually returns it.
// The director has a label table of its own, separate from the chrome's. A string in one that
// NAMES a control from the other has to reach for that control's current label, or a translated
// interface ends up pointing at a button by its English name.
// This is a teaching page: nothing a reader changed last visit may decide what they see this
// visit. `rlmnb-studio-view` surviving a reload is what made the "open the Podcast tab" step
// vanish, and the podcast length is the same shape one step later.
// A `pg-` class exists to be styled: the playground's chrome adds nodes the product's own
// stylesheet knows nothing about. So one created in JS with no rule in chrome.css is either a typo
// or a rule that has been deleted, and deletion is how it happened: replacing the picker's card
// grid took the two heading rules sitting inside the replaced range with it, and a bare <h3> then
// rendered the language name larger than the notebook titles under it. Nothing else here can see
// that, since the Python suite never renders and there is no JS test runner (invariant 36's
// reasoning, applied to the playground's own chrome).
console.log("\nevery class the chrome creates has a rule:");
{
  const JS = readFileSync(join(DIST, "chrome.js"), "utf8");
  const CSS = readFileSync(join(DIST, "chrome.css"), "utf8");
  const created = new Set();
  for (const m of JS.matchAll(/el\(\s*"[a-z0-9]+"\s*,\s*"([^"]+)"/g)) {
    for (const cls of m[1].split(/\s+/)) if (cls.startsWith("pg-")) created.add(cls);
  }
  ok(created.size >= 10, `${created.size} pg- classes created in chrome.js`);
  const unstyled = [...created].filter((c) => !new RegExp(`\\.${c}\\b`).test(CSS));
  ok(unstyled.length === 0, `every one has a rule${unstyled.length ? ` — missing: ${unstyled}` : ""}`);

}

console.log("\nthe demo starts from scratch on every load:");
{
  const SHIM = readFileSync(join(DIST, "shim.js"), "utf8");
  const APP = readFileSync(join(DIST, "app.js"), "utf8");
  const listed = [...SHIM.slice(SHIM.indexOf("const WORKSPACE_KEYS"),
                                SHIM.indexOf("];", SHIM.indexOf("const WORKSPACE_KEYS")))
                    .matchAll(/"(rlmnb-[a-z-]+)"/g)].map((m) => m[1]);
  ok(listed.length >= 4, `${listed.length} workspace keys cleared on load`);
  // Every key the workspace persists is either cleared or deliberately exempt. A key added later
  // and forgotten is exactly how this bug arrives again.
  const owned = [...new Set([...APP.matchAll(/"(rlmnb-[a-z-]+)"/g)].map((m) => m[1]))];
  const EXEMPT = ["rlmnb-ui-lang", "rlmnb-theme"];  // how the reader LOOKS at it, not what is taught
  for (const key of owned) {
    ok(listed.includes(key) || EXEMPT.includes(key),
       `${key} is ${EXEMPT.includes(key) ? "deliberately kept" : "cleared"}`);
  }
  // At module scope, or app.js reads the value before anything clears it.
  const call = SHIM.indexOf("resetWorkspacePrefs();");
  ok(call > 0 && call < SHIM.indexOf("PG.reset ="), "cleared at load, before PG.reset is defined");
  const html = readFileSync(join(DIST, "index.html"), "utf8");
  ok(html.indexOf("shim.js") < html.indexOf("app.js"), "and shim.js loads before app.js");
}

console.log("\nthe director never spells another table's label:");
{
  const DIR = readFileSync(join(DIST, "director.js"), "utf8");
  const TOUR = readFileSync(join(DIST, "tour.js"), "utf8");
  const labels = DIR.slice(DIR.indexOf("const LABEL"), DIR.indexOf("const L ="));
  const dones = [...labels.matchAll(/done:\s*"([^"]*)"/g)].map((m) => m[1]);
  ok(dones.length === 2, `${dones.length} done strings, one per language`);
  ok(dones.every((d) => d.includes("{install}")),
     "both name the install button by placeholder, not by word");
  ok(/\.replace\("\{install\}",\s*label\)/.test(DIR), "the placeholder is substituted at paint");
  ok(/PG\.ui\("install"\)/.test(DIR), "and substituted from the chrome's own current label");
  // Both languages must actually have that label, or the substitution renders "undefined".
  for (const lang of ["en", '"zh-Hant"']) void lang;
  ok((TOUR.match(/\binstall:\s*"/g) || []).length >= 2, "both chrome tables define install");

  // The advance button is the ordinary way through a demo, so it must not read as giving up, and
  // it must not promise a next step on the step that has none.
  ok(/skip:\s*"Next/.test(labels) && /skip:\s*"下一步/.test(labels),
     "the advance button says Next, not Skip");
  ok(/finish:\s*"/.test(labels), "the last step has its own label");
  ok(/L\(step && step\.last \? "finish" : "skip"\)/.test(DIR),
     "and the last step is what selects it");
}

console.log("\nthe shim answers /audio in the shape app.js reads:");
{
  const APP = readFileSync(join(DIST, "app.js"), "utf8");
  const SHIM = readFileSync(join(DIST, "shim.js"), "utf8");
  const gen = APP.slice(APP.indexOf("data.utterances.length") - 2000,
                        APP.indexOf("data.utterances.length") + 2000);
  const wants = [...new Set([...gen.matchAll(/\bdata\.([a-z_]+)/g)].map((m) => m[1]))];
  ok(wants.includes("utterances"), `app.js reads ${wants.length} field(s) off the reply`);

  const at = SHIM.indexOf('st.podcast = body.length');
  ok(at > 0, "the shim has an /audio handler");
  const handler = SHIM.slice(at, SHIM.indexOf("});", SHIM.indexOf("return json({", at)));
  for (const field of wants) {
    ok(new RegExp(`\\b${field}\\s*:`).test(handler), `the reply carries ${field}`);
  }
  ok(!/return json\(\{\s*podcast:/.test(handler), "the reply is flat, not nested under podcast");
}

console.log("\nthe director scrolls before it places the popover:");
{
  const DIR = readFileSync(join(DIST, "director.js"), "utf8")
    .split("\n").filter((l) => !l.trim().startsWith("//")).join("\n");
  const reveal = DIR.indexOf("this.revealTarget(target, step.side)");
  const place = DIR.indexOf("this.highlight(step, target)");
  ok(reveal > 0 && place > 0, "the tick both scrolls and highlights");
  ok(reveal < place, "revealTarget runs BEFORE highlight");
  ok(!/if\s*\([^)]*lastTarget[^)]*\)\s*this\.revealTarget/.test(DIR),
     "the scroll is not gated on the target being unchanged");
  // A tick that scrolls without building a new popover has to tell driver to measure again.
  ok(/\.refresh\s*\(\)/.test(DIR), "a later scroll refreshes the popover's placement");
  ok(/const\s+moved\s*=\s*this\.revealTarget/.test(DIR),
     "revealTarget's return value is what decides that");
}

console.log("\nthe director scrolls without dragging the page:");
{
  const DIR = readFileSync(join(DIST, "director.js"), "utf8")
    .split("\n").filter((l) => !l.trim().startsWith("//")).join("\n");
  ok(!/\.scrollIntoView\s*\(/.test(DIR), "no DOM scrollIntoView call");
  ok(/revealTarget\(/.test(DIR), "it has its own reveal that sets scrollTop");
  ok(/Math\.max\(0,/.test(DIR), "the computed offset is clamped");
}

console.log("\nskipping a wait ends the run and still lands its result:");
{
  const sh = { console: { log() {}, warn() {} }, URL, Request: Q, Response: R, MessageEvent: ME,
    EventTarget, structuredClone: clone, setTimeout, clearTimeout, JSON, Math, Object, Number,
    Map, Set, Promise, String, Array, Error,
    location: { href: `file://${DIST}/index.html`, hash: "" },
    document: { currentScript: { src: `file://${DIST}/shim.js` } },
    HTMLMediaElement: function () {}, addEventListener() {},
    fetch: async (input) => {
      const path = String(input && input.url ? input.url : input).replace(/^file:\/\//, "").split("?")[0];
      return new R(readFileSync(path, "utf8"), { headers: { "Content-Type": "application/json" } });
    } };
  sh.window = sh;
  sh.HTMLMediaElement.prototype = {};
  Object.defineProperty(sh.HTMLMediaElement.prototype, "src", {
    configurable: true, get() { return this._src; }, set(v) { this._src = v; },
  });
  const c2 = vm.createContext(sh);
  vm.runInContext(readFileSync(join(DIST, "tour.js"), "utf8"), c2, { filename: "tour.js" });
  vm.runInContext(readFileSync(join(DIST, "shim.js"), "utf8"), c2, { filename: "shim.js" });
  const SPG = sh.rlmPlayground;
  ok(typeof SPG.finishRun === "function", "the shim can finish a run early");

  const nb = fixtures.scenarios[0].id;
  await SPG.progress(nb);
  const started = Date.now();
  const inflight = sh.fetch(new Q(`http://x/notebooks/${nb}/overview`, { method: "POST", body: "{}" }));
  await new Promise((r) => setTimeout(r, 120));
  ok(SPG.isRunning("overview"), "the overview run is in flight");
  SPG.finishRun("overview");
  const resp = await inflight;
  const took = Date.now() - started;
  const after = await SPG.progress(nb);
  ok(took < 2000, `it ended early (${took}ms, against a 7000ms wait)`);
  ok(resp.status === 200, "the response still arrives");
  ok(after.overview, "and the overview still lands: the WAIT was skipped, not the result");
  ok(!SPG.isRunning("overview"), "nothing is left running");

  // The director must reach for it before advancing.
  const DIR = readFileSync(join(DIST, "director.js"), "utf8");
  const fn = DIR.slice(DIR.indexOf("async fulfilAndAdvance"), DIR.indexOf("\n    advance("))
    .split("\n").filter((l) => !l.trim().startsWith("//")).join("\n");
  ok(/finishRun\(/.test(fn), "Skip finishes the run before it advances");
}

console.log("\nrun checks are per kind, so a step cannot fall through another's run:");
{
  const s = { console: { log() {}, warn() {} }, JSON, Math, Object,
              document: { querySelector: () => null, getElementById: () => null } };
  s.window = s;
  vm.createContext(s);
  vm.runInContext(readFileSync(join(DIST, "tour.js"), "utf8"), s);
  const SCRIPT = s.rlmPlayground.SCRIPT;

  // Pretend ONLY the overview is running. Nothing downstream of the overview may report done.
  s.rlmPlayground.isRunning = (kind) => kind === "overview";
  s.rlmPlayground.lengthTouched = false;
  // Nothing else done yet, so any step reporting done is reacting to the OVERVIEW's run.
  const fresh = { sources: 0, sourcesTotal: 3, overview: false, turns: 0, turnsTotal: 2,
                  podcast: null, questions: ["q1", "q2"] };
  const bled = [];
  for (const step of SCRIPT) {
    // Dwell steps are held open by the director's own guard, and `overview` is the run's own step.
    if (step.id === "overview" || step.dwell || step.last) continue;
    let done;
    try { done = !!step.done(fresh); } catch { done = false; }
    if (done) bled.push(step.id);
  }
  ok(bled.length === 0,
     `an overview run completes only overview steps${bled.length ? ` — also completed: ${bled.join(", ")}` : ""}`);

  // Every dwell step must name the kind it is waiting on, or it waits on all of them.
  const unkinded = SCRIPT.filter((st) => st.dwell && !st.kind).map((st) => st.id);
  ok(unkinded.length === 0,
     `every dwell step names its kind${unkinded.length ? ` — missing: ${unkinded.join(", ")}` : ""}`);
}

console.log("\nnothing repaints while a run is in flight:");
{
  const DIR = readFileSync(join(DIST, "director.js"), "utf8");
  // Comments stripped: the one explaining this bug names `openNotebook` above the guard, and an
  // ordering check on raw text reads that as the guard coming second.
  const fn = DIR.slice(DIR.indexOf("async fulfilAndAdvance"), DIR.indexOf("\n    advance("))
    .split("\n")
    .filter((l) => !l.trim().startsWith("//"))
    .join("\n");
  ok(fn.length > 0, "fulfilAndAdvance is present");
  ok(/isRunning\(\)/.test(fn), "it checks whether a run is in flight");
  // The guard has to sit BEFORE the repaint, not after it.
  ok(fn.indexOf("isRunning()") < fn.indexOf("openNotebook"),
     "the in-flight check comes before openNotebook");
  // And nothing else may repaint unconditionally.
  const repaints = [...DIR.matchAll(/openNotebook\(/g)].length;
  ok(repaints <= 1, `openNotebook is called from one place only (${repaints})`);
}

console.log("\nno step completes before the reader acts:");
{
  const s = { console: { log() {}, warn() {} }, JSON, Math, Object,
              document: { querySelector: () => null, getElementById: () => null } };
  s.window = s;
  vm.createContext(s);
  vm.runInContext(readFileSync(join(DIST, "tour.js"), "utf8"), s);
  const SCRIPT = s.rlmPlayground.SCRIPT;
  s.rlmPlayground.isRunning = () => false;
  s.rlmPlayground.lengthTouched = false;

  const fresh = { sources: 0, sourcesTotal: 3, overview: false, turns: 0, turnsTotal: 2,
                  podcast: null, questions: ["q1", "q2"] };
  const instant = [];
  for (const step of SCRIPT) {
    if (step.dwell || step.last) continue; // held open by the director / deliberately terminal
    let done;
    try { done = !!step.done(fresh); } catch { done = false; } // DOM-reading steps throw here
    if (done) instant.push(step.id);
  }
  ok(instant.length === 0,
     `every step waits for the reader${instant.length ? ` — already done on arrival: ${instant.join(", ")}` : ""}`);

  // The literal form that caused it, forbidden outright — in CODE. Comments explaining the bug
  // mention the same string, and a naive grep flags the explanation as the defect.
  const CODE = readFileSync(join(DIST, "tour.js"), "utf8")
    .split("\n")
    .filter((l) => !l.trim().startsWith("//"))
    .join("\n");
  ok(!/done:\s*\(\)\s*=>\s*true/.test(CODE), "no step declares `done: () => true`");
}

console.log("\nthe demo notebook follows the interface language:");
{
  const CHROME = readFileSync(join(DIST, "chrome.js"), "utf8");
  const LANG = { "zh-Hant": "Traditional Chinese", en: "English" };
  for (const [ui, want] of Object.entries(LANG)) {
    const match = fixtures.scenarios.find((s) => s.lang === want);
    ok(!!match, `${ui} has a notebook to open (${match ? match.id : "none"})`);
  }
  // Both directions have to exist or the preference silently falls through to scenarios[0].
  const langs = new Set(fixtures.scenarios.map((s) => s.lang));
  ok(Object.values(LANG).every((l) => langs.has(l)),
     `every interface language maps to a real notebook language (${[...langs].join(", ")})`);

  // The arriving hash is captured ONCE, before anything writes it. Reading `location.hash` at call
  // time meant the hash we had just written won on every reload after the first, so the language
  // preference only ever applied on a reader's very first visit.
  ok(/ARRIVED_WITH\s*=/.test(CHROME), "the arriving hash is captured once, at load");
  const openInitial = CHROME.slice(CHROME.indexOf("async function openInitial"),
                                   CHROME.indexOf("async function noteTrimmedAudio"));
  ok(!/location\.hash\.replace/.test(openInitial),
     "openInitial does not re-read location.hash (it writes it)");
  ok(/ui-lang-changed/.test(CHROME), "changing the interface language re-picks the notebook");
}

console.log("\nthe dwell step cannot strand the reader:");
{
  const s = { console: { log() {}, warn() {} }, JSON, Math, Object };
  s.window = s;
  vm.createContext(s);
  vm.runInContext(readFileSync(join(DIST, "tour.js"), "utf8"), s);
  const SCRIPT = s.rlmPlayground.SCRIPT;
  const dwell = SCRIPT.filter((st) => st.dwell);
  ok(dwell.length > 0, `${dwell.length} dwell step(s)`);

  for (const d of dwell) {
    const i = SCRIPT.indexOf(d);
    const before = SCRIPT[i - 1];
    ok(!!before, `${d.id} has a step before it`);
    // The step before must release WHILE the run is in flight, or the dwell arrives too late.
    s.rlmPlayground.isRunning = () => true;
    let releasesOnStart = false;
    try { releasesOnStart = !!before.done({ overview: false, turns: 0, sources: 0, sourcesTotal: 0 }); }
    catch { releasesOnStart = false; }
    ok(releasesOnStart, `${before.id} hands over when the run STARTS, not when it ends`);
    // And the dwell itself must report done once nothing is running, so the director's own
    // grace counter is the only thing holding it.
    s.rlmPlayground.isRunning = () => false;
    ok(!!d.done({}), `${d.id} releases once the run is over`);
  }

  // The director must bound the wait rather than trust a run to arrive.
  const DIR = readFileSync(join(DIST, "director.js"), "utf8");
  ok(/waitedFor[\s\S]{0,200}POLL_MS/.test(DIR), "the dwell wait is bounded in the director");
}

console.log("\nplayground chrome stays interactive during the tour:");
{
  const CSS = readFileSync(join(DIST, "chrome.css"), "utf8");
  // (ids, classes/attrs/pseudo-classes, elements). The universal selector contributes nothing,
  // which is exactly why driver's rule is weak enough to override.
  const spec = (sel) => [
    (sel.match(/#[\w-]+/g) || []).length,
    (sel.match(/\.[\w-]+|\[[^\]]+\]|:[a-z-]+(?!\()/g) || []).length,
    (sel.match(/(^|[\s>+~])[a-z]+/g) || []).length,
  ];
  const beats = (a, b) => a[0] !== b[0] ? a[0] > b[0] : a[1] !== b[1] ? a[1] > b[1] : a[2] >= b[2];
  const DRIVER = spec(".driver-active *");

  // Rules in chrome.css that set `pointer-events: auto`.
  const enabling = [];
  for (const m of CSS.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    if (!/pointer-events:\s*auto/.test(m[2])) continue;
    for (const sel of m[1].split(",")) enabling.push(sel.trim());
  }
  ok(enabling.length > 0, `${enabling.length} selectors re-enable pointer events`);

  // Everything the reader must be able to click or select while a step is spotlit.
  for (const cls of ["pg-tour", "pg-foot", "pg-overlay"]) {
    const covering = enabling.filter((s) => s.includes(`.${cls}`) && s.includes(".driver-active"));
    const strong = covering.filter((s) => beats(spec(s), DRIVER));
    ok(strong.length > 0,
       `.${cls} opts back in and outranks .driver-active * ` +
       `(${strong.length}/${covering.length} rules win the cascade)`);
  }
}

console.log("\nheader chrome actually mounts:");
{
  const nodes = [];
  function makeEl(tag) {
    const n = {
      tagName: tag, className: "", children: [], parentElement: null, style: {}, dataset: {},
      hidden: false, type: "", textContent: "", title: "",
      appendChild(c) { c.parentElement = this; this.children.push(c); return c; },
      prepend(c) { c.parentElement = this; this.children.unshift(c); },
      insertBefore(c, ref) {
        // The real contract. Getting this wrong is the bug this block exists to catch.
        const at = this.children.indexOf(ref);
        if (at < 0) throw new Error("NotFoundError: reference node is not a child of this node");
        c.parentElement = this;
        this.children.splice(at, 0, c);
        return c;
      },
      addEventListener() {}, remove() {}, replaceChildren() { this.children = []; },
      querySelector() { return null; }, querySelectorAll() { return []; },
      setAttribute() {}, classList: { add() {}, remove() {}, toggle: () => false },
      get offsetParent() { return {}; },
    };
    nodes.push(n);
    return n;
  }
  // The real nesting from index.html: header > .header-actions > #settings-open
  const header = makeEl("header");
  const actions = makeEl("div");
  const settingsBtn = makeEl("button");
  const wordmark = makeEl("button");
  header.appendChild(wordmark);
  header.appendChild(actions);
  actions.appendChild(settingsBtn);

  const byId = { "settings-open": settingsBtn, "new-notebook": wordmark };
  const sandbox = {
    console: { warn() {}, log() {} }, setTimeout, clearTimeout, setInterval: () => 0,
    JSON, Math, Object, Number, Map, Set, Promise, String, Array, Error, Boolean,
    location: { href: "http://x/", hash: "", reload() {} },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: {
      readyState: "complete", body: makeEl("body"),
      currentScript: { src: "http://x/chrome.js" },
      createElement: makeEl,
      getElementById: (id) => byId[id] || null,
      querySelector: (s) => (s.includes("header") ? header : null),
      addEventListener() {},
    },
    addEventListener() {}, fetch: async () => ({ json: async () => ({}) }),
  };
  sandbox.window = sandbox;
  sandbox.rlmPlayground = {
    scenarios: async () => [],
    progress: async () => null,
    reset: async () => {},
  };
  const c = vm.createContext(sandbox);
  let threw = null;
  for (const f of ["tour.js", "chrome.js"]) {
    try { vm.runInContext(readFileSync(join(DIST, f), "utf8"), c, { filename: f }); }
    catch (err) { threw = `${f}: ${err.message}`; }
  }
  ok(!threw, threw || "tour.js + chrome.js evaluate cleanly");
  await new Promise((r) => setTimeout(r, 40));
  const added = actions.children.filter((n) => (n.className || "").includes("pg-"));
  // Four, not five: the Notebooks button was deleted. The product's own title dropdown is the
  // notebook picker, and a second one in the header was a second modal to keep working.
  ok(added.length >= 4, `${added.length} chrome controls inserted into .header-actions`);
  // Expected labels come from the copy table, not from strings pinned here: this asserts that the
  // chrome MOUNTED, and rewording a button should not fail a DOM test.
  const labels = added.map((n) => n.textContent || n.className).join(" ");
  const wanted = ["notebooks", "restart", "install", "github"].map((k) => c.rlmPlayground.ui(k));
  ok(labels.includes("pg-sim"), "header has the SIMULATED badge");
  for (const want of wanted) ok(labels.includes(want), `header has: ${want}`);
  ok(
    wordmark.children.some((n) => n.className === "pg-wordmark-tag"),
    "wordmark is tagged PLAYGROUND"
  );
}

// A page that is Chinese in the product and English in the guidance is the state this was reported
// for. Every user-facing string has to exist in both tables, and a key present in one and missing
// from the other must fail here rather than surface as a stray English sentence mid-demo.
console.log("\nno string is half-translated:");
{
  const s = { console: { log() {}, warn() {} }, JSON, Math, Object };
  s.window = s;
  vm.createContext(s);
  vm.runInContext(readFileSync(join(DIST, "tour.js"), "utf8"), s);
  const PG = s.rlmPlayground;
  const SRC = readFileSync(join(DIST, "tour.js"), "utf8");

  // Step copy: every step in SCRIPT must resolve to a non-empty title AND body in BOTH languages.
  const langs = ["en", "zh-Hant"];
  let holes = [];
  for (const step of PG.SCRIPT) {
    for (const lang of langs) {
      s.uiLang = () => lang;
      const [title, body] = PG.text(step.key);
      if (!title || !body) holes.push(`${step.key}/${lang}`);
    }
  }
  ok(holes.length === 0, `all ${PG.SCRIPT.length} steps have copy in both languages${holes.length ? ` — missing: ${holes.join(", ")}` : ""}`);

  // Chrome copy: compare the two tables key for key.
  const table = (lang) => {
    const i = SRC.indexOf(lang === "en" ? "    en: {" : '    "zh-Hant": {');
    const j = SRC.indexOf("\n    },", i);
    return new Set([...SRC.slice(i, j).matchAll(/^\s{6}(\w+):/gm)].map((m) => m[1]));
  };
  const en = table("en");
  const zh = table("zh-Hant");
  const onlyEn = [...en].filter((k) => !zh.has(k));
  const onlyZh = [...zh].filter((k) => !en.has(k));
  ok(en.size > 10, `chrome copy table has ${en.size} keys`);
  ok(onlyEn.length === 0 && onlyZh.length === 0,
     `chrome keys match${onlyEn.length ? ` — only en: ${onlyEn.join(", ")}` : ""}${onlyZh.length ? ` — only zh: ${onlyZh.join(", ")}` : ""}`);

  // The em-dash rule from /write: it is the strongest AI-tone marker in this register, and the
  // draft shipped twelve of them.
  const dashes = [];
  for (const f of ["tour.js", "chrome.js", "director.js", "shim.js"]) {
    const src = readFileSync(join(DIST, f), "utf8");
    for (const m of src.matchAll(/"((?:[^"\\]|\\.)*)"/g)) {
      if (m[1].includes("\u2014")) dashes.push(`${f}: ${m[1].slice(0, 40)}`);
    }
  }
  ok(dashes.length === 0, `no em-dash in user-facing strings${dashes.length ? ` — ${dashes[0]}` : ""}`);
}

console.log("\ndirector selectors still match the shipped UI:");
{
  const TOUR = readFileSync(join(DIST, "tour.js"), "utf8");
  const HTML = readFileSync(join(DIST, "index.html"), "utf8");
  // The playground's own chrome counts too: the final step spotlights a button this project adds,
  // and it can be renamed just as easily as one of the product's.
  const CHROME = readFileSync(join(DIST, "chrome.js"), "utf8");
  const hay = APP + HTML + CHROME;
  // Anchor per selector: the substring that must exist in app.js/index.html for it to resolve.
  // Runtime-built nodes are anchored on the className app.js assigns, not on static markup.
  const ANCHORS = {
    "#add-source-form": 'id="add-source-form"',
    "#chat-overview": 'id="chat-overview"',
    "chat-starter": '"chat-starter"',
    "ticker-affordance": '"ticker-affordance"',
    "ticker-toggle": '"ticker-toggle',
    "#ask-submit": 'id="ask-submit"',
    "studio-views": 'id="studio-views"',
    "podcast-length": '"podcast-length"',
    "#podcast-generate": 'id="podcast-generate"',
    "#podcast-body": 'id="podcast-body"',
    "traj-drawer": 'id="traj-drawer"',
    "notebook-current": 'id="notebook-current"',
    "traj-close": 'id="traj-close"',
    "traj-head": '"traj-head',
    "run-status": '"run-status"',
    "run-log": '"run-log"',
    "chat-history": 'id="chat-history"',
    "data-view-body": "data-view-body",
    ".pg-btn": '"header-btn pg-btn',
    ".header-btn": '"header-btn',
  };
  const targets = [...TOUR.matchAll(/target:\s*['"](.+?)['"],/g)].map((m) => m[1]);
  ok(targets.length >= 8, `${targets.length} director targets found in tour.js`);
  for (const [token, anchor] of Object.entries(ANCHORS)) {
    ok(hay.includes(anchor), `${token} -> ${anchor}`);
  }
  // Every target must name at least one token we verified above, so a NEW selector cannot be added
  // without also being anchored here.
  const known = Object.keys(ANCHORS);
  const unanchored = targets.filter((sel) => !known.some((k) => sel.includes(k)));
  ok(unanchored.length === 0,
     `every target is anchored${unanchored.length ? ` — unanchored: ${unanchored.join(" | ")}` : ""}`);
}

console.log("\naudio rewrite:");
const media = new sandbox.HTMLMediaElement();
media.src = `/notebooks/${nb}/audio/file?v=1`;
ok(media.src.endsWith(`audio/${nb}.mp3`), `player.src -> ${media.src.split("/").slice(-2).join("/")}`);

console.log(failures ? `\n${failures} FAILED` : "\nall checks passed");
process.exit(failures ? 1 : 0);
