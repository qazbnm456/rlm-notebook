#!/usr/bin/env python3
"""Serve `dist/` with caching turned OFF.

`python -m http.server` sends no `Cache-Control` at all, which leaves the browser on heuristic
caching: free to reuse a stale copy without revalidating. For a zero-build app whose filenames carry
no content hash, that means testing a fix and being served the previous JavaScript — the exact
hazard invariant 72 records for the product's own assets. Half an hour was spent here debugging a
guided-tour step that had already been fixed on disk.

It resolves each request against `--dir` by NAME rather than `chdir`-ing into it once at startup.
`build.py` removes and recreates `dist/`, which pulls the old directory's inode out from under a
running server: the process stays alive and keeps accepting connections, but `SimpleHTTPRequestHandler`
calls `os.getcwd()` per request and every one of them dies with `FileNotFoundError`. From the
browser that is a connection reset with a healthy-looking process behind it, which is a worse
failure than crashing would have been.
"""

import argparse
import http.server
from pathlib import Path


class NoCache(http.server.SimpleHTTPRequestHandler):
    #: Bound to `--dir` in `main`, and passed to every handler instance. Requests are then resolved
    #: against this PATH, so a rebuild that replaces the directory is picked up rather than fatal.
    directory = ""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=type(self).directory, **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, *args):  # quiet: the point is the browser, not the log
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parent / "dist"))
    args = ap.parse_args()
    NoCache.directory = str(Path(args.dir).resolve())
    print(f"serving {NoCache.directory} at http://127.0.0.1:{args.port}/ (no-store)")
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), NoCache).serve_forever()
