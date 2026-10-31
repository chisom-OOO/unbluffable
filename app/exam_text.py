"""What the Exam Room interviewer says. Written here, not in llm/prompt.py.

Questions are forge template instances, read as written. Acknowledgements are
neutral (decision log 6). Challenges and nudges are Socratic questions about the
candidate's own words (decision log 3, 3a); nudges ask for a solution-map step by
name and introduce no new number.
"""

from __future__ import annotations

from fractions import Fraction

from engine.answers import StatedNumber
from engine.templates import Puzzle

ACKNOWLEDGEMENTS = ("Got it.", "Understood.", "Okay.", "Thanks.")
OPENING = "Take your time. Talk me through it out loud."
TWIN_INTRO = "Now the same puzzle with new numbers."
NEW_PUZZLE_INTRO = "Here's a different puzzle."
REPEAT_INTRO = "Sure. Here it is again."
CORRECT_CLOSE = "That matches the exact answer."
NOT_RECOVERED_CLOSE = "Let's leave this one there."
SESSION_CLOSE = "That's the end of the interview. Your report is ready."
TIME_CLOSE = "We're out of time, so let's stop there. Your report is ready."
UNCHECKED = "Sorry, I couldn't check that. Could you say your answer again?"
ASK_FOR_VALUE = "What answer do you commit to?"  # the answer need not be a probability
PART2_INTRO = "Good. Here's a follow-up."
PART2_CLOSE = "Thanks. Let's move on."
FOLLOW_UP_INTRO = "One more on this, about the idea rather than the numbers."
FOLLOW_UP_NO_HINT = "There's no hint for this one. Just say what you think."
FOLLOW_UP_CLOSE = "Thanks. Let's move on."
# A rounded answer that also rounds from a known wrong value: ask once for more precision.
ONE_MORE_DIGIT = "That rounds from more than one method. Could you give it to one more decimal place?"
ASK_WHY = "How did you get that?"
HELP_ASK = "Sure, what are you stuck on?"
OFFER_HELP = "Is there anything you're stuck on?"
# Decision log 27: a number that may have been misheard is confirmed before it is graded.
CONFIRM = "Just to check, did you say {number}?"
REOPEN = "Sorry, I misheard. What's your answer?"

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
         "sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ORDINALS = {1: "first", 2: "half", 3: "third", 4: "quarter", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth",
             9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth", 20: "twentieth", 30: "thirtieth", 40: "fortieth",
             50: "fiftieth", 60: "sixtieth", 70: "seventieth", 80: "eightieth", 90: "ninetieth", 100: "hundredth"}


def words(n: int) -> str | None:
    """0-999 in words, or None."""
    if not 0 <= n < 1000:
        return None
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    rest = n % 100
    return _ONES[n // 100] + " hundred" + ("" if rest == 0 else " and " + words(rest))


def _ordinal(n: int) -> str | None:
    if n in _ORDINALS:
        return _ORDINALS[n]
    if 13 <= n <= 19:
        return words(n) + "th"
    if 20 < n < 100:
        return _TENS[n // 10] + "-" + _ORDINALS[n % 10] if n % 10 != 2 else _TENS[n // 10] + "-second"
    return None


def number_said(stated: StatedNumber) -> tuple[str, str]:
    """(shown, spoken) for the confirmation, in the form the candidate used where possible:
    5/7 is "five sevenths", 15% is "15 percent"."""
    v = Fraction(stated.value)
    if stated.form == "percent":
        shown = (stated.written or _decimal(v * 100)) + "%"
        return shown, shown[:-1] + " percent"
    if stated.form == "decimal" or (v.denominator != 1 and stated.written and "." in stated.written):
        shown = stated.written or _decimal(v)
        return shown, shown
    if v.denominator == 1:
        return str(v.numerator), words(v.numerator) or str(v.numerator)
    num, den = words(v.numerator), _ordinal(v.denominator)
    shown = f"{v.numerator}/{v.denominator}"
    if num is None or den is None:
        return shown, f"{v.numerator} over {v.denominator}"
    plural = den if v.numerator == 1 else ("halves" if den == "half" else den + "s")
    return shown, f"{num} {plural}"


def _decimal(v: Fraction) -> str:
    text = f"{float(v):.6g}"
    return text


def pct(x: Fraction) -> str:
    v = Fraction(x) * 100
    return f"{v.numerator}%" if v.denominator == 1 else f"{float(v):g}%"


def puzzle_text(puzzle: Puzzle) -> str:
    """A forge template instance's own reworded text."""
    if not getattr(puzzle, "text", ""):
        raise ValueError(f"no question text for template {puzzle.template_id}")
    return puzzle.text


def said(stated: StatedNumber | None, span: str | None) -> str:
    """The candidate's number as they said it, for "You said ..."."""
    if span:
        return span.strip().rstrip(".")
    if stated is None:
        return "that"
    if stated.form == "percent":
        return pct(stated.value)
    return f"{stated.value.numerator}/{stated.value.denominator}"


def challenge(puzzle: Puzzle, stated: StatedNumber | None, span: str | None, misconception: str | None) -> str:
    """Round 1 after a committed wrong answer. Points at no solution-map step."""
    return f"You said {said(stated, span)}. Can you walk me through how you got there?"


FORGE_NUDGE = "Talk me through the steps you'd need to get there."


def value(x: Fraction) -> str:
    """An exact value for display: whole numbers as they are, others as n/d ≈ decimal."""
    x = Fraction(x)
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator} ≈ {float(x):.4g}"


def why_numbers(diagnostic) -> str:
    """The "Why these numbers?" note for a diagnostic twin (decision log 16). Shown only
    after the twin is answered: before, the right value would give the answer away."""
    right = f"Right method: {value(diagnostic.correct)}."
    if diagnostic.suspected:
        return (f"{right} Suspected error ({diagnostic.misconception}): {value(diagnostic.wrong)}. "
                "These numbers were picked to keep the two far apart.")
    return (f"{right} Closest wrong method ({diagnostic.misconception}): {value(diagnostic.wrong)}. "
            "These numbers were picked to keep every known wrong method far from the right answer.")


# Drill mode (decision log 16): questions only, no explanations.
DRILL_OPENING = ("This drill has up to three questions aimed at one mistake, then one check with new numbers "
                 "and no help. Talk me through each one out loud.")
DRILL_CHECK_INTRO = "Last one: the check. New numbers, and no help this time."
DRILL_NO_HELP = "This one is without help. Talk me through your best answer."
DRILL_CHECK_THANKS = "Thanks."
DRILL_CLOSE = "That's the end of the drill. Your result is ready."

METER_CLASSES = (("S", "Sound"), ("M", "Misconception"), ("G", "Gap"))
METER_FINAL = "No more questions, so this is the final estimate."


def whole_pct(x: Fraction) -> str:
    return f"{round(float(x) * 100)}%"


def meter_line(kind: str, right: tuple, named: tuple) -> str:
    """What would change the evidence meter: the next answer, right or a named error.
    `right` and `named` are (posterior, label) from engine Interview.what_if."""
    def effect(result, key, name):
        posterior, label = result
        text = f"move {name} to {whole_pct(posterior[key])}"
        return text + (f" (“{label.value}”)" if label.value != "More evidence needed" else "")
    which = "the twin" if kind == "twin" else "the next question"
    return (f"On {which}, a right answer with reasoning would {effect(right, 'S', 'Sound')}; "
            f"a named error would {effect(named, 'M', 'Misconception')}.")


def forge_step_prompt(name: str) -> str:
    """A forge solution-map step, asked by its name only (no new numbers)."""
    return f"What do you get for the {name.replace('_', ' ').strip().rstrip('.?')}?"
