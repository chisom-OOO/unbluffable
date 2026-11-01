"""Merge provider speech turns into a single candidate answer."""

from dataclasses import dataclass
import math


@dataclass
class Turn:
    text: str = ""
    complete: bool = False
    ended: bool = False


class AnswerMerger:
    def __init__(self, silence_s=0.8, prompt_s=8):
        if not math.isfinite(silence_s) or silence_s <= 0:
            raise ValueError("Silence threshold must be finite and positive.")
        self.silence_s = silence_s
        self.turns = {}
        self.active = None
        self.last_end = None
        self.emitted = False
        self.last_activity = 0
        self.revision = 0
        self.checked_revision = -1
        self.prompted_revision = -1
        # Candidate speech only (the interviewer's speaking controls also bump `revision`):
        # the silence prompt needs new speech between two prompts.
        self.speech_revision = 0
        self.prompted_speech = -1
        self.prompt_s = prompt_s
        self.paused = False
        self.accepted_revision = None

    @property
    def transcript(self):
        return " ".join(turn.text.strip() for turn in self.turns.values() if turn.text.strip())

    def feed(self, event, now):
        if self.emitted:
            return
        before = self.revision
        self._feed(event, now)
        if self.revision != before:
            self.speech_revision += 1

    def _feed(self, event, now):
        kind = event.get("type")
        if kind == "speechStart":
            self.active = event["turnId"]
            self.turns.setdefault(self.active, Turn())
            self.last_end = None
            self.last_activity = now
            self.revision += 1
        elif kind == "transcript" and not event.get("final", False):
            if self.active is not None:
                turn = self.turns[self.active]
                if not turn.complete:
                    turn.text = event.get("transcript", "")  # Replace cumulative partials.
                    self.last_activity = now
                    self.revision += 1
        elif kind in {"speechEnd", "speechComplete"}:
            turn_id = event["turnId"]
            turn = self.turns.setdefault(turn_id, Turn())
            if kind == "speechComplete":
                if turn.text != event.get("transcript", ""):
                    self.revision += 1
                turn.text = event.get("transcript", "")
                turn.complete = True
            turn.ended = True
            if self.active == turn_id:
                self.active = None
                self.last_end = now
                self.last_activity = now
                self.revision += 1
            elif self.active is None and self.last_end is None:
                self.last_end = now

    def remaining(self, now):
        """Time until a content check, never an instruction to complete an answer."""
        if self.emitted or not self.transcript or self.checked_revision == self.revision:
            return None
        # Provider turn boundaries are cues to check, even if shorter than 0.8 s.
        due = self.last_activity if self.active is None and self.last_end is not None else self.last_activity + self.silence_s
        return max(0.0, due - now)

    def prompt_remaining(self, now):
        if self.emitted or self.prompted_revision == self.revision or self.prompted_speech == self.speech_revision:
            return None
        return max(0.0, self.last_activity + self.prompt_s - now)

    def mark_prompted(self):
        """The silence prompt (or its commitment check) fired at this point of the answer."""
        self.prompted_revision = self.revision
        self.prompted_speech = self.speech_revision

    def finish(self, reason):
        if self.emitted:
            return None
        if not all(turn.complete for turn in self.turns.values()):
            raise ValueError("A speech turn has not been finalized.")
        self.emitted = True
        return {"type": "answer_complete", "transcript": self.transcript, "reason": reason}
