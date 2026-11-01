"""Speakability: what the interviewer says aloud for a question, and which question texts are
hard to follow by ear. Pure (no network, no model calls).

The screen always shows the full question. Aloud, a question that holds a list, brackets, a
tuple, a subscript or underscore, or more than 6 numbers is replaced by "The numbers are on
your screen." and its final question sentence; any other question is said in full. Nothing
said aloud contains brackets, underscores or tuple notation.

The scan (forge/speakability_scan.py) flags variants by the same tests plus length (more than
60 words, only when nothing above applies) and jargon; families where most variants are flagged leave the spoken pool.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_NUMBERS = 6
MAX_WORDS = 60  # only for questions with no list, brackets, tuple or subscript
ON_SCREEN = "The numbers are on your screen."
# Lead-ins said before a new question (never shown on screen), in rotation.
LEAD_INS = ("Okay, try this one.", "Here's the next one.", "Right, here's one for you.", "Let's try this one.")
JARGON = ("toy payoff", "fill indicator")
# Coding-round families are never removed from the pool; aloud, the interviewer sends the
# candidate to the screen instead of reading the problem.
CODING_PREFIXES = ("sw_", "swf_", "qd_")
CODING_LINE = "Here's the problem — it's on your screen. Read it through, then talk me through your approach."


def coding_family(template_id: str | None) -> bool:
    return bool(template_id) and str(template_id).split(".")[0].startswith(CODING_PREFIXES)

_NUMBER = re.compile(r"(?<![\w./])\d+(?:[.,/]\d+)*(?![\w])|(?<=[a-zA-Z_])\d+")  # "1/8" and "0.25" are one number
_LIST = re.compile(r"\[[^\]]*,[^\]]*\]|\{[^}]*,[^}]*\}|\d[\d.]*\s*,\s*\d[\d.]*\s*,\s*(?:and\s+|or\s+)?\d")
_TUPLE = re.compile(r"\(\s*[^()]{1,40}?,[^()]{1,40}?\)")
_SQUARE = re.compile(r"[\[\]{}]")
_MATH_PAREN = re.compile(r"\([^()]*[\d=<>+*/^_\\][^()]*\)")
_SUBSCRIPT = re.compile(r"_|[₀-₉]|\\(?:sum|prod|frac|binom)")
_PROPORTIONAL = re.compile(r"proportional to \[", re.I)


@dataclass(frozen=True)
class Flags:
    list: bool = False
    brackets: bool = False
    tuple: bool = False
    subscript: bool = False
    numbers: int = 0
    words: int = 0
    proportional: bool = False
    jargon: tuple[str, ...] = field(default_factory=tuple)

    @property
    def screen_only(self) -> bool:
        """Said as "The numbers are on your screen." plus the final question sentence."""
        return self.list or self.brackets or self.tuple or self.subscript or self.numbers > MAX_NUMBERS

    @property
    def reasons(self) -> list[str]:
        """Why a variant is hard to follow aloud (the scan's flags)."""
        out = [name for name in ("list", "brackets", "tuple", "subscript") if getattr(self, name)]
        if self.proportional:
            out.append("proportional to [")
        if self.numbers > MAX_NUMBERS:
            out.append(f"{self.numbers} numbers")
        if self.words > MAX_WORDS and not (self.list or self.brackets or self.tuple or self.subscript):
            out.append(f"{self.words} words")
        out += [f"jargon: {j}" for j in self.jargon]
        return out


def numbers(text: str) -> int:
    return len(_NUMBER.findall(text))


def flags(text: str) -> Flags:
    text = str(text or "")
    lowered = text.lower()
    return Flags(
        list=bool(_LIST.search(text)),
        brackets=bool(_SQUARE.search(text) or _MATH_PAREN.search(text)),
        tuple=bool(_TUPLE.search(text)),
        subscript=bool(_SUBSCRIPT.search(text)),
        numbers=numbers(text),
        words=len(text.split()),
        proportional=bool(_PROPORTIONAL.search(text)),
        jargon=tuple(j for j in JARGON if j in lowered),
    )


_SENTENCE = re.compile(r"(?<=[.?!])\s+(?=[A-Z(\"'])")


def sentences(text: str) -> list[str]:
    """Sentences, never split at a decimal point ("0.5") or inside brackets."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += ch in "([{"
        depth -= ch in ")]}"
        if ch in ".?!" and depth <= 0 and (i + 1 == len(text) or text[i + 1].isspace()):
            if ch == "." and i > 0 and text[i - 1].isdigit() and i + 1 < len(text) and text[i + 1].isdigit():
                continue
            out.append(text[start:i + 1].strip())
            start = i + 1
    rest = text[start:].strip()
    if rest:
        out.append(rest)
    return [s for s in out if s]


def final_question(text: str) -> str:
    """The last sentence that asks something (ends with "?"), else the last sentence."""
    parts = sentences(text)
    asked = [s for s in parts if s.endswith("?")]
    return (asked or parts or [""])[-1]


_PROB = re.compile(r"\bP\s*\(\s*([^()]+?)\s*\)")
_EXPECT = re.compile(r"\bE\s*[\[(]\s*([^\[\]()]+?)\s*[\])]")
_PAIR = re.compile(r"\(\s*([^(),]+?)\s*,\s*([^(),]+?)\s*\)")
_INTERVAL = re.compile(r"\[\s*([^\[\](),]+?)\s*,\s*([^\[\](),]+?)\s*[\])]|\(\s*([^\[\](),]+?)\s*,\s*([^\[\](),]+?)\s*\]")


def clean_spoken(text: str) -> str:
    """No brackets, underscores or tuple notation aloud; "Y=1" is "Y equals 1"."""
    s = str(text or "")
    s = _PROB.sub(lambda m: f"the probability {'that' if re.search(r'[=<>≤≥]', m.group(1)) else 'of'} {m.group(1)}", s)
    s = _EXPECT.sub(lambda m: f"the expected value of {m.group(1)}", s)
    s = _INTERVAL.sub(lambda m: f"between {m.group(1) or m.group(3)} and {m.group(2) or m.group(4)}", s)  # [0,1)
    for _ in range(3):  # (a, b) pairs, innermost first
        s = _PAIR.sub(lambda m: f"{m.group(1)} and {m.group(2)}", s)
    s = re.sub(r"\s*(<=|≤)\s*", " is at most ", s)
    s = re.sub(r"\s*(>=|≥)\s*", " is at least ", s)
    s = re.sub(r"\s*!=\s*|\s*≠\s*", " is not ", s)
    s = re.sub(r"\s*=\s*", " equals ", s)
    s = re.sub(r"([A-Za-z])_\{?([A-Za-z0-9]+)\}?", r"\1 \2", s)  # x_1 -> x 1
    s = re.sub(r"[\[\](){}_]", " ", s)
    s = re.sub(r"\s+([,.?!;:])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def spoken_question(shown: str, speech: str | None = None) -> str:
    """What the interviewer says for a question shown as `shown` (its spoken form `speech`
    when the forge wrote one): the full spoken text, or, for a question that is hard to hear,
    "The numbers are on your screen." and the final question sentence."""
    said = speech or shown
    if not flags(shown).screen_only and not flags(said).screen_only:
        return clean_spoken(said)
    return f"{ON_SCREEN} {clean_spoken(final_question(said))}"
