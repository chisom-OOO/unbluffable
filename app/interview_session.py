"""One Exam Room interview: questions, challenge, nudges and hints, scoring (spec/02 §7).

The controller is transport-free: it gets `send(event)` and `listen()` from the
route (or a test). Each question is scored once from its final outcome
(decision log 3b) through engine.Interview.record(observation, weight, help_load).
Nothing here is persisted; the session lives in memory only.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Awaitable, Callable

from app import exam_text as say
from engine.answers import StatedNumber, matches, normalise_numbers, parse_number
from engine.coding import Observation, Outcome, code_answer
from engine.help import position, strength, weight_for
from engine.interview import Interview, Question
from engine.templates import POPULATIONS, Puzzle
from voice.answers import restated_given
from voice.endpointing import cues
from voice.numbers import number_from_text
from voice.recording import VoiceError
from voice.schemas import CONTEXT, FULL, FULL_PROMPT, MINIMAL, MINIMAL_PROMPT

# Gap filled (spec/01 says "up to 4 rounds"): the challenge is round 1, so a
# candidate gets the challenge plus up to three nudges before "not recovered".
MAX_ROUNDS = 4
# Session countdown (decision log 10). ASSUMPTION for the builder to confirm: at 0:00 the
# interviewer finishes the current question, then closes and shows the report.
SESSION_SECONDS = 600
GUIDE_SECONDS = {"new": 120, "twin": 60}
_DECLINE = re.compile(r"^\s*(?:no|nope|not really|no thanks|no thank you|i'?m (?:fine|ok|okay|good))\W*$", re.I)


class SessionClosed(Exception):
    """The candidate left or the connection closed."""


# --- Analysis of one answer for the current puzzle -------------------------

_FLAGSHIP_FACTS = "The question asks P(fraud given flagged): 1% fraud, 90% of fraud flagged, 5% of genuine flagged. "


def context_for(puzzle: Puzzle) -> str:
    """voice/schemas CONTEXT for any puzzle; for the flagship it is byte-identical,
    so existing recordings still replay."""
    v = puzzle.params
    if puzzle.template_id == "T1":
        facts = (f"The question asks P(fraud given flagged): {say.pct(v['p'])} fraud, "
                 f"{say.pct(v['s'])} of fraud flagged, {say.pct(v['f'])} of genuine flagged. ")
    elif puzzle.template_id == "T2":
        facts = (f"The question asks P(machine A given defective): A makes {say.pct(v['a'])} of items, "
                 f"{say.pct(v['dA'])} of A's and {say.pct(v['dB'])} of B's items are defective. ")
    else:
        facts = (f"The question asks P(biased coin given {int(v['k'])} heads): biased coin {say.pct(v['q'])} "
                 f"of the time, lands heads {say.pct(v['b'])} of the time; otherwise a fair coin. ")
    return CONTEXT.replace(_FLAGSHIP_FACTS, facts)


def stated_in(text: str, span: str) -> StatedNumber | None:
    """The committed number in `span`, unless it is a restated given. voice.numbers reads
    spoken forms; engine.answers also reads "18 out of 117", which it does not."""
    if not span or span == "none" or restated_given(text, span):
        return None
    return number_from_text(span) or parse_number(span)


@dataclass
class Analysis:
    observation: Observation | None  # None: the answer could not be checked
    stated: StatedNumber | None = None
    span: str | None = None


class VoiceAnalyzer:
    """voice.answers' two lanes, generalised to the current puzzle. Uses the voice
    provider's recorded Spark calls; code decides every outcome."""

    def __init__(self, provider):
        self.provider = provider

    async def analyse(self, puzzle: Puzzle, text: str, send) -> Analysis:
        context = context_for(puzzle)
        minimal_prompt = MINIMAL_PROMPT.replace(CONTEXT, context)
        full_prompt = FULL_PROMPT.replace(CONTEXT, context)

        async def fast():
            try:
                parsed, model = await self.provider.structured(text, "minimal", "minimal", MINIMAL, minimal_prompt)
                span = parsed["committed_number_text"]
                if not parsed["is_commitment"]:
                    span = "none"
                elif not span or span == "none" or span not in text:
                    raise VoiceError("The committed number was not found verbatim in your answer.")
                stated = stated_in(text, span)
                wrong = stated is not None and not matches(stated, puzzle.answer)
                await send({"type": "challenge_result", "should_challenge": wrong, "message": None,
                            "number_found": stated is not None,
                            "stated_number": str(stated.value) if stated else None, "model": model})
                return stated, (span if stated else None)
            except VoiceError as error:
                await send({"type": "model_error", "job": "minimal", "message": str(error)})
                return None

        async def full():
            try:
                parsed, model = await self.provider.structured(text, "extraction", "low", FULL, full_prompt)
                parsed["reasoning_quotes"] = [r for r in parsed["reasoning_quotes"] if r["quote"] and r["quote"] in text]
                if parsed["committed_answer_text"] not in text:
                    parsed["committed_answer_text"] = "none"
                if not parsed["reasoning_quotes"]:
                    parsed["reasoning_code"] = "vague"
                span = parsed["committed_answer_text"]
                stated = stated_in(text, span)
                observation = code_answer(puzzle, stated, parsed["reasoning_code"])
                await send({"type": "scoring_result", "extraction": parsed,
                            "observation": observation.outcome.value, "model": model})
                return observation, stated, (span if stated else None)
            except VoiceError as error:
                await send({"type": "model_error", "job": "extraction", "message": str(error)})
                return None

        quick, scored = await asyncio.gather(fast(), full())
        if scored is not None:
            return Analysis(*scored)
        if quick is not None:
            # No reasoning check: the number alone can show a wrong answer, never Correct.
            stated, span = quick
            return Analysis(code_answer(puzzle, stated, "vague"), stated, span)
        return Analysis(None)


# --- Numbers the candidate has said (for the solution-map position) --------

_COUNT = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?![\d,])|(?<![\d.,])\d+(?:\.\d+)?(?![\d,])")


def numbers_in(text: str) -> list[Fraction]:
    out = []
    for token in _COUNT.findall(normalise_numbers(text)):
        out.append(Fraction(token.replace(",", "")))
    return out


_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b|per\s+cent\b)", re.I)
_RATIO = re.compile(r"(\d[\d,]*)\s*(?:/|out\s+of)\s*(\d[\d,]*)", re.I)


def leak(puzzle: Puzzle, text: str, said: list[Fraction], population: int | None) -> str | None:
    """Why a nudge or hint may not be spoken, or None (spec/01 leak guard, decision log 3a).

    Blocks the answer in any form, and any number that is not a given, not already
    said by the candidate, and not the template's round population.
    """
    plain = normalise_numbers(text)
    givens = set(puzzle.givens)
    allowed = set(said) | givens | {Fraction(puzzle.population)}
    if population is not None:
        allowed.add(Fraction(population))
    for a, b in _RATIO.findall(plain):
        num, den = Fraction(a.replace(",", "")), Fraction(b.replace(",", ""))
        if den and num / den == puzzle.answer:
            return "answer"
    for value in _PERCENT.findall(plain):
        share = Fraction(value) / 100
        if matches(StatedNumber(share, "percent"), puzzle.answer):
            return "answer"
        if share not in givens and share not in said:
            return f"new number {value}%"
    for value in numbers_in(_PERCENT.sub(" ", plain)):
        if value not in allowed and value / 100 not in givens:
            return f"new number {value}"
    return None


# --- Session state ----------------------------------------------------------


@dataclass
class Answer:
    transcript: str
    outcome: str | None  # None: unchecked
    stated: str | None  # the candidate's committed number as a fraction string
    span: str | None  # the words they used for it


@dataclass
class QuestionLog:
    number: int
    kind: str  # "new" or "twin"
    puzzle: Puzzle
    text: str
    guide_seconds: int
    started: float
    answers: list[Answer] = field(default_factory=list)
    challenges: int = 0
    nudges: int = 0
    hints: int = 0
    help_load: int = 0
    numbers: list[Fraction] = field(default_factory=list)
    said: list[str] = field(default_factory=list)  # the candidate's own words, for written help
    help_lines: list[tuple[str, str]] = field(default_factory=list)  # (challenge|nudge|hint, text)
    population: int | None = None  # round population, once the candidate or a hint has one
    first_wrong: tuple[Observation, str | None] | None = None
    scored: str | None = None
    weight: Fraction | None = None
    recovered: bool | None = None
    seconds: float | None = None

    @property
    def position(self) -> int:
        if self.puzzle.template_id != "T1":
            return 0
        return position(self.puzzle, self.numbers, self.population)


class ExamSession:
    def __init__(
        self,
        send: Callable[[dict], Awaitable[None]],
        listen: Callable[[], Awaitable[str]],
        analyzer,
        interview: Interview | None = None,
        deadline: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        writer=None,
    ):
        """`writer`, if given, drafts nudges and hints for the candidate's own words:
        `await writer(puzzle, kind, transcripts, position)` -> (text, target step or None) or None.
        Code checks every draft with `leak` and computes its strength; a rejected or
        missing draft falls back to the plain step prompt (spec/01)."""
        self.send, self.listen, self.analyzer, self.writer = send, listen, analyzer, writer
        self.interview = interview if interview is not None else Interview(demo=True)
        self.deadline, self.clock = deadline, clock
        self.questions: list[QuestionLog] = []
        self.timed_out = False
        self.finished = False
        self._acks = 0

    # --- events ---
    async def line(self, kind: str, text: str, target: int | None = None) -> None:
        if self.questions and kind in {"challenge", "nudge", "hint"}:
            self.questions[-1].help_lines.append((kind, text))
        await self.send({"type": "interviewer_line", "kind": kind, "text": text, "target_step": target,
                         "counts": self._counts()})

    def _counts(self) -> dict:
        q = self.questions[-1] if self.questions else None
        return {"challenges": q.challenges if q else 0, "nudges": q.nudges if q else 0, "hints": q.hints if q else 0}

    async def state(self, value: str) -> None:
        await self.send({"type": "state", "value": value})

    # --- flow ---
    async def run(self) -> None:
        try:
            while True:
                question = self.interview.next_question()
                if question is None:
                    break
                await self.ask(question)
                await self.question_loop(self.questions[-1])
                if self.deadline is not None and self.clock() >= self.deadline and not self.interview.finished:
                    self.timed_out = True
                    break
            await self.line("close", say.TIME_CLOSE if self.timed_out else say.SESSION_CLOSE)
            self.finished = True
            await self.send({"type": "session_end", "label": self.interview.label.value,
                             "timed_out": self.timed_out})
        except SessionClosed:
            return

    async def ask(self, question: Question, repeat: bool = False) -> None:
        text = say.puzzle_text(question.puzzle)
        if not repeat:
            self.questions.append(QuestionLog(question.number, question.kind, question.puzzle, text,
                                              GUIDE_SECONDS[question.kind], self.clock()))
            await self.send({"type": "question", "number": question.number, "kind": question.kind,
                             "template": question.puzzle.template_id, "text": text,
                             "guide_seconds": GUIDE_SECONDS[question.kind]})
        if repeat:
            spoken = f"{say.REPEAT_INTRO} {text}"
        elif question.kind == "twin":
            spoken = f"{say.TWIN_INTRO} {text}"
        elif question.number > 1:
            spoken = f"{say.NEW_PUZZLE_INTRO} {text}"
        else:
            spoken = f"{text} {say.OPENING}"
        await self.line("question", spoken)

    async def question_loop(self, q: QuestionLog) -> None:
        question = self.interview.next_question()
        rounds = 0
        challenged = False
        while True:
            text = await self.listen()
            q.said.append(text)
            q.numbers += numbers_in(text)
            self._note_population(q)
            cue = cues(text)
            if cue is not None and cue.kind == "question":
                await self.ask(question, repeat=True)
                continue
            if cue is not None and cue.kind == "help":
                await self.give_hint(q)
                continue
            if _DECLINE.match(text):
                continue  # "no" to an offer of help costs nothing
            await self.send({"type": "answer_complete", "transcript": text, "acknowledgement": self._ack()})
            await self.state("checking")
            analysis = await self.analyzer.analyse(q.puzzle, text, self.send)
            await self.send({"type": "analysis_complete"})
            obs = analysis.observation
            q.answers.append(Answer(text, obs.outcome.value if obs else None,
                                    str(analysis.stated.value) if analysis.stated else None, analysis.span))
            if obs is None or obs.outcome is Outcome.ABSTAIN:
                await self.line("prompt", say.UNCHECKED)
                continue
            if obs.outcome is Outcome.CORRECT:
                weight = weight_for(q.help_load, challenged=challenged)
                self._score(q, obs, weight, recovered=challenged)
                await self.line("close", say.CORRECT_CLOSE)
                return
            if q.first_wrong is None:
                q.first_wrong = (obs, analysis.span)
            if rounds >= MAX_ROUNDS:
                self._score(q, q.first_wrong[0], Fraction(1), recovered=False)
                await self.line("close", say.NOT_RECOVERED_CLOSE)
                return
            rounds += 1
            if not challenged:
                challenged = True
                q.challenges += 1
                await self.line("challenge", self._challenge_text(q, obs, analysis))
            else:
                await self.nudge(q, obs)

    def _challenge_text(self, q: QuestionLog, obs: Observation, analysis: Analysis) -> str:
        if analysis.stated is None:
            return say.ASK_FOR_ANSWER
        if obs.outcome is Outcome.VAGUE:  # right number, reasoning not shown
            return say.ASK_WHY
        return say.challenge(q.puzzle, analysis.stated, analysis.span, obs.misconception)

    def _next_step(self, q: QuestionLog, at: int) -> tuple[int | None, str]:
        """Plain step prompt for the step after `at` (spec/01: the fallback when no model text)."""
        if q.puzzle.template_id != "T1":
            return None, say.GENERIC_NUDGE
        if at >= 6:
            return None, say.ASK_WHY
        target = at + 1
        if q.population is None:
            q.population = q.puzzle.population  # the template's round population (decision log 9)
        return target, say.step_prompt(q.puzzle, target, q.population)

    async def nudge(self, q: QuestionLog, obs: Observation) -> None:
        """Rounds 2-4: aimed at the candidate's next step; its strength counts toward H."""
        q.nudges += 1
        await self.help(q, "nudge")

    async def give_hint(self, q: QuestionLog) -> None:
        """Help on request: ask what they are stuck on, then hint for that (spec/01)."""
        await self.line("prompt", say.HELP_ASK)
        text = await self.listen()
        q.said.append(text)
        q.numbers += numbers_in(text)
        self._note_population(q)
        q.hints += 1
        await self.help(q, "hint")

    async def help(self, q: QuestionLog, kind: str) -> None:
        at = q.position
        target, text = self._next_step(q, at)
        draft = await self.writer(q.puzzle, kind, list(q.said), at) if self.writer else None
        if draft is not None:
            drafted, step = draft
            valid_step = step is None or (q.puzzle.template_id == "T1" and 1 <= step <= 6)
            if valid_step and drafted.strip() and leak(q.puzzle, drafted, q.numbers, q.population) is None:
                target, text = step, drafted.strip()
        if target is not None:
            q.help_load += strength(target, at)
        await self.line(kind, text, target)

    def _note_population(self, q: QuestionLog) -> None:
        if q.population is None:
            rounds = [int(x) for x in q.numbers if x.denominator == 1 and int(x) in POPULATIONS]
            if rounds:
                q.population = rounds[0]

    def _ack(self) -> str:
        text = say.ACKNOWLEDGEMENTS[self._acks % len(say.ACKNOWLEDGEMENTS)]
        self._acks += 1
        return text

    def _score(self, q: QuestionLog, obs: Observation, weight: Fraction, recovered: bool) -> None:
        self.interview.record(obs, weight=weight, help_load=q.help_load)
        q.scored, q.weight, q.recovered = obs.outcome.value, weight, recovered
        q.seconds = self.clock() - q.started
