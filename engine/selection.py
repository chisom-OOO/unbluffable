"""Question selection by expected information gain per minute (spec/02 §4).

Candidates: the current puzzle's twin (if not yet asked) or a new puzzle from an
unused template. New puzzle = 2 minutes, twin = 1 minute. Entropy in bits.
Ties go to the fixed order twin, T1, T2, T3.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log2

from engine.coding import Outcome
from engine.likelihoods import Likelihoods, Table
from engine.posterior import Distribution, update
from engine.templates import TEMPLATE_ORDER

NEW_PUZZLE_MINUTES = 2
TWIN_MINUTES = 1
_TIE_EPS = 1e-12


@dataclass(frozen=True)
class Choice:
    kind: str  # "twin" or "new"
    template_id: str | None  # for "new"; None for "twin"
    bits_per_minute: float
    scores: tuple[tuple[str, float], ...]  # every candidate, in tie order


def entropy(dist: Distribution) -> float:
    return -sum(float(p) * log2(float(p)) for p in dist.values() if p > 0)


def information_gain(posterior: Distribution, table: Table) -> float:
    """Mutual information between the class and the next outcome, in bits."""
    expected = 0.0
    for row in table.values():
        p_outcome = sum(posterior[c] * row[c] for c in posterior)
        if p_outcome > 0:
            expected += float(p_outcome) * entropy(update(posterior, row))
    return entropy(posterior) - expected


def information_gain_per_minute(posterior: Distribution, table: Table, minutes: int) -> float:
    return information_gain(posterior, table) / minutes


def new_puzzle_table(likelihoods: Likelihoods) -> Table:
    return likelihoods.first_table()


def choose_next(
    posterior: Distribution,
    likelihoods: Likelihoods,
    *,
    twin_after: Outcome | None,
    unused_templates,
) -> Choice | None:
    """Pick the next question. `twin_after` is the current puzzle's first outcome
    if its twin has not been asked yet, else None. Returns None if no candidates."""
    candidates = []
    if twin_after is not None:
        table = likelihoods.twin_table(twin_after)
        candidates.append(("twin", None, information_gain_per_minute(posterior, table, TWIN_MINUTES)))
    unused = set(unused_templates)
    if unused:
        rate = information_gain_per_minute(posterior, new_puzzle_table(likelihoods), NEW_PUZZLE_MINUTES)
        for tid in TEMPLATE_ORDER:
            if tid in unused:
                candidates.append(("new", tid, rate))
    if not candidates:
        return None
    best = candidates[0]
    for cand in candidates[1:]:
        if cand[2] > best[2] + _TIE_EPS:  # strictly better; ties keep the earlier one
            best = cand
    scores = tuple((tid or "twin", rate) for _, tid, rate in candidates)
    return Choice(kind=best[0], template_id=best[1], bits_per_minute=best[2], scores=scores)
