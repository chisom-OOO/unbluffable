"""Spoken probability normalization, keeping exact rational arithmetic."""

from fractions import Fraction
import re

from engine.answers import StatedNumber


ONES = dict(zip("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(20)))
ONES["nought"] = 0
TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
ORDINALS = {"half": 2, "halves": 2, "third": 3, "quarter": 4, "fourth": 4,
            "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
            "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13}


def integer(words, index):
    if index >= len(words):
        return None
    token = words[index]
    if token.isdigit():
        return int(token), index + 1
    if token in ONES:
        return ONES[token], index + 1
    if token in TENS:
        value, index = TENS[token], index + 1
        if index < len(words) and words[index] in ONES and 0 < ONES[words[index]] < 10:
            value += ONES[words[index]]
            index += 1
        return value, index
    return None


def number_from_text(text):
    if re.search(r"-\s*\d|\bminus\b", text.lower()):
        return None
    words = re.findall(r"\d+\.\d+|\d+|[a-z]+|[%/]", text.lower().replace("-", " "))
    for start in range(len(words)):
        token = words[start]
        kind = "decimal"
        if re.fullmatch(r"\d+\.\d+", token):
            value, index = Fraction(token), start + 1
        else:
            parsed = integer(words, start)
            if token == "point":
                value, index = Fraction(0), start
            elif parsed:
                value, index = Fraction(parsed[0]), parsed[1]
            else:
                continue
            if index < len(words) and words[index] in {"/", "over"}:
                denominator = integer(words, index + 1)
                if denominator is None or denominator[0] == 0:
                    return None
                value = value / denominator[0]
                index, kind = denominator[1], "fraction"
            elif index < len(words) and words[index] == "point":
                index += 1
                digits = ""
                while index < len(words):
                    word = words[index]
                    if word.isdigit():
                        digits += word
                    elif word in ONES and ONES[word] < 10:
                        digits += str(ONES[word])
                    else:
                        break
                    index += 1
                if not digits:
                    return None
                value += Fraction(int(digits), 10 ** len(digits))
            elif index < len(words) and words[index].removesuffix("s") in ORDINALS:
                value /= ORDINALS[words[index].removesuffix("s")]
                index, kind = index + 1, "fraction"
            elif index >= len(words) or words[index] not in {"%", "percent", "per"}:
                if value not in {0, 1}:
                    continue  # Bare counts are not probabilities.
        if index < len(words) and words[index] in {"%", "percent"}:
            value, kind = value / 100, "percent"
        elif words[index:index + 2] == ["per", "cent"]:
            value, kind = value / 100, "percent"
        return StatedNumber(value, kind)
    return None
