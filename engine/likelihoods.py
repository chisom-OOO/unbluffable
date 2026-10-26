"""Likelihood tables loaded from content/likelihoods.yaml (spec/02 §3).

Model estimates (assumed likelihoods), not calibrated probabilities. Values load
as exact fractions and every table must sum to exactly 1 per class.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import yaml

from engine.coding import Outcome

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "content" / "likelihoods.yaml"

FIRST_OUTCOMES = (Outcome.CORRECT, Outcome.NAMED_WRONG, Outcome.OTHER_WRONG, Outcome.VAGUE)

Row = dict[str, Fraction]
Table = dict[Outcome, Row]


class LikelihoodError(ValueError):
    pass


@dataclass(frozen=True)
class Likelihoods:
    version: int
    classes: tuple[str, ...]
    prior: Row
    first_answer: Table
    twins: dict[Outcome, Table]  # keyed by the first outcome

    @property
    def twin_firsts(self) -> tuple[Outcome, ...]:
        return tuple(self.twins)

    def first_table(self) -> Table:
        return self.first_answer

    def twin_table(self, first: Outcome) -> Table:
        return self.twins[first]

    def first(self, outcome: Outcome) -> Row:
        return self.first_answer[outcome]

    def twin(self, first: Outcome, outcome: Outcome) -> Row:
        table = self.twins[first]
        if outcome is Outcome.RECITED and outcome not in table:
            # Interpretation (not in the spec table): after a wrong or vague first
            # answer, repeating the original answer is a wrong number that is not a
            # named value, so it uses the "other wrong" row.
            outcome = Outcome.OTHER_WRONG
        return table[outcome]


def load_likelihoods(path: Path | str | None = None) -> Likelihoods:
    path = Path(path) if path is not None else DEFAULT_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        version = data["version"]
        classes = tuple(data["classes"])
        prior = _row(data["prior"], classes, "prior")
        first = _table(data["first_answer"], classes, "first_answer")
        twins = {}
        for outcome in FIRST_OUTCOMES:
            key = f"after_{outcome.value}"
            twins[outcome] = _table(data["twin"][key], classes, f"twin.{key}")
    except (KeyError, TypeError) as exc:
        raise LikelihoodError(f"{path}: missing or malformed entry {exc}") from exc

    if not isinstance(version, int):
        raise LikelihoodError("version must be an integer")
    if sum(prior.values()) != 1:
        raise LikelihoodError("prior must sum to 1")
    if set(first) != set(FIRST_OUTCOMES):
        raise LikelihoodError("first_answer needs exactly correct/named_wrong/other_wrong/vague")
    if Outcome.RECITED not in twins[Outcome.CORRECT]:
        raise LikelihoodError("twin.after_correct needs a recited row")
    return Likelihoods(version, classes, prior, first, twins)


def _row(raw: dict, classes: tuple[str, ...], where: str) -> Row:
    if set(raw) != set(classes):
        raise LikelihoodError(f"{where}: needs exactly the classes {classes}")
    row = {c: Fraction(str(raw[c])) for c in classes}
    if any(not 0 <= v <= 1 for v in row.values()):
        raise LikelihoodError(f"{where}: values must be in [0, 1]")
    return row


def _table(raw: dict, classes: tuple[str, ...], where: str) -> Table:
    table = {}
    for key, row in raw.items():
        try:
            outcome = Outcome(key)
        except ValueError:
            raise LikelihoodError(f"{where}: unknown outcome {key!r}") from None
        if outcome is Outcome.ABSTAIN:
            raise LikelihoodError(f"{where}: abstain never updates")
        table[outcome] = _row(row, classes, f"{where}.{key}")
    for c in classes:
        total = sum(row[c] for row in table.values())
        if total != 1:
            raise LikelihoodError(f"{where}: class {c} sums to {total}, not 1")
    return table
