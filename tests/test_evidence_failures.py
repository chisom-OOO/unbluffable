"""Evidence harness: refuses to start without its keys, counts failed calls by type, and marks a
run with any failed call INVALID (no headline, no p-values). Fake models only, no network."""

import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "evidence"))

import harness  # noqa: E402
from test_evidence_harness import ITEMS, ScriptedProvider, extraction  # noqa: E402
from voice.provider import IncompleteOutput, MetaVoice  # noqa: E402
from voice.recording import VoiceError  # noqa: E402

PROVENANCE = {"runs": 1, "backend": "fake", "model": "fake", "git_commit": "abc", "items_file": "items.json",
              "items_sha256": "0" * 64, "prompt_sha256": {"plain": "1"}, "created_at": "now"}


# --- Keys ------------------------------------------------------------------------------

def test_missing_keys_names_each_variable_the_arms_need():
    assert harness.missing_keys(["meta_api"], {}) == ["MODEL_API_KEY"]
    assert harness.missing_keys(["meta_api", "open_weights"], {"MODEL_API_KEY": "k"}) == ["BASETEN_API_KEY"]
    assert harness.missing_keys(["meta_api", "open_weights"], {"MODEL_API_KEY": " \n", "BASETEN_API_KEY": "k"}) == ["MODEL_API_KEY"]
    assert harness.missing_keys(["meta_api", "open_weights"], {"MODEL_API_KEY": "k", "BASETEN_API_KEY": "k"}) == []


def test_main_refuses_to_start_without_keys(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BACKEND", "meta_api")
    started = []
    monkeypatch.setattr(harness, "evaluate", lambda *a, **k: started.append(1))
    monkeypatch.setattr(harness, "load_items", lambda *a: started.append(1))
    code = harness.main(["--items", str(tmp_path / "items.json"), "--open-weights", "--out", str(tmp_path)])
    assert code == 2 and not started and not list(tmp_path.iterdir())
    out = capsys.readouterr().out
    assert "MODEL_API_KEY" in out and "BASETEN_API_KEY" in out
    monkeypatch.setenv("MODEL_API_KEY", "dummy")  # one key set: the other arm still blocks the run
    assert harness.main(["--items", str(tmp_path / "items.json"), "--open-weights", "--out", str(tmp_path)]) == 2
    assert "BASETEN_API_KEY" in capsys.readouterr().out and not started


# --- Failure types ------------------------------------------------------------------------

def test_failures_are_classified_by_type():
    assert harness.failure_type(VoiceError("Live mode needs MODEL_API_KEY in the server environment.")) == "missing_key"
    assert harness.failure_type(VoiceError("The model request failed. Your transcript is available.")) == "request_failed"
    assert harness.failure_type(IncompleteOutput("Incomplete or refused model output was rejected.")) == "incomplete_output"
    assert harness.failure_type(VoiceError("The model returned an invalid extraction.")) == "invalid_output"
    assert harness.failure_type(VoiceError("No recorded result matches this answer.")) == "no_recording"
    assert harness.failure_type("The committed number was not found verbatim in your answer.") == "not_verbatim"
    assert harness.failure_type(VoiceError("down")) == "other"


class Failing:
    def __init__(self, error):
        self.error = error

    async def structured(self, *args):
        raise self.error


def test_every_failed_call_is_logged_with_arm_run_item_and_type():
    failures = []
    verdicts = asyncio.run(harness.evaluate(ITEMS[:1], Failing(VoiceError("Live mode needs MODEL_API_KEY.")),
                                            runs=2, failures=failures))
    assert all(run["sound"] == "error" for arm in verdicts.values() for run in arm)
    assert {f["type"] for f in failures} == {"missing_key"}
    # Each chatbot arm makes one call per run; Unbluffable's two lanes both fail on the original,
    # which ends that item (the twin is never analysed).
    per_arm = {arm: sum(1 for f in failures if f["arm"] == arm) for arm in harness.ARMS}
    assert per_arm == {"plain": 2, "careful": 2, "careful_answers": 2, "unbluffable": 4}
    assert {(f["run"], f["item"]) for f in failures} == {(0, "sound"), (1, "sound")}


class OneLaneFails(ScriptedProvider):
    """The fast lane fails; the full extraction still scores the answer."""

    async def structured(self, text, kind, effort, schema, prompt):
        if kind == "minimal":
            raise IncompleteOutput("Incomplete or refused model output was rejected.")
        return await super().structured(text, kind, effort, schema, prompt)


def test_a_failed_lane_counts_even_when_the_verdict_survives():
    failures = []
    verdicts = asyncio.run(harness.evaluate(ITEMS, OneLaneFails(), runs=1, failures=failures))
    assert verdicts["unbluffable"][0]["sound"] == "understands"
    assert failures and {(f["arm"], f["type"]) for f in failures} == {("unbluffable", "incomplete_output")}


# --- INVALID runs ----------------------------------------------------------------------------

def test_a_run_with_failed_calls_is_invalid_with_no_headline_or_p_values():
    failures = []
    verdicts = asyncio.run(harness.evaluate(ITEMS, OneLaneFails(), runs=1, failures=failures))
    results = harness.summarise(ITEMS, verdicts, PROVENANCE, failures)
    assert results["status"] == harness.INVALID
    assert results["headline_rule"] is None and results["mcnemar_vs_unbluffable"] is None and results["open_weights"] is None
    cf = results["call_failures"]
    assert cf["count"] == len(failures) and cf["by_type"] == {"incomplete_output": len(failures)}
    assert cf["items"] == sorted({f["item"] for f in failures})
    md = harness.markdown(results)
    assert md.startswith("# Evidence run: INVALID") and "incomplete_output" in md
    assert "McNemar" not in md and "Headline" not in md and "p (two-sided)" not in md
    assert harness.HEADLINE not in md and harness.HEADLINE_IF_CLOSE not in md


def test_a_clean_run_is_valid_and_keeps_its_statistics():
    failures = []
    verdicts = asyncio.run(harness.evaluate(ITEMS, ScriptedProvider(), runs=1, failures=failures))
    results = harness.summarise(ITEMS, verdicts, PROVENANCE, failures)
    assert failures == [] and results["status"] == "valid" and results["call_failures"]["count"] == 0
    assert results["headline_rule"]["headline"] and "Exact McNemar" in harness.markdown(results)


def test_http_failures_from_a_live_provider_make_the_run_invalid(tmp_path, monkeypatch):
    """The afternoon-of-run-1 shape: every call fails, and the run must not report numbers."""
    def handler(request):
        name = json.loads(request.content)["response_format"]["json_schema"]["name"]
        if name.startswith("evidence_"):
            return httpx.Response(401, json={"error": {"type": "auth", "message": "bad key"}})
        text = json.loads(request.content)["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(extraction(name, text))}}]})

    monkeypatch.setenv("LLM_BACKEND", "meta_api")
    monkeypatch.setenv("MODEL_API_KEY", "dummy-test-key")
    live = MetaVoice("live", str(tmp_path), transport=httpx.MockTransport(handler))
    failures = []
    verdicts = asyncio.run(harness.evaluate(ITEMS, live, runs=1, failures=failures))
    results = harness.summarise(ITEMS, verdicts, PROVENANCE, failures)
    assert results["status"] == harness.INVALID and results["headline_rule"] is None
    assert {f["type"] for f in failures} == {"request_failed"}
    assert {f["arm"] for f in failures} == {"plain", "careful", "careful_answers"}
