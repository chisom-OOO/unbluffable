"""Exact interview friendliness and deterministic spoken question text."""
import re
from fractions import Fraction

from forge.errors import Reject


def mental_arithmetic(value):
    """Score exact answer forms; never round a hard answer to qualify it."""
    value = Fraction(value)
    score, basis = 0, "complex_fraction"
    if value.denominator == 1:
        score, basis = 3, "integer"
    elif value.denominator <= 100:
        score, basis = 2, "simple_fraction"
    else:
        denominator, twos, fives = value.denominator, 0, 0
        while denominator % 2 == 0:
            denominator //= 2
            twos += 1
        while denominator % 5 == 0:
            denominator //= 5
            fives += 1
        if denominator == 1:
            places = max(twos, fives)
            coefficient = abs(value.numerator) * 2 ** (places - twos) * 5 ** (places - fives)
            significant = len(str(coefficient).strip("0"))
            if significant <= 2:
                score, basis = 1, "clean_decimal_or_percent"
    return {"interview_friendly": score > 0, "interview_friendly_score": score,
            "interview_friendly_basis": basis}


def validate_wording(text):
    if ("$" in text or re.search(r"\\[A-Za-z]+", text)
            or re.search(r"\b1\s*\*", text)
            or re.search(r"(?:\d+|\{[a-z0-9_]+\})\s+(?:squared|cubed)\s+"
                         r"(?:observations?|samples?|people|trials?|flips?|draws?|cards?|items?)\b", text, re.I)):
        raise Reject("wording", "not_spoken_english")


_SMALL = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
          "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = ("zero ten twenty thirty forty fifty sixty seventy eighty ninety").split()


def cardinal(value):
    value = int(value)
    if value < 0:
        return "minus " + cardinal(-value)
    if value < 20:
        return _SMALL[value]
    if value < 100:
        return _TENS[value // 10] + ("-" + _SMALL[value % 10] if value % 10 else "")
    if value < 1000:
        return _SMALL[value // 100] + " hundred" + (" and " + cardinal(value % 100) if value % 100 else "")
    for power, label in ((15, "quadrillion"), (12, "trillion"), (9, "billion"), (6, "million"), (3, "thousand")):
        unit = 10 ** power
        if unit <= value < unit * 1000:
            return cardinal(value // unit) + " " + label + (" " + cardinal(value % unit) if value % unit else "")
    # A finite unambiguous reading even for an unusually large integer.
    return " ".join(_SMALL[int(digit)] for digit in str(value))


def numeric_words(token):
    token = token.replace(",", "")
    percent = token.rstrip().endswith("%")
    if percent:
        token = token.rstrip()[:-1].strip()
    if "/" in token:
        numerator, denominator = token.split("/")
        result = cardinal(numerator.strip()) + " over " + cardinal(denominator.strip())
    elif "e" in token.casefold():
        mantissa, exponent = token.casefold().split("e")
        result = numeric_words(mantissa) + " times ten to the power of " + cardinal(exponent)
    elif "." in token:
        negative = token.startswith("-")
        whole, digits = token.lstrip("+-").split(".")
        result = ("minus " if negative else "") + cardinal(whole or 0) + " point " + " ".join(_SMALL[int(digit)] for digit in digits)
    else:
        result = cardinal(token)
    return result + (" percent" if percent else "")


def spoken_text(text, *, check_wording=True):
    if check_wording:
        validate_wording(text)
    operators = {"<=": "less than or equal to", ">=": "greater than or equal to",
                 "!=": "not equal to", "\u2264": "less than or equal to", "\u2265": "greater than or equal to",
                 "\u2260": "not equal to", "\u00d7": "times", "\u00f7": "divided by",
                 "\u2212": "minus", "+": "plus", "*": "times", "^": "to the power of",
                 "=": "equals", "<": "less than", ">": "greater than", "|": "given"}
    literal = r"(?<![\w.])[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+|\s*/\s*[+-]?\d+)?(?:\s*%)?"
    text = re.sub(literal, lambda match: numeric_words(match[0]), text)
    for operator in sorted(operators, key=len, reverse=True):
        text = text.replace(operator, " " + operators[operator] + " ")
    text = re.sub(r"\s+-\s+", " minus ", text)
    text = text.replace("/", " over ").replace("%", " percent ")
    # Parentheses act as pauses; ordinary punctuation remains readable by TTS.
    text = text.replace("(", ", ").replace(")", ", ")
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,!?;:])", r"\1", text)
