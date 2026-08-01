from __future__ import annotations

import pytest

from rlm_notebook.config import NotebookConfig


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
