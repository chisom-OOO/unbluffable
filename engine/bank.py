"""Forge templates at runtime (decision log 15): content/forge/<template_id>.json.

Each template carries precomputed instances; nothing generated runs here. A question
uses one instance and its twin another instance of the same template. Named
misconceptions are the instance's wrong values, and its steps are the solution map
for help strength (spec/02 §7). Answers are checked by engine.checker with the
instance's tolerance.

`BankSource` feeds engine.Interview new questions from a topic (or "Mixed") along
a difficulty ladder: start Easy or Medium, up one level after a correct answer,
down one after a wrong one.

Twins are diagnostic (decision log 16): the twin instance is the one whose numbers
best separate the right answer from the suspected misconception's value.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from engine import checker
from engine.answers import StatedNumber
from engine.coding import Outcome
from engine.templates import NamedValue, Puzzle

LOG = logging.getLogger(__name__)

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "content" / "forge"
DIFFICULTIES = ("Easy", "Medium", "Hard")
START_LEVELS = ("Easy", "Medium")
MIXED = "Mixed"
MIN_INSTANCES = 8
WRONG_OUTCOMES = (Outcome.NAMED_WRONG, Outcome.OTHER_WRONG, Outcome.RECITED)
PREVIOUS_ANSWER = "repeats the previous question's answer"  # Recited, as a wrong method


class ForgeError(ValueError):
    pass


@dataclass(frozen=True)
class Step:
    name: str
    value: Fraction


@dataclass(frozen=True)
class Instance:
    text: str
    params: dict
    answer_text: str
    answer: Fraction
    tolerance: Fraction
    wrong: tuple[NamedValue, ...]
    steps: tuple[Step, ...]
    part2: Instance | None = None


@dataclass(frozen=True)
class ForgeTemplate:
    template_id: str
    topic: str
    topics: tuple[str, ...]
    difficulty: str
    models: object
    verification: object
    instances: tuple[Instance, ...]


@dataclass(frozen=True)
class Diagnostic:
    """Why a twin uses its numbers (decision log 16): the right answer and the wrong
    value it is kept furthest from. `suspected` is false when no misconception was
    suspected; `misconception` is then the closest wrong method."""
    misconception: str
    correct: Fraction
    wrong: Fraction
    suspected: bool


@dataclass(frozen=True)
class ForgePuzzle(Puzzle):
    text: str = ""
    answer_text: str = ""
    tolerance: Fraction = Fraction(0)
    steps: tuple[Step, ...] = ()
    part2: ForgePuzzle | None = None
    topic: str = ""
    difficulty: str = ""
    instance: int = -1
    diagnostic: Diagnostic | None = None  # twins only

    def accepts(self, stated: StatedNumber, target: Fraction) -> bool:
        return checker.accepts(stated, target, self.tolerance)


# --- Loading and the contract ------------------------------------------------


def _need(raw: dict, key: str, kind, where: str):
    if not isinstance(raw, dict) or key not in raw:
        raise ForgeError(f"{where}: missing {key}")
    value = raw[key]
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise ForgeError(f"{where}.{key}: wrong type")
    return value


def _exact(value, where: str) -> Fraction:
    try:
        return checker.parse_exact(value)
    except ValueError as error:
        raise ForgeError(f"{where}: {error}") from None


def parse_instance(raw: dict, where: str, part2_allowed: bool = True) -> Instance:
    text = _need(raw, "text", str, where).strip()
    if not text:
        raise ForgeError(f"{where}.text: empty")
    answer_text = _need(raw, "answer", str, where).strip()
    tolerance = _exact(_need(raw, "tolerance", (str, int, float), where), f"{where}.tolerance")
    if tolerance < 0:
        raise ForgeError(f"{where}.tolerance: negative")
    wrong = []
    for i, row in enumerate(_need(raw, "wrong", list, where)):
        here = f"{where}.wrong[{i}]"
        misconception = _need(row, "misconception", str, here).strip()
        wrong.append(NamedValue(f"wrong_{i + 1}", _exact(_need(row, "value", (str, int, float), here), here),
                                misconception, misconception))
    steps = []
    for i, row in enumerate(_need(raw, "steps", list, where)):
        here = f"{where}.steps[{i}]"
        steps.append(Step(_need(row, "name", str, here).strip(), _exact(_need(row, "value", (str, int, float), here), here)))
    part2 = None
    if raw.get("part2") is not None:
        if not part2_allowed:
            raise ForgeError(f"{where}.part2: a part 2 has no part 2")
        part2 = parse_instance(raw["part2"], f"{where}.part2", part2_allowed=False)
    return Instance(text, _need(raw, "params", dict, where), answer_text,
                    _exact(answer_text, f"{where}.answer"), tolerance, tuple(wrong), tuple(steps), part2)


def parse_template(raw: dict, where: str = "template") -> ForgeTemplate:
    template_id = _need(raw, "template_id", str, where).strip()
    if not template_id:
        raise ForgeError(f"{where}.template_id: empty")
    difficulty = _need(raw, "difficulty", str, where)
    if difficulty not in DIFFICULTIES:
        raise ForgeError(f"{where}.difficulty: must be one of {DIFFICULTIES}")
    topics = _need(raw, "topics", list, where)
    if not all(isinstance(t, str) for t in topics):
        raise ForgeError(f"{where}.topics: must be strings")
    raw_instances = _need(raw, "instances", list, where)
    if len(raw_instances) < MIN_INSTANCES:
        raise ForgeError(f"{where}.instances: needs at least {MIN_INSTANCES}")
    instances = tuple(parse_instance(row, f"{where}.instances[{i}]") for i, row in enumerate(raw_instances))
    return ForgeTemplate(template_id, _need(raw, "topic", str, where).strip(), tuple(topics), difficulty,
                         raw.get("models"), raw.get("verification"), instances)


@dataclass
class Bank:
    templates: dict[str, ForgeTemplate] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)  # files skipped, with the reason

    def topics(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for t in self.templates.values():
            counts[t.topic] = counts.get(t.topic, 0) + 1
        return sorted(counts.items(), key=lambda kv: kv[0].lower())

    def pool(self, topic: str) -> list[ForgeTemplate]:
        return [t for t in self.templates.values() if topic == MIXED or t.topic == topic]


def load_bank(directory: Path | str | None = None) -> Bank:
    """Every valid template in the directory; an invalid file is skipped and logged."""
    bank = Bank()
    directory = Path(directory) if directory is not None else DEFAULT_DIR
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            template = parse_template(json.loads(path.read_text(encoding="utf-8")), path.name)
            if template.template_id in bank.templates:
                raise ForgeError(f"{path.name}: duplicate template_id {template.template_id}")
        except (ForgeError, ValueError) as error:
            LOG.warning("forge template skipped: %s", error)
            bank.errors.append(str(error))
            continue
        bank.templates[template.template_id] = template
    return bank


# --- Puzzles ----------------------------------------------------------------


def instance_puzzle(template: ForgeTemplate, instance: Instance, index: int,
                    original: Puzzle | None = None, template_id: str | None = None,
                    diagnostic: Diagnostic | None = None) -> ForgePuzzle:
    part2 = None
    if instance.part2 is not None:
        part2 = instance_puzzle(template, instance.part2, index, template_id=f"{template.template_id}.part2")
    return ForgePuzzle(
        template_id=template_id or template.template_id,
        params=dict(instance.params),
        population=0,
        answer=instance.answer,
        named_values=instance.wrong,
        counts={},
        recited=original.answer if original is not None else None,
        givens=checker.given_values(instance.text),
        text=instance.text,
        answer_text=instance.answer_text,
        tolerance=instance.tolerance,
        steps=instance.steps,
        part2=part2,
        topic=template.topic,
        difficulty=template.difficulty,
        instance=index,
        diagnostic=diagnostic,
    )


def _wrong_methods(instance: Instance, previous: Fraction) -> list[tuple[str, Fraction]]:
    return [(nv.misconception, nv.value) for nv in instance.wrong] + [(PREVIOUS_ANSWER, previous)]


def _nearest(instance: Instance, previous: Fraction, skip: str | None = None) -> tuple[Fraction, str, Fraction] | None:
    """(gap, misconception, value) of the wrong method closest to the right answer."""
    gaps = [(abs(instance.answer - value), name, value)
            for name, value in _wrong_methods(instance, previous) if name != skip]
    return min(gaps, key=lambda g: g[0]) if gaps else None


def twin_choice(template: ForgeTemplate, original: int, rng: random.Random,
                suspect: str | None = None) -> tuple[int, Diagnostic]:
    """The twin instance (decision log 16). Another instance, preferring one whose answer
    differs from the original's so that repeating it is detectable (Recited). With a
    suspected misconception that the template names: the largest gap between the right
    answer and that misconception's value; ties go to the largest gap to the nearest
    other wrong method. Otherwise: the largest gap to the nearest wrong method. Repeating
    the original's answer counts as a wrong method. Remaining ties are drawn at random."""
    first = template.instances[original]
    others = [i for i in range(len(template.instances)) if i != original]
    pool = [i for i in others if template.instances[i].answer != first.answer] or others
    aimed = [i for i in pool if suspect and any(nv.misconception == suspect for nv in template.instances[i].wrong)]

    def aimed_key(i: int):
        inst = template.instances[i]
        gap, value = min((abs(inst.answer - nv.value), nv.value) for nv in inst.wrong if nv.misconception == suspect)
        rest = _nearest(inst, first.answer, skip=suspect)
        return (gap, rest[0] if rest else float("inf")), Diagnostic(suspect, inst.answer, value, True)

    def spread_key(i: int):
        gap, name, value = _nearest(template.instances[i], first.answer)
        return (gap,), Diagnostic(name, template.instances[i].answer, value, False)

    key = aimed_key if aimed else spread_key
    scored = {i: key(i) for i in (aimed or pool)}
    best = max(rank for rank, _ in scored.values())
    index = rng.choice([i for i, (rank, _) in scored.items() if rank == best])
    return index, scored[index][1]


class BankSource:
    """New questions for engine.Interview: one template per new question, chosen
    from the topic at the ladder's level; twins come from the same template."""

    def __init__(self, bank: Bank, topic: str = MIXED, start: str = "Easy", rng: random.Random | None = None):
        if start not in START_LEVELS:
            raise ValueError(f"start must be one of {START_LEVELS}")
        self.templates = {t.template_id: t for t in bank.pool(topic)}
        if not self.templates:
            raise ValueError(f"no accepted templates for topic {topic!r}")
        self.topic = topic
        self.level = DIFFICULTIES.index(start)
        self.rng = rng if rng is not None else random.Random()
        self.unused = set(self.templates)
        self.levels: list[str] = []  # difficulty of each new question, in order
        self._next: tuple[int, str] | None = None

    @property
    def difficulty(self) -> str:
        return DIFFICULTIES[self.level]

    def candidates(self) -> list[str]:
        """The template the next new question would use (empty when none are left)."""
        if self._next is not None and self._next[0] == self.level and self._next[1] in self.unused:
            return [self._next[1]]
        if not self.unused:
            return []
        # Closest level to the ladder's; ties go to the easier level.
        distance = lambda tid: (abs(DIFFICULTIES.index(self.templates[tid].difficulty) - self.level),
                                DIFFICULTIES.index(self.templates[tid].difficulty))
        best = min(distance(tid) for tid in self.unused)
        choice = self.rng.choice(sorted(tid for tid in self.unused if distance(tid) == best))
        self._next = (self.level, choice)
        return [choice]

    def new(self, template_id: str) -> ForgePuzzle:
        template = self.templates[template_id]
        index = self.rng.randrange(len(template.instances))
        self.unused.discard(template_id)
        self.levels.append(template.difficulty)
        return instance_puzzle(template, template.instances[index], index)

    def twin(self, puzzle: ForgePuzzle, suspect: str | None = None) -> ForgePuzzle:
        template = self.templates[puzzle.template_id]
        index, why = twin_choice(template, puzzle.instance, self.rng, suspect)
        return instance_puzzle(template, template.instances[index], index, original=puzzle, diagnostic=why)

    def step(self, first: Outcome) -> None:
        """Ladder: up after a correct first answer, down after a wrong one; vague stays."""
        if first is Outcome.CORRECT:
            self.level = min(self.level + 1, len(DIFFICULTIES) - 1)
        elif first in WRONG_OUTCOMES:
            self.level = max(self.level - 1, 0)
