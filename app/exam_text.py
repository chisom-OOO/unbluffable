"""What the Exam Room interviewer says. Written here, not in llm/prompt.py.

Puzzle text states percentages only (decision log 9): the round population is
never in the question. Acknowledgements are neutral (decision log 6).
Challenges and nudges are Socratic questions about the candidate's own words
(decision log 3, 3a); the only number they may introduce is the template's
round population, and only nudges that target a solution-map step do so.
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
ASK_FOR_ANSWER = "What probability do you commit to?"
ASK_WHY = "How did you get that?"
HELP_ASK = "Sure, what are you stuck on?"
OFFER_HELP = "Is there anything you're stuck on?"


def pct(x: Fraction) -> str:
    v = Fraction(x) * 100
    return f"{v.numerator}%" if v.denominator == 1 else f"{float(v):g}%"


def puzzle_text(puzzle: Puzzle) -> str:
    v = puzzle.params
    if puzzle.template_id == "T1":
        return (
            f"{pct(v['p'])} of transactions are fraudulent. The detector flags {pct(v['s'])} of "
            f"fraudulent transactions and {pct(v['f'])} of genuine ones. A transaction is flagged. "
            "What is the probability it is fraud?"
        )
    if puzzle.template_id == "T2":
        return (
            f"Machine A makes {pct(v['a'])} of a factory's items and machine B makes the rest. "
            f"{pct(v['dA'])} of A's items and {pct(v['dB'])} of B's items are defective. "
            "An item is defective. What is the probability that machine A made it?"
        )
    if puzzle.template_id == "T3":
        return (
            f"A bag holds a biased coin {pct(v['q'])} of the time; it lands heads {pct(v['b'])} of "
            f"the time. Otherwise the bag holds a fair coin. The coin is flipped {int(v['k'])} times "
            "and lands heads every time. What is the probability it is the biased coin?"
        )
    raise ValueError(f"unknown template {puzzle.template_id}")


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
    you = f"You said {said(stated, span)}."
    if puzzle.template_id == "T1" and misconception == "transposed_conditional":
        return f"{you} Is that the chance a flag is fraud, or the chance fraud gets flagged?"
    if puzzle.template_id == "T1" and misconception == "base_rate_neglect":
        return f"{you} Where does the share of fraudulent transactions come into that?"
    if misconception == "transposed_conditional":
        return f"{you} Which way does the condition run in that number?"
    if misconception in {"ignores_data", "ignores_prior"}:
        return f"{you} What did you use from the evidence, and what from the starting chance?"
    return f"{you} Can you walk me through how you got there?"


# T1 step prompts by target step (spec/02 §7 solution map). Each asks for the
# value of its step; step 1 introduces the round population.
T1_STEP_PROMPTS = {
    1: "Picture {n} transactions. How many of them are fraudulent?",
    2: "Out of your {n}, how many transactions are fraudulent?",
    3: "Of the fraudulent ones, how many get flagged?",
    4: "Which transactions get flagged, apart from the fraudulent ones? How many?",
    5: "How many transactions get flagged in total?",
    6: "Of all the flagged ones, what share are fraudulent?",
}


def step_prompt(puzzle: Puzzle, target: int, population: int) -> str:
    if puzzle.template_id != "T1":
        raise NotImplementedError("step prompts exist for T1 only")
    return T1_STEP_PROMPTS[target].format(n=f"{population:,}")


GENERIC_NUDGE = "Talk me through the counts you'd need to get there."
