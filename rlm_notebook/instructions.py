"""Shared instruction fragments for every RLMTask that grounds its output in the corpus blob and
cites it — `AnswerQuestion` (`task.py`), the four Notebook Guide tasks (`guide.py`) and
`GeneratePodcastScript` (`audio.py`). Plain string constants/functions, not a class hierarchy: the
citation-marker rules are IDENTICAL text every one of these tasks needs (CLAUDE.md invariant 4), and
hand-duplicating that paragraph across SIX task classes (an independent audit found this docstring
still saying five, from before the podcast joined them) is a drift hazard waiting to happen —
a wording fix applied to one and forgotten in the
others would silently weaken the guarantee for whichever task got missed.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import zhconv.zhconv as _zh
from rlm_harness import (
    RLMTask,
    load_skills_as_tools,
    record_tool_call,
    render_skills_manifest,
)
from rlm_harness.tools.validation import make_schema_validator

#: This package's own recorded craft and measured failure modes, shipped INSIDE the wheel for the
#: same packaging reason the web assets are (`packages = ["rlm_notebook"]`, invariant 29): a
#: top-level directory works from a checkout and silently vanishes from an install. Verified by
#: building a wheel and reading its manifest, not by trusting the layout.
SKILLS_DIR = str(Path(__file__).resolve().parent / "skills")

#: The catalog header every task shares. ONE copy, like `CITATION_RULES` — six tasks each wording
#: their own invitation is exactly the drift invariant 13 exists to prevent.
_SKILLS_HEADER = (
    "<available_skills> — this project's own recorded craft and measured failure modes. "
    "`read_skill(name)` loads one in full. Consult the relevant skill BEFORE working: they record "
    "what was actually measured here, including several ways a run has been lost outright:"
)



def _marker_offenders(value: Any, path: str = "") -> list[str]:
    """Every path under `value` whose string holds a `[[SRC:...]]` marker.

    `quote` is EXEMPT: it is copied verbatim out of a source, and a source that itself contains the
    literal text `[[SRC:` would make an honest quote look like a violation. Every other string in
    every output model is the model's own prose, where a marker is always wrong.
    """
    from .citations import MARKER_PATTERN

    if isinstance(value, str):
        return [path] if MARKER_PATTERN.search(value) else []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [p for i, v in enumerate(value) for p in _marker_offenders(v, f"{path}[{i}]")]
    # No output model has a dict field today; skipping one silently would be a fail-open the moment
    # somebody adds one, and this walk exists precisely because a guard that fails open is worse
    # than no guard.
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in _marker_offenders(v, f"{path}[{k!r}]")]
    # `type(value)`, NOT the instance: pydantic deprecated instance access in 2.11 and removes it
    # in 3.0, and `getattr(instance, "model_fields", None)` would then return None — this walk
    # would return [] for every model and the guard would silently stop checking anything, on all
    # six tasks, with no error. A guard that fails OPEN is worse than one that raises.
    fields = getattr(type(value), "model_fields", None)
    if fields:
        out: list[str] = []
        for name in fields:
            if name == "quote":
                continue
            out += _marker_offenders(getattr(value, name), f"{path}.{name}" if path else name)
        return out
    return []


#: A corpus marker, capturing the coordinate INSIDE it (`s1|whole`, `s3|page:2`).
#: Deliberately a second, capturing spelling of `citations.MARKER_PATTERN` rather than an import:
#: `instructions.py` is imported by every task module and `citations.py` pulls in the schema, and
#: the pattern is three tokens long. If it ever grows, share it.
_COORDINATE_PATTERN = re.compile(r"\[\[SRC:([^\]]*)\]\]")


def coordinates_in(blob: str) -> set[str]:
    """Every `source_id|locator` pair that actually occurs as a marker in `blob`.

    This is the ground truth `citations.verify_citations` checks against server-side, computed from
    the SAME string the model was handed — so the pre-SUBMIT validator can reject an invented
    coordinate while the model can still fix it, instead of the reader finding it as a red
    "unverified" badge afterwards.
    """
    return {m.group(1) for m in _COORDINATE_PATTERN.finditer(blob)}


def _cited_coordinates(value: Any, path: str = "") -> list[tuple[str, str]]:
    """Every `(path, coordinate)` in `value` — anything carrying BOTH `source_id` and `locator`.

    Structural rather than an `isinstance(value, Citation)` check, for the same reason
    `_marker_offenders` walks by field: `instructions.py` stays free of the schema module, and a
    future citation-shaped model is covered without this function being remembered.
    """
    fields = getattr(type(value), "model_fields", None)
    if not fields:
        if isinstance(value, (list, tuple, set, frozenset)):
            return [p for i, v in enumerate(value) for p in _cited_coordinates(v, f"{path}[{i}]")]
        if isinstance(value, dict):
            return [p for k, v in value.items() for p in _cited_coordinates(v, f"{path}[{k!r}]")]
        return []
    if "source_id" in fields and "locator" in fields:
        return [(path or "citation", f"{value.source_id}|{value.locator}")]
    found: list[tuple[str, str]] = []
    for name in fields:
        child = getattr(value, name, None)
        found.extend(_cited_coordinates(child, f"{path}.{name}" if path else name))
    return found


#: Languages whose name pins a SCRIPT, for the runtime check below. Matching on the language NAME is
#: correct HERE and was wrong in the prompt: `arun` receives the RESOLVED value ("Traditional
#: Chinese"), while a class-level `instructions` string is composed at import time and only ever sees
#: the literal placeholder. That distinction is the whole reason `SCRIPT_PINNED` is worded
#: conditionally and this is not — do not "unify" them.
_SCRIPT_NEEDLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Both orderings of the English name, because `Chinese (Traditional)` is as ordinary a
    # spelling as `Traditional Chinese` and matched NOTHING — which turns the check off silently,
    # and `RN_OUTPUT_LANGUAGE`/the settings file accept any string (`clean_language` bounds length,
    # not the character set). `簡體` alongside `简体` for the same reason in the other direction: a
    # Traditional-script interface naming Simplified wrote it the Traditional way.
    ("hant", (
        "traditional chinese", "chinese (traditional", "zh-hant", "zh-tw", "zh-hk",
        "繁體", "繁体", "正體", "正体",
    )),
    ("hans", ("simplified chinese", "chinese (simplified", "zh-hans", "zh-cn", "简体", "簡體")),
)


def script_family(language: str | None) -> str | None:
    """`"hant"`, `"hans"`, or `None` when the language does not pin a Chinese script."""
    lowered = (language or "").lower()
    for family, needles in _SCRIPT_NEEDLES:
        if any(needle in lowered for needle in needles):
            return family
    return None


#: Characters the Big5/GB gate lets through that are REAL other-script forms, each measured on real
#: output rather than reasoned about. NOT the "~90-character hand table" this project condemned:
#: that was a hand list used as the WHOLE detector, and this is a short, sourced addition on top of
#: a derived one, in the SAFE direction only (things flagged despite the gate, never exemptions
#: from it).
#:
#: `体 适 荐 离 据` come from a sibling project's 89,160-Han-character deployment, where they
#: are five of its 29 real Simplified sites — `适` being the exact title (`執行環境與作業系統适配`)
#: that started its conversion work, which the bare gate would have left unfixed. `构 与 么` are
#: this project's own measured gaps; `么` is `怎么`, three times.
#:
#: The Big5 gate lets 131 single-character rewrites through (plus four curly quotation marks the
#: table turns into corner brackets). They are ENUMERATED here rather than characterised, because
#: an earlier note called them "almost exactly the genuinely ambiguous set" after reading the first
#: forty — and the tail is `机 网 于 云 并 确 范 优 价 复`, so `基于`, `机器`, `后端`, `优化` and
#: `价值` produced NO flag at all while `网络`, `标准`, `确认`, `范围` and `复杂` flagged one
#: character of two. That is this project's own subject matter.
#:
#: **SHARED is the unflagged half: a character with a live Traditional use the phrase table does
#: NOT protect.** Where the table DOES protect the Traditional word (`皇后`, `茶几`, `划船`,
#: `拮据`, `佣金`, `老么`, `尸位素餐`, `夸父`, `并州`, `云云`, `于右任`, `洪适`), flagging is safe
#: and the character is SIMPLIFIED — `_actionable` drops the self-suggestion.
#:
#: **A PROPER NOUN keeps a character SHARED even when the Simplified drift is commoner**, which is
#: where this list deliberately diverges from a sibling project's: `范` (范仲淹), `余` (余先生), `涌`
#: (東涌), `涂`, `朴` (朴槿惠), `杰`, `岳`, `郁`. Invariant 69 forbids translating a name, and an
#: obedient model told `范 -> 範` writes `範仲淹`. The sibling ranks them the other way because its
#: corpora are technical rather than literary corpora; the two answers are both defensible and the reason is recorded rather
#: than averaged. `吁` (長吁短嘆) and `咨` (咨文) are the same call on an idiom rather than a name.
#:
#: **Read once, character by character, and pinned.** `test_the_big5_letthrough_is_fully_classified`
#: asserts SHARED ∪ SIMPLIFIED is EXACTLY the table's Big5-encodable rewrites, so a zhconv upgrade
#: fails the build instead of silently adding an unread character to neither. Two independent
#: readings (this one and the sibling's) agreed on 72 and disagreed on 16; each caught real errors
#: in the other — `伙食`/`凶宅` would have been corrupted by mine, `昵稱`/`腌菜`/`昆虫`/`蚝油`/
#: `蝎子` were missed by mine.
_BIG5_SHARED: dict[str, frozenset[str]] = {
    "hant": frozenset(
        "丑仆伙余凄准凶占厘台吁吃咨咸唇喂岩岳峰干床征托斗朴杰栖栗涂涌游灶痳痴皂秘"
        "粽群肴膻苧范蒏蔂跖踊辟郁采里雇霉"
    ),
    "hans": frozenset(),
}


@lru_cache(maxsize=2)
def _wrong_script_chars(family: str) -> dict[str, str]:
    """Characters that are unambiguously the WRONG script for `family`, mapped to the right one.

    **The membership test is a legacy CODEC, not zhconv's own `SIMPONLY`/`TRADONLY` sets.** Those
    sets were tried first and are unusable here: `SIMPONLY` contains `干`, `台`, `群` and `里`,
    which are ordinary Traditional characters (`干預`, `一台`, `里程碑`) that a correct episode
    uses — measured on this project's own notebooks, where all four appear in prose that is not
    wrong. Big5 answers the question that actually matters, "does this glyph exist in the
    Traditional inventory at all", and `干` is in Big5 while `对` is not. zhconv is still needed,
    for the SUGGESTION (`对 -> 對`) and to bound the set to known Simplified forms, without which a
    rare Traditional character outside Big5 would be flagged.

    **Deliberately imperfect RECALL, and the loss is larger than the gate's arithmetic suggests.**
    Of the table's 3909 single-character rewrites, 131 are Big5-encodable; `_BIG5_SHARED` names
    the 52 with a live Traditional use the phrase table does not protect, and the other 79 are
    flagged despite the codec. Before that enumeration all 131 passed, which meant `基于`,
    `机器`, `后端`, `优化` and `价值` produced NO flag at all — this project's own subject matter.

    A missed character costs one wrong glyph on screen; a false one costs a rejection the model
    cannot satisfy (see `make_grounded_validator` and `_actionable`), so the uncertainty is spent
    on the safe side.
    """
    locale, codec = ("zh-hant", "big5") if family == "hant" else ("zh-hans", "gbk")
    mapping = _zh.getdict(locale)
    shared = _BIG5_SHARED[family]
    out: dict[str, str] = {}
    for src, dst in mapping.items():
        if len(src) != 1 or len(dst) != 1 or src == dst:
            continue
        if shared:
            # ENUMERATED direction: the codec's let-through was read character by character and the
            # ambiguous half named, so the codec has no vote left.
            if src in shared:
                continue
        else:
            # UNENUMERATED direction: the codec decides, exactly as it did for both before the
            # Traditional half was enumerated. **The asymmetry is the point.** Collapsing the two
            # branches — which a first version did by leaving the `encode` call with no `continue`
            # after it — makes the codec DEAD CODE, and since `_BIG5_SHARED["hans"]` is empty the
            # Simplified direction then had no gate at all: 652 flagged characters became 4,704,
            # taking every Japanese shinjitai (`鎖 響 際 係 門 軍 優`) and every retained Simplified
            # form (`瞭` in 一目瞭然, `徵` in 宫商角徵羽, `麼` in 幺麼小丑) with it. Found by an
            # independent review; no test saw it, because the one that checks this direction lists
            # only characters that are already Simplified and so are not sources in the table.
            try:
                src.encode(codec)
                continue
            except (UnicodeEncodeError, UnicodeError):
                pass  # not in the target's inventory at all — always the wrong script
        out[src] = _regional(src, dst, family)
    return out


def _regional(src: str, dst: str, family: str) -> str:
    """`src`'s Traditional form in the region's OWN standard, which `zh-hant` does not always give.

    zhconv's `zh-hant` target answers "a Traditional form", not "the form Taiwan writes": it maps
    `为` to `爲` where Taiwan writes `為`, and does the same for `众`/`眾`, `启`/`啟`, `账`/`帳` and
    `伪`/`偽` — 22 of the characters this gate flags. Telling a model to write `爲` is telling
    it to write a character no Taiwanese reader uses.

    **SINGLE-CHARACTER only, and that is not an optimisation.** `zh-tw` carries a VOCABULARY layer
    on top of the script one — it rewrites `鼠标` to `滑鼠`, two characters for two but not the
    same two — so running it over a whole string and zipping positionally would misalign. Fed one
    character it can only answer about the script. (Credit: a sibling project, which hit this first.)
    """
    if family != "hant":
        return dst
    # Mapped from the SOURCE, not from `zh-hant`'s answer: `账` reaches `賬` under `zh-hant` and
    # `zh-tw` leaves that alone, while `账` itself maps straight to `帳`. Measured — the two agree
    # on 24 of the 33 characters where anything differs, and `via src` is right on all NINE of the
    # rest (`账`->`帳` plus the eight Taiwan element names `鈽 鍅 鉲 鎝 鉳 鑀 鋂 錼`). An earlier
    # version of this comment said "four", which CLAUDE.md was corrected on and this was not.
    regional = _zh.convert(src, "zh-tw")
    return regional if len(regional) == 1 and regional != src else dst


@lru_cache(maxsize=2)
def _plain_script_chars(family: str) -> dict[str, str]:
    """The same table WITHOUT the regional preference — what `zh-hant` alone answers per character.

    Used only to ask whether the phrase-aware conversion made a CHOICE at a position. It is the
    difference between the two that carries the information; neither is the answer on its own.
    """
    locale = "zh-hant" if family == "hant" else "zh-hans"
    return {
        src: dst
        for src, dst in _zh.getdict(locale).items()
        if len(src) == 1 and len(dst) == 1 and src != dst
    }


def _suggest(text: str, family: str, wrong: dict[str, str]) -> dict[int, str]:
    """The right form for each offending character AT ITS POSITION in `text`, by index.

    **A character-level table cannot answer this and shipping one was a defect.** `历` is `歷` in
    `历史` and `曆` in `日历`; `发` is `發` in `发现` and `髮` in `头发`; `汇` is `匯` in `汇率` and
    `彙` in `词汇`. The table gives whichever form is commoner, so the validator was telling a model
    to write the wrong character roughly whenever the word was the less common one. (Found by
    a sibling project, which hit it in its converter; confirmed here against this project's own table.)

    So the whole string is converted — `zh-hant` is phrase-aware and script-only — and each
    offender takes the character at its own index. **The regional preference (invariant 66's
    `zh-tw` post-map) applies ONLY where the phrase-aware pass made no choice of its own**, i.e.
    where it agrees with the plain single-character answer: otherwise `日历` would lose `曆` to
    `歷`, which is the bug this function exists to fix, reintroduced from the other side.

    Falls back to the table if the conversion changes LENGTH, since the index would no longer mean
    anything. `zh-hant` is script-only and should not, but a future table is not this code's to
    promise.
    """
    locale = "zh-hant" if family == "hant" else "zh-hans"
    converted = _zh.convert(text, locale)
    plain = _plain_script_chars(family)
    if len(converted) != len(text):
        return {}
    out: dict[int, str] = {}
    for i, char in enumerate(text):
        if char not in wrong:
            continue
        in_context = converted[i]
        out[i] = wrong[char] if in_context == plain.get(char) else in_context
    return out


def _actionable(offenders: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Drop any offender whose "fix" is the character it already has.

    `_suggest` returns the phrase-aware conversion at the position, and when zhconv's phrase table
    leaves a character alone — because it is already correct in THAT word — that is the character
    itself. The rejection then read `据 -> 据` for `拮据` and `恒 -> 恒` for `恒生`, both ordinary
    Traditional, telling a model to rewrite a character into itself.

    **A rejection the model cannot satisfy is the failure `make_grounded_validator` exists to
    avoid** (invariant 66: advice it cannot follow costs the whole step budget looping on it). The
    once-per-run bound capped the damage and did not make the message coherent. Sixteen gate
    characters have such a context — `么 农 冲 别 叶 广 恒 据 汤 温 灯 联 胆 荐 适 鹰`, which covers
    `恒生`/`恒隆`/`恒基` in any finance corpus — so this is not the single documented `拮据`.

    The phrase-aware pass agreeing with the input IS the evidence the character is right in
    context; this reads that answer instead of overriding it."""
    return [(path, bad, good) for path, bad, good in offenders if good != bad]


def _script_offenders(
    value: Any, wrong: dict[str, str], family: str, path: str = ""
) -> list[tuple[str, str, str]]:
    """`(path, character, correct form)` for every wrong-script character in the model's own prose.

    `quote` is EXEMPT for `_marker_offenders`' reason ONE step sharper: a quote is copied verbatim
    out of a source, and this project's own corpora include JAPANESE, whose shinjitai collide with
    Chinese simplified forms — `学`, `会`, `国`, `峡` and thirty-odd others are flagged by the test
    above and are correct inside a Japanese quotation. The same walk shape as `_marker_offenders`,
    including reading `model_fields` off `type(value)` rather than the instance, for the reason
    recorded there: that walk must never fail open.
    """
    if isinstance(value, str):
        suggestions = _suggest(value, family, wrong)
        seen: dict[tuple[str, str], None] = {}
        for i, char in enumerate(value):
            if char in wrong:
                seen.setdefault((char, suggestions.get(i, wrong[char])), None)
        return [(path, bad, good) for bad, good in seen]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            o for i, v in enumerate(value) for o in _script_offenders(v, wrong, family, f"{path}[{i}]")
        ]
    if isinstance(value, dict):
        return [
            o for k, v in value.items() for o in _script_offenders(v, wrong, family, f"{path}[{k!r}]")
        ]
    fields = getattr(type(value), "model_fields", None)
    if fields:
        out: list[tuple[str, str, str]] = []
        for name in fields:
            if name == "quote":
                continue
            out += _script_offenders(
                getattr(value, name), wrong, family, f"{path}.{name}" if path else name
            )
        return out
    return []


#: How many times one run may be rejected for script drift. See `make_grounded_validator`: ONE was
#: measured too few in both directions — a model that ignores the list ships anyway, and a model
#: that complies is told `success` on its second call whether or not it fixed anything.
_SCRIPT_REPORT_LIMIT = 3

#: How much of a verdict reaches the trace. A rejection is short by construction (it names paths,
#: coordinates or characters); this only bounds a pathological one.
_VERDICT_CHARS = 1200


def make_grounded_validator(
    model: type,
    coordinates: Callable[[], set[str]] | None = None,
    script: Callable[[], str | None] | None = None,
) -> Callable[[str], str]:
    """`rlm_harness`'s schema validator PLUS a check the schema cannot express: no `[[SRC:...]]`
    marker anywhere in the model's own prose.

    **Why not a schema validator.** Nothing rewrites a stored artifact (the strip happens on the way
    OUT), so a notebook written before this validator existed holds whatever the model produced — the
    measured cases were a podcast with twenty markers across nineteen of its forty-seven utterances
    and an overview with four — and a field-level reject would make those files fail to LOAD, turning
    untidy data into a corrupt-notebook 409. The check belongs
    where the model can still act on it: before SUBMIT, in the tool the instructions already tell it
    to call.

    **Why every task and not just the podcast.** It was written for `GeneratePodcastScript`, whose
    failure was loud (the voice read the markers aloud). `GenerateSummary` had produced exactly the
    same defect, silently — four markers printed in an overview a user reported as a broken render.
    A guard on the one task that made a noise is a guard on the symptom.
    """
    schema_check = make_schema_validator(model)
    # The script check is BOUNDED, not one-shot, and the bound is the design rather than an
    # optimisation. Every other check here rejects something that would be WRONG — a leaked marker,
    # a coordinate that resolves to nothing. A Simplified character in Traditional prose is
    # COSMETIC, and the detector cannot distinguish it from a Japanese glyph the model is quoting
    # inline (`学`, `会`, `国` and `峡` are all shinjitai, and this project's own corpora carry
    # Japanese). A blocking check the model cannot satisfy spends the whole step budget looping and
    # loses a paid-for episode over one wrong glyph — the trade invariant 66 already refuses for
    # `tts.spoken_script`.
    #
    # **It was ONE, and one is too few for two measured reasons.** A live run rejected nine
    # characters with their fixes (`权`->`權`, `时`->`時`, `识`->`識`), the model submitted anyway,
    # and all nine shipped: the single look bought nothing there. Worse in the other direction, a
    # COMPLIANT model that fixes and re-validates gets `success` on its second call whether or not
    # it actually fixed anything — the bound was lying to the model that deserved the answer.
    # Three gives fix, verify, and one more fix; the budget cost is at most three planner turns
    # against `max_iterations=25`, and the run still can never be held hostage.
    script_reports = 0

    def validate(data_json_str: str) -> str:
        """Validate a JSON string against the expected output schema AND check that no
        `[[SRC:...]]` marker appears in your own prose. Pass your generated JSON here before
        emitting it as the final answer."""
        started = time.perf_counter()
        verdict = _validate(data_json_str)
        # `record_tool_call` is OPT-IN — every tool wrapper calls it or the event does not exist.
        # This one did not, so `tool_call` events were never written, the Trajectory drawer's
        # timeline was empty on EVERY run, and its empty state said "this run called no tools"
        # while the turn's own code pane showed `validate_podcastscript(...)` three lines away.
        # Upstream's `read_skill` records; ours simply never did.
        #
        # It also closes a measurement gap this project wrote down as a limitation: a live A/B of
        # the script check could not say whether the validator had FIRED, and that caveat had to be
        # attached to every number in it.
        #
        # The JSON is the whole artifact, so its LENGTH goes in and its TEXT does not — invariant
        # 52's rule for the ticker, and invariant 70's for the drawer.
        #
        # **The VERDICT is a different matter and the honest statement is narrower.** An earlier
        # version of this comment said "coordinates and character names, never source text", which
        # is false: the coordinate branch interpolates the offending `locator` VERBATIM, and its own
        # documented failure mode is a model writing the SECTION HEADING it was citing into that
        # field — text copied from a source. A failing SHAPE check also carries pydantic's
        # `input_value=` repr, which is head-and-tail of the artifact (short inputs are truncated
        # past recognition, long ones are not). Bounded by `_VERDICT_CHARS` and no more.
        #
        # Not tightened, because the model needs its real coordinate back to fix it, and a trace is
        # already the one artifact here that can hold full ingested source text in front of an API
        # with no authentication (invariants 25 and 29). This is inside that accepted posture; the
        # sentence that claimed otherwise was the defect.
        record_tool_call(
            validate.__name__,
            args={"chars": len(data_json_str)},
            ok=not verdict.startswith("Validation failed"),
            result=verdict[:_VERDICT_CHARS],
            duration_s=time.perf_counter() - started,
        )
        return verdict

    def _validate(data_json_str: str) -> str:
        verdict = schema_check(data_json_str)
        if verdict.startswith("Validation failed"):
            return verdict
        offenders = _marker_offenders(model.model_validate_json(data_json_str))
        if offenders:
            # The advice has to differ by WHERE the marker is. "put it in the citations entry" is a
            # dead end when the offender IS a citation field, and a model that loops on impossible
            # advice spends the whole step budget doing it.
            inside = [o for o in offenders if "citations[" in o or o.startswith("citations")]
            if inside:
                advice = (
                    "a `source_id` is the id alone (`s1`) and a `locator` the locator alone "
                    "(`whole`, `page:3`) — copy the PARTS out of the marker, never the marker itself"
                )
            else:
                advice = (
                    "remove it from the text and put the coordinate in the accompanying "
                    "`citations` entry instead"
                )
            where = ", ".join(offenders)
            verb = "contains" if len(offenders) == 1 else "contain"
            return (
                f"Validation failed: {where} {verb} a [[SRC:...]] marker. A marker is a coordinate "
                f"for the interface, not a citation and not something a reader or a listener should "
                f"ever see — {advice}."
            )
        known = coordinates() if coordinates else set()
        if known:
            wrong = [
                (path, coord)
                for path, coord in _cited_coordinates(model.model_validate_json(data_json_str))
                if coord not in known
            ]
            if wrong:
                # Show what a REAL one looks like rather than only naming the bad ones: the observed
                # failure is a model writing a section heading or a whole sentence as the `locator`,
                # and a rejection that just says "wrong" invites it to invent a different sentence.
                sample = sorted(known)[:4]
                listed = "; ".join(f"{path} -> {coord!r}" for path, coord in wrong[:5])
                return (
                    f"Validation failed: {len(wrong)} citation(s) point at a coordinate that does "
                    f"not exist in `sources` — {listed}. A `source_id`/`locator` pair is COPIED from "
                    f"a `[[SRC:<source_id>|<locator>]]` marker you actually found in `sources`, "
                    f"never composed from the passage's wording. Real markers in this corpus look "
                    f"like: {', '.join(repr(s) for s in sample)}. Search `sources` for the marker "
                    f"that precedes the block you are citing and copy both parts of it verbatim."
                )
        nonlocal script_reports
        family = script() if script else None
        if family and script_reports < _SCRIPT_REPORT_LIMIT:
            wrong = _wrong_script_chars(family)
            offenders = _actionable(
                _script_offenders(model.model_validate_json(data_json_str), wrong, family)
            )
            if offenders:
                script_reports += 1
                want = "Traditional" if family == "hant" else "Simplified"
                listed = "; ".join(f"{path}: {bad} -> {good}" for path, bad, good in offenders[:8])
                more = f" (and {len(offenders) - 8} more)" if len(offenders) > 8 else ""
                # CHARACTERS, not fields: an offender is a (path, char, fix) triple, so one field
                # holding four wrong characters used to be reported as "4 field(s)".
                fields = len({path for path, _, _ in offenders})
                where = "field" if fields == 1 else "fields"
                return (
                    f"Validation failed: {len(offenders)} character(s) across {fields} {where} "
                    f"belong to the wrong "
                    f"script for {want} Chinese — {listed}{more}. Rewrite each in {want} and "
                    f"validate again. A character that is verbatim from a source — a name or a "
                    f"title the sources spell that way, or Japanese text you are quoting — is the "
                    f"one exception, and this check cannot see the difference; keep those as they "
                    f"are."
                )
        return verdict

    validate.__name__ = f"validate_{model.__name__.lower()}"
    validate.__qualname__ = validate.__name__
    return validate


def apply_skills(task: Any, skills_dir: str | None) -> None:
    """Wire `skills_dir` onto `task` using `discovery="inject"`, the shape four sibling projects
    already use.

    The CATALOG (one `- name: description` line per skill) is prepended to the instructions at
    construction time, so the planner knows which skills exist without spending a `list_skills`
    round-trip; only `read_skill` becomes a tool, pulling a body just-in-time. That is the whole
    reason craft lives in a skill rather than in the prompt: the prompt is paid for on EVERY planner
    turn, a skill body only when the model decides it needs one.

    **What belongs in a skill and what does not.** A skill is read only if the model chooses to, so
    anything that CORRUPTS the output when skipped stays in the prompt — grounding, citations, the
    marker rule, language, the output shape. Craft and technique are the right things to move: work
    done without them is duller or more expensive, not wrong.

    `read_skill` resolves a NAME against the skills discovered here, so it cannot read an arbitrary
    path and never touches the network — invariants 1 and 14 are about a model reaching the outside
    world at generation time, which this does not do.

    ONE directory for every task, deliberately: `rlm_harness.skills.discover_skills` takes a single
    directory and does not recurse, and the catalog costs one line per skill. If it ever grows
    enough that a chat turn is paying to be told about podcast craft, that is the point to split it —
    not before.
    """
    if skills_dir is None or not os.path.isdir(skills_dir):
        return
    manifest = render_skills_manifest(skills_dir, header=_SKILLS_HEADER)
    # The MANIFEST decides, not the directory. `load_skills_as_tools` returns `read_skill`
    # regardless of whether anything was discovered, and that tool's own description tells the model
    # to pick "the ones listed in the skills manifest in your instructions" — so an empty or
    # skill-less directory used to hand the model a tool pointing at a list that was not there.
    if not manifest:
        return
    task.tools = [*task.tools, *load_skills_as_tools(skills_dir, discovery="inject")]
    # `instructions` is a ClassVar on RLMTask, so assigning it on the INSTANCE shadows the class
    # default for this task only — the same pattern the `tools` line above relies on.
    # CLOSED. `render_skills_manifest` only prepends the header, so without this every rule in
    # the task's own prompt — citations, language, validate-before-submit — reads as though it
    # were inside the skills element.
    task.instructions = manifest + "\n</available_skills>\n\n" + type(task).instructions


class GroundedTask(RLMTask):
    """The shape all SIX citation-grounded tasks share: skills by injection, and a pre-SUBMIT
    validator that can see the corpus THIS run was given.

    It exists because the six `__init__`s were byte-identical copies of the skills wiring, which is
    the drift hazard invariant 13 is about — and because the coordinate check below needs a per-RUN
    value, which a `ClassVar` tool list composed at import time cannot hold.

    **The validator is built here, from `output_model`, rather than declared as a `ClassVar` on each
    task.** Six `tools: ClassVar = [make_grounded_validator(X)]` lines were six chances for one task
    to be given a weaker validator than the others — which is exactly how the marker check spent a
    slice living only on the podcast.
    """

    #: A skills directory is a CONSTRUCTOR argument, matching the siblings: a test points it at a
    #: fixture and `None` turns it off, which a caller needs because a stale skill is worse than an
    #: absent one. Defaults ON, because a planner that has to be told to consult its own knowledge
    #: base will not.
    def __init__(self, *, skills_dir: str | None = SKILLS_DIR, **kw: Any) -> None:
        self._coordinates: set[str] = set()
        self._script: str | None = None
        self.tools = [
            make_grounded_validator(
                self.output_model, lambda: self._coordinates, lambda: self._script
            )
        ]
        apply_skills(self, skills_dir)
        super().__init__(**kw)

    async def arun(self, **inputs: Any) -> Any:
        """Capture this run's real coordinates before the model can cite anything.

        `sources` is the blob the model is about to explore, so the markers IN it are exactly the
        coordinates a citation may legitimately carry — the same ground truth
        `citations.verify_citations` uses server-side, just applied while the model can still act
        on it.

        **Deliberately fails OPEN when the blob yields no markers at all.** An empty set means "we
        do not know what is valid here", and rejecting every citation of a legitimate run is far
        worse than letting the server-side verification catch an invented one (invariant 5 is the
        guarantee; this is an early warning). Stated rather than left as an accident, because a
        guard that silently stops checking is the failure mode invariant 66 already records.
        """
        self._coordinates = coordinates_in(inputs.get("sources", "") or "")
        # The RESOLVED language, which only exists per run — the prompt beside it can only ever
        # hold the placeholder (see `_SCRIPT_NEEDLES`). `None` for any language that does not pin a
        # Chinese script, which is what makes the check inert for every other run.
        self._script = script_family(inputs.get("output_language"))
        return await super().arun(**inputs)


CITATION_RULES = """\
`sources` is a single string containing every source in this notebook. Each citable block is
preceded by a marker line of the EXACT form `[[SRC:<source_id>|<locator>]]`, immediately followed
by that block's text. Explore `sources` with Python — `.find()`, slicing, splitting on the literal
substring "[[SRC:" — to locate the passages relevant to your task; you have not already been shown
its contents above, so read before you answer.

Markers are OPAQUE identifiers, not something you compute. When a claim relies on a block, copy
that block's marker's `source_id` and `locator` VERBATIM into a `Citation` — never invent, alter,
guess, or reconstruct one from surrounding context. If you cannot find a marker supporting a claim,
leave that claim uncited rather than fabricating a citation for it; an uncited claim is honest, a
fabricated citation is not.

A `[[SRC:...]]` marker belongs in a `Citation` and NOWHERE ELSE. Never write one into your own
prose: it is a coordinate for the interface, and a reader sees it as a template that failed to
render. Cite by filling in a `Citation`; write the sentence as a sentence.

A `Citation`'s `quote` is copied VERBATIM from the block — never translated, paraphrased,
summarised, re-punctuated, or tidied. It is the reader's way of checking your prose against the
source's own words, and it stops being that the moment you rewrite it.

A `Citation`'s `answer_span` points the other way: copy into it, VERBATIM, the stretch of YOUR OWN
text that this citation supports — usually the sentence or clause making the claim. Two rules make
it usable:

- It must appear in your own text EXACTLY, character for character. The reader's interface finds it
  by searching your text for it; a span that has been re-typed, trimmed differently or
  re-punctuated simply will not be found.
- It is in YOUR language, not the source's. `quote` stays in the source's words and `answer_span`
  stays in yours — that is the whole point of having both, and it is what lets a reader writing in
  one language cite a source written in another.

Pick the smallest stretch that carries the claim: a sentence is usually right, a whole paragraph is
too coarse to be useful, and three words are too little to find reliably. If a citation supports
something you cannot point at that precisely, leave `answer_span` out — an absent span costs the
reader a highlight, and a wrong one sends them to the wrong sentence.

Do NOT number your citations in your own prose. No `[1]`, no `[2]`, no superscript markers written
into the sentence. The interface numbers them, from the order it renders them in, and draws each one
as a highlight on the exact span you named — so a number you write yourself becomes a SECOND
numbering next to that one, and the two disagree the moment they count differently. Write the
sentence as a sentence; the `citations` list is what carries the pointer.\
"""

#: The carve-out every language instruction composes with. Kept SEPARATE from the language rules
#: below so both of them share one copy (CLAUDE.md invariant 13) rather than each restating it.
#:
#: Naming only `quote` would be insufficient, and the omission is not cosmetic: a model told to
#: write everything in Chinese will equally localise a LOCATOR — `page:1` becomes `第1頁`, a YouTube
#: `ts:01:30` gets reformatted — and `citations.verify_citations` compares locators with an exact
#: `==`. Every such citation lands as UNVERIFIED, which reads to a user as the model having made the
#: citation up. Found by this slice's pre-implementation audit, before any of it was written.
VERBATIM_COORDINATES = """\
This does NOT apply to citation coordinates. A `source_id`, a `locator`, the `[[SRC:...]]` marker
syntax, and a `quote` are all copied EXACTLY as they appear in `sources`, in the source's own
language and formatting, however you are writing your prose. `page:1` stays `page:1`; a quote of
English text stays in English inside a Chinese answer. These are coordinates and evidence, not
prose, and a reader uses them to find the passage you are pointing at.\
"""


ACCUMULATE_LARGE_OUTPUTS = """\
If your finished output will not comfortably fit in ONE reply, do not write it in one. Keep a
Python variable in the sandbox, add to it across several REPL turns, print only its LENGTH to check
your progress, and SUBMIT the finished variable at the end. Never print the thing you are
accumulating — that spends the same budget a second time and brings the reply cap closer.

This is not a style preference. A reply that exceeds the per-call generation cap is cut off
mid-structure, the fragment does not parse, and the whole run is lost along with everything it had
already spent. Building across turns is what the sandbox is FOR; a short output that genuinely fits
in one reply should still be written in one.\
"""


PROPER_NOUNS = """\
Keep a proper noun as the source wrote it. Names of people, products, projects, companies,
standards and identifiers stay in their original script — "Trinity" stays "Trinity", not a
translation of the word "trinity"; "NASA" and "CVE-2026-1234" stay as they are. Translating one
costs the reader the exact term they would need to search for, which is the opposite of what a
research notebook is for. Everything AROUND the name still follows the language you were asked to
write in.\
"""


#: A language NAME can under-specify which characters to write, and the model treats the scripts as
#: interchangeable. Worded CONDITIONALLY and shipped UNCONDITIONALLY, for the same reason the
#: sentence above it says "write your prose in {language}" rather than naming one: the language
#: arrives as a SIGNATURE FIELD (invariant 39), so the prompt is composed at import time and cannot
#: know it. A first draft matched on the language name instead, and every call site passes the
#: placeholder — so it returned the empty string in production, for every task, from the day it
#: shipped. The characters are named IN the script because that cannot be read as a loose synonym.
SCRIPT_PINNED = """\
If that language has more than one script, its name does not settle which characters to write, and
Chinese is the case that matters. Write the variety you were asked for, throughout: Traditional
Chinese (繁體字) means `概覽` and `模組`, never `概览` or `模块`; Simplified Chinese (简体字) means
the reverse. A short field — a title, a follow-up question — follows this exactly as much as body
prose does. A PROPER NOUN is the exception and outranks it: a name the sources spell in the other
variety stays exactly as they spell it, because a reader who wants to look it up needs the string
the sources used.\
"""

#: Naming a language gets the language; it does not get the language's own IDIOM. A real run wrote
#: `源文` for "the source text" in Traditional Chinese output — a word-for-word rendering of the
#: English, where a reader expects `原文`. Nothing in the script rules above catches it: 源 and 原
#: are both perfectly ordinary Traditional characters, so this is a REGISTER failure rather than a
#: script one, and only a rule about wording can reach it.
NATURAL_REGISTER = (
    "Write the way someone writes natively in that language, not a word-for-word rendering of an"
    " English sentence. Use the term a reader of that language would use for a thing, not a"
    " literal compound assembled from the English words for it, and prefer the plain everyday"
    " word over the formal one. This applies to a follow-up question and a title as much as to"
    " a paragraph."
)


def chat_language_rule(language: str) -> str:
    """`AnswerQuestion`'s language rule. Separate from the artifact rule because chat has something
    no artifact has — a question, whose own language is the strongest available signal.

    `language` is never empty: callers pass a literal default rather than an empty string, so this
    paragraph is always present and never has to guard an absent value (a class-level `instructions`
    string is composed at import time and cannot know a per-request language — trying to have both a
    signature field and byte-identical prompts-when-unset was a contradiction this slice's audit
    caught in its own design)."""
    return (
        f"Write your prose in {language}. If that instruction names the question's own language,\n"
        f"answer in whatever language the question was asked in; when a follow-up is too short to\n"
        f"tell (\"and Y?\", \"why?\"), use the language of the most recent question in `history`.\n"
        f"Reading `history` for THAT is reading it as context for what the question refers to, which\n"
        f"is what it is for — it remains never a source of facts or citations.\n\n"
        f"{SCRIPT_PINNED}\n\n"
        f"{NATURAL_REGISTER}\n\n"
        f"{PROPER_NOUNS}\n\n"
        f"{VERBATIM_COORDINATES}"
    )


def artifact_language_rule(language: str) -> str:
    """The language rule for whole-corpus artifacts, which have no question to take a cue from."""
    return (
        f"Write your prose in {language}.\n\n{SCRIPT_PINNED}\n\n"
        f"{NATURAL_REGISTER}\n\n{PROPER_NOUNS}\n\n{VERBATIM_COORDINATES}"
    )


def validate_before_submit_rule(tool_name: str) -> str:
    """The "validate before SUBMIT" paragraph, parameterized by the schema-validator tool's name
    (`make_schema_validator` derives it from the output model as `validate_<model name, lowered>`).
    """
    return (
        f"Before you SUBMIT, validate your draft JSON with the `{tool_name}` tool, and only\n"
        f"submit after it reports success. **Put the SUBMIT in a LATER REPL turn than the call\n"
        f"that validated.** A cell that reads\n"
        f"`print({tool_name}(draft)); SUBMIT(draft)` has validated nothing: the answer is printed\n"
        f"where you cannot act on it, because the submit next to it has already run. Call it,\n"
        f"read what it says, and submit on the turn after — or branch on the result and only\n"
        f"submit in the success arm. A real run wrote exactly that pair, was told which character\n"
        f"was in the wrong script, and shipped it anyway.\n"
        f"It checks four things: the JSON shape, that no\n"
        f"`[[SRC:...]]` marker leaked into your own prose, that every citation's\n"
        f"`source_id`/`locator` pair actually occurs as a marker in `sources`, and — when you were\n"
        f"asked to write in a Chinese variety — that no character belongs to the other script.\n"
        f"The coordinate one is the common mistake: a locator is COPIED from a marker, never\n"
        f"composed from the passage's own wording. It still cannot confirm your prose faithfully\n"
        f"represents the passage you cited; that remains yours to get right."
    )
