"""Offline transport, quote-integrity, credential handling, and replay checks."""

import asyncio
import json
import sys
from types import SimpleNamespace
import wave

import pytest

import probe_support as probes


def valid_extraction():
    return {
        "committed_answer_text": "2/13",
        "reasoning_quotes": [{"quote": probes.SENTENCES[-1], "step": "posterior"}],
        "reasoning_code": "valid", "misconception_name": "none", "self_corrected": False,
    }


def completion(parsed, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(parsed)}}]}


@pytest.mark.parametrize("finish", ["length", "content_filter", None])
def test_incomplete_chat_is_rejected(finish):
    with pytest.raises(probes.ProbeFailure, match="incomplete"):
        probes.parse_chat(completion(valid_extraction(), finish), "spark_strict")


def test_invented_quotes_are_rejected_and_enum_is_enforced():
    parsed = valid_extraction()
    parsed["reasoning_quotes"][0]["quote"] = "The answer is ninety percent."
    with pytest.raises(probes.ProbeFailure, match="verbatim"):
        probes.parse_chat(completion(parsed), "spark_strict")
    with pytest.raises(probes.SpecContradiction, match="enum"):
        probes.parse_chat(completion(parsed), "quote_enum")
    parsed["reasoning_quotes"][0]["quote"] = "probability is 2/13"
    assert probes.parse_chat(completion(parsed), "spark_strict")["quotes_found_verbatim"]
    with pytest.raises(probes.SpecContradiction):
        probes.parse_chat(completion(parsed), "quote_enum")


def test_synthetic_quote_enum_succeeds():
    result = probes.parse_chat(completion(valid_extraction()), "quote_enum")
    assert result["parsed"]["committed_answer_text"] == "2/13"


def test_capture_and_report_redact_even_echoed_credentials(tmp_path, monkeypatch, capsys):
    fake_key = "synthetic-credential-for-offline-test"
    monkeypatch.setenv("MODEL_API_KEY", fake_key)

    def fake_live(probe, recorder, key, wav):
        recorder.data["response"] = {"authorization": "Bearer " + key}
        recorder.event({"type": "transcript", "transcript": "echo " + key}, None)
        return {"text": "echo " + key}

    monkeypatch.setattr(probes, "run_live", fake_live)
    capture, report = tmp_path / "capture.json", tmp_path / "sheet.md"
    assert probes.main("wonder", ["--capture", str(capture), "--report", str(report)]) == 0
    assert fake_key not in capture.read_text(encoding="utf-8")
    assert fake_key not in report.read_text(encoding="utf-8")
    assert fake_key not in capsys.readouterr().out


def test_replay_needs_neither_key_nor_network(tmp_path, monkeypatch, capsys):
    capture, report = tmp_path / "capture.json", tmp_path / "sheet.md"
    recorder = probes.Recorder("wonder", capture)
    recorder.data.update(status="passed", result={"text": "synthetic fixture"})
    recorder.save()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)

    def no_network(*args):
        raise AssertionError("replay attempted live work")

    monkeypatch.setattr(probes, "run_live", no_network)
    assert probes.main("wonder", ["--mode", "replay", "--capture", str(capture), "--report", str(report)]) == 0
    assert "OFFLINE REPLAY" in capsys.readouterr().out
    assert "OFFLINE REPLAY" in report.read_text(encoding="utf-8")


def test_missing_key_is_recorded_without_network(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    capture, report = tmp_path / "capture.json", tmp_path / "sheet.md"
    assert probes.main("wonder", ["--capture", str(capture), "--report", str(report)]) == 1
    assert json.loads(capture.read_text(encoding="utf-8"))["status"] == "blocked"


def test_wav_format_and_raw_pcm(tmp_path):
    path = tmp_path / "clip.wav"
    pcm = b"\x00\x00" * 1600
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(pcm)
    actual, info = probes.load_wav(path)
    assert actual == pcm and info["duration_s"] == 0.1
    with wave.open(str(path), "wb") as audio:
        audio.setparams((2, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(pcm)
    with pytest.raises(probes.ProbeFailure, match="mono"):
        probes.load_wav(path)


def test_realtime_auth_pacing_revisions_and_drain(tmp_path, monkeypatch, capsys):
    sent, sleeps = [], []
    events = [
        {"sessionId": "offline-session"},
        {"type": "speechStart", "turnId": 1},
        {"type": "transcript", "transcript": "ninety", "final": False},
        {"type": "transcript", "transcript": "nine", "final": False},
        {"type": "speechEnd", "turnId": 1},
        {"type": "speechComplete", "turnId": 1, "transcript": "Nine."},
    ]
    ended = asyncio.Event()

    class Socket:
        close_code = 1000

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, frame):
            sent.append(frame)
            if isinstance(frame, str) and json.loads(frame).get("type") == "endStream":
                ended.set()

        async def recv(self):
            return json.dumps(events[0])

        def __aiter__(self):
            async def iterate():
                await ended.wait()
                for event in events[1:]:
                    yield json.dumps(event)
            return iterate()

    def connect(url, **kwargs):
        assert url == probes.REALTIME_URL and "authorization" not in kwargs
        return Socket()

    original_sleep = asyncio.sleep

    async def fake_sleep(delay):
        sleeps.append(delay)
        await original_sleep(0)

    monkeypatch.setitem(sys.modules, "websockets.asyncio.client", SimpleNamespace(connect=connect))
    monkeypatch.setattr(probes.asyncio, "sleep", fake_sleep)
    recorder = probes.Recorder("voice_realtime", tmp_path / "capture.json", "offline-key")
    pcm = b"\x00\x00" * 2560  # Two 80 ms frames at 16 kHz.
    result = asyncio.run(probes.stream_wav(recorder, pcm, {"sample_rate": 16000}, "offline-key"))
    handshake = json.loads(sent[0])
    assert handshake["authorization"]["accessToken"] == "Bearer offline-key"
    assert handshake["audioEncoding"] == "PCM_16KHZ" and handshake["mode"] == "ENDPOINTING"
    assert b"".join(frame for frame in sent if isinstance(frame, bytes)) == pcm
    assert json.loads(sent[-1]) == {"type": "endStream"}
    assert len(sleeps) == 2 and all(delay > 0 for delay in sleeps)
    assert result["partial_count"] == 2 and result["completed_turns"] == 1
    partials = [row for row in recorder.data["events"] if row["event"].get("type") == "transcript"]
    assert [row["event"]["transcript"] for row in partials] == ["ninety", "nine"]
    assert all(row["stream_elapsed_s"] >= 0 and row["arrival_utc"] for row in partials)
    assert "offline-key" not in capsys.readouterr().out
