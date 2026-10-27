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
    r"\b(?:(?:so\s+)?the\s+probability(?:\s+of\s+fraud)?\s+is|"
    r"(?:the|my)\s+answer\s+(?:is|would\s+be)|"
    r"(?:it's|it\s+is)|you(?:'re|\s+are)\s+about|"
    r"i(?:'d|\s+would)\s+say\s+(?:[a-z']+\s+){0,8}is|"
    r"i(?:'d|\s+would)\s+(?:go\s+with|put\s+it\s+at)|"
    r"it\s+comes\s+out\s+(?:at|to)|"
    r"(?:the\s+)?(?:chance|odds)(?:\s+of\s+fraud)?\s+(?:is|are)|"
    r"with\s+probability|"
    r"(?:if\s+(?:the\s+alert\s+goes\s+off|flagged)|given\s+(?:a|the)\s+flag)"
    r"\s*[,;:]?\s*(?:then\s+)?(?:it's|it\s+is|the\s+probability\s+is))\b"
)
POSTFIX_MARKER = re.compile(r"(?:\bthat(?:'s|\s+is)|\bis|'s)\s+my\s+(?:final\s+)?answer\b")
FILLER = re.compile(r"(?:,\s*)?\b(?:um|uh|er|like|you\s+know)\b(?:\s*,)?")
EXCLUDED = re.compile(
    r"\b(?:maybe|no|wait|actually|suppose|if\s+i|if\s+it\s+(?:were|was)|"
    r"i\s+mean|scratch\s+that|let\s+me\s+correct|on\s+second\s+thought|"
    r"people\s+(?:say|would\s+say)|my\s+first\s+instinct|"
    r"(?:someone|somebody|they|he|she)\s+(?:says?|said)|"
    r"according\s+to|quot(?:e|ed|ing|ation)|"
    r"i\s+(?:don't|do\s+not|wouldn't|would\s+not)\s+(?:think|reckon|guess|believe|say))\b"
)
GIVEN_SUFFIX = re.compile(
    r"^[\s,;:.!?]*(?:of\s+(?:the\s+)?(?:fraud|genuine)|detection\s+rate|"
    r"false\s+alarm\s+rate|specificity|base\s+rate|flagged)\b"
)
PENDING_GIVEN_SUFFIX = re.compile(r"^[\s,;:]*?(?:of(?:\s+the)?|detection|false(?:\s+alarm)?|base)[\s,;:]*$")
GIVEN_SUBJECT = re.compile(
    r"\b(?:detector\s+(?:catches|detects|flags)|detection\s+rate|false\s+alarm\s+rate|"
    r"specificity|base\s+rate|fraud\s+(?:is|gets)\s+(?:detected|flagged))\b"
)


def normalize(text):
    return re.sub(r"(?<=[a-z])-(?=[a-z])", " ", text.lower().replace("’", "'"))


def without_fillers(text):
    text = normalize(text)
    # Repeat to handle disfluencies inside "you uh know" as well as between words.
    while True:
        cleaned = " ".join(FILLER.sub(" ", text).split())
        if cleaned == text:
            return cleaned
        text = cleaned


def excluded_context(text):
    if (EXCLUDED.search(text) or any(char in text for char in '?"“”')
            or re.search(r"(?:^|[\s:(])'", text)):
        return True
    # Known conditioning on an observed flag remains a commitment with "it's".
    # Every other "if", and any "if ... would be", remains hypothetical.
    if re.search(r"\bif\b", text):
        if (re.search(r"\bwould\s+be\b", text)
                or re.search(r"\bif\b(?!\s+(?:the\s+alert\s+goes\s+off|flagged)\b)", text)):
            return True
    remainder = re.sub(r"\b(?:the|my)\s+answer\s+would\s+be\b", " ", text)
    return re.search(r"\bwould\s+be\b", remainder) is not None


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


def number_before(text, end):
    """Find a complete adjacent number before an answer-commitment suffix."""
    prefix = text[:end]
    tokens = list(TOKEN.finditer(prefix))
    for index, token in enumerate(tokens):
        # Do not rescue an incomplete/invalid number by reading its denominator
        # or a decimal tail as a new, standalone answer.
        if index:
            previous = tokens[index - 1].group()
            if previous in {*ONES, *TENS, "over", "point", "/", ".", "hundred"}:
                continue
        start = token.start()
        if start and prefix[start - 1] == "-":
            continue
        number = parse_number(prefix[start:])
        if number and not prefix[start + number.end:].strip(" \t,;:.!"):
            return number, start
    return None


def find_claim(text):
    text = without_fillers(text)
    if excluded_context(text):
        return None
    markers = sorted(
        [(match.start(), "prefix", match) for match in MARKER.finditer(text)]
        + [(match.start(), "postfix", match) for match in POSTFIX_MARKER.finditer(text)],
        key=lambda item: item[0],
    )
    if not markers:
        return None
    _, direction, marker = markers[-1]
    if direction == "postfix":
        found = number_before(text, marker.start())
        if found is None:
            return None
        number, number_start = found
        context_end = number_start
    else:
        tail = text[marker.end():]
        approximation = re.match(r"\s*(?:(?:about|approximately|roughly|around)\s+)*", tail)
        number_start = marker.end() + approximation.end()
        number = parse_number(text[number_start:])
        if number is None:
            return None
        context_end = marker.end()
    # Keep earlier completed sentences from contaminating a later committed
    # posterior, while refusing a detector-rate subject in the current clause.
    clause = re.split(r"[.!?;]\s+", text[:context_end])[-1]
    suffix = text[number_start + number.end:]
    if (GIVEN_SUBJECT.search(clause) or GIVEN_SUFFIX.search(suffix)
            or PENDING_GIVEN_SUFFIX.search(suffix)):
        return None
    if direction == "prefix" and marker.group().startswith(("you're", "you are")) and not re.search(r"\blikely\b", suffix):
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
