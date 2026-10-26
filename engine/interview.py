"""One interview: selection, posterior updates, labels and stopping (spec/02 §3–5).

Pure state machine; callers code each answer (engine.coding) and pass the
Observation to `record`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from engine.coding import Observation, Outcome
from engine.generator import generate, make_twin
from engine.labels import Label, label_for, should_stop
from engine.likelihoods import Likelihoods, load_likelihoods
from engine.posterior import update
from engine.selection import choose_next
from engine.templates import TEMPLATE_ORDER, Puzzle, flagship, flagship_twin


@dataclass(frozen=True)
class Question:
    number: int  # 1-based
    kind: str  # "new" or "twin"
    puzzle: Puzzle
    bits_per_minute: float


class Interview:
    def __init__(
        self,
        rng: random.Random | None = None,
        likelihoods: Likelihoods | None = None,
        demo: bool = False,
    ):
        """`demo=True` uses the fixed flagship puzzle and twin for T1."""
        self.rng = rng if rng is not None else random.Random()
        self.likelihoods = likelihoods if likelihoods is not None else load_likelihoods()
        self.demo = demo
        self.posterior = dict(self.likelihoods.prior)
        self.history: list[tuple[Question, Observation]] = []
        self.label = Label.MORE_EVIDENCE
        self.finished = False
        self._pending: Question | None = None
        self._current: Puzzle | None = None
        self._twin_after: Outcome | None = None  # first outcome, while the twin is unasked
        self._unused = list(TEMPLATE_ORDER)

    @property
    def answers(self) -> int:
        return len(self.history)

    @property
    def misconception(self) -> str | None:
        """Most recent named misconception, for "Misconception detected (name it)"."""
        for _, obs in reversed(self.history):
            if obs.misconception:
                return obs.misconception
        return None

    def next_question(self) -> Question | None:
        if self.finished:
            return None
        if self._pending is not None:
            return self._pending  # unanswered or abstained: ask again
        choice = choose_next(
            self.posterior,
            self.likelihoods,
            twin_after=self._twin_after,
            unused_templates=self._unused,
        )
        if choice is None:
            self.finished = True
            return None
        if choice.kind == "twin":
            puzzle = self._twin_of(self._current)
        else:
            puzzle = self._new_puzzle(choice.template_id)
            self._unused.remove(choice.template_id)
        self._pending = Question(self.answers + 1, choice.kind, puzzle, choice.bits_per_minute)
        return self._pending

    def record(self, observation: Observation) -> None:
        question = self._pending
        if question is None:
            raise RuntimeError("no question is waiting for an answer")
        if observation.outcome is Outcome.ABSTAIN:
            return  # system abstain: no update, same question stays pending
        if question.kind == "twin":
            row = self.likelihoods.twin(self._twin_after, observation.outcome)
            self._twin_after = None
        else:
            if observation.outcome is Outcome.RECITED:
                raise ValueError("Recited is only defined for twins")
            row = self.likelihoods.first(observation.outcome)
            self._current = question.puzzle
            self._twin_after = observation.outcome
        self.posterior = update(self.posterior, row)
        self.history.append((question, observation))
        self._pending = None
        self.label = label_for(self.posterior, self.answers)
        if should_stop(self.label, self.answers):
            self.finished = True
        elif self._twin_after is None and not self._unused:
            self.finished = True  # no candidates left

    def _new_puzzle(self, template_id: str) -> Puzzle:
        if self.demo and template_id == "T1":
            return flagship()
        return generate(template_id, self.rng)

    def _twin_of(self, puzzle: Puzzle) -> Puzzle:
        if self.demo and puzzle == flagship():
            return flagship_twin()
        return make_twin(puzzle, self.rng)

