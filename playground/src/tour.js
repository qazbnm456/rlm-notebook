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
  //: Ordered by what actually sells the product, not by where things sit on screen. The three
  //: headline demos come first — a grounded answer, the reasoning behind it, and the podcast —
  //: because those are the three a stranger cannot picture from a README and would otherwise have
  //: to install the whole stack to see.
  PG.TOUR = [
    {
      id: "ask",
      title: "1 · Ask a grounded question",
      body:
        "Press a starter question, or type your own. Watch the status line while it runs: that is a " +
        "reasoning trace from a run that really happened, replayed at its real shape. The answer " +
        "comes back with numbered strokes — every claim points at the passage it came from.",
      hint: "Press a starter question under the overview.",
    },
    {
      id: "trace",
      title: "2 · Open the reasoning trajectory",
      body:
        "Every answer keeps the run that produced it. The ⌁ pill opens the Trajectory drawer: " +
        "planner turns with the model's own reasoning, a tool timeline sized by real elapsed time, " +
        "the token budget, and what the pre-SUBMIT validator rejected before it would submit.",
      hint: "Click the ⌁ steps pill under an answer.",
    },
    {
      id: "podcast",
      title: "3 · Play the Audio Overview",
      body:
        "A two-host episode written from the same sources and synthesized locally. The transcript " +
        "is subtitles: it scrolls with the playhead, and clicking a line seeks to it. Every line " +
        "carries its own citations.",
      hint: "Open the Podcast tab in Studio, then press play.",
    },
    {
      id: "source",
      title: "Check a citation against the source",
      body:
        "Click a row in Sources to read the original. A citation verifies a COORDINATE — that the " +
        "passage exists where the model said it does — never that the prose around it is faithful. " +
        "That distinction is the whole design, and the UI never claims more than it checked.",
      hint: "Click any row in the Sources column.",
    },
    {
      id: "language",
      title: "Switch language and compare",
      body:
        "The English and Chinese notebooks are built from the SAME sources. Only the output " +
        "language differs: the prose follows the reader, while every citation quote stays in the " +
        "source's own words.",
      hint: "Open Notebooks in the header and pick the other language.",
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
