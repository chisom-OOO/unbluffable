"""Conceptual follow-ups (template `follow_up`: {"question", "reference"}).

Asked aloud after a correct answer and its part 2, at most once per template in a
session. One Spark call judges the reply: does it make the reference's key point
(yes / partly / no), with a verbatim quote from the candidate. The judgement is
model-matched, not an exact check: it is shown in the report and receipts beside the
exact checks and is never scored by the engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from voice.recording import VoiceError

VERDICTS = ("yes", "partly", "no")
MODEL_MATCHED = {
    "yes": "Model-matched: makes the key point",
    "partly": "Model-matched: partly makes the key point",
    "no": "Model-matched: does not make the key point",
    None: "Model-matched: not judged",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "quote": {"type": "string"},
    },
    "required": ["verdict", "quote"],
    "additionalProperties": False,
}

PROMPT = (
    "You compare a candidate's spoken reply to a follow-up question with a reference answer. "
    "Question: {question} Reference answer: {reference} "
    "Decide whether the reply makes the reference's key point: yes if it makes it; partly if it makes "
    "only part of it or makes it alongside an error; no if it does not. Judge the idea only, never the "
    "wording, grammar, accent or delivery. In quote, copy the words from the reply that show your "
    "decision, verbatim; use none only when the verdict is no and nothing in the reply bears on the point."
)


@dataclass
class FollowUpLog:
    question: str  # as shown
    reference: str
    reply: str | None = None
    verdict: str | None = None  # yes / partly / no; None: not judged
    quote: str | None = None
    note: str | None = None  # why it was not judged
    model: dict | None = None
    receipt: dict | None = None

    @property
    def label(self) -> str:
        return MODEL_MATCHED[self.verdict]


async def judge(provider, question: str, reference: str, reply: str, send) -> tuple[str | None, str | None, str | None, dict | None]:
    """(verdict, quote, note, model). A verdict needs a quote found verbatim in the reply,
    except "no", which may have none; otherwise the reply is not judged."""
    prompt = PROMPT.format(question=question, reference=reference)
    try:
        parsed, model = await provider.structured(reply, "extraction", "low", SCHEMA, prompt)
    except VoiceError as error:
        await send({"type": "model_error", "job": "follow_up", "message": str(error)})
        return None, None, "The model call failed, so this reply was not judged.", None
    verdict, quote = parsed["verdict"], parsed["quote"].strip()
    if quote.lower() == "none":
        quote = ""
    if quote and quote not in reply:
        return None, None, "The model's quote is not in your words, so this reply was not judged.", model
    if not quote and verdict != "no":
        return None, None, "The model gave no quote from your words, so this reply was not judged.", model
    await send({"type": "follow_up_result", "verdict": verdict, "quote": quote or None, "model": model})
    return verdict, quote or None, None, model
