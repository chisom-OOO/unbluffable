"""Merge provider speech turns into a single candidate answer."""

from dataclasses import dataclass
import math


@dataclass
class Turn:
    text: str = ""
    complete: bool = False
    ended: bool = False


class AnswerMerger:
    def __init__(self, silence_s=1.8):
        if not math.isfinite(silence_s) or silence_s <= 0:
            raise ValueError("Silence threshold must be finite and positive.")
        self.silence_s = silence_s
        self.turns = {}
        self.active = None
        self.last_end = None
        self.emitted = False

    @property
    def transcript(self):
        return " ".join(turn.text.strip() for turn in self.turns.values() if turn.text.strip())

    def feed(self, event, now):
        if self.emitted:
            return
        kind = event.get("type")
        if kind == "speechStart":
            self.active = event["turnId"]
            self.turns.setdefault(self.active, Turn())
            self.last_end = None
        elif kind == "transcript" and not event.get("final", False):
            if self.active is not None:
                turn = self.turns[self.active]
                if not turn.complete:
                    turn.text = event.get("transcript", "")  # Replace cumulative partials.
        elif kind in {"speechEnd", "speechComplete"}:
            turn_id = event["turnId"]
            turn = self.turns.setdefault(turn_id, Turn())
            if kind == "speechComplete":
                turn.text = event.get("transcript", "")
                turn.complete = True
            turn.ended = True
            if self.active == turn_id:
                self.active = None
                self.last_end = now
            elif self.active is None and self.last_end is None:
                self.last_end = now

    def remaining(self, now):
        if (self.emitted or self.active is not None or self.last_end is None
                or not self.transcript or not all(turn.complete for turn in self.turns.values())):
            return None
        return max(0.0, self.last_end + self.silence_s - now)

    def finish(self, reason):
        if self.emitted:
            return None
        if not all(turn.complete for turn in self.turns.values()):
            raise ValueError("A speech turn has not been finalized.")
        self.emitted = True
        return {"type": "answer_complete", "transcript": self.transcript, "reason": reason}
