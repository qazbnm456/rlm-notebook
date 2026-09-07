# Invariant 69 — Interface language signals output language

**The INTERFACE language is a SIGNAL to output-language resolution — a fourth one, ranked above
`Accept-Language` — which narrows invariant 48 without merging it.** A user running a Chinese interface
got an English notebook title, because the one place they had actually SAID which language they read
was invisible to `naming.SuggestLanguage`.

**Chosen beats inherited.** `Accept-Language` comes from the operating system; the interface language
was picked in this app. That ordering is the whole justification, and it is the same reasoning invariant
39 uses to weight typed questions highest. Invariant 48's separation survives: two rows on the settings
page, and an explicit output-language setting still wins outright.

**Carried in a header (`X-RLM-Interface-Language`), added once in `app.js`'s `api()`** —
`_resolve_language` is reached from every run-taking endpoint, so a body field would be five schema
changes and a sixth one forgotten. **The value sent is the language's ENGLISH NAME, not `zh-Hant`**: the
model answers in English language names, so sending a code or a word in the very language it is
identifying makes it parse rather than weigh.

**A proper noun is never translated (`instructions.PROPER_NOUNS`)** — translating the WORD hands a
reader a term they cannot search for, which is the opposite of what a research notebook is for.
Composed into BOTH `chat_language_rule` and `artifact_language_rule` from one constant (invariant 13),
plus the title prompt, which is a plain `dspy.Predict` and shares nothing. This generalises invariant
45's reversal from the podcast to every artifact a reader might search from.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
