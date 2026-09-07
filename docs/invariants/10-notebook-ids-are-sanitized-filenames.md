# Invariant 10 — Notebook ids are sanitized filenames

**A notebook id is sanitized (`notebook.slug`) before it becomes a filename, and an id the
whitelist empties falls back to a content hash rather than being rejected.** `--notebook` and
the API's `{notebook_id}` turn directly into `<notebooks_dir>/<slug(id)>.json`, so an
unsanitized id could become a traversal segment (`..`, an absolute path, a nested directory) or
blow past a path-component length limit.

**`nb-<sha256[:16]>` when the whitelist leaves nothing.** `[A-Za-z0-9._-]` strips every CJK,
Arabic, Cyrillic and emoji character, so a notebook named in Chinese reduced to the empty string
and was rejected. The id is NFC-normalized before hashing (two spellings reach the same file)
and encoded with `surrogatepass` — load-bearing, because `api._derive_run_id` calls `slug()`
OUTSIDE every error wrapper, which would make a raising `slug` an unauthenticated 500. It
affects the FILENAME only: `Notebook.id` stores what the user typed and
`list_notebook_summaries` reports that stored value, so non-Latin names round-trip. A genuinely
empty or whitespace-only id still raises.

**This deliberately supersedes part of invariant 27**: `"!!!"` is an ordinary notebook now, not
a 400. The unhandled 500 that 27 exists to fix is still gone; that input simply no longer
reaches the arm, and a genuinely empty id still exercises it.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
