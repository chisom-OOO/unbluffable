"""Turn a transcript into an engine Observation (spec/02 §2).

The model extracts; code decides. The committed number is parsed and checked
exactly by engine.answers / engine.coding, so a wrong number can never be
Correct. If the extraction fails or its committed span is not in the transcript,
the no-model fallback runs: it can detect misconceptions but never awards
Correct (decision log 0i, clarification 3).
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.answers import committed_number, parse_number
from engine.coding import Observation, abstain, code_answer
from engine.templates import Puzzle
from llm.extract import ExtractionResult, extract
from llm.injection import is_injection, is_injection_only

# Steps that count as support for "valid" reasoning.
SUPPORT_STEPS = {"base_rate", "likelihood", "false_positive_count", "total_positive", "posterior"}
NOT_A_CLAIM_STEPS = {"restated_given", "hypothetical"}


@dataclass(frozen=True)
class Turn:
    observation: Observation
    source: str  # "model", "fallback" or "system" (abstain before any call)
    extraction: ExtractionResult | None
    reasoning_code: str | None


def assess(puzzle: Puzzle, transcript: str, *, mode=None, backend=None, store=None) -> Turn:
    if not transcript.strip():
        return Turn(abstain("empty_audio"), "system", None, None)
    if is_injection_only(transcript):
        return Turn(abstain("injection_only"), "system", None, None)
    result = extract(puzzle, transcript, mode=mode, backend=backend, store=store)
    return score_turn(puzzle, transcript, result)


def score_turn(puzzle: Puzzle, transcript: str, result: ExtractionResult) -> Turn:
    if not result.ok or not result.committed_verbatim:
        stated = committed_number(transcript)
        return Turn(code_answer(puzzle, stated, "vague"), "fallback", result, "vague")

    stated = None
    if result.committed_text is not None and not _is_restated_or_hypothetical(result):
        stated = parse_number(result.committed_text)

    code = result.extraction["reasoning_code"]
    supported = any(q.step in SUPPORT_STEPS and not is_injection(q.quote) for q in result.quotes)
    if code == "valid" and not supported:
        code = "vague"  # correct number with unsupported reasoning is Vague
    return Turn(code_answer(puzzle, stated, code), "model", result, code)


def _is_restated_or_hypothetical(result: ExtractionResult) -> bool:
    span = result.committed_text
    return any(
        q.step in NOT_A_CLAIM_STEPS and (span in q.quote or q.quote in span)
        for q in result.quotes
    )
