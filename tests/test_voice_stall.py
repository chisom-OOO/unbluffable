"""Invented answers and fake clocks; no API or recorded audio access."""

import asyncio

import pytest

from voice.answers import silence_commitment_check
from voice.endpointing import PROMPT
from voice.recording import VoiceError
from voice.relay import wait_for_endpoint
from voice.turns import AnswerMerger


class Browser:
    def __init__(self):
        self.events = []
        self.prompted = asyncio.Event()

    async def send_json(self, event):
        self.events.append(event)
        if event["type"] == "listening_prompt":
            self.prompted.set()


class Thinking:
    async def endpoint(self, text):
        return {"finished": False, "kind": "thinking"}, {}


@pytest.mark.parametrize("text,span,commit,complete", [
    ("Eleven out of forty-four, so about 25%.", "25%", True, True),
    ("The detector catches 90% of fraud.", "90%", True, False),
    ("I am still considering 25%.", "25%", False, False),
    ("I have not settled on a value.", "none", False, False),
])
def test_silence_check_runs_only_at_eight_seconds_and_guards_givens(text, span, commit, complete):
    async def exercise():
        calls, clock = [], [.2]
        merger, browser, changed = AnswerMerger(), Browser(), asyncio.Event()
        merger.feed({"type": "speechStart", "turnId": 1}, 0)
        merger.feed({"type": "speechComplete", "turnId": 1, "transcript": text}, .2)

        class Model(Thinking):
            async def extract(self, transcript, full=False):
                calls.append((transcript, full))
                return {"committed_number_text": span, "is_commitment": commit}, {}

        model = Model()

        async def check(transcript):
            return await silence_commitment_check(model, transcript)

        task = asyncio.create_task(wait_for_endpoint(merger, model, browser, changed,
            lambda: clock[0], silence_check=check))
        try:
            await asyncio.sleep(.01)
            clock[0] = 8.19
            changed.set()
            await asyncio.sleep(.01)
            assert not calls and not browser.prompted.is_set() and not task.done()
            clock[0] = 8.2
            changed.set()
            if complete:
                assert await asyncio.wait_for(task, 1) == "silence_commitment"
                assert merger.accepted_revision == merger.revision
                assert merger.finish("silence_commitment") is not None
                assert merger.finish("silence_commitment") is None
                assert not browser.prompted.is_set()
            else:
                await asyncio.wait_for(browser.prompted.wait(), 1)
                assert not task.done() and not merger.emitted
                assert browser.events[-1] == {"type": "listening_prompt", "message": PROMPT}
                clock[0] = 20
                changed.set()
                await asyncio.sleep(.01)
            assert calls == [(text, False)]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_new_speech_cancels_stale_silence_extraction_and_does_not_prompt():
    async def exercise():
        clock, started, cancelled = [.2], asyncio.Event(), asyncio.Event()
        merger, browser, changed = AnswerMerger(), Browser(), asyncio.Event()
        merger.feed({"type": "speechStart", "turnId": 1}, 0)
        merger.feed({"type": "speechComplete", "turnId": 1, "transcript": "I have a provisional count."}, .2)

        async def check(text):
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(wait_for_endpoint(merger, Thinking(), browser, changed,
            lambda: clock[0], silence_check=check))
        try:
            await asyncio.sleep(.01)
            clock[0] = 8.2
            changed.set()
            await asyncio.wait_for(started.wait(), 1)
            merger.feed({"type": "speechStart", "turnId": 2}, 8.3)
            merger.feed({"type": "transcript", "transcript": "and"}, 8.4)
            clock[0] = 8.4
            changed.set()
            await asyncio.wait_for(cancelled.wait(), 1)
            assert not task.done() and not browser.prompted.is_set()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_failed_silence_extraction_preserves_the_prompt():
    async def exercise():
        merger, browser = AnswerMerger(), Browser()
        merger.feed({"type": "speechStart", "turnId": 1}, 0)
        merger.feed({"type": "speechComplete", "turnId": 1, "transcript": "An intermediate count."}, .2)

        async def check(text):
            raise VoiceError("Synthetic failure")

        task = asyncio.create_task(wait_for_endpoint(merger, Thinking(), browser, asyncio.Event(),
            lambda: 8.2, silence_check=check))
        try:
            await asyncio.wait_for(browser.prompted.wait(), 1)
            assert not task.done()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_silence_check_does_not_wait_for_a_slow_endpoint_classifier():
    async def exercise():
        clock, endpoint_started = [.2], asyncio.Event()
        merger, browser, changed = AnswerMerger(), Browser(), asyncio.Event()
        merger.feed({"type": "speechStart", "turnId": 1}, 0)
        merger.feed({"type": "speechComplete", "turnId": 1, "transcript": "So I get 25%."}, .2)

        class SlowEndpoint:
            async def endpoint(self, text):
                endpoint_started.set()
                await asyncio.Future()

        async def check(text):
            return True

        task = asyncio.create_task(wait_for_endpoint(merger, SlowEndpoint(), browser, changed,
            lambda: clock[0], silence_check=check))
        try:
            await asyncio.wait_for(endpoint_started.wait(), 1)
            clock[0] = 8.2
            changed.set()
            assert await asyncio.wait_for(task, 1) == "silence_commitment"
            assert not browser.prompted.is_set()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def interviewer_speaking(merger, value, now, headphones=False):
    """What voice.relay does when the browser says the interviewer started or stopped speaking."""
    merger.paused = bool(value) and not headphones
    merger.last_activity = now
    merger.revision += 1


@pytest.mark.parametrize("silence_check", [False, True])
def test_the_silence_prompt_is_never_spoken_twice_without_new_speech(silence_check):
    """Live mic test: the prompt was spoken, the interviewer's own speech bumped the revision,
    and 8 s later the same prompt came again although the candidate had said nothing."""
    async def exercise():
        clock = [0.0]
        merger, browser, changed = AnswerMerger(), Browser(), asyncio.Event()
        prompts = lambda: sum(e["type"] == "listening_prompt" for e in browser.events)  # noqa: E731

        async def check(text):
            return False  # nothing committed: the prompt is due

        task = asyncio.create_task(wait_for_endpoint(merger, Thinking(), browser, changed, lambda: clock[0],
                                                     silence_check=check if silence_check else None))
        try:
            await asyncio.sleep(.01)
            clock[0] = 8.0
            changed.set()
            await asyncio.wait_for(browser.prompted.wait(), 1)
            assert prompts() == 1
            # The interviewer speaks the prompt (the mic pauses without headphones), then stops.
            interviewer_speaking(merger, True, 8.1)
            changed.set()
            await asyncio.sleep(.01)
            interviewer_speaking(merger, False, 10.0)
            changed.set()
            await asyncio.sleep(.01)
            for t in (18.0, 30.0, 60.0):
                clock[0] = t
                changed.set()
                await asyncio.sleep(.02)
            assert prompts() == 1, "a second prompt with no speech in between"
            # New speech from the candidate, then silence again: one more prompt is allowed.
            merger.feed({"type": "speechStart", "turnId": 1}, 61.0)
            merger.feed({"type": "speechComplete", "turnId": 1, "transcript": "I have the first count."}, 61.5)
            clock[0] = 70.0
            changed.set()
            for _ in range(50):
                await asyncio.sleep(.01)
                if prompts() == 2:
                    break
            assert prompts() == 2
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())
