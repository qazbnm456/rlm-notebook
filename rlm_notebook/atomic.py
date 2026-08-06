"""One atomic file write, shared by everything here that persists state.

Extracted from `notebook.save_notebook`, which grew it after an independent review found a plain
`path.write_text(...)` left a truncated, unparseable file behind on an interrupted write (Ctrl+C,
crash, power loss) with no recovery but deleting it. The settings file needs the identical
guarantee, and a second hand-copy of twelve lines is exactly the drift this project factors out
(the same "one copy, not five" discipline invariants 13 and 20 apply to instructions and ingestion).

Deliberately its own module rather than living in `notebook.py`: `config.py` needs it too, and
`config.py` importing `notebook.py` would drag in the whole ingestion/parser chain to write one
file.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` via a same-directory temp file, `fsync`, then `os.replace`.

    `os.replace` is atomic on both POSIX and Windows, so a concurrent reader only ever sees the
    fully-old or fully-new file, never a partial one — which is also why readers of these files need
    no lock. The temp file is removed if anything fails, so a failed write leaves the original
    untouched rather than a `.tmp` beside it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
