import asyncio
import json

import pytest

from voice.provider import MetaVoice, REALTIME
from voice.recording import VoiceError
from voice.relay import realtime_answer


@pytest.fixture(autouse=True)
def no_live_endpoint_calls(monkeypatch):
    async def thinking(self, text):
        return {"finished": False, "kind": "thinking"}, {}
    monkeypatch.setattr(MetaVoice, "endpoint", thinking)


class Browser:
    def __init__(self, done=True):
        self.output = []
        self.receives = 0
        self.done = done

    async def send_json(self, event):
        self.output.append(event)

    async def receive(self):
        self.receives += 1
        if self.receives == 1:
            return {"type": "websocket.receive", "bytes": b"\x00\x00" * 1280}
        if self.done:
            await asyncio.sleep(0)
            return {"type": "websocket.receive", "text": '{"type":"done"}'}
        await asyncio.Future()


class Upstream:
    def __init__(self):
        self.frames = []
        self.events = asyncio.Queue()
        self.close_code = 1000

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def recv(self):
        return '{"sessionId":"synthetic-session"}'

    async def send(self, frame):
        self.frames.append(frame)
        if isinstance(frame, bytes):
            for event in [
                {"type": "speechStart", "turnId": 1},
                {"type": "transcript", "transcript": "There are ninety"},
                {"type": "speechEnd", "turnId": 1},
                {"type": "speechComplete", "turnId": 1, "transcript": "There are nineteen."},
                {"type": "speechStart", "turnId": 2},
                {"type": "transcript", "transcript": "So it is ninety"},
                {"type": "speechEnd", "turnId": 2},
            ]:
                await self.events.put(event)
        elif json.loads(frame).get("type") == "endStream":
            await self.events.put({"type": "speechComplete", "turnId": 2, "transcript": "So it is nineteen percent."})
            await self.events.put({"type": "transcript", "transcript": "", "final": True})
            await self.events.put(None)

    def __aiter__(self):
        async def receive():
            while True:
                event = await self.events.get()
                if event is None:
                    return
                yield json.dumps(event)
        return receive()


def test_initial_auth_done_draining_and_keyless_replay(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-server-key")

    async def exercise():
        upstream = Upstream()

        def connect(url, **kwargs):
            assert url == REALTIME and "additional_headers" not in kwargs
            return upstream

        browser = Browser()
        live = MetaVoice(record_dir=tmp_path)
        text, model = await asyncio.wait_for(realtime_answer(browser, live, {"sample_rate": 16000}, connect=connect), 2)
        assert text == "There are nineteen. So it is nineteen percent."
        auth = json.loads(upstream.frames[0])
        assert auth["authorization"]["accessToken"] == "Bearer synthetic-server-key"
        assert auth["mode"] == "ENDPOINTING" and auth["audioEncoding"] == "PCM_16KHZ"
        assert any(isinstance(frame, bytes) for frame in upstream.frames)
        assert json.loads(upstream.frames[-1]) == {"type": "endStream"}
        assert not any(event["type"] in {"challenge_result", "answer_complete"} for event in browser.output)
        assert "synthetic-server-key" not in json.dumps(browser.output)
        monkeypatch.delenv("MODEL_API_KEY")
        replayed, metadata = await realtime_answer(Browser(), MetaVoice("replay", tmp_path),
            {"replay_id": model["run_id"]}, replay_speed=0,
            connect=lambda *args, **kwargs: pytest.fail("Replay opened a network socket"))
        assert replayed == text and metadata["mode"] == "replay"

    asyncio.run(exercise())
    for path in tmp_path.glob("*.json"):
        assert "synthetic-server-key" not in path.read_text(encoding="utf-8")


def test_content_closer_ends_input_without_done(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-server-key")

    class FinalizedUpstream(Upstream):
        async def send(self, frame):
            if isinstance(frame, str) and json.loads(frame).get("type") == "endStream":
                self.frames.append(frame)
                await self.events.put(None)
                return
            await super().send(frame)
            if isinstance(frame, bytes):
                await self.events.put({"type": "speechComplete", "turnId": 2, "transcript": "So it is nineteen percent. That's my answer."})

    async def exercise():
        upstream = FinalizedUpstream()
        text, _ = await asyncio.wait_for(realtime_answer(Browser(done=False), MetaVoice(record_dir=tmp_path),
            {}, silence_s=0.02, connect=lambda *a, **k: upstream), 2)
        assert text == "There are nineteen. So it is nineteen percent. That's my answer."
        assert json.loads(upstream.frames[-1]) == {"type": "endStream"}

    asyncio.run(exercise())


def test_disconnect_and_upstream_error_are_recorded_safely(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-server-key")

    class BadUpstream(Upstream):
        async def recv(self):
            return '{"type":"error","authorization":"Bearer synthetic-server-key"}'

    async def exercise():
        with pytest.raises(VoiceError, match="could not start"):
            await realtime_answer(Browser(), MetaVoice(record_dir=tmp_path), {}, connect=lambda *a, **k: BadUpstream())

    asyncio.run(exercise())
    records = list(tmp_path.glob("*.json"))
    assert len(records) == 1
    saved = records[0].read_text(encoding="utf-8")
    assert '"status": "failed"' in saved and "synthetic-server-key" not in saved


def test_live_transcription_reports_its_audio_seconds_not_a_latency():
    from voice.provider import metadata
    record = {"kind": "realtime", "request": {}, "run_id": "r", "recorded_at": "t", "latency_s": 70.0,
              "events": [{"elapsed_s": 0, "event": {}}, {"elapsed_s": 61.84, "event": {}}]}
    assert metadata(record, "live", "transcription")["audio_s"] == 61.8
    assert "audio_s" not in metadata({**record, "kind": "minimal", "events": []}, "live", "minimal")
