from __future__ import annotations

import pytest

from rlm_notebook.parsers.youtube import (
    CaptionError,
    _chunk,
    _dedupe_consecutive,
    _parse_vtt,
    _select_language,
    is_youtube_url,
    parse_youtube,
)

# Real WebVTT dumps captured live during this feature's design (a real public video's official
# and auto-generated English caption tracks) — not synthetic fixtures, so the parsing rules below
# are verified against actual YouTube caption quirks, not an idealized approximation of them.

_OFFICIAL_VTT = """\
WEBVTT
Kind: captions
Language: en

00:00:01.360 --> 00:00:03.040
[Music]

00:00:18.640 --> 00:00:21.880
We're no strangers to love

00:00:22.640 --> 00:00:26.960
You know the rules
and so do I
"""

# Includes the real "space-only line is part of a cue's OWN payload, not a separator" quirk and
# the "both lines blank" transition cue (after a bracketed-annotation cue) this feature's own
# pre-implementation audit found and required explicit handling for. Built line-by-line (not as a
# triple-quoted block) so a single-space content line is unambiguous in the source, never
# confusable with editor-stripped trailing whitespace.
_AUTO_VTT = "\n".join(  # noqa: FLY002 — an f-string is a worse fit than a literal line-by-line list here
    [
        "WEBVTT",
        "Kind: captions",
        "Language: en",
        "",
        "00:00:00.320 --> 00:00:18.790 align:start position:0%",
        " ",
        "[Music]",
        "",
        "00:00:18.790 --> 00:00:18.800 align:start position:0%",
        " ",
        " ",
        "",
        "00:00:18.800 --> 00:00:21.790 align:start position:0%",
        " ",
        "We're<00:00:19.039><c> no</c><00:00:19.359><c> strangers</c><00:00:19.840><c> to</c>",
        "",
        "00:00:21.790 --> 00:00:21.800 align:start position:0%",
        "We're no strangers to",
        " ",
        "",
        "00:00:21.800 --> 00:00:25.950 align:start position:0%",
        "We're no strangers to",
        (
            "love.<00:00:22.800><c> You</c><00:00:23.039><c> know</c><00:00:23.279><c> the</c>"
            "<00:00:23.600><c> rules</c><00:00:24.320><c> and</c><00:00:24.640><c> so</c><00:00:25.199><c> do</c>"
        ),
        "",
        "00:00:25.950 --> 00:00:25.960 align:start position:0%",
        "love. You know the rules and so do",
        " ",
        "",
    ]
)


# --- is_youtube_url -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
    ],
)
def test_is_youtube_url_true_for_known_hosts(url):
    assert is_youtube_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",  # a different product, not in scope
        "https://youtube.com.evil.example/watch",
        "not a url at all",
    ],
)
def test_is_youtube_url_false_for_everything_else(url):
    assert not is_youtube_url(url)


# --- _parse_vtt ------------------------------------------------------------------------------------


def test_parse_vtt_official_subtitles_flatten_one_entry_per_line():
    """Each line becomes its own entry — a genuine 2-line official dialogue cue ("You know the
    rules" / "and so do I") yields TWO entries, not one joined string; `_chunk` (not `_parse_vtt`)
    is what later reassembles them into a readable block."""
    cues = _parse_vtt(_OFFICIAL_VTT)
    assert [text for _, text in cues] == [
        "[Music]",
        "We're no strangers to love",
        "You know the rules",
        "and so do I",
    ]


def test_parse_vtt_auto_captions_strips_tags_and_flattens_every_line():
    cues = _parse_vtt(_AUTO_VTT)
    # Before dedup: the "rolling karaoke" duplication is still present here (that's
    # _dedupe_consecutive's job) — this test only checks tag-stripping and line flattening,
    # including the real both-lines-blank cue contributing no entries at all.
    assert [text for _, text in cues] == [
        "[Music]",
        "We're no strangers to",
        "We're no strangers to",
        "We're no strangers to",
        "love. You know the rules and so do",
        "love. You know the rules and so do",
    ]
    # No leftover <c> or timestamp tag markup anywhere.
    assert not any("<" in text for _, text in cues)


def test_parse_vtt_ignores_lines_with_no_timestamp():
    assert _parse_vtt("WEBVTT\nKind: captions\nLanguage: en\n") == []


# --- _dedupe_consecutive ---------------------------------------------------------------------------


def test_dedupe_consecutive_collapses_the_real_auto_caption_rolling_duplication():
    cues = _dedupe_consecutive(_parse_vtt(_AUTO_VTT))
    assert [text for _, text in cues] == [
        "[Music]",
        "We're no strangers to",
        "love. You know the rules and so do",
    ]


def test_dedupe_consecutive_is_a_no_op_on_already_clean_official_subtitles():
    cues = _dedupe_consecutive(_parse_vtt(_OFFICIAL_VTT))
    assert [text for _, text in cues] == [
        "[Music]",
        "We're no strangers to love",
        "You know the rules",
        "and so do I",
    ]


def test_dedupe_consecutive_keeps_non_adjacent_repeats():
    cues = [(0.0, "hello"), (1.0, "world"), (2.0, "hello")]
    assert _dedupe_consecutive(cues) == cues


def test_parse_vtt_handles_a_single_new_word_building_cue_with_no_tag_at_all():
    """A real bug an independent completion check found live: when a "building" auto-caption cue
    advances by exactly ONE new word, YouTube's real VTT often carries NO `<c>` tag at all (a tag
    wraps a word only when there are multiple new words to time within one line) — an earlier
    tag-presence-based design misclassified this as ordinary dialogue and left a duplicate word
    pair in the output (e.g. real data produced "...I'm thinking thinking of..."). Line-level
    flattening + adjacent dedup sidesteps the classification question: the settling transition
    cue's line is identical to the just-emitted line regardless of tags, so it always collapses."""
    vtt = "\n".join(  # noqa: FLY002 — a literal line list reads clearer than an f-string here
        [
            "WEBVTT",
            "",
            "00:00:25.960 --> 00:00:29.119 align:start position:0%",
            "I feel commitments from what I'm",
            "thinking",
            "",
            "00:00:29.119 --> 00:00:29.129 align:start position:0%",
            "thinking",
            " ",
            "",
        ]
    )
    cues = _dedupe_consecutive(_parse_vtt(vtt))
    assert [text for _, text in cues] == ["I feel commitments from what I'm", "thinking"]


# --- _chunk ------------------------------------------------------------------------------------


def test_chunk_groups_cues_within_the_same_window():
    cues = [(0.0, "a"), (10.0, "b"), (200.0, "c")]
    blocks = _chunk(cues, window=120.0)
    assert [b.locator for b in blocks] == ["ts:0:00", "ts:3:20"]
    assert blocks[0].text == "a b"
    assert blocks[1].text == "c"


def test_chunk_empty_input_returns_no_blocks():
    assert _chunk([]) == []


def test_chunk_formats_timestamps_past_one_hour():
    cues = [(3661.0, "an hour and a bit in")]
    blocks = _chunk(cues, window=120.0)
    assert blocks[0].locator == "ts:1:01:01"


# --- _select_language -------------------------------------------------------------------------


def test_select_language_prefers_the_video_language_when_available():
    assert _select_language({"en": [], "ja": []}, "ja") == "ja"


def test_select_language_falls_back_to_alphabetically_first_when_no_preference_matches():
    assert _select_language({"pt-BR": [], "de-DE": []}, "en") == "de-DE"


def test_select_language_none_when_nothing_available():
    assert _select_language({}, "en") is None


# --- parse_youtube (full pipeline, injected downloader) --------------------------------------------


def test_parse_youtube_end_to_end_with_the_real_auto_caption_dump():
    calls = []

    def fake_downloader(url: str) -> str:
        calls.append(url)
        return _AUTO_VTT

    source = parse_youtube("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "s1", downloader=fake_downloader)

    assert calls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
    assert source.kind == "youtube"
    assert source.origin == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert len(source.blocks) == 1
    assert source.blocks[0].locator == "ts:0:00"
    assert source.blocks[0].text == "[Music] We're no strangers to love. You know the rules and so do"


def test_parse_youtube_raises_caption_error_when_downloader_yields_no_usable_text():
    def empty_downloader(url: str) -> str:
        return "WEBVTT\n"

    with pytest.raises(CaptionError):
        parse_youtube("https://www.youtube.com/watch?v=none", "s1", downloader=empty_downloader)


def test_caption_error_is_a_value_error_subclass():
    """Not a style nit — cli._prepare and api.add_sources both catch ingestion failures as
    `except (FetchError, ValueError, OSError)`; only a `ValueError` subclass lands a captionless
    video as a clean ingestion-time error instead of an unhandled 500/traceback. Found by this
    feature's own pre-implementation audit before any code was written."""
    assert issubclass(CaptionError, ValueError)
