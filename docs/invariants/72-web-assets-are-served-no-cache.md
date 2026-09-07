# Invariant 72 — Web assets are served no-cache

**The web assets are served `Cache-Control: no-cache`, because a zero-build app has no other way to stop
a browser running last week's JavaScript.** Starlette's `StaticFiles` sends `ETag` and `Last-Modified`
and NO `Cache-Control`, leaving the browser on heuristic caching — free to reuse a stale copy without
asking — and invariant 29's zero-build choice means the filenames carry no content hash either, so there
is no cache-busting URL to fall back on. This rests on the MECHANISM, not on the bug report that
prompted it (which turned out to be invariant 70's second steps pill).

**`no-cache` is NOT `no-store`.** The copy stays in the cache and the ETag short-circuits the transfer,
so an unchanged asset costs one conditional request and a 304 with no body. `no-store` would turn every
navigation into a full re-download of a ~190KB script, which is why the test asserts the ETag and the
304 as well as the header.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
