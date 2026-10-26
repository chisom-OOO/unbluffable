"""Fresh-number generator with collision filters (spec/02 §1, generator rules).

- Natural-frequency counts are whole numbers for a round population size.
- A draw is rejected if its answer is within 2 percentage points of any named
  wrong value.
- A twin keeps the template, changes one parameter, moves the answer by at least
  10 percentage points, and is filtered against its own named wrong values plus
  the original answer ("Recited").

Pass a seeded `random.Random` for reproducible draws (the demo uses a fixed,
labelled seed); practice uses fresh seeds.
"""

from __future__ import annotations

import random
from fractions import Fraction

from engine.templates import TEMPLATES, Puzzle

COLLISION_GAP = Fraction(2, 100)  # reject if |answer − wrong value| <= 2pp
TWIN_SHIFT = Fraction(10, 100)  # twin must move the answer by >= 10pp
MAX_ATTEMPTS = 10_000


class GenerationError(RuntimeError):
    pass


def collisions(puzzle: Puzzle) -> list[str]:
    """Names of every rule the puzzle breaks (empty list = passes)."""
    hits = [
        nv.key
        for nv in puzzle.named_values
        if abs(puzzle.answer - nv.value) <= COLLISION_GAP
    ]
    if puzzle.recited is not None:
        if abs(puzzle.answer - puzzle.recited) <= COLLISION_GAP:
            hits.append("recited")
        if abs(puzzle.answer - puzzle.recited) < TWIN_SHIFT:
            hits.append("twin_shift")
        if puzzle.changed_param is None:
            hits.append("twin_must_change_one_param")
    return hits


def passes_filters(puzzle: Puzzle) -> bool:
    return not collisions(puzzle)


def generate(template_id: str, rng: random.Random) -> Puzzle:
    template = TEMPLATES[template_id]
    for _ in range(MAX_ATTEMPTS):
        params = {name: rng.choice(template.grid[name]) for name in template.param_names}
        try:
            puzzle = template.build(params)
        except ValueError:
            continue  # no round population gives whole counts
        if passes_filters(puzzle):
            return puzzle
    raise GenerationError(f"no valid {template_id} draw in {MAX_ATTEMPTS} attempts")


def make_twin(original: Puzzle, rng: random.Random) -> Puzzle:
    """Same template, one parameter changed, filtered including "Recited"."""
    template = TEMPLATES[original.template_id]
    options = [
        (name, value)
        for name in template.param_names
        for value in template.grid[name]
        if value != original.params[name]
    ]
    rng.shuffle(options)
    for name, value in options:
        params = {**original.params, name: value}
        puzzle = _build_twin(template, params, original)
        if puzzle is not None and passes_filters(puzzle):
            return puzzle
    raise GenerationError(f"no valid twin for {original.template_id} {original.params}")


def _build_twin(template, params, original):
    # Prefer the original population so the story stays "out of N".
    for population in (original.population, None):
        try:
            return template.build(params, population=population, original=original)
        except ValueError:
            continue
    return None
