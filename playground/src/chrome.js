/* rlm-notebook PLAYGROUND — the extra furniture.
 *
 * Loaded AFTER `app.js`, so the header it augments is already built and the app's own listeners are
 * already attached. Adds what a product page needs and the application itself has no reason to
 * carry: an honest SIMULATED badge, a scenario switcher, Reset, install commands, the repo link,
 * and the guided tour.
 *
 * Every node is built with `createElement`/`textContent`, never `innerHTML` with an interpolated
 * string — the same rule the application follows (invariant 29), kept here because this file
 * renders scenario titles and notebook names that came from a model.
 *
 * Styling uses the app's OWN custom properties (`--surface-2`, `--accent`, `--border`, …), so the
 * chrome inherits both themes for free and cannot drift from the product's palette.
 */
(() => {
  "use strict";
  const PG = window.rlmPlayground;
  const REPO = "https://github.com/qazbnm456/rlm-notebook";

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  function button(label, title, onClick, cls) {
    const b = el("button", `header-btn pg-btn ${cls || ""}`.trim(), label);
    b.type = "button";
    b.title = title;
    b.addEventListener("click", onClick);
    return b;
  }

  // --- modal ------------------------------------------------------------------------------------
  //: `hidden` plus a `[hidden]` rule in `chrome.css` that OUTRANKS the author `display:flex`
  //: (invariant 36 — this project has shipped that exact bug twice, once leaving an invisible
  //: overlay swallowing every click on the page).
  function modal(titleText, subtitleText, buildBody) {
    const overlay = el("div", "modal-overlay pg-overlay");
    overlay.hidden = true;
    const box = el("div", "modal pg-modal");
    box.appendChild(el("div", "modal-title", titleText));
    if (subtitleText) box.appendChild(el("p", "pg-modal-sub", subtitleText));
    const body = el("div", "pg-modal-body");
    box.appendChild(body);
    const foot = el("div", "pg-modal-foot");
    const close = el("button", "btn", "Close");
    close.type = "button";
    close.addEventListener("click", () => (overlay.hidden = true));
    foot.appendChild(close);
    box.appendChild(foot);
    overlay.appendChild(box);
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) overlay.hidden = true;
    });
    document.body.appendChild(overlay);
    return {
      open() {
        body.replaceChildren();
        buildBody(body, () => (overlay.hidden = true));
        overlay.hidden = false;
      },
    };
  }

  // --- scenario picker --------------------------------------------------------------------------
  const scenarioModal = modal(
    "Pick a notebook",
    "Every scenario is a real notebook from the author's own machine — real sources, real answers, " +
      "real reasoning traces. Switching reloads the workspace.",
    async (body, close) => {
      //: Grouped by OUTPUT language, because the two groups are built from the same source sets and
      //: the comparison between them is the thing worth noticing — a flat grid of six would hide it.
      const scenarios = await PG.scenarios();
      const groups = new Map();
      for (const s of scenarios) {
        if (!groups.has(s.lang)) groups.set(s.lang, []);
        groups.get(s.lang).push(s);
      }
      for (const [lang, items] of groups) {
        const sec = el("section", "pg-scenario-group");
        const head = el("h3", null, lang);
        head.appendChild(el("span", "pg-group-note", `${items.length} notebooks`));
        sec.appendChild(head);
        const grid = el("div", "pg-grid");
        for (const s of items) {
          const card = el("button", "pg-card");
          card.type = "button";
          const cardHead = el("div", "pg-card-head");
          cardHead.appendChild(el("strong", null, s.title || s.label));
          cardHead.appendChild(el("span", "pg-badge", s.badge));
          card.appendChild(cardHead);
          card.appendChild(el("p", null, s.blurb));
          if (s.utterances) {
            const meta = el("div", "pg-card-meta");
            meta.appendChild(el("span", null, `🎧 ${s.utterances}-turn episode`));
            if (s.audio && s.audio.trimmed) {
              meta.appendChild(
                el("span", "pg-card-warn",
                   `audio capped at ${Math.round(s.audio.seconds / 60)} min of ${Math.round(
                     (s.audio.full_seconds || 0) / 60)}`)
              );
            }
            card.appendChild(meta);
          }
          card.addEventListener("click", () => {
            close();
            location.hash = `#${s.id}`;
            location.reload();
          });
          grid.appendChild(card);
        }
        sec.appendChild(grid);
        body.appendChild(sec);
      }
      const note = el("p", "pg-modal-sub");
      note.textContent =
        "Both groups are built from the same sources. Only RN_OUTPUT_LANGUAGE differs — the prose " +
        "follows the reader, while every citation quote stays in the source's own words.";
      body.appendChild(note);
    }
  );

  // --- install ----------------------------------------------------------------------------------
  const installModal = modal(
    "Install rlm-notebook",
    "Python 3.11+. Click a command to copy it. A live run additionally needs model credentials and " +
      "a Deno sandbox (brew install deno).",
    (body) => {
      for (const group of PG.INSTALL) {
        const sec = el("section", "pg-install-group");
        sec.appendChild(el("h3", null, group.group));
        for (const [label, cmd] of group.items) {
          const row = el("button", "pg-cmd");
          row.type = "button";
          row.appendChild(el("span", "pg-cmd-label", label));
          row.appendChild(el("code", null, cmd));
          const mark = el("span", "pg-cmd-copy", "⧉");
          row.appendChild(mark);
          row.addEventListener("click", async () => {
            try {
              await navigator.clipboard.writeText(cmd);
              mark.textContent = "✓";
            } catch {
              mark.textContent = "select & copy";
            }
            setTimeout(() => (mark.textContent = "⧉"), 1400);
          });
          sec.appendChild(row);
        }
        body.appendChild(sec);
      }
      const link = el("a", "pg-link", "Full documentation & source on GitHub →");
      link.href = REPO;
      link.rel = "noopener";
      link.target = "_blank";
      body.appendChild(link);
    }
  );

  // The guided tour lives in `director.js` now: a passive checklist asked the reader to find things
  // for themselves, which is the same failure as loading the whole notebook up front.

  // --- header ------------------------------------------------------------------------------------
  function mount() {
    const header = document.querySelector("header.header");
    const settings = document.getElementById("settings-open");
    if (!header || !settings) return;

    const badge = el("span", "pg-sim");
    badge.appendChild(el("span", "pg-sim-dot"));
    badge.appendChild(el("span", null, "SIMULATED"));
    badge.title =
      "No server, no model, no network. Real notebooks and real recorded reasoning traces, " +
      "replayed in your browser.";
    header.insertBefore(badge, settings);

    header.insertBefore(button("Notebooks", "Switch demo notebook", () => scenarioModal.open()), settings);
    header.insertBefore(
      button("↺ Restart demo", "Start the guided walkthrough from an empty notebook", async () => {
        await PG.reset();
        location.reload();
      }),
      settings
    );
    header.insertBefore(
      button("↓ Install", "How to install and run it for real", () => installModal.open(), "pg-btn-primary"),
      settings
    );
    const star = el("a", "header-btn pg-btn pg-btn-star", "★ GitHub");
    star.href = REPO;
    star.target = "_blank";
    star.rel = "noopener";
    star.title = "Source, documentation and invariants";
    header.insertBefore(star, settings);

    const foot = el("div", "pg-foot");
    foot.appendChild(
      el("span", null,
        "A playground: the real rlm-notebook web UI, running against recorded data in your browser. " +
        "Nothing is sent anywhere and nothing is stored.")
    );
    const a = el("a", null, "See the source →");
    a.href = `${REPO}/tree/main/playground`;
    a.target = "_blank";
    a.rel = "noopener";
    foot.appendChild(a);
    document.body.appendChild(foot);
  }

  // --- boot --------------------------------------------------------------------------------------
  //: A landing page that opens on an empty workspace has thrown away its first three seconds, so
  //: the playground always has a notebook open. `openNotebook` is a top-level function in `app.js`
  //: and therefore global — this calls the product's own entry point rather than reproducing what
  //: it does.
  async function openInitial() {
    const scenarios = await PG.scenarios();
    const wanted = decodeURIComponent(location.hash.replace(/^#/, ""));
    const pick = scenarios.find((s) => s.id === wanted) || scenarios[0];
    if (!pick) return;
    location.hash = `#${pick.id}`;
    if (typeof window.openNotebook === "function") await window.openNotebook(pick.id);
  }

  //: A capped episode still shows its WHOLE transcript, so its later lines point past the end of
  //: the audio. Said once, near the player, rather than left as a thing that silently does nothing
  //: when clicked — the transcript's click-to-seek is one of the behaviours this page exists to
  //: demonstrate, and a dead click would read as a bug in the product.
  async function noteTrimmedAudio() {
    const scenarios = await PG.scenarios();
    const id = decodeURIComponent(location.hash.replace(/^#/, ""));
    const s = scenarios.find((x) => x.id === id) || scenarios[0];
    if (!s || !s.audio || !s.audio.trimmed) return;
    const body = document.getElementById("podcast-body");
    if (!body || body.querySelector(".pg-audio-note")) return;
    const note = el("div", "pg-audio-note");
    note.textContent =
      `Playground note: the transcript is the complete ${s.utterances}-turn episode, but the audio ` +
      `is capped at ${Math.round(s.audio.seconds / 60)} minutes for this page. Lines past that ` +
      `point still highlight and are still clickable — there is just no audio left to seek to.`;
    body.prepend(note);
  }

  async function start() {
    mount();
    try {
      await openInitial();
      // The Podcast panel renders lazily, so re-check when Studio tabs change rather than once.
      document.addEventListener("click", () => setTimeout(noteTrimmedAudio, 60), true);
      await noteTrimmedAudio();
      if (PG.startDirector) PG.startDirector();
    } catch (err) {
      console.warn("playground: could not open the initial notebook", err);
    }
  }

  if (document.readyState === "complete") start();
  else window.addEventListener("load", start);
})();
