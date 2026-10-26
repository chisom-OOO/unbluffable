"""Offline gate checks; all test utterances below are synthetic."""

from fractions import Fraction
import json
from pathlib import Path
import wave

import pytest

from claim_rules import ClaimTracker, find_claim, parse_number
import run_gate as gate


@pytest.mark.parametrize("text,expected", [
    ("90%", Fraction(9, 10)), ("90 percent", Fraction(9, 10)),
    ("ninety percent", Fraction(9, 10)), ("point nine", Fraction(9, 10)),
    ("0.9", Fraction(9, 10)), ("two over 13", Fraction(2, 13)),
    ("two over thirteen", Fraction(2, 13)), ("2/13", Fraction(2, 13)),
    ("two thirteenths", Fraction(2, 13)), ("95%", Fraction(19, 20)),
    ("ninety five percent", Fraction(19, 20)), ("five percent", Fraction(1, 20)),
    ("5.85%", Fraction(117, 2000)), ("five point eight five percent", Fraction(117, 2000)),
    ("fifteen point four percent", Fraction(77, 500)),
    ("nought point one five", Fraction(3, 20)), ("0.15", Fraction(3, 20)),
])
def test_numbers(text, expected):
    assert parse_number(text).value == expected


@pytest.mark.parametrize("text", ["two over", "ninety", "0.", "point", "two over zero", "ninety point"])
def test_incomplete_numbers_are_not_claims(text):
    assert parse_number(text) is None


@pytest.mark.parametrize("text", [
    "So the probability is 90%", "So it's ninety percent",
    "The answer is point nine", "You're about 90% likely to see fraud",
    "If the alert goes off, it's 90%", "If flagged it's 90 percent",
    "Given a flag, it's 0.9", "uh so if the alert goes off it's about 90% um likely",
])
def test_committed_markers(text):
    assert find_claim(text).number.value == Fraction(9, 10)


@pytest.mark.parametrize("text", [
    "The detector catches 90% of fraud", "It flags 5% of genuine transactions",
    "Maybe so the probability is 90%", "No, the answer is 90%",
    "Wait, so it's 90%", "If I ignore the base rate, so it's 90%",
    "Suppose the answer is 90%", "If it were different, so it's 90%",
    "If it was different, the answer is 90%", "So the probability is 90% would be my guess",
    "So the probability is 90% no wait", "So the probability is 90% I mean 15%",
    "So it's the detector that catches 90% of fraud",
    "So the probability is 90% of fraud being flagged",
    "You're about 90% through the explanation",
])
def test_exclusions(text):
    assert find_claim(text) is None


def partial(text, when):
    return {"stream_elapsed_s": when, "event": {"type": "transcript", "transcript": text, "final": False}}


def test_number_persists_while_full_partial_grows():
    tracker = ClaimTracker()
    assert tracker.consume(partial("So it's 90%", 1)) is None
    assert tracker.consume(partial("So it's 90% um", 1.2)) is None
    fired = tracker.consume(partial("So it's 90% um likely", 1.5))
    assert fired["challenge_elapsed_s"] == 1.5 and fired["named_wrong"] == "90%"
    assert tracker.consume(partial("So it's 90% um likely fraud", 2)) is None


def test_unrelated_prefix_revision_does_not_reset_the_number_span():
    tracker = ClaimTracker()
    tracker.consume(partial("uh so the probability is 90%", 1))
    fired = tracker.consume(partial("So the probability is 90% um", 1.5))
    assert fired and fired["challenge_elapsed_s"] == 1.5


def test_exact_boundary_and_no_timer_from_progress_or_finals():
    tracker = ClaimTracker()
    assert tracker.consume(partial("The answer is 95%", 0)) is None
    assert tracker.consume(partial("The answer is 95%", 0.499999)) is None
    assert tracker.consume({"stream_elapsed_s": 2, "event": {"type": "audioProgress"}}) is None
    assert tracker.consume({"stream_elapsed_s": 2.1, "event": {"type": "speechComplete", "turnId": 0}}) is None
    assert tracker.consume(partial("The answer is 95%", 3)) is None  # Turn reset.
    assert tracker.consume(partial("The answer is 95%", 3.5))["challenge_elapsed_s"] == 3.5


def test_revisions_removals_and_corrections_reset_stability():
    tracker = ClaimTracker()
    tracker.consume(partial("So it's 90%", 0))
    assert tracker.consume(partial("So it's", 0.6)) is None
    assert tracker.consume(partial("So it's 95%", 1)) is None
    assert tracker.consume(partial("So it's 95% wait", 2)) is None
    assert tracker.consume(partial("So it's 95%", 2.1)) is None
    assert tracker.consume(partial("So it's 95%", 2.6)) is not None


@pytest.mark.parametrize("text", ["2/13", "two thirteenths", "15%", "0.15", "fifteen point four percent"])
def test_correct_exact_and_approximate_answers_never_fire(text):
    tracker = ClaimTracker()
    tracker.consume(partial("So the probability is " + text, 0))
    assert tracker.consume(partial("So the probability is " + text + " um", 1)) is None


def test_wrong_fraction_uses_exact_match_and_other_wrong_is_challenged():
    for text in ["3/20", "20%"]:
        tracker = ClaimTracker()
        tracker.consume(partial("The answer is " + text, 0))
        fired = tracker.consume(partial("The answer is " + text, 0.5))
        assert fired and fired["named_wrong"] is None


def test_new_turn_and_new_claim_cannot_reuse_old_stability():
    tracker = ClaimTracker()
    tracker.consume({"stream_elapsed_s": 0, "event": {"type": "speechStart", "turnId": 1}})
    tracker.consume(partial("So it's 90%", 0.1))
    tracker.consume({"stream_elapsed_s": 0.5, "event": {"type": "speechStart", "turnId": 2}})
    assert tracker.consume(partial("So it's 90%", 1)) is None
    tracker.consume({"stream_elapsed_s": 1.1, "event": {"type": "speechComplete", "turnId": 1}})
    assert tracker.consume(partial("So it's 90% the answer is 90%", 1.5)) is None
    assert tracker.consume(partial("So it's 90% the answer is 90%", 2))


def test_live_probe_captures_with_original_event_times():
    runs = Path(__file__).resolve().parents[1] / "probes" / "runs"
    if not all((runs / f"voice_realtime-live-{index:02d}.json").exists() for index in [1, 2]):
        pytest.skip("Local ignored live probe captures are not available in this checkout.")
    first = json.loads((runs / "voice_realtime-live-01.json").read_text(encoding="utf-8"))
    second = json.loads((runs / "voice_realtime-live-02.json").read_text(encoding="utf-8"))
    assert gate.analyse_events(first["events"]) is None
    assert gate.analyse_events(second["events"])["challenge_elapsed_s"] == 8.806442


def result_rows(hits=8):
    rows = []
    for category in ["error", "non_error", "correct"]:
        for index in range(10):
            fired = category == "error" and index < hits
            rows.append({"clip": f"{category}{index}.wav", "category": category,
                         "should_fire": category == "error", "claim_end_s": 1,
                         "status": "passed", "challenge_fired": fired,
                         "challenge_elapsed_s": 2 if fired else None,
                         "latency_s": 1 if fired else None})
    return rows


def test_gate_thresholds_and_incomplete_set_cannot_pass():
    assert gate.summarize(result_rows())["passed"]
    assert not gate.summarize(result_rows(7))["passed"]
    rows = result_rows()
    rows[10].update(challenge_fired=True, latency_s=0.5)
    assert not gate.summarize(rows)["passed"]
    rows = result_rows()
    rows[0]["latency_s"] = 3.000001
    assert not gate.summarize(rows)["passed"]
    rows = result_rows()
    for row in rows[:8]:
        row["latency_s"] = 1.500001
    assert not gate.summarize(rows)["passed"]
    rows = result_rows()
    rows[0]["status"] = "failed"
    assert not gate.summarize(rows)["passed"]
    assert not gate.summarize(result_rows()[:-1])["passed"]


def test_latency_boundaries_are_inclusive_and_signed():
    rows = result_rows()
    for row, latency in zip(rows[:8], [0, 0, 0, 0, 3, 3, 3, 3]):
        row["latency_s"] = latency
    assert gate.summarize(rows)["passed"]  # Median exactly 1.5; max exactly 3.
    captured = {"status": "passed", "close_code": 1000, "events": [
        partial("So it's 90%", 0), partial("So it's 90% um", 0.5)]}
    row = gate.clip_result({"clip": "E01.wav", "category": "error", "should_fire": True,
                            "claim_end_s": 1}, captured)
    assert row["latency_s"] == -0.5


def test_non_csv_labels_are_rejected_without_reading(tmp_path):
    with pytest.raises(gate.GateError, match=".csv"):
        gate.load_labels(tmp_path, tmp_path / "not-labels.txt")


def test_labels_validate_files_categories_and_claim_times(tmp_path):
    wav = tmp_path / "E01.wav"
    with wave.open(str(wav), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x00" * 16000)
    labels = tmp_path / "labels.csv"
    labels.write_text("clip,category,should_fire,claim_end_s\nE01.wav,error,true,0.5\n", encoding="utf-8")
    assert gate.load_labels(tmp_path, labels)[0]["category"] == "error"
    for row in ["E01.wav,error,false,0.5", "E01.wav,error,true,nan", "E01.wav,error,true,2",
                "../E01.wav,error,true,0.5", "E01.wav,other,true,0.5"]:
        labels.write_text("clip,category,should_fire,claim_end_s\n" + row + "\n", encoding="utf-8")
        with pytest.raises(gate.GateError):
            gate.load_labels(tmp_path, labels)


def test_replay_recomputes_without_key_audio_or_network(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    events = [partial("So it's 90%", 1), partial("So it's 90% um", 1.5)]
    capture = {"format_version": 1, "probe": "voice_realtime", "status": "passed",
               "recorded_at": "2026-10-26T00:00:00+00:00", "events": events,
               "request": {"wav": {"duration_s": 4}}, "close_code": 1000}
    (source / "clip.json").write_text(json.dumps(capture), encoding="utf-8")
    manifest = {"format_version": 1, "kind": "realtime_gate", "run_id": "original",
                "recorded_at": capture["recorded_at"], "clips": [{
                    "clip": "E01.wav", "category": "error", "should_fire": True,
                    "claim_end_s": 1.1, "capture": "clip.json"}], "results": [{"invented": True}]}
    (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setattr(gate.probes, "stream_wav", lambda *a: pytest.fail("network in replay"))
    output = tmp_path / "replay"
    assert gate.main(["--mode", "replay", "--capture", str(source / "manifest.json"), "--run-dir", str(output)]) == 1
    saved = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert saved["results"][0]["challenge_fired"] is True
    assert saved["results"][0]["latency_s"] == 0.4
    assert saved["source_run_id"] == "original"
    assert "OFFLINE REPLAY" in (output / "report.md").read_text(encoding="utf-8")


def test_gate_recorder_redacts_and_applies_claims_before_writing(tmp_path, capsys):
    recorder = gate.GateRecorder(tmp_path / "clip.json", "synthetic-secret")
    # Make the clock deterministic without touching the transport.
    recorder.accept({"type": "transcript", "transcript": "So it's 90%"}, 1, 0)
    recorder.accept({"type": "transcript", "transcript": "So it's 90% um synthetic-secret"}, 1.5, 0)
    recorder.save()
    assert recorder.challenge["challenge_elapsed_s"] == 1.5
    assert "synthetic-secret" not in (tmp_path / "clip.json").read_text(encoding="utf-8")
    assert "So it's" not in capsys.readouterr().out
