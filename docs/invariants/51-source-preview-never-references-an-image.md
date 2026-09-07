# Invariant 51 — Source preview never references an image

**`Source.preview` is display-only page metadata, scraped from html already in hand, and it NEVER
references an image.** `parsers/web.extract_preview` reads og:/twitter:/`description`/`<title>` out
of the SAME html `parse_web` already fetched — one host-side request per source, as invariant 1
requires; a preview that fetched anything of its own would quietly break that. The corpus blob is
built from `blocks` alone, so a page controlling its own `<meta>` tags influences what a Sources row
LOOKS like and nothing the model reads — the same trust level `origin` already carries, rendered
with `textContent` for the same reason.

**`og:image` is deliberately absent, and adding it back looks like an obvious improvement.**
Rendering one makes the READER's browser fetch a URL the page author chose, handing that third party
the reader's IP and a request to log — every pasted link becomes a beacon, in exchange for a
thumbnail. Pinned by a test. Regex rather than an HTML parser because the point is to add no
dependency to an ingestion path where `trafilatura` already does the real work; a malformed match is
a cosmetic miss, never a hazard.

**Every quantifier in those patterns is BOUNDED and the input is windowed to the `<head>`, and both
are load-bearing.** With an unbounded `[^>]*?`, a page of UNCLOSED `<meta` tags backtracks
catastrophically — cubic, and `re` does NOT release the GIL, so `asyncio.to_thread` buys the event
loop nothing. On a no-auth API where any caller can paste any URL, that is a one-request freeze of
the whole server.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
