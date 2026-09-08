# Invariant 35 — The subscription path needs an injected LM

**A model string prefixed `claude-agent-sdk/` routes that role onto the user's Claude Pro/Max
SUBSCRIPTION, through a `ClaudeAgentLM` that `config.setup` injects into `configure`'s public
`main_lm=`/`sub_lm=` seam.** Every non-sentinel role is still built from the `RN_*` config.

**THE REASON THIS FUNCTION EXISTED HAS EXPIRED, AND THE OLD WORDING MUST NOT COME BACK.** It read:
"it works ONLY because `config.setup` injects the LM — `rlm_harness.configure` does not route on
the prefix itself", on the premise that `runtime.configure` calls `dspy.LM(...)` unconditionally
for any seat left unsupplied, so a bare sentinel would reach litellm as a provider that does not
exist. That was true of the harness of the time. It is FALSE of `rlm-harness==1.10.0`, the version
`pyproject.toml` pins: `runtime.configure` calls its own `_maybe_subscription_lm(cfg.main_model)`
for any role left `None`, on the identical prefix string, and its docstring calls it
"Claude-subscription auto-routing".

So what the injection does now is WIN, not enable: an explicit `main_lm=` is used verbatim, and the
seat never reaches upstream's branch. Nothing about the behaviour changed when upstream gained the
feature, which is exactly why nobody noticed the justification had stopped being true.

Two consequences worth stating rather than leaving to be rediscovered. `_maybe_subscription_lm`
here is now a DUPLICATE of upstream's, and `SUBSCRIPTION_PREFIX` a second copy of
`claude_agent_lm.SUBSCRIPTION_PREFIX` — kept, because `config.py` deliberately stays free of
`dspy`/`rlm_harness` at import time and cannot read upstream's constant to compare against. And
deleting ours would now "work", which is the trap: it would silently hand every subscription run to
upstream's construction, whose timeout and error semantics this project has never tested against.
Removing it is a measurement, not a cleanup.

The sentinel string ALSO stays in `RLMConfig` — inert for an injected seat, but it is what labels
the trace and the log.

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
