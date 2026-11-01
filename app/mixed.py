"""Mixed interviews (decision log 37): special formats combine with regular topics and with each
other in one interview, as real interviews do. The interview runs as ordered segments, each run
by that format's own session (the forge ExamSession, market.MarketSession, behavioural,
conversational, cases), with one short spoken line between segments. A single special format
chosen alone still runs on its own and never comes here.

Scoring stays separate: the forge questions give the Bayesian label; market making keeps its
exact scorecard; behavioural and conversational stay model-judged, not exact, and out of the
rating. The report has one section per segment, each the segment's own report.

Software mixes inside the coding round (its design-concepts segment already follows the code),
so its row here only orders the setup note.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app import exam_text as say
from app.interview_session import SessionClosed


@dataclass(frozen=True)
class Format:
    share: int  # relative share of the interview's time
    count: int | None  # questions or games when mixed (None: as many as its share allows)
    transition: str  # said once before the segment, unless it comes first
    heading: str  # the report section's heading
    note: str | None  # the setup note's words (None: the chosen topic names)


# The defaults table (decision log 37). The builder may change any value here.
FORMATS = {
    "forge": Format(6, None, "Let's switch to some technical questions.", "Technical questions (graded exactly)", None),
    "market": Format(4, 1, "Let's switch to a market-making game.", "Market making (graded exactly)", "a market-making game"),
    "behavioural": Format(3, 1, "Let's switch to a behavioural question.", "Behavioural (model-judged, not exact)",
                          "one behavioural question with its follow-up"),
    "conversational": Format(3, 1, "Let's switch to a conceptual question.", "Conceptual questions (model-judged, not exact)",
                             "one conceptual question"),
    "cases": Format(20, None, "Let's switch to a case.", "Case", "a case"),
    "coding": Format(1, None, "Let's start with the coding problem.", "Coding round (Python)", None),
    "design": Format(1, 1, "Let's switch to a design question.", "Design concepts (model-judged, not exact)",
                     "one design-concepts question"),
}
ORDER = {
    "quant": ("forge", "market"),
    "ib": ("behavioural", "forge", "conversational", "cases"),
    "consulting": ("behavioural", "forge", "conversational", "cases"),
    "software": ("coding", "design"),
}
TRANSITIONS = {name: f.transition for name, f in FORMATS.items()}
# A chip's kind (app/roles.py) or a legacy topic id -> its format.
KIND_FORMAT = {"market": "market", "behavioural": "behavioural", "conversational": "conversational",
               "design": "design", "cases": "cases"}


def order(track: str, formats) -> list[str]:
    """The chosen formats in the track's default order."""
    return [f for f in ORDER.get(track, ()) if f in set(formats)]


def mix_view(track: str) -> list[dict]:
    """For the setup page's topics note: the track's order and each format's words."""
    return [{"format": f, "note": FORMATS[f].note} for f in ORDER.get(track, ())]


def share_deadline(formats: list[str], index: int, now: float, end: float) -> float:
    """When segment `index` should hand over: its weighted share of the time left; the last
    segment gets the rest."""
    if index == len(formats) - 1:
        return end
    rest = [FORMATS[f].share for f in formats[index:]]
    return now + (end - now) * rest[0] / sum(rest)


@dataclass
class Segment:
    format: str
    session: object


class Guard:
    """The segments' listen: remembers that the candidate left, so the next segment never starts
    (each session ends quietly on SessionClosed)."""

    def __init__(self, listen):
        self._listen, self.closed = listen, False

    async def listen(self) -> str:
        try:
            return await self._listen()
        except SessionClosed:
            self.closed = True
            raise


class MixedSession:
    def __init__(self, send, segments: list[Segment], deadline: float | None, track: str, topics: str,
                 guard: Guard | None = None, clock=time.monotonic, session_seconds: int | None = None):
        if not segments:
            raise ValueError("a mixed interview needs at least one segment")
        self.send, self.segments, self.deadline, self.clock, self.guard = send, segments, deadline, clock, guard
        self.track, self.topics, self.placement = track, topics, False
        self.session_seconds = session_seconds
        self.ran: list[Segment] = []
        self.finished = self.timed_out = False
        self.active = segments[0].session
        self._conditions = "exam"
        for s in segments:
            s.session.track = track

    @property
    def conditions(self) -> str:
        return self._conditions

    @conditions.setter
    def conditions(self, value: str) -> None:  # decision log 20: one mode for every segment
        self._conditions = value
        for s in self.segments:
            s.session.conditions = value

    # The voice relay asks the segment in progress.
    async def silence_check(self, text: str) -> bool:
        return await self.active.silence_check(text)

    def turn_policy(self):
        policy = getattr(self.active, "turn_policy", None)
        return policy() if policy else None

    def keywords(self) -> list[str]:
        words = getattr(self.active, "keywords", None)
        return words() if words else []

    async def line(self, kind: str, text: str) -> None:
        await self.send({"type": "interviewer_line", "kind": kind, "text": text, "target_step": None,
                         "counts": {"challenges": 0, "nudges": 0, "hints": 0}, "receipt": None})

    async def run(self) -> None:
        formats = [s.format for s in self.segments]
        last = len(self.segments) - 1
        try:
            for i, segment in enumerate(self.segments):
                now = self.clock()
                if i and self.deadline is not None and now >= self.deadline:
                    self.timed_out = True  # out of time before this segment: stop here
                    break
                if i:
                    await self.line("prompt", FORMATS[segment.format].transition)
                session = segment.session
                session.ends_session = i == last  # only the last segment closes the interview
                if self.deadline is not None:
                    session.deadline = share_deadline(formats, i, now, self.deadline)
                self.active = session
                self.ran.append(segment)
                await session.run()
                if self.guard is not None and self.guard.closed:
                    return
                if i < last:
                    # A segment that reached its share of the time handed over; the interview hasn't run out.
                    session.timed_out = False
            if self.ran[-1] is self.segments[-1]:
                self.timed_out = bool(self.segments[-1].session.timed_out)
                self.finished = True
                return  # the last segment said the closing line and ended the interview
            self.finished = True
            await self.line("close", say.TIME_CLOSE if self.timed_out else say.SESSION_CLOSE)
            await self.send({"type": "session_end", "label": self.label(), "mixed": True, "timed_out": self.timed_out})
        except SessionClosed:
            return

    def label(self) -> str | None:
        """The Bayesian label comes from the forge questions only."""
        forge = next((s.session for s in self.ran if s.format == "forge"), None)
        return forge.interview.label.value if forge is not None else None


def report(session: MixedSession, templates: dict) -> dict:
    """One section per segment, in the order they ran, each that format's own report; the label
    is the forge segment's; the rating items are the segments' own items, nothing new."""
    from app import behavioural, cases, conversational, interview_report, market
    build = {"forge": lambda s: interview_report.build(s, templates), "market": market.report,
             "behavioural": behavioural.report, "conversational": conversational.report, "cases": cases.report}
    parts = []
    for segment in session.ran:
        part = build[segment.format](segment.session)
        part.update(track=session.track)
        parts.append({"format": segment.format, "heading": FORMATS[segment.format].heading, "report": part})
    forge = next((p["report"] for p in parts if p["format"] == "forge"), None)
    first = parts[0]["report"]
    return {"sample": False, "mixed": True, "segments": parts, "track": session.track, "topics": session.topics,
            "placement": False, "conditions": first["conditions"], "label": forge["label"] if forge else None,
            "questions": sum(p["report"].get("questions", 0) for p in parts),
            "rating_items": [i for p in parts for i in p["report"].get("rating_items", [])],
            "timed_out": session.timed_out}
