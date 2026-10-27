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


# --- open_weights arm (Muse Spark Open on Baseten) -----------------------------

META_KEY, BASETEN_KEY = "offline-meta-credential", "offline-baseten-credential"


def ow_response(parsed=None, finish="stop", content=None, reasoning="Thinking... 2/13? {\"x\": 1}"):
    body = response(parsed, finish)
    message = body["choices"][0]["message"]
    if content is not None:
        message["content"] = content
    message["reasoning_content"] = reasoning
    return body


def two_host_client(monkeypatch, calls, ow_body=None):
    """Fake httpx client for both hosts; answers agree except on case 5.

    `ow_body` overrides the open-weights reply: a body, or a function of
    (default body, attempt number for this answer) returning one.
    """
    attempts = Counter()
    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 90, "follow_redirects": False}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            body_json = kwargs["json"]
            answer = body_json["messages"][1]["content"]  # the candidate answer, also in a repair
            calls.append((url, body_json))
            parsed = {"committed_number_text": "none", "is_commitment": False}
            if answer == latency.ANSWERS[0]:
                parsed = {"committed_number_text": "ninety percent", "is_commitment": True}
            if url.startswith("https://inference.baseten.co/v1"):
                assert url == "https://inference.baseten.co/v1/chat/completions"
                assert kwargs["headers"]["Authorization"] == "Bearer " + BASETEN_KEY
                if answer == latency.ANSWERS[4]:
                    parsed = {"committed_number_text": "two over thirteen", "is_commitment": True}
                attempts[answer] += 1
                body = ow_response(parsed)
                if callable(ow_body):
                    body = ow_body(body, attempts[answer])
                elif ow_body is not None:
                    body = ow_body
                body = {**body, "echo": BASETEN_KEY}
            else:
                assert url == "https://api.meta.ai/v1/chat/completions"
                assert kwargs["headers"]["Authorization"] == "Bearer " + META_KEY
                body = response(parsed, echo=META_KEY)
            return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setenv("MODEL_API_KEY", META_KEY)
    monkeypatch.setenv("BASETEN_API_KEY", BASETEN_KEY)


def test_open_weights_request_matches_the_meta_arm_except_model():
    from llm.client import BASETEN_URL, OPEN_WEIGHTS_MODEL

    assert latency.ARMS == ("low", "minimal", "open_weights")
    assert latency.OPEN_WEIGHTS_MODEL == OPEN_WEIGHTS_MODEL == "meta-models/muse-spark-open-1026"
    assert latency.BASETEN_URL == BASETEN_URL
    ow = latency.request_for(latency.ANSWERS[0], "open_weights")
    meta = latency.request_for(latency.ANSWERS[0], "low")
    assert ow["model"] == "meta-models/muse-spark-open-1026"
    assert ow["reasoning_effort"] == "low" and ow["max_tokens"] >= 4000
    same = lambda r: {k: v for k, v in r.items() if k not in ("model", "messages")}
    assert same(ow) == same(meta)
    # spec/03: the schema is also in the prompt for a host that does not enforce it.
    assert ow["messages"][0]["content"].startswith(meta["messages"][0]["content"])
    assert json.dumps(latency.SCHEMA, separators=(",", ":")) in ow["messages"][0]["content"]
    assert meta["messages"][0]["content"] == latency.PROMPT
    assert ow["messages"][1] == meta["messages"][1]
    assert latency.url_for("open_weights") == "https://inference.baseten.co/v1/chat/completions"


def test_open_weights_parses_only_the_final_answer():
    parsed = {"committed_number_text": "ninety percent", "is_commitment": True}
    body = ow_response(parsed, reasoning=json.dumps({"committed_number_text": "none", "is_commitment": False}))
    assert latency.parse_response(body, "I think ninety percent.", "open_weights") == parsed
    think = ow_response(content="<think>hmm</think>" + json.dumps(parsed))
    assert latency.parse_response(think, "I think ninety percent.", "open_weights") == parsed


@pytest.mark.parametrize("content", [
    "```json\n{\"committed_number_text\": \"none\", \"is_commitment\": false}\n```",
    "{\"committed_number_text\": \"none\"}",
    "{\"committed_number_text\": \"none\", \"is_commitment\": \"false\"}",
    "",
])
def test_invalid_open_weights_output_is_a_plain_failure(content):
    with pytest.raises(latency.probes.ProbeFailure) as caught:
        latency.parse_response(ow_response(content=content), "synthetic answer", "open_weights")
    assert not isinstance(caught.value, latency.probes.SpecContradiction)


def test_all_arms_record_compare_and_replay_without_keys(tmp_path, monkeypatch, capsys):
    calls = []
    two_host_client(monkeypatch, calls)
    live, replay = tmp_path / "live", tmp_path / "replay"
    assert latency.main(["--mode", "live", "--effort", "all", "--run-dir", str(live)]) == 0
    assert len(calls) == 30
    assert Counter(body["model"] for _, body in calls) == {
        "muse-spark-1.3": 20, "meta-models/muse-spark-open-1026": 10,
    }
    manifest = json.loads((live / "manifest.json").read_text(encoding="utf-8"))
    summary = manifest["summary"]
    assert all(summary[arm]["complete"] for arm in latency.ARMS)
    assert summary["open_weights"]["agreement_with_low"] == {
        "compared": 10, "same_is_commitment": 9, "same_commitment_and_number": 9,
        "disagreeing_cases": [5],
    }
    assert summary["minimal"]["agreement_with_low"]["same_commitment_and_number"] == 10
    assert "agreement_with_low" not in summary["low"]
    for path in live.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert META_KEY not in text and BASETEN_KEY not in text
    assert BASETEN_KEY not in capsys.readouterr().out

    monkeypatch.delenv("MODEL_API_KEY")
    monkeypatch.delenv("BASETEN_API_KEY")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("Replay created an HTTP client"))
    assert latency.main(["--mode", "replay", "--capture", str(live / "manifest.json"), "--run-dir", str(replay)]) == 0
    replayed = json.loads((replay / "manifest.json").read_text(encoding="utf-8"))
    assert replayed["summary"] == summary


def test_invalid_open_weights_output_fails_the_arm_without_stopping_the_run(tmp_path, monkeypatch):
    calls = []
    two_host_client(monkeypatch, calls, ow_body=ow_response(content="not json"))
    directory = tmp_path / "run"
    assert latency.main(["--mode", "live", "--effort", "all", "--run-dir", str(directory)]) == 1
    # One repair per case and no strict-schema STOP for a host that does not enforce it.
    assert len(calls) == 40
    summary = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["summary"]
    assert summary["low"]["complete"] and summary["minimal"]["complete"]
    assert summary["open_weights"]["failed"] == 10
    assert summary["open_weights"]["agreement_with_low"]["compared"] == 0


def test_missing_baseten_key_blocks_before_any_call(tmp_path, monkeypatch):
    calls = []
    two_host_client(monkeypatch, calls)
    monkeypatch.delenv("BASETEN_API_KEY")
    assert latency.main(["--mode", "live", "--effort", "all", "--run-dir", str(tmp_path / "r")]) == 1
    assert calls == []
    assert latency.main(["--mode", "live", "--effort", "open_weights", "--run-dir", str(tmp_path / "s")]) == 1
    assert calls == []


def test_invalid_open_weights_output_is_repaired_once_and_timed_in_full(tmp_path, monkeypatch):
    calls = []

    def first_reply_fenced(body, attempt):
        if attempt == 1:
            return ow_response(content="```json\n" + body["choices"][0]["message"]["content"] + "\n```")
        return body

    two_host_client(monkeypatch, calls, ow_body=first_reply_fenced)
    directory = tmp_path / "run"
    assert latency.main(["--mode", "live", "--effort", "all", "--run-dir", str(directory)]) == 0
    ow_calls = [body for url, body in calls if "baseten" in url]
    assert len(calls) == 40 and len(ow_calls) == 20
    first, repair = ow_calls[0], ow_calls[1]
    assert repair["messages"][:2] == first["messages"]
    assert repair["messages"][2]["role"] == "assistant" and repair["messages"][2]["content"].startswith("```json")
    assert repair["messages"][3]["role"] == "user" and "not valid JSON" in repair["messages"][3]["content"]

    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    ow_rows = [row for row in manifest["calls"] if row["effort"] == "open_weights"]
    assert len(ow_rows) == 10 and all(row["repaired"] for row in ow_rows)
    assert not any(row["repaired"] for row in manifest["calls"] if row["effort"] != "open_weights")
    assert manifest["summary"]["open_weights"]["repaired"] == 10
    assert manifest["summary"]["open_weights"]["complete"]
    for row in ow_rows:
        capture = json.loads((directory / row["capture"]).read_text(encoding="utf-8"))
        assert capture["repaired"] is True and len(capture["attempts"]) == 2
        assert capture["latency_s"] == pytest.approx(sum(a["latency_s"] for a in capture["attempts"]))
        assert row["latency_s"] == capture["latency_s"]


def test_second_invalid_open_weights_output_fails(tmp_path, monkeypatch):
    calls = []
    two_host_client(monkeypatch, calls, ow_body=lambda body, attempt: ow_response(content="nope"))
    directory = tmp_path / "run"
    assert latency.main(["--mode", "live", "--effort", "open_weights", "--run-dir", str(directory)]) == 1
    assert len(calls) == 20  # exactly one repair per case
    summary = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["summary"]
    assert summary["open_weights"]["failed"] == 10 and summary["open_weights"]["repaired"] == 10


def test_valid_open_weights_output_is_not_repaired(tmp_path, monkeypatch):
    calls = []
    two_host_client(monkeypatch, calls)
    directory = tmp_path / "run"
    assert latency.main(["--mode", "live", "--effort", "open_weights", "--run-dir", str(directory)]) == 0
    assert len(calls) == 10
    summary = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["summary"]
    assert summary["open_weights"]["repaired"] == 0
