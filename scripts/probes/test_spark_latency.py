"""Latency probe checks use synthetic responses and never call Meta."""

from collections import Counter
import json

import httpx
import pytest

import probe_spark_latency as latency


def response(parsed=None, finish="stop", **extra):
    parsed = parsed or {"committed_number_text": "none", "is_commitment": False}
    return {"choices": [{"finish_reason": finish, "message": {"content": json.dumps(parsed)}}], **extra}


def fake_client(monkeypatch, calls, behavior="success", key="offline-test-credential"):
    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 90, "follow_redirects": False}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            assert url == "https://api.meta.ai/v1/chat/completions"
            assert kwargs["headers"]["Authorization"] == "Bearer " + key
            calls.append(kwargs["json"])
            if behavior == "timeout":
                raise httpx.ReadTimeout("synthetic credential echo " + key)
            body = response(echo=key)
            if behavior == "truncated":
                body = response(finish="length", echo=key)
            if behavior == "schema_violation":
                body = response({"committed_number_text": "none", "is_commitment": "false"}, echo=key)
            return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setenv("MODEL_API_KEY", key)


def test_ten_invented_answers_and_both_documented_arms():
    assert len(latency.ANSWERS) == len(set(latency.ANSWERS)) == 10
    assert latency.EFFORTS == ("low", "minimal")
    for effort in latency.EFFORTS:
        request = latency.request_for(latency.ANSWERS[0], effort)
        assert request["model"] == "muse-spark-1.3"
        assert request["reasoning_effort"] == effort and request["max_tokens"] >= 4000
        schema = request["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False
        assert set(schema["schema"]["required"]) == {"committed_number_text", "is_commitment"}


@pytest.mark.parametrize("finish", ["length", "content_filter", None])
def test_incomplete_outputs_fail(finish):
    with pytest.raises(latency.probes.ProbeFailure, match="truncated"):
        latency.parse_response(response(finish=finish), "synthetic answer")


@pytest.mark.parametrize("parsed", [
    {"committed_number_text": "none", "is_commitment": True},
    {"committed_number_text": "95%", "is_commitment": True},
    {"committed_number_text": "90%", "is_commitment": False},
])
def test_missing_or_invented_committed_span_fails(parsed):
    with pytest.raises(latency.probes.ProbeFailure):
        latency.parse_response(response(parsed), "I think ninety percent.")


def test_parsed_commitment_is_returned():
    parsed = {"committed_number_text": "ninety percent", "is_commitment": True}
    assert latency.parse_response(response(parsed), "I think ninety percent.") == parsed


def test_twenty_calls_record_redact_and_replay_without_key(tmp_path, monkeypatch, capsys):
    calls = []
    fake_client(monkeypatch, calls)
    live, replay = tmp_path / "live", tmp_path / "replay"
    assert latency.main(["--mode", "live", "--run-dir", str(live)]) == 0
    manifest = json.loads((live / "manifest.json").read_text(encoding="utf-8"))
    assert len(calls) == 20
    assert Counter(call["reasoning_effort"] for call in calls) == {"low": 10, "minimal": 10}
    assert [call["reasoning_effort"] for call in calls[:4]] == ["low", "minimal", "minimal", "low"]
    assert len(manifest["calls"]) == 20
    assert all(call["latency_s"] >= 0 for call in manifest["calls"])
    for effort in latency.EFFORTS:
        assert manifest["summary"][effort]["complete"]
        assert manifest["summary"][effort]["median_s"] is not None
        assert manifest["summary"][effort]["max_s"] is not None
    for path in live.glob("*.json"):
        assert "offline-test-credential" not in path.read_text(encoding="utf-8")
    assert "offline-test-credential" not in capsys.readouterr().out
    monkeypatch.delenv("MODEL_API_KEY")

    def forbidden_client(**kwargs):
        pytest.fail("Replay tried to create an HTTP client")

    monkeypatch.setattr(httpx, "Client", forbidden_client)
    assert latency.main(["--mode", "replay", "--capture", str(live / "manifest.json"), "--run-dir", str(replay)]) == 0
    replayed = json.loads((replay / "manifest.json").read_text(encoding="utf-8"))
    assert replayed["summary"] == manifest["summary"]
    assert replayed["source_run_id"] == manifest["run_id"]
    assert len(list(replay.glob("*.json"))) == 21
    assert "OFFLINE REPLAY" in capsys.readouterr().out


@pytest.mark.parametrize("behavior,count,code", [("truncated", 20, 1), ("timeout", 20, 1), ("schema_violation", 1, 3)])
def test_failures_are_recorded_and_schema_contradictions_stop(tmp_path, monkeypatch, capsys, behavior, count, code):
    calls = []
    fake_client(monkeypatch, calls, behavior)
    directory = tmp_path / "run"
    assert latency.main(["--mode", "live", "--run-dir", str(directory)]) == code
    assert len(calls) == count
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert all(not arm["complete"] for arm in manifest["summary"].values())
    assert all(arm["median_s"] is None for arm in manifest["summary"].values())
    assert len(manifest["calls"]) == count
    for path in directory.glob("*.json"):
        assert "offline-test-credential" not in path.read_text(encoding="utf-8")
    assert "offline-test-credential" not in capsys.readouterr().out


def test_single_arm_and_missing_key(tmp_path, monkeypatch):
    calls = []
    fake_client(monkeypatch, calls)
    assert latency.main(["--mode", "live", "--effort", "low", "--run-dir", str(tmp_path / "low")]) == 0
    assert len(calls) == 10
    monkeypatch.delenv("MODEL_API_KEY")
    assert latency.main(["--mode", "live", "--run-dir", str(tmp_path / "missing")]) == 1
    assert len(calls) == 10
