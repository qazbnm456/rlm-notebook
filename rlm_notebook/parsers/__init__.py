"""Host-side source parsers (AGENTS.md invariant 3 — never runs inside the RLM sandbox).

Each parser turns raw input (a file path, a URL, pasted text) into a `Source` with citable
`SourceBlock`s. Ingestion happens entirely before any `RLMTask` exists — nothing here is reachable
from the model.
"""

from __future__ import annotations
