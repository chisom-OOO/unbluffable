"""Synthetic backend and replay contracts; no captures or live network calls."""

import asyncio
import json

import httpx
import pytest

from llm import backends
from llm.client import OPEN_WEIGHTS_MODEL, STANDARD_MODEL
from voice.provider import MetaVoice
from voice.recording import RecordStore, VoiceError
from voice.schemas import ENDPOINT, ENDPOINT_PROMPT, FULL, FULL_PROMPT, MINIMAL, MINIMAL_PROMPT

TEXT = "So the probability is nine percent."
MIN = {"committed_number_text": "nine percent", "is_commitment": True}
FULL_RESULT = {"committed_answer_text": "nine percent", "reasoning_quotes": [],
               "reasoning_code": "vague", "misconception_name": "none", "self_corrected": False}
CASES = [("endpoint", "minimal", ENDPOINT, ENDPOINT_PROMPT, {"finished": True, "kind": "answer"}),
         ("minimal", "minimal", MINIMAL, MINIMAL_PROMPT, MIN),
         ("extraction", "low", FULL, FULL_PROMPT, FULL_RESULT)]


@pytest.fixture(autouse=True)
def no_external_configuration(monkeypatch):
    for name in ("MODEL_API_KEY", "BASETEN_API_KEY", "LLM_BACKEND"):
        monkeypatch.delenv(name, raising=False)


def completion(result, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(result)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


@pytest.mark.parametrize("selected", ["meta_api", "open_weights"])
@pytest.mark.parametrize("kind,effort,schema,prompt,result", CASES, ids=["endpoint", "minimal", "full"])
def test_all_voice_spark_jobs_use_the_selected_llm_backend(tmp_path, monkeypatch, selected, kind, effort, schema, prompt, result):
    if selected == "open_weights":
        monkeypatch.setenv("LLM_BACKEND", selected)
        monkeypatch.setenv("BASETEN_API_KEY", "synthetic-baseten-key")
    else:
        monkeypatch.setenv("MODEL_API_KEY", "synthetic-meta-key")
    calls = []
    routed = []
    chosen = backends.get_backend(selected)
    original = chosen.acomplete

    async def acomplete(request, **kwargs):
        routed.append(request)
        return await original(request, **kwargs)

    monkeypatch.setattr(chosen, "acomplete", acomplete)
    monkeypatch.setattr(backends, "get_backend", lambda name=None: chosen)

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.host == ("inference.baseten.co" if selected == "open_weights" else "api.meta.ai")
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-" + ("baseten-key" if selected == "open_weights" else "meta-key")
        assert body["model"] == (OPEN_WEIGHTS_MODEL if selected == "open_weights" else STANDARD_MODEL)
        assert body["reasoning_effort"] == ("low" if selected == "open_weights" else effort)
        assert body["response_format"]["json_schema"] == {"name": kind, "strict": True, "schema": schema}
        assert body["messages"][0]["content"].startswith(prompt)
        if selected == "open_weights":
            assert json.dumps(schema, separators=(",", ":")) in body["messages"][0]["content"]
        return httpx.Response(200, json=completion(result))

    async def exercise():
        provider = MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(handler))
        if kind == "endpoint":
            parsed, model = await provider.endpoint(TEXT)
        else:
            parsed, model = await provider.extract(TEXT, full=kind == "extraction")
        assert parsed == result
        assert model["model"] == calls[0]["model"]
        if selected == "open_weights":
            assert model["estimated_cost_usd"] is None
        assert len(routed) == len(calls) == 1
    asyncio.run(exercise())


@pytest.mark.parametrize("kind,effort,schema,prompt,result", CASES, ids=["endpoint", "minimal", "full"])
def test_legacy_meta_replay_bytes_and_outputs_survive_backend_switch(tmp_path, monkeypatch, kind, effort, schema, prompt, result):
    request = {"model": STANDARD_MODEL, "reasoning_effort": effort, "max_tokens": 4000,
               "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": TEXT}],
               "response_format": {"type": "json_schema", "json_schema": {"name": kind, "strict": True, "schema": schema}}}
    stored = RecordStore(tmp_path).create(kind, request)
    stored.finish(completion(result), latency_s=.75)
    expected = (result, {"model": STANDARD_MODEL, "job": kind, "effort": effort,
                         "latency_s": .75, "estimated_cost_usd": .00021, "mode": "replay",
                         "run_id": stored.data["run_id"], "recorded_at": stored.data["recorded_at"]})
    original_bytes = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    monkeypatch.setenv("LLM_BACKEND", "open_weights")
    transport = httpx.MockTransport(lambda request: pytest.fail("Replay attempted network access"))
    replayed = asyncio.run(MetaVoice("replay", tmp_path, transport=transport).structured(TEXT, kind, effort, schema, prompt))
    assert json.dumps(replayed).encode() == json.dumps(expected).encode()
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == original_bytes


def test_open_weights_repairs_once_and_replays_without_keys_or_backend_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "open_weights")
    monkeypatch.setenv("BASETEN_API_KEY", "synthetic-baseten-key")
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=completion({"extra": True} if len(calls) == 1 else MIN))

    parsed, model = asyncio.run(MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(handler)).extract(TEXT))
    assert parsed == MIN and len(calls) == 2
    assert len(calls[1]["messages"]) == 4
    assert model["model"] == OPEN_WEIGHTS_MODEL and model["repaired"] is True
    before = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    assert len(before) == 2
    monkeypatch.delenv("BASETEN_API_KEY")
    monkeypatch.delenv("LLM_BACKEND")
    replayed, replay_model = asyncio.run(MetaVoice("replay", tmp_path).extract(TEXT))
    assert replayed == parsed and replay_model["model"] == OPEN_WEIGHTS_MODEL
    assert replay_model["repaired"] is True and replay_model["latency_s"] == model["latency_s"]
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == before


@pytest.mark.parametrize("finish,count", [("length", 1), ("stop", 2)])
def test_open_weights_failure_is_bounded(tmp_path, monkeypatch, finish, count):
    monkeypatch.setenv("LLM_BACKEND", "open_weights")
    monkeypatch.setenv("BASETEN_API_KEY", "synthetic-baseten-key")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=completion({"extra": True}, finish=finish))

    with pytest.raises(VoiceError):
        asyncio.run(MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(handler)).extract(TEXT))
    assert len(calls) == count


def test_open_weights_selection_keeps_file_transcription_on_meta(tmp_path, monkeypatch):
    from voice import provider as module
    monkeypatch.setenv("LLM_BACKEND", "open_weights")
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-asr-key")

    async def convert(audio):
        return b"synthetic converted audio"

    monkeypatch.setattr(module, "convert_to_wav", convert)

    def handler(request):
        assert request.url.host == "api.meta.ai" and request.url.path == "/v1/asr/transcribe"
        assert request.headers["authorization"] == "Bearer synthetic-asr-key"
        assert b"muse-voice-transcribe-1.0" in request.content
        return httpx.Response(200, json={"transcript": "Synthetic speech."})

    result = asyncio.run(MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(handler)).transcribe(b"synthetic input"))
    assert result["model"]["model"] == "muse-voice-transcribe-1.0"


def test_baseten_records_redact_its_key_and_ignore_reasoning_content(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "open_weights")
    monkeypatch.setenv("BASETEN_API_KEY", "synthetic-secret-echo")

    def handler(request):
        body = completion(MIN)
        body["choices"][0]["message"]["content"] = "<think>private internal reasoning</think>" + json.dumps(MIN)
        body["choices"][0]["message"]["reasoning_content"] = "not JSON or answer data"
        body["echo"] = "synthetic-secret-echo"
        return httpx.Response(200, json=body)

    result, model = asyncio.run(MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(handler)).extract(TEXT))
    assert result == MIN and model["repaired"] is False
    for path in tmp_path.glob("*.json"):
        assert "synthetic-secret-echo" not in path.read_text(encoding="utf-8")


def test_async_backend_cancellation_cancels_http_and_records_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "open_weights")
    monkeypatch.setenv("BASETEN_API_KEY", "synthetic-cancel-key")

    async def exercise():
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def handler(request):
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        provider = MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(handler))
        task = asyncio.create_task(provider.endpoint(TEXT))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()

    asyncio.run(exercise())
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    assert json.loads(body)["status"] == "failed" and "synthetic-cancel-key" not in body


def test_unknown_backend_is_rejected_without_network(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "unknown")
    with pytest.raises(VoiceError, match="LLM_BACKEND"):
        MetaVoice(record_dir=tmp_path)
