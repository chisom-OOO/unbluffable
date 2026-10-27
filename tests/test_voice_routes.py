import json

from fastapi.testclient import TestClient

from app.main import app
from app import voice_routes
from voice.answers import ACKNOWLEDGEMENT


class Provider:
    def __init__(self):
        self.calls = []

    async def transcribe(self, audio):
        return {"transcript": "The detector catches 90% of fraud.", "editable": True, "model": {}}

    async def extract(self, text, full=False):
        self.calls.append(full)
        if not full:
            return {"committed_number_text": "90%", "is_commitment": False}, {}
        return {"committed_answer_text": "none", "reasoning_quotes": [], "reasoning_code": "vague",
                "misconception_name": "none", "self_corrected": False}, {}


def test_file_fallback_waits_for_confirmation_then_acknowledges(monkeypatch):
    provider = Provider()
    monkeypatch.setattr(voice_routes, "provider", lambda: provider)
    client = TestClient(app)
    result = client.post("/api/voice/transcribe", content=b"synthetic-audio", headers={"content-type": "audio/webm"})
    assert result.status_code == 200 and result.json()["editable"]
    assert not provider.calls
    with client.websocket_connect("/api/voice/answer") as socket:
        socket.send_json({"transcript": result.json()["transcript"]})
        first = socket.receive_json()
        assert first["type"] == "answer_complete" and first["acknowledgement"] == ACKNOWLEDGEMENT
        messages = [socket.receive_json() for _ in range(3)]
        challenge = next(message for message in messages if message["type"] == "challenge_result")
        assert challenge["should_challenge"] is False
    assert sorted(provider.calls) == [False, True]


def test_public_static_assets_and_consent_controls():
    client = TestClient(app)
    html = client.get("/practice")
    assert html.status_code == 200 and 'id="done"' in html.text and 'id="consent"' in html.text
    js = client.get("/voice-static/voice.js")
    assert js.status_code == 200 and "speak(event.acknowledgement)" in js.text
    assert "MODEL_API_KEY" not in html.text + js.text
    assert client.get("/voice-static/mic-worklet.js").status_code == 200
    assert 'Start interview' in html.text and 'id="headphones"' in html.text


def test_one_start_accepts_multiple_answers_without_another_gesture(monkeypatch):
    provider = Provider()
    provider.mode = "live"
    monkeypatch.setattr(voice_routes, "provider", lambda: provider)
    captures = []

    async def capture(socket, current, start, *args):
        captures.append(start)
        await socket.send_json({"type": "ready", "model": {"mode": "live"}})
        message = await socket.receive_json()
        return message["transcript"], {}

    monkeypatch.setattr(voice_routes, "realtime_answer", capture)
    with TestClient(app).websocket_connect("/api/voice/realtime") as socket:
        socket.send_json({"type": "start", "hands_free": True})
        assert socket.receive_json()["type"] == "ready"
        for _ in range(2):
            socket.send_json({"transcript": "The detector catches 90% of fraud."})
            acknowledged = False
            while True:
                event = socket.receive_json()
                if event["type"] == "answer_complete":
                    assert not acknowledged
                    acknowledged = True
                if event["type"] == "ready":
                    assert acknowledged
                    break
    assert len(captures) == 3
    assert all(start["hands_free"] for start in captures)


def test_cross_origin_websocket_is_rejected():
    from starlette.websockets import WebSocketDisconnect
    import pytest
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/api/voice/answer", headers={"origin": "https://unrelated.example"}):
            pass
