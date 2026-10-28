"""HTTP diagnostics with mock transports only. No environment files or audio."""

import asyncio
import logging
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.model_diagnostics import log_startup_models
from llm.backends import MetaAPIBackend, OpenWeightsBackend
from llm.client import OPEN_WEIGHTS_MODEL, STANDARD_MODEL
from voice.provider import MetaVoice
from voice.recording import VoiceError


def test_startup_without_key_does_not_call_models(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    transport = httpx.MockTransport(lambda request: pytest.fail("No key must mean no models request"))
    asyncio.run(log_startup_models(transport=transport))


def test_app_startup_calls_models_once_and_logs_status_and_ids(monkeypatch, caplog):
    import app.main as main

    monkeypatch.setenv("MODEL_API_KEY", "synthetic-startup-key\n")
    monkeypatch.setattr(main, "initialize_database", lambda: None)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET" and str(request.url) == "https://api.meta.ai/v1/models"
        assert request.headers["authorization"] == "Bearer synthetic-startup-key"
        return httpx.Response(200, json={"data": [{"id": STANDARD_MODEL}, {"id": "muse-wonder-1.0"}],
                                        "ignored": "synthetic-startup-key"})

    async def diagnostic():
        await log_startup_models(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(main, "log_startup_models", diagnostic)
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        with TestClient(main.app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/health").status_code == 200
    assert len(requests) == 1
    assert "200" in caplog.text and STANDARD_MODEL in caplog.text and "muse-wonder-1.0" in caplog.text
    assert "synthetic-startup-key" not in caplog.text


@pytest.mark.parametrize("json_body", [True, False])
def test_models_failure_logs_status_and_request_id_without_body(monkeypatch, caplog, json_body):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-diagnostic-key")

    def handler(request):
        kwargs = {"json": {"error": "private answer synthetic-diagnostic-key"}} if json_body else {"text": "private answer synthetic-diagnostic-key"}
        return httpx.Response(403, headers={"request-id": "models-request-123"}, **kwargs)

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        asyncio.run(log_startup_models(transport=httpx.MockTransport(handler)))
    assert "403" in caplog.text and "models-request-123" in caplog.text
    assert "synthetic-diagnostic-key" not in caplog.text and "private answer" not in caplog.text


@pytest.mark.parametrize("header", ["request-id", "x-request-id"])
@pytest.mark.parametrize("json_body", [True, False])
def test_voice_http_failures_include_request_id(monkeypatch, tmp_path, caplog, header, json_body):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-voice-key")

    def handler(request):
        kwargs = {"json": {"error": {"type": "denied"}}} if json_body else {"text": "private response"}
        return httpx.Response(429, headers={header: "voice-request-456"}, **kwargs)

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        with pytest.raises(VoiceError):
            asyncio.run(MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(handler)).endpoint("Synthetic answer"))
    assert "429" in caplog.text and "voice-request-456" in caplog.text
    assert "synthetic-voice-key" not in caplog.text and "private response" not in caplog.text


@pytest.mark.parametrize("backend,model", [(MetaAPIBackend, STANDARD_MODEL), (OpenWeightsBackend, OPEN_WEIGHTS_MODEL)])
def test_sdk_http_failures_include_request_id_and_do_not_log_exception(backend, model, caplog):
    response = httpx.Response(503, headers={"x-request-id": "sdk-request-789"},
                              request=httpx.Request("POST", "https://example.invalid/v1/chat/completions"))

    class Failure(Exception):
        def __init__(self):
            self.response = response
            super().__init__("private candidate words and synthetic-sdk-key")

    def create(**kwargs):
        raise Failure()

    client = SimpleNamespace(api_key="synthetic-sdk-key", chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        with pytest.raises(Failure):
            backend(client).complete({"model": model})
    assert "503" in caplog.text and "sdk-request-789" in caplog.text
    assert "synthetic-sdk-key" not in caplog.text and "private candidate" not in caplog.text


def test_realtime_handshake_http_failure_logs_request_id(monkeypatch, tmp_path, caplog):
    from voice.relay import realtime_answer

    monkeypatch.setenv("MODEL_API_KEY", "synthetic-realtime-key")

    class Rejected(Exception):
        response = httpx.Response(401, headers={"request-id": "realtime-request-123"})

    class Connection:
        async def __aenter__(self):
            raise Rejected("private details synthetic-realtime-key")

        async def __aexit__(self, *args):
            pass

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        with pytest.raises(VoiceError):
            asyncio.run(realtime_answer(None, MetaVoice(record_dir=tmp_path), {}, connect=lambda *a, **kw: Connection()))
    assert "401" in caplog.text and "realtime-request-123" in caplog.text
    assert "synthetic-realtime-key" not in caplog.text and "private details" not in caplog.text


def test_reflected_credentials_in_ids_are_redacted(monkeypatch, caplog):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-reflected-key")

    def handler(request):
        return httpx.Response(403, json={"data": [{"id": "synthetic-reflected-key"}]},
                              headers={"request-id": "echo-synthetic-reflected-key"})

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        asyncio.run(log_startup_models(transport=httpx.MockTransport(handler)))
    assert "synthetic-reflected-key" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_startup_network_failure_is_nonfatal_and_does_not_log_exception(monkeypatch, caplog):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-network-key")

    def handler(request):
        raise httpx.ConnectError("private details synthetic-network-key", request=request)

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        asyncio.run(log_startup_models(transport=httpx.MockTransport(handler)))
    assert "ConnectError" in caplog.text and "HTTP unavailable" in caplog.text
    assert "synthetic-network-key" not in caplog.text and "private details" not in caplog.text
