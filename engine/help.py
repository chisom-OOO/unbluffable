"""Help load and discount (spec/02 §7; decision log 3a, 3b).

Each hint or nudge targets a step of the template's fixed solution map. Its
strength is the number of steps it gives away past the candidate's position;
a forge template's solution map is its instance's steps (engine.bank);
the help load H is the sum for a question. A Correct answer after help is
discounted by mixing its likelihood row with an uninformative ¼.
"""

from __future__ import annotations

from collections.abc import Iterable
from fractions import Fraction

from engine.posterior import Distribution
from engine.templates import Puzzle

# T1 solution map, in order (02 §7). Steps are numbered from 1.
T1_STEPS = (
    "population",
    "fraud_count",
    "flagged_fraud",
    "flagged_genuine",
    "total_flagged",
    "divide",
)

UNINFORMATIVE = Fraction(1, 4)


def step_values(puzzle: Puzzle, population: int | Fraction) -> dict[int, Fraction]:
    """Exact value of each map step for a candidate who picked `population`."""
    if puzzle.template_id != "T1":
        raise NotImplementedError("solution maps exist for T1 only")
    n = Fraction(population)
    p, s, f = puzzle.params["p"], puzzle.params["s"], puzzle.params["f"]
    flagged_fraud = p * s * n
    flagged_genuine = (1 - p) * f * n
    return {
        1: n,
        2: p * n,
        3: flagged_fraud,
        4: flagged_genuine,
        5: flagged_fraud + flagged_genuine,
        6: puzzle.answer,
    }


def position(
    puzzle: Puzzle,
    stated: Iterable[int | Fraction],
    population: int | Fraction | None = None,
) -> int:
    """Furthest map step whose value the candidate has stated correctly (0 = none).

    Counts (steps 2-5) are checked against the population the candidate picked;
    without one only the answer (step 6, a ratio) can be checked. A forge puzzle's
    steps are checked by value, within the instance's tolerance.
    """
    said = {Fraction(x) for x in stated}
    steps = getattr(puzzle, "steps", ())
    if steps:
        reached = [k for k, step in enumerate(steps, 1)
                   if any(abs(step.value - x) <= puzzle.tolerance for x in said)]
        return max(reached, default=0)
    if population is None:
        return 6 if puzzle.answer in said else 0
    values = step_values(puzzle, population)
    reached = [k for k, v in values.items() if k > 1 and v in said]
    return max(reached, default=1)


def strength(target: int | None, at: int) -> int:
    """Steps a hint or nudge gives away; `target=None` is a "why?" with no step."""
    if target is None:
        return 0
    return max(0, target - at)


def help_load(helps: Iterable[tuple[int | None, int]]) -> int:
    """H for one question: sum of strengths over (target step, position at the time)."""
    return sum(strength(target, at) for target, at in helps)


def weight_for(help_load: int, challenged: bool = False) -> Fraction:
    """w = 2/(2 + H), or 2/(2 + H + 1) when recovered after a challenge (3b)."""
    return Fraction(2, 2 + help_load + (1 if challenged else 0))


def discount(row: Distribution, weight: Fraction) -> Distribution:
    """L'(o | c) = w·L(o | c) + (1 − w)·¼. Callers apply it to Correct rows only."""
    return {c: weight * v + (1 - weight) * UNINFORMATIVE for c, v in row.items()}
