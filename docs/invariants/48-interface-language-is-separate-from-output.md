# Invariant 48 — Interface language is separate from output

**The INTERFACE language (`web/i18n.js`) is a browser preference, deliberately separate from the
OUTPUT language (invariant 39, a server setting).** One decides what the buttons say, the other
what the model writes. A reader in Taiwan may well want a Chinese interface over English papers,
and folding the two together makes that combination unexpressible — so the UI language lives in
`localStorage` and the settings page carries both, on separate rows, saying which is which.

**The separation is NOT isolation**: the chosen interface language IS sent on every request and
DOES reach a prompt (invariant 69). What survives is that they are two settings with two rows, and
an explicit output language still wins outright.

**`STRINGS.en` is EMPTY on purpose.** English is whatever `index.html` and `app.js` already say:
static markup carries `data-i18n`/`-title`/`-placeholder`/`-tip` and keeps its own text as the
fallback, and every `t(key, fallback)` call passes its English at the call site. So there is no
English table to drift out of sync with a translation nobody updated. A tripwire fails the build on
a bare `t("key")` (which would render the KEY to an English reader) and a second one on a key used
but not translated, because a typo is otherwise invisible — `t()` falls back and the interface
silently stays half-English.

**`zh-CN`/`zh-Hans` deliberately does NOT resolve to the Traditional table** — shipping Traditional
text to a Simplified reader is worse than leaving it in English. Detection is `localStorage` →
`navigator.languages` → English.

**A language change re-renders** rather than threading a language argument through every renderer:
`setUiLang` re-applies the static markup and dispatches `ui-lang-changed`. A renderer added later is
translated by construction instead of by somebody remembering to subscribe.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
