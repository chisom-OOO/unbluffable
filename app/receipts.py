"""Receipts (decision log 16): the candidate's exact words beside the exact computation
behind each judgement: the value read from those words, the exact answer, the check,
the known wrong methods and how the answer was coded.

During a question the receipt is redacted: the exact answer, the check and the wrong
methods would give the answer away, so they appear once the question is scored.
"""

from __future__ import annotations

from fractions import Fraction

from app.exam_text import value
from engine import checker
from engine.answers import PERCENTAGE_POINT, StatedNumber
from engine.bank import ForgePuzzle
from engine.coding import Observation, Outcome
from engine.templates import Puzzle

CODED = {
    Outcome.CORRECT: "Correct: the exact value, with reasoning",
    Outcome.NAMED_WRONG: "A known wrong method",
    Outcome.OTHER_WRONG: "Not the exact value, and no known wrong method",
    Outcome.RECITED: "The previous question's answer, repeated",
    Outcome.VAGUE: "Not committed, or the reasoning was not shown",
}
REDACTED_NOTE = "The exact value and the check are shown when this question ends."


def tolerance(puzzle: Puzzle) -> Fraction:
    return puzzle.tolerance if isinstance(puzzle, ForgePuzzle) else PERCENTAGE_POINT


def exact_text(puzzle: Puzzle) -> str:
    if isinstance(puzzle, ForgePuzzle) and puzzle.answer_text != str(puzzle.answer):
        return f"{puzzle.answer_text} = {value(puzzle.answer)}"
    return value(puzzle.answer)


def _frac(x: Fraction) -> str:
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"


def check_text(puzzle: Puzzle, stated: StatedNumber, target: Fraction) -> str:
    """How the stated number was compared, with the result (engine Puzzle.accepts)."""
    same = puzzle.accepts(stated, target)
    if stated.form == "fraction":
        return f"Fractions must match exactly: {_frac(stated.value)} {'=' if same else '≠'} {_frac(target)}."
    gap = abs(stated.value - target)
    allowed = tolerance(puzzle)
    article = "An" if stated.form[0] in "aeiou" else "A"
    verdict = f"it is {float(gap):.4g} away, so it {'matches' if same else 'does not match'}."
    figures = checker.precision(stated) if isinstance(puzzle, ForgePuzzle) else None
    if figures is not None:
        places = len(stated.written.partition(".")[2])
        unit = f"{Fraction(1, 10 ** places):f}".rstrip("0").rstrip(".") if places else "1"
        unit += "%" if stated.form == "percent" else ""
        return (f"{article} {stated.form} counts when it is the exact value rounded to the nearest {unit} "
                f"(as you said it), with at least {checker.MIN_FIGURES} significant figures, "
                f"or within {float(allowed):g}: {verdict}")
    return f"{article} {stated.form} may be within {float(allowed):g} of the exact value: {verdict}"


def build(puzzle: Puzzle, transcript: str, span: str | None, stated: StatedNumber | None,
          observation: Observation | None, quote: str | None) -> dict:
    rows = []
    if stated is not None:
        rows.append({"key": "said", "label": "You said", "text": f"“{span}”, read as {value(stated.value)} ({stated.form})"})
    else:
        rows.append({"key": "said", "label": "You said", "text": "No committed number was found in your words."})
    rows.append({"key": "exact", "label": "Exact answer", "text": exact_text(puzzle)})
    if stated is not None:
        rows.append({"key": "check", "label": "Check", "text": check_text(puzzle, stated, puzzle.answer)})
        if puzzle.recited is not None:
            repeated = puzzle.accepts(stated, puzzle.recited)
            rows.append({"key": "recited", "label": "Previous question's answer",
                         "text": f"{value(puzzle.recited)}: {'your number matches it' if repeated else 'not this'}."})
    if puzzle.named_values:
        methods = []
        for nv in puzzle.named_values:
            hit = stated is not None and observation is not None and nv.key in observation.matched
            methods.append(f"{nv.description}: {value(nv.value)}" + (" (your number matches it)" if hit else ""))
        rows.append({"key": "methods", "label": "Known wrong methods", "text": "; ".join(methods) + "."})
    rows.append({"key": "reasoning", "label": "Reasoning quoted",
                 "text": f"“{quote}”" if quote else "None quoted, so a right number alone counts as not explained."})
    if observation is not None and observation.outcome in CODED:
        named = [nv.description for nv in puzzle.named_values if nv.key in observation.matched]
        rows.append({"key": "coded", "label": "Coded as", "text": CODED[observation.outcome]
                     + (f" ({named[0]})" if named else "")})
    elif observation is None:
        rows.append({"key": "coded", "label": "Coded as", "text": "Not checked: the answer could not be read."})
    return {"words": transcript, "span": span, "rows": rows}


def redacted(receipt: dict) -> dict:
    """For a judgement made during the question: only what the candidate already knows."""
    keep = [r for r in receipt["rows"] if r["key"] in {"said", "reasoning"}]
    return {**receipt, "rows": keep, "note": REDACTED_NOTE}


def weight_receipt(words: str, help_load: int, recovered: bool, weight: Fraction | None, scored: str | None) -> dict:
    """The help discount behind a question's score (engine.help.weight_for)."""
    rows = [{"key": "help", "label": "Help load H", "text": str(help_load)}]
    if scored == "correct":
        formula = f"2/(2+H{'+1' if recovered else ''})"
        rows.append({"key": "weight", "label": "Weight on Correct",
                     "text": f"{formula} = {value(weight)}" + (" (+1 because it was recovered after the challenge)" if recovered else "")})
    else:
        rows.append({"key": "weight", "label": "Scored", "text": "The opening wrong or vague answer, at full weight."})
    return {"words": words, "span": None, "rows": rows}


def why_receipt(diagnostic, words: str | None, previous: Fraction | None) -> dict:
    """The gap behind a diagnostic twin's numbers (engine.bank.twin_choice)."""
    rows = [{"key": "exact", "label": "Right method", "text": value(diagnostic.correct)},
            {"key": "methods", "label": "Suspected error" if diagnostic.suspected else "Closest wrong method",
             "text": f"{diagnostic.misconception}: {value(diagnostic.wrong)}"},
            {"key": "gap", "label": "Gap", "text": f"|{value(diagnostic.correct)} − {value(diagnostic.wrong)}| = "
                                                    f"{value(abs(diagnostic.correct - diagnostic.wrong))}"},
            {"key": "rule", "label": "Rule", "text": "Largest gap to the suspected error among this template's instances."
             if diagnostic.suspected else "Largest gap to the closest wrong method among this template's instances."}]
    if previous is not None:
        rows.insert(2, {"key": "recited", "label": "Previous question's answer", "text": value(previous)})
    return {"words": words, "span": None, "rows": rows}
