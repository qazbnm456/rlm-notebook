#!/usr/bin/env python3
"""Serve `dist/` with caching turned OFF.

`python -m http.server` sends no `Cache-Control` at all, which leaves the browser on heuristic
caching: free to reuse a stale copy without revalidating. For a zero-build app whose filenames carry
no content hash, that means testing a fix and being served the previous JavaScript — the exact
hazard invariant 72 records for the product's own assets. Half an hour was spent here debugging a
guided-tour step that had already been fixed on disk.
"""

import argparse
import http.server
import os
from pathlib import Path


class NoCache(http.server.SimpleHTTPRequestHandler):
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
    os.chdir(args.dir)
    print(f"serving {args.dir} at http://127.0.0.1:{args.port}/ (no-store)")
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), NoCache).serve_forever()
