# Invariant 76 — The SSRF carve-out for fake-IP resolvers

**The SSRF guard's DNS half is handed an operator-supplied carve-out (`RN_FETCH_ALLOW_CIDRS`),
resolved in ONE place (`web.allow_nets`) that both host-side fetchers read.** Full strictness is
WRONG on a fake-IP resolver, and silently so.

A split-DNS VPN or fake-IP proxy (Clash / Mihomo / Surge, default range `198.18.0.0/16`) answers
every public hostname with a synthetic address in a RESERVED range. `resolved_host_is_safe` then
refuses it — **correctly, on the information it has** — and EVERY web and YouTube ingestion on that
machine fails with "resolves to a disallowed address". The guard is not buggy; it cannot tell an
operator's own lying resolver from an attacker's redirect, which is exactly why the carve-out has to
be opt-in and operator-supplied rather than inferred.

**A value that would disable the guard is REFUSED, and that check is what makes this invariant's
guarantee true.** `allow_nets` short-circuits every property `resolved_host_is_safe` tests —
loopback, private, link-local, reserved, unspecified, multicast — so a wide value does not widen the
carve-out, it turns the DNS-rebinding defence off. `config._NEVER_ALLOWED` therefore refuses any
entry overlapping those ranges, so `0.0.0.0/0`, `::/0` and RFC1918 cannot be configured at all.

**`is_safe_url` is NOT the backstop, and believing it was is how this shipped wrong the first time.**
It refuses a URL whose host is a LITERAL blocked IP, and returns True for `http://evil.example.com/`
however that name resolves — so it never sees the resolved address, and the DNS-rebinding check is
the only layer that does. The first version of this invariant claimed "no value makes a loopback or
cloud-metadata URL fetchable ... that check is syntactic", which was true only for literal-IP hosts
and false for exactly the threat the guard exists to stop. Under `0.0.0.0/0` a public-looking
hostname resolving to `127.0.0.1` was fetchable end to end, on an API with no authentication
(invariant 25).

**The test that "pinned" it was vacuous, and that is the more useful half of the lesson.** It used
literal-IP URLs, which `is_safe_url` rejects before `resolved_host_is_safe` is consulted — so it
passed with the `resolved_host_is_safe` call DELETED from `_check_safe` entirely, and the whole
suite stayed green under a mutant that opened every IPv6 internal target. **A guard test that never
reaches the guard is worse than no test, because it is cited as proof.** The replacement resolves a
public-looking hostname to each internal address in turn and is verified to kill both mutants.

**Validating only "does it parse" caught the harmless typo, not the dangerous one.** A dropped
character turns `198.18.0.0/16` into `198.18.0.0/1`, which normalises to `128.0.0.0/1` — half the
address space, cloud metadata and `192.168/16` included — and parses cleanly.

**`_NEVER_ALLOWED` is an explicit list, deliberately NOT `ipaddress`'s own `is_private`/`is_reserved`
properties**: `198.18.0.0/16` is RFC 2544 benchmarking space and reports `is_private` True, so a
property-based rule would refuse the single value this variable exists to accept.

**Accepted cost, stated rather than discovered later**: a split-DNS VPN mapping internal names into
RFC1918 cannot be carved out. That is not an oversight — it is the SSRF this guard exists to
prevent, and there is deliberately no override.

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
