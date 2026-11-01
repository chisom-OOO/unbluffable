import asyncio

from voice.endpointing import PROMPT
from voice.relay import wait_for_endpoint
from voice.turns import AnswerMerger


class Browser:
    def __init__(self):
        self.events = []
        self.prompt = asyncio.Event()

    async def send_json(self, event):
        self.events.append(event)
        if event["type"] == "listening_prompt":
            self.prompt.set()


def test_long_thinking_pause_prompts_once_then_listens_for_a_closer():
    async def exercise():
        class NoModel:
            async def endpoint(self, text):
                raise AssertionError("A deterministic cue should not use Spark")

        merger, browser, changed, clock = AnswerMerger(), Browser(), asyncio.Event(), [.1]
        merger.feed({"type": "speechStart", "turnId": 1}, 0)
        merger.feed({"type": "speechComplete", "turnId": 1, "transcript": "Let me think."}, .1)
        task = asyncio.create_task(wait_for_endpoint(merger, NoModel(), browser, changed, lambda: clock[0]))
        try:
            await asyncio.sleep(.01)
            clock[0] = 3
            changed.set()
            await asyncio.sleep(.01)
            assert not task.done() and not merger.emitted
            clock[0] = 8.2  # decision log 40: no prompt yet at 8 s
            changed.set()
            await asyncio.sleep(.01)
            assert not browser.prompt.is_set()
            clock[0] = 20.2
            changed.set()
            await asyncio.wait_for(browser.prompt.wait(), 1)
            prompts = [event for event in browser.events if event["type"] == "listening_prompt"]
            assert prompts == [{"type": "listening_prompt", "message": PROMPT}]
            assert not task.done()
            clock[0] = 40
            changed.set()
            await asyncio.sleep(.01)
            assert len([event for event in browser.events if event["type"] == "listening_prompt"]) == 1
            merger.feed({"type": "speechStart", "turnId": 2}, 40)
            merger.feed({"type": "speechComplete", "turnId": 2, "transcript": "That's my answer."}, 40.1)
            clock[0] = 40.1
            changed.set()
            assert await asyncio.wait_for(task, 1) == "explicit_closer"
            assert merger.finish("explicit_closer") and merger.finish("done") is None
        finally:
            task.cancel()
    asyncio.run(exercise())


def test_new_speech_invalidates_an_inflight_finished_decision():
    async def exercise():
        started, cancelled = asyncio.Event(), asyncio.Event()

        class Model:
            async def endpoint(self, text):
                started.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        merger, browser, changed, clock = AnswerMerger(), Browser(), asyncio.Event(), [.1]
        merger.feed({"type": "speechStart", "turnId": 1}, 0)
        merger.feed({"type": "speechComplete", "turnId": 1, "transcript": "An intermediate count."}, .1)
        task = asyncio.create_task(wait_for_endpoint(merger, Model(), browser, changed, lambda: clock[0]))
        await asyncio.wait_for(started.wait(), 1)
        merger.feed({"type": "speechStart", "turnId": 2}, .2)
        merger.feed({"type": "transcript", "transcript": "and"}, .3)
        clock[0] = .3
        changed.set()
        await asyncio.wait_for(cancelled.wait(), 1)
        await asyncio.sleep(.01)
        assert not task.done() and not any(event.get("finished") for event in browser.events)
        merger.feed({"type": "speechComplete", "turnId": 2, "transcript": "Final answer."}, .4)
        clock[0] = .4
        changed.set()
        assert await asyncio.wait_for(task, 1) == "explicit_closer"
    asyncio.run(exercise())


def test_partial_idle_checks_content_without_a_provider_boundary():
    async def exercise():
        calls = []

        class Model:
            async def endpoint(self, text):
                calls.append(text)
                return {"finished": False, "kind": "thinking"}, {}

        merger, changed, clock = AnswerMerger(), asyncio.Event(), [0]
        merger.feed({"type": "speechStart", "turnId": 1}, 0)
        merger.feed({"type": "transcript", "transcript": "An intermediate count."}, .1)
        task = asyncio.create_task(wait_for_endpoint(merger, Model(), Browser(), changed, lambda: clock[0]))
        try:
            clock[0] = .89
            changed.set()
            await asyncio.sleep(.01)
            assert not calls
            clock[0] = .91
            changed.set()
            await asyncio.sleep(.01)
            assert len(calls) == 1 and not task.done()
            clock[0] = 3
            changed.set()
            await asyncio.sleep(.01)
            assert len(calls) == 1
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    asyncio.run(exercise())


def test_interviewer_speech_suspends_prompt_and_completion_without_headphones():
    async def exercise():
        merger, browser, changed, clock = AnswerMerger(), Browser(), asyncio.Event(), [30]
        merger.paused = True
        merger.feed({"type": "speechStart", "turnId": 1}, 0)
        merger.feed({"type": "speechComplete", "turnId": 1, "transcript": "Final answer."}, .1)
        task = asyncio.create_task(wait_for_endpoint(merger, None, browser, changed, lambda: clock[0]))
        await asyncio.sleep(.01)
        assert not task.done() and not browser.events
        merger.paused = False
        changed.set()
        assert await asyncio.wait_for(task, 1) == "explicit_closer"
    asyncio.run(exercise())
