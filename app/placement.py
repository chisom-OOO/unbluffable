"""Placement interview (decision log 23): five new questions from five different strength
areas of a track, starting at Medium. The normal ladder, challenges and help discount apply;
there are no twins, and the session ends after five questions, not when the label settles."""

from __future__ import annotations

from app.areas import area_for
from engine.bank import Bank, BankSource
from engine.interview import Interview

QUESTIONS = 5
START = "Medium"


class PlacementSource(BankSource):
    """BankSource limited to one template per strength area."""

    def __init__(self, bank: Bank, track: str, rng=None):
        super().__init__(bank, "Mixed", START, rng=rng, pack=track)
        self.track = track
        self.unused = {tid for tid in self.unused if area_for(track, self.templates[tid].topic)}
        self.areas_used: list[str] = []

    def candidates(self) -> list[str]:
        used = set(self.areas_used)
        self.unused = {tid for tid in self.unused if area_for(self.track, self.templates[tid].topic) not in used}
        return super().candidates()

    def new(self, template_id: str):
        self.areas_used.append(area_for(self.track, self.templates[template_id].topic))
        return super().new(template_id)


class PlacementInterview(Interview):
    """Asks new questions only, until five are scored or no area is left."""

    def record(self, observation, *args, **kwargs) -> None:
        super().record(observation, *args, **kwargs)
        self._twin_after = None  # no twin: the next question is always a new area
        self.finished = self.answers >= QUESTIONS or not self.source.candidates()
