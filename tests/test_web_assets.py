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

    # (a) createElement + className, then `<var>.hidden = …` on the same variable.
    for var, class_expr in re.findall(r"(?:const|let)\s+(\w+)\s*=\s*document\.createElement\([^)]*\);?\s*\n\s*\1\.className\s*=\s*([^;\n]+)", js):
        if re.search(rf"\b{re.escape(var)}\.hidden\s*=", js):
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

    # A self-check on the EXTRACTION, one per route: if any route silently stops matching, this
    # fails loudly instead of the whole test passing vacuously — which is exactly how the first
    # version of this file reported "ok" for a class that was broken at the time.
    for expected in ("modal-overlay", "ticker-detail", "empty-note", "tab-body"):
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
