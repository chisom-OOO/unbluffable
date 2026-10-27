import asyncio
from fractions import Fraction
import io
import json
import shutil
import wave

import httpx
import pytest

from voice import provider as module
from voice.answers import ACKNOWLEDGEMENT, analyse_answer, decision
from voice.provider import MetaVoice
from voice.recording import RecordStore, VoiceError


TEXT = "So the probability is ninety percent."


def extraction():
    return {"committed_answer_text": "ninety percent", "reasoning_quotes": [
        {"quote": "ninety percent", "step": "posterior"},
        {"quote": "invented quotation", "step": "other"}],
        "reasoning_code": "valid", "misconception_name": "none", "self_corrected": False}


def completion(data, finish="stop", **extra):
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(data)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}, **extra}


def test_record_replay_two_schemas_and_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-private-credential")
    requests = []

    async def handler(request):
        assert request.headers["authorization"] == "Bearer synthetic-private-credential"
        body = json.loads(request.content)
        requests.append(body)
        full = body["reasoning_effort"] == "low"
        data = extraction() if full else {"committed_number_text": "ninety percent", "is_commitment": True}
        return httpx.Response(200, json=completion(data, echo="synthetic-private-credential"))

    live = MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(handler))

    async def exercise():
        minimal, _ = await live.extract(TEXT)
        full, _ = await live.extract(TEXT, full=True)
        assert len(full["reasoning_quotes"]) == 1
        assert decision(TEXT, minimal)["should_challenge"]
        monkeypatch.delenv("MODEL_API_KEY")
        replay = MetaVoice("replay", tmp_path)
        assert (await replay.extract(TEXT))[0] == minimal
        assert (await replay.extract(TEXT, full=True))[0] == full

    asyncio.run(exercise())
    assert [r["reasoning_effort"] for r in requests] == ["minimal", "low"]
    assert all(r["max_tokens"] >= 4000 and r["response_format"]["json_schema"]["strict"] for r in requests)
    for path in tmp_path.glob("*.json"):
        assert "synthetic-private-credential" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("finish", ["length", "content_filter", None])
def test_truncated_finishes_fail(tmp_path, monkeypatch, finish):
    monkeypatch.setenv("MODEL_API_KEY", "offline-key")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=completion(
        {"committed_number_text": "none", "is_commitment": False}, finish)))
    with pytest.raises(VoiceError, match="Incomplete"):
        asyncio.run(MetaVoice(record_dir=tmp_path, transport=transport).extract(TEXT))


def test_ack_precedes_parallel_models_and_fast_does_not_wait_for_full():
    async def exercise():
        sent, started = [], set()
        both = asyncio.Event()
        release_full = asyncio.Event()
        got_fast = asyncio.Event()

        class Provider:
            async def extract(self, text, full=False):
                assert sent[0]["acknowledgement"] == ACKNOWLEDGEMENT
                started.add(full)
                if len(started) == 2:
                    both.set()
                await both.wait()
                if full:
                    await release_full.wait()
                    return extraction(), {"job": "extraction"}
                return {"committed_number_text": "ninety percent", "is_commitment": True}, {"job": "minimal"}

        async def send(event):
            sent.append(event)
            if event["type"] == "challenge_result":
                got_fast.set()

        task = asyncio.create_task(analyse_answer(Provider(), TEXT, send))
        await asyncio.wait_for(got_fast.wait(), 1)
        assert not any(row["type"] == "scoring_result" for row in sent)
        release_full.set()
        await task
        assert sent[-1]["type"] == "analysis_complete"
        assert next(row for row in sent if row["type"] == "scoring_result")["observation"] != "correct"

    asyncio.run(exercise())


def test_full_extraction_failure_does_not_hide_fast_challenge():
    class Provider:
        async def extract(self, text, full=False):
            if full:
                raise VoiceError("Synthetic full-lane failure.")
            return {"committed_number_text": "ninety percent", "is_commitment": True}, {}

    events = []

    async def send(event):
        events.append(event)

    asyncio.run(analyse_answer(Provider(), TEXT, send))
    assert any(row["type"] == "challenge_result" and row["should_challenge"] for row in events)
    assert any(row["type"] == "model_error" and row["job"] == "extraction" for row in events)
    assert events[-1]["type"] == "analysis_complete"


@pytest.mark.parametrize("text,span,commit,expected", [
    (TEXT, "ninety percent", True, True),
    ("The detector catches ninety percent of fraud.", "ninety percent", True, False),
    ("The detector catches 90% of fraud.", "90%", False, False),
    ("So it's two thirteenths.", "two thirteenths", True, False),
    ("So it's 15.4%.", "15.4%", True, False),
    ("I haven't decided.", "none", False, False),
    ("The detector catches 90% of fraud. So the probability is 90%.", "90%", True, True),
    ("So it's 90%, because the detector catches 90% of fraud.", "90%", True, True),
])
def test_exact_challenge_and_given_guard(text, span, commit, expected):
    assert decision(text, {"committed_number_text": span, "is_commitment": commit})["should_challenge"] == expected


def test_file_editable_and_replay_needs_neither_ffmpeg_nor_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "offline-key")
    converted = []

    async def convert(data):
        converted.append(data)
        return b"synthetic-wav-transport-fixture"

    async def handler(request):
        assert request.url.path == "/v1/asr/transcribe"
        assert "multipart/form-data" in request.headers["content-type"]
        assert b'muse-voice-transcribe-1.0' in request.content
        return httpx.Response(200, json={"transcript": TEXT})

    monkeypatch.setattr(module, "convert_to_wav", convert)
    live = MetaVoice(record_dir=tmp_path, transport=httpx.MockTransport(handler))
    result = asyncio.run(live.transcribe(b"original-webm-fixture"))
    assert result["editable"] and result["transcript"] == TEXT
    assert len(converted) == 1
    monkeypatch.delenv("MODEL_API_KEY")
    result = asyncio.run(MetaVoice("replay", tmp_path).transcribe(b"original-webm-fixture"))
    assert result["transcript"] == TEXT and result["model"]["mode"] == "replay"
    assert len(converted) == 1


def test_ffmpeg_converts_stereo_wav_to_16khz_mono():
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not available on this machine.")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setparams((2, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x00\x00\x00" * 2400)
    converted = asyncio.run(module.convert_to_wav(buffer.getvalue()))
    with wave.open(io.BytesIO(converted), "rb") as audio:
        assert audio.getnchannels() == 1 and audio.getsampwidth() == 2 and audio.getframerate() == 16000


def test_failed_records_do_not_hide_available_replay(tmp_path):
    store = RecordStore(tmp_path)
    good = store.create("minimal", {"case": 1})
    good.finish({"ok": True})
    bad = store.create("minimal", {"case": 2})
    bad.finish(error="failure")
    assert store.find("minimal", {"case": 1})["run_id"] == good.data["run_id"]
