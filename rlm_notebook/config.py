"""Configuration for rlm-notebook — the `RN_*` env surface `.env.example` documents.

Mirrors the sibling projects' `config.py` convention (see `ctx-distillery/ctx_distillery/config.py`):
its own env prefix rather than sharing rlm-harness's `RLM_*` surface directly, so this project's env
names stay stable even if rlm-harness's own defaults change, and a live run's config is fully visible
in one place. No `dspy` import, and no `rlm_harness` import at module scope — `from_env()` is plain
stdlib so it can be exercised without paying for the model stack; `setup()` imports rlm-harness lazily,
at the point it is actually about to configure a model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: The one sandbox `AnswerQuestion` ever runs in (see CLAUDE.md invariant 9 — `from_env` below
#: refuses any other `RN_INTERPRETER` rather than silently overriding it).
PINNED_INTERPRETER = "pyodide"

#: Model-string prefix routing a role onto the user's Claude Pro/Max SUBSCRIPTION through
#: rlm-harness's `ClaudeAgentLM`, instead of building a `dspy.LM` against `RN_API_KEY`/`RN_BASE_URL`.
#: A naming convention, so it lives here in the dspy-free module; `setup()` does the actual (lazy,
#: dspy-bearing) wiring. Same sentinel and same placement as the sibling `cve-reverser`, which
#: shipped this pattern first — deliberately not a second spelling of the same idea.
SUBSCRIPTION_PREFIX = "claude-agent-sdk/"

#: Default cap on the assembled corpus blob (CLAUDE.md invariant 8) — a `chars`, not `tokens`,
#: budget, matching rlm-harness's own `max_output_chars` convention. This is a memory-safety cap on the
#: pyodide/deno sandbox, not a tuning knob; raise it only once real usage shows headroom.
_DEFAULT_MAX_CORPUS_CHARS = 8_000_000

_KNOWN_OCR_PROVIDERS = ("local", "vision_llm")

#: Default two-host voice cast for the Audio Overview (`RN_TTS_VOICE_HOST_A`/`_B`) — edge-tts voice
#: ids needing no API key or account, chosen only so `rlm-notebook audio` works out of the box;
#: override either independently.
_DEFAULT_TTS_VOICE_HOST_A = "en-US-GuyNeural"
_DEFAULT_TTS_VOICE_HOST_B = "en-US-JennyNeural"

#: Cap on one uploaded file's byte size (`api.py`'s `POST /notebooks/{id}/sources/upload`).
_DEFAULT_MAX_UPLOAD_BYTES = 50_000_000

#: Trace-file retention (`traces.prune_traces`). A week of history is enough for the one affordance
#: a trace actually serves after its run finishes — a citation's "view reasoning" link — without
#: keeping full ingested source text on disk indefinitely behind an API with no auth (invariant 25).
_DEFAULT_TRACE_RETENTION_DAYS = 7
_DEFAULT_MAX_TRACE_FILES = 500


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise SystemExit(f"{name}={raw!r} is not an integer") from None
    if value < 1:
        raise SystemExit(f"{name}={raw!r} must be a positive integer (it is a budget)")
    return value


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        raise SystemExit(f"{name}={raw!r} is not a number") from None
    if value <= 0:
        raise SystemExit(f"{name}={raw!r} must be a positive number (it is a timeout)")
    return value


def _env_int_allowing_zero(name: str, default: int) -> int:
    """Like `_env_int`, but accepts `0`. `_env_int` refuses it deliberately — every value it reads
    is a BUDGET (iterations, tokens, bytes), where zero means "do nothing" and is far more likely a
    mistake than an intent. The retention knobs below are the opposite: `0` has a well-defined,
    useful meaning there ("no limit — keep everything"), so they get their own reader rather than
    loosening `_env_int` for values where zero really is a misconfiguration."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise SystemExit(f"{name}={raw!r} is not an integer") from None
    if value < 0:
        raise SystemExit(f"{name}={raw!r} must be zero (no limit) or a positive integer")
    return value


def _ocr_provider_from_env() -> str:
    raw = (os.getenv("RN_OCR_PROVIDER") or "").strip() or "local"
    if raw not in _KNOWN_OCR_PROVIDERS:
        raise SystemExit(
            f"RN_OCR_PROVIDER={raw!r} is not a known provider; expected one of "
            f"{', '.join(_KNOWN_OCR_PROVIDERS)} (see .env.example)."
        )
    return raw


@dataclass(frozen=True)
class NotebookConfig:
    """The `RN_*` surface, resolved. Build with `from_env()`; construct directly in tests."""

    #: The RLM's main model, driving the REPL loop. Required for a live run.
    main_model: str = ""
    #: The sub LM rlm-harness hands to `llm_query`. Defaults to the main model.
    sub_model: str = ""
    api_key: str | None = None
    base_url: str | None = None

    #: Pinned; kept as a field so the value actually configured is visible in the trace.
    interpreter: str = PINNED_INTERPRETER
    max_iterations: int = 10
    max_llm_calls: int = 30
    max_tokens: int = 8192
    max_output_chars: int = 10_000
    adapter: str = "json"

    #: rlm-notebook-specific: the size cap on the assembled corpus blob (CLAUDE.md invariant 8).
    max_corpus_chars: int = _DEFAULT_MAX_CORPUS_CHARS

    #: Which OCR backend `parsers/pdf.py` dispatches scanned/image pages to. "local" (default) uses
    #: `parsers/_ocr.py`'s hybrid OCR (RapidOCR/Tesseract — core dependencies, always installed).
    #: "vision_llm" is a deferred follow-up (CLAUDE.md invariant 7) — accepted here so config
    #: validation is ready for it, but `parsers/pdf.py` does not yet implement that branch.
    ocr_provider: str = "local"

    #: Which TTS backend `tts.py` dispatches to. Default is a free, no-API-key provider so
    #: `rlm-notebook audio` works with no paid credentials — see CLAUDE.md's Audio Overview
    #: invariant (mirrors the OCR default's reasoning, invariant 7).
    tts_provider: str = "edge-tts"
    tts_voice_host_a: str = _DEFAULT_TTS_VOICE_HOST_A
    tts_voice_host_b: str = _DEFAULT_TTS_VOICE_HOST_B

    #: `api.py`-specific: how long `runner.wait_result` waits for a subprocess run before
    #: cancelling it (`killpg`) and reporting a timeout — a backstop distinct from rlm-harness's own
    #: `max_iterations`/`max_llm_calls` budget (which bounds the RLM loop's *steps*, not wall-clock
    #: time; a slow model/network can still run long past a small iteration budget). `cli.py`'s
    #: in-process commands don't use this at all — only the subprocess-isolated API path does.
    run_timeout_seconds: float = 300.0

    @classmethod
    def from_env(cls) -> NotebookConfig:
        """Read `RN_*`. Raises `SystemExit` on a missing required var or an invalid enum value."""
        main = (os.getenv("RN_MAIN_MODEL") or "").strip()
        if not main:
            raise SystemExit(
                "RN_MAIN_MODEL is not set — a live run needs a model. Copy .env.example to .env, "
                "fill it in, and export it (`set -a; . ./.env; set +a`); nothing here auto-loads "
                "a .env file."
            )
        interpreter = (os.getenv("RN_INTERPRETER") or PINNED_INTERPRETER).strip()
        if interpreter != PINNED_INTERPRETER:
            raise SystemExit(
                f"RN_INTERPRETER={interpreter!r} is refused — rlm-notebook only ever runs its chat "
                f"task in the {PINNED_INTERPRETER!r} sandbox (CLAUDE.md invariant 9). Refusing "
                f"rather than silently ignoring what you configured."
            )
        return cls(
            main_model=main,
            sub_model=(os.getenv("RN_SUB_MODEL") or "").strip() or main,
            api_key=(os.getenv("RN_API_KEY") or "").strip() or None,
            base_url=(os.getenv("RN_BASE_URL") or "").strip() or None,
            interpreter=interpreter,
            max_iterations=_env_int("RN_MAX_ITERATIONS", 10),
            max_llm_calls=_env_int("RN_MAX_LLM_CALLS", 30),
            max_tokens=_env_int("RN_MAX_TOKENS", 8192),
            max_output_chars=_env_int("RN_MAX_OUTPUT_CHARS", 10_000),
            adapter=(os.getenv("RN_ADAPTER") or "json").strip(),
            max_corpus_chars=_env_int("RN_MAX_CORPUS_CHARS", _DEFAULT_MAX_CORPUS_CHARS),
            ocr_provider=_ocr_provider_from_env(),
            tts_provider=(os.getenv("RN_TTS_PROVIDER") or "edge-tts").strip(),
            tts_voice_host_a=(os.getenv("RN_TTS_VOICE_HOST_A") or _DEFAULT_TTS_VOICE_HOST_A).strip(),
            tts_voice_host_b=(os.getenv("RN_TTS_VOICE_HOST_B") or _DEFAULT_TTS_VOICE_HOST_B).strip(),
            run_timeout_seconds=_env_float("RN_RUN_TIMEOUT_SECONDS", 300.0),
        )


def max_upload_bytes() -> int:
    """`RN_MAX_UPLOAD_BYTES`, read INDEPENDENTLY of `NotebookConfig.from_env()` — deliberately not
    a field on `NotebookConfig` at all. `from_env()` raises `SystemExit` (a 500 via `api._config()`)
    whenever `RN_MAIN_MODEL` is unset; that's correct for `ask`/`guide`/`audio`, which actually run
    a model, but would be a real bug for a file-upload endpoint, which has nothing to do with
    whether a model is configured — `add_sources` (the existing URL-based ingestion path) already
    reflects this by never calling `_config()` either. Caught while designing the upload endpoint,
    not left for an audit to find."""
    return _env_int("RN_MAX_UPLOAD_BYTES", _DEFAULT_MAX_UPLOAD_BYTES)


def trace_retention_seconds() -> float:
    """`RN_TRACE_RETENTION_DAYS` as seconds; `0` disables the age sweep (keep traces forever).

    Read INDEPENDENTLY of `NotebookConfig.from_env()`, for the same reason `max_upload_bytes` is
    (invariant 30): `from_env()` raises `SystemExit` whenever `RN_MAIN_MODEL` is unset, and trace
    housekeeping — which runs at server startup, before any model call is in sight — has nothing to
    do with whether a model is configured. A server started without model credentials should still
    tidy up after itself rather than fail to start."""
    return _env_int_allowing_zero("RN_TRACE_RETENTION_DAYS", _DEFAULT_TRACE_RETENTION_DAYS) * 86_400.0


def max_trace_files() -> int:
    """`RN_MAX_TRACE_FILES`; `0` disables the count sweep. Standalone for the same reason as
    `trace_retention_seconds`."""
    return _env_int_allowing_zero("RN_MAX_TRACE_FILES", _DEFAULT_MAX_TRACE_FILES)


def _maybe_subscription_lm(model: str):
    """A `ClaudeAgentLM` when a role's model carries the `claude-agent-sdk/` sentinel, else `None`
    (which makes `rlm_harness.configure` build a `dspy.LM` from the `RN_*` proxy config exactly as
    before).

    Imports `ClaudeAgentLM` LAZILY, inside the sentinel branch ONLY, so `import rlm_notebook.config`
    stays free of `dspy`/`rlm_harness` (this module's docstring promises that) and an API-key install
    that never uses the sentinel never touches the optional SDK at all. `claude-agent-sdk` is the
    `subscription` extra; rlm-harness defers that import to construction and raises an actionable
    install hint when it's missing.

    The stripped remainder is the Claude model — prefer a full id (`claude-sonnet-5`) over an alias
    (`sonnet`), which drifts over time.
    """
    if not model.startswith(SUBSCRIPTION_PREFIX):
        return None
    name = model[len(SUBSCRIPTION_PREFIX) :].strip()
    if not name:
        # A bare `claude-agent-sdk/` otherwise builds an LM with an empty model name and fails only
        # on the FIRST CALL, deep inside the retry wrapper, as the same opaque "Failed to produce a
        # valid 'answer'" every other run failure reports — after ingestion has already run. Refuse
        # at config time instead, the way invariant 9 (`RN_INTERPRETER`) and `_ocr_provider_from_env`
        # already do for their own bad values. Found by an independent review; `cve-reverser` has
        # the identical gap, so this is a lesson the sibling had not learned either, not a mis-copy.
        raise SystemExit(
            f"{model!r} names no model — expected {SUBSCRIPTION_PREFIX}<id>, e.g. "
            f"{SUBSCRIPTION_PREFIX}claude-sonnet-5 (see .env.example)."
        )
    from rlm_harness import ClaudeAgentLM

    return ClaudeAgentLM(name)


#: Bound on `RN_OUTPUT_LANGUAGE` / a model-resolved language. Both end up spliced into a prompt, and
#: the resolved one is unvalidated model prose derived from UNTRUSTED source content (invariant 6) —
#: the same reason `naming.clean_title` exists.
_MAX_LANGUAGE_CHARS = 40


def clean_language(raw: str | None) -> str | None:
    """A language name safe to splice into an instruction: one line, bounded, no control characters.
    Returns `None` for anything empty, which every caller reads as "no preference".

    Not a closed-set check like `_ocr_provider_from_env`'s: human language names have no enumerable
    set, so this bounds the value rather than refusing unknown ones."""
    if not raw:
        return None
    collapsed = " ".join(str(raw).split())
    stripped = "".join(c for c in collapsed if c.isprintable())
    return stripped[:_MAX_LANGUAGE_CHARS].strip() or None


def output_language() -> str | None:
    """`RN_OUTPUT_LANGUAGE` — a HARD override over anything resolved from the reader's signals, and
    it applies to chat as well as to whole-corpus artifacts (NotebookLM's equivalent forced-language
    setting does too; scoping it to artifacts would leave an operator who set it wondering why their
    answers were still in the sources' language).

    Standalone rather than a `NotebookConfig` field, for the same reason as `max_upload_bytes`
    (invariant 30): it is read on paths that have nothing to do with whether a model is configured.
    Read at GENERATION time, so changing it takes effect without re-resolving any notebook."""
    return clean_language(os.getenv("RN_OUTPUT_LANGUAGE"))


def setup(config: NotebookConfig) -> NotebookConfig:
    """Configure rlm-harness (main + sub LM) for this process, and return `config` unchanged.

    Mirrors the sibling projects' `setup(config)` shape: `AnswerQuestion` reads the process-wide
    config through `rlm_harness.runtime.get_config()` when no `config=` is passed, so without this call
    a live run would silently inherit `RLMConfig.from_env()`'s own `RLM_*` defaults rather than the
    `RN_*` values the operator set.

    **A role whose model is `claude-agent-sdk/<id>` runs on the user's Claude Pro/Max SUBSCRIPTION**
    (`ClaudeAgentLM`, injected through `configure`'s public `main_lm=`/`sub_lm=` seam); every other
    role is built from the `RN_*` proxy config, byte-identical to before. `configure` does NOT route
    on the prefix itself — it calls `dspy.LM(cfg.main_model)` unconditionally for any seat left
    unsupplied — so the sentinel only works because it is injected HERE. Mixed auth (a subscription
    planner with a proxy sub-LM, or the reverse) is supported by construction, since each role is
    tested independently.

    This is the ONE place either entry point configures a model: `cli.py` calls it in-process and
    `worker.py` calls it inside the API's isolated subprocess, so both get the subscription path
    from this single change.
    """
    import rlm_harness
    from rlm_harness.config import RLMConfig

    # None → configure builds a dspy.LM from the RN_* proxy config (the pre-existing behavior).
    main_lm = _maybe_subscription_lm(config.main_model)
    sub_lm = _maybe_subscription_lm(config.sub_model)

    rlm_harness.configure(
        RLMConfig(
            # Inert for a seat whose LM is injected below (`configure` builds from config ONLY for
            # un-supplied seats), but still what labels the trace and the log — so the sentinel
            # string, not the stripped model id, is what a reader sees attributed to the run.
            main_model=config.main_model,
            sub_model=config.sub_model,
            api_key=config.api_key,
            base_url=config.base_url,
            interpreter=config.interpreter,
            max_iterations=config.max_iterations,
            max_llm_calls=config.max_llm_calls,
            max_tokens=config.max_tokens,
            max_output_chars=config.max_output_chars,
            adapter=config.adapter,
            max_retries=1,
        ),
        main_lm=main_lm,
        sub_lm=sub_lm,
    )
    return config
