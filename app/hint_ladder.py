"""The hint ladder (decision log 27): each nudge or hint on a question goes one step further
along the family's solution steps than the last, starting from the furthest step the
candidate has shown, and never repeats or paraphrases an earlier line on that question.

A step is named, never given away: a step's value is said only when the leak guard allows
it (a given, or a number the candidate already said). Once the last step has been asked,
further help walks a fixed list of different prompts about that step.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable

from app import exam_text as say

SIMILAR = 0.75  # a line this close to an earlier one counts as a repeat
# Socratic: every line is a question (decision log 3). No number words: the leak guard reads
# "one" as 1.
LAST_STEP = (
    "If you put the steps you have together, step by step, what comes out for the {name}?",
    "Which numbers would you use for the {name}, and where does each come from in the question?",
    "Reading the question again, what feeds into the {name}, and what does that give you?",
)


def step_name(name: str) -> str:
    return name.replace("_", " ").strip().rstrip(".?")


def _plain(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def repeats(text: str, earlier: list[str]) -> bool:
    """True when `text` is identical or near-identical to any earlier line."""
    mine = _plain(text)
    return any(mine == _plain(e) or SequenceMatcher(None, mine, _plain(e)).ratio() >= SIMILAR for e in earlier)


def target_step(at: int, last_target: int | None, steps: int) -> int:
    """One step beyond both the candidate's position and the last help's step."""
    return min(max(at, last_target or 0) + 1, steps)


def step_prompt(puzzle, target: int, earlier_help: bool, allowed: Callable[[str], bool]) -> str:
    """Help for step `target` (1-based). The first help is the plain step question; later
    help starts from the step before, with its value when the leak guard allows it."""
    steps = puzzle.steps
    ask = say.forge_step_prompt(steps[target - 1].name)
    if not earlier_help or target < 2:
        return ask
    before = steps[target - 2]
    with_value = f"The {step_name(before.name)} is {_number(before.value)}. Building on that: {ask[0].lower()}{ask[1:]}"
    if allowed(with_value):
        return with_value
    return f"Start from the {step_name(before.name)}, then go a step further: {ask[0].lower()}{ask[1:]}"


def _number(value) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def next_help(puzzle, at: int, last_target: int | None, earlier: list[str],
              allowed: Callable[[str], bool]) -> tuple[int | None, str]:
    """(target step, text) for the next nudge or hint. `earlier`: every challenge, nudge and
    hint already said on this question; `allowed(text)`: the leak guard."""
    steps = len(puzzle.steps)
    if not steps:
        options = [say.FORGE_NUDGE, say.ASK_WHY, *(line.format(name="answer") for line in LAST_STEP)]
        return None, next((o for o in options if not repeats(o, earlier)), options[-1])
    target = target_step(at, last_target, steps)
    candidates = []
    if last_target is None or target > last_target:
        candidates.append(step_prompt(puzzle, target, bool(earlier), allowed))
    name = step_name(puzzle.steps[target - 1].name)
    candidates += [line.format(name=name) for line in LAST_STEP]
    for text in candidates:
        if allowed(text) and not repeats(text, earlier):
            return target, text
    return target, say.FORGE_NUDGE if not repeats(say.FORGE_NUDGE, earlier) else candidates[-1]
