"""Decision log 39: a committed number within 0.1% of the exact answer, but not accepted, gets
"Close. How precise is your last step?" in place of the challenge or nudge. It is still not
coded Correct. Bag template from test_bank_runtime (P(red) = r / (r + 11)); no network."""

import random
from fractions import Fraction
from types import SimpleNamespace

from app import exam_text as say
from app.interview_session import Analysis, near_miss
from engine.answers import StatedNumber
from engine.bank import BankSource
from engine.coding import Observation, Outcome
from test_bank_runtime import _bag, _bag_bank, run


def source():
    return BankSource(_bag_bank(_bag()), "Probability", "Easy", rng=random.Random(3))


def lines(events, kind):
    return [e["text"] for e in events if e.get("type") == "interviewer_line" and e.get("kind") == kind]


def off_by(answer: Fraction, share: str) -> str:
    """The answer moved by a relative `share`, written to six decimals (finer than the slip,
    so the rounding rule can't accept it)."""
    return f"{float(answer * (1 - Fraction(share))):.6f}"


def test_a_near_miss_gets_the_precision_line_and_is_never_correct():
    said = []

    def policy(session, events):
        q = session.questions[-1]
        if len(q.said) == 0 and q.number == 1:
            value = off_by(q.puzzle.answer, "0.0005")  # 0.05% short
        else:
            value = q.puzzle.answer_text
        said.append(value)
        return f"My answer is {value}, because red over all balls."

    session, events, _ = run(source(), policy)
    first = session.questions[0]
    assert first.answers[0].outcome == Outcome.OTHER_WRONG.value  # not accepted, not Correct
    assert lines(events, "challenge")[0] == say.NEAR_MISS == "Close. How precise is your last step?"
    assert first.challenges == 1 and first.help_load == 0  # counts as the challenge, no help load


def test_a_near_miss_after_the_challenge_replaces_the_nudge_without_help_load():
    def policy(session, events):
        q = session.questions[-1]
        if q.number == 1 and len(q.said) == 0:
            return "My answer is 1/2, because half of them."  # far off: the usual challenge
        if q.number == 1 and len(q.said) == 1:
            return f"My answer is {off_by(q.puzzle.answer, '0.0009')}, because red over all balls."
        return f"My answer is {q.puzzle.answer_text}, because red over all balls."

    session, events, _ = run(source(), policy)
    first = session.questions[0]
    assert lines(events, "challenge")[0].startswith("You said")
    assert lines(events, "nudge")[0] == say.NEAR_MISS
    assert first.nudges == 1 and first.help_load == 0
    assert all(a.outcome != Outcome.CORRECT.value for a in first.answers[:2])


def test_beyond_a_tenth_of_a_percent_is_the_usual_challenge():
    def policy(session, events):
        q = session.questions[-1]
        if q.number == 1 and len(q.said) == 0:
            return f"My answer is {off_by(q.puzzle.answer, '0.002')}, because red over all balls."
        return f"My answer is {q.puzzle.answer_text}, because red over all balls."

    session, events, _ = run(source(), policy)
    assert lines(events, "challenge")[0].startswith("You said")
    assert say.NEAR_MISS not in lines(events, "nudge")


def puzzle(answer, named=()):
    return SimpleNamespace(answer=Fraction(answer), named_values=tuple(SimpleNamespace(value=Fraction(v)) for v in named))


def analysis(value, outcome=Outcome.OTHER_WRONG, matched=()):
    stated = StatedNumber(Fraction(value), "decimal", str(value))
    return Analysis(Observation(outcome, stated, matched=matched), stated=stated)


def test_a_known_wrong_method_keeps_the_usual_challenge():
    # Within 0.1% but it is a named wrong method: a method mistake, not precision.
    assert near_miss(puzzle("1000"), analysis("999.5", Outcome.NAMED_WRONG, ("wrong_1",))) is False
    assert near_miss(puzzle("1000"), analysis("999.5")) is True


def test_an_exact_answer_of_zero_never_triggers_it():
    assert near_miss(puzzle("0"), analysis("0.0000001")) is False


def test_the_boundary_is_a_tenth_of_a_percent_exactly():
    assert near_miss(puzzle("1000"), analysis("999")) is True     # 0.1%
    assert near_miss(puzzle("1000"), analysis("1001")) is True
    assert near_miss(puzzle("1000"), analysis("998.999")) is False
    assert near_miss(puzzle("-1000"), analysis("-999")) is True


def test_correct_and_vague_answers_are_never_near_misses():
    assert near_miss(puzzle("1000"), analysis("1000", Outcome.CORRECT)) is False
    assert near_miss(puzzle("1000"), analysis("999.5", Outcome.VAGUE)) is False
    assert near_miss(puzzle("1000"), Analysis(None)) is False
