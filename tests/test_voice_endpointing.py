"""Invented conversational examples; private transcripts never enter fixtures."""

import asyncio

import httpx
import pytest

from voice.endpointing import classify, cues
from voice.provider import MetaVoice
from voice.recording import VoiceError


def completion(data, finish="stop"):
    import json
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(data)}}]}


@pytest.mark.parametrize("text,finished,kind,cue", [
    ("That's my answer.", True, "answer", "explicit_closer"),
    ("Final answer", True, "answer", "explicit_closer"),
    ("I think that's it.", True, "answer", "explicit_closer"),
    ("That's my answer, but", False, "thinking", "trailing_filler_or_clause"),
    ("The flagged ones are, um...", False, "thinking", "trailing_filler_or_clause"),
    ("I'll divide by the", False, "thinking", "trailing_filler_or_clause"),
    ("Let me think.", False, "thinking", "thinking_request"),
    ("Can I get a hint?", True, "help", "help_request"),
    ("Could you help me?", True, "help", "help_request"),
    ("Could you clarify the assumptions?", True, "question", "clarify_request"),
])
def test_cues_precede_model(text, finished, kind, cue):
    class NoModel:
        async def endpoint(self, text):
            pytest.fail("Deterministic cue called the model")
    result = asyncio.run(classify(NoModel(), text))
    assert (result.finished, result.kind, result.cue) == (finished, kind, cue)


@pytest.mark.parametrize("text", ["I get seven percent.", "Are the checks independent?", "There are forty flagged cases."])
def test_unclear_uses_model(text):
    class Model:
        async def endpoint(self, transcript):
            assert transcript == text
            return {"finished": True, "kind": "answer"}, {}
    assert cues(text) is None
    assert asyncio.run(classify(Model(), text)).finished


def test_thinking_always_keeps_listening():
    class Model:
        async def endpoint(self, text):
            return {"finished": True, "kind": "thinking"}, {}
    assert not asyncio.run(classify(Model(), "An intermediate calculation.")).finished


def test_endpoint_strict_contract_records_and_replays_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-key")
    requests = []

    def handler(request):
        import json
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json=completion({"finished": False, "kind": "thinking"}))

    async def exercise():
        live = MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(handler))
        result = await live.endpoint("An intermediate calculation.")
        monkeypatch.delenv("MODEL_API_KEY")
        replay = await MetaVoice("replay", tmp_path).endpoint("An intermediate calculation.")
        assert replay[0] == result[0] and replay[1]["mode"] == "replay"
        assert replay[1]["model"] == "muse-spark-1.3"

    asyncio.run(exercise())
    request = requests[0]
    contract = request["response_format"]["json_schema"]
    assert request["reasoning_effort"] == "minimal" and request["max_tokens"] >= 4000
    assert contract["strict"] and contract["schema"]["additionalProperties"] is False
    assert set(contract["schema"]["required"]) == {"finished", "kind"}


@pytest.mark.parametrize("payload,finish", [
    ({"finished": True, "kind": "answer", "extra": "bad"}, "stop"),
    ({"finished": "yes", "kind": "answer"}, "stop"),
    ({"finished": True, "kind": "unsupported"}, "stop"),
    ({"finished": True, "kind": "answer"}, "length"),
])
def test_invalid_endpoint_decisions_are_rejected(tmp_path, monkeypatch, payload, finish):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-key")
    model = MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=completion(payload, finish))))
    with pytest.raises(VoiceError):
        asyncio.run(model.endpoint("An answer."))
