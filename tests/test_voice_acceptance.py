import asyncio

import pytest

from voice.acceptance import replay_clip
from voice.recording import VoiceError


def events(middle="Let me think."):
    return [{"stream_elapsed_s": at, "event": event} for at, event in [
        (0, {"type": "speechStart", "turnId": 1}),
        (.2, {"type": "speechComplete", "turnId": 1, "transcript": middle}),
        (2.68, {"type": "speechStart", "turnId": 2}),
        (3, {"type": "transcript", "transcript": "That's my answer."}),
        (3.1, {"type": "speechEnd", "turnId": 2}),
        (3.2, {"type": "speechComplete", "turnId": 2, "transcript": "That's my answer."}),
    ]]


def test_gate_simulation_keeps_long_thinking_pause_and_completes_once():
    result = asyncio.run(replay_clip(events(), None))
    assert result["passed"] and result["completions"] == 1 and not result["early"]
    assert result["cue"] == "explicit_closer"


@pytest.mark.parametrize("text", [
    "That's my final answer.", "Can I get a hint?", "Could you clarify the assumptions?",
])
def test_semantic_boundary_is_valid_even_when_candidate_continues(text):
    result = asyncio.run(replay_clip(events(text), None))
    assert result["passed"] and result["completions"] == 1 and not result["early"]
    assert result["at_s"] == .2


def test_committed_answer_can_finish_before_later_speech():
    class Model:
        async def endpoint(self, text):
            return {"finished": True, "kind": "answer"}, {"latency_s": .1}
    result = asyncio.run(replay_clip(events("My answer is seven percent."), Model()))
    assert result["passed"] and not result["early"] and result["at_s"] == .3


def test_mid_thought_completion_is_early_even_without_later_speech(monkeypatch):
    from voice.endpointing import Endpoint

    async def bad_classifier(provider, text):
        return Endpoint(True, "answer", "spark_answer")

    monkeypatch.setattr("voice.acceptance.classify", bad_classifier)
    result = asyncio.run(replay_clip(events("I am still thinking.")[:2], None))
    assert not result["passed"] and result["early"] and result["cue"] == "spark_answer"


def test_partial_closer_does_not_need_the_later_full_transcript():
    rows = [{"stream_elapsed_s": at, "event": event} for at, event in [
        (0, {"type": "speechStart", "turnId": 1}),
        (.1, {"type": "transcript", "transcript": "That's my final answer."}),
        (2, {"type": "transcript", "transcript": "That's my final answer. I might explain more."}),
        (3, {"type": "speechEnd", "turnId": 1}),
        (3.1, {"type": "speechComplete", "turnId": 1,
               "transcript": "That's my final answer. I might explain more."}),
    ]]
    result = asyncio.run(replay_clip(rows, None))
    assert result["passed"] and not result["early"] and result["at_s"] == .9


def test_gate_replays_model_latency_and_invalidates_stale_completion():
    class SlowModel:
        async def endpoint(self, text):
            return {"finished": True, "kind": "answer"}, {"latency_s": 3}
    result = asyncio.run(replay_clip(events("A tentative count."), SlowModel()))
    assert result["passed"] and result["cue"] == "explicit_closer"


def test_missing_replay_cannot_count_as_acceptance():
    class NoRecord:
        async def endpoint(self, text):
            raise VoiceError("No record")
    result = asyncio.run(replay_clip(events("A tentative count."), NoRecord()))
    assert not result["passed"] and result["model_unavailable"]


def test_silence_is_never_automatic_completion():
    result = asyncio.run(replay_clip(events()[:2], None))
    assert not result["passed"] and result["completions"] == 0
    assert result["cue"] == "thinking_request"
