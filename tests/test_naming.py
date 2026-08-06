"""`naming.py` — the notebook title suggested from its sources.

No model is called here. `SuggestTitle.arun`'s model branch needs a live LM (and runs inside the
API's isolated subprocess in production); these cover the deterministic halves — the fallback, the
cleanup of whatever the model returns, and the no-sources short circuit — plus the guarantee that
matters most: it never raises.
"""

from __future__ import annotations

import asyncio

from rlm_notebook.naming import SuggestTitle, clean_title, fallback_title


def test_fallback_reads_a_pasted_origins_snippet_not_its_hash():
    """`ingest_pasted_text` gives pasted text a `pasted:<snippet> #<hash>` origin. Showing the hash
    would be the same UX regression invariant 30 already records for the Sources list."""
    title = fallback_title(["pasted:Bees navigate using polarized light #a1b2c3d4"])
    assert title == "Bees navigate using polarized light"


def test_fallback_shortens_a_url_and_counts_the_rest():
    assert fallback_title(["https://www.example.com/articles/voyager-1", "x", "y"]) == "voyager-1 (+2)"


def test_fallback_is_deterministic_and_never_empty():
    assert fallback_title([]) == "Untitled notebook"
    assert fallback_title(["pasted:hi #1"]) == fallback_title(["pasted:hi #1"])


def test_clean_title_falls_back_rather_than_showing_junk():
    """The model is unsupervised here — unlike every `RLMTask` output in this project there is no
    schema validation behind it, so this is the only guard on what reaches the UI."""
    origins = ["pasted:hello #1"]
    assert clean_title("", origins) == "hello"
    assert clean_title("x" * 500, origins) == "hello"
    assert clean_title('  "Voyager 1 Interstellar Mission."  ', origins) == "Voyager 1 Interstellar Mission"
    assert clean_title("「蜜蜂的偏振光導航」", origins) == "蜜蜂的偏振光導航"


def test_arun_short_circuits_without_sources_and_never_raises():
    """A title is a convenience; losing one must never cost the user the source they just added, so
    the model branch is wrapped and every path returns a string."""
    assert asyncio.run(SuggestTitle().arun(sources="", origins=["pasted:hi #1"])) == "hi"
    assert asyncio.run(SuggestTitle().arun()) == "Untitled notebook"


def test_arun_falls_back_when_the_model_call_explodes(monkeypatch):
    """The realistic failure: no LM configured, the endpoint unreachable, a timeout. `arun` imports
    `dspy` lazily inside the try, so swapping the module out is enough to exercise it."""
    import sys
    import types

    def _boom(*args, **kwargs):
        raise RuntimeError("no LM configured")

    fake = types.ModuleType("dspy")
    fake.Predict = _boom
    fake.Signature = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "dspy", fake)

    assert asyncio.run(SuggestTitle().arun(sources="text", origins=["pasted:hi #1"])) == "hi"
