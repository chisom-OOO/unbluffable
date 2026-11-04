"""One time limit per turn, the same for every format (decision log 48).

The clock starts when an answer arrives (Done, the end-of-answer check, a typed answer or a
code message) and stops when the room listens again or the interview ends. At SLOW_SECONDS
the status says STILL_CHECKING; at GIVE_UP_SECONDS the room gives up on the turn's model
calls: in-flight calls are cancelled and later ones in the turn fail at once, as a
TurnTimedOut (a VoiceError, so each format's existing model-error path applies and nothing is
coded Correct). Sessions that check an answer with a model read `gave_up(provider)` and listen
again on the same question; the timed-out attempt is not an answer.
"""

from __future__ import annotations

import asyncio
import time

from voice.recording import VoiceError

SLOW_SECONDS = 10
GIVE_UP_SECONDS = 30
STILL_CHECKING = "Still checking your answer…"
GAVE_UP = "That took too long on my side. Say your answer again, or press Done to move on."


class TurnTimedOut(VoiceError):
    """A model call in a turn that passed the limit."""

    def __init__(self):
        super().__init__("The model request failed: it took too long, so this answer was not checked.")


class TurnClock:
    """`send(event)`: the socket's send. One clock per interview."""

    def __init__(self, send, clock=time.monotonic):
        self.send, self.clock = send, clock
        self.started: float | None = None
        self.gave_up = False
        self.text: str | None = None  # the last answer's words
        self.retry_text: str | None = None  # the words of an answer that timed out, for Done with nothing new
        self._watch: asyncio.Task | None = None
        self._calls: set[asyncio.Task] = set()

    def start(self, text: str | None = None) -> None:
        self.stop()
        self.started, self.gave_up, self.text = self.clock(), False, text
        self._watch = asyncio.create_task(self._watchdog())

    def stop(self) -> None:
        if self._watch is not None and self._watch is not asyncio.current_task():
            self._watch.cancel()
        self._watch, self.started = None, None

    @property
    def running(self) -> bool:
        return self.started is not None

    async def _watchdog(self) -> None:
        await asyncio.sleep(SLOW_SECONDS)
        await self.send({"type": "turn_slow", "message": STILL_CHECKING})
        await asyncio.sleep(max(0, GIVE_UP_SECONDS - SLOW_SECONDS))
        await self.give_up()

    async def give_up(self) -> None:
        if self.gave_up or not self.running:
            return
        self.gave_up = True
        self.retry_text = self.text
        for call in list(self._calls):
            call.cancel()
        await self.send({"type": "turn_timed_out", "message": GAVE_UP})

    async def call(self, make):
        """Run one model call under the turn's limit."""
        if not self.running:
            return await make()
        if self.gave_up:
            raise TurnTimedOut()
        task = asyncio.ensure_future(make())
        self._calls.add(task)
        try:
            return await task
        except asyncio.CancelledError:
            if task.cancelled() and self.gave_up and not _cancelling():
                raise TurnTimedOut() from None
            raise
        finally:
            self._calls.discard(task)


def _cancelling() -> bool:
    """True when the caller itself is being cancelled (not just the model call)."""
    current = asyncio.current_task()
    return bool(current is not None and current.cancelling())


class TimedProvider:
    """The voice provider with every structured call under the turn clock; everything else passes through."""

    def __init__(self, provider, turn: TurnClock):
        object.__setattr__(self, "_provider", provider)
        object.__setattr__(self, "turn", turn)

    async def structured(self, *args, **kwargs):
        return await self.turn.call(lambda: self._provider.structured(*args, **kwargs))

    @property
    def gave_up(self) -> bool:
        return self.turn.gave_up

    def __getattr__(self, name):
        return getattr(self._provider, name)

    def __setattr__(self, name, value):
        setattr(self._provider, name, value)


def gave_up(provider) -> bool:
    """True when the current turn passed the limit (False for a provider without a clock)."""
    return isinstance(provider, TimedProvider) and provider.turn.gave_up


async def until_checked(provider, answer, check):
    """An answer and its model check, asked again while the check passes the time limit:
    `answer()` -> the words, `check(words)` -> the result. A timed-out attempt is dropped."""
    return await recheck(provider, await answer(), answer, check)


async def recheck(provider, text, again, check):
    """`check(text)`; while it passes the time limit, `again()` asks for the answer once more."""
    result = await check(text)
    while gave_up(provider):
        text = await again()
        result = await check(text)
    return text, result
