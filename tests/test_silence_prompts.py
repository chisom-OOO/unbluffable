"""Decision log 40: "Want to talk me through where you are?" at most once per question, only after
20 s of silence with no committed number; one "Take your time..." line once the silence passes
60 s; the 8 s commitment check still ends the turn. Fake clocks and models; no network."""

import asyncio
import random

import pytest

from app.interview_session import ExamSession, VoiceAnalyzer
from engine.bank import BankSource
from engine.interview import Interview
from voice.endpointing import PATIENCE, PROMPT, SilencePrompts
from voice.relay import wait_for_endpoint
from voice.turns import AnswerMerger
from test_bank_runtime import ScriptedProvider, _bag, _bag_bank

assert PROMPT == "Want to talk me through where you are?"
assert PATIENCE == "Take your time. Say your answer when you're ready, or press Done."


class Browser:
    def __init__(self):
        self.events = []

    async def send_json(self, event):
        self.events.append(event)

    def said(self):
        return [e["message"] for e in self.events if e["type"] == "listening_prompt"]


class Thinking:
    async def endpoint(self, text):
        return {"finished": False, "kind": "thinking"}, {}


def interviewer_speaking(merger, value, now, headphones=False):
    """What voice.relay does when the browser says the interviewer started or stopped speaking."""
    merger.paused = bool(value) and not headphones
    merger.last_activity = now
    merger.revision += 1


class Room:
    """wait_for_endpoint on a fake clock: `at(t)` moves time and lets the loop run."""

    def __init__(self, prompts=None, committed=False, transcript="I have the first count."):
        self.clock, self.checks = [0.0], []
        self.merger, self.browser, self.changed = AnswerMerger(), Browser(), asyncio.Event()
        self.prompts = prompts if prompts is not None else SilencePrompts()
        if transcript:
            self.merger.feed({"type": "speechStart", "turnId": 1}, 0)
            self.merger.feed({"type": "speechComplete", "turnId": 1, "transcript": transcript}, 0)
        self.committed = committed

    async def check(self, text):
        self.checks.append((self.clock[0], text))
        return self.committed

    def start(self):
        self.task = asyncio.create_task(wait_for_endpoint(self.merger, Thinking(), self.browser, self.changed,
                                                          lambda: self.clock[0], silence_check=self.check,
                                                          prompts=self.prompts))

    async def at(self, t):
        self.clock[0] = t
        self.changed.set()
        for _ in range(5):
            await asyncio.sleep(.005)

    async def stop(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


def run(coroutine):
    asyncio.run(coroutine())


@pytest.mark.parametrize("transcript", ["I have the first count.", ""])
def test_no_prompt_before_twenty_seconds_of_silence(transcript):
    async def exercise():
        room = Room(transcript=transcript)
        room.start()
        try:
            for t in (1, 8.0, 8.2, 12, 19.9):
                await room.at(t)
                assert room.browser.said() == [], f"prompted at {t} s"
            await room.at(20.0)
            assert room.browser.said() == [PROMPT]
        finally:
            await room.stop()
    run(exercise)


def test_the_commitment_check_still_ends_the_turn_at_eight_seconds():
    async def exercise():
        room = Room(committed=True, transcript="So it's 11/44.")
        room.start()
        try:
            await room.at(7.9)
            assert not room.task.done()
            await room.at(8.0)
            assert await asyncio.wait_for(room.task, 1) == "silence_commitment"
            assert room.browser.said() == [] and len(room.checks) == 1
        finally:
            await room.stop()
    run(exercise)


def test_at_most_one_prompt_per_question_even_after_new_speech():
    async def exercise():
        room = Room()
        room.start()
        try:
            await room.at(20)
            assert room.browser.said() == [PROMPT]
            interviewer_speaking(room.merger, True, 20.1)   # the prompt is spoken
            await room.at(20.1)
            interviewer_speaking(room.merger, False, 22.0)
            await room.at(22.0)
            room.merger.feed({"type": "speechStart", "turnId": 2}, 30)
            room.merger.feed({"type": "speechComplete", "turnId": 2, "transcript": "and then I divide"}, 31)
            for t in (31, 45, 52, 70):
                await room.at(t)
            assert room.browser.said().count(PROMPT) == 1
        finally:
            await room.stop()
    run(exercise)


def test_the_limit_holds_across_recordings_of_the_same_question():
    async def exercise():
        prompts = SilencePrompts()  # the question's own state, shared by each recording
        first = Room(prompts=prompts)
        first.start()
        await first.at(20)
        await first.stop()
        second = Room(prompts=prompts)
        second.start()
        try:
            for t in (20, 40, 59):
                await second.at(t)
            assert first.browser.said() == [PROMPT] and second.browser.said() == []
        finally:
            await second.stop()
    run(exercise)


def test_no_back_to_back_repeats_and_one_patience_line_after_sixty_seconds():
    async def exercise():
        room = Room()
        room.start()
        try:
            for t in (20, 30, 40, 59.9):
                await room.at(t)
            assert room.browser.said() == [PROMPT]
            await room.at(60)
            assert room.browser.said() == [PROMPT, PATIENCE]
            for t in (90, 120, 200, 400):
                await room.at(t)
            assert room.browser.said() == [PROMPT, PATIENCE]
            said = room.browser.said()
            assert all(a != b for a, b in zip(said, said[1:]))
        finally:
            await room.stop()
    run(exercise)


def test_silence_restarts_after_the_interviewers_line():
    async def exercise():
        room = Room()
        room.start()
        try:
            await room.at(15)
            interviewer_speaking(room.merger, True, 15)   # e.g. a line the interviewer reads out
            await room.at(15)
            interviewer_speaking(room.merger, False, 18)
            await room.at(30)
            assert room.browser.said() == [], "only 12 s since the interviewer stopped"
            await room.at(38)
            assert room.browser.said() == [PROMPT]
        finally:
            await room.stop()
    run(exercise)


def test_no_prompt_while_the_interviewer_is_speaking():
    async def exercise():
        room = Room()
        room.merger.paused = True
        room.start()
        try:
            await room.at(100)
            assert room.browser.said() == []
        finally:
            await room.stop()
    run(exercise)


def test_each_question_has_its_own_prompt_state():
    async def send(event):
        pass

    async def listen():
        return ""

    source = BankSource(_bag_bank(_bag()), "Probability", "Easy", rng=random.Random(1))
    session = ExamSession(send, listen, VoiceAnalyzer(ScriptedProvider()), Interview(rng=random.Random(2), source=source))
    assert session.silence_prompts() is None  # no question yet

    async def ask_two():
        await session.ask(session.interview.next_question())
        first = session.silence_prompts()
        assert first is session.silence_prompts()
        first.prompted = True
        session.interview._pending = None  # move on without scoring, as a test shortcut
        session.questions.append(type(session.questions[-1])(2, "new", session.questions[-1].puzzle, "", 120, 0))
        assert session.silence_prompts() is not first and not session.silence_prompts().prompted
    asyncio.run(ask_two())
