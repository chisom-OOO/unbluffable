"""Deterministic flagship claim checks. No model, network, or audio dependencies."""

from dataclasses import dataclass
from fractions import Fraction
import re


CORRECT = Fraction(2, 13)
TOLERANCE = Fraction(1, 100)  # spec/02: percentage/decimal answers only.
NAMED_WRONG = {
    Fraction(9, 10): "90%", Fraction(19, 20): "95%",
    Fraction(1, 20): "5%", Fraction(117, 2000): "5.85%",
}
ONES = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20),
))
ONES["nought"] = 0
TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
ORDINALS = {
    "half": 2, "halves": 2, "third": 3, "fourth": 4, "quarter": 4,
    "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9,
    "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
    "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17,
    "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "hundredth": 100,
}
TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z]+(?:'[a-z]+)?|[%/.,!?;:]")
MARKER = re.compile(
    r"\b(?:(?:so\s+)?the\s+probability\s+is|(?:the|my)\s+answer\s+is|"
    r"so\s+(?:it's|it\s+is)|you(?:'re|\s+are)\s+about|"
    r"(?:if\s+(?:the\s+alert\s+goes\s+off|flagged)|given\s+(?:a|the)\s+flag)"
    r"\s*[,;:]?\s*(?:then\s+)?(?:it's|it\s+is|the\s+probability\s+is))\b"
)
EXCLUDED = re.compile(
    r"\b(?:maybe|no|wait|suppose|if\s+i|if\s+it\s+(?:were|was)|would\s+be|"
    r"i\s+mean|scratch\s+that|let\s+me\s+correct|on\s+second\s+thought)\b"
)
GIVEN_SUFFIX = re.compile(r"^\s*(?:of\s+(?:the\s+)?fraud\b|of\s+(?:the\s+)?genuine\b)")


def normalize(text):
    return re.sub(r"(?<=[a-z])-(?=[a-z])", " ", text.lower().replace("’", "'"))


@dataclass(frozen=True)
class ParsedNumber:
    value: Fraction
    kind: str
    span: str
    end: int

    @property
    def wrong(self):
        if self.kind == "fraction":
            return self.value != CORRECT
        return abs(self.value - CORRECT) > TOLERANCE


def integer(tokens, index):
    if index >= len(tokens):
        return None
    word = tokens[index]
    if word.isdigit():
        return int(word), index + 1
    if word in ONES:
        value, index = ONES[word], index + 1
    elif word in TENS:
        value, index = TENS[word], index + 1
        if index < len(tokens) and tokens[index] in ONES and 0 < ONES[tokens[index]] < 10:
            value += ONES[tokens[index]]
            index += 1
    else:
        return None
    if index < len(tokens) and tokens[index] == "hundred":
        value *= 100
        index += 1
        if index < len(tokens) and tokens[index] == "and":
            index += 1
        tail = integer(tokens, index)
        if tail:
            value += tail[0]
            index = tail[1]
    return value, index


def decimal_digits(tokens, index):
    digits = ""
    while index < len(tokens):
        token = tokens[index]
        if token.isdigit():
            digits += token
        elif token in ONES and ONES[token] < 10:
            digits += str(ONES[token])
        else:
            break
        index += 1
    return digits, index


def parse_number(text):
    """Read one complete number at the start; never search later for a number."""
    text = normalize(text)
    matches = list(TOKEN.finditer(text))
    if not matches or text[:matches[0].start()].strip():
        return None
    tokens = [match.group() for match in matches]
    kind = "decimal"
    if tokens[0] in {"point", "."}:
        digits, index = decimal_digits(tokens, 1)
        if not digits:
            return None
        value = Fraction(int(digits), 10 ** len(digits))
    elif re.fullmatch(r"\d+\.\d+", tokens[0]):
        value, index = Fraction(tokens[0]), 1
    else:
        start = integer(tokens, 0)
        if start is None:
            return None
        whole, index = start
        value, kind = Fraction(whole), "integer"
        if index < len(tokens) and tokens[index] in {"point", "over", "/"}:
            operator = tokens[index]
            index += 1
            if operator == "point":
                digits, index = decimal_digits(tokens, index)
                if not digits:
                    return None
                value = Fraction(whole) + Fraction(int(digits), 10 ** len(digits))
                kind = "decimal"
            else:
                denominator = integer(tokens, index)
                if denominator is None or denominator[0] == 0:
                    return None
                value, index = Fraction(whole, denominator[0]), denominator[1]
                kind = "fraction"
        elif index < len(tokens) and tokens[index].rstrip("s") in ORDINALS:
            value = Fraction(whole, ORDINALS[tokens[index].rstrip("s")])
            index += 1
            kind = "fraction"
        elif index < len(tokens) and tokens[index] == "." and whole == 0:
            return None  # A streaming "0." is an unfinished decimal.
    if index < len(tokens) and tokens[index] in {"%", "percent", "percentage"}:
        if kind == "fraction":
            return None  # Do not guess how a mixed fraction/percent was intended.
        value /= 100
        kind = "percentage"
        index += 1
    elif kind == "integer" and value not in {0, 1}:
        return None  # Could still grow into a fraction or percentage.
    end = matches[index - 1].end()
    return ParsedNumber(value, kind, " ".join(tokens[:index]), end)


@dataclass(frozen=True)
class Claim:
    number: ParsedNumber
    occurrence: int

    @property
    def identity(self):
        # Trailing growth and unrelated prefix revisions do not change the number.
        # A newly stated marker or revised number wording starts a new interval.
        return self.occurrence, self.number.span, self.number.kind


def find_claim(text):
    text = normalize(text)
    if EXCLUDED.search(text):
        return None
    markers = list(MARKER.finditer(text))
    if not markers:
        return None
    marker = markers[-1]
    tail = text[marker.end():]
    filler = re.match(r"\s*(?:(?:about|approximately|roughly|around|uh|um)\s+)*", tail)
    number_start = marker.end() + filler.end()
    number = parse_number(text[number_start:])
    if number is None:
        return None
    suffix = text[number_start + number.end:]
    if GIVEN_SUFFIX.search(suffix):
        return None
    if marker.group().startswith(("you're", "you are")) and not re.search(r"\blikely\b", suffix):
        return None
    return Claim(number, len(markers) - 1)


class ClaimTracker:
    """Evaluate only nonfinal transcript partials, at their original arrival time."""

    def __init__(self):
        self.active_turn = None
        self.previous_time = None
        self.challenge = None
        self.reset()

    def reset(self):
        self.candidate = None
        self.since = None
        self.count = 0

    def consume(self, row):
        elapsed = row.get("stream_elapsed_s")
        if elapsed is None:
            return None  # Handshake predates the audio clock.
        now = Fraction(str(elapsed))
        if now < 0 or (self.previous_time is not None and now < self.previous_time):
            raise ValueError("Events must have nonnegative monotonic stream times.")
        self.previous_time = now
        event = row["event"]
        kind = event.get("type")
        if kind == "speechStart":
            self.active_turn = event.get("turnId")
            self.reset()
        elif kind in {"speechEnd", "speechComplete"}:
            if self.active_turn is None or event.get("turnId") == self.active_turn:
                self.reset()
        elif kind == "transcript":
            if event.get("final", False):
                self.reset()
                return None
            claim = find_claim(event.get("transcript", ""))
            if claim is None:
                self.reset()
                return None
            if self.candidate != claim.identity:
                self.candidate, self.since, self.count = claim.identity, now, 1
            else:
                self.count += 1
            if (self.challenge is None and self.count >= 2 and now - self.since >= Fraction(1, 2)
                    and claim.number.wrong):
                self.challenge = {
                    "challenge_elapsed_s": float(now), "number_span": claim.number.span,
                    "claimed_value": str(claim.number.value),
                    "named_wrong": NAMED_WRONG.get(claim.number.value),
                    "stable_since_s": float(self.since), "consecutive_partials": self.count,
                }
                return dict(self.challenge)
        return None
