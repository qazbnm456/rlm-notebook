# Invariant 2 — SSRF guard revalidated per redirect

**`parsers/web.py` re-validates the SSRF guard on EVERY redirect hop, not just the requested
URL.** `_SafeRedirectHandler` runs `is_safe_url`/`resolved_host_is_safe` again on each
`Location` target before following it. Without this, an initially-safe-looking URL could 302 to
an internal/loopback/metadata address and the default `urllib` opener would follow it unchecked.
Do not swap back to plain `urllib.request.urlopen`.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
