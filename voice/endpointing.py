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


# --- Behavioural answers (decision log 27): long stories, no committed number -------------

ANYTHING_TO_ADD = "Anything to add before I ask a follow-up?"
# Wrap-up cues in the last sentence or two: "we ended up winning the competition".
WRAP_UP = re.compile(r"\b(?:we|i|they|it) ended up\b|\bthat(?:'s| is| was) (?:it|all|about it|the story)\b|\bso yeah\b"
                     r"|\band that(?:'s| is| was) how\b|\bin the end\b|\bat the end of the day\b|\bi(?:'m| am) done\b"
                     r"|\bthat(?:'s| is) my answer\b")
# A result or outcome somewhere in the answer.
OUTCOME = re.compile(r"\b(?:result(?:ed|s)?|outcome|ended up|in the end|eventually|we won|i won|won the"
                     r"|led to|which meant|increas\w*|reduc\w*|improv\w*|saved|grew|achiev\w*|deliver(?:ed)?"
                     r"|learn(?:ed|t)|on time|percent)\b|%")
TRAILING = re.compile(r"\b(?:um|uh|erm|er|hmm|so|and|but|because|then|the|a|an|of|to|with|which|that)$")


@dataclass(frozen=True)
class TurnDecision:
    action: str | None  # "finish", "ask" or None (keep listening)
    cue: str = ""
    wait: float | None = None  # seconds of further silence until a rule could next fire


class BehaviouralTurn:
    """When a spoken behavioural answer is finished. Never the committed-number silence
    prompt: finish on a wrap-up cue after a short pause, on an outcome and a ~3 s pause, or
    after ~5 s of silence once 40+ words are in; otherwise ask once whether there is
    anything to add, then finish on the next pause after a reply (or a long silence)."""

    def __init__(self, cue_pause=1.5, outcome_pause=3.0, long_pause=5.0, ask_pause=8.0, min_words=40):
        self.cue_pause, self.outcome_pause, self.long_pause = cue_pause, outcome_pause, long_pause
        self.ask_pause, self.min_words = ask_pause, min_words
        self.asked_at = None  # the transcript when "anything to add?" was asked

    def rules(self, clean: str) -> list[tuple[float, str]]:
        if self.asked_at is not None:
            # Asked once already: a reply then a short pause, or a long silence, ends it.
            return [(self.cue_pause, "after_ask")] if clean != self.asked_at else [(self.ask_pause * 2, "silence_after_ask")]
        if TRAILING.search(clean.rstrip(".!?,… ")):
            return [(self.ask_pause, "ask")]  # mid-clause ("...and"): no early finish
        last = " ".join(re.split(r"(?<=[.!?])\s+", clean)[-2:])
        out = []
        if WRAP_UP.search(last):
            out.append((self.cue_pause, "wrap_up_cue"))
        if OUTCOME.search(clean):
            out.append((self.outcome_pause, "outcome_pause"))
        if len(re.findall(r"\w+", clean)) >= self.min_words:
            out.append((self.long_pause, "long_silence"))
        return sorted(out + [(self.ask_pause, "ask")])

    def decide(self, text: str, silent: float) -> TurnDecision:
        clean = text.lower().replace("’", "'").strip()
        if not clean.rstrip(".!?,… "):
            return TurnDecision(None)
        rules = self.rules(clean)
        for pause, cue in rules:
            if silent >= pause:
                if cue == "ask":
                    self.asked_at = clean
                    return TurnDecision("ask", "anything_to_add")
                return TurnDecision("finish", cue)
        return TurnDecision(None, wait=min(pause - silent for pause, _ in rules))
