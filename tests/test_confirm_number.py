"""Misheard numbers (decision log 27): a committed number that isn't clearly in the
transcript, or that the two extraction lanes read differently, is confirmed before grading;
a "no" reopens the answer. The question's terms bias live transcription (keywords)."""

import asyncio
import random
from fractions import Fraction

from app import exam_text as say
from app.interview_session import ExamSession, unclear
from engine.answers import StatedNumber
from engine.bank import BankSource
from engine.interview import Interview
from test_bank_runtime import ScriptedProvider
from test_exam_session import Analyzer, bag_bank, lines, red


class Unsure(Analyzer):
    """The real analyser, marking answers that contain "(unsure)" as possibly misheard."""

    async def analyse(self, puzzle, text, send):
        analysis = await super().analyse(puzzle, text.replace(" (unsure)", ""), send)
        analysis.confirm = "(unsure)" in text
        return analysis


def run(script, conditions="exam"):
    events, queue = [], list(script)

    async def send(event):
        events.append(event)

    async def listen():
        r = red(session.questions[-1].puzzle)
        return queue.pop(0).format(r=r, n=r + 11)

    source = BankSource(bag_bank(), "Probability", "Easy", rng=random.Random(1))
    session = ExamSession(send, listen, Unsure(ScriptedProvider()), Interview(rng=random.Random(5), source=source))
    session.conditions = conditions
    asyncio.run(session.run())
    assert not queue, queue
    return session, events


RIGHT = "My answer is {r}/{n}, because red over all balls."


def test_a_possibly_misheard_number_is_confirmed_and_a_yes_grades_it():
    session, events = run([RIGHT + " (unsure)", "Yes", RIGHT])
    prompts = [e for e in lines(events, "prompt")]
    q1 = session.questions[0]
    assert prompts[0]["text"] == say.CONFIRM.format(number=f"{red(q1.puzzle)}/{red(q1.puzzle) + 11}")
    assert prompts[0]["speech"].startswith("Just to check, did you say ") and "/" not in prompts[0]["speech"]
    assert q1.scored == "correct" and q1.weight == 1 and len(q1.answers) == 1


def test_a_no_reopens_the_answer_and_the_misheard_one_is_never_graded():
    session, events = run(["My answer is 11/{n}, because blue over all balls. (unsure)", "No", RIGHT, RIGHT])
    q1 = session.questions[0]
    assert [e["text"] for e in lines(events, "prompt")][:2][1] == say.REOPEN
    assert not lines(events, "challenge")  # the misheard wrong number was never challenged
    assert q1.scored == "correct" and q1.weight == 1 and len(q1.answers) == 1


def test_a_no_with_the_right_number_is_taken_as_the_answer():
    session, events = run(["My answer is 11/{n}, because blue. (unsure)", "No, " + RIGHT, RIGHT])
    assert session.questions[0].scored == "correct" and say.REOPEN not in [e["text"] for e in lines(events, "prompt")]


def test_typed_answers_are_never_confirmed():
    session, events = run([RIGHT + " (unsure)", RIGHT], conditions="typed")
    assert not any(e["text"].startswith("Just to check") for e in lines(events, "prompt"))


def test_unclear_spans():
    five = StatedNumber(Fraction(5), "integer", "5")
    assert unclear("5 7", five) and unclear("five seven", five)
    assert not unclear("five sevenths", StatedNumber(Fraction(5, 7), "fraction"))
    assert not unclear("18 out of 117", StatedNumber(Fraction(18, 117), "fraction"))
    assert not unclear("15 percent", StatedNumber(Fraction(3, 20), "percent", "15"))


def test_spoken_confirmations_read_as_words():
    assert say.number_said(StatedNumber(Fraction(5, 7), "fraction")) == ("5/7", "five sevenths")
    assert say.number_said(StatedNumber(Fraction(3, 20), "percent", "15")) == ("15%", "15 percent")


def test_live_transcription_is_biased_with_the_question_terms(tmp_path, monkeypatch):
    """The handshake's documented `keywords` (spec/03) carry the current question's terms."""
    import json
    from app.interview_session import question_terms
    from engine.bank import instance_puzzle
    from test_exam_session import BAG
    from test_voice_relay import Browser, Upstream
    from voice.provider import KEYWORDS, MetaVoice
    from voice.relay import realtime_answer

    terms = question_terms(instance_puzzle(BAG, BAG.instances[0], 0))
    assert terms and len(terms) <= 12 and not any(c.isdigit() for t in terms for c in t)
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-server-key")
    upstream = Upstream()
    asyncio.run(asyncio.wait_for(realtime_answer(Browser(), MetaVoice(record_dir=tmp_path), {"sample_rate": 16000},
                                                 connect=lambda url, **kw: upstream, keywords=terms), 2))
    sent = json.loads(upstream.frames[0])["keywords"]
    assert sent[:len(KEYWORDS)] == KEYWORDS and set(terms) <= set(sent)
