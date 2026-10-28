"""Synthetic merging tests; optional private capture checks never print speech."""

import json
from pathlib import Path

import pytest

from voice.turns import AnswerMerger
from voice.numbers import number_from_text
from fractions import Fraction


def test_short_pauses_revisions_and_late_finals_form_one_answer():
    merger = AnswerMerger()
    merger.feed({"type": "speechStart", "turnId": 1}, 0)
    merger.feed({"type": "transcript", "transcript": "There are ninety"}, 0.2)
    merger.feed({"type": "transcript", "transcript": "There are nineteen"}, 0.4)
    merger.feed({"type": "speechEnd", "turnId": 1}, 0.5)
    assert merger.remaining(3) == 0  # A boundary requests a content check, not completion.
    merger.feed({"type": "speechStart", "turnId": 2}, 0.8)
    merger.feed({"type": "speechComplete", "turnId": 1, "transcript": "There are nineteen."}, 0.9)
    assert merger.active == 2  # An older final must not stop a newer turn.
    merger.feed({"type": "transcript", "transcript": "So I get fifteen percent"}, 1)
    merger.feed({"type": "speechEnd", "turnId": 2}, 1.2)
    merger.feed({"type": "speechComplete", "turnId": 2, "transcript": "So I get fifteen percent."}, 1.3)
    merger.feed({"type": "transcript", "transcript": "", "final": True}, 1.4)
    assert merger.remaining(1.3) == 0
    assert merger.remaining(3) == 0
    assert merger.finish("content")["transcript"] == "There are nineteen. So I get fifteen percent."
    assert merger.finish("done") is None


def test_done_skips_wait_but_requires_finalized_text():
    merger = AnswerMerger(8)
    merger.feed({"type": "speechStart", "turnId": 4}, 0)
    merger.feed({"type": "transcript", "transcript": "ninety"}, 0.1)
    with pytest.raises(ValueError):
        merger.finish("done")
    merger.feed({"type": "speechComplete", "turnId": 4, "transcript": "Nineteen percent."}, 0.2)
    assert merger.finish("done")["transcript"] == "Nineteen percent."


def test_content_check_and_silence_prompt_do_not_complete_an_answer():
    merger = AnswerMerger()
    merger.feed({"type": "speechStart", "turnId": 1}, 0)
    merger.feed({"type": "speechEnd", "turnId": 1}, 0.2)
    merger.feed({"type": "speechComplete", "turnId": 1, "transcript": "Let me think."}, 0.3)
    assert merger.remaining(2) == 0
    merger.checked_revision = merger.revision
    assert merger.remaining(20) is None
    assert merger.prompt_remaining(8.2) == 0
    assert not merger.emitted
    merger.feed({"type": "speechStart", "turnId": 2}, 2.68)
    assert merger.active == 2 and not merger.emitted


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_silence(value):
    with pytest.raises(ValueError):
        AnswerMerger(value)


@pytest.mark.parametrize("text,value,form", [
    ("two over thirteen", Fraction(2, 13), "fraction"),
    ("two thirteenths", Fraction(2, 13), "fraction"),
    ("two over 13", Fraction(2, 13), "fraction"),
    ("2/13", Fraction(2, 13), "fraction"),
    ("fifteen point four percent", Fraction(77, 500), "percent"),
    ("about fifteen percent", Fraction(3, 20), "percent"),
    ("nought point one five", Fraction(3, 20), "decimal"),
    ("point nine", Fraction(9, 10), "decimal"),
    ("0.15", Fraction(3, 20), "decimal"),
    ("15%", Fraction(3, 20), "percent"),
    ("ninety-five percent", Fraction(19, 20), "percent"),
    ("5.85%", Fraction(117, 2000), "percent"),
])
def test_spoken_numbers(text, value, form):
    stated = number_from_text(text)
    assert stated.value == value and stated.form == form


@pytest.mark.parametrize("text", ["two over zero", "ninety", "none", "minus point one five", "-0.15"])
def test_unsupported_numbers_abstain(text):
    assert number_from_text(text) is None


CAPTURE_ROOT = Path(r"C:\Users\chiso\unbluffable\scripts\gate\runs")


@pytest.mark.parametrize("run", ["live-02", "live-03"])
def test_private_capture_turns_merge_without_copying(run):
    manifest_path = CAPTURE_ROOT / run / "manifest.json"
    if not manifest_path.exists():
        pytest.skip("Private read-only capture set is not installed on this machine.")
    source = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(source["clips"]) == 30
    for clip in source["clips"]:
        captured = json.loads((manifest_path.parent / clip["capture"]).read_text(encoding="utf-8"))
        # This is a merging check, not end-of-answer acceptance. The separate
        # voice.acceptance command exercises content decisions on these captures.
        merger = AnswerMerger()
        finals = {}
        completed = None
        elapsed = 0
        for row in captured["events"]:
            event = row["event"]
            if row.get("stream_elapsed_s") is None:
                continue
            elapsed = row["stream_elapsed_s"]
            merger.feed(event, row["stream_elapsed_s"])
            if event.get("type") == "speechStart":
                finals.setdefault(event["turnId"], "")
            if event.get("type") == "speechComplete":
                finals[event["turnId"]] = event.get("transcript", "")
        completed = merger.finish("done")
        expected = " ".join(value.strip() for value in finals.values() if value.strip())
        # Do not let assertion introspection copy private transcript text into logs.
        if completed is None or completed["transcript"] != expected or not expected:
            pytest.fail("Private capture did not produce its complete merged transcript.", pytrace=False)
        if merger.finish("done") is not None:
            pytest.fail("Private capture produced more than one answer.", pytrace=False)
