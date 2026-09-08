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
    // The fallback still requires the element to OCCUPY SPACE. Handing driver.js a zero-size node
    // (a control inside a hidden Studio view, say) puts the popover at the top-left corner of the
    // page, pointing at nothing — which is worse than no spotlight at all.
    for (const part of parts) {
      const found = document.querySelector(part);
      if (found && (found.offsetWidth > 0 || found.offsetHeight > 0)) return found;
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
          doing: "Doing it for you…",
          done: "That is the whole product. The Install button has what you need." },
    "zh-Hant": { head: "導覽", skip: "略過", exit: "結束", waiting: "等你操作…",
                 finding: "正在尋找控制項…",
                 manual: "請自己操作一次，導覽會接著走。",
                 doing: "正在幫你完成…",
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
      this.skip.addEventListener("click", () => this.fulfilAndAdvance());
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
      // A SIDE HINT per step. driver.js has a fifth arrow state, `-side-over`
      // (`.driver-popover-arrow-side-over { display: none }`): when the popover does not fit beside
      // the element it lands ON it and the arrow is hidden, which is what "no arrow" was. Naming a
      // side with room keeps the popover anchored and the arrow pointing at the thing it describes.
      // driver still falls back on its own if the hint does not fit.
      this.driver.highlight({
        element: target,
        popover: {
          title,
          description: body,
          ...(step.side ? { side: step.side } : {}),
          ...(step.align ? { align: step.align } : {}),
        },
      });
    }

    //: The popover follows its target; the panel is pinned bottom-right. On any step whose control
    //: sits low and right they land on each other. Measured after each highlight rather than
    //: guessed per step, because where the popover ends up depends on the viewport.
    //: The panel is pinned bottom-right and the popover follows its target, so on some steps they
    //: land on each other. A single fixed escape direction does not work: nudging LEFT moves the
    //: panel toward a popover anchored in the chat column, which is most of them. So all three
    //: resting places are tried and the first clear one wins; if none is clear the panel stays put
    //: rather than jittering between two bad options.
    avoidPopover() {
      if (!this.panel) return;
      const pop = document.querySelector(".driver-popover");
      const CLASSES = ["is-left", "is-top", "is-topleft"];
      if (!pop) {
        this.panel.classList.remove(...CLASSES);
        return;
      }
      const a = pop.getBoundingClientRect();
      // Resting geometry computed from the panel's own fixed offsets, never measured: the panel
      // has a transform transition, so `getBoundingClientRect` right after changing a class returns
      // the position it is still animating away from and the overlap is never seen.
      const w = this.panel.offsetWidth;
      const h = this.panel.offsetHeight;
      const GAP = 12;
      const P = 16;
      const candidates = [
        { cls: null, left: window.innerWidth - P - w, top: window.innerHeight - P - h },
        { cls: "is-left", left: P, top: window.innerHeight - P - h },
        { cls: "is-top", left: window.innerWidth - P - w, top: P + 56 },
        { cls: "is-topleft", left: P, top: P + 56 },
      ];
      const clear = (c) =>
        !(a.left < c.left + w + GAP && a.right > c.left - GAP &&
          a.top < c.top + h + GAP && a.bottom > c.top - GAP);

      const pick = candidates.find(clear);
      this.panel.classList.remove(...CLASSES);
      if (pick && pick.cls) this.panel.classList.add(pick.cls);
    }

    clearSpotlight() {
      this.lastTarget = null;
      if (this.panel) this.panel.classList.remove("is-nudged");
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

    //: `tick` awaits, and the poll fires every 350ms, so two can overlap. When "Do it for me"
    //: advanced mid-await, the older tick resumed afterwards and re-armed and re-highlighted the
    //: step it had captured BEFORE the advance — the spotlight flashed and came straight back to
    //: the step the reader had just left. A generation counter makes a stale tick discard itself,
    //: and the re-entry guard stops two running at once in the first place.
    async tick() {
      if (this.stopped || this.ticking) return;
      this.ticking = true;
      try {
        await this.run();
      } finally {
        this.ticking = false;
      }
    }

    async run() {
      if (this.stopped) return;
      const gen = this.gen || 0;
      const now = await this.current();
      if (gen !== (this.gen || 0)) return; // advanced while awaiting: this result is stale
      if (!now) {
        this.clearSpotlight();
        this.paint(null);
        return;
      }
      const { step, progress } = now;

      if (step !== this.armed) {
        this.armed = step;
        this.missed = 0;
        this.sawRun = false;
        this.waitedFor = 0;
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
      // A DWELL step ends when a run ends, so it must first SEE one start. Without this it is
      // already "done" on arrival — no run is in flight yet — and skips past the very thing it
      // exists to hold the reader on.
      if (step.dwell) {
        if (PG.isRunning(step.kind)) this.sawRun = true;
        // Hold for a run, but not forever. "Do it for me" fulfils the previous step with no run at
        // all, and a dwell that waits unconditionally would strand the reader on a step whose whole
        // job is to show something that is never going to happen.
        this.waitedFor = (this.waitedFor || 0) + 1;
        if (!this.sawRun && this.waitedFor < Math.ceil(2500 / POLL_MS)) done = false;
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
        // AFTER highlighting: driver creates and positions the popover there, so measuring first
        // sized up either nothing or the previous step's popover. It also PLACES the popover
        // asynchronously, so one measurement can land before it has settled; the poll re-checks
        // every tick and a short follow-up catches the common case without waiting 350ms.
        this.avoidPopover();
        clearTimeout(this.avoidTimer);
        this.avoidTimer = setTimeout(() => this.avoidPopover(), 120);
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

    //: Skip means "do it for me": it advances the SHIM's stage and re-opens the notebook through
    //: `openNotebook`, the product's own entry point, so the workspace ends up in exactly the state
    //: pressing the button would have produced.
    async fulfilAndAdvance() {
      const now = await this.current();
      const step = now && now.step;
      // NEVER refresh while a run is in flight. `openNotebook` is a full repaint, and a repaint
      // during a run deletes the run — the product records this twice, as invariant 60 ("a repaint
      // may not delete a RUN") and invariant 71 (`renderChatOverview` clears the element holding the
      // run's own Stop button). Pressing this mid-run wiped the answer and the overview off the
      // screen and left a status strip with nothing behind it.
      //
      // There is nothing to fulfil in that case anyway: the run already underway produces exactly
      // the state this would have forced, so the script just moves on and lets it land.
      if (step && step.fulfil && !PG.isRunning()) {
        this.setHint(L("doing"));
        try {
          await PG.fulfil(notebookId(), step.fulfil);
          if (typeof window.openNotebook === "function") await window.openNotebook(notebookId());
        } catch (err) {
          console.warn("playground: could not fulfil the step", err);
        }
      }
      this.advance(true);
    }

    advance(manual) {
      this.gen = (this.gen || 0) + 1;
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
      // The overlap depends on the viewport, so a resize can create or clear one without any step
      // changing.
      window.addEventListener("resize", () => this.avoidPopover());
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
      clearTimeout(this.avoidTimer);
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
