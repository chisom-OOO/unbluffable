"""Content cues and the small, recorded Spark end-of-answer decision."""

from dataclasses import dataclass
import re

from voice.recording import VoiceError


PROMPT = "Want to talk me through where you are?"


@dataclass(frozen=True)
class Endpoint:
    finished: bool
    kind: str
    cue: str
    latency_s: float = 0
    model: dict | None = None


def cues(text):
    """Use only general conversational cues, never puzzle values or correctness."""
    tail = text.lower().replace("’", "'").strip().rstrip(".!?,… ")
    if not tail:
        return Endpoint(False, "thinking", "empty")
    # A continuation after a closer must win over that earlier closer.
    if re.search(r"\b(?:um|uh|erm|er|hmm|so|and|but|because|therefore|then|the|a|an|of|to|is|are|equals|over|divided by|multiplied by)\s*$", tail):
        return Endpoint(False, "thinking", "trailing_filler_or_clause")
    if re.search(r"\b(?:let me think|still thinking|give me a (?:moment|second)|i(?:'m| am) (?:thinking|not (?:done|finished)))$", tail):
        return Endpoint(False, "thinking", "thinking_request")
    if re.search(r"\b(?:that(?:'s| is) my (?:answer|final answer)|(?:my )?final answer|i think that(?:'s| is) it|that(?:'s| is) all|i(?:'m| am) (?:done|finished))$", tail):
        return Endpoint(True, "answer", "explicit_closer")
    if re.search(r"\b(?:(?:can|could|may) i (?:get|have|ask for) (?:a |some )?(?:hint|help)|(?:can|could|would) you (?:help(?: me)?|give me (?:a hint|some help))|i need (?:a hint|(?:some )?help))$", tail):
        return Endpoint(True, "help", "help_request")
    if re.search(r"\b(?:can|could|would) you (?:repeat|clarify|explain) (?:that|the question|the assumptions)$", tail):
        return Endpoint(True, "question", "clarify_request")
    # General questions, numerical commitments and complete-looking sentences can
    # still be thinking aloud. Leave those ambiguous cases to Spark.
    return None


async def classify(provider, text):
    result = cues(text)
    if result is not None:
        return result
    parsed, model = await provider.endpoint(text)
    # Even an inconsistent model reply must never end a thinking turn.
    return Endpoint(parsed["finished"] and parsed["kind"] != "thinking", parsed["kind"],
                    "spark_" + parsed["kind"], model.get("latency_s") or 0, model)


async def safe_classify(provider, text):
    try:
        return await classify(provider, text)
    except VoiceError:
        return Endpoint(False, "thinking", "model_unavailable")
