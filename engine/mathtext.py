"""Simple LaTeX in question text: shown as plain Unicode on screen, read out as words.

Forge instances may carry `spoken_text`; without it the interviewer speaks `spoken`
of the text. Only common inline maths is handled (fractions, powers, roots, binomials,
comparison and arithmetic symbols, Greek letters, \\text). Text without LaTeX is
returned unchanged by both functions. A `$` is a maths delimiter only when the
segment between two of them looks like maths, so "$5 and $10" stays as it is.
"""

from __future__ import annotations

import re

_SYMBOLS = {
    "times": ("×", " times "), "cdot": ("·", " times "), "div": ("÷", " divided by "),
    "pm": ("±", " plus or minus "), "le": ("≤", " is at most "), "leq": ("≤", " is at most "),
    "ge": ("≥", " is at least "), "geq": ("≥", " is at least "), "ne": ("≠", " is not equal to "),
    "neq": ("≠", " is not equal to "), "approx": ("≈", " is about "), "lt": ("<", " is less than "),
    "gt": (">", " is greater than "), "infty": ("∞", " infinity "), "ldots": ("…", " and so on "),
    "dots": ("…", " and so on "), "cdots": ("⋯", " and so on "), "in": ("∈", " in "),
    "cup": ("∪", " union "), "cap": ("∩", " intersect "), "mid": ("|", " given "),
    "%": ("%", " percent"), "$": ("$", " dollars "), ",": (" ", " "), ";": (" ", " "), "!": ("", ""),
    "quad": (" ", " "), "qquad": (" ", " "), " ": (" ", " "), "left": ("", ""), "right": ("", ""),
}
_GREEK = {name: chr(code) for name, code in zip(
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi pi rho sigma tau "
    "upsilon phi chi psi omega".split(),
    [0x3B1, 0x3B2, 0x3B3, 0x3B4, 0x3B5, 0x3B6, 0x3B7, 0x3B8, 0x3B9, 0x3BA, 0x3BB, 0x3BC, 0x3BD,
     0x3BE, 0x3C0, 0x3C1, 0x3C3, 0x3C4, 0x3C5, 0x3C6, 0x3C7, 0x3C8, 0x3C9])}
_GREEK.update({"Delta": "Δ", "Sigma": "Σ", "Omega": "Ω", "Pi": "Π", "Phi": "Φ", "Theta": "Θ", "Lambda": "Λ"})
_SUPER = str.maketrans("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ")
_SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
_POWER_WORDS = {"2": "squared", "3": "cubed"}
_OPERATORS = {"+": " plus ", "-": " minus ", "=": " equals ", "<": " is less than ", ">": " is greater than "}

_COMMAND = re.compile(r"\\([A-Za-z]+|[%$,;! ])")
_DOLLARS = re.compile(r"(?<!\\)\$([^$\n]+?)(?<!\\)\$")
_PARENS = re.compile(r"\\\((.+?)\\\)")
_MATHY = re.compile(r"[\\^_{}=]|^\s*[A-Za-z]\s*$")


def _group(s: str, i: int) -> tuple[str, int]:
    """The argument at s[i]: a braced group or a single character (after spaces)."""
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        return "", i
    if s[i] != "{":
        if s[i] == "\\":
            m = _COMMAND.match(s, i)
            if m:
                return m.group(0), m.end()
        return s[i], i + 1
    depth = 0
    for j in range(i, len(s)):
        depth += {"{": 1, "}": -1}.get(s[j], 0)
        if depth == 0:
            return s[i + 1:j], j + 1
    return s[i + 1:], len(s)


def _simple(x: str) -> bool:
    return bool(re.fullmatch(r"[\w.]+(\([^()]*\))?", x))


def _convert(s: str, speech: bool, ops: bool = True) -> str:
    """`ops`: inside maths, so + - = < > are read as words."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            m = _COMMAND.match(s, i)
            if not m:
                out.append(c)
                i += 1
                continue
            name, i = m.group(1), m.end()
            if name in {"frac", "dfrac", "tfrac"}:
                a, i = _group(s, i)
                b, i = _group(s, i)
                a, b = _convert(a, speech, ops), _convert(b, speech, ops)
                if speech:
                    out.append(f" {a} over {b} ")
                else:
                    out.append(f"{a if _simple(a) else f'({a})'}/{b if _simple(b) else f'({b})'}")
            elif name in {"binom", "dbinom", "tbinom"}:
                n, i = _group(s, i)
                k, i = _group(s, i)
                n, k = _convert(n, speech, ops), _convert(k, speech, ops)
                out.append(f" {n} choose {k} " if speech else f"C({n}, {k})")
            elif name == "sqrt":
                a, i = _group(s, i)
                a = _convert(a, speech, ops)
                out.append(f" the square root of {a} " if speech else (f"√{a}" if _simple(a) else f"√({a})"))
            elif name in {"text", "mathrm", "textrm", "mathit", "mathbf", "textbf", "operatorname"}:
                a, i = _group(s, i)
                out.append(_convert(a, speech, ops))
            elif name in _SYMBOLS:
                out.append(_SYMBOLS[name][1 if speech else 0])
            elif name in _GREEK:
                out.append(f" {name} " if speech else _GREEK[name])
            else:
                out.append(name)
        elif c in "^_":
            a, i = _group(s, i + 1)
            a = _convert(a, speech, ops)
            if speech:
                out.append(f" sub {a} " if c == "_" else f" {_POWER_WORDS[a]} " if a in _POWER_WORDS
                           else f" to the power {a} ")
            else:
                chars, table = ("0123456789+-=()ni", _SUPER) if c == "^" else ("0123456789+-=()", _SUB)
                if a and all(ch in chars for ch in a):
                    out.append(a.translate(table))
                else:
                    out.append(f"{c}{a}" if len(a) == 1 else f"{c}({a})")
        elif c in "{}":
            i += 1
        else:
            out.append(_OPERATORS[c] if speech and ops and c in _OPERATORS else c)
            i += 1
    return "".join(out)


def _tidy(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"\s+([,.;:?!)])", r"\1", s).strip()


def _math(text: str, speech: bool) -> str:
    def segment(m: re.Match) -> str:
        body = m.group(1)
        if m.re is _DOLLARS and not _is_math(body):
            return m.group(0)
        return _convert(body, speech)

    text = _PARENS.sub(segment, text)
    text = _DOLLARS.sub(segment, text)
    if "\\" in text:
        text = _convert(text, speech, ops=False)  # commands outside delimiters
    return text


def _is_math(body: str) -> bool:
    """Between two `$`: maths, unless it reads as money ("$5 and $10": starts with a digit
    and has no LaTeX)."""
    return bool(_MATHY.search(body)) or not body.lstrip()[:1].isdigit()


def has_latex(text: str) -> bool:
    return "\\" in text or any(_is_math(m.group(1)) for m in _DOLLARS.finditer(text))


def display(text: str) -> str:
    """The text for the screen: simple LaTeX as plain Unicode."""
    if not has_latex(text):
        return text
    out = _math(text, speech=False)
    return re.sub(r" {2,}", " ", out).strip()


def spoken(text: str) -> str:
    """The text for speech: simple LaTeX as words."""
    if not has_latex(text):
        return text
    return _tidy(_math(text, speech=True))
