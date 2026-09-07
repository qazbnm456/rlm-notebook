# Invariant 30 — Upload and paste do not reopen the path ban

**`POST /notebooks/{id}/sources/upload` and `add_sources`'s `texts` field never reopen
invariant 26's local-path ban.** Upload is the opposite shape: the server only receives opaque
bytes the caller already had, plus a claimed filename used solely for extension-based kind
detection (`.pdf`/`.txt`/`.md`, `ingest.ingest_uploaded_file`) and display. Pasted text has no
path at all — `ingest.ingest_pasted_text` gives it a content-derived origin (a readable snippet
plus a hash, not a bare hash, because the Sources list renders `origin` verbatim as its label).

**The size cap must be checked BEFORE FastAPI parses the body.** Declaring the endpoint the
natural way (`file: UploadFile = File(...)`) makes FastAPI parse the ENTIRE multipart body
before the handler runs — a 5MB body is fully read and spooled to disk the instant the handler
starts — and Starlette's `max_part_size` never applies to file parts, only plain form fields, so
there is no framework-level backstop. `upload_source` therefore takes `request: Request`
directly (no `File(...)` parameter), checks `Content-Length` FIRST, and only calls
`request.form()` once that clears `config.max_upload_bytes()` (`RN_MAX_UPLOAD_BYTES`, 50MB). A
missing `Content-Length` (chunked encoding) is refused outright (411) — there is no safe way to
bound an unknown-length body before reading it.

**`config.max_upload_bytes()` is deliberately NOT a `NotebookConfig` field.** `from_env()` raises
`SystemExit` whenever `RN_MAIN_MODEL` is unset, correct for `ask`/`guide`/`audio` and a real bug
here: uploading a source has nothing to do with whether a model is configured. (See invariant 24
for the coverage gap this creates.)

**Deliberately not attempted**: Word/Slides/Docs native-format parsing, and multi-file batch
upload (matching the single-file `<input>`).

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
