import copy
import csv
import json

import pytest

from forge import models as model_module
from forge import run
from forge_fakes import draft, question, response_for


class Backend:
    def __init__(self, name):
        self.name = name
        self.model = "meta-models/muse-spark-open-1026" if name == "open_weights" else "muse-spark-1.3"
        self.enforces_schema = name == "meta_api"
        self.calls = []

    def complete(self, request):
        self.calls.append(copy.deepcopy(request))
        stage = request["response_format"]["json_schema"]["name"].removeprefix("forge_")
        payload = json.loads(request["messages"][-1]["content"])
        response = response_for(stage, payload, draft())
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(response)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 200}}


def configure(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.setenv("LLM_BACKEND", "open_weights")
    monkeypatch.setenv("MODEL_API_KEY", "synthetic-cli-meta")
    monkeypatch.setenv("BASETEN_API_KEY", "synthetic-cli-baseten")
    author, checker = Backend("open_weights"), Backend("meta_api")
    backend = lambda name=None: author if name == "open_weights" else checker
    monkeypatch.setattr(run, "get_backend", backend)
    monkeypatch.setattr(model_module, "get_backend", backend)
    csv_path = tmp_path / "data" / "bank" / "invented.csv"
    csv_path.parent.mkdir(parents=True)
    q = question()
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["question_id", "title", "difficulty", "topics", "statement", "solution"])
        writer.writeheader()
        writer.writerow({key: getattr(q, key) if key != "topics" else "probability" for key in writer.fieldnames})
    work = tmp_path / "data" / "forge"
    args = ["--csv", str(csv_path), "--work-dir", str(work), "--mode", "live", "--limit", "100", "--trials", "1000"]
    return args, author, checker


def test_cli_fake_pilot_resume_and_no_bank_text_in_public_output(tmp_path, monkeypatch, capsys):
    args, author, checker = configure(tmp_path, monkeypatch)
    assert run.main(args) == 0
    public = capsys.readouterr().out + (tmp_path / "forge" / "funnel.json").read_text(encoding="utf-8")
    assert question().statement not in public and question().question_id not in public
    report = json.loads((tmp_path / "forge" / "funnel.json").read_text(encoding="utf-8"))
    assert report["accepted_templates"] == 1 and report["acceptance_rate"] == 1
    assert report["billing_per_topic"]["probability"]["calls"] == 5
    assert report["billing_per_stage"]["author"]["calls"] == 1
    paid = len(author.calls) + len(checker.calls)
    assert paid == 5
    assert run.main(args) == 0
    assert len(author.calls) + len(checker.calls) == paid


def test_budget_stop_then_resume_uses_cached_calls(tmp_path, monkeypatch, capsys):
    args, author, checker = configure(tmp_path, monkeypatch)
    assert run.main([*args, "--budget-usd", "0"]) == 2
    assert not author.calls and not checker.calls
    assert run.main(args) == 0
    paid = len(author.calls) + len(checker.calls)
    assert run.main([*args, "--mode", "replay"]) == 0
    assert len(author.calls) + len(checker.calls) == paid


@pytest.mark.parametrize("bad", [".env", "captures/private.csv", "recordings/private.csv", "scripts/gate/runs/private.csv"])
def test_cli_refuses_environment_and_capture_inputs_before_opening(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    with pytest.raises(SystemExit):
        run.main(["--csv", str(tmp_path / bad), "--work-dir", str(tmp_path / "data" / "forge")])


def test_job_lock_prevents_two_writers(tmp_path):
    with run.job_lock(tmp_path):
        with pytest.raises(OSError):
            with run.job_lock(tmp_path):
                pass


def test_live_cli_missing_key_stops_before_bank_or_model_access(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, "ROOT", tmp_path)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setattr(run, "load_csv", lambda path: pytest.fail("Missing-key preflight opened a bank"))
    assert run.main(["--csv", str(tmp_path / "private.csv"), "--mode", "live", "--work-dir", str(tmp_path / "data" / "forge")]) == 1
    assert "MissingKey" in capsys.readouterr().out
