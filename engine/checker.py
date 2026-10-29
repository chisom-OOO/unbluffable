"""General numeric checker for forge templates: any exact answer, not only probabilities.

Reuses engine.answers for spoken forms ("eighteen out of sixty-seven", "two
thirteenths", "nought point two five"). Unlike `engine.answers.parse_number`, a bare
whole number or a decimal above 1 is a value here, and a sign is kept.

Acceptance: a stated fraction or ratio must equal the exact answer; a percentage,
decimal or whole number may differ from it by at most the instance's tolerance.
Everything is a `fractions.Fraction`, so a wrong number can never be accepted.
"""

from __future__ import annotations

import re
from fractions import Fraction

from engine.answers import StatedNumber, normalise_numbers

_INT = r"\d{1,3}(?:,\d{3})+|\d+"
_SIGN = r"(?P<sign>-|−|\bminus\s+|\bnegative\s+)?"
_VALUE = re.compile(
    rf"(?<![\w.,/]){_SIGN}(?:"
    rf"(?P<num>{_INT})\s+out\s+of\s+(?P<den>{_INT})"
    rf"|(?P<fnum>{_INT})\s*/\s*(?P<fden>{_INT})"
    rf"|(?P<pct>(?:{_INT})(?:\.\d+)?|\.\d+)\s*(?:%|percent\b|per\s+cent\b)"
    rf"|(?P<dec>(?:{_INT})?\.\d+)"
    rf"|(?P<int>{_INT})"
    rf")(?![\d/]|\.\d)",
    re.IGNORECASE,
)
_EXACT = re.compile(r"^\s*(-?)\s*(?:(\d+)\s*/\s*(\d+)|(\d+(?:\.\d+)?|\.\d+)(\s*%)?)\s*$")


def _int(s: str) -> int:
    return int(s.replace(",", ""))


def _iter_values(text: str):
    for m in _VALUE.finditer(normalise_numbers(text)):
        sign = -1 if m.group("sign") else 1
        if m.group("num") or m.group("fnum"):
            num, den = (m.group("num"), m.group("den")) if m.group("num") else (m.group("fnum"), m.group("fden"))
            if _int(den) == 0:
                continue
            yield m, StatedNumber(sign * Fraction(_int(num), _int(den)), "fraction")
        elif m.group("pct"):
            yield m, StatedNumber(sign * Fraction(m.group("pct").replace(",", "")) / 100, "percent")
        elif m.group("dec"):
            yield m, StatedNumber(sign * Fraction(m.group("dec").replace(",", "")), "decimal")
        else:
            yield m, StatedNumber(sign * Fraction(_int(m.group("int"))), "integer")


def parse_value(text: str) -> StatedNumber | None:
    """First number in the text, in any form ("18/67", "18 out of 67", "26.9%", "0.27", "42")."""
    for _, stated in _iter_values(text):
        return stated
    return None


def values_in(text: str) -> list[Fraction]:
    """Every number in the text, percentages as shares (for the solution-map position)."""
    return [stated.value for _, stated in _iter_values(text)]


def given_values(text: str) -> tuple[Fraction, ...]:
    """Numbers a question states: each as written, and percentages also as shares."""
    out = []
    for m, stated in _iter_values(text):
        out.append(stated.value)
        if stated.form == "percent":
            out.append(Fraction(m.group("pct").replace(",", "")))
    return tuple(dict.fromkeys(out))


def parse_exact(value) -> Fraction:
    """An instance's stored value: "18/67", "0.25", "25%", "-3" or a JSON number."""
    if isinstance(value, bool):
        raise ValueError(f"not an exact value: {value!r}")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    if not isinstance(value, str):
        raise ValueError(f"not an exact value: {value!r}")
    m = _EXACT.match(value)
    if not m:
        raise ValueError(f"not an exact value: {value!r}")
    sign = -1 if m.group(1) else 1
    if m.group(2):
        if int(m.group(3)) == 0:
            raise ValueError(f"zero denominator: {value!r}")
        return sign * Fraction(int(m.group(2)), int(m.group(3)))
    result = Fraction(m.group(4))
    return sign * (result / 100 if m.group(5) else result)


def accepts(stated: StatedNumber, target: Fraction, tolerance: Fraction) -> bool:
    if stated.form == "fraction":
        return stated.value == target
    return abs(stated.value - target) <= tolerance
