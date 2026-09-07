# Invariant 53 — Renaming and generating a title are separate

**Renaming is a separate VERB from generating a title, and a rename REFUSES rather than derives.**
`PUT /notebooks/{id}/title` sets what a user typed; `POST` to the same path runs
`naming.SuggestTitle`. Setting a title is an instant write that always succeeds; generating one is a
model run that can fail, take seconds and be superseded — folding them into one endpoint would give
rename the failure semantics of a model call for no reason. `naming.normalize_title` is split out of
`clean_title` because the two callers need OPPOSITE things from an unusable value: generation falls
back to a derived label (a notebook must end up with one), a rename returns 422, because silently
substituting a derived title for what someone typed would be the UI lying. It still normalises,
because this API has no authentication and "a person typed it" is not a provenance claim.

**A model-authored title is NOT unique, so the picker orders by file mtime.** Since invariant 37
stopped showing the id anywhere, "which one did I touch last" is the only thing left to tell two
same-named notebooks apart. The timestamp is carried out-of-band (`notebook._MTIMES`/
`last_modified`) rather than added to the schema: it is a property of the FILE, and a schema field
would mean writing a timestamp nobody reads on every mutation.

**`derived_title` appears in BOTH `NotebookSummary` and `NotebookResponse`**, or the header says
"Untitled notebook" while the picker row shows a derived label for the same notebook. It is
`naming.fallback_title` and costs no model call, which matters because titling is lazy (invariant
37) — a notebook someone has only put sources into would otherwise sit in the picker as "Untitled"
forever.

**`GET /settings/choices` serves the settings page's dropdown values, and must never call
`_config()`** — invariant 41's reason, one endpoint further. A voice name is provider-specific, so
the answer depends on `RN_TTS_PROVIDER`, read straight from the environment; an unknown provider
yields an empty voice list rather than raising, so the page still renders. Served rather than
hardcoded in JS because a second copy would drift from `tts._LANGUAGE_VOICES`.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
