"""LLM_BACKEND=open_weights: Muse Spark Open on Baseten Model APIs (offline).

Baseten docs (checked 27 Oct 2026):
- Reasoning (https://docs.baseten.co/inference/model-apis/reasoning): Muse Spark Open
  always reasons; reasoning comes back in message.reasoning_content and the final
  answer in message.content; max_tokens caps reasoning + answer; reasoning_effort
  defaults to xhigh.
- Structured outputs (https://docs.baseten.co/inference/structured-outputs): Muse
  Spark Open accepts json_schema but does not enforce it, so code validates.
"""

import json

import pytest

from engine.templates import flagship
from llm.backends import OpenWeightsBackend
from llm.client import BASETEN_URL, OPEN_WEIGHTS_MODEL, make_baseten_client
from llm.extract import build_request, extract
from llm.prompt import SYSTEM_PROMPT
from llm.replay import CallStore
from llm.schema import EXTRACTION_SCHEMA
from llm_fakes import FakeClient, chat_response, extraction

TEXT = "So it's about ninety percent likely to be fraud."
GOOD = extraction("So it's about ninety percent likely to be fraud", [], "misconception",
                  "transposed_conditional")


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for name in ("MODEL_API_KEY", "BASETEN_API_KEY", "LLM_BACKEND", "LLM_MODE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def store(tmp_path):
    return CallStore(tmp_path / "calls")


def with_reasoning(content, reasoning="The candidate says 2/13 is wrong... {\"x\": 1}", **kw):
    body = chat_response(content, **kw)
    body["choices"][0]["message"]["reasoning_content"] = reasoning
    return body


def live(store, body, monkeypatch=None):
    client = FakeClient(body)
    result = extract(flagship(), TEXT, mode="live", backend=OpenWeightsBackend(client=client), store=store)
    return result, client


# --- Request -------------------------------------------------------------------


def test_request_uses_the_exact_model_and_low_effort():
    req = build_request(flagship(), TEXT, backend="open_weights")
    assert req["model"] == OPEN_WEIGHTS_MODEL == "meta-models/muse-spark-open-1026"
    assert req["reasoning_effort"] == "low"  # Baseten's default is xhigh
    assert req["max_tokens"] >= 4000
    assert req["response_format"]["json_schema"]["schema"] == EXTRACTION_SCHEMA


def test_schema_is_spelled_out_in_the_prompt_because_it_is_not_enforced():
    system = build_request(flagship(), TEXT, backend="open_weights")["messages"][0]["content"]
    assert system.startswith(SYSTEM_PROMPT)
    assert json.dumps(EXTRACTION_SCHEMA, separators=(",", ":")) in system
    # The Meta request is unchanged.
    assert build_request(flagship(), TEXT)["messages"][0]["content"] == SYSTEM_PROMPT


def test_baseten_client_gets_its_own_key_explicitly(monkeypatch):
    import openai

    seen = {}

    class Capture:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", Capture)
    monkeypatch.setenv("MODEL_API_KEY", "meta-key-not-this-one")
    monkeypatch.setenv("BASETEN_API_KEY", "baseten-test-key")
    make_baseten_client()
    assert seen["api_key"] == "baseten-test-key"
    assert seen["base_url"] == BASETEN_URL == "https://inference.baseten.co/v1"


def test_other_model_ids_are_refused():
    req = build_request(flagship(), TEXT, backend="open_weights") | {"model": "meta-models/other"}
    with pytest.raises(ValueError):
        OpenWeightsBackend(client=FakeClient(chat_response(GOOD))).complete(req)


# --- Final answer only ------------------------------------------------------------


def test_only_the_final_answer_is_parsed_not_the_reasoning(store):
    result, client = live(store, with_reasoning(GOOD))
    assert result.ok and result.backend == "open_weights"
    assert result.extraction == GOOD
    sent = client.calls[0]
    assert sent["model"] == OPEN_WEIGHTS_MODEL and sent["reasoning_effort"] == "low"


def test_reasoning_alone_is_not_an_answer(store):
    result, _ = live(store, with_reasoning("", reasoning=json.dumps(GOOD)))
    assert not result.ok and result.error == "empty_content"


def test_think_block_before_the_answer_is_ignored(store):
    content = "<think>maybe 2/13?</think>\n" + json.dumps(GOOD)
    result, _ = live(store, with_reasoning(content))
    assert result.ok and result.extraction == GOOD


@pytest.mark.parametrize(
    "content, error",
    [
        ("```json\n" + json.dumps(GOOD) + "\n```", "invalid_json"),  # no lenient repair
        ("Sure! Here is the JSON.", "invalid_json"),
        (json.dumps({**GOOD, "confidence": 0.9}), "schema_invalid"),
        (json.dumps({k: v for k, v in GOOD.items() if k != "self_corrected"}), "schema_invalid"),
        (json.dumps({**GOOD, "reasoning_code": "correct"}), "schema_invalid"),
    ],
)
def test_any_invalid_output_is_a_failure(store, content, error):
    result, _ = live(store, with_reasoning(content))
    assert not result.ok and result.error == error


def test_truncated_reasoning_is_a_failure(store):
    result, _ = live(store, with_reasoning(json.dumps(GOOD), finish_reason="length"))
    assert not result.ok and result.error == "finish_length"


# --- Record / replay / redaction -----------------------------------------------------


def test_recorded_redacted_and_replayed_without_a_key(store, monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "bt-secret-echo-42")
    body = with_reasoning(GOOD)
    body["debug"] = "Authorization: Api-Key bt-secret-echo-42"
    first, _ = live(store, body)
    assert first.ok
    files = list(store.directory.glob("*.json"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "bt-secret-echo-42" not in text and "[REDACTED]" in text
    assert json.loads(text)["backend"] == "open_weights"

    monkeypatch.delenv("BASETEN_API_KEY")
    again = extract(flagship(), TEXT, mode="replay", backend=OpenWeightsBackend(), store=store)
    assert again.ok and again.replayed and again.extraction == GOOD
    # The Meta backend has no recording for this call.
    assert extract(flagship(), TEXT, mode="replay", store=store).error == "replay_missing"


def test_scoring_is_the_same_code_path(store):
    from engine.coding import Outcome
    from llm.score import assess

    live(store, with_reasoning(GOOD))
    turn = assess(flagship(), TEXT, mode="replay", backend=OpenWeightsBackend(), store=store)
    assert turn.source == "model"
    assert turn.observation.outcome is Outcome.NAMED_WRONG


# --- One repair attempt (spec/03: schema in prompt + local validation + one repair) ---

BAD_JSON = "```json\n" + json.dumps(GOOD) + "\n```"
BAD_SCHEMA = json.dumps({**GOOD, "reasoning_code": "correct"})


def saved(store):
    files = list(store.directory.glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text(encoding="utf-8"))


@pytest.mark.parametrize("bad, detail", [(BAD_JSON, "not valid JSON"), (BAD_SCHEMA, "reasoning_code")])
def test_invalid_output_is_repaired_once(store, bad, detail):
    result, client = live(store, [with_reasoning(bad), with_reasoning(GOOD)])
    assert result.ok and result.repaired and result.attempts == 2
    assert result.extraction == GOOD
    assert len(client.calls) == 2

    first, repair = client.calls
    # The repair repeats the request, then sends back the invalid reply and the error.
    assert repair["messages"][: len(first["messages"])] == first["messages"]
    assistant, user = repair["messages"][-2:]
    assert assistant == {"role": "assistant", "content": bad}
    assert user["role"] == "user" and detail in user["content"]
    assert {k: v for k, v in repair.items() if k != "messages"} == {
        k: v for k, v in first.items() if k != "messages"
    }

    record = saved(store)
    assert record["repaired"] is True
    assert len(record["attempts"]) == 2
    assert record["latency_s"] == pytest.approx(sum(a["latency_s"] for a in record["attempts"]), abs=0.002)
    assert result.latency_s == record["latency_s"]


def test_second_invalid_output_is_a_failure(store):
    result, client = live(store, [with_reasoning(BAD_JSON), with_reasoning(BAD_SCHEMA)])
    assert not result.ok and result.error == "schema_invalid"
    assert result.repaired and result.attempts == 2
    assert len(client.calls) == 2  # exactly one repair, never a second
    assert saved(store)["repaired"] is True


def test_valid_output_needs_no_repair(store):
    result, client = live(store, [with_reasoning(GOOD)])
    assert result.ok and not result.repaired and result.attempts == 1
    assert len(client.calls) == 1
    record = saved(store)
    assert record["repaired"] is False and len(record["attempts"]) == 1


@pytest.mark.parametrize("body, error", [
    (with_reasoning(json.dumps(GOOD), finish_reason="length"), "finish_length"),
    (with_reasoning("", refusal="no"), "refusal"),
])
def test_truncation_and_refusal_are_not_repaired(store, body, error):
    result, client = live(store, [body, with_reasoning(GOOD)])
    assert not result.ok and result.error == error and len(client.calls) == 1


def test_meta_backend_is_strict_and_never_repaired(store):
    from llm.backends import MetaAPIBackend

    client = FakeClient([chat_response(BAD_JSON), chat_response(GOOD)])
    result = extract(flagship(), TEXT, mode="live", backend=MetaAPIBackend(client=client), store=store)
    assert not result.ok and result.error == "invalid_json" and not result.repaired
    assert len(client.calls) == 1


def test_repaired_call_replays_without_a_key(store):
    first, _ = live(store, [with_reasoning(BAD_JSON), with_reasoning(GOOD)])
    again = extract(flagship(), TEXT, mode="replay", backend=OpenWeightsBackend(), store=store)
    assert again.ok and again.replayed and again.repaired and again.attempts == 2
    assert again.extraction == GOOD and again.latency_s == first.latency_s


def test_failed_repair_call_is_recorded_and_replays_as_a_failure(store):
    result, client = live(store, [with_reasoning(BAD_JSON), TimeoutError("synthetic")])
    assert not result.ok and result.error == "call_failed:TimeoutError"
    assert result.repaired and len(client.calls) == 2
    record = saved(store)
    assert record["repair_error"] == "call_failed:TimeoutError"
    again = extract(flagship(), TEXT, mode="replay", backend=OpenWeightsBackend(), store=store)
    assert not again.ok and again.error == "call_failed:TimeoutError"
