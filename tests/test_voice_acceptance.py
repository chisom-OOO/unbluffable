import asyncio

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


def test_gate_reports_a_bad_model_cue_without_tuning_it_away():
    class BadModel:
        async def endpoint(self, text):
            return {"finished": True, "kind": "answer"}, {"latency_s": .1}
    result = asyncio.run(replay_clip(events("A tentative count."), BadModel()))
    assert not result["passed"] and result["early"] and result["cue"] == "spark_answer"


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
