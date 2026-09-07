# Invariant 3 — Ingestion is host-side and serial

**Ingestion is host-side only AND SERIAL — never inside the sandbox, never in a thread pool.** `parsers/{text,web,pdf,youtube}.py`
and `parsers/_ocr.py` all run before any `RLMTask` exists. `pypdfium2`, `trafilatura`, `yt-dlp`
and the OCR backends are native/C-extension dependencies unsuited to the pyodide/deno sandbox —
and untrusted parsing logic has no reason to run inside the same trust boundary as the model's
own code anyway. `corpus.py` only ever hands the RLM a plain string, already parsed.

**`ingest.ingest_new`'s plain `for` loop is load-bearing, and it looks exactly like an easy win.**
Each source is a network round trip, so a serial loop spends the sum of every wait when the
longest would do, and the sources are independent by construction (the caller handed us a list) —
the case for a `ThreadPoolExecutor` writes itself. It was written, measured, and it CRASHES:
four PDFs ingested concurrently died with `rc=134` (SIGABRT; an earlier attempt `rc=139`,
SIGSEGV), because `pypdfium2`'s own metadata says so in as many words —
*"PDFium is inherently not thread-safe"* (`pypdfium2-5.12.1.dist-info/METADATA:1066`). That
constraint arrived with the dependency invariant 7 chose and nobody had written it down here.

**The measured upside was near zero on the path that crashes**: five HTML sources went 7.55s to
2.85s, but four ordinary PDFs parse serially in 0.41s — `api.py`'s "can take minutes" describes
OCR on SCANNED pages, one branch of PDF ingestion, not the text-extraction path. So the workload
the saving was supposed to scale on is the one where the saving is nearly zero and the risk is a
hard crash.

**A green suite proved nothing, and that is the transferable part**: `tests/test_ingest.py`'s
multi-value cases all take local TEXT files through `parse_text`, so nothing in 614 passing tests
drove two PDFs at once. **A suite that is green on the path you did not change is not evidence
about the path you did.**

A sound version is NOT ten lines: the waiting is the network FETCH and the crashing is the PDF
PARSE, but `ingest_one` fuses them, so separating them is a real refactor of the ingestion
dispatch — a different proposal with a different cost, and not one a 2.94% measurement buys.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
