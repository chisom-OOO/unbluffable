"""llm/: request shape, prompt, record/replay, failure handling and verbatim quotes.

Offline only: live calls go to a fake client; replay needs no key.
"""

import json

import pytest

from llm.backends import MetaAPIBackend, OpenWeightsBackend, get_backend
from llm.client import BASE_URL, STANDARD_MODEL, assert_standard_model, make_meta_client
from llm.extract import build_request, extract
from llm.prompt import STEP_DEFINITIONS, SYSTEM_PROMPT
from llm.replay import CallStore
from llm.schema import EXTRACTION_SCHEMA, STEPS, SchemaError, validate_extraction
from llm_fakes import FakeClient, chat_response, extraction
from engine.templates import flagship

WORKED = (
    "Out of 2,000 transactions, 20 are fraud and 18 of those get flagged. "
    "Of the 1,980 genuine ones, 99 get flagged, so 117 flagged in total. "
    "So the probability is 18 over 117."
)
WORKED_EXTRACTION = extraction(
    committed="So the probability is 18 over 117",
    quotes=[
        ("Out of 2,000 transactions, 20 are fraud", "base_rate"),
        ("18 of those get flagged", "likelihood"),
        ("Of the 1,980 genuine ones, 99 get flagged", "false_positive_count"),
        ("117 flagged in total", "total_positive"),
        ("18 over 117", "posterior"),
    ],
    code="valid",
)


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("LLM_MODE", raising=False)


@pytest.fixture
def store(tmp_path):
    return CallStore(tmp_path / "calls")


def record(store, transcript, response, puzzle=None, latency_s=7.5):
    """Write a synthetic recording for exactly the request extract() will make."""
    request = build_request(puzzle or flagship(), transcript)
    store.save("meta_api", request, response, latency_s=latency_s)
    return request


# --- Request shape -----------------------------------------------------------


def test_request_is_strict_low_effort_standard_model():
    req = build_request(flagship(), WORKED)
    assert req["model"] == STANDARD_MODEL == "muse-spark-1.3"
    assert req["reasoning_effort"] == "low"
    assert req["max_tokens"] >= 4000
    fmt = req["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == EXTRACTION_SCHEMA


def _walk(schema):
    yield schema
    for child in schema.get("properties", {}).values():
        yield from _walk(child)
    if "items" in schema:
        yield from _walk(schema["items"])


def test_schema_is_in_the_strict_subset():
    assert set(EXTRACTION_SCHEMA["required"]) == {
        "committed_answer_text", "reasoning_quotes", "reasoning_code",
        "misconception_name", "self_corrected",
    }
    for node in _walk(EXTRACTION_SCHEMA):
        assert "oneOf" not in node and "allOf" not in node
        if node["type"] == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def test_contributor_models_are_rejected():
    with pytest.raises(ValueError):
        assert_standard_model("muse-spark-1.3-contributor")
    assert_standard_model(STANDARD_MODEL)


def test_client_gets_key_and_base_url_explicitly(monkeypatch):
    import openai

    seen = {}

    class Capture:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(openai, "OpenAI", Capture)
    monkeypatch.setenv("MODEL_API_KEY", "test-key-not-real")
    make_meta_client()
    assert seen["api_key"] == "test-key-not-real"
    assert seen["base_url"] == BASE_URL == "https://api.meta.ai/v1"


def test_missing_key_is_a_clear_error():
    with pytest.raises(RuntimeError, match="MODEL_API_KEY"):
        make_meta_client()


# --- Prompt ------------------------------------------------------------------


def test_prompt_defines_every_step_value():
    assert set(STEP_DEFINITIONS) == set(STEPS)
    for step, definition in STEP_DEFINITIONS.items():
        assert f"- {step}: {definition}" in SYSTEM_PROMPT


def test_hypothetical_is_a_counterfactual_not_a_natural_frequency_setup():
    hyp = STEP_DEFINITIONS["hypothetical"].lower()
    assert "counterfactual" in hyp and "does not commit" in hyp
    assert "if it were" in hyp and "suppose" in hyp
    assert "out of 2,000 transactions" in hyp and "base_rate" in hyp
    assert "out of 2,000 transactions" in STEP_DEFINITIONS["base_rate"].lower()


def test_puzzle_numbers_are_in_the_user_message():
    user = build_request(flagship(), WORKED)["messages"][1]["content"]
    assert "1%" in user and "90%" in user and "5%" in user
    assert WORKED in user


# --- Record / replay -----------------------------------------------------------


def test_live_call_is_recorded_without_the_key_and_replays_offline(store, monkeypatch):
    client = FakeClient(chat_response(WORKED_EXTRACTION))
    live = extract(flagship(), WORKED, mode="live", backend=MetaAPIBackend(client=client), store=store)
    assert live.ok and not live.replayed
    assert len(client.calls) == 1
    sent = client.calls[0]
    assert sent["reasoning_effort"] == "low" and sent["max_tokens"] >= 4000
    assert sent["response_format"]["json_schema"]["strict"] is True

    files = list(store.directory.glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert saved["run_id"] and saved["recorded_at"] and saved["backend"] == "meta_api"
    assert "api_key" not in json.dumps(saved).lower()

    # Replay: no key, no client, same result.
    replay = extract(flagship(), WORKED, mode="replay", store=store)
    assert replay.ok and replay.replayed
    assert replay.extraction == live.extraction
    assert replay.run_id == saved["run_id"]
    assert replay.latency_s == saved["latency_s"]


def test_live_record_redacts_a_key_echoed_by_the_provider(store, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "sk-test-echo-123")
    echoed = chat_response(WORKED_EXTRACTION)
    echoed["debug"] = "auth was Bearer sk-test-echo-123"
    extract(flagship(), WORKED, mode="live", backend=MetaAPIBackend(client=FakeClient(echoed)), store=store)
    text = next(store.directory.glob("*.json")).read_text(encoding="utf-8")
    assert "sk-test-echo-123" not in text and "[REDACTED]" in text


def test_replay_miss_fails_without_network(store):
    result = extract(flagship(), WORKED, mode="replay", store=store)
    assert not result.ok and result.error == "replay_missing"


def test_default_mode_is_replay(store):
    record(store, WORKED, chat_response(WORKED_EXTRACTION))
    result = extract(flagship(), WORKED, store=store)
    assert result.ok and result.replayed


# --- Failures --------------------------------------------------------------------


@pytest.mark.parametrize(
    "response, error",
    [
        (chat_response(WORKED_EXTRACTION, finish_reason="length"), "finish_length"),
        (chat_response(WORKED_EXTRACTION, finish_reason="content_filter"), "finish_content_filter"),
        (chat_response("", refusal="I can't help"), "refusal"),
        (chat_response("{not json"), "invalid_json"),
        (chat_response({**WORKED_EXTRACTION, "extra": 1}), "schema_invalid"),
        (chat_response({**WORKED_EXTRACTION, "reasoning_code": "great"}), "schema_invalid"),
        ({"choices": []}, "no_choices"),
    ],
)
def test_bad_responses_are_failures(store, response, error):
    record(store, WORKED, response)
    result = extract(flagship(), WORKED, mode="replay", store=store)
    assert not result.ok
    assert result.error == error


def test_validate_extraction_rejects_wrong_types():
    bad = {**WORKED_EXTRACTION, "self_corrected": "yes"}
    with pytest.raises(SchemaError):
        validate_extraction(bad)
    validate_extraction(WORKED_EXTRACTION)


# --- Verbatim quotes ----------------------------------------------------------------


def test_quotes_not_found_verbatim_are_dropped(store):
    resp = extraction(
        committed="So the probability is 18 over 117",
        quotes=[
            ("117 flagged in total", "total_positive"),
            ("eighteen of those are flagged", "likelihood"),  # paraphrase: not in the text
        ],
        code="valid",
    )
    record(store, WORKED, chat_response(resp))
    result = extract(flagship(), WORKED, mode="replay", store=store)
    assert result.ok
    assert [q.quote for q in result.quotes] == ["117 flagged in total"]
    assert [q.quote for q in result.dropped_quotes] == ["eighteen of those are flagged"]
    assert result.committed_text == "So the probability is 18 over 117"
    assert result.committed_verbatim


def test_committed_text_not_in_transcript_is_flagged(store):
    record(store, WORKED, chat_response({**WORKED_EXTRACTION, "committed_answer_text": "2/13"}))
    result = extract(flagship(), WORKED, mode="replay", store=store)
    assert result.ok and not result.committed_verbatim


# --- Backend switch -----------------------------------------------------------------


def test_backend_switch(monkeypatch):
    assert isinstance(get_backend(), MetaAPIBackend)
    monkeypatch.setenv("LLM_BACKEND", "open_weights")
    assert isinstance(get_backend(), OpenWeightsBackend)
    monkeypatch.setenv("LLM_BACKEND", "something_else")
    with pytest.raises(ValueError):
        get_backend()


def test_open_weights_without_key_fails_cleanly(store, monkeypatch):
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    result = extract(flagship(), WORKED, mode="live", backend=OpenWeightsBackend(), store=store)
    assert not result.ok and result.error == "missing_key"
    assert not list(store.directory.glob("*.json"))


def test_replay_is_keyed_by_backend(store):
    record(store, WORKED, chat_response(WORKED_EXTRACTION))  # meta_api recording
    result = extract(flagship(), WORKED, mode="replay", backend=OpenWeightsBackend(), store=store)
    assert result.error == "replay_missing"
