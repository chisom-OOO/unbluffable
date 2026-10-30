"""General numeric checker for forge templates: any exact answer, not only probabilities.

Reuses engine.answers for spoken forms ("eighteen out of sixty-seven", "two
thirteenths", "nought point two five"). Unlike `engine.answers.parse_number`, a bare
whole number or a decimal above 1 is a value here, and a sign is kept.

Acceptance: a stated fraction or ratio must equal the exact answer. A percentage,
decimal or whole number is accepted when it is the exact value rounded at the
precision the candidate stated, with at least 2 significant figures ("15%" for 2/13;
not "1" for 0.975), or when it is within the instance's tolerance. Nobody is asked
for more precision than they can say aloud. Everything is a `fractions.Fraction`, so
a number that is not a correct rounding of the answer can never be accepted.
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
            figure = m.group("pct").replace(",", "")
            yield m, StatedNumber(sign * Fraction(figure) / 100, "percent", figure)
        elif m.group("dec"):
            figure = m.group("dec").replace(",", "")
            yield m, StatedNumber(sign * Fraction(figure), "decimal", figure)
        else:
            figure = m.group("int").replace(",", "")
            yield m, StatedNumber(sign * Fraction(_int(figure)), "integer", figure)


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


MIN_FIGURES = 2


def precision(stated: StatedNumber) -> tuple[Fraction, int] | None:
    """(half a unit in the last stated place, as a share; significant figures) of a
    spoken percent, decimal or whole number, when the figure as said is known."""
    if stated.form == "fraction" or not stated.written:
        return None
    whole, _, places = stated.written.partition(".")
    figures = len((whole + places).lstrip("0"))
    half = Fraction(1, 2 * 10 ** len(places))
    return (half / 100 if stated.form == "percent" else half), figures


def rounds_to(stated: StatedNumber, target: Fraction) -> bool:
    """The stated figure is `target` correctly rounded at the stated precision, with at
    least MIN_FIGURES significant figures (an exact half either way counts)."""
    p = precision(stated)
    return p is not None and p[1] >= MIN_FIGURES and abs(stated.value - target) <= p[0]


def accepts(stated: StatedNumber, target: Fraction, tolerance: Fraction) -> bool:
    if stated.form == "fraction":
        return stated.value == target
    return stated.value == target or abs(stated.value - target) <= tolerance or rounds_to(stated, target)
