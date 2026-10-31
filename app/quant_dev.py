"""Quantitative development (the quant_dev track): one spoken opener from the core quant
topics (probability or expectations, Easy or Medium), then the coding interview (the same
live editor and Part 1 -> Part 2 -> bonus progression, in Python) on the quant_dev coding
families. Until those families have coding specs, the track shows "Being added".

The opener is an ordinary exam question, scored exactly; its rating item and the coding
round's count toward the quant_dev areas. No Bayesian label: a single question can't earn one.
"""

from __future__ import annotations

import random

from app import coding, interview_report
from app.areas import AREAS, area_for
from app.interview_session import ExamSession, SessionClosed
from app.placement import PlacementInterview
from engine.bank import BankSource

TRACK = "quant_dev"
TOPICS_LABEL = "Quant development: spoken opener + coding round"
OPENER_AREAS = ("Probability", "Expectations")  # quant areas the opener draws from
OPENER_LEVELS = ("Easy", "Medium")


class OpenerInterview(PlacementInterview):
    """One new question, no twin."""

    def record(self, observation, *args, **kwargs) -> None:
        super().record(observation, *args, **kwargs)
        self.finished = True


def opener_topics(bank) -> tuple[str, ...]:
    return tuple(t for t, _ in bank.topics("quant") if area_for("quant", t) in OPENER_AREAS)


def available(bank) -> bool:
    return bool(coding.specs(TRACK)) and bool(opener_topics(bank))


class QuantDevSession:
    """The opener (an ExamSession that does not end the interview), then the coding session."""

    def __init__(self, send, listen, next_event, provider, analyzer, bank, coding_session: coding.CodingSession,
                 deadline=None, rng: random.Random | None = None):
        rng = rng or random.Random()
        self.send = send
        source = BankSource(bank, opener_topics(bank), rng.choice(OPENER_LEVELS), rng=rng, pack="quant")

        async def opener_send(event):
            if event.get("type") == "question":
                event = {**event, "opener": True}
            await send(event)

        self.opener = ExamSession(opener_send, listen, analyzer, OpenerInterview(source=source), deadline=deadline)
        self.opener.ends_session = False
        self.opener.track, self.opener.topics = TRACK, TOPICS_LABEL
        self.coding = coding_session
        self.coding.track, self.coding.topics = TRACK, TOPICS_LABEL
        self.track, self.topics, self.placement = TRACK, TOPICS_LABEL, False
        self.active = self.opener

    @property
    def conditions(self) -> str:
        return self.opener.conditions

    @conditions.setter
    def conditions(self, value: str) -> None:
        self.opener.conditions = self.coding.conditions = value

    finished = property(lambda self: self.coding.finished)
    timed_out = property(lambda self: self.opener.timed_out or self.coding.timed_out)

    # The voice relay asks the session in progress.
    async def silence_check(self, text: str) -> bool:
        return await self.active.silence_check(text)

    def keywords(self) -> list[str]:
        return self.opener.keywords() if self.active is self.opener else []

    async def run(self) -> None:
        try:
            await self.opener.run()
            if self.opener.timed_out:
                await self.send({"type": "session_end", "label": None, "coding": True, "timed_out": True})
                return
            self.active = self.coding
            await self.coding.run()
        except SessionClosed:
            return


def report(session: QuantDevSession, templates: dict) -> dict:
    """The coding report, with the opener's card and rating item first."""
    out = coding.report(session.coding)
    opener = interview_report.build(session.opener, templates)
    out.update(topics=TOPICS_LABEL, track=TRACK, quant_dev=True,
               opener={"cards": opener["cards"], "outcomes": opener.get("outcomes", []), "conditions": opener["conditions"]},
               rating_items=opener["rating_items"] + out["rating_items"])
    return out


assert TRACK in AREAS
