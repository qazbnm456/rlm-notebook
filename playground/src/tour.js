/* rlm-notebook PLAYGROUND — helpers, tour data, and the extra chrome.
 *
 * Loaded BEFORE `shim.js`, which calls into `window.rlmPlayground` for the four things that need a
 * judgement rather than a route: which recorded run to replay, how to shape a ticker event, what a
 * Guide tab should return, and what the Trajectory drawer reads.
 *
 * Everything the build precomputed with the real Python lives in `fixtures.json`; this file only
 * chooses between those pieces. Nothing here re-derives an answer the product already knows how to
 * compute — that rule is why the playground cannot drift into a mock-up.
 */
(() => {
  "use strict";
  const PG = (window.rlmPlayground = window.rlmPlayground || {});

  // --- which recorded run to replay -------------------------------------------------------------
  //: Traces are keyed by the run id of the run that HAPPENED; the playground's run ids are minted
  //: fresh by `app.js` each time. So the pick is by TASK and notebook, and a miss degrades to a
  //: short synthesised sequence rather than an empty ticker (invariant 29: a missing trace costs
  //: one affordance, never the page).
  const TASK_FOR = {
    ask: "AnswerQuestion",
    overview: "GenerateSummary",
    audio: "GeneratePodcastScript",
    "guide:summary": "GenerateSummary",
    "guide:faq": "GenerateFAQ",
    "guide:timeline": "GenerateTimeline",
    "guide:insight": "GenerateInsight",
  };

  PG.runsFor = (fixtures, nbId, kind) => {
    const want = TASK_FOR[kind] || "";
    return Object.entries(fixtures.runs || {})
      .filter(([id, r]) => id.startsWith(`${nbId}-`) && r.task.endsWith(want))
      .map(([, r]) => r);
  };

  PG.pickTrace = (fixtures, meta, runId) => {
    if (meta) {
      const pool = PG.runsFor(fixtures, meta.nbId, meta.kind);
      if (pool.length) return pool[0].ticker;
      const any = PG.runsFor(fixtures, meta.nbId, "ask");
      if (any.length) return any[0].ticker;
    }
    const first = Object.values(fixtures.runs || {})[0];
    return first ? first.ticker : PG.syntheticTicker();
  };

  PG.syntheticTicker = () => [
    { step: 1, kind: "thinking", primary: "Step 1", detail: "Reading the corpus and locating the source markers.", meta: null },
    { step: 2, kind: "code", primary: "Step 2", detail: "Slicing the blocks this answer will cite.", meta: null },
    { step: 3, kind: "tool", primary: "validate", primary_detail: "", detail: "Validation successful.", meta: null },
  ];

  //: `_translate_trace_event` already produced the shape `app.js` reads (invariant 52's
  //: `{kind, primary, detail, meta}`); it returns `null` for events with nothing to say, and the
  //: stream must not forward those.
  PG.tickerEvent = (raw) => raw || { kind: "thinking", primary: "…", detail: "", meta: null };

  // --- the Trajectory drawer --------------------------------------------------------------------
  PG.trajectory = (run) => run.trajectory;

  // --- Guide tabs -------------------------------------------------------------------------------
  //: Only the overview is persisted onto a notebook (invariant 38), and a Guide artifact is not —
  //: so `summary` and `faq` can be served from what this notebook REALLY produced (the overview is
  //: `GenerateSummary` + `GenerateFAQ`'s output), and `timeline`/`insight` have no recorded
  //: artifact at all.
  //:
  //: They therefore say so. Inventing a timeline would be the one genuinely dishonest thing this
  //: playground could do: every other pixel is either the shipped UI or output a model actually
  //: produced, and a reader has no way to tell a fabricated artifact from a real one.
  PG.guide = (nb, kind) => {
    const ov = nb.overview;
    if (kind === "summary" && ov) {
      return { kind, text: ov.text, citations: ov.citations, run_id: ov.run_id };
    }
    if (kind === "faq" && ov && (ov.starter_questions || []).length) {
      return {
        kind,
        items: ov.starter_questions.map((q) => ({
          question: q,
          answer:
            "Ask this in the Chat panel to see it answered with verifiable citations — the " +
            "playground replays the questions this notebook really produced.",
          citations: [],
        })),
        run_id: ov.run_id,
      };
    }
    return {
      kind,
      unavailable: true,
      note:
        "This Studio tab runs a live model call, and the playground only replays artifacts this " +
        "notebook actually produced. Install rlm-notebook and run it against your own sources to " +
        "generate one — nothing here is fabricated.",
      citations: [],
      run_id: null,
    };
  };

  // --- guided tour ------------------------------------------------------------------------------
  //: witr's playground taught the lesson this copies: a simulated product that does not TELL you
  //: what to try is a screenshot you can click. Each step names one action and what to look for.
  // --- the guided script ------------------------------------------------------------------------
  //: Each step SPOTLIGHTS one real control, says what it is about to do, and then WAITS for the
  //: reader to press it. Nothing advances on a timer, because the point is not to play a video at
  //: someone — it is that they did it, on the product's own controls, and can therefore believe the
  //: thing they just watched.
  //:
  //: `target` is a selector into the SHIPPED markup. `done(p)` reads `PG.progress()` — the stage the
  //: shim has actually reached — rather than a click, so a reader who explores ahead is never told
  //: to press something they already pressed.
  PG.SCRIPT = [
    {
      id: "sources",
      title: "Add the sources",
      body:
        "A notebook is nothing without a corpus. Press Add — the playground will stream in this " +
        "notebook's real sources one at a time. (You cannot add your own here: ingestion fetches, " +
        "parses and OCRs host-side, which needs a machine, not a browser tab.)",
      target: '#add-source-form button[type="submit"]',
      repeat: true,
      done: (p) => p.sources >= p.sourcesTotal,
      progress: (p) => `${p.sources} / ${p.sourcesTotal} sources`,
    },
    {
      id: "overview",
      title: "Generate the overview",
      body:
        "This is a real model run in the product: two tasks, a summary and the starter questions. " +
        "Press it and watch the status line — the reasoning ticking past is a recorded trace from " +
        "the run that actually produced this overview.",
      // Built by `renderChatOverview` at runtime (`.chat-starter` wrapping a `.btn`), not present
      // in the static markup — so the selector has to match what app.js CREATES, and a fallback
      // outside `#chat-overview` covers the case where the panel has not been filled yet.
      target: "#chat-overview button.btn, #chat-overview .chat-starter button, .chat-starter button",
      done: (p) => p.overview,
    },
    {
      id: "ask1",
      title: "Ask the first question",
      body:
        "The question is already in the box. Press Enter (or the send button) — Shift+Enter would " +
        "just add a line. Every claim in the answer comes back with a numbered stroke pointing at " +
        "the passage it came from.",
      target: "#ask-submit",
      fill: (p) => p.questions[0],
      done: (p) => p.turns >= 1,
    },
    {
      id: "trace",
      title: "Open the Trajectory drawer",
      body:
        "Press the ⌁ pill under the answer. Inside: every planner turn with the model's own " +
        "reasoning, a tool timeline sized by real elapsed time, the token budget, and what the " +
        "pre-SUBMIT validator rejected. Try the nav rail, the replay transport and a timeline " +
        "segment — Esc closes it.",
      target: ".turn .ticker-affordance, #chat-overview .ticker-affordance, .ticker-affordance",
      done: () => !document.getElementById("traj-drawer").hidden,
      afterBody:
        "That drawer is the answer to \u201cwhy did it say that\u201d — and it is why a run keeps " +
        "the id of the trace that produced it.",
    },
    {
      id: "ask2",
      title: "Ask a follow-up",
      body:
        "History is context, never a source: the follow-up can resolve \u201cit\u201d from the " +
        "conversation, but its citations are verified fresh against the corpus every time.",
      target: "#ask-submit",
      fill: (p) => p.questions[1],
      skipIf: (p) => p.turnsTotal < 2,
      done: (p) => p.turns >= 2,
    },
    {
      id: "podcast-tab",
      title: "Open the Podcast tab",
      body:
        "Studio holds the artifacts. The Podcast tab generates a two-host Audio Overview from the " +
        "same sources — script first, then speech synthesis.",
      target: '.studio-views [data-view="podcast"], .studio-views button',
      done: () => !!document.querySelector("#podcast-generate:not([hidden])"),
    },
    {
      id: "podcast-length",
      title: "Pick a length",
      body:
        "Three tiers, and they are numbers rather than adjectives: Short is 12-18 turns, Default " +
        "30-45, Long 60-90. It is asked here, at generation time, because that is the moment you " +
        "have an opinion about how long you want to listen.",
      target: ".podcast-length",
      done: () => true,
      manual: true,
    },
    {
      id: "podcast-generate",
      title: "Generate the episode",
      body:
        "This runs the script task and then synthesizes speech. Only the script half is cancellable " +
        "— synthesis runs host-side after the subprocess returns.",
      target: "#podcast-generate",
      done: (p) => !!p.podcast,
    },
    {
      id: "podcast-play",
      title: "Play it, and watch the transcript",
      body:
        "Press play. The transcript is subtitles: it scrolls with the playhead and highlights the " +
        "line being spoken, and clicking any line seeks to it. Each line carries its own citations. " +
        "The ↓ Download button hands you the file.",
      target: "#podcast-body audio",
      done: () => {
        const a = document.querySelector("#podcast-body audio");
        return !!a && a.currentTime > 1.5;
      },
    },
    {
      id: "compare",
      title: "Now compare the languages",
      body:
        "Open Notebooks in the header. The English and Chinese sets are built from the SAME " +
        "sources — only the output language differs. The prose follows the reader; every citation " +
        "quote stays in the source's own words.",
      target: ".pg-btn, .header-btn",
      done: () => false,
      last: true,
    },
  ];

  PG.INSTALL = [
    {
      group: "Install",
      items: [
        ["uv (recommended)", "uv tool install rlm-notebook"],
        ["pipx", "pipx install rlm-notebook"],
        ["pip", "pip install rlm-notebook"],
      ],
    },
    {
      group: "Run the web UI",
      items: [
        ["with the API extra", "uv tool install 'rlm-notebook[api]'"],
        ["serve", "rlm-notebook serve"],
        ["then open", "http://localhost:8000/"],
      ],
    },
    {
      group: "Ask from the CLI",
      items: [
        ["one question", "rlm-notebook ask --source https://… 'your question'"],
        ["an episode", "rlm-notebook audio --source https://… --length long"],
      ],
    },
  ];
})();
