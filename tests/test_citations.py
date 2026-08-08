from __future__ import annotations

from rlm_notebook.citations import verify_citations
from rlm_notebook.corpus import Corpus
from rlm_notebook.schema import Citation, Source, SourceBlock


def _corpus() -> Corpus:
    corpus = Corpus()
    corpus.add(
        Source(
            id="s1",
            kind="pdf",
            origin="paper.pdf",
            blocks=[
                SourceBlock(locator="page:1", text="Apples are red or green."),
                SourceBlock(locator="page:2", text="Oranges are orange."),
            ],
        )
    )
    return corpus


def test_valid_citation_verifies():
    result = verify_citations(
        [Citation(source_id="s1", locator="page:1", quote="Apples are red or green.")], _corpus()
    )
    assert result[0].verified is True
    assert result[0].reason is None


def test_unknown_source_id_is_unverified_not_dropped():
    result = verify_citations([Citation(source_id="nope", locator="page:1", quote="x")], _corpus())
    assert len(result) == 1
    assert result[0].verified is False
    assert "nope" in result[0].reason


def test_unknown_locator_is_unverified_not_dropped():
    result = verify_citations([Citation(source_id="s1", locator="page:99", quote="x")], _corpus())
    assert len(result) == 1
    assert result[0].verified is False
    assert "page:99" in result[0].reason


def test_order_and_count_preserved():
    citations = [
        Citation(source_id="s1", locator="page:1", quote="a"),
        Citation(source_id="s1", locator="page:99", quote="b"),
        Citation(source_id="s1", locator="page:2", quote="c"),
    ]
    result = verify_citations(citations, _corpus())
    assert [v.verified for v in result] == [True, False, True]


def test_does_not_check_quote_faithfulness():
    """CLAUDE.md invariant 5: coordinate existence only. A wildly wrong quote at a real
    coordinate still verifies — this module makes no claim about content faithfulness."""
    result = verify_citations(
        [Citation(source_id="s1", locator="page:1", quote="Oranges are purple dinosaurs.")],
        _corpus(),
    )
    assert result[0].verified is True


def test_an_answer_span_is_kept_only_when_it_occurs_verbatim_in_the_prose():
    """The signature interaction — a citation drawn as a stroke through the sentence it backs — is
    located by searching the prose for this span. It exists because the OLD way (searching for the
    `quote`) stopped working at invariant 39: the prose follows the reader's language while the
    quote stays in the source's, so the two never share a substring and a user reported the strokes
    had simply disappeared.

    Same coordinate-existence discipline invariant 5 applies to `source_id`/`locator`, pointed at
    the model's own text: a span that cannot be found is DROPPED, and the citation survives without
    it. Losing a highlight costs a reader little; highlighting the wrong sentence costs them trust.
    """
    from rlm_notebook.citations import locate_answer_spans
    from rlm_notebook.schema import Citation

    prose = "根據資料：先發射的是航海家2號。它比航海家1號早了十六天。"

    def cite(span):
        return Citation(source_id="s1", locator="whole", quote="English evidence", answer_span=span)

    located = locate_answer_spans(
        [
            cite("先發射的是航海家2號"),
            cite("  它比航海家1號早了十六天  "),  # stray whitespace is not a different sentence
            cite("這句話不在答案裡"),
            cite(None),
        ],
        prose,
    )

    assert [c.answer_span for c in located] == [
        "先發射的是航海家2號",
        "它比航海家1號早了十六天",
        None,
        None,
    ]
    # Nothing is ever dropped, only the unlocatable span (invariant 5's "flag, never hide").
    assert len(located) == 4
    assert all(c.quote == "English evidence" for c in located)


def test_the_span_and_the_quote_are_in_different_languages_on_purpose():
    """`quote` stays in the SOURCE's words (it is evidence a reader checks) and `answer_span` stays
    in the model's (it is where the highlight goes). Having both is what lets someone reading in one
    language cite a source written in another — the case that broke the old single-field design."""
    from rlm_notebook.citations import locate_answer_spans
    from rlm_notebook.schema import Citation

    prose = "航海家2號比較早發射。"
    citation = Citation(
        source_id="s1",
        locator="whole",
        quote="Voyager 2, launched sixteen days EARLIER on August 20, 1977",
        answer_span="航海家2號比較早發射",
    )
    located = locate_answer_spans([citation], prose)[0]
    assert located.answer_span == "航海家2號比較早發射"
    assert located.quote == citation.quote  # untouched
    # ...and the quote alone could never have located anything in this prose, which is the bug.
    assert citation.quote not in prose


def test_a_corpus_marker_never_reaches_the_reader():
    """The marker is a coordinate the model is told to echo into a `Citation` (invariant 4), never
    into the sentence it is writing — but it reads a corpus full of them, and a real run ended four
    of five paragraphs with a literal `[[SRC:s1|whole]]` on screen. A user reported it as a failed
    render, which is a fair reading: it looks exactly like a template that did not resolve."""
    from rlm_notebook.citations import strip_markers

    assert strip_markers("A claim.[[SRC:s1|whole]]") == "A claim."
    assert strip_markers("Mid [[SRC:s2|page:3]] sentence.") == "Mid sentence."
    assert strip_markers("Para one.\n\n[[SRC:s1|whole]]\n\nPara two.") == "Para one.\n\nPara two."
    # Untouched when there is nothing to strip — including the empty and None cases.
    assert strip_markers("Ordinary prose.") == "Ordinary prose."
    assert strip_markers("") == ""
    assert strip_markers(None) == ""
    # A locator with a pipe or a colon in it is still one marker, not a partial match.
    assert strip_markers("x[[SRC:s1|ts:01:20]]y") == "xy"


def test_a_span_carrying_a_marker_still_matches_the_stripped_prose():
    """The model copies `answer_span` out of its own text, so if the text had a marker the span can
    have one too. Both get the SAME strip, or the span silently stops being locatable and the
    highlighter stroke disappears — which is invariant 49's whole failure mode, one layer down."""
    from rlm_notebook.citations import locate_answer_spans, strip_markers
    from rlm_notebook.schema import Citation

    raw = "Voyager left in 2012.[[SRC:s1|whole]] It still transmits."
    prose = strip_markers(raw)
    located = locate_answer_spans(
        [Citation(source_id="s1", locator="whole", quote="q",
                  answer_span="Voyager left in 2012.[[SRC:s1|whole]]")],
        prose,
    )
    assert located[0].answer_span == "Voyager left in 2012."


def test_the_punctuation_tidy_only_touches_where_a_marker_was():
    """A GLOBAL space-before-punctuation rule normalises text that never had a marker — French
    typographic spacing is the case an independent review found — and because `strip_markers`
    early-returns on a marker-free string, the prose and the `answer_span` would then get DIFFERENT
    normalisation and the span would stop matching. That is invariant 49's failure mode one layer
    down: the highlighter stroke silently disappears."""
    from rlm_notebook.citations import locate_answer_spans, strip_markers
    from rlm_notebook.schema import Citation

    prose = strip_markers("C'est vrai ! Voir [[SRC:s1|whole]].")
    assert prose == "C'est vrai ! Voir.", f"spacing outside the marker's hole was altered: {prose!r}"

    located = locate_answer_spans(
        [Citation(source_id="s1", locator="whole", quote="q", answer_span="C'est vrai !")], prose
    )
    assert located[0].answer_span == "C'est vrai !", "the stroke was dropped by an over-broad tidy"
