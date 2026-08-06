from __future__ import annotations

import pytest

from rlm_notebook.config import NotebookConfig, max_trace_files, trace_retention_seconds


def test_from_env_requires_main_model(monkeypatch):
    monkeypatch.delenv("RN_MAIN_MODEL", raising=False)
    with pytest.raises(SystemExit, match="RN_MAIN_MODEL"):
        NotebookConfig.from_env()


def test_from_env_refuses_non_pinned_interpreter(monkeypatch):
    monkeypatch.setenv("RN_MAIN_MODEL", "openai/gpt-4o")
    monkeypatch.setenv("RN_INTERPRETER", "local")
    with pytest.raises(SystemExit, match="refused"):
        NotebookConfig.from_env()


def test_from_env_refuses_unknown_ocr_provider(monkeypatch):
    monkeypatch.setenv("RN_MAIN_MODEL", "openai/gpt-4o")
    monkeypatch.delenv("RN_INTERPRETER", raising=False)
    monkeypatch.setenv("RN_OCR_PROVIDER", "made-up")
    with pytest.raises(SystemExit, match="RN_OCR_PROVIDER"):
        NotebookConfig.from_env()


def test_from_env_defaults(monkeypatch):
    monkeypatch.setenv("RN_MAIN_MODEL", "openai/gpt-4o")
    for var in ("RN_INTERPRETER", "RN_SUB_MODEL", "RN_OCR_PROVIDER", "RN_MAX_CORPUS_CHARS"):
        monkeypatch.delenv(var, raising=False)
    config = NotebookConfig.from_env()
    assert config.main_model == "openai/gpt-4o"
    assert config.sub_model == "openai/gpt-4o"
    assert config.interpreter == "pyodide"
    assert config.ocr_provider == "local"
    assert config.max_corpus_chars == 8_000_000


def test_trace_retention_defaults(monkeypatch):
    for var in ("RN_TRACE_RETENTION_DAYS", "RN_MAX_TRACE_FILES"):
        monkeypatch.delenv(var, raising=False)
    assert trace_retention_seconds() == 7 * 86_400
    assert max_trace_files() == 500


def test_trace_retention_does_not_need_a_model_configured(monkeypatch):
    """Standalone, not a `NotebookConfig` field, for the same reason `max_upload_bytes` is
    (invariant 30): housekeeping runs at server startup and must not depend on `RN_MAIN_MODEL`."""
    monkeypatch.delenv("RN_MAIN_MODEL", raising=False)
    assert trace_retention_seconds() > 0
    assert max_trace_files() > 0


def test_zero_means_no_limit_for_the_retention_knobs(monkeypatch):
    """`_env_int` refuses 0 on purpose — every value it reads is a budget, where zero is almost
    certainly a mistake. Here it has a real meaning ("keep everything"), which is why these two use
    their own reader rather than loosening `_env_int` for everyone."""
    monkeypatch.setenv("RN_TRACE_RETENTION_DAYS", "0")
    monkeypatch.setenv("RN_MAX_TRACE_FILES", "0")
    assert trace_retention_seconds() == 0
    assert max_trace_files() == 0


@pytest.mark.parametrize("value", ["not-a-number", "-1"])
def test_a_malformed_retention_value_is_refused(monkeypatch, value):
    monkeypatch.setenv("RN_MAX_TRACE_FILES", value)
    with pytest.raises(SystemExit, match="RN_MAX_TRACE_FILES"):
        max_trace_files()
