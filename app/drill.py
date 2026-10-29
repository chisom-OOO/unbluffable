"""Drill mode, minimal (decision log 16): practice aimed at one misconception the
report detected. Up to three diagnostic instances of the template where it showed,
asked with Socratic questions only (the Exam Room's challenge, step-prompt nudges and
step-prompt hints; no explanations), then one new-numbers check with no help. The
check decides the result: "Cleared" when it is Correct, otherwise "Still showing".

Drill answers are not scored by the engine and do not change any interview label.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from app import exam_text as say
from app.interview_session import GUIDE_SECONDS, ExamSession, QuestionLog, SessionClosed, _DECLINE
from engine.bank import ForgePuzzle, ForgeTemplate, aimed_puzzle, drill_plan
from engine.coding import Observation, Outcome
from engine.interview import Question
from voice.endpointing import cues

CLEARED = "Cleared"
STILL_SHOWING = "Still showing"
CHECK_GUIDE_SECONDS = GUIDE_SECONDS["drill"]


@dataclass(frozen=True)
class DrillTarget:
    """A misconception the report can drill: where it showed and the instances already used."""
    template_id: str
    misconception: str
    used: frozenset[int]


def drill_targets(session: ExamSession, templates: dict[str, ForgeTemplate]) -> list[DrillTarget]:
    """Each named misconception from the session's forge questions, in the order first
    seen, with an instance left to aim at it."""
    targets: dict[str, DrillTarget] = {}
    for q in session.questions:
        if not isinstance(q.puzzle, ForgePuzzle) or q.puzzle.template_id not in templates:
            continue
        for answer in q.answers:
            name = answer.misconception
            if not name or name in targets:
                continue
            template_id = q.puzzle.template_id
            used = frozenset(p.puzzle.instance for p in session.questions if p.puzzle.template_id == template_id)
            if drill_plan(templates[template_id], name, set(used))[1] is not None:
                targets[name] = DrillTarget(template_id, name, used)
    return list(targets.values())


@dataclass
class DrillPlan:
    """Stands in for engine.Interview in ExamSession: the drill questions in order. A
    question answered right first time, with no help, ends the drill rounds early."""
    template: ForgeTemplate
    misconception: str
    order: list[int]
    check_index: int
    source: None = None
    finished: bool = False
    results: list[tuple[Outcome, Fraction]] = field(default_factory=list)
    _pending: Question | None = None
    _previous: ForgePuzzle | None = None

    def next_question(self) -> Question | None:
        if self.finished:
            return None
        if self._pending is not None:
            return self._pending
        done = len(self.results)
        if done >= len(self.order) or (self.results and self.results[-1] == (Outcome.CORRECT, Fraction(1))):
            self.finished = True
            return None
        puzzle = aimed_puzzle(self.template, self.order[done], self.misconception, self._previous)
        self._pending = Question(done + 1, "drill", puzzle, 0.0)
        return self._pending

    def record(self, observation: Observation, weight: Fraction = Fraction(1), help_load: int = 0,
               misconception: str | None = None) -> None:
        self.results.append((observation.outcome, weight))
        self._previous = self._pending.puzzle
        self._pending = None

    def check_puzzle(self) -> ForgePuzzle:
        return aimed_puzzle(self.template, self.check_index, self.misconception, self._previous)


class DrillSession(ExamSession):
    def __init__(self, send, listen, analyzer, template: ForgeTemplate, target: DrillTarget, **kwargs):
        order, check = drill_plan(template, target.misconception, set(target.used))
        if check is None:
            raise ValueError("no instance left to drill this misconception")
        super().__init__(send, listen, analyzer, DrillPlan(template, target.misconception, order, check), **kwargs)
        self.target = target
        self.check: QuestionLog | None = None
        self.result: str | None = None

    async def run(self) -> None:
        try:
            await self.line("prompt", say.DRILL_OPENING)
            while (question := self.interview.next_question()) is not None:
                await self.ask(question)
                await self.question_loop(self.questions[-1])
                if self.questions[-1].scored is not None:
                    await self.scored_event()
            await self.ask_check()
            self.result = CLEARED if self.check.scored == Outcome.CORRECT.value else STILL_SHOWING
            await self.line("close", say.DRILL_CLOSE)
            self.finished = True
            await self.send({"type": "session_end", "drill": True, "result": self.result, "timed_out": False})
        except SessionClosed:
            return

    async def scored_event(self) -> None:
        """Drill answers are not scored by the engine: no evidence meter, only the
        "Why these numbers?" note."""
        q = self._scored[-1]
        await self.send({"type": "scored", "number": q.number, "outcome": q.scored, "meter": None,
                         "why": say.why_numbers(q.puzzle.diagnostic)})

    async def ask_check(self) -> None:
        """The new-numbers check: asked once, no challenge and no help."""
        puzzle = self.interview.check_puzzle()
        q = QuestionLog(len(self.questions) + 1, "check", puzzle, puzzle.text, CHECK_GUIDE_SECONDS, self.clock())
        self.check = q
        await self.send({"type": "question", "number": q.number, "kind": "check", "template": puzzle.template_id,
                         "text": puzzle.text, "topic": puzzle.topic or None, "difficulty": puzzle.difficulty or None,
                         "guide_seconds": CHECK_GUIDE_SECONDS})
        await self.line("question", f"{say.DRILL_CHECK_INTRO} {puzzle.text}")
        while True:
            text = await self.listen()
            q.said.append(text)
            cue = cues(text)
            if cue is not None and cue.kind == "question":
                await self.line("question", f"{say.REPEAT_INTRO} {puzzle.text}")
                continue
            if cue is not None and cue.kind == "help":
                await self.line("prompt", say.DRILL_NO_HELP)
                continue
            if _DECLINE.match(text):
                continue
            await self.send({"type": "answer_complete", "transcript": text, "acknowledgement": self._ack()})
            await self.state("checking")
            analysis = await self.analyzer.analyse(puzzle, text, self.send)
            await self.send({"type": "analysis_complete"})
            answer = self._answer(puzzle, text, analysis)
            q.answers.append(answer)
            obs = analysis.observation
            if obs is None or obs.outcome is Outcome.ABSTAIN:
                await self.line("prompt", say.UNCHECKED)
                continue
            q.scored, q.weight, q.recovered = obs.outcome.value, Fraction(1), False
            if obs.outcome is not Outcome.CORRECT:
                q.first_wrong = (obs, analysis.span)
            q.seconds = self.clock() - q.started
            await self.line("close", say.CORRECT_CLOSE if obs.outcome is Outcome.CORRECT else say.DRILL_CHECK_THANKS,
                            receipt=answer.receipt)
            return
