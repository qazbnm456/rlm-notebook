"""Configuration for rlm-notebook — the `RN_*` env surface `.env.example` documents.

Mirrors the sibling projects' `config.py` convention (see `ctx-distillery/ctx_distillery/config.py`):
its own env prefix rather than sharing rlm-kit's `RLM_*` surface directly, so this project's env
names stay stable even if rlm-kit's own defaults change, and a live run's config is fully visible
in one place. No `dspy` import, and no `rlm_kit` import at module scope — `from_env()` is plain
stdlib so it can be exercised without paying for the model stack; `setup()` imports rlm-kit lazily,
at the point it is actually about to configure a model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: The one sandbox `AnswerQuestion` ever runs in (see CLAUDE.md invariant 9 — `from_env` below
#: refuses any other `RN_INTERPRETER` rather than silently overriding it).
PINNED_INTERPRETER = "pyodide"

#: Default cap on the assembled corpus blob (CLAUDE.md invariant 8) — a `chars`, not `tokens`,
#: budget, matching rlm-kit's own `max_output_chars` convention. This is a memory-safety cap on the
#: pyodide/deno sandbox, not a tuning knob; raise it only once real usage shows headroom.
_DEFAULT_MAX_CORPUS_CHARS = 8_000_000

_KNOWN_OCR_PROVIDERS = ("local", "vision_llm")

#: Default two-host voice cast for the Audio Overview (`RN_TTS_VOICE_HOST_A`/`_B`) — edge-tts voice
#: ids needing no API key or account, chosen only so `rlm-notebook audio` works out of the box;
#: override either independently.
_DEFAULT_TTS_VOICE_HOST_A = "en-US-GuyNeural"
_DEFAULT_TTS_VOICE_HOST_B = "en-US-JennyNeural"


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
    #: The sub LM rlm-kit hands to `llm_query`. Defaults to the main model.
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
    #: pymupdf4llm's built-in hybrid OCR (RapidOCR/Tesseract — core dependencies, always installed).
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
    #: cancelling it (`killpg`) and reporting a timeout — a backstop distinct from rlm-kit's own
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


def setup(config: NotebookConfig) -> NotebookConfig:
    """Configure rlm-kit (main + sub LM) for this process, and return `config` unchanged.

    Mirrors the sibling projects' `setup(config)` shape: `AnswerQuestion` reads the process-wide
    config through `rlm_kit.runtime.get_config()` when no `config=` is passed, so without this call
    a live run would silently inherit `RLMConfig.from_env()`'s own `RLM_*` defaults rather than the
    `RN_*` values the operator set.
    """
    import rlm_kit
    from rlm_kit.config import RLMConfig

    rlm_kit.configure(
        RLMConfig(
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
        )
    )
    return config
