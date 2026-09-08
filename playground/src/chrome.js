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
  //: Title and subtitle are FUNCTIONS, read when the modal opens rather than when it is built, so a
  //: language change between page load and opening it is picked up.
  function modal(titleText, subtitleText, buildBody) {
    const asText = (v) => (typeof v === "function" ? v() : v);
    const overlay = el("div", "modal-overlay pg-overlay");
    overlay.hidden = true;
    const box = el("div", "modal pg-modal");
    const titleEl = el("div", "modal-title");
    box.appendChild(titleEl);
    const subEl = el("p", "pg-modal-sub");
    box.appendChild(subEl);
    const body = el("div", "pg-modal-body");
    box.appendChild(body);
    const foot = el("div", "pg-modal-foot");
    const close = el("button", "btn", PG.ui("close"));
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
        titleEl.textContent = asText(titleText);
        subEl.textContent = asText(subtitleText);
        close.textContent = PG.ui("close");
        body.replaceChildren();
        buildBody(body, () => (overlay.hidden = true));
        overlay.hidden = false;
      },
    };
  }

  // --- scenario picker --------------------------------------------------------------------------
  const scenarioModal = modal(
    () => PG.ui("pickTitle"),
    () => PG.ui("pickSub"),
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
        // The heading is the LANGUAGE, translated. `lang` stays English because it is the grouping
        // KEY (and the fixture's own field); what a reader sees comes from the copy table.
        const head = el("h3", null, PG.ui(lang === "English" ? "groupEn" : "groupZh"));
        head.appendChild(el("span", "pg-group-note", PG.ui("groupCount", items.length)));
        sec.appendChild(head);
        // A LIST, not a grid of cards. The product's own notebook picker (`.notebook-row`) is a
        // dense column of rows: a title line, a quiet line under it, hover on the row. The grid this
        // replaces stretched every card to its row's tallest sibling, left a lone card marooned
        // beside empty space, and put the title and a badge on one line inside a 240px column so
        // they fought for it.
        const list = el("div", "pg-picklist");
        for (const s of items) {
          const row = el("button", "pg-pickrow");
          row.type = "button";
          const line = el("div", "pg-pickrow-line");
          line.appendChild(el("strong", "pg-pickrow-title", s.title || s.label));
          // Only a badge that SAYS something. Every row used to carry its own language, directly
          // under a heading that had just said it.
          if (s.badge) line.appendChild(el("span", "pg-badge", PG.ui(`badge.${s.badge}`)));
          row.appendChild(line);
          const blurb = s.blurb && typeof s.blurb === "object"
            ? s.blurb[uiLang()] || s.blurb.en
            : s.blurb;
          if (blurb) row.appendChild(el("p", "pg-pickrow-blurb", blurb));
          if (s.utterances) {
            const meta = el("div", "pg-pickrow-meta");
            meta.appendChild(el("span", null, `\u266a ${PG.ui("turnEpisode", s.utterances)}`));
            if (s.audio && s.audio.trimmed) {
              meta.appendChild(
                el("span", "pg-card-warn",
                   `audio capped at ${Math.round(s.audio.seconds / 60)} min of ${Math.round(
                     (s.audio.full_seconds || 0) / 60)}`)
              );
            }
            row.appendChild(meta);
          }
          row.addEventListener("click", () => {
            close();
            location.hash = `#${s.id}`;
            location.reload();
          });
          list.appendChild(row);
        }
        sec.appendChild(list);
        body.appendChild(sec);
      }
      const note = el("p", "pg-modal-sub");
      note.textContent = PG.ui("pickNote");
      body.appendChild(note);
    }
  );

  // --- install ----------------------------------------------------------------------------------
  const installModal = modal(
    () => PG.ui("installTitle"),
    () => PG.ui("installSub"),
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
      const link = el("a", "pg-link", `${PG.ui("installMore")} →`);
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
    const settings = document.getElementById("settings-open");
    if (!settings) return;
    // INSERT INTO THE SETTINGS BUTTON'S OWN PARENT, not into `<header>`. `#settings-open` sits
    // inside `<div class="header-actions">`, so `header.insertBefore(node, settings)` throws
    // NotFoundError — the reference node must be a direct child. That one throw took down mount(),
    // and with it `openInitial()` and the director: the page rendered as the bare product with no
    // badge, no buttons and no guidance, which is exactly what the first screenshot showed.
    // Reading the parent instead of naming a container keeps this working if the markup nests
    // differently later.
    const bar = settings.parentElement;
    if (!bar) return;
    const put = (node) => bar.insertBefore(node, settings);

    // The wordmark says what this is, the way witr's does. Someone who lands here from a link has
    // to be told in the first glance that they are looking at a demo, not a running install.
    const wordmark = document.getElementById("new-notebook");
    if (wordmark && !wordmark.querySelector(".pg-wordmark-tag")) {
      wordmark.appendChild(el("span", "pg-wordmark-tag", "PLAYGROUND"));
      wordmark.title = "This is a simulated playground, not a running install.";
    }

    const badge = el("span", "pg-sim");
    badge.appendChild(el("span", "pg-sim-dot"));
    badge.appendChild(el("span", null, PG.ui("simulated")));
    badge.title = PG.ui("simulatedTip");
    put(badge);

    put(button(PG.ui("notebooks"), PG.ui("notebooksTip"), () => scenarioModal.open()));
    put(
      button(PG.ui("restart"), PG.ui("restartTip"), async () => {
        await PG.reset();
        location.reload();
      })
    );
    put(
      button(PG.ui("install"), PG.ui("installTip"), () => installModal.open(), "pg-btn-primary")
    );
    const star = el("a", "header-btn pg-btn pg-btn-star", PG.ui("github"));
    star.href = REPO;
    star.target = "_blank";
    star.rel = "noopener";
    star.title = PG.ui("githubTip");
    put(star);

    const foot = el("div", "pg-foot");
    foot.appendChild(el("span", null, PG.ui("footer")));
    const a = el("a", null, `${PG.ui("footerLink")} →`);
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
  //: `uiLang()` already resolves the interface language from localStorage, then
  //: `navigator.languages`, then English (invariant 48). The notebook opened should AGREE with it:
  //: landing on an English notebook inside a Chinese interface is the half-translated state, and it
  //: also hides the thing worth noticing, which is that both language sets come from one corpus.
  //:
  //: An explicit `#notebook-id` still wins, because a shared link names a specific notebook and
  //: guessing over it would break the link.
  const LANG_FOR_UI = { "zh-Hant": "Traditional Chinese", en: "English" };
  const preferredLang = () => LANG_FOR_UI[typeof uiLang === "function" ? uiLang() : "en"];

  //: Captured ONCE, before anything writes it. `openInitial` sets `location.hash` itself, so reading
  //: it at call time meant the hash always won from the second visit onward and the language
  //: preference only ever applied on somebody's very first load. An ARRIVING hash is a shared link
  //: and must be honoured; one we wrote ourselves is not a choice the reader made.
  const ARRIVED_WITH = decodeURIComponent(location.hash.replace(/^#/, ""));

  async function openInitial() {
    const scenarios = await PG.scenarios();
    const preferred = preferredLang();
    const pick =
      scenarios.find((s) => s.id === ARRIVED_WITH) ||
      scenarios.find((s) => s.lang === preferred) ||
      scenarios[0];
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
    // mount() is guarded SEPARATELY: it used to sit outside the try, so one DOM mistake in the
    // header took down `openInitial()` and the director with it and the page rendered as the bare
    // product. Chrome and guidance are independent features; one failing must not remove the other.
    try {
      mount();
    } catch (err) {
      console.warn("playground: header chrome failed to mount", err);
    }
    try {
      await openInitial();
      // The Podcast panel renders lazily, so re-check when Studio tabs change rather than once.
      document.addEventListener("click", () => setTimeout(noteTrimmedAudio, 60), true);
      await noteTrimmedAudio();
      // Records that the reader engaged with the length control, which is what that step asks of
      // them. A listener rather than a change to `app.js`, which stays untouched by the playground.
      document.addEventListener(
        "click",
        (e) => {
          if (e.target.closest && e.target.closest(".podcast-length")) PG.lengthTouched = true;
        },
        true
      );
      if (PG.startDirector) PG.startDirector();

      //: Changing the interface language should move the DEMO too. Reading English answers under a
      //: Chinese interface is the half-translated state again, one level up: the interface is only
      //: half the language the reader chose. A notebook whose language already matches is left
      //: alone, so this never interrupts somebody who is simply mid-demo.
      window.addEventListener("ui-lang-changed", async () => {
        const scenarios = await PG.scenarios();
        const want = preferredLang();
        const current = scenarios.find((s) => s.id === decodeURIComponent(location.hash.slice(1)));
        if (current && current.lang === want) return;
        const next = scenarios.find((s) => s.lang === want);
        if (!next) return;
        await PG.reset();
        location.hash = `#${next.id}`;
        location.reload();
      });
    } catch (err) {
      console.warn("playground: could not open the initial notebook", err);
    }
  }

  if (document.readyState === "complete") start();
  else window.addEventListener("load", start);
})();
