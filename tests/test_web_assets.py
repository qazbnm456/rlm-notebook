"""Static checks on `rlm_notebook/web/` — the zero-build UI has no test runner of its own.

These assert on the SOURCE TREE rather than on rendered behavior, deliberately. The bug that
prompted the first one is invisible to every layer this project can otherwise test: the Python
suite never renders the page, and a unit test of `closeSourceViewer()` would pass against the
broken stylesheet, because the JS was always correct — it was the CSS that silently disabled the
attribute the JS relies on. A source-tree assertion runs in the normal suite, needs no browser,
and turns "someone has to remember" into a failing build.

**The first version of this file was itself reviewed and found badly wrong**, which is worth
recording because every fault was the same shape — it only looked at what was easy to parse:

- It harvested element ids from `index.html` only, so it could not see either element built with
  `createElement`. One of those, `.ticker-detail`, had the exact bug this file exists to catch,
  live and unfixed, while the file claimed to guarantee it could not happen.
- It matched `X.hidden = …` by bare variable name anywhere in the file, so an unrelated
  `body.hidden` in a `forEach` made it treat every `const body = getElementById(...)` as
  hidden-toggled — three confirmed false positives waiting on the next styling change.
- Its comment-stripping never ran: a `{`/`}` inside a CSS comment splits that comment across two
  regex "blocks", so neither half contains a complete `/*…*/`.

It now works on CSS CLASSES, which is the axis the hazard actually lives on and which both the
markup and the JS spell the same way.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "rlm_notebook" / "web"


def _strip_css_comments(css: str) -> str:
    """Remove `/* … */` BEFORE any block splitting. Doing it after is what broke the first version:
    a comment containing braces (this stylesheet has several, quoting CSS at the reader) is torn
    into pieces that no longer look like comments."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _rules(css: str) -> list[tuple[str, str]]:
    """(selector, body) pairs from comment-free CSS."""
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def _class_tokens(selector: str) -> set[str]:
    return set(re.findall(r"\.([A-Za-z][\w-]*)", selector))


def test_every_hidden_toggled_class_still_honours_the_hidden_attribute():
    """`hidden` works via the UA stylesheet's `[hidden] { display: none }`, which ANY author
    `display` declaration outranks — author styles beat UA styles regardless of specificity. So a
    class whose elements `app.js` shows/hides through `.hidden` MUST NOT carry an author `display`
    rule without a matching `[hidden]` rule.

    Both known instances shipped broken. `.modal-overlay { display: flex }` left the source-viewer
    overlay permanently visible, and with `inset: 0` + `z-index: 1000` it swallowed every click on
    the page — the whole UI was dead from the first paint. `.ticker-detail { display: flex }` left
    the reasoning-step log permanently expanded with a dead toggle. Both were found by a person
    opening the page, the second only after the first was "fixed" and this file wrongly claimed to
    cover it.

    Works on CLASSES, not ids: the markup and the JS both spell classes the same way, so an element
    built with `createElement` + `className` is just as visible here as one written in the HTML.
    """
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    rules = _rules(css)
    display_selectors = [sel for sel, body in rules if re.search(r"\bdisplay\s*:", body)]
    guarded = {c for sel in display_selectors if "[hidden]" in sel for c in _class_tokens(sel)}
    styled = {
        c for sel in display_selectors if "[hidden]" not in sel for c in _class_tokens(sel)
    }

    # Classes whose elements are hidden-toggled, from BOTH construction routes.
    toggled: set[str] = set()

    # KNOWN LIMITATION, stated rather than left to surprise someone: both routes match variable
    # names across the WHOLE file, so two functions using the same local name (`list`, `body`) make
    # this flag classes that are not actually hidden-toggled. That happened, and it fails LOUDLY —
    # the safe direction for a tripwire — so the fix is to rename the local, not to loosen this.

    # (a) createElement + className, then `<var>.hidden = …` on the same variable. The two
    #     statements are matched INDEPENDENTLY: requiring `.className` on the line immediately after
    #     `createElement` missed every element with anything in between, and an independent review
    #     found `logToggle.type = "button";` doing exactly that — `.run-log-toggle` was invisible
    #     here, a permanently-visible toggle waiting to be the `.ticker-detail` bug again.
    for var in set(re.findall(r"(?:const|let)\s+(\w+)\s*=\s*document\.createElement\(", js)):
        if not re.search(rf"\b{re.escape(var)}\.hidden\s*=", js):
            continue
        for class_expr in re.findall(rf"\b{re.escape(var)}\.className\s*=\s*([^;\n]+)", js):
            toggled |= set(re.findall(r"[\w-]+", class_expr.strip("\"'` ")))

    # (b) an id, inline OR via a stored reference, resolved to that element's classes in the markup.
    #     The stored form is the dominant style in this file; an independent review found the first
    #     rewrite only handled the inline one, leaving all three `.empty-note` elements invisible.
    ids = set(re.findall(r'getElementById\("([\w-]+)"\)\.hidden', js))
    binding = r'(?:const|let)\s+(\w+)\s*=\s*document\.getElementById\("([\w-]+)"\)'
    for var, element_id in re.findall(binding, js):
        if re.search(rf"\b{re.escape(var)}\.hidden\s*=", js):
            ids.add(element_id)
    for element_id in ids:
        tag = re.search(rf'<[^>]*\bid="{re.escape(element_id)}"[^>]*>', html)
        if tag:
            attr = re.search(r'class="([^"]*)"', tag.group(0))
            if attr:
                toggled |= set(attr.group(1).split())

    # (c) `querySelectorAll(".cls").forEach((x) => { … x.hidden = … })` — how `.tab-body` is driven,
    #     matched by neither of the routes above.
    for cls, var in re.findall(r'querySelectorAll\("\.([\w-]+)"\)\s*\.forEach\(\s*\(?(\w+)', js):
        if re.search(rf"\b{re.escape(var)}\.hidden\s*=", js):
            toggled.add(cls)

    # (d) `querySelectorAll("[data-attr]")` — an ATTRIBUTE selector, which route (c)'s class-only
    #     pattern cannot see. The four `.studio-view` panels are driven this way, so deleting
    #     `.studio-view[hidden]` used to leave all four rendering stacked on top of each other with
    #     this test still green.
    for var, attr in re.findall(
        r'(?:const|let)\s+(\w+)\s*=\s*\[?\.{0,3}\s*document\.querySelectorAll\("\[([\w-]+)\]"\)', js
    ):
        param = re.search(rf"\b{re.escape(var)}\.forEach\(\s*\(?(\w+)", js)
        if param and re.search(rf"\b{re.escape(param.group(1))}\.hidden\s*=", js):
            for tag in re.findall(rf'<[^>]*\b{re.escape(attr)}=[^>]*>', html):
                attr_match = re.search(r'class="([^"]*)"', tag)
                if attr_match:
                    toggled |= set(attr_match.group(1).split())

    # (e) A BARE `hidden` attribute in the markup. An element written hidden is by definition
    #     toggled — something has to unhide it or it would never be seen — and this route needs to
    #     know nothing about HOW. It is what the four routes above all missed for the Trajectory
    #     drawer, whose element is reached as `trajEl.drawer.hidden = …`: a property on an object
    #     built in a loop, which no `const x = getElementById(...)` pattern can match. Blind to the
    #     ordinary spelling of the very attribute this file exists to police.
    for tag in re.findall(r"<[^>]*\bhidden\b[^>]*>", html):
        if re.search(r'\bhidden\s*=\s*"', tag):
            continue  # `hidden="..."` is route (d)'s data-attribute shape, not a boolean attribute
        attr = re.search(r'class="([^"]*)"', tag)
        if attr:
            toggled |= set(attr.group(1).split())

    # A self-check on the EXTRACTION, one per route: if any route silently stops matching, this
    # fails loudly instead of the whole test passing vacuously — which is exactly how the first
    # version of this file reported "ok" for a class that was broken at the time.
    # `.ticker-detail` was one of these until the persisted steps pill stopped expanding inline and
    # started opening the Trajectory drawer. Replaced by `.traj-drawer` rather than dropped: this
    # list is what stops the whole test passing vacuously, so it has to keep naming a class that IS
    # hidden-toggled AND carries an author `display` — and the drawer is exactly that.
    for expected in (
        "modal-overlay", "traj-drawer", "empty-note", "tab-body", "run-log-toggle", "studio-view"
    ):
        assert expected in toggled, (
            f"the extraction no longer sees .{expected}, which IS hidden-toggled in app.js — a "
            f"route has silently stopped matching (found: {sorted(toggled)})"
        )
    offenders = sorted((toggled & styled) - guarded)
    assert not offenders, (
        "these classes are toggled via `hidden` but carry an author `display` rule with no "
        f"matching `[hidden]` rule, so `hidden` does nothing for them: {offenders}"
    )


def test_no_innerhtml_with_interpolated_content():
    """CLAUDE.md invariant 29: every DOM node carrying model- or source-derived content is built
    with createElement/textContent, never `innerHTML` with an interpolated string — a citation's
    `source_id`/`locator`/`quote` can echo attacker-supplied text from a prompt-injected source.
    Clearing a container is the one allowed use. `outerHTML`/`insertAdjacentHTML`/`document.write`
    are covered too: they are the same sink reached by a different name, and an independent review
    pointed out the first version of this test watched only one of the four."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    sinks = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")
    bad = []
    for line in js.splitlines():
        code = line.strip()
        # This file's comments discuss these sinks at length (explaining why they are avoided);
        # matching those would make the test fail on its own documentation. A first version did.
        if code.startswith(("//", "*", "/*")):
            continue
        if not any(sink in code for sink in sinks):
            continue
        if re.search(r"""innerHTML\s*=\s*(""|'')\s*;?$""", code):
            continue  # a bare clear
        bad.append(code)
    assert not bad, "an HTML-parsing sink used with something other than a bare clear:\n" + "\n".join(bad)


def test_every_init_function_is_actually_called():
    """Two features shipped inert because their `init*()` was never wired into the boot sequence:
    the header's notebook title (which therefore never displayed at all) and the settings button
    (dead on click, reported by a user). Both came from a scripted edit whose anchor didn't match,
    which `str.replace` silently ignores.

    Nothing else here can catch it — there is no JavaScript test runner (zero-build vanilla JS, by
    design), the Python suite never executes the page, and a defined-but-uncalled function is
    perfectly valid JS. A source-tree assertion is the only place this is visible."""
    js = (WEB / "app.js").read_text(encoding="utf-8")

    defined = set(re.findall(r"^function (init\w+)\(", js, re.MULTILINE))
    called = set(re.findall(r"^(init\w+)\(\);", js, re.MULTILINE))

    assert defined, "found no init functions — this test has stopped testing anything"
    uncalled = sorted(defined - called)
    assert not uncalled, (
        f"these init functions are defined but never called from the boot sequence: {uncalled}"
    )


def test_no_event_is_subscribed_twice_inside_one_init_function():
    """`store.emit` runs subscribers in registration order, so two handlers for the same event
    inside one `init*` function are a silent ordering trap: the persisted podcast rendered on
    `notebook:switched` and was then blanked by a `clearPlayer` subscriber registered a few lines
    later, so an episode never appeared on notebook open — the entire point of persisting it.

    Two subscribers for one event across DIFFERENT panels is normal and correct (each renders its
    own region); two inside one function are almost always one undoing the other."""
    js = (WEB / "app.js").read_text(encoding="utf-8")

    # Split on top-level `function name(` so each block is one init function's body.
    blocks = re.split(r"^function \w+\(", js, flags=re.MULTILINE)
    offenders = []
    for block in blocks:
        events = re.findall(r'store\.on\("([\w:]+)"', block)
        for event in set(events):
            if events.count(event) > 1:
                offenders.append(f"{event} subscribed {events.count(event)}x in one function")
    assert not offenders, "\n".join(offenders)


def test_no_studio_tab_click_starts_a_run_by_itself():
    """Selecting a Guide tab used to fire a real RLM call immediately, so browsing the four kinds
    to see what they were cost four model runs and a user could not tell which click had committed
    them. A user reported the panel as disorienting; every run is an explicit button press now.

    A source-tree assertion because there is no JS test runner here (invariant 29): `showKind` must
    not call `fetchKind`, and the tab click handler must go through `showKind`.
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")
    start = js.index("  function showKind(kind) {")
    end = js.index("\n  tabs.forEach(", start)
    body = js[start:end]
    # `fetchKind` may appear ONLY as a click handler inside `showKind` — that is the explicit button
    # press. Any other occurrence means selecting the tab itself starts a run again.
    occurrences = [line.strip() for line in body.splitlines() if "fetchKind(" in line]
    assert occurrences == ['btn.addEventListener("click", () => fetchKind(kind));'], occurrences
    assert 'tab.addEventListener("click", () => showKind(tab.dataset.guideKind));' in js


def test_every_long_running_action_offers_a_way_to_stop_it():
    """A user asked for this after watching a generation with no progress and no way out: chat,
    the chat overview, each Guide kind and the podcast all mount the shared `runStatus`, which is
    what carries the pulsing dot, the elapsed timer and the Stop button.

    Also pins that Stop cancels by RUN ID rather than by notebook: `/overview` fires two runs and
    `_ACTIVE_RUNS` holds one slot per notebook, so a notebook-scoped cancel would leave the second
    run burning a model call to completion.
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")
    # Minus one for the definition itself: chat, the chat overview, a Guide kind, the podcast.
    assert js.count("runStatus({") - js.count("function runStatus({") == 4
    assert "/cancel" in js and "runs/${encodeURIComponent(runId)}/cancel" in js
    # The overview cancels BOTH of its runs.
    assert "runIds: [`${base}-summary`, `${base}-faq`]" in js


def test_the_studio_panels_say_what_they_are_for():
    """Users could not tell what Studio, Podcast or Notes were. Each carries one visible sentence,
    and the per-control detail lives in `title=` hovers rather than more permanent prose — the
    treatment `toolscout`/`cve-reverser` use for their own controls."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    # Checked PER VIEW, not counted. A count passes as long as the total holds, and an independent
    # review found exactly that: the Studio view lost its sentence during the rail redesign while
    # References gained one, so `>= 3` stayed true and the panel this invariant is mostly about had
    # nothing at all.
    for view in ("studio", "podcast", "references", "notes"):
        marker = f'data-view-body="{view}"'
        assert marker in html, view
        body = html[html.index(marker) : html.index('data-view-body="', html.index(marker) + 1)] \
            if html.count('data-view-body="') > 1 and view != "notes" else html[html.index(marker):]
        assert 'class="panel-sub"' in body, f'the {view} view has no sentence saying what it is for'
    assert "Audio Overview" not in html, "renamed to Podcast — users did not know what it was"
    assert ">Podcast<" in html
    for kind in ("summary", "faq", "timeline", "insight"):
        marker = f'data-guide-kind="{kind}"'
        tab = html[html.index(marker) : html.index(">", html.index(marker))]
        # `data-tip`, this project's own tooltip, not the native `title`: the native one waits about
        # a second, which is what made the hover help feel disconnected from the hover effect.
        assert "data-tip=" in tab, kind


def _i18n_keys():
    """Every key the zh-Hant table defines, from the source rather than by running JS."""
    src = (WEB / "i18n.js").read_text(encoding="utf-8")
    start = src.index('"zh-Hant": {')
    depth, i = 0, src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                break
    table = src[i : j + 1]
    return set(re.findall(r'^\s*"([\w.]+)":', table, re.MULTILINE))


def test_every_translation_key_used_by_the_ui_exists_in_the_table():
    """A typo'd key is invisible at runtime — `t()` falls back to the English text and the interface
    silently stays half-translated. This is the only place that can catch it, since this project has
    no JS test runner (invariant 29)."""
    defined = _i18n_keys()
    assert len(defined) > 60, len(defined)

    html = (WEB / "index.html").read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n(?:-title|-placeholder|-html|-tip)?="([\w.]+)"', html))
    js = (WEB / "app.js").read_text(encoding="utf-8")
    # `\b` matters: without it this also matches the tail of `createElement("div")`.
    used |= set(re.findall(r'\bt\(\s*"([\w.]+)"', js))
    # Template-literal keys (`studio.kind.${kind}`) are checked by their known expansions instead.
    for kind in ("summary", "faq", "timeline", "insight"):
        used |= {f"studio.kind.{kind}", f"studio.tip.{kind}"}

    missing = sorted(used - defined)
    assert not missing, f"used but not translated: {missing}"


def test_every_t_call_passes_an_english_fallback():
    """`STRINGS.en` is deliberately EMPTY: the English UI is whatever the markup and the code
    already say, so it can never drift out of sync with a translation table nobody updated. That
    only works if every call site carries its own fallback — a bare `t("key")` would render the KEY
    to an English reader."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    bare = re.findall(r'\bt\(\s*"[\w.]+"\s*\)', js)
    assert not bare, bare


def test_the_interface_language_is_separate_from_the_output_language():
    """Two different questions: what the MODEL writes (invariant 39, a server setting) and what the
    BUTTONS say (this, a browser preference). Folding them together would make "Chinese interface
    over English papers" unexpressible, and would put a UI preference into a prompt."""
    raw = (WEB / "i18n.js").read_text(encoding="utf-8")
    # Comments stripped: this file EXPLAINS the separation, so it names the server setting in prose.
    # The assertion is about the code.
    i18n = "\n".join(
        line for line in raw.splitlines() if not line.lstrip().startswith("//")
    )
    app = (WEB / "app.js").read_text(encoding="utf-8")
    # The UI language lives in localStorage. It IS sent, as one signal among four that language
    # resolution weighs (invariant 69) — what this pins is the SEPARATION: `i18n.js` knows nothing
    # about the OUTPUT language, so the two settings can never collapse into one.
    assert "localStorage" in i18n
    assert "RN_OUTPUT_LANGUAGE" not in i18n
    assert "output_language" not in i18n
    # ...and the settings PUT body carries only the server settings, never the UI language.
    assert "setting-ui-language" in app
    put = app[app.index("function initSettings()") :]
    assert "ui_language" not in put

    # Simplified Chinese must NOT resolve to the Traditional table: shipping Traditional text to a
    # Simplified reader is worse than leaving it in English.
    assert "hant|tw|hk|mo" in raw


def test_the_notebook_id_never_appears_in_the_picker():
    """The id is an internal handle (invariant 37). It used to be the ONLY way to reach a notebook —
    a bare text box plus a datalist of `id (N sources, M turns)` — which put the handle and machine
    metadata in front of the name. Notebooks are located by title now."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")

    assert "notebook-input" not in html and "notebook-input" not in js
    assert "<datalist" not in html
    assert 'id="notebook-current"' in html and 'id="notebook-menu"' in html
    # The row is built from the TITLE; the id is only ever a value passed to openNotebook.
    row = js[js.index("function renderNotebookRow(") : js.index("function startRename(")]
    assert "nb.title" in row
    # The id may be COMPARED (is this the current notebook?) and PASSED (openNotebook), but it must
    # never be rendered: no assignment of it to any textContent.
    shown = re.findall(r"\.textContent\s*=\s*([^;]+);", row)
    assert shown, row
    assert not [line for line in shown if "nb.id" in line], shown


def test_titling_never_fires_from_adding_a_source():
    """A user called it too aggressive: adding a source spent a real model call before they had
    asked for anything. Titling is lazy now, from the actions that already run a model."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    start = js.index("const isFirstSource")
    end = js.index("function initChatPanel", start)
    # Boundaries checked, not assumed: an earlier version sliced to a marker defined EARLIER in the
    # file, so the range was empty and the assertion passed vacuously. Mutation-testing found it.
    assert end > start
    add = js[start:end]
    assert "suggestTitle(" not in add, add[-400:]
    assert "function ensureTitle()" in js
    # ...and it IS called from the paths that already committed the user to a run.
    assert js.count("ensureTitle();") >= 4


def test_the_run_status_counts_by_event_kind_rather_than_logging():
    """A scrolling log is the noise the user asked to avoid; a sibling project settled on typed
    counters plus one current-activity line, and ITS own comment explains why the framing matters.
    Pins that the ticker hands the whole EVENT over (the kind is what the counters are made of) and
    that a kind with no occurrences renders nothing."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "status.onEvent(evt)" in js or "status.onEvent(event)" in js
    assert "setSummary(evt.summary)" not in js, "the kind would be thrown away"
    meter = js[js.index("function renderMeter()") : js.index("let stopped = false;")]
    assert "if (!n) return;" in meter



def _tooltip_host_classes() -> set[str]:
    """Every CSS class that carries this project's own `data-tip` tooltip, from all three places one
    can be attached: a static attribute in the markup, `dataset.tip` on a `createElement`'d node,
    and a stylesheet rule that already targets `[data-tip]` on a named class."""
    hosts: set[str] = set()

    markup = (WEB / "index.html").read_text()
    for tag in re.findall(r"<[a-zA-Z][^>]*>", markup):
        if "data-tip" not in tag and "data-i18n-tip" not in tag:
            continue
        found = re.search(r'class="([^"]*)"', tag)
        if found:
            hosts.update(found.group(1).split())

    script = (WEB / "app.js").read_text()
    for var in set(re.findall(r"\b(\w+)\.dataset\.tip\s*=", script)):
        for value in re.findall(rf'\b{var}\.className\s*=\s*"([^"]*)"', script):
            hosts.update(value.split())

    for selector, _ in _rules(_strip_css_comments((WEB / "style.css").read_text())):
        if "[data-tip]" in selector:
            for part in selector.split(","):
                hosts.update(_class_tokens(part.split("[data-tip]")[0]))
    return hosts


def test_no_tooltip_host_clips_its_own_tooltip():
    """A `data-tip` tooltip is an `::after` on its host, so ANY clipping `overflow` on that host
    erases it outright — no console error, no layout shift, just an affordance that silently stops
    existing.

    This shipped twice in one slice. `.source-item { overflow: hidden }` (redundant: every child
    already clamps itself) took out the source card's tip AND the tips on the ⚠ flags and ✕ remove
    controls inside it; `.studio-view-tab { overflow: hidden }`, added to ellipsize a long tab
    label, took out the four right-rail tabs' tips — which is the one place a tip is not optional,
    since a collapsed rail shows nothing but icons. Reported as "以前有的 hover tooltip 效果都不見了".

    Not covered, and stated rather than implied: an ANCESTOR's clipping overflow does the same
    thing, and finding those needs a DOM this suite does not have. This checks the host itself,
    which is where both real instances were.
    """
    hosts = _tooltip_host_classes()
    assert {"studio-view-tab", "src-remove", "src-flags", "source-item"} <= hosts, (
        f"harvest broke — known tooltip hosts went missing, so this test would pass vacuously: {hosts}"
    )

    offenders = []
    for selector, body in _rules(_strip_css_comments((WEB / "style.css").read_text())):
        clipping = [
            declaration.strip()
            for declaration in body.split(";")
            if re.match(r"\s*overflow(-[xy])?\s*:\s*(hidden|clip|auto|scroll)", declaration)
        ]
        if not clipping:
            continue
        for part in selector.split(","):
            # The LAST compound is the element the rule actually styles; a class appearing earlier
            # is an ancestor or a state, and `.a .b { overflow: hidden }` says nothing about `.a`.
            subject = re.split(r"::", part.strip().split()[-1])[0]
            hit = _class_tokens(subject) & hosts
            if hit:
                offenders.append(f"{part.strip()} {{ {'; '.join(clipping)} }}  → clips {sorted(hit)}")

    assert not offenders, "a tooltip host clips its own tooltip:\n  " + "\n  ".join(offenders)


def test_the_studio_rail_thresholds_cannot_oscillate():
    """A two-state toggle driven by one continuous value (the pointer's distance from the window
    edge) is stable only while the OPEN threshold is at or above the CLOSE one. Put it below and
    every pointermove inside the gap flips the state — the panel visibly shuddering between two
    widths, which is what a user reported after exactly that change.

    Pinned as a source-tree assertion rather than a unit test because this project has no JS test
    runner (invariant 29), and pinned at all because the inverted version had a GOOD-SOUNDING
    reason behind it: re-opening from a 46px rail is cheap when the bar is low. The dead band that
    the correct ordering creates is covered by `--studio-rail` instead, not by breaking the
    ordering.
    """
    src = (WEB / "app.js").read_text()
    values: dict[str, int] = {}
    for name, raw in re.findall(r"const (STUDIO_\w+) = ([A-Za-z0-9_]+);", src):
        values[name] = int(raw) if raw.isdigit() else values[raw]

    assert {"STUDIO_EXPAND_AT", "STUDIO_COLLAPSE_AT", "STUDIO_MIN_WIDTH"} <= values.keys(), (
        f"the drag thresholds were renamed, so this test would pass vacuously: {sorted(values)}"
    )
    assert values["STUDIO_EXPAND_AT"] >= values["STUDIO_COLLAPSE_AT"], (
        f"inverted hysteresis: expanding at {values['STUDIO_EXPAND_AT']}px while collapsing at "
        f"{values['STUDIO_COLLAPSE_AT']}px makes every drag through that band flip the state on "
        f"every pointer event."
    )
    # Opening below the minimum width means the panel jumps away from the pointer the instant it
    # opens; opening AT the minimum means the two agree at the crossing.
    assert values["STUDIO_EXPAND_AT"] == values["STUDIO_MIN_WIDTH"]

    # ...and the CONSUMER has to pair each threshold with the right state. Checking the constants
    # alone was hollow: an independent review swapped the two arms of this ternary — reproducing the
    # exact reported shudder, since an open panel would then collapse below 240 while a collapsed
    # one expands above 170 — and this test stayed green. There is no seam to observe the choice
    # through (no JS test runner, invariant 29), so the assertion is on the expression itself.
    assert "collapsed ? STUDIO_EXPAND_AT : STUDIO_COLLAPSE_AT" in src, (
        "the drag handler no longer pairs the EXPAND threshold with the collapsed state; a swapped "
        "pair reintroduces the oscillation the constants above only look like they prevent"
    )


def test_the_markdown_renderer_never_creates_a_navigable_link():
    """A markdown link is SHOWN, never clickable, and that is a security decision rather than an
    omission. Invariant 1 refuses to let the model reach a URL because a prompt-injected source
    could steer it into exfiltrating notebook contents to an attacker-chosen address; an `<a href>`
    in an answer is the same hazard with the reader's click as the transport, arriving dressed as a
    citation-grounded reference.

    Pinned because `createElement("a")` is the obvious thing a future edit adds — the renderer even
    has the URL in hand at that point.
    """
    script = (WEB / "app.js").read_text(encoding="utf-8")
    start = script.index("const MD_FENCE")
    end = script.index("function renderAnswerWithCitations")
    renderer = script[start:end]
    assert "mdLinkAt" in renderer, "the extraction no longer sees the renderer; this would pass vacuously"

    # An independent review mutation-tested the first version of this list and got THREE navigable
    # links past it: `setAttribute("href", url)`, a template-literal `createElement(`a`)`, and a
    # click handler assigning `window.location`. A sink list is only as good as its worst omission,
    # so the anchor check is now a pattern over any quoting, and navigation is covered as well as
    # markup.
    assert not re.search(r"""createElement\(\s*['"`]a['"`]""", renderer), (
        "the markdown renderer creates an anchor element"
    )
    for sink in (".href", "setAttribute(\"href\"", "setAttribute('href'", "window.open",
                 "location.assign", "location.replace", "window.location", "document.location"):
        assert sink not in renderer, f"the markdown renderer builds a navigable link via {sink}"


def test_the_markdown_renderer_builds_nodes_rather_than_markup():
    """The whole reason this is hand-written instead of a library (invariant 29): every string it
    handles came out of a model that has been reading source content an attacker may have written.
    The sibling studios build markup as HTML strings with an `esc()` helper, where one missed call
    is an XSS sink; a sibling project states the same exception for the same reason."""
    script = (WEB / "app.js").read_text(encoding="utf-8")
    renderer = script[script.index("const MD_FENCE") : script.index("function renderAnswerWithCitations")]
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in renderer, f"the markdown renderer uses {sink}"
    # And it must never make its own text nodes: `emit` owns that, which is what keeps a citation
    # stroke splitting correctly across block and inline boundaries.
    assert "createTextNode" not in renderer, (
        "the markdown renderer creates text nodes directly; citation ranges are applied in `emit`, "
        "so text bypassing it can never carry a highlighter stroke"
    )



def test_the_chat_overview_lives_inside_the_thread_and_is_always_put_back():
    """Invariant 57's structure, pinned. The overview is `#chat-history`'s first child now, so any
    path that clears the list without re-appending it silently DELETES the notebook's front page —
    which is the risk the invariant names and accepts, and nothing was checking it.

    Two assertions because the hazard has two halves: the markup has to nest it, and the code has to
    have exactly one place that clears the list.
    """
    html = (WEB / "index.html").read_text(encoding="utf-8")
    history_at = html.index('id="chat-history"')
    overview_at = html.index('id="chat-overview"')
    close_at = html.index("</div>", html.index('id="chat-empty"'))
    assert history_at < overview_at < close_at, (
        "#chat-overview is no longer nested inside #chat-history; it was a sibling pinned above the "
        "thread, which cost the conversation 45% of the column permanently"
    )

    script = (WEB / "app.js").read_text(encoding="utf-8")
    start = script.index("function initChatPanel()")
    end = script.index("\nfunction ", start + 1)
    body = script[start:end]
    assert "const rebuildHistory" in body, "the extraction broke; this would pass vacuously"
    # Comments stripped first: this file DISCUSSES `history.innerHTML = ""` in the comment explaining
    # why exactly one place may do it, and counting that as a call site is a false positive that
    # would make the assertion unfixable.
    code = re.sub(r"//[^\n]*", "", body)
    clears = re.findall(r"history\.(?:innerHTML|textContent)\s*=\s*\"\"", code)
    assert len(clears) == 1, (
        f"{len(clears)} places clear the chat history; exactly one (`rebuildHistory`) may, because "
        f"it is the only one that puts the overview node back"
    )


def test_only_the_latest_answer_offers_follow_up_questions():
    """Every turn PERSISTS its own `follow_ups`, so rendering all of them put a row of chips under
    every answer in the thread — nine of ten offering to continue from a point the reader had
    already moved past. A user asked whether it would be "the last, newest one", which is what it
    should have been.

    The rule is CSS, deliberately: turns reach the DOM through TWO paths (`rebuildHistory` and the
    `chat:turnAdded` replay), and a rule that reads the DOM is correct for both without either
    having to remember which turn is newest. It also covers the pending row for free.
    """
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    script = (WEB / "app.js").read_text(encoding="utf-8")

    assert 'className = "turn-followups"' in script, (
        "the follow-up block lost its wrapper class, so the stylesheet rule below selects nothing"
    )
    # The rule's SUBJECT — its LAST compound — has to be `.turn-followups`. Checking only that the
    # token appears somewhere in the selector passed with the subject renamed to a class that
    # selects nothing, which is the mutation an independent review walked straight through.
    hides = []
    for selector, body in _rules(css):
        if "display: none" not in body or "not(:last-child)" not in selector:
            continue
        for part in selector.split(","):
            subject = re.split(r"::", part.strip().split()[-1])[0]
            if "turn-followups" in _class_tokens(subject):
                hides.append(part.strip())
    assert hides, (
        "nothing hides follow-up chips on a turn that is no longer the latest — check the rule's "
        "SUBJECT, not just that the class name appears in it somewhere"
    )


def test_the_overview_stops_offering_starters_once_the_conversation_has_begun():
    """"Start with" is an invitation to BEGIN — which is exactly why it is not unified with an
    answer's "Ask next" (invariant 56). Once turns exist the live suggestion is the latest answer's,
    at the bottom of the thread where the reader is; both on screen was two competing rows a scroll
    apart."""
    script = (WEB / "app.js").read_text(encoding="utf-8")
    start = script.index("function renderChatOverview()")
    end = script.index("\nfunction ", start + 1)
    body = script[start:end]
    assert "starter_questions" in body, "the extraction broke; this would pass vacuously"
    # The ORDER of the branches is the behaviour: turns-exist must come FIRST and be the empty one,
    # with the starter row built in the `else if`. Asserting only that the condition appears
    # somewhere passed with the two branches swapped — i.e. with starters shown ONLY once a
    # conversation exists, the exact inverse — which an independent review demonstrated.
    gate = body.index("if (state.turns && state.turns.length)")
    starters = body.index("starterQuestionRow(overview.starter_questions)")
    assert gate < starters, "the starter row is not behind the has-a-conversation gate"
    between = body[gate:starters]
    assert "else if" in between, (
        "the starter row is no longer the ELSE of the turns-exist gate, so the two can both render"
    )
    assert "starterQuestionRow" not in body[gate : gate + between.index("else if")], (
        "the turns-exist branch itself renders starters, which is the inverse of the rule"
    )


def test_a_message_naming_an_action_ships_with_that_action():
    """The overview's "regenerate to try again" note was gated on nothing, while the regenerate
    BUTTON was gated on `overview.stale` — so a reader whose FAQ half had timed out got told to do
    something the page did not offer. A user found it immediately.

    Pinned as the general rule rather than the instance: both the note and the control are set from
    the same `offerRegenerate` flag, so a future state that shows one shows the other.
    """
    script = (WEB / "app.js").read_text(encoding="utf-8")
    start = script.index("function renderChatOverview()")
    end = script.index("\nfunction ", start + 1)
    body = script[start:end]
    assert "chat.noStarters" in body, "the extraction broke; this would pass vacuously"

    # SEEDED from `overview.stale`, not just declared: `= false` keeps the declaration and silently
    # stops a stale overview from offering the button, which is the state the control was built for.
    assert re.search(r"let offerRegenerate\s*=\s*overview\.stale", body), (
        "the regenerate flag is no longer seeded from `overview.stale`, so a stale overview stops "
        "offering the button that exists for it"
    )
    # The note's branch must set it, and the button must be the flag's only consumer.
    note_at = body.index("chat.noStarters")
    assert "offerRegenerate = true;" in body[note_at : note_at + 400]
    assert body.count("chat.regenerateOverview") == 1

    # The control is now UNCONDITIONAL, which is the strongest possible form of this rule: a note
    # naming regeneration can never ship without it. It was gated on `offerRegenerate`, so an
    # overview that was current and complete but simply WRONG had no way to be regenerated — a user
    # asked how to press a button that was not on the page, while looking at an overview whose five
    # citations had all failed coordinate verification.
    # Checked by looking at what PRECEDES the append rather than by matching a syntax shape: a
    # mutation reintroduced the gate as a brace-less `if (offerRegenerate) el.appendChild(...)` and
    # a regex expecting `{` walked straight past it.
    button_at = body.index("chat.regenerateOverview")
    append_at = body.rindex("el.appendChild(", 0, button_at)
    assert "el.appendChild(" in body[button_at - 300 : button_at], "the button is not appended"
    preceding = body[max(0, append_at - 120) : append_at]
    assert "if (offerRegenerate)" not in preceding, (
        f"the regenerate control is gated again — an overview nobody has invalidated cannot be "
        f"redone. Preceding source: {preceding!r}"
    )

    # ...and the flag still decides the LABEL and the WEIGHT, so a stale or incomplete overview
    # gets the louder, explicit control rather than the quiet one a healthy overview carries.
    assert "chat.refreshOverview" in body, "the quiet variant is gone"
    assert re.search(r"offerRegenerate\s*\n?\s*\?\s*t\(\s*\"chat\.regenerateOverview\"", body), (
        "the stale/incomplete label is no longer chosen by the flag"
    )
    assert "!offerRegenerate," in body, "the quiet weight is no longer chosen by the flag"


def test_the_chat_placeholder_only_appears_while_its_sentence_is_true():
    """"Ask a question once you've added a source" is a precondition, and it was gated on TURNS
    alone — so a notebook with eight sources and no conversation still told the reader to add one.
    A user reported it as confusing, which it is: the page was describing a step they had already
    taken."""
    script = (WEB / "app.js").read_text(encoding="utf-8")
    start = script.index("function initChatPanel()")
    end = script.index("\nfunction ", start + 1)
    body = script[start:end]
    assert "syncEmptyNote" in body, "the extraction broke; this would pass vacuously"

    gate = body[body.index("const syncEmptyNote") : body.index("const rebuildHistory")]
    # The DIRECTION matters: `< 0` keeps the token and inverts the rule, and is never true, so the
    # placeholder would be shown forever. An independent review got that past the first version.
    assert re.search(r"\(state\.sources \|\| \[\]\)\.length > 0", gate), (
        "the chat placeholder does not hide itself once a source exists — check the comparison's "
        "direction, not just that `state.sources` is mentioned"
    )
    # And adding the first source must retire it immediately: nothing else redraws at that moment.
    changed_at = body.index('store.on("sources:changed"')
    assert "syncEmptyNote" in body[changed_at : changed_at + 400]


def test_a_citations_number_comes_from_the_notebook_wide_reference_order():
    """A stroke labelled "2" and the References row labelled "2" have to be the same thing — the
    renderer's own comment claimed exactly that while numbering 1..n WITHIN each artifact, so an
    overview citing two sources numbered them 1 and 2, the next answer numbered its first citation
    1 again, and the panel called that one 3. Every artifact after the first disagreed with the
    panel it points into.

    A user noticed the symptom from the other end — regenerating the overview and not being able to
    tell whether the References panel was still in sync.
    """
    script = (WEB / "app.js").read_text(encoding="utf-8")
    start = script.index("function renderAnswerWithCitations")
    end = script.index("\nfunction ", start + 1)
    body = script[start:end]
    assert "referenceNumberFor" in body, "the extraction broke; this would pass vacuously"
    # The exact MAPPING. `collectReferences()` appearing somewhere is not enough — a mutation that
    # kept a `void collectReferences();` and went back to per-artifact numbering passed, and so did
    # an off-by-one (`i` instead of `i + 1`), which is the precise bug this change is about.
    assert re.search(
        r"new Map\(\s*collectReferences\(\)\.map\(\(ref, i\) => \[referenceKey\(ref\), i \+ 1\]\)\s*\)",
        body,
    ), (
        "stroke numbers no longer come from `collectReferences()` position + 1, so they disagree "
        "with the References panel — which numbers `index + 1` over the same list"
    )
    # And no SECOND numbering map built from this artifact's own `citations`: the surviving mutation
    # left `void collectReferences();` in place and numbered per artifact next to it.
    assert not re.search(r"new Map\(\s*citations\.", body), (
        "a per-artifact numbering map survives; strokes numbered from it disagree with the panel"
    )
    # `renderReferenceView` numbers by position in that same list — the two must read one ordering.
    view = script[script.index("function renderReferenceView") :]
    assert "String(index + 1)" in view[:3000]


def test_regenerating_the_overview_renumbers_the_thread():
    """A new overview changes which coordinates come FIRST in the notebook-wide order, so strokes
    already on screen would keep numbers pointing at the wrong rows until the next reload."""
    script = (WEB / "app.js").read_text(encoding="utf-8")
    assert script.count('store.emit("chat:rerender"') == 1
    assert script.count('store.on("chat:rerender"') == 1
    gen = script[script.index("async function generateOverview") :]
    gen = gen[: gen.index("\nfunction ")]
    assert 'store.emit("chat:rerender"' in gen


def test_the_guide_cache_defines_every_method_its_callers_use():
    """It was a `Map`; moving the guide results onto `state` (so the References view could collect
    their citations) replaced it with an object literal that lost `delete` — and `regenerateBtn`
    calls exactly that, so Studio's ↻ Regenerate threw `TypeError: cache.delete is not a function`
    and did nothing. Shipped, and found by an independent review rather than by anything here.

    A duck-typed stand-in for a built-in is the general hazard: the compiler cannot see it, and the
    call site only fails when a user presses the button.
    """
    script = (WEB / "app.js").read_text(encoding="utf-8")
    start = script.index("function initStudioPanel()")
    end = script.index("\nfunction ", start + 1)
    body = script[start:end]

    literal_at = body.index("const cache = {")
    literal = body[literal_at : body.index("\n  };", literal_at)]
    defined = set(re.findall(r"^\s{4}(\w+):", literal, re.MULTILINE))
    assert {"has", "get", "set"} <= defined, (
        f"the extraction no longer sees the cache literal, so this would pass vacuously: {defined}"
    )

    used = set(re.findall(r"\bcache\.(\w+)\(", body))
    missing = used - defined
    assert not missing, f"`cache` is called with methods it does not define: {sorted(missing)}"


def _js_without_literals(script: str) -> str:
    """`app.js` with comments and string/template literals blanked, so an identifier scan sees code
    rather than prose. Crude on purpose — it only has to stop a `t` inside a message from counting."""
    out = re.sub(r"//[^\n]*", "", script)
    out = re.sub(r"/\*.*?\*/", "", out, flags=re.DOTALL)
    out = re.sub(r"`(?:[^`\\]|\\.)*`", "``", out)
    out = re.sub(r'"(?:[^"\\]|\\.)*"', '""', out)
    out = re.sub(r"'(?:[^'\\]|\\.)*'", "''", out)
    return out


def test_the_i18n_function_is_never_used_as_a_value():
    """`t` is the translation FUNCTION and nothing else, so every occurrence must be a call.

    This exists because of a real, shipped, silent failure: three closures took a parameter named
    `t`, an independent review pointed out that adding a translated string inside one would throw,
    and the fix renamed the parameters — but the podcast's `seek` body still said
    `player.currentTime = t`. Assigning a function to `currentTime` coerces to NaN, so clicking a
    transcript timecode stopped seeking, with no error anywhere. A user found it.

    A rename that does not reach the body is invisible to every other check here: the syntax is
    valid, the identifier resolves, and the value is silently wrong.
    """
    code = _js_without_literals((WEB / "app.js").read_text(encoding="utf-8"))
    offenders = []
    for match in re.finditer(r"(?<![\w.$])t(?![\w(])", code):
        line = code[: match.start()].count("\n") + 1
        offenders.append(f"line {line}: {code.splitlines()[line - 1].strip()[:90]}")
    assert not offenders, "`t` used as a value rather than called:\n  " + "\n  ".join(offenders)


def test_the_podcast_seeks_to_the_time_it_was_given():
    """The specific half of the rule above: `seek` must assign `currentTime` from its OWN parameter,
    not from whatever identifier happened to be in scope."""
    script = (WEB / "app.js").read_text(encoding="utf-8")
    body = script[script.index("const seek = (") :]
    body = body[: body.index("\n  };") + 4]
    param = re.match(r"const seek = \((\w+)\)", body).group(1)
    assert re.search(rf"player\.currentTime\s*=\s*{param}\b", body), (
        f"`seek({param})` does not assign `currentTime` from `{param}`, so clicking a timecode "
        f"seeks to NaN and silently does nothing"
    )


def test_the_podcast_button_offers_the_action_that_fits_the_state():
    """Same three-state shape the chat overview has (invariant 38): no episode -> an offer;
    an episode -> the player, with regeneration a quieter second action; stale -> the same button
    reading as the obvious next move.

    It used to be one permanent primary button sitting above a player that already existed, which
    put the loudest control in the panel on the action a reader with an episode is least likely to
    want — and made "have I already made one?" a question the button could not answer.
    """
    script = (WEB / "app.js").read_text(encoding="utf-8")
    start = script.index("function initPodcastPlayer()")
    end = script.index("\nfunction ", start + 1)
    body = script[start:end]

    sync = body[body.index("function syncGenerateButton") : body.index("store.on(\"notebook:switched\"")]
    assert "state.podcast" in sync, "the button no longer looks at whether an episode exists"
    assert "podcast.stale" in sync, "the button no longer distinguishes a stale episode"
    # Primary ONLY in the no-episode branch. Comparing POSITIONS passed with the regenerate branch
    # also styled primary, because the first occurrence is in the early-return either way — so this
    # reads the regenerate branch itself, which is everything after the early return.
    regenerate_branch = sync[sync.index("podcast.stale") :]
    assert "btn-primary" not in regenerate_branch, (
        "regenerating is styled as the primary action, on a panel that already has an episode — it "
        "costs a full model run plus synthesis (invariant 43)"
    )
    assert "btn-primary" in sync[: sync.index("podcast.stale")], (
        "the no-episode offer is no longer the primary action"
    )
    # And it has to be re-synced everywhere the state can change, or the label lies.
    for trigger in ('store.on("notebook:switched"', 'store.on("sources:changed"'):
        at = body.index(trigger)
        assert "syncGenerateButton" in body[at : at + 400], f"{trigger} does not re-sync the button"
    assert "syncGenerateButton();" in body[body.index("renderPodcast(body, {", body.index("try {")) :], (
        "a successful generation leaves the button still offering to generate"
    )


def test_the_podcast_transcript_is_not_capped_by_a_fixed_height():
    """22rem was chosen when the podcast shared a scrolling column with two other sections, where a
    tall transcript pushed everything below it off screen. It has its own view now (invariant 58),
    so the fixed cap only left a blank strip under the last line while the transcript scrolled.

    Pinned together with the reason it is a `max-height` and not `flex: 1`: filling would need an
    author `display` on `.studio-view`, which is `hidden`-toggled, and any such rule above
    `.studio-view[hidden]`'s specificity un-hides all four views at once — invariant 36's defect.
    """
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    rule = [body for sel, body in _rules(css) if sel.strip() == ".podcast-transcript.is-timed"]
    assert rule, "the extraction broke; this would pass vacuously"
    assert "overflow-y: auto" in rule[0], "the transcript no longer scrolls in its own box"
    assert re.search(r"\bflex:\s*1", rule[0]), (
        "the transcript no longer FILLS the space the rest of the panel leaves. Two fixed answers "
        "were tried and both were reported: `22rem` left a blank strip under the last line while "
        "the transcript scrolled, and `60vh` made the panel taller than the column so the whole "
        "column scrolled and took the heading with it"
    )
    assert "max-height" not in rule[0], "a cap defeats the flex chain that sizes this"

    # The chain only works if every box between it and the column can shrink below its content.
    for selector in (
        '.col-studio .studio-view[data-view-body="podcast"]',
        ".podcast-section",
        ".podcast-body",
    ):
        bodies = [b for sel, b in _rules(css) if sel.strip() == selector]
        assert bodies, f"{selector} lost its rule, so the flex chain is broken"
        assert "min-height: 0" in bodies[0], (
            f"{selector} has no `min-height: 0`, so a flex item's default minimum (its CONTENT) "
            f"stops the chain shrinking and the column scrolls instead"
        )

    # Filling the column requires `display: flex` on `.studio-view`, which is `hidden`-toggled — so
    # every VISIBLE `display` on that class must be OUTRANKED by a `[hidden]` rule. Specificity, not
    # mere presence: invariant 36's own tripwire compares by class name, so it would accept a guard
    # that loses the cascade. `display: none` needs no guard (it hides either way), which is what
    # `.col-studio.is-collapsed .studio-view` relies on.
    def specificity(selector):
        sel = re.sub(r"::[\w-]+", "", selector)
        ids = len(re.findall(r"#[\w-]+", sel))
        classes = len(re.findall(r"[.:\[][\w-]+", sel))
        return (ids, classes)

    guards = [
        specificity(part)
        for sel, body in _rules(css)
        for part in sel.split(",")
        if "studio-view" in _class_tokens(part)
        and "[hidden]" in part
        and re.search(r"\bdisplay\s*:\s*none\b", body)
    ]
    for sel, body in _rules(css):
        for part in sel.split(","):
            if "studio-view" not in _class_tokens(part) or "[hidden]" in part:
                continue
            if not re.search(r"\bdisplay\s*:\s*(?!none\b)\S+", body):
                continue
            mine = specificity(part)
            assert any(g > mine for g in guards), (
                f"`{part.strip()}` gives the hidden-toggled view a visible `display` and no "
                f"`[hidden]` rule outranks it, so a hidden view stays on screen — the defect "
                f"invariant 36 exists for, with all four views showing at once"
            )


def test_the_podcast_panels_small_controls_keep_their_own_width():
    """`.podcast-body` became a flex COLUMN so the transcript could fill what the rest of the panel
    leaves. A flex column stretches its children to full width by default, which turned the
    inline-block download link and the small steps pill into full-width boxes with their labels
    stranded on the left — reported from a screenshot, one fix after the last one.

    The player and the transcript should span; the buttons should not. Pinned because the stretch is
    a DEFAULT, so it comes back silently the moment someone adds another small control here.
    """
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    column = [b for sel, b in _rules(css) if sel.strip() == ".podcast-body"]
    assert column and "flex-direction: column" in column[0], "the extraction broke"

    exempt = {
        token
        for sel, body in _rules(css)
        if "align-self: flex-start" in body
        for part in sel.split(",")
        if ".podcast-body >" in part
        for token in _class_tokens(part.split(">")[-1])
    }
    assert {"btn", "ticker-affordance"} <= exempt, (
        f"a small control in the podcast panel is stretched to full width by the flex column: "
        f"exempted classes are {sorted(exempt)}"
    )


def test_the_podcast_length_is_chosen_at_generation_time_and_sent():
    """Three tiers, the same shape NotebookLM offers — asked AT generation time because that is
    when a reader has an opinion about how long they want to listen, and because changing your mind
    afterwards costs a full model run plus synthesis.

    Pinned because a control that renders but is never sent looks identical to one that works: the
    request would quietly produce a default-length episode after a real run.
    """
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = (WEB / "app.js").read_text(encoding="utf-8")

    for tier in ("short", "default", "long"):
        assert f'data-length="{tier}"' in html, f"the {tier} option is not offered"

    body = script[script.index("function initPodcastPlayer()") :]
    body = body[: body.index("\nfunction ", 1)]
    post = body[body.index('/audio`'):]
    assert "length: podcastLength()" in post[:400], (
        "the chosen length is never put in the request body, so every episode is `default`"
    )
    # ...and an unknown stored value must not be forwarded verbatim.
    reader = script[script.index("function podcastLength()") :]
    reader = reader[: reader.index("\n}") + 2]
    assert "PODCAST_LENGTHS.has" in reader, (
        "a hand-edited localStorage value reaches the server unchecked"
    )


def test_the_run_status_line_wraps_rather_than_truncating():
    """`.run-text` was `white-space: nowrap` with an ellipsis, so a long phrase lost its END — and
    the end is where the elapsed time lives, the one part that changes. A user hit it on
    "正在合成語音…（此階段無法中止）· 已…", where the wait counter was the casualty.

    `.run-status` already wraps its children, so a two-line status costs nothing.
    """
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    body = "".join(b for sel, b in _rules(css) if sel.strip() == ".run-text")
    assert body, "the extraction broke; this would pass vacuously"
    assert "nowrap" not in body, (
        "the status line clips again, and what it clips is the elapsed time — the only part a "
        "reader watching a slow run is actually reading"
    )
    assert "text-overflow: ellipsis" not in body


def test_the_scrollbar_is_themed_in_both_spellings():
    """The UA paints a scrollbar from the OS theme, not the page's, so the dark theme showed a
    near-white track down the middle of every scroller — reported from a screenshot.

    Both spellings are REQUIRED and are not alternatives: `scrollbar-color` is the standard
    (Firefox, Chromium 121+), `::-webkit-scrollbar` is Safari and older Chromium. Shipping one
    leaves the other's users looking at the bug."""
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    assert "scrollbar-color:" in css and "scrollbar-width:" in css
    assert "::-webkit-scrollbar-thumb" in css and "::-webkit-scrollbar-track" in css
    # The colours must come from the palette, or the fix reintroduces the bug on the other theme.
    thumb = re.search(r"::-webkit-scrollbar-thumb\s*\{([^}]*)\}", css)
    assert thumb and "var(--" in thumb.group(1), thumb.group(1) if thumb else "no thumb rule"


def test_a_citation_hover_names_the_source_not_the_raw_coordinate():
    """It read `s1 · whole` — the interface's own filing system. A user pointed out that nobody can
    tell what `s1` is."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "span.title = citationHoverLabel(match.citation);" in js
    assert re.search(
        r"span\.title\s*=\s*`\$\{match\.citation\.source_id\}", js
    ) is None, "the raw coordinate is back in the hover label"
    # And the helper must drop a `whole` locator, which is what every single-block source carries.
    helper = re.search(r"function citationHoverLabel\(citation\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert helper and '!== "whole"' in helper.group(1), "a `whole` locator is shown as if it located"


def test_clicking_a_citation_opens_its_reference_card_at_the_right_quote():
    """Arriving at a collapsed row left the reader to click it and then work out which of its
    quotes was theirs — "還是得自己點開並慢慢追", reported verbatim."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    focus = re.search(r"function focusReference\(citation\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert focus, "focusReference is gone"
    assert "_openCard(citation.quote" in focus.group(1), (
        "focusReference no longer opens the card at the clicked quote"
    )
    # The card must actually honour the requested quote rather than always highlighting the first.
    assert "reference.quotes.includes(wanted) ? wanted : reference.quotes[0]" in js
    # ...and the marker must still DO something. A review replaced this function's body with
    # `return;` — killing the whole reported behaviour — and every assertion above still passed.
    marker = re.search(r"function markWantedQuote\(cardBody, quote\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert marker, "markWantedQuote is gone"
    body = marker.group(1)
    assert "is-wanted" in body, "markWantedQuote no longer marks anything"
    # ...and the toggle must be REACHABLE. A token check alone is defeated by an early `return`,
    # which is exactly the mutation an independent review used to gut this function while leaving
    # the token in place. A source-tree test cannot prove reachability in general; asserting the
    # body does not OPEN with an unconditional return catches the whole class that matters here.
    first = next(
        (ln.strip() for ln in body.splitlines()
         if ln.strip() and not ln.strip().startswith(("//", "/*", "*"))),
        "",
    )
    assert not re.match(r"^return\s*;?$", first), f"markWantedQuote returns before it marks: {first!r}"
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    assert ".reference-quote.is-wanted" in css, "the marked quote has no styling to show for it"


def test_an_unverified_reference_explains_itself_rather_than_only_labelling_itself():
    """A user asked what "未通過驗證" means. The answer is narrow and matters: the COORDINATE could
    not be found (invariant 5 verifies coordinates, never faithfulness), so the quote may be fine
    and filed under the wrong address. A label that never says that is a label nobody can act on."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "cite.unverifiedWhy" in js
    assert "reference.reason" in js, "the server's own reason is never shown"
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    assert ".ref-card-why" in css
    # An unverified coordinate matches no block; filtering by it alone would render an empty box.
    assert "blocks.length ? blocks : data.blocks" in js, (
        "an unverified citation's card would show source meta and no passage at all"
    )


def test_a_long_locator_cannot_break_the_reference_row():
    """A locator is MODEL OUTPUT. One run wrote a whole section heading into it, and `flex: none`
    made the chip unshrinkable, so it pushed the rest of the meta row out of the card."""
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    rule = re.search(r"\.reference-locator\s*\{([^}]*)\}", css)
    assert rule, ".reference-locator is gone"
    body = rule.group(1)
    assert "flex: none" not in body, "an unshrinkable locator chip is back"
    assert "min-width: 0" in body and "text-overflow: ellipsis" in body, body


def test_the_chat_bubble_no_longer_carries_the_reasoning_log():
    """The whole point of the drawer. A user reported the expanded steps as unreadable prose taking
    up the answer's space; leaving the log appended would mean shipping the drawer AND the problem
    it was built to remove."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "node.appendChild(logToggle);" in js, "the steps pill is gone entirely"
    # BOTH spellings. A review re-shipped the log with `node.append(log)` and the first version of
    # this test passed — it only knew the name of the method that happened to be used before.
    assert re.search(r"^\s*node\.append(Child)?\(\s*log\s*\)", js, re.MULTILINE) is None, (
        "the inline reasoning log is being appended into the chat again"
    )
    # And the pill must open the drawer rather than unfold in place.
    assert "logToggle.addEventListener(\"click\", () => openTrajectory(runIds));" in js


def test_the_trajectory_drawer_guards_every_hidden_toggled_display():
    """Invariant 36, at the surface most likely to trip it: a drawer is `hidden`-toggled AND needs
    `display: flex` for its own layout, which is exactly the pairing that shipped broken twice."""
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    for cls in (".traj-drawer", ".traj-backdrop", ".traj-note", ".traj-pick"):
        assert re.search(rf"{re.escape(cls)}\[hidden\]\s*\{{[^}}]*display:\s*none", css), (
            f"{cls} is hidden-toggled with no [hidden] guard — the UA rule loses to any author "
            f"display, which is how the modal overlay swallowed every click on the page"
        )


def test_the_timeline_segment_width_tracks_real_time():
    """The strip's only reason to exist. A row of equal segments is a decoration; width
    proportional to `duration_s` is what makes a slow call visible without reading numbers."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    # `flex: <duration> 0 <floor>px` — the sibling's own sizing, and reimplementing it from scratch
    # got it wrong TWICE. Both halves are load-bearing and each fixes the other's failure:
    #   GROW  — a run with ONE tool call fills the strip instead of sitting at a fixed width
    #           beside empty space.
    #   BASIS — a fast call keeps a readable minimum instead of collapsing to a sliver.
    flex = re.search(r"seg\.style\.flex = `([^`]*)`", js)
    assert flex, "timeline segments no longer size themselves"
    assert "${basis}px" in flex.group(1), f"no flex-basis floor: {flex.group(1)}"

    # GROW is the duration NORMALISED by the strip's total, and the normalisation is not cosmetic:
    # CSS distributes free space in proportion to the grow values and STOPS AT THEIR SUM, so four
    # millisecond calls floored to 0.01 each summed to 0.04 and left 96% of the strip empty
    # (reported, with a screenshot). Dividing by the total makes the sum exactly 1 while leaving
    # every ratio between segments untouched.
    assert "weight(entry) / weightTotal" in flex.group(1), (
        f"the grow factor is not a normalised duration: {flex.group(1)}"
    )
    weight = re.search(r"const weight = \(entry\) => ([^;]*);", js)
    assert weight and "entry.duration_s" in weight.group(1), "the weight is no longer the duration"
    assert "0.01" in weight.group(1), "a zero-duration call must still get a share, not vanish"
    assert re.search(r"const weightTotal = line\.reduce\(\(sum, e\) => sum \+ weight\(e\)", js), (
        "the weights are no longer summed, so grow cannot reach 1 and the strip will not fill"
    )
    basis = re.search(r"const basis = ([^;]*);", js)
    assert basis and "TRAJ_SEG_MIN_PX" in basis.group(1), "the floor is gone"
    # ...and the constant must EXIST. An earlier edit landed the use without the declaration and
    # this assertion passed on the spelling alone, while the drawer threw `ReferenceError` on every
    # open. A source-tree test sees names, not bindings, unless it is told to look for both.
    assert re.search(r"^const TRAJ_SEG_MIN_PX = \d+;", js, re.MULTILINE), (
        "TRAJ_SEG_MIN_PX is used but never declared"
    )
    assert "entry.duration_s" in re.search(r"const dur = ([^;]*);", js).group(1)
    # And nothing may pin a width alongside it, which would freeze the grow.
    assert not re.search(r"seg\.style\.width\s*=", js), "a fixed width is back, so grow is dead"


def test_the_replay_dwell_is_the_real_duration_divided_by_speed():
    """"Replay" that steps at a fixed interval is a slideshow. Dwelling for the time a turn really
    took is what makes 1× mean "watch the run happen"."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "trajRealMs(stops[at]) / Math.max(1e-9, trajSpeed)" in js
    # A stop with no live timing must still be walkable, or a finalize-flushed trace replays as
    # nothing at all.
    real = re.search(r"function trajRealMs\(stop\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert real and "TRAJ_NOMINAL_MS" in real.group(1), "an untimed stop is skipped"


def test_the_trajectory_detail_is_built_with_textcontent():
    """Every string in this drawer came out of a model that has been reading source content an
    attacker may have written (invariant 6), and this is the one view that renders raw REPL output
    and tool results. Invariant 29's rule where it matters most."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    field = re.search(r"function trajField\(host, label, value\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert field, "trajField is gone"
    assert "body.textContent = value;" in field.group(1)
    assert "innerHTML" not in field.group(1)


def test_the_interface_language_is_actually_sent():
    """The reading side is pinned in `test_api.py`; the SENDING side was not. A review deleted the
    one line that sets the header and the whole suite stayed green — with the user's original
    report (Chinese interface, English title) fully restored."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    api_fn = re.search(r"async function api\(path, options\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert api_fn, "the api() choke point is gone"
    body = api_fn.group(1)
    assert '"X-RLM-Interface-Language": uiLangName()' in body, body
    # It must reach fetch: building `opts` and then passing `options` sends nothing.
    assert "fetch(path, opts)" in body, body


def test_no_control_carries_both_data_tip_and_title():
    """Invariant 47 replaced the native `title=` with this project's own instant tooltip. Carrying
    both shows the styled tip at 120ms and the OS one on top of it a second later — two tooltips
    for one control, which is the regression that invariant records fixing."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    doubled = re.findall(r'data-tip="[^"]*"\s+title="[^"]*"', html)
    assert not doubled, f"{len(doubled)} controls carry both: {doubled[:3]}"


def test_the_trajectory_backdrop_cannot_eat_clicks_while_it_fades_out():
    """`closeTrajectory` sets `hidden` only after the 280ms slide-out, so without this the backdrop
    stays full-viewport and hit-testable for that window — close the drawer, click a Studio tab,
    and the click is swallowed. The short-lived form of invariant 36's `.modal-overlay` failure."""
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    base = re.search(r"\.traj-backdrop\s*\{([^}]*)\}", css)
    shown = re.search(r"\.traj-backdrop\.is-shown\s*\{([^}]*)\}", css)
    assert base and "pointer-events: none" in base.group(1), base.group(1) if base else "no rule"
    assert shown and "pointer-events: auto" in shown.group(1), "the open backdrop cannot be clicked"


def test_a_live_trajectory_poll_keeps_the_readers_place():
    """The drawer re-fetches every few seconds while a run is live — the one case reading a live
    trace exists to serve. Rebuilding unconditionally sent a reader watching a long podcast back to
    "Start" with an emptied search box every 4 seconds."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    render = re.search(r"function renderTrajectory\(runId\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert render, "renderTrajectory is gone"
    body = render.group(1)
    assert "const priorSel = trajSel;" in body and "trajSearch(priorQuery)" in body, body[-400:]
    assert re.search(r'trajEl\.search\.value\s*=\s*""', body) is None, (
        "the live poll clears the reader's search box again"
    )
    assert 'trajSelect("init", 0);' not in body, "the live poll resets the selection unconditionally"


def test_a_repaint_cannot_delete_the_overviews_progress_and_stop():
    """Adding or removing a source while an overview generates calls `renderChatOverview`, which
    CLEARS `#chat-overview` — the element holding that run's pulsing dot, elapsed counter and its
    only Stop button. Invariant 47's rule broken by a repaint, which is exactly the class invariant
    60 fixed for the pending chat turn.

    Worse than it sounds: `sources:changed` deliberately does not bump `overviewToken` (stranding a
    generation the server already paid for would be the bigger bug), so the run stays live with no
    way to see or stop it until it lands minutes later."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    render = re.search(r"function renderChatOverview\(\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert render, "renderChatOverview is gone"
    body = render.group(1)
    guard = re.search(r"^\s*if \(overviewRunning\) return;", body, re.MULTILINE)
    assert guard, "a repaint can clear the overview panel while a run owns it"
    # The guard must come BEFORE the clear, or it protects nothing.
    assert guard.start() < body.index('el.textContent = ""'), body[:300]

    # ...and every path out of the run must release it, or the panel is frozen forever. A notebook
    # SWITCH matters most: without it the new notebook keeps the old run's status node.
    gen = re.search(r"async function generateOverview\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert gen and gen.group(1).count("overviewRunning = false") >= 3, (
        "not every exit from generateOverview releases the panel"
    )
    switched = re.search(r'store\.on\("notebook:switched", \(\) => \{(.*?)\n  \}\)', js, re.DOTALL)
    assert switched and "overviewRunning = false" in switched.group(1), (
        "switching notebooks leaves the previous run owning the new notebook's overview panel"
    )


def test_a_superseded_overview_note_never_lands_in_another_notebooks_panel():
    """`!live()` covers two different situations. A second press of Generate on the SAME notebook is
    a supersede and should say so; a NOTEBOOK SWITCH means `#chat-overview` now belongs to a
    different notebook, and writing there overwrites ITS overview with a note about a run it never
    started."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    gen = re.search(r"async function generateOverview\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert gen, "generateOverview is gone"
    calls = re.findall(r"supersededNote\(el\)", gen.group(1))
    assert calls, "the supersede note is gone entirely — a dropped response reads as a hang"
    guarded = re.findall(r"if \(generation === notebookGeneration\) supersededNote\(el\)", gen.group(1))
    assert len(guarded) == len(calls), (
        f"{len(calls) - len(guarded)} supersede note(s) can still land in another notebook's panel"
    )


def test_the_overviews_ticker_never_calls_the_whole_action_finished():
    """`/overview` runs TWO tasks and the ticker follows only the summary. Forwarding its terminal
    event made "Finished" the whole action's headline while the FAQ half was still running and the
    POST had not returned — measured live: a 63KB summary trace beside a 226-byte FAQ trace whose
    worker was still alive, with no response yet. The panel sat on "Finished" next to a live Stop.

    Invariant 60's rule ("a status line may not claim something the page is not doing") broken by
    the second RUN rather than by a phase — which is why the fix reuses `setPhase`, the seam that
    invariant added for a stage the trace cannot see."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    gen = re.search(r"async function generateOverview\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert gen, "generateOverview is gone"
    body = gen.group(1)
    ticker = re.search(r"void openTicker\((.*?)\n  \}\);", body, re.DOTALL)
    assert ticker, "the overview ticker is gone"
    hook = ticker.group(1)
    assert "TERMINAL_KINDS.has(event.kind)" in hook, (
        "a terminal event from the summary run reaches the shared status line again, so the panel "
        "says Finished while the FAQ half is still running"
    )
    assert "status.setPhase(" in hook, "the second half is not named"
    # It must RETURN rather than fall through, or the phase is immediately overwritten by the
    # terminal event's own label.
    assert re.search(r"status\.setPhase\([^;]*\);\s*\n\s*return;", hook, re.DOTALL), hook
    # Stop stays available: `runIds` carries both ids and the FAQ run is genuinely cancellable.
    assert "stoppable: false" not in hook, "Stop was disabled for a stage that IS interruptible"


def test_the_chat_composer_is_frozen_while_an_overview_generates():
    """Asked for twice by the user. NOT needed for correctness — the two runs are independent, both
    writes land under the per-notebook lock (invariant 34), and neither repaint can delete the
    other's run (invariants 60, 71) — but a question asked into a thread whose overview is being
    rewritten reads as two things fighting, whether or not they are.

    The COMPOSER only. Clearing the conversation was offered as an alternative and is the one thing
    not to do: it would destroy history to signal a transient state."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    gen = re.search(r"async function generateOverview\(\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert gen, "generateOverview is gone"
    body = gen.group(1)
    assert 'store.emit("chat:pending", { pending: true })' in body, "the composer is never frozen"
    # Every exit must thaw it, or one failed generation locks the composer for the session.
    releases = body.count('store.emit("chat:pending", { pending: false })')
    assert releases >= 3, f"only {releases} of the exits thaw the composer (need cancel/ok/error)"
    # ...including a notebook switch, which strands the run rather than ending it.
    switched = re.search(r'store\.on\("notebook:switched", \(\) => \{(.*?)\n  \}\)', js, re.DOTALL)
    assert switched and 'pending: false' in switched.group(1), (
        "switching notebooks leaves the new notebook's composer frozen by the old run"
    )
    # The THREAD is never cleared — history must not be destroyed to signal a transient state.
    assert "state.turns = []" not in body and "history.textContent" not in body


def test_both_steps_pills_open_the_trajectory_drawer():
    """There are TWO "⌁ N steps" affordances and they are different components: `runStatus`'s LIVE
    log during a run, and `renderTickerAffordance`'s PERSISTED pill under a finished artifact (a
    chat answer, the overview, a Guide result, the podcast).

    Moving only the live one into the drawer left the persisted one still expanding the model's
    reasoning prose inline — a user hard-reloaded, pressed it, and reported the drawer as missing.
    It was a different component, and the first diagnosis (a stale cached `app.js`) was wrong.
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")

    # The live one.
    assert 'logToggle.addEventListener("click", () => openTrajectory(runIds));' in js

    # The persisted one — and it must not rebuild an inline log of its own.
    fn = re.search(r"function renderTickerAffordance\(runId\)\s*\{(.*?)\n\}", js, re.DOTALL)
    assert fn, "renderTickerAffordance is gone"
    body = fn.group(1)
    assert "openTrajectory([runId])" in body, (
        "the persisted steps pill no longer opens the drawer — it is the one a reader presses on a "
        "finished answer, which is most of the time"
    )
    assert "ticker-detail" not in body, "the inline reasoning panel is back under finished artifacts"
    assert "ticker-row" not in body, "the flat event rows are back"
    # Nothing may be left styling an element nobody builds.
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    assert not re.search(r"\.ticker-detail\s*\{", css), "dead CSS for a removed element"
    assert not re.search(r"\.ticker-row\s*\{", css), "dead CSS for a removed element"


def test_a_timeline_segment_cannot_clip_its_own_label():
    """`.seg` is a fixed-height box with `overflow: hidden` and three stacked lines. Left to the
    browser's ~1.5 default line-height they measured 74.3px inside a 72px box, so the MIDDLE line —
    the label — was sliced through the letterforms. Reported from a screenshot showing
    "skill corpus-navigation" cut in half.

    Arithmetic, not taste: the height is the constraint, so every line has to declare what it costs.
    """
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    box = re.search(r"\.traj-timeline\s*\{([^}]*)\}", css)
    assert box, ".traj-timeline is gone"
    height = re.search(r"height:\s*(\d+)px", box.group(1))
    assert height, f"the timeline no longer sets a height: {box.group(1)}"

    total = 0.0
    for cls, size in (("seg-ic", None), ("seg-lab", None), ("seg-dur", None)):
        rule = re.search(rf"\.{cls}\s*\{{([^}}]*)\}}", css)
        assert rule, f".{cls} is gone"
        font = re.search(r"font-size:\s*([\d.]+)rem", rule.group(1))
        lh = re.search(r"line-height:\s*([\d.]+)", rule.group(1))
        assert font and lh, (
            f".{cls} must declare BOTH font-size and line-height — an undeclared line-height "
            f"defaults to about 1.5 and is what overflowed the box: {rule.group(1)}"
        )
        total += float(font.group(1)) * 16 * float(lh.group(1))

    seg = re.search(r"\.seg\s*\{([^}]*)\}", css)
    pad = re.search(r"padding:\s*(\d+)px", seg.group(1))
    gap = re.search(r"gap:\s*(\d+)px", seg.group(1))
    total += 2 * int(pad.group(1)) + 2 * int(gap.group(1))
    assert total <= int(height.group(1)), (
        f"a segment's content measures {total:.1f}px inside a {height.group(1)}px box — "
        f"`.seg`'s own overflow:hidden will slice a line in half"
    )


def test_the_empty_initial_state_says_which_empty_it_is():
    """An empty panel reads as broken, so the empty state has to name itself — and there are TWO
    live causes, neither of which is "an old trace", which was only the first one anybody hit.

    `_run_isolated` reserves the trace file exclusively BEFORE spawning and `run_trajectory` stops
    at a torn final line, so a run opened in its first moments — or one whose spawn failed, or one
    killed instantly — has a real file with zero events. That branch stays reachable no matter how
    many old traces are deleted, which is exactly why the wording must not name a historical cause
    a reader can no longer hit."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "trajData.started_at" in js, "the two empty states are no longer distinguished"
    for key in ("traj.noMeta", "traj.notStarted"):
        assert f'"{key}"' in js, f"{key} is gone"
    # A run that never started must NOT be described as one that merely lacks configuration.
    at = js.index('"traj.notStarted"')
    assert "still be starting" in js[at : at + 300], js[at : at + 300]
    i18n = (WEB / "i18n.js").read_text(encoding="utf-8")
    for key in ("traj.noMeta", "traj.notStarted"):
        assert f'"{key}":' in i18n, f"{key} is not translated"
    # The retired wording named a cause that deleting old traces makes unreachable.
    assert "noMetaWhen" not in js and "noMetaWhen" not in i18n


def test_only_the_last_turn_offers_to_be_regenerated():
    """Every later answer was produced with this one in its `history` (invariant 11), so redoing a
    turn in the middle would leave the answers after it derived from a conversation that no longer
    exists. The server re-checks the same thing inside its lock; this is the affordance half.

    A stylesheet rule rather than a flag passed into `renderTurn`, because turns reach the DOM
    through TWO paths — `rebuildHistory` and the `chat:turnAdded` replay — and a rule that reads the
    DOM is right for both. The same mechanism `.turn-followups` already uses."""
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    assert re.search(r"\.turn:not\(:last-child\)\s+\.turn-regenerate\s*\{[^}]*display:\s*none", css), (
        "a mid-thread answer can be regenerated, invalidating every answer after it"
    )
    # ...and never while a question is in flight.
    assert re.search(
        r"\.turn-answer\.is-pending\s+\.turn-regenerate\s*\{[^}]*display:\s*none", css
    ), "the pending row offers to redo an answer that does not exist yet"
    # `display` here is author CSS on a class that is NOT hidden-toggled, so invariant 36's pairing
    # does not apply — but it must stay that way, or the guard is needed.
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert ".turn-regenerate" not in js, "the class is hidden-toggled in JS now; it needs [hidden]"


def test_regenerating_a_turn_goes_through_the_same_flow_as_asking():
    """The pending row, the live ticker, the Stop button, the cancel path and the
    rebuild-from-the-server's-record are what would drift between two copies — and this file has
    already paid for a duplicated affordance once, with the two "N steps" pills."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    assert "async function askQuestion(question, { regenerate = false } = {})" in js
    # The composer and the button are both entry points into it, and only one of them clears input.
    assert "void askQuestion(question);" in js
    assert "askQuestion(question, { regenerate: true })" in js
    # The flag has to REACH the server, or the turn is appended and the thread grows a duplicate.
    body = re.search(r"body: JSON\.stringify\(\{ question[^}]*\}\)", js)
    assert body and "regenerate" in body.group(0), body


def test_regenerate_replaces_only_a_matching_last_turn():
    """Server-side half. Checked inside the lock against the notebook as it is THEN, because the
    snapshot the handler read may be minutes old — and a request that arrives after someone else
    asked something new must append rather than overwrite a turn it did not mean to.

    Read as TEXT rather than through `inspect.getsource(api.ask)`, because importing `api` needs
    the `api` extra: this file is source-tree assertions and every other test in it runs on a bare
    `uv sync`. Importing made this one FAIL rather than be absent without the extra, which is
    sharper than the trap CLAUDE.md's Verify section records and misreports a missing dependency as
    a broken feature.
    """
    api_src = (Path(__file__).resolve().parent.parent / "rlm_notebook" / "api.py").read_text(
        encoding="utf-8"
    )
    src = api_src[api_src.index("async def ask(") :]
    persist = src[src.index("def _persist(") : src.index("await _mutate_or_http(notebook_id, _persist")]
    assert "body.regenerate" in persist and "nb.turns[-1].question == body.question" in persist, persist
    assert "nb.turns[-1] = turn" in persist and "nb.turns.append(turn)" in persist, persist


def test_the_clear_conversation_control_appears_only_when_there_is_one():
    """A destructive control offered on an empty thread is an invitation to nothing. It is also the
    only way to undo a turn in the MIDDLE — regenerate deliberately reaches the last one only."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    # The DIRECTION, as a whole expression rather than as tokens that happen to appear. An
    # independent review inverted the condition (`.length > 0`) and the suite stayed green: every
    # substring the first version checked was still present, just saying the opposite.
    assert re.search(
        r"clearBtn\.hidden\s*=\s*!state\.notebookId\s*\|\|\s*!\(state\.turns", js
    ), "the visibility condition no longer hides the control on an empty thread"

    # ...and the WIRING. The same review deleted every call site — leaving `#chat-clear` with the
    # `hidden` attribute it is born with, so the feature was entirely dead — and the suite stayed
    # green too. Both are invariant 60's own recorded lesson: a substring assertion is not a
    # behavioural one.
    #
    # FIVE sites: the three handlers below, the clear handler's own re-sync after it empties the
    # thread, and the initial paint at the tail of `initChatPanel`. An exact count rather than a
    # floor, so DELETING one fails here — adding a sixth is a deliberate edit to this number.
    assert js.count("syncClearBtn();") == 5, (
        f"syncClearBtn is called from {js.count('syncClearBtn();')} places, expected 5 — the three "
        f"handlers, the clear handler's own re-sync, and the initial paint"
    )
    # Scoped to `initChatPanel`: `notebook:switched` is subscribed in FOUR init functions, and an
    # unscoped search matched the source viewer's one — a test that reads "the handler" has to say
    # WHICH handler in a file where several spell the same event.
    panel = js[js.index("function initChatPanel()") : js.index("\nfunction renderGuideContent")]
    for event in ("chat:turnAdded", "chat:rerender", "notebook:switched"):
        handler = re.search(rf'store\.on\("{event}",(.*?)\n  \}}\);', panel, re.DOTALL)
        assert handler and "syncClearBtn();" in handler.group(1), (
            f"initChatPanel's {event} handler no longer re-syncs the clear control"
        )

    # Clearing while a question runs would delete the turns and then let `ask`'s own persist append
    # the answer to the empty list — the conversation comes back with one entry.
    pending = re.search(r'store\.on\("chat:pending", \(\{ pending \}\) => \{(.*?)\n  \}\);', js, re.DOTALL)
    assert pending and "clearBtn.disabled = pending" in pending.group(1), (
        "the clear control is live during an in-flight question"
    )
    # Destructive and irreversible, so it confirms — and names what SURVIVES, since losing sources
    # is what a reader would fear from a control in the chat panel.
    at = js.index('"chat.clearConfirm"')
    assert "Sources, notes and the overview are kept" in js[at : at + 300], js[at : at + 300]
    i18n = (WEB / "i18n.js").read_text(encoding="utf-8")
    at = i18n.index('"chat.clearConfirm"')
    assert "保留" in i18n[at : at + 200], "the Chinese confirmation drops what survives"


def test_a_tip_on_a_left_edge_control_opens_rightward():
    """`[data-tip]::after` anchors `right: 0` by default, so a 15rem panel on a control at the LEFT
    edge of a scroller extends off it — and `.chat-history` is `overflow-y: auto`, which computes
    `overflow-x` to `auto` too. Photographed by a user: a tip arriving with its first characters
    sliced off.

    Removing the tips was the first instinct and the wrong one. Invariant 54's ancestor case cannot
    always be fixed, but when the clipping is HORIZONTAL and the control sits at the left edge, it
    always can — anchor the tip into the space the control actually has, which this file already
    does for `.src-flags`."""
    css = _strip_css_comments((WEB / "style.css").read_text(encoding="utf-8"))
    for sel in (r"\.ticker-toggle\[data-tip\]::after", r"\.turn-regenerate \[data-tip\]::after"):
        rule = re.search(rf"{sel}[^{{]*\{{([^}}]*)\}}", css)
        assert rule, f"{sel} has no anchor override — its tip is clipped by the chat scroller"
        assert "left: 0" in rule.group(1) and "right: auto" in rule.group(1), rule.group(1)


def test_no_translated_string_carries_an_english_dash():
    """The English copy uses `—` as a rhetorical break; carrying it into the Chinese table is a
    translation artifact, not a translation. A user reported one rendering as a long rule that read
    like a glyph run that had failed to resolve.

    Three spellings had accumulated in one file — `——`, a SPACED `——` (the dash is already
    full-width; the spaces are the English habit) and a half-width `—`. Chinese punctuation carries
    the same joins: a comma continues, a semicolon separates two complete thoughts, a colon labels.

    Scoped to the STRING TABLE. The file's own comments are English prose and keep their dashes,
    which is why this reads values rather than lines.
    """
    src = (WEB / "i18n.js").read_text(encoding="utf-8")
    body = src[src.index("const STRINGS = {") : src.index("const UI_LANG_KEY")]
    offenders = [
        line.strip()
        for line in body.splitlines()
        if "—" in line and not line.lstrip().startswith("//")
    ]
    assert not offenders, (
        f"{len(offenders)} translated string(s) still carry an English dash: {offenders[:3]}"
    )


def test_an_unrecorded_token_budget_never_renders_as_no_truncation():
    """`budget === null` means the trace predates rlm-harness 1.10.0 and carries no budget fields
    at all. It must render as NOT RECORDED, never as a zero or a clean bill of health — reading an
    absent field as "nothing was truncated" is how a corpus boundary gets mistaken for a property
    of the code, which is the one thing CHANGELOG.md forbids about this upgrade.

    A source-tree assertion because there is no JS test runner (invariant 36): the falsy branch has
    to come FIRST, before anything reads `.truncated` off a null.
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")
    body = js[js.index("function renderTrajBudget(") : js.index("function renderTrajectory(")]

    none_at = body.index("if (!budget)")
    assert none_at < body.index(".truncated"), "the null check must precede any field read"
    assert "traj.budgetNone" in body[none_at : body.index("else if")], (
        "the not-recorded branch must use its own string, not the healthy one"
    )
    # The string itself has to deny the wrong reading, in both tables.
    assert "Not the same as" in body
    zh = (WEB / "i18n.js").read_text(encoding="utf-8")
    assert "這不等於" in zh[zh.index('"traj.budgetNone"') : zh.index('"traj.budgetNone"') + 200]


def test_a_missing_trajectory_clears_the_previous_runs_panes():
    """`renderTrajectory` writes the task name, both notes and the axis end; the fetch-failure path
    does not run it. Clearing only the step/detail/timeline panes left the PREVIOUS run's timing
    note and token budget on screen beside a "no trajectory" line, reading as facts about the run
    that has none.

    A source-tree assertion because there is no JS test runner (invariant 36).
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")
    catch = js[js.index("    trajData = null;") : js.index("  trajShowDrawer();")]

    for pane in ("steps", "detail", "timeline", "name", "axisEnd"):
        assert f'trajEl.{pane}.textContent = ""' in catch, f"trajEl.{pane} keeps the last run's text"
    # The two notes are BOXES, not bare text: emptying one leaves its border and padding drawn, so
    # each has to be hidden as well as cleared.
    for note in ("note", "budget"):
        assert f'trajEl.{note}.textContent = ""' in catch, f"trajEl.{note} keeps its text"
        assert f"trajEl.{note}.hidden = true" in catch, f"trajEl.{note} is emptied but still drawn"


def test_an_unloadable_trajectory_drawer_is_sized_to_its_content():
    """One sentence in an 80vh panel reads as a broken drawer rather than a missing trace."""
    js = (WEB / "app.js").read_text(encoding="utf-8")
    css = (WEB / "style.css").read_text(encoding="utf-8")

    assert 'classList.toggle("is-empty", !trajData)' in js, "the class must track the DATA"
    rule = re.search(r"\.traj-drawer\.is-empty\s*\{([^}]*)\}", css)
    assert rule, "no .traj-drawer.is-empty rule"
    # Both, or the fixed `max-height: 80vh` on the base rule still wins.
    assert "height: auto" in rule.group(1) and "max-height" in rule.group(1), rule.group(1)


def test_a_steps_pill_on_a_traceless_run_does_not_open_an_empty_drawer():
    """A transport, a search box and an empty timeline wrapped around one sentence reads as a
    broken drawer rather than a missing trace. The fetch already happens BEFORE the drawer is
    shown, so the closed case can simply say so and leave the page alone — via `alert`, which is
    how rename, save-settings and add-source already report an unfulfillable click.

    Switching runs inside an ALREADY-OPEN drawer takes the other branch: it cannot close under the
    reader, so it clears every pane instead.
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")
    start = js.index("  } catch (err) {\n    // A trace is only as durable")
    catch = js[start : js.index("  if (trajData) renderTrajectory(runId);")]

    assert "if (trajEl.drawer.hidden)" in catch, "the two situations must be told apart"
    closed = catch[catch.index("if (trajEl.drawer.hidden)") : catch.index("trajEl.stat.textContent")]
    assert "alert(" in closed and "return;" in closed, "a closed drawer must report and not open"
    assert "trajShowDrawer" not in closed


def test_a_reported_cap_with_no_usage_is_its_own_state():
    """Four states, not three. A provider that returns no `usage` block leaves `cap` set and
    `peak_completion` null — collapsing that into the no-cap branch made the drawer say no cap was
    reported for a run that had one, which is the same "an absent field is not a zero" error the
    test above exists to prevent, one branch over.

    Pinned by ORDER and by SUBJECT, not by token presence (invariant 60): the two-field branch has
    to come before the cap-only branch, or a run with both would take the weaker one.
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")
    body = js[js.index("function renderTrajBudget(") : js.index("function renderTrajectory(")]

    both = body.index("budget.cap != null && budget.peak_completion != null")
    cap_only = body.index("} else if (budget.cap != null) {")
    assert both < cap_only, "the both-fields branch must be tested before the cap-only one"
    assert "traj.budgetNoUsage" in body[cap_only:], "the cap-only state needs its own string"
    assert "traj.budgetPartial" in body[body.index("} else {", cap_only) :], (
        "the no-cap fallback must keep the partial string rather than inheriting the new one"
    )


def test_a_dropped_step_budget_never_overwrites_the_truncation_colour():
    """A run can BOTH hit the generation cap and have its step budgets rejected. The `dropped`
    notice is appended, and its tone assignment must preserve `is-cut` — the colours exist to keep
    "a turn was cut off" separable from "the caps did not apply", and an unconditional
    `tone = "is-info"` erased the first the moment the second was also true.

    The DIRECTION of the conditional is the assertion, since a mutation to a constant leaves every
    token in place.
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")
    body = js[js.index("function renderTrajBudget(") : js.index("function renderTrajectory(")]

    dropped = body.index("iterations.dropped")
    tail = body[dropped:]
    assert 'tone === "is-cut" ? "is-cut"' in tail, (
        "the dropped notice must preserve a truncation tone rather than overwriting it"
    )
    # And it appends: replacing the note would drop the sentence explaining what was truncated.
    assert tail.index("appendChild") < tail.index("tone ="), (
        "the notice is appended before the tone is adjusted, never in place of the first note"
    )


def test_no_stylesheet_fallback_hardcodes_a_colour():
    """`var(--x, <hex>)` is how a typo'd token ships looking healthy: the fallback renders, so
    nothing is visibly broken, and the value silently ignores all three theme blocks. A live
    example was `var(--danger, #d9534f)` where the defined token is `--bad` — `--danger` is
    assigned nowhere in the tree, so every theme got one hardcoded red.

    Stated as a property of the FALLBACK rather than as a list of known-good token names, because
    the failure is "a colour that cannot follow the theme", not "this particular typo".
    A non-colour fallback (a font stack, a width) is fine and several are deliberate.
    """
    css = (WEB / "style.css").read_text(encoding="utf-8")
    hardcoded = re.findall(r"var\(\s*(--[\w-]+)\s*,\s*(#[0-9a-fA-F]{3,8}|rgba?\([^)]*\))", css)
    assert not hardcoded, f"hardcoded colour fallbacks bypass the theme blocks: {hardcoded}"

    # The guard is only worth having if the tokens it protects are really defined per theme.
    for token in ("--bad", "--warn", "--accent"):
        assert len(re.findall(rf"^\s*{token}\s*:", css, re.MULTILINE)) >= 3, (
            f"{token} must be defined in every theme block, or a reference to it is theme-blind"
        )


def test_a_regenerate_asks_for_a_fresh_run_and_a_first_generate_does_not():
    """`dspy.LM` defaults to `cache=True`. A user pressed Regenerate on an unchanged notebook and
    got a run with ZERO model calls in 3.4 seconds that replayed the previous one byte-identically
    — same turns, same reasoning text, the same two validator failures — while the drawer honestly
    reported no usage and no per-turn timing, which reads as a broken panel.

    A button labelled Regenerate that returns what you already had is a UI that lies. A FIRST
    generate keeps the cache, where a hit is a free correct answer, so the flag is the EXISTENCE of
    the artifact rather than a constant.
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")

    # Anchored on the REQUEST, not on the path: `/overview` appears in three comments first, and a
    # first version of this test read one of those and failed against correct source.
    for surface, artifact in (
        ("}/overview`, {", "state.overview"),
        ("}/audio`, {", "state.podcast"),
    ):
        at = js.index(surface)
        body = js[at : at + 900]
        assert f"fresh: Boolean({artifact})" in body, (
            f"the {surface} request must send fresh keyed on {artifact}, not a constant: {body[:300]}"
        )
        # Keyed on the artifact, never hardcoded — either constant is a different bug.
        assert "fresh: true" not in body and "fresh: false" not in body, body[:300]


def test_a_tool_segment_offers_a_way_back_to_the_turn_that_called_it():
    """The detail head already NAMES the owning turn, and naming a turn a reader then has to find
    in the nav by eye is the two-lists-to-correlate problem the strip's turn marks exist to remove.

    On EVERY attributed segment, not only a failed one — "why was this called" is the same question
    whether or not it worked — and absent when nothing is attributed, since a button reading "open
    turn null" is worse than no button (a sibling project shipped that and said so).
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")
    at = js.index("traj.openTurn")
    around = js[at - 700 : at + 500]

    # Guarded on ATTRIBUTION, not on failure.
    assert "entry.turn_index != null" in around, around
    assert "entry.ok" not in around, "the jump must not be limited to failures"
    # It selects the TURN, not the tool it was opened from.
    assert 'trajSelect("turn", entry.turn_index)' in around, around
    # Translated, or a Chinese drawer grows an English button (invariant 48's tripwire covers the
    # key; this asserts the literal is not left bare at the call site).
    assert 'Open turn ${entry.turn_index + 1}' in around, around


def test_the_strip_numbers_turns_the_way_every_other_surface_does():
    """The nav rail says "Turn 3", the detail head says "Turn 3", and the strip's mark said `T2`
    for the same call — the trace data is 0-indexed and only the strip forgot to add one.

    Pinned as the EXPRESSION, not as the token: `entry.turn_index` appears either way, and the
    whole defect was the missing `+ 1`.
    """
    js = (WEB / "app.js").read_text(encoding="utf-8")

    mark = re.search(r"markLabel\.textContent = `T\$\{([^}]*)\}`", js)
    assert mark, "the turn mark no longer labels itself"
    assert mark.group(1).strip() == "entry.turn_index + 1", (
        f"the strip is numbering turns from zero again: {mark.group(1)}"
    )
    # ...and the two panes it has to agree with.
    assert "`Turn ${entry.turn_index + 1}`" in js
    assert "`\\u2191 Open turn ${entry.turn_index + 1}`" in js
