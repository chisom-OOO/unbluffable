"""Timing telemetry uses invented input and never includes candidate text."""

import asyncio
import json
import logging

import pytest

from voice.timing import EndpointTiming, STAGES, browser_timing
from voice.relay import wait_for_endpoint
from voice.turns import AnswerMerger


def test_endpoint_event_and_log_have_all_stages_without_text_or_keys(caplog):
    async def exercise():
        clock = [10.8]
        timing = EndpointTiming()
        timing.partial(10)
        merger = AnswerMerger()
        merger.feed({"type": "speechStart", "turnId": 1}, 9)
        merger.feed({"type": "transcript", "transcript": "I think the answer is ninety percent."}, 10)

        class Model:
            async def endpoint(self, text):
                clock[0] = 11.1
                return {"finished": True, "kind": "answer"}, {"latency_s": .3}

        class Browser:
            async def send_json(self, event):
                events.append(event)

        events = []
        reason = await wait_for_endpoint(merger, Model(), Browser(), asyncio.Event(),
                                         lambda: clock[0], timing=timing)
        assert reason == "spark_answer"
        event = events[-1]
        assert set(event["timing_ms"]) == set(STAGES)
        assert event["timing_ms"]["last_partial_received"] == 0
        assert event["timing_ms"]["partial_idle_fired"] == pytest.approx(800)
        assert event["timing_ms"]["endpoint_decision_started"] == pytest.approx(800)
        assert event["timing_ms"]["endpoint_decision_finished"] == pytest.approx(1100)
        assert event["cue"] == "spark_answer" and event["kind"] == "answer"
        assert event["timing_ms"]["end_stream_sent"] is None
        timing.mark("end_stream_sent", 11.12)
        timing.final(11.2)
        snapshot = timing.event("final", 11.21)
        feedback = browser_timing({**snapshot, "timing_ms": {**snapshot["timing_ms"],
            "checking_working_shown": 1220, "acknowledgement_speech_started": 1240},
            "transcript": "MUST NOT APPEAR", "authorization": "SECRET"})
        assert feedback["timing_ms"]["final_transcript_received"] == pytest.approx(1200)
        assert feedback["timing_ms"]["acknowledgement_audio_first_byte"] is None
        assert feedback["timing_ms"]["acknowledgement_speech_started"] == 1240
        assert feedback["timing_ms"]["checking_working_shown"] == 1220
        serialized = json.dumps(event) + json.dumps(feedback) + caplog.text
        for private in ("ninety", '"transcript"', "authorization", "SECRET", "MUST NOT APPEAR"):
            assert private not in serialized

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        asyncio.run(exercise())
    assert "endpoint_decision" in caplog.text


def test_provider_boundary_does_not_fabricate_an_idle_or_first_byte():
    timing = EndpointTiming()
    timing.partial(2)
    timing.final(2.1)
    timing.begin(2.1, idle=False)
    assert timing.event("decision", 2.1)["timing_ms"]["partial_idle_fired"] is None
    timing.partial(3)
    timing.begin(3.8, idle=True)
    event = timing.event("decision", 3.8)
    assert event["timing_ms"]["final_transcript_received"] is None
    assert event["timing_ms"]["acknowledgement_audio_first_byte"] is None


def test_browser_feedback_is_allowlisted_and_rejects_invalid_timing():
    timing = EndpointTiming()
    timing.partial(1)
    timing.begin(1.8, idle=True)
    event = timing.event("final", 2)
    with pytest.raises(ValueError):
        browser_timing({**event, "cue": "candidate text"})
    with pytest.raises(ValueError):
        browser_timing({**event, "timing_ms": {**event["timing_ms"], "checking_working_shown": float("nan")}})


def test_browser_timing_route_logs_only_allowlisted_fields(caplog):
    from fastapi.testclient import TestClient
    from app.main import app

    timing = EndpointTiming()
    timing.partial(1)
    timing.begin(1.8, idle=True)
    event = timing.event("final", 2)
    event.update(transcript="private candidate words", authorization="private key")
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        client = TestClient(app)
        response = client.post("/api/voice/timing", json=event)
    assert response.status_code == 200
    assert "private" not in response.text + caplog.text
    assert set(response.json()["timing_ms"]) == set(STAGES)
    assert client.post("/api/voice/timing", json=event,
                       headers={"origin": "https://elsewhere.invalid"}).status_code == 403
    assert client.post("/api/voice/timing", json={**event, "cue": "private words"}).status_code == 422
