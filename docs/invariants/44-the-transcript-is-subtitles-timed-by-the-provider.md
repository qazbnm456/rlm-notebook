# Invariant 44 — The transcript is subtitles timed by the provider

**The podcast transcript behaves like subtitles, and the timing comes from the PROVIDER rather
than from measuring the audio.** `TTSProvider.synthesize` returns each utterance's start offset
IN SECONDS — the unit is the contract between every provider, `Podcast.offsets` and `app.js`'s
seek handler, so it is stated rather than inferred from a call site;
every provider here already synthesizes utterance by utterance, so it knows them, and parsing MP3
frame headers to recover a number the provider already reports would be a second, worse
implementation.

**`Podcast.offsets` is a list PARALLEL to `utterances`, never a field on `Utterance`** —
`Utterance` is the MODEL's output shape, and the model has no idea how long its own words take to
say.

**The consumer's guard is MONOTONICITY, not length alone.** A provider reporting no boundaries
yields `[0.0, 0.0, ...]`, which is exactly as long as `utterances` — every line stamped `0:00`,
one row highlighted for the whole episode, every click seeking to zero. `app.js`'s `timed`
requires finite, non-negative, strictly increasing offsets AND a matching length; anything else
renders a plain transcript (which is also what a persisted episode from before this field existed
gets). Mis-aligned subtitles are worse than none.

**Match ANY `*Boundary` event from edge-tts, not `WordBoundary`** — the installed edge-tts
defaults to `boundary="SentenceBoundary"` and emits only that, so keying on `WordBoundary`
returns every offset as 0.0. The boundary sum APPROXIMATES each utterance's duration rather than
equalling it (measured error -0.049s..+0.066s per utterance, non-systematic in sign): fine for
highlighting a line, and NOT a drift that grows in one direction. The drift-free alternative is
named in the docstring and left as a follow-up.

**A provider holding raw samples gets its offsets from a PURE FUNCTION, `tts.sequence_offsets`,**
with the gap between utterances charged to the line BEFORE it, so an offset is where its own
line's audio starts. Extracting the bookkeeping out of `synthesize` is what lets CI check it at
all — with no extra, no model download and no audio. Both offset tests use THREE DIFFERENT
durations on purpose: with equal ones, a running-total bug and a correct implementation produce
the same list.

**`.btn` sets `color: inherit`, `text-decoration: none` and `display: inline-block` because it
has to work on an `<a>`** — the global reset covers `button` only. The `display` is what would
enrol this file's most-used class in invariant 36's tripwire the moment anyone `hidden`-toggles a
`.btn`, so `.btn` carries its own `[hidden] { display: none }` up front: a pre-emptive pairing,
not a tripwire the code trips today.

**The transcript scrolls in its OWN box (`.podcast-transcript.is-timed`) and the playhead follower
moves `scrollTop` directly, never `scrollIntoView`**, which walks EVERY scrollable ancestor and
would drag a listener who scrolled away back to the podcast panel every few seconds. Positions are
read from `getBoundingClientRect`, not `offsetTop`, so the arithmetic doesn't break if the box
stops being positioned. Only a TIMED transcript becomes a scroll box.

**A transcript line seeks on click, but not when the click was meant for something inside it** —
excluding `.citation, .citation-row, .citation-detail, .podcast-timecode`. `.citation-detail` is
the expanded trace payload appended as a SIBLING of the citation list inside the same utterance,
so clicking into that JSON would jump the player. `click` also fires on the mouseup ending a
drag-selection, so a non-collapsed selection suppresses the seek. The `play()` promise is caught:
a cleared file should be a silent no-op, not an unhandled rejection. **And a `.is-seekable:hover`
rule must not touch a property `.is-speaking` sets** — the fix is DISJOINT PROPERTIES, not lower
specificity: hover still wins any property it declares, it just declares `border-color`, which
`.is-speaking` (`background` + `box-shadow`) never sets.

---

One-line index: [`AGENTS.md`](../../AGENTS.md) · Incidents, measurements and superseded drafts: [`CHANGELOG.md`](../../CHANGELOG.md)
