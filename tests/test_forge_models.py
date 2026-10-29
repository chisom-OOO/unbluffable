import json
from decimal import Decimal

import pytest

from forge.errors import BudgetStop, Reject, ReplayMissing, ResumeBlocked
from forge.models import Models, State
from forge.schemas import BLIND


class Backend:
    def __init__(self, name, responses=None):
        self.name = name
        self.model = "muse-spark-1.3" if name == "meta_api" else "meta-models/muse-spark-open-1026"
        self.enforces_schema = name == "meta_api"
        self.calls = []
        self.responses = responses or [{"answer": "2"}]

    def complete(self, request):
        self.calls.append(request)
        body = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(body, Exception):
            raise body
        if "choices" in body:
            return body
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 200}}


def models(tmp_path, **kwargs):
    state = State(tmp_path)
    author, checker = Backend("open_weights"), Backend("meta_api")
    return Models(state, mode="live", author=author, checker=checker, **kwargs)


def call(model, **kwargs):
    return model.call("blind_model", {"question": "Invented question"}, BLIND, "Solve exactly.", **kwargs)


def test_calls_use_existing_record_store_and_charge_usage_once(tmp_path):
    model = models(tmp_path)
    assert call(model) == {"answer": "2"}
    assert model.spent() == Decimal(".000975")
    assert len(model.checker.calls) == 1
    before = {p.name: p.read_bytes() for p in (tmp_path / "calls").glob("*.json")}
    assert call(model) == {"answer": "2"} and len(model.checker.calls) == 1
    replay = Models(model.state, mode="replay", author=model.author, checker=model.checker)
    assert call(replay) == {"answer": "2"} and replay.spent() == model.spent()
    assert {p.name: p.read_bytes() for p in (tmp_path / "calls").glob("*.json")} == before


def test_budget_reserves_before_network_and_never_overruns_limit(tmp_path):
    model = models(tmp_path, budget_usd=".0001")
    with pytest.raises(BudgetStop):
        call(model)
    assert not model.checker.calls and model.spent() == 0


def test_crash_after_reservation_never_automatically_retries(tmp_path):
    model = models(tmp_path)
    call(model)
    for path in (tmp_path / "calls").glob("*.json"):
        path.unlink()
    with pytest.raises(ResumeBlocked):
        call(model)
    assert len(model.checker.calls) == 1


def test_replay_missing_never_calls_a_backend(tmp_path):
    model = models(tmp_path)
    model.mode = "replay"
    with pytest.raises(ReplayMissing):
        call(model)
    assert not model.checker.calls


def test_open_weights_schema_repair_is_separate_cached_and_bounded(tmp_path):
    model = models(tmp_path)
    model.author.responses = [{"wrong": True}, {"answer": "2"}]
    assert call(model, author=True) == {"answer": "2"}
    assert len(model.author.calls) == 2
    assert len(list((tmp_path / "calls").glob("*.json"))) == 2
    assert model.spent() == Decimal(".001950")
    call(model, author=True)
    assert len(model.author.calls) == 2


@pytest.mark.parametrize("body,count", [
    ({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}, 1),
    ({"wrong": True}, 2),
])
def test_invalid_or_truncated_outputs_cannot_loop(tmp_path, body, count):
    model = models(tmp_path)
    model.author.responses = [body]
    with pytest.raises(Reject):
        call(model, author=True)
    assert len(model.author.calls) == count


def test_failed_call_is_recorded_without_exception_text_and_never_retried(tmp_path):
    model = models(tmp_path)
    model.checker.responses = [RuntimeError("Private error details must not be copied")]
    with pytest.raises(Reject):
        call(model)
    with pytest.raises(Reject):
        call(model)
    assert len(model.checker.calls) == 1
    for path in (tmp_path / "calls").glob("*.json"):
        assert "Private error details" not in path.read_text(encoding="utf-8")


def test_prices_are_configurable_and_resume_cannot_reprice_old_calls(tmp_path):
    model = models(tmp_path, prices={"meta_api": ("2", "3"), "open_weights": ("2", "3")})
    call(model)
    assert model.spent() == Decimal(".0008")
    with pytest.raises(ValueError):
        Models(model.state, prices={"meta_api": ("1", "1"), "open_weights": ("1", "1")},
               author=model.author, checker=model.checker)
