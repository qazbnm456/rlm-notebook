

def test_a_language_whose_name_underspecifies_its_script_gets_the_script_pinned():
    """Naming a language does not name its SCRIPT. A sibling project shipped a Traditional Chinese
    document set whose body text were Traditional while every page TITLE came back Simplified, so the nav
    and the page disagreed on screen — the rule is stated in the script itself, which cannot be read
    as a loose synonym.

    Not reproduced in this project: every model-authored field in two real notebooks scored zero
    Simplified-only characters. This is insurance against a measured sibling failure.
    """
    from rlm_notebook.instructions import artifact_language_rule, chat_language_rule

    for rule in (artifact_language_rule, chat_language_rule):
        assert "繁體字" in rule("Traditional Chinese")
        assert "繁體字" in rule("zh-Hant")
        assert "简体字" in rule("Simplified Chinese")
        # A language whose name already pins one script gets no paragraph about scripts at all.
        assert "繁體字" not in rule("English") and "简体字" not in rule("English")


def test_every_language_rule_asks_for_native_wording_not_a_calque():
    """The observed failure was LEXICAL, not script: a Traditional Chinese answer wrote `源文` for
    "the source text" where a reader expects `原文`. 源 and 原 are both ordinary Traditional
    characters, so no script rule can reach it — only a rule about wording."""
    from rlm_notebook.instructions import (
        NATURAL_REGISTER,
        artifact_language_rule,
        chat_language_rule,
    )

    assert NATURAL_REGISTER in artifact_language_rule("Traditional Chinese")
    assert NATURAL_REGISTER in chat_language_rule("Traditional Chinese")
    # It is about wording, so it must apply to a language with one script too.
    assert NATURAL_REGISTER in artifact_language_rule("English")


def test_a_proper_noun_outranks_the_script_rule():
    """The two rules collide, and nothing said which wins until a live run made them collide.

    A Traditional Chinese podcast carried `霍尔木兹海峡` — a Simplified place name — nine times,
    verbatim from a Simplified source. `PROPER_NOUNS` says never translate a name; the script rule
    says write Traditional throughout. The model chose the name, which is right (converting it costs
    the reader the string they would search for, invariant 69), but it chose it without being told.
    """
    from rlm_notebook.instructions import artifact_language_rule, chat_language_rule

    for rule in (artifact_language_rule, chat_language_rule):
        text = rule("Traditional Chinese")
        assert "PROPER NOUN is the exception" in text
        # Stated INSIDE the script rule, not merely nearby: a reader of the script paragraph has to
        # meet the exception without having to hold the later paragraph in mind.
        script_at = text.index("繁體字")
        assert text.index("PROPER NOUN is the exception") > script_at
        assert text.index("PROPER NOUN is the exception") < text.index("Write the way someone")
