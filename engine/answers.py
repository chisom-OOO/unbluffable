"""Stated numbers, the tolerance rule and committed-claim detection.

Tolerance (spec/02 §1): exact fraction match, or within ±1 percentage point when
the answer is stated as a percentage or decimal.

`committed_number` is a deterministic guard over digit-form text (spec/03 claim
rules 1 and 3): a number counts as a committed answer only after a claim marker,
and never inside a restated given, a hypothetical, or after a hedge. Spoken-word
normalisation ("two thirteenths") belongs to voice/ and runs before this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

PERCENTAGE_POINT = Fraction(1, 100)

Form = Literal["fraction", "percent", "decimal"]


@dataclass(frozen=True)
class StatedNumber:
    value: Fraction
    form: Form


def matches(stated: StatedNumber, target: Fraction) -> bool:
    if stated.form == "fraction":
        return stated.value == target
    return abs(stated.value - target) <= PERCENTAGE_POINT


_INT = r"\d{1,3}(?:,\d{3})+|\d+"
_NUMBER = re.compile(
    rf"(?<![\d.,/])(?:"
    rf"(?P<num>{_INT})\s+out\s+of\s+(?P<den>{_INT})"
    rf"|(?P<fnum>\d+)\s*/\s*(?P<fden>\d+)"
    rf"|(?P<pct>\d+(?:\.\d+)?)\s*(?:%|percent\b|per\s+cent\b)"
    rf"|(?P<dec>\d*\.\d+)"
    rf")(?![\d/])",
    re.IGNORECASE,
)


def _to_int(s: str) -> int:
    return int(s.replace(",", ""))


def _iter_numbers(text: str):
    for m in _NUMBER.finditer(text):
        if m.group("num"):
            den = _to_int(m.group("den"))
            if den == 0:
                continue
            yield m, StatedNumber(Fraction(_to_int(m.group("num")), den), "fraction")
        elif m.group("fnum"):
            den = int(m.group("fden"))
            if den == 0:
                continue
            yield m, StatedNumber(Fraction(int(m.group("fnum")), den), "fraction")
        elif m.group("pct"):
            yield m, StatedNumber(Fraction(m.group("pct")) / 100, "percent")
        else:
            value = Fraction(m.group("dec"))
            if value <= 1:  # bare decimals above 1 are not probabilities
                yield m, StatedNumber(value, "decimal")


def parse_number(text: str) -> StatedNumber | None:
    """First fraction, percentage or decimal in the text (bare counts are ignored)."""
    for _, stated in _iter_numbers(text):
        return stated
    return None


# --- Claim rules -----------------------------------------------------------

_FILLER = r"(?:(?:about|around|roughly|approximately|exactly|just|only|basically|nearly|almost|close\s+to|like)\s+)*"
_PRE_MARKER = re.compile(
    r"(?:"
    r"\bthe\s+answer\s+is"
    r"|\banswer'?s"
    r"|\bso\s+(?:the\s+)?(?:probability|chance|likelihood|posterior)\b[^.?!]{0,60}?\s+is"
    r"|\b(?:probability|chance|likelihood|posterior)\s+is"
    r"|\bso\s+it(?:'s|\s+is)"
    r"|\bso\s+that(?:'s|\s+is)"
    r"|\bi\s+get"
    r"|\bi'?d\s+say"
    r"|\bcomes\s+(?:out\s+)?(?:to|at)"
    r"|\bworks\s+out\s+(?:to|at)"
    r"|\bequals"
    r"|="
    rf")\s*{_FILLER}$",
    re.IGNORECASE,
)
_POST_MARKER = re.compile(
    r"^\s*(?:likely\b|chance\s+(?:that\s+)?it(?:'s|\s+is|\s+was)\b)",
    re.IGNORECASE,
)
_HEDGE = re.compile(r"\b(?:maybe|perhaps|might|possibly)\b", re.IGNORECASE)
_HYPOTHETICAL = re.compile(
    r"\b(?:if\s+it\s+(?:were|was)|what\s+if|suppose|supposing|imagine|hypothetically|say\s+it'?s)\b",
    re.IGNORECASE,
)
_RETRACTION = re.compile(
    r"\bwait\b|\bno\s*[,.!]|\bactually\b|\bhang\s+on\b|\bscratch\s+that\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.?!]+(?=\s|$)")


def _sentence_start(text: str, pos: int) -> int:
    start = 0
    for m in _SENTENCE_END.finditer(text, 0, pos):
        start = m.end()
    return start


def committed_number(text: str) -> StatedNumber | None:
    """The last committed answer in the text, or None if nothing was committed.

    Restated givens ("the detector catches 90% of fraud") have no claim marker
    and are never returned.
    """
    last = None
    for m, stated in _iter_numbers(text):
        before = text[_sentence_start(text, m.start()) : m.start()]
        after = text[m.end() :]
        if not (_PRE_MARKER.search(before) or _POST_MARKER.match(after)):
            continue
        if _HEDGE.search(before) or _HYPOTHETICAL.search(before):
            continue
        last = (m, stated)
    if last is None:
        return None
    m, stated = last
    if _RETRACTION.search(text[m.end() :]):
        return None  # retracted with nothing in its place
    return stated
