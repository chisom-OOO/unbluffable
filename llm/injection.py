"""Prompt-injection text in answers is quoted and ignored (spec/01).

These patterns only decide two things: an answer made of nothing but
instructions is a system abstain (spec/02 §2), and an instruction quote never
counts as reasoning support. They never change a number check.
"""

from __future__ import annotations

import re

_PATTERNS = re.compile(
    r"\b(?:ignore|disregard|forget)\b[^.!?]{0,40}\b(?:instructions?|prompt|rules?|rubric|above)\b"
    r"|\bdisregard\b"
    r"|^\s*(?:system|developer|assistant)\s*:"
    r"|\byou\s+are\s+now\b"
    r"|\bdeveloper\s+mode\b"
    r"|\bnew\s+instructions?\b"
    r"|\b(?:mark|grade|score|label)\b[^.!?]{0,30}\b(?:correct|right|valid|full\s+marks)\b"
    r"|\bgive\s+(?:me|this|it)\s+full\s+marks\b"
    r"|\b(?:reasoning_code|misconception_name|committed_answer_text)\b"
    r"|\bthe\s+candidate\s+is\s+correct\b",
    re.IGNORECASE,
)
_SENTENCES = re.compile(r"[^.!?]+[.!?]*")


def is_injection(text: str) -> bool:
    return bool(_PATTERNS.search(text))


def is_injection_only(text: str) -> bool:
    """True if every sentence is an instruction aimed at the scorer."""
    sentences = [s.strip() for s in _SENTENCES.findall(text) if re.search(r"\w", s)]
    return bool(sentences) and all(is_injection(s) for s in sentences)
