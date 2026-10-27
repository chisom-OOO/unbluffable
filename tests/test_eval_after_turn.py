"""eval/after_turn_set.py: CSV in, per-row outcome / pass / latency out (offline)."""

import csv

import pytest

from engine.templates import flagship
from eval.after_turn_set import load_rows, main, run_set
from llm.extract import build_request
from llm.replay import CallStore
from llm_fakes import chat_response, extraction

ROWS = [
    {
        "clip": "E99",
        "transcript": "So if it's flagged, it's about ninety percent likely to be fraud.",
        "expected_outcome": "named_wrong",
    },
    {
        "clip": "N99",
        "transcript": "The detector catches ninety percent of fraud.",
        "expected_outcome": "vague",
    },
    {
        "clip": "C99",
        "transcript": "So the probability is two thirteenths.",
        "expected_outcome": "correct",  # will fail: no recording -> fallback -> vague
    },
]


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)


def write_csv(path, rows, fields=("clip", "transcript", "expected_outcome")):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def seed_store(store):
    store.save("meta_api", build_request(flagship(), ROWS[0]["transcript"]), chat_response(extraction(
        "it's about ninety percent likely to be fraud", [], "misconception", "transposed_conditional",
    )), latency_s=7.2)
    store.save("meta_api", build_request(flagship(), ROWS[1]["transcript"]), chat_response(extraction(
        "none", [("The detector catches ninety percent of fraud", "restated_given")], "vague",
    )), latency_s=9.8)


def test_run_set_reports_outcome_pass_and_latency(tmp_path):
    store = CallStore(tmp_path / "calls")
    seed_store(store)
    rows = load_rows(write_csv(tmp_path / "set.csv", ROWS))
    results = run_set(rows, flagship(), mode="replay", store=store)

    by_clip = {r.clip: r for r in results}
    assert by_clip["E99"].outcome == "named_wrong" and by_clip["E99"].passed
    assert by_clip["E99"].challenged
    assert by_clip["E99"].latency_s == 7.2 and by_clip["E99"].replayed
    assert by_clip["N99"].outcome == "vague" and by_clip["N99"].passed
    assert not by_clip["N99"].challenged
    assert by_clip["C99"].outcome == "vague" and not by_clip["C99"].passed
    assert by_clip["C99"].source == "fallback" and by_clip["C99"].error == "replay_missing"


def test_main_writes_a_report_and_exits_nonzero_on_failures(tmp_path, capsys):
    store_dir = tmp_path / "calls"
    seed_store(CallStore(store_dir))
    out = tmp_path / "report.csv"
    code = main([
        "--csv", str(write_csv(tmp_path / "set.csv", ROWS)),
        "--store", str(store_dir), "--out", str(out),
    ])
    assert code == 1
    printed = capsys.readouterr().out
    assert "2/3 passed" in printed
    assert "replay" in printed.lower()
    with out.open(encoding="utf-8") as f:
        report = list(csv.DictReader(f))
    assert [r["clip"] for r in report] == ["E99", "N99", "C99"]
    assert {"outcome", "passed", "latency_s", "source", "challenged"} <= set(report[0])


def test_all_passing_set_exits_zero(tmp_path):
    store_dir = tmp_path / "calls"
    seed_store(CallStore(store_dir))
    path = write_csv(tmp_path / "set.csv", ROWS[:2])
    assert main(["--csv", str(path), "--store", str(store_dir)]) == 0


def test_bad_csv_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="columns"):
        load_rows(write_csv(tmp_path / "a.csv", [{"clip": "x", "text": "y"}], fields=("clip", "text")))
    with pytest.raises(ValueError, match="expected_outcome"):
        load_rows(write_csv(tmp_path / "b.csv", [{"clip": "x", "transcript": "y", "expected_outcome": "great"}]))


def test_default_mode_is_replay(tmp_path):
    # Without --mode live, nothing is sent anywhere; a missing recording falls back.
    path = write_csv(tmp_path / "set.csv", ROWS[2:])
    assert main(["--csv", str(path), "--store", str(tmp_path / "empty")]) == 1
