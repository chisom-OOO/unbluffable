"""A committed number that only restates a number from the question is not an answer
("restated a given number"), for forge questions on every track. Real content, fake model."""

import asyncio
from fractions import Fraction

import pytest

from app.interview_session import VoiceAnalyzer, stated_in
from engine.bank import instance_puzzle, load_bank
from voice.answers import RESTATED_GIVEN, given_number, restated_given


def text_of(x: Fraction) -> str:
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"


def case(pack):
    """A puzzle on this track and a number its question states that is neither its answer
    nor a named wrong value."""
    bank = load_bank()
    for template in sorted((t for t in bank.templates.values() if t.pack == pack), key=lambda t: t.template_id):
        for i, inst in enumerate(template.instances):
            puzzle = instance_puzzle(template, inst, i)
            named = {nv.value for nv in puzzle.named_values}
            for g in puzzle.givens:
                if g != puzzle.answer and g not in named and g > 1 and g.denominator == 1:
                    return puzzle, g
    pytest.skip(f"no {pack} family states a usable number")


@pytest.mark.parametrize("pack", ["quant", "ib", "consulting", "software"])
def test_a_number_from_the_question_is_not_a_commitment(pack):
    puzzle, given = case(pack)
    span = text_of(given)
    text = f"So my answer is {span}."
    assert given_number(span, puzzle.givens, puzzle.answer)
    assert stated_in(text, span, puzzle) is None
    # The real answer, said the same way, still counts.
    answer = text_of(puzzle.answer)
    assert stated_in(f"So my answer is {answer}.", answer, puzzle).value == puzzle.answer


class Minimal:
    """Fake Spark: the committed span is whatever follows "answer is"."""
    mode = "live"

    async def structured(self, text, kind, effort, schema, prompt):
        span = text.split("answer is ", 1)[1].rstrip(".").split(",")[0] if "answer is " in text else "none"
        if kind == "minimal":
            return {"committed_number_text": span, "is_commitment": span != "none"}, {"model": "fake"}
        return {"committed_answer_text": span, "reasoning_quotes": [{"quote": text, "step": "other"}],
                "reasoning_code": "valid", "misconception_name": "none", "self_corrected": False}, {"model": "fake"}


@pytest.mark.parametrize("pack", ["quant", "ib", "consulting", "software"])
def test_the_analyser_flags_it_and_the_silence_check_waits(pack):
    puzzle, given = case(pack)
    text = f"My answer is {text_of(given)}, because that is in the question."
    events = []

    async def send(event):
        events.append(event)

    analyzer = VoiceAnalyzer(Minimal())
    analysis = asyncio.run(analyzer.analyse(puzzle, text, send))
    assert analysis.stated is None and analysis.observation.outcome.value != "correct"
    challenge = next(e for e in events if e["type"] == "challenge_result")
    assert challenge["note"] == RESTATED_GIVEN and challenge["number_found"] is False
    assert asyncio.run(analyzer.committed(puzzle, text)) is False
    right = f"My answer is {text_of(puzzle.answer)}, because I worked it out."
    assert asyncio.run(analyzer.committed(puzzle, right)) is True


def test_answers_and_named_mistakes_that_repeat_a_given_still_count():
    givens = (Fraction(5), Fraction(40), Fraction(2, 5))
    assert given_number("40", givens) and given_number("40%", givens)  # 40% read as the share 2/5
    assert not given_number("5", givens, answer=Fraction(5))  # the answer itself
    assert not given_number("40", givens, named=(Fraction(40),))  # a named wrong method, e.g. "gives the target"
    assert not given_number("7", givens) and not given_number("none", givens)
    # Without givens (the flagship path), only the fraud wording counts, as before.
    assert restated_given("The detector catches 90% of fraud.", "90%")
    assert not restated_given("So it's 40.", "40")
    assert restated_given("So it's 40.", "40", givens)
