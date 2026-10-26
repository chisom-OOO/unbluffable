"""Verdict labels and stopping (spec/02 §5). These four labels are the only
verdict vocabulary (spec/01)."""

from __future__ import annotations

from enum import Enum
from fractions import Fraction

from engine.posterior import Distribution

MIN_ANSWERS_FOR_LABEL = 2
MAX_QUESTIONS = 4
SUPPORTS_S = Fraction(80, 100)
MISCONCEPTION_M = Fraction(70, 100)
NOT_SHOWN_S = Fraction(10, 100)


class Label(str, Enum):
    SUPPORTS = "Evidence supports understanding"
    MISCONCEPTION = "Misconception detected"
    NOT_SHOWN = "Understanding not shown"
    MORE_EVIDENCE = "More evidence needed"


def label_for(posterior: Distribution, n_answers: int) -> Label:
    """Rules applied in order, only after >= 2 answers."""
    if n_answers < MIN_ANSWERS_FOR_LABEL:
        return Label.MORE_EVIDENCE
    if posterior["S"] >= SUPPORTS_S:
        return Label.SUPPORTS
    if posterior["M"] >= MISCONCEPTION_M:
        return Label.MISCONCEPTION
    if posterior["S"] <= NOT_SHOWN_S:
        return Label.NOT_SHOWN
    return Label.MORE_EVIDENCE


def should_stop(label: Label, n_questions: int) -> bool:
    return label is not Label.MORE_EVIDENCE or n_questions >= MAX_QUESTIONS
