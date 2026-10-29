"""One interview: selection, posterior updates, labels and stopping (spec/02 §3–5).

Pure state machine; callers code each answer (engine.coding) and pass the
Observation to `record`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from fractions import Fraction

from engine.coding import Observation, Outcome
from engine.generator import generate, make_twin
from engine.help import discount
from engine.labels import Label, label_for, should_stop
from engine.likelihoods import Likelihoods, load_likelihoods
from engine.posterior import update
from engine.selection import choose_next
from engine.templates import TEMPLATE_ORDER, Puzzle, flagship, flagship_twin


MAX_HELP_FOR_ESCALATION = 1


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
        source=None,
    ):
        """`demo=True` uses the fixed flagship puzzle and twin for T1.

        `source` (e.g. engine.bank.BankSource) replaces T1-T3 with its own templates:
        `candidates()` lists the template ids a new question may use, `new(id)` and
        `twin(puzzle, suspect)` build puzzles; `suspect` is the suspected misconception
        the twin is aimed at, or None (decision log 16). Selection, posterior and
        labels are unchanged."""
        self.rng = rng if rng is not None else random.Random()
        self.likelihoods = likelihoods if likelihoods is not None else load_likelihoods()
        self.demo = demo
        self.posterior = dict(self.likelihoods.prior)
        self.history: list[tuple[Question, Observation]] = []
        self.help_loads: list[int] = []  # H per scored answer, for the escalation gate
        self.label = Label.MORE_EVIDENCE
        self.finished = False
        self._pending: Question | None = None
        self._current: Puzzle | None = None
        self._twin_after: Outcome | None = None  # first outcome, while the twin is unasked
        self._named: list[str] = []  # misconceptions shown so far, including ones later recovered
        self._suspect: str | None = None  # named on the question the twin follows
        self.source = source
        self._unused = list(TEMPLATE_ORDER) if source is None else []

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

    @property
    def can_escalate(self) -> bool:
        """Escalate only on "Evidence supports understanding" with H <= 1 on each scored answer (02 §7)."""
        return self.label is Label.SUPPORTS and all(h <= MAX_HELP_FOR_ESCALATION for h in self.help_loads)

    @property
    def suspected(self) -> str | None:
        """The misconception a twin is aimed at (decision log 16): the one named on the
        question it follows, else, while Misconception leads the posterior, the most
        recent one named in the session."""
        if self._suspect is not None:
            return self._suspect
        if self._named and max(self.posterior, key=self.posterior.get) == "M":
            return self._named[-1]
        return None

    def what_if(self, outcome: Outcome) -> tuple[dict[str, Fraction], Label]:
        """Posterior and label if the waiting question were answered with `outcome` at
        full weight (decision log 16, evidence meter). Changes nothing."""
        question = self._pending
        if question is None:
            raise RuntimeError("no question is waiting for an answer")
        if question.kind == "twin":
            row = self.likelihoods.twin(self._twin_after, outcome)
        else:
            row = self.likelihoods.first(outcome)
        posterior = update(self.posterior, row)
        return posterior, label_for(posterior, self.answers + 1)

    def next_question(self) -> Question | None:
        if self.finished:
            return None
        if self._pending is not None:
            return self._pending  # unanswered or abstained: ask again
        choice = choose_next(
            self.posterior,
            self.likelihoods,
            twin_after=self._twin_after,
            unused_templates=self._candidates(),
        )
        if choice is None:
            self.finished = True
            return None
        if choice.kind == "twin":
            puzzle = self._twin_of(self._current)
        else:
            puzzle = self._new_puzzle(choice.template_id)
            if self.source is None:
                self._unused.remove(choice.template_id)
        self._pending = Question(self.answers + 1, choice.kind, puzzle, choice.bits_per_minute)
        return self._pending

    def record(
        self,
        observation: Observation,
        weight: Fraction = Fraction(1),
        help_load: int = 0,
        misconception: str | None = None,
    ) -> None:
        """Score a question once, from its final outcome (decision log 3b).

        Correct after help: weight = 2/(2+H); recovered after a challenge:
        2/(2+H+1) (engine.help.weight_for). Not recovered: pass the first
        wrong/vague outcome with weight 1. The weight discounts Correct only.
        `misconception`: one named on this question before it was recovered; it aims
        the twin and is not scored.
        """
        question = self._pending
        if question is None:
            raise RuntimeError("no question is waiting for an answer")
        if not 0 < weight <= 1:
            raise ValueError("weight must be in (0, 1]")
        if weight != 1 and observation.outcome is not Outcome.CORRECT:
            raise ValueError("the help discount applies to Correct only")
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
            self._suspect = observation.misconception or misconception
        named = observation.misconception or misconception
        if named:
            self._named.append(named)
        if observation.outcome is Outcome.CORRECT:
            row = discount(row, Fraction(weight))
        self.posterior = update(self.posterior, row)
        self.history.append((question, observation))
        self.help_loads.append(help_load)
        self._pending = None
        self.label = label_for(self.posterior, self.answers)
        if should_stop(self.label, self.answers):
            self.finished = True
        elif self._twin_after is None and not self._candidates():
            self.finished = True  # no candidates left

    def _candidates(self) -> list[str]:
        return self._unused if self.source is None else self.source.candidates()

    def _new_puzzle(self, template_id: str) -> Puzzle:
        if self.source is not None:
            return self.source.new(template_id)
        if self.demo and template_id == "T1":
            return flagship()
        return generate(template_id, self.rng)

    def _twin_of(self, puzzle: Puzzle) -> Puzzle:
        if self.source is not None:
            return self.source.twin(puzzle, self.suspected)
        if self.demo and puzzle == flagship():
            return flagship_twin()
        return make_twin(puzzle, self.rng)

