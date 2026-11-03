"""Decision log 42: on the hosted app, model-call records (which hold answer and question text)
are not written to disk unless RECORD_MODEL_CALLS=1. Development keeps recording (rule 8)."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import byoq
from app.main import app
from llm import replay
from llm.replay import CallStore
from test_voice_relay import Browser, Upstream
from voice.provider import MetaVoice
from voice.recording import RecordStore
from voice.relay import realtime_answer


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("RECORD_MODEL_CALLS", raising=False)


@pytest.mark.parametrize("render, setting, expected", [
    (None, None, True),      # development: every live call is recorded
    ("true", None, False),   # the hosted app: off by default
    ("true", "1", True),     # the hosted app, switched on deliberately
    ("true", "0", False),
    (None, "0", False),
    (None, "1", True),
])
def test_recording_switch(monkeypatch, render, setting, expected):
    for name, value in (("RENDER", render), ("RECORD_MODEL_CALLS", setting)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert replay.recording_on() is expected


def files(path):
    return sorted(p.name for p in path.rglob("*") if p.is_file()) if path.exists() else []


def test_hosted_voice_record_stays_in_memory(tmp_path, hosted):
    record = RecordStore(tmp_path).create("extraction", {"messages": [{"role": "user", "content": "my answer is 19%"}]})
    record.event({"type": "transcript"}, 0.1)
    record.finish({"ok": True}, latency_s=0.2)
    assert record.data["status"] == "passed" and record.data["response"] == {"ok": True}
    assert files(tmp_path) == []


def test_development_voice_record_is_written(tmp_path, monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("RECORD_MODEL_CALLS", raising=False)
    RecordStore(tmp_path).create("extraction", {"x": 1}).finish({"ok": True})
    assert len(files(tmp_path)) == 1


def endpoint_reply(request):
    content = json.dumps({"finished": True, "kind": "answer"})
    return httpx.Response(200, json={"model": "muse-spark-1.3", "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                                     "choices": [{"finish_reason": "stop", "message": {"content": content}}]})


def test_hosted_live_spark_call_writes_nothing(tmp_path, hosted, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-key")
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    voice = MetaVoice("live", tmp_path, transport=httpx.MockTransport(endpoint_reply))
    parsed, model = asyncio.run(voice.endpoint("So the answer is nineteen percent. That's my answer."))
    assert parsed["finished"] is True and model["mode"] == "live"
    assert files(tmp_path) == []


def test_hosted_realtime_stream_writes_nothing(tmp_path, hosted, monkeypatch):
    async def thinking(self, text):
        return {"finished": False, "kind": "thinking"}, {}

    monkeypatch.setattr(MetaVoice, "endpoint", thinking)
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-key")
    text, _ = asyncio.run(asyncio.wait_for(realtime_answer(Browser(), MetaVoice(record_dir=tmp_path), {"sample_rate": 16000},
                                                           connect=lambda *a, **k: Upstream()), 2))
    assert text and files(tmp_path) == []


class Backend:
    name = "open_weights"

    def __init__(self):
        self.sent = []

    def complete(self, request):
        self.sent.append(request)
        return {"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}


def test_hosted_byoq_call_writes_nothing(tmp_path, hosted):
    backend = Backend()
    calls = byoq.Calls(CallStore(tmp_path), "live")
    request = {"model": "m", "messages": [{"role": "user", "content": "A bag has 3 red balls..."}]}
    assert calls.complete("read", backend, request)["choices"]
    assert calls.complete("read", backend, request)["choices"]  # nothing cached on disk: sent again
    assert len(backend.sent) == 2 and files(tmp_path) == []


def test_development_byoq_call_is_recorded_and_reused(tmp_path, monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("RECORD_MODEL_CALLS", raising=False)
    backend = Backend()
    calls = byoq.Calls(CallStore(tmp_path), "live")
    request = {"model": "m", "messages": []}
    calls.complete("read", backend, request)
    calls.complete("read", backend, request)
    assert len(backend.sent) == 1 and len(files(tmp_path)) == 1


def test_privacy_page_agrees_with_the_hosted_setting():
    html = TestClient(app).get("/ui/privacy").text
    assert "private records of the model calls" not in html
    assert "not written to disk" in html
    assert "in memory" in html and "gone after a restart" in html
