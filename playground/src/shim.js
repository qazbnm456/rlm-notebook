/* rlm-notebook PLAYGROUND — the network shim.
 *
 * `app.js` is the SHIPPED application, copied verbatim and never edited. It reaches the network in
 * exactly three ways, and this file replaces all three before `app.js` is evaluated:
 *
 *   1. `window.fetch`             — every `api()` call (23 call sites, ~18 endpoints)
 *   2. `window.EventSource`       — the live reasoning-trace stream
 *   3. `HTMLMediaElement.src`     — the podcast `<audio>`, which is a browser fetch no shim can see
 *
 * Nothing else touches a server, so nothing else needs faking. That count is the whole reason this
 * approach is maintainable: if it were thirty entry points, forking the UI would be cheaper.
 *
 * SCRIPT ORDER IS THE CONTRACT. `app.js` captures no reference to these globals — it calls them at
 * request time — so replacing them first is sufficient AND necessary. `build.py` injects this file
 * before `i18n.js`/`app.js`; do not reorder them.
 */
(() => {
  "use strict";

  const BASE = new URL(".", document.currentScript ? document.currentScript.src : location.href);
  const asset = (p) => new URL(p, BASE).href;

  // --- fixture load -----------------------------------------------------------------------------
  // Loaded lazily and awaited INSIDE the handlers rather than blocking startup: every intercepted
  // call is already async, and a synchronous XHR to gate boot would stall first paint for a file
  // that only the first request needs.
  let fixturesPromise = null;
  const realFetch = window.fetch.bind(window);
  function fixtures() {
    if (!fixturesPromise) {
      fixturesPromise = realFetch(asset("fixtures.json")).then((r) => r.json());
    }
    return fixturesPromise;
  }

  // --- mutable demo state -----------------------------------------------------------------------
  // A DEEP COPY per scenario, so Reset is `delete state[id]` and the next read rebuilds from the
  // pristine fixture. Mutating the fixture in place would make Reset a no-op after the first edit,
  // which is exactly the bug a "reset" button exists to not have.
  const live = new Map();
  const PG = (window.rlmPlayground = window.rlmPlayground || {});

  async function notebook(id) {
    if (!live.has(id)) {
      const f = await fixtures();
      if (!f.notebooks[id]) return null;
      live.set(id, structuredClone(f.notebooks[id]));
    }
    return live.get(id);
  }

  PG.reset = async (id) => {
    if (id) live.delete(id);
    else live.clear();
  };
  PG.scenarios = async () => (await fixtures()).scenarios;

  // --- helpers ----------------------------------------------------------------------------------
  const json = (body, status = 200) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  const notFound = (detail) => json({ detail }, 404);

  //: A source added in the playground has no ingestion behind it, so it is labelled as simulated
  //: rather than dressed up as real. Pretending would be the one dishonest thing here: the reader
  //: would conclude their own URL had been fetched and read, and nothing about the answer would
  //: reflect it.
  function simulatedSource(nb, origin, kind) {
    const n = nb.sources.reduce((m, s) => Math.max(m, parseInt(s.id.slice(1), 10) || 0), 0) + 1;
    return {
      id: `s${n}`,
      kind,
      origin,
      flags: [],
      preview: {
        title: origin,
        description:
          "Added in the playground. Nothing was fetched or parsed — the demo runs entirely in " +
          "your browser, so answers below still come from the notebook's original sources.",
      },
    };
  }

  //: Settings are per-browser here. The real `PUT /settings` is a GLOBAL, unauthenticated mutation
  //: (invariant 41); a playground that persisted it across visitors would be that hazard shipped on
  //: purpose, so it lives in memory and dies with the tab.
  let settings = {
    output_language: { value: null, source: "default" },
    tts_voice_host_a: { value: null, source: "default" },
    tts_voice_host_b: { value: null, source: "default" },
    error: null,
  };

  // --- the router -------------------------------------------------------------------------------
  const ROUTES = [];
  const route = (method, pattern, handler) =>
    ROUTES.push({ method, re: new RegExp(`^${pattern}$`), handler });
  const NB = "/notebooks/([^/]+)";

  route("GET", "/notebooks", async () => {
    const f = await fixtures();
    const items = [];
    for (const s of f.scenarios) {
      const nb = await notebook(s.id);
      // Field names are `NotebookSummary`'s, not invented ones: the picker row reads
      // `source_count`/`turn_count`/`updated_at`, and a near-miss here renders "undefined sources"
      // rather than failing — which is why the smoke test asserts the shape and not just the 200.
      items.push({
        id: nb.id,
        title: nb.title,
        derived_title: nb.derived_title,
        source_count: nb.sources.length,
        turn_count: nb.turns.length,
        updated_at: Date.now() / 1000 - f.scenarios.indexOf(s) * 3600,
      });
    }
    return json({ notebooks: items, unreadable: [] });
  });

  route("GET", NB, async (m) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    return nb ? json(nb) : notFound(`notebook ${m[1]} not found`);
  });

  route("GET", `${NB}/sources/([^/]+)`, async (m) => {
    const id = decodeURIComponent(m[1]);
    const f = await fixtures();
    const src = (f.sources[id] || {})[decodeURIComponent(m[2])];
    return src ? json(src) : notFound("source not found");
  });

  route("POST", `${NB}/sources`, async (m, req) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    const body = await req.json();
    for (const url of body.sources || []) nb.sources.push(simulatedSource(nb, url, "web"));
    for (const t of body.texts || [])
      nb.sources.push(simulatedSource(nb, t.slice(0, 60).replace(/\s+/g, " "), "text"));
    return json(nb);
  });

  route("POST", `${NB}/sources/upload`, async (m) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    nb.sources.push(simulatedSource(nb, "uploaded-file", "pdf"));
    return json(nb);
  });

  route("DELETE", `${NB}/sources/([^/]+)`, async (m) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    const sid = decodeURIComponent(m[2]);
    const i = nb.sources.findIndex((s) => s.id === sid);
    if (i < 0) return notFound("source not found");
    nb.sources.splice(i, 1);
    // Survivors are never renumbered (invariant 50) and the artifacts go stale by set-equality
    // (invariant 38) — the playground shows both, because "why did my overview grey out" is one of
    // the things a reader most needs to understand before installing.
    const ids = new Set(nb.sources.map((s) => s.id));
    for (const art of [nb.overview, nb.podcast]) {
      if (art) art.stale = art.stale || !(art.source_ids || []).every((x) => ids.has(x));
    }
    if (nb.overview) nb.overview.stale = true;
    if (nb.podcast) nb.podcast.stale = true;
    return json(nb);
  });

  route("POST", `${NB}/notes`, async (m, req) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    const { text } = await req.json();
    // `n{max live numeric suffix + 1}`, never `n{length + 1}` — invariant 32: with length-based
    // ids, deleting a non-last note lets TWO live notes share one, and `delete`/`promote` both act
    // BY id, so either one would silently act on both.
    const max = nb.notes.reduce((mx, n) => Math.max(mx, parseInt(String(n.id).slice(1), 10) || 0), 0);
    nb.notes.push({ id: `n${max + 1}`, text });
    return json(nb);
  });

  route("DELETE", `${NB}/notes/([^/]+)`, async (m) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    const i = nb.notes.findIndex((n) => String(n.id) === decodeURIComponent(m[2]));
    if (i < 0) return notFound("note not found");
    nb.notes.splice(i, 1);
    return json(nb);
  });

  route("POST", `${NB}/notes/([^/]+)/promote`, async (m) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    const i = nb.notes.findIndex((n) => String(n.id) === decodeURIComponent(m[2]));
    if (i < 0) return notFound("note not found");
    const [note] = nb.notes.splice(i, 1);
    nb.sources.push(simulatedSource(nb, `note: ${note.text.slice(0, 48)}`, "text"));
    return json(nb);
  });

  route("DELETE", `${NB}/turns`, async (m) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    nb.turns = [];
    return json(nb);
  });

  route("PUT", `${NB}/title`, async (m, req) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    nb.title = (await req.json()).title;
    nb.derived_title = nb.title;
    return json(nb);
  });

  route("POST", `${NB}/title`, async (m) => json(await notebook(decodeURIComponent(m[1]))));

  route("GET", "/settings", async () => json(settings));
  route("PUT", "/settings", async (m, req) => {
    const body = await req.json();
    for (const k of ["output_language", "tts_voice_host_a", "tts_voice_host_b"]) {
      if (k in body) settings[k] = { value: body[k], source: body[k] ? "file" : "default" };
    }
    return json(settings);
  });
  route("GET", "/settings/choices", async () =>
    json({
      languages: ["Traditional Chinese", "Simplified Chinese", "English", "Japanese", "Korean"],
      voices: ["zh-TW-YunJheNeural", "zh-TW-HsiaoChenNeural", "en-US-AndrewNeural",
               "en-US-AvaNeural", "ja-JP-KeitaNeural", "ja-JP-NanamiNeural"],
    })
  );

  route("POST", `${NB}/runs/([^/]+)/cancel`, async () => json({ cancelled: true }));

  route("GET", `${NB}/runs/([^/]+)/trajectory`, async (m) => {
    const f = await fixtures();
    const events = f.traces[decodeURIComponent(m[2])];
    return events ? json(PG.trajectory(events)) : notFound("no trace for this run");
  });

  // --- the run-taking endpoints -----------------------------------------------------------------
  // These are the ones a real deployment pays a model for. Here they replay what the model ACTUALLY
  // produced for this notebook, after a delay long enough that the run status, the Stop button and
  // the live ticker all behave the way they do in the product — a run that returned instantly would
  // hide the entire "watch it think" surface this page exists to show.
  const RUN_MS = 2600;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  route("POST", `${NB}/ask`, async (m, req) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    const body = await req.json();
    PG.announce(body.run_id, nb.id, "ask");
    await sleep(RUN_MS);
    const canned = nb.turns[nb.turns.length - 1] || null;
    const pool = (await fixtures()).notebooks[nb.id].turns;
    const pick = pool.find((t) => t.question.trim() === (body.question || "").trim()) ||
      pool[nb.turns.length % pool.length] || canned;
    if (!pick) return json({ detail: "no canned answer" }, 422);
    const turn = { ...structuredClone(pick), question: body.question, run_id: body.run_id };
    if (body.regenerate && nb.turns.length) nb.turns[nb.turns.length - 1] = turn;
    else nb.turns.push(turn);
    return json({
      answer: turn.answer, citations: turn.citations,
      follow_ups: turn.follow_ups, run_id: turn.run_id,
    });
  });

  route("POST", `${NB}/overview`, async (m, req) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    const body = await req.json().catch(() => ({}));
    PG.announce(body.run_id, nb.id, "overview");
    await sleep(RUN_MS);
    const pristine = (await fixtures()).notebooks[nb.id].overview;
    nb.overview = pristine ? { ...structuredClone(pristine), stale: false } : null;
    return json(nb);
  });

  route("POST", `${NB}/guide/([a-z]+)`, async (m, req) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    const body = await req.json().catch(() => ({}));
    PG.announce(body.run_id, nb.id, `guide:${m[2]}`);
    await sleep(RUN_MS);
    return json(PG.guide(nb, m[2]));
  });

  route("POST", `${NB}/audio`, async (m, req) => {
    const nb = await notebook(decodeURIComponent(m[1]));
    const body = await req.json().catch(() => ({}));
    PG.announce(body.run_id, nb.id, "audio");
    await sleep(RUN_MS);
    const pristine = (await fixtures()).notebooks[nb.id].podcast;
    nb.podcast = pristine ? { ...structuredClone(pristine), stale: false } : null;
    return json({ podcast: nb.podcast, run_id: body.run_id });
  });

  // --- 1. fetch ---------------------------------------------------------------------------------
  window.fetch = async function (input, init) {
    const req = input instanceof Request ? input : new Request(input, init);
    const url = new URL(req.url, location.href);
    // Anything that is not one of OUR API paths is a real asset request (fixtures, audio) and goes
    // to the network untouched.
    if (!url.pathname.startsWith("/notebooks") && !url.pathname.startsWith("/settings")) {
      return realFetch(input, init);
    }
    for (const r of ROUTES) {
      if (r.method !== req.method) continue;
      const match = url.pathname.match(r.re);
      if (match) {
        try {
          return await r.handler(match, req, url);
        } catch (err) {
          return json({ detail: `playground shim error: ${err && err.message}` }, 500);
        }
      }
    }
    return notFound(`no playground route for ${req.method} ${url.pathname}`);
  };

  // --- 2. EventSource ---------------------------------------------------------------------------
  // Replays the REAL trace recorded for this notebook, paced so the ticker reads like a live run.
  // A run id with no recorded trace still streams — a short synthesised sequence — because a
  // missing trace must degrade one affordance and never the page (invariant 29).
  const announced = new Map();
  PG.announce = (runId, nbId, kind) => runId && announced.set(runId, { nbId, kind });

  class PlaygroundEventSource extends EventTarget {
    constructor(url) {
      super();
      this.url = String(url);
      this.readyState = 1;
      this._closed = false;
      this.onmessage = null;
      this.onerror = null;
      this._start();
    }
    close() {
      this._closed = true;
      this.readyState = 2;
    }
    _emit(obj) {
      if (this._closed) return;
      const ev = new MessageEvent("message", { data: JSON.stringify(obj) });
      if (this.onmessage) this.onmessage(ev);
      this.dispatchEvent(ev);
    }
    async _start() {
      const m = this.url.match(/\/notebooks\/([^/]+)\/runs\/([^/]+)\/stream/);
      const runId = m ? decodeURIComponent(m[2]) : "";
      const f = await fixtures();
      const meta = announced.get(runId);
      const events = PG.pickTrace(f, meta, runId);
      // Spread across the same window the POST takes, so the ticker finishes with the request
      // rather than long before or after it.
      const gap = Math.max(90, Math.floor(RUN_MS / Math.max(events.length, 1)));
      for (const raw of events) {
        if (this._closed) return;
        await sleep(gap);
        this._emit(PG.tickerEvent(raw));
      }
      if (!this._closed) this._emit({ kind: "done", primary: "Finished", detail: "", meta: null });
    }
  }
  window.EventSource = PlaygroundEventSource;

  // --- 3. <audio> -------------------------------------------------------------------------------
  // `player.src = "/notebooks/…/audio/file"` is a browser-issued request, invisible to `fetch`. The
  // property setter is the only seam, and rewriting there keeps `app.js` untouched.
  const media = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "src");
  Object.defineProperty(HTMLMediaElement.prototype, "src", {
    configurable: true,
    enumerable: media.enumerable,
    get() {
      return media.get.call(this);
    },
    set(value) {
      const s = String(value);
      const m = s.match(/\/notebooks\/([^/]+)\/audio\/file/);
      media.set.call(this, m ? asset(`audio/${decodeURIComponent(m[1])}.mp3`) : value);
    },
  });
})();
