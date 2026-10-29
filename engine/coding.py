"""Observation coding per answer (spec/02 §2).

Inputs are the deterministic number check and the reasoning code from the Muse
Spark extraction (spec/03 schema). A wrong number can never be coded Correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from engine.answers import StatedNumber
from engine.templates import Puzzle


class Outcome(str, Enum):
    CORRECT = "correct"
    RECITED = "recited"  # twin only: the twin answer equals the original answer
    NAMED_WRONG = "named_wrong"
    OTHER_WRONG = "other_wrong"
    VAGUE = "vague"
    ABSTAIN = "abstain"  # system abstain: no update


REASONING_CODES = ("valid", "misconception", "other_wrong", "vague")
ABSTAIN_REASONS = (
    "empty_audio",
    "unintelligible_audio",
    "transcription_failure",
    "injection_only",
    "off_topic",
)


@dataclass(frozen=True)
class Observation:
    outcome: Outcome
    stated: StatedNumber | None = None
    matched: tuple[str, ...] = field(default=())  # named wrong value keys
    misconception: str | None = None
    abstain_reason: str | None = None


def code_answer(
    puzzle: Puzzle,
    stated: StatedNumber | None,
    reasoning_code: str,
) -> Observation:
    """Code one answer. `stated` is the committed number, or None if none was committed."""
    if reasoning_code not in REASONING_CODES:
        raise ValueError(f"unknown reasoning code {reasoning_code!r}")
    if stated is None:
        return Observation(Outcome.VAGUE)
    if puzzle.accepts(stated, puzzle.answer):
        # Correct number with unsupported or vague reasoning is Vague.
        outcome = Outcome.CORRECT if reasoning_code == "valid" else Outcome.VAGUE
        return Observation(outcome, stated)
    if puzzle.recited is not None and puzzle.accepts(stated, puzzle.recited):
        return Observation(Outcome.RECITED, stated)
    hits = [nv for nv in puzzle.named_values if puzzle.accepts(stated, nv.value)]
    if hits:
        # Near-identical named values (e.g. f and P(+)) are reported together.
        return Observation(
            Outcome.NAMED_WRONG,
            stated,
            matched=tuple(nv.key for nv in hits),
            misconception=hits[0].misconception,
        )
    return Observation(Outcome.OTHER_WRONG, stated)


def abstain(reason: str) -> Observation:
    if reason not in ABSTAIN_REASONS:
        raise ValueError(f"unknown abstain reason {reason!r}")
    return Observation(Outcome.ABSTAIN, abstain_reason=reason)
