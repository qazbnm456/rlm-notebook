/* rlm-notebook PLAYGROUND — the director.
 *
 * Runs `PG.SCRIPT`: spotlight one real control, say what it does, then WAIT for the reader to press
 * it. Nothing advances on a timer. The point is not to play a video at somebody — it is that they
 * pressed the product's own button and can therefore believe what they just watched.
 *
 * `driver.js` (MIT, vendored) does the spotlight, the popover positioning and the scroll-into-view.
 * It does NOT do the half that matters here: every tour library advances on its own Next button,
 * and this one advances on `PG.progress()` — the stage the shim has actually reached. So the buttons
 * are hidden (`showButtons: []`) and `moveNext()` is called from a poll.
 *
 * Consequences that shaped this file:
 *  - The highlighted element must stay clickable (`disableActiveInteraction` left false, and the
 *    overlay must never sit above it), or the reader cannot do the thing they are being asked to do.
 *  - `allowClose: false`, because a stray backdrop click would silently end the demo.
 *  - Steps are re-evaluated against real state, so a reader who explores ahead is never asked to
 *    press something they already pressed.
 */
(() => {
  "use strict";
  const PG = window.rlmPlayground;
  const POLL_MS = 350;

  //: `driver.js` exposes itself as `driver.js.driver` from the IIFE build. Absence is not fatal:
  //: the script still runs, just without the spotlight, which keeps a vendored-asset 404 from
  //: taking the whole page down.
  const factory =
    (window.driver && window.driver.js && window.driver.js.driver) || (window.driver || {}).driver;

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  //: Prefer a VISIBLE match, but fall back to one that merely exists. Requiring `offsetParent` was
  //: too strict: a control the app has built but not yet laid out reads as missing, the step shows
  //: no spotlight, and — because the instruction had moved into the popover — the reader was left
  //: with a title and nothing to do. driver.js scrolls whatever it is given into view anyway.
  const firstMatch = (selector) => {
    const parts = selector.split(",").map((s) => s.trim());
    for (const part of parts) {
      const found = document.querySelector(part);
      if (found && found.offsetParent !== null) return found;
    }
    for (const part of parts) {
      const found = document.querySelector(part);
      if (found) return found;
    }
    return null;
  };

  const notebookId = () => decodeURIComponent(location.hash.replace(/^#/, ""));

  //: The panel's own chrome follows the interface language too — a Chinese page with an English
  //: "Skip step" is the half-translated state this whole change exists to remove.
  const LABEL = {
    en: { head: "Guided demo", skip: "Skip", exit: "Exit", waiting: "Waiting for you…",
          finding: "Looking for the control…",
          manual: "Do this yourself, then the tour continues.",
          done: "That is the whole product. The Install button has what you need." },
    "zh-Hant": { head: "導覽", skip: "略過", exit: "結束", waiting: "等你操作…",
                 finding: "正在尋找控制項…",
                 manual: "請自己操作一次，導覽會接著走。",
                 done: "這就是產品的全貌。安裝方式在上面的「↓ Install」。" },
  };
  const L = (k) => {
    const lang = typeof uiLang === "function" ? uiLang() : "en";
    return (LABEL[lang] || LABEL.en)[k] || LABEL.en[k];
  };

  class Director {
    constructor() {
      this.index = 0;
      this.stopped = false;
      this.driver = null;
      this.panel = null;
      this.lastTarget = null;
    }

    // --- the panel ----------------------------------------------------------------------------
    //: A persistent panel BESIDE the spotlight, not only inside the popover. The popover moves with
    //: the target and can be missed; the panel is the one thing that is always in the same place
    //: when a reader looks up and asks "what am I supposed to do".
    buildPanel() {
      const panel = el("aside", "pg-tour");
      const head = el("div", "pg-tour-head");
      this.headLabel = el("span", "pg-tour-title", L("head"));
      head.appendChild(this.headLabel);
      this.count = el("span", "pg-tour-count");
      head.appendChild(this.count);
      const collapse = el("button", "pg-tour-collapse", "–");
      collapse.type = "button";
      collapse.addEventListener("click", () => {
        const open = !panel.classList.toggle("is-collapsed");
        collapse.textContent = open ? "–" : "+";
      });
      head.appendChild(collapse);
      panel.appendChild(head);

      this.bar = el("div", "pg-bar");
      this.barFill = el("div", "pg-bar-fill");
      this.bar.appendChild(this.barFill);
      panel.appendChild(this.bar);

      this.body = el("div", "pg-tour-list");
      panel.appendChild(this.body);

      const foot = el("div", "pg-tour-foot");
      this.skip = el("button", "btn pg-step-btn", L("skip"));
      this.skip.type = "button";
      this.skip.addEventListener("click", () => this.advance(true));
      foot.appendChild(this.skip);
      this.exit = el("button", "btn pg-step-btn", L("exit"));
      this.exit.type = "button";
      this.exit.addEventListener("click", () => this.stop());
      foot.appendChild(this.exit);
      panel.appendChild(foot);

      document.body.appendChild(panel);
      this.panel = panel;
    }

    //: Position and controls ONLY. The instruction is in the popover, anchored to the control it is
    //: talking about — repeating it here produced two blocks of identical text and a reader with no
    //: way to tell which one was asking something of them.
    paint(step) {
      const n = PG.SCRIPT.length;
      this.headLabel.textContent = L("head");
      this.skip.textContent = L("skip");
      this.exit.textContent = L("exit");
      this.count.textContent = `${Math.min(this.index + 1, n)} / ${n}`;
      this.barFill.style.width = `${(this.index / n) * 100}%`;
      this.body.replaceChildren();
      if (!step) {
        this.body.appendChild(el("p", "pg-done", L("done")));
        this.skip.hidden = true;
        return;
      }
      const [title, text] = PG.text(step.key);
      this.body.appendChild(el("div", "pg-step-title", title));
      // The instruction normally lives ONLY in the popover, anchored to the control it names. When
      // there is no popover — the control has not appeared yet — the panel carries it instead, so a
      // step can never present a heading with nothing to act on. `paintBody` is re-run by `tick`
      // when the spotlight appears or disappears.
      this.stepBody = el("p", "pg-step-body", text);
      this.stepBody.hidden = true;
      this.body.appendChild(this.stepBody);
      this.hint = el("div", "pg-step-hint");
      this.body.appendChild(this.hint);
    }

    showBodyInPanel(show) {
      if (this.stepBody) this.stepBody.hidden = !show;
    }

    setHint(text) {
      if (this.hint) this.hint.textContent = text || "";
    }

    // --- the spotlight ------------------------------------------------------------------------
    highlight(step, target) {
      if (!factory || !target || target === this.lastTarget) return;
      this.lastTarget = target;
      try {
        this.driver && this.driver.destroy();
      } catch {
        /* a destroyed driver throwing must not end the script */
      }
      this.driver = factory({
        // No Next button: this tour advances on what the reader actually did, not on a click that
        // would let them skip past the thing being demonstrated.
        showButtons: [],
        allowClose: false,
        overlayOpacity: 0.55,
        stagePadding: 6,
        popoverClass: "pg-pop",
      });
      const [title, body] = PG.text(step.key);
      this.driver.highlight({ element: target, popover: { title, description: body } });
    }

    clearSpotlight() {
      this.lastTarget = null;
      try {
        this.driver && this.driver.destroy();
      } catch {
        /* ignore */
      }
      this.driver = null;
    }

    // --- the loop -----------------------------------------------------------------------------
    async current() {
      const progress = await PG.progress(notebookId());
      if (!progress) return null;
      while (this.index < PG.SCRIPT.length) {
        const step = PG.SCRIPT[this.index];
        if (step.skipIf && step.skipIf(progress)) {
          this.index += 1;
          continue;
        }
        return { step, progress };
      }
      return null;
    }

    async tick() {
      if (this.stopped) return;
      const now = await this.current();
      if (!now) {
        this.clearSpotlight();
        this.paint(null);
        return;
      }
      const { step, progress } = now;

      if (step !== this.armed) {
        this.armed = step;
        this.missed = 0;
        this.clearSpotlight();
        this.paint(step);
        // Pre-fill the composer so the reader presses send rather than typing a question the demo
        // then has to pretend it recognised.
        if (step.fill) {
          const input = document.getElementById("ask-input");
          const text = step.fill(progress);
          if (input && text) {
            input.value = text;
            input.dispatchEvent(new Event("input", { bubbles: true }));
            input.focus();
          }
        }
      }

      // `done` is evaluated every tick against real state, so exploring ahead never strands anybody.
      let done = false;
      try {
        done = !!step.done(progress);
      } catch {
        done = false;
      }
      if (done && !step.last) {
        // A `repeat` step (streaming the sources in) presses the control for the reader after the
        // first press: they started it, and watching three identical clicks is not a demo.
        this.advance();
        return;
      }

      const target = firstMatch(step.target);
      if (target) {
        this.missed = 0;
        this.showBodyInPanel(false);
        this.highlight(step, target);
        this.setHint(step.progress ? step.progress(progress) : L("waiting"));
        if (step.repeat && this.started) this.maybeRepeat(target);
      } else {
        // Two ticks of grace before saying anything: a control that is one render away should not
        // make the panel flicker a warning.
        this.missed = (this.missed || 0) + 1;
        if (this.missed > 2) {
          this.clearSpotlight();
          this.showBodyInPanel(true);
          this.setHint(L("manual"));
        }
      }
      if (step.repeat && !this.started && target) {
        target.addEventListener("click", () => (this.started = true), { once: true });
      }
    }

    //: One press starts it; the director presses the rest, spaced out, so the sources stream in the
    //: way an ingest of several URLs actually feels rather than appearing all at once.
    maybeRepeat(target) {
      if (this.repeating) return;
      this.repeating = true;
      setTimeout(() => {
        this.repeating = false;
        if (!this.stopped) target.click();
      }, 700);
    }

    advance(manual) {
      this.index += 1;
      this.started = false;
      this.armed = null;
      this.clearSpotlight();
      if (manual) this.tick();
    }

    start() {
      this.buildPanel();
      // The product re-renders on `ui-lang-changed` rather than threading a language argument
      // through every renderer (invariant 48); the director subscribes for the same reason.
      window.addEventListener("ui-lang-changed", () => {
        this.armed = null;
        this.lastTarget = null;
        this.tick();
      });
      this.timer = setInterval(() => this.tick(), POLL_MS);
      this.tick();
    }

    stop() {
      this.stopped = true;
      clearInterval(this.timer);
      this.clearSpotlight();
      if (this.panel) this.panel.remove();
      PG.directorStopped = true;
    }
  }

  PG.startDirector = () => {
    if (PG.director) PG.director.stop();
    PG.director = new Director();
    PG.director.stopped = false;
    PG.director.start();
  };
})();
