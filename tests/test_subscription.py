"""The `claude-agent-sdk/` sentinel: routing a role onto the user's Claude subscription.

Split the way the sibling `cve-reverser`'s equivalent suite is: the config-level and non-sentinel
assertions run with NO optional dependency at all, and only the injection test needs
`claude-agent-sdk` (skipped when absent). The point of the split is that the non-sentinel branch
must be provable WITHOUT the SDK — that is the property that keeps an API-key-only install from
paying for an import it never uses.
"""

from __future__ import annotations

import sys

import pytest

from rlm_notebook.config import SUBSCRIPTION_PREFIX, NotebookConfig, _maybe_subscription_lm


def _clear(monkeypatch):
    for var in ("RN_MAIN_MODEL", "RN_SUB_MODEL", "RN_API_KEY", "RN_BASE_URL", "RN_INTERPRETER"):
        monkeypatch.delenv(var, raising=False)


def test_non_sentinel_returns_none_without_importing_the_adapter():
    """The proxy path must not drag in `rlm_harness.claude_agent_lm` (and through it the optional
    SDK). Compares before/after rather than asserting the module is simply absent, so the result
    doesn't depend on whether an earlier test in the session already loaded it."""
    had_adapter = "rlm_harness.claude_agent_lm" in sys.modules

    assert _maybe_subscription_lm("anthropic/claude-sonnet-5") is None

    assert ("rlm_harness.claude_agent_lm" in sys.modules) == had_adapter


def test_a_subscription_model_needs_no_api_key(monkeypatch):
    """`RN_API_KEY` stays optional, which is the whole point: a subscription run authenticates
    through the Claude Code CLI's own login, so `from_env` must not start demanding a key."""
    _clear(monkeypatch)
    monkeypatch.setenv("RN_MAIN_MODEL", f"{SUBSCRIPTION_PREFIX}claude-sonnet-5")

    config = NotebookConfig.from_env()

    assert config.main_model == "claude-agent-sdk/claude-sonnet-5"
    assert config.api_key is None
    assert config.base_url is None


def test_an_unset_sub_model_inherits_the_sentinel(monkeypatch):
    """`RN_SUB_MODEL` defaults to the main model, so a subscription planner puts the sub-LM on the
    subscription too. Unlike `cve-reverser` — where the same inheritance was a HAZARD it had to
    reject, because its generator role is a separate tool that must stay on its own endpoint —
    this project has no such role, so inheriting is simply correct here. Pinned so the difference
    between the two projects is deliberate rather than accidental."""
    _clear(monkeypatch)
    monkeypatch.setenv("RN_MAIN_MODEL", f"{SUBSCRIPTION_PREFIX}claude-sonnet-5")

    config = NotebookConfig.from_env()

    assert config.sub_model == config.main_model


def test_mixed_auth_is_allowed(monkeypatch):
    """A subscription planner with a proxy sub-LM (or the reverse) — each role is resolved
    independently, so nothing forces both onto the same backend."""
    _clear(monkeypatch)
    monkeypatch.setenv("RN_MAIN_MODEL", f"{SUBSCRIPTION_PREFIX}claude-sonnet-5")
    monkeypatch.setenv("RN_SUB_MODEL", "openai/gpt-4o")
    monkeypatch.setenv("RN_API_KEY", "sk-proxy")

    config = NotebookConfig.from_env()

    assert config.main_model.startswith(SUBSCRIPTION_PREFIX)
    assert config.sub_model == "openai/gpt-4o"


def test_setup_injects_the_subscription_lm_for_a_sentinel_role(monkeypatch):
    """`rlm_harness.configure` does NOT route on the prefix — it calls `dspy.LM(cfg.main_model)`
    for any seat left unsupplied, which for `claude-agent-sdk/...` means litellm resolving a
    provider that doesn't exist. The sentinel works ONLY because `setup` injects through the
    `main_lm=`/`sub_lm=` seam, so that is what this asserts: the seat is supplied, and the seat
    left on the proxy is not."""
    pytest.importorskip("dspy")
    pytest.importorskip("claude_agent_sdk")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # ClaudeAgentLM refuses to build with it set

    import rlm_harness

    captured = {}

    def _spy_configure(config, *, main_lm=None, sub_lm=None):
        captured["config"] = config
        captured["main_lm"] = main_lm
        captured["sub_lm"] = sub_lm

    monkeypatch.setattr(rlm_harness, "configure", _spy_configure)

    from rlm_notebook.config import setup

    setup(
        NotebookConfig(
            main_model=f"{SUBSCRIPTION_PREFIX}claude-sonnet-5",
            sub_model="openai/gpt-4o",
            api_key="sk-proxy",
        )
    )

    assert captured["main_lm"] is not None, "the sentinel role was left for configure to build"
    assert type(captured["main_lm"]).__name__ == "ClaudeAgentLM"
    assert captured["sub_lm"] is None, "the proxy role must stay un-supplied, built from config"
    # The sentinel STRING still reaches RLMConfig — it is what labels the trace and the log, even
    # though the seat it names is now inert.
    assert captured["config"].main_model == f"{SUBSCRIPTION_PREFIX}claude-sonnet-5"


def test_setup_leaves_both_seats_to_configure_on_the_pure_proxy_path(monkeypatch):
    """No sentinel anywhere → byte-identical to the behavior before this feature existed."""
    pytest.importorskip("dspy")
    import rlm_harness

    captured = {}
    monkeypatch.setattr(
        rlm_harness,
        "configure",
        lambda config, *, main_lm=None, sub_lm=None: captured.update(main_lm=main_lm, sub_lm=sub_lm),
    )

    from rlm_notebook.config import setup

    setup(NotebookConfig(main_model="anthropic/claude-sonnet-5", sub_model="openai/gpt-4o"))

    assert captured == {"main_lm": None, "sub_lm": None}
