"""Test-wide isolation.

`config.settings_path`, `notebook.DEFAULT_NOTEBOOKS_DIR` and `api._TRACE_DIR` are all resolved
against the process's working directory, so without this a test run picks up whatever the developer
happens to have in their own `notebooks/` — and a settings file written by a live check silently
changed the result of an unrelated TTS test. That is the same class of failure a sibling
project's ASR-locale design note records: an instrument that does not reproduce production's shape
returns the right answer to the wrong question.

Default arguments bind at definition time (`def settings_path(base_dir=_DEFAULT_NOTEBOOKS_DIR)`), so
monkeypatching the constant would not help — the working directory is the only lever that reaches
every caller. `test_api.py` and `test_cli.py` already did this per-file; this makes it the floor for
every test rather than something each file has to remember.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
