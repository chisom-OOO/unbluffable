"""Stated numbers, the tolerance rule and committed-claim detection.

Tolerance (spec/02 §1): exact fraction match, or within ±1 percentage point when
the answer is stated as a percentage or decimal.

`normalise_numbers` rewrites spoken forms as digits first ("two thirteenths" →
"2/13", "nought point one five" → "0.15", "fifteen, sixteen percent" → "15
percent", taking the first of a range).

`committed_number` is a deterministic guard (spec/03 claim rules 1 and 3): a
number counts as a committed answer only after a claim marker, and never inside a
restated given, a hypothetical, or after a hedge.
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


# --- Spoken forms ----------------------------------------------------------

_ONES = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20),
))
_ONES["nought"] = 0
_TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
_DIGIT_WORDS = {w: v for w, v in _ONES.items() if v < 10} | {"oh": 0}
_ORDINAL_UNITS = {
    "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
}
_ORDINALS = _ORDINAL_UNITS | {
    "half": 2, "halve": 2, "quarter": 4, "tenth": 10, "eleventh": 11, "twelfth": 12,
    "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
    "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "hundredth": 100,
} | {w[:-1] + "ieth": v for w, v in _TENS.items()}  # twentieth ... ninetieth


def _alts(words) -> str:
    return "|".join(sorted(words, key=len, reverse=True))


# A denominator such as "thirteenths", "sixty-sevenths" or "halves".
_ORDINAL = re.compile(
    rf"\b(?:(?P<tens>{_alts(_TENS)})[\s-]+(?P<unit>{_alts(_ORDINAL_UNITS)})"
    rf"|(?P<ord>{_alts(_ORDINALS)}))(?:s|es)?\b",
    re.IGNORECASE,
)
_WORD = (
    rf"(?:\b(?:{_alts([*_ONES, *_TENS, 'hundred', 'thousand', 'point', 'and', 'oh', 'a'])})\b"
    r"|(?<![\d.,])\d+(?![.,]?\d))"
)
_WORD_RUN = re.compile(rf"{_WORD}(?:[\s-]+{_WORD})*", re.IGNORECASE)
_HELD = "\x00"  # brackets a held denominator while words are converted
_HELD_AFTER_NUMERATOR = re.compile(rf"(?<![\d.,])(\d+)\s+{_HELD}(\d+){_HELD}")
_HELD_LEFT = re.compile(rf"{_HELD}(\d+){_HELD}")
_OVER_IN = re.compile(r"(?<![\d.,])(\d+)\s+(?:over|in)\s+(\d+)(?![.,]?\d)", re.IGNORECASE)
_RANGE = re.compile(
    r"(?<![\d.,])(\d+(?:\.\d+)?)(?:\s*,\s+|\s+or\s+|\s+to\s+|\s*-\s*)\d+(?:\.\d+)?"
    r"(\s*(?:%|percent\b|per\s+cent\b))",
    re.IGNORECASE,
)


def _parse_int(t: list[str], i: int):
    """Parse a spoken whole number starting at t[i]; returns (value, next index) or None."""
    total, current, j, last = 0, 0, i, None
    while j < len(t):
        w = t[j]
        if w.isdigit():
            if last is not None:
                break
            return int(w), j + 1
        if w == "a" and last is None and j + 1 < len(t) and t[j + 1] in ("hundred", "thousand"):
            current, last = 1, "unit"
        elif w in _ONES:
            value = _ONES[w]
            if last in ("unit", "teen") or (last == "tens" and not 0 < value < 10):
                break
            current += value
            last = "teen" if value >= 10 else "unit"
        elif w in _TENS:
            if last in ("unit", "teen", "tens"):
                break
            current += _TENS[w]
            last = "tens"
        elif w == "hundred":
            if last not in ("unit", "teen"):
                break
            current *= 100
            last = "hundred"
        elif w == "thousand":
            if last in (None, "thousand", "and"):
                break
            total += (current or 1) * 1000
            current, last = 0, "thousand"
        elif (w == "and" and last in ("hundred", "thousand")
              and j + 1 < len(t) and (t[j + 1] in _ONES or t[j + 1] in _TENS)):
            last = "and"
        else:
            break
        j += 1
    if last is None:
        return None
    return total + current, j


def _parse_spoken(t: list[str], i: int):
    """A whole number or a decimal ("nought point one five", "point nine")."""
    whole = _parse_int(t, i)
    value, j = whole if whole else (None, i)
    if j < len(t) and t[j] == "point":
        digits, k = "", j + 1
        while k < len(t):
            if t[k] in _DIGIT_WORDS:
                digits += str(_DIGIT_WORDS[t[k]])
            elif t[k].isdigit():
                digits += t[k]
            else:
                break
            k += 1
        if digits:
            return f"{value or 0}.{digits}", k
    if value is None:
        return None
    return str(value), j


def _convert_run(m: re.Match) -> str:
    tokens = re.findall(_WORD, m.group(0), re.IGNORECASE)
    low = [tok.lower() for tok in tokens]
    out, changed, i = [], False, 0
    while i < len(tokens):
        parsed = _parse_spoken(low, i)
        if parsed is None:
            out.append(tokens[i])
            i += 1
            continue
        text, j = parsed
        changed = changed or text != tokens[i] or j != i + 1
        out.append(text)
        i = j
    return " ".join(out) if changed else m.group(0)


def normalise_numbers(text: str) -> str:
    """Rewrite spoken numbers as digits; text without spoken numbers is unchanged."""
    held: list[tuple[str, int]] = []

    def hold(m: re.Match) -> str:
        if m.group("ord"):
            den = _ORDINALS[m.group("ord").lower()]
        else:
            den = _TENS[m.group("tens").lower()] + _ORDINAL_UNITS[m.group("unit").lower()]
        held.append((m.group(0), den))
        return f"{_HELD}{len(held) - 1}{_HELD}"

    text = _ORDINAL.sub(hold, text.replace(_HELD, ""))
    text = _WORD_RUN.sub(_convert_run, text)
    # A denominator counts only after a numerator: "2 thirteenths" → "2/13",
    # while "a third party" is left alone.
    text = _HELD_AFTER_NUMERATOR.sub(lambda m: f"{m.group(1)}/{held[int(m.group(2))][1]}", text)
    text = _HELD_LEFT.sub(lambda m: held[int(m.group(1))][0], text)
    text = _OVER_IN.sub(r"\1/\2", text)
    return _RANGE.sub(r"\1\2", text)


def _iter_numbers(text: str):
    """Numbers in already-normalised text."""
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
    for _, stated in _iter_numbers(normalise_numbers(text)):
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
    text = normalise_numbers(text)
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
