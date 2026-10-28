"""Independent challenge and scoring lanes for a completed flagship answer."""

import asyncio
from fractions import Fraction
import re

from engine.answers import matches
from engine.coding import code_answer
from engine.templates import T1
from voice.numbers import number_from_text
from voice.recording import VoiceError


ACKNOWLEDGEMENT = "Okay, let me check your working"
QUESTION = ("One percent of transactions are fraudulent. The detector flags ninety percent of fraud "
            "and five percent of genuine transactions. A transaction is flagged. What is the probability it is fraud?")
FLAGSHIP = T1.build({"p": Fraction(1, 100), "s": Fraction(9, 10), "f": Fraction(1, 20)}, population=2000)


def restated_given(text, span):
    occurrences = list(re.finditer(re.escape(span), text)) if span else []
    if not occurrences:
        return True
    for occurrence in occurrences:
        before = re.split(r"[.!?]\s+", text[:occurrence.start()].lower())[-1]
        after = text[occurrence.end():].lower()
        given = (re.search(r"(?:detector\s+(?:catches|flags|detects)|detection\s+rate|false[- ]alarm\s+rate|specificity|base\s+rate)\s*(?:is\s*)?$", before)
                 or re.match(r"\s*(?:of\s+(?:the\s+)?(?:fraud|genuine)|detection\s+rate|false[- ]alarm\s+rate|specificity|base\s+rate|flagged)\b", after))
        if not given:
            return False
    return True


async def silence_commitment_check(provider, text):
    """Caller-owned fast check at the existing silence-prompt boundary."""
    extracted, _ = await provider.extract(text)
    return extracted["is_commitment"] and not restated_given(text, extracted["committed_number_text"])


def decision(text, extracted):
    span = extracted["committed_number_text"]
    stated = number_from_text(span) if extracted["is_commitment"] and not restated_given(text, span) else None
    wrong = stated is not None and not matches(stated, FLAGSHIP.answer)
    message = None
    if wrong:
        if matches(stated, Fraction(9, 10)):
            message = ("Careful. Ninety percent is the chance a fraudulent transaction gets flagged, "
                       "not the chance a flagged transaction is fraud. Out of two thousand transactions, "
                       "how many genuine ones get flagged too?")
        else:
            message = ("Let's check that against the counts. Out of two thousand transactions, "
                       "how many flagged transactions are fraudulent, and how many are genuine?")
    return {"type": "challenge_result", "should_challenge": wrong, "message": message,
            "number_found": stated is not None, "stated_number": str(stated.value) if stated else None}


async def analyse_answer(provider, text, send):
    """Send acknowledgement before scheduling either model; lanes never block each other."""
    await send({"type": "answer_complete", "transcript": text, "acknowledgement": ACKNOWLEDGEMENT})

    async def fast():
        try:
            extracted, model = await provider.extract(text)
            await send({**decision(text, extracted), "model": model})
        except VoiceError as error:
            await send({"type": "model_error", "job": "minimal", "message": str(error)})

    async def full():
        try:
            extracted, model = await provider.extract(text, full=True)
            span = extracted["committed_answer_text"]
            stated = number_from_text(span) if span != "none" and not restated_given(text, span) else None
            observation = code_answer(FLAGSHIP, stated, extracted["reasoning_code"])
            await send({"type": "scoring_result", "extraction": extracted,
                        "observation": observation.outcome.value, "model": model})
        except VoiceError as error:
            await send({"type": "model_error", "job": "extraction", "message": str(error)})

    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(fast())
        tasks.create_task(full())
    await send({"type": "analysis_complete"})
