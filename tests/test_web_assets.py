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
    for var, element_id in re.findall(r'(?:const|let)\s+(\w+)\s*=\s*document\.getElementById\("([\w-]+)"\)', js):
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

    # A self-check on the EXTRACTION, one per route: if any route silently stops matching, this
    # fails loudly instead of the whole test passing vacuously — which is exactly how the first
    # version of this file reported "ok" for a class that was broken at the time.
    for expected in (
        "modal-overlay", "ticker-detail", "empty-note", "tab-body", "run-log-toggle", "studio-view"
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
    # The UI language lives in localStorage and is never sent anywhere.
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
    """A scrolling log is the noise the user asked to avoid; `nuclei-forge/studio` settled on typed
    counters plus one current-activity line, and its own comment explains why the framing matters.
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
    is an XSS sink; `bugcademy` states the same exception for the same reason."""
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
    button_at = body.index("chat.regenerateOverview")
    assert "if (offerRegenerate)" in body[button_at - 300 : button_at]


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
