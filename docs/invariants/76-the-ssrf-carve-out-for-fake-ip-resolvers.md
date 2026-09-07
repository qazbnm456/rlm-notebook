# Invariant 76 — The SSRF carve out for fake IP resolvers

**The SSRF guard's DNS half is handed an operator-supplied carve-out (`RN_FETCH_ALLOW_CIDRS`),
resolved in ONE place (`web.allow_nets`) that both host-side fetchers read — because full strictness
is WRONG on a fake-IP resolver, and silently so.**

A split-DNS VPN or fake-IP proxy (Clash / Mihomo / Surge, default range `198.18.0.0/16`) answers
every public hostname with a synthetic address in a RESERVED range. `resolved_host_is_safe` then
refuses it — **correctly, on the information it has** — and EVERY web and YouTube ingestion on that
machine fails with "resolves to a disallowed address". The guard is not buggy; it cannot tell an
operator's own lying resolver from an attacker's redirect, which is exactly why the carve-out has to
be opt-in and operator-supplied rather than inferred.

**The carve-out reaches ONLY the DNS-rebinding half.** `is_safe_url` is syntactic, runs first, and is
never given `allow_nets`, so no value — `0.0.0.0/0` included — makes a loopback or cloud-metadata URL
fetchable. A reader could reasonably assume an allow-list is an allow-list, so a test pins it.

**One copy, not two.** `parsers/youtube.py` has its own `_check_caption_url_safe` and imports
`web.allow_nets` rather than re-reading the variable, so the two host-side fetchers can never
disagree about what is permitted — invariant 13's one-copy rule applied to a guard. Pinned by a
source-tree assertion, since observing it needs a live fetch.

**Resolved per call, never cached at import.** A module-level constant would freeze whatever the
environment held when `web.py` was first imported, which a test cannot then change and a
long-running server cannot pick up. `parse_cidrs` on a one- or two-entry tuple costs nothing beside
a network fetch.

**`config.fetch_allow_cidrs` is a standalone reader, deliberately NOT a `NotebookConfig` field**, for
invariant 30's reason one path further: `from_env()` raises `SystemExit` whenever `RN_MAIN_MODEL` is
unset, and ingesting a URL has nothing to do with whether a model is configured — `add_sources` never
calls `_config()` at all.

**An unparseable entry RAISES rather than being skipped, which deliberately inverts upstream's own
policy.** `rlm_harness.tools.parse_cidrs` warns and drops one so a typo "can't sink a run" — right
for a tool the model calls mid-run, wrong for an operator setting read once at the boundary: dropping
the only entry restores full strictness, so a typo'd variable reproduces the exact symptom the
variable was set to fix, with nothing on screen connecting the two. Same reasoning as `_env_int`
raising, and as the lifespan refusing startup on a malformed `RN_TRACE_RETENTION_DAYS` rather than
warning and defaulting.

**That `SystemExit` is invariant 24's documented trap, and it was live.** `add_sources` caught
`(FetchError, ValueError, OSError)` around ingestion and nothing else, so a malformed variable would
have escaped a request handler as an unhandled 500. Invariant 24 says in as many words that its RULE
is the invariant and not the list of places it currently applies, and that any standalone config
reader a handler calls needs the same treatment; this is that.

**The refusal message names the variable.** The failure is indistinguishable from a genuine SSRF
refusal otherwise, and the whole difficulty here was that nothing connected the symptom to the cause.

**How it was found matters, because it was misread first.** This was a standing `pytest` failure on
the developer's own machine — `test_default_fetcher_uses_the_guarded_opener_never_plain_urlopen` —
reported for three consecutive runs as "pre-existing and unrelated: a sandbox artifact". It was
neither: the test does live DNS (violating the suite's stated "fully offline" property), and it was
correctly reporting that the product refused every URL on that machine. **A test that fails on one
developer's machine and passes in CI is evidence about the product until someone proves otherwise.**
The test is hermetic now, and still kills the mutation it exists to catch.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
