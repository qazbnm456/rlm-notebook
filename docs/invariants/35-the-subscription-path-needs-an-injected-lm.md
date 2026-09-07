# Invariant 35 — The subscription path needs an injected LM

**A model string prefixed `claude-agent-sdk/` routes that role onto the user's Claude Pro/Max
SUBSCRIPTION, and it works ONLY because `config.setup` injects the LM — `rlm_harness.configure`
does not route on the prefix itself.** `runtime.configure` calls `dspy.LM(...)` unconditionally
for any seat left unsupplied, so a `claude-agent-sdk/…` string handed to it alone reaches
litellm as a provider that does not exist. `setup` builds a `rlm_harness.ClaudeAgentLM` per
sentinel role and passes it through `configure`'s public `main_lm=`/`sub_lm=` seam; every
non-sentinel role is still built from the `RN_*` config. The sentinel string ALSO stays in
`RLMConfig` — inert for an injected seat, but it is what labels the trace and the log.

`SUBSCRIPTION_PREFIX` lives in `config.py` (a naming convention, in the module that stays free of
`dspy`/`rlm_harness` at import time) and `_maybe_subscription_lm` imports `ClaudeAgentLM` LAZILY,
inside the sentinel branch only, so an API-key-only install never touches the optional SDK.
**`config.setup` is the ONE place either entry point configures a model** — `cli.py` in-process
and `worker.py` inside the subprocess both call it — so one change covers both execution models.

**`RN_SUB_MODEL` inheriting the sentinel from `RN_MAIN_MODEL` is correct HERE** (this project has
no separate role that must stay on its own endpoint), and is pinned by a test so the divergence
from the sibling that gates against it stays deliberate.

`claude-agent-sdk` is the `subscription` extra, MIRRORED as a `subscription-sdk` dev group with
`[tool.uv] default-groups`. Not redundancy: an extra is not synced by default, so a bare
`uv sync` PRUNES the SDK back out and the next subscription run dies with an `ImportError`
nobody caused. The SDK also needs the Claude Code CLI installed and logged in, a runtime
prerequisite no manifest can express. `ClaudeAgentLM` refuses to construct when
`ANTHROPIC_API_KEY` is set (the CLI silently prefers it over subscription OAuth, which would
quietly bill API credit) — an upstream guard. A BARE `claude-agent-sdk/` with no model after the
slash raises `SystemExit`, reaching the API as a clean 500 through `_config()`.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
