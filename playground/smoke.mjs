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

console.log("\naudio rewrite:");
const media = new sandbox.HTMLMediaElement();
media.src = `/notebooks/${nb}/audio/file?v=1`;
ok(media.src.endsWith(`audio/${nb}.mp3`), `player.src -> ${media.src.split("/").slice(-2).join("/")}`);

console.log(failures ? `\n${failures} FAILED` : "\nall checks passed");
process.exit(failures ? 1 : 0);
