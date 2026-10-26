"""Tolerance rules, committed-claim detection and observation coding (spec/02 §1–2)."""

from fractions import Fraction

import pytest

from engine.answers import StatedNumber, committed_number, matches, parse_number
from engine.coding import Outcome, abstain, code_answer
from engine.templates import flagship, flagship_twin

TWO_13 = Fraction(2, 13)  # 15.38%


# --- Tolerance rules -------------------------------------------------------


@pytest.mark.parametrize(
    "text, ok",
    [
        ("2/13", True),
        ("18/117", True),  # equivalent fraction, still exact
        ("18 out of 117", True),
        ("3/20", False),  # 15% as a fraction is not exact
        ("15%", True),  # within 1pp as a percentage
        ("15.4 percent", True),
        ("16.38%", True),  # just inside 1pp
        ("16.5%", False),
        ("14.3%", False),
        ("0.154", True),  # decimal, within 1pp
        ("0.17", False),
    ],
)
def test_tolerance_rules(text, ok):
    stated = parse_number(text)
    assert stated is not None
    assert matches(stated, TWO_13) is ok


def test_parse_forms():
    assert parse_number("2/13") == StatedNumber(Fraction(2, 13), "fraction")
    assert parse_number("15.4%") == StatedNumber(Fraction(154, 1000), "percent")
    assert parse_number("0.154") == StatedNumber(Fraction(154, 1000), "decimal")
    assert parse_number("about 2,000 transactions") is None  # bare count


# --- Committed claims vs restated givens -----------------------------------


def test_restated_given_is_not_coded_as_an_answer():
    puz = flagship()
    text = "The detector catches 90% of fraud."
    assert committed_number(text) is None
    obs = code_answer(puz, committed_number(text), reasoning_code="vague")
    assert obs.outcome is not Outcome.NAMED_WRONG
    assert obs.outcome is Outcome.VAGUE  # no committed number


@pytest.mark.parametrize(
    "text",
    [
        "The chance that fraud gets flagged is 90%.",
        "The false alarm rate is 5%, and 1% of transactions are fraud.",
        "If it were 90 percent, that would be odd.",
        "So it's maybe 90 percent, no wait, let me count.",
        "So it's 90 percent. No, wait.",
    ],
)
def test_non_claims_are_not_committed(text):
    assert committed_number(text) is None


def test_transposed_conditional_claim_is_named_wrong():
    puz = flagship()
    text = "So if a transaction gets flagged, it's about 90 percent likely to be fraud."
    stated = committed_number(text)
    assert stated == StatedNumber(Fraction(9, 10), "percent")
    obs = code_answer(puz, stated, reasoning_code="misconception")
    assert obs.outcome is Outcome.NAMED_WRONG
    assert obs.misconception == "transposed_conditional"


def test_correct_claim_after_working():
    text = "18 of the 117 flagged are fraud, so the answer is 18 out of 117."
    assert committed_number(text) == StatedNumber(Fraction(18, 117), "fraction")


def test_self_correction_takes_the_last_claim():
    text = "So it's 90%. Wait, no. The answer is 2/13."
    assert committed_number(text) == StatedNumber(Fraction(2, 13), "fraction")


# --- Observation coding ----------------------------------------------------


def test_correct_needs_valid_reasoning():
    puz = flagship()
    stated = parse_number("2/13")
    assert code_answer(puz, stated, "valid").outcome is Outcome.CORRECT
    assert code_answer(puz, stated, "vague").outcome is Outcome.VAGUE
    assert code_answer(puz, stated, "misconception").outcome is Outcome.VAGUE


@pytest.mark.parametrize("text", ["3/20", "17%", "0.5", "90%", "95%", "5%"])
def test_wrong_number_never_coded_correct(text):
    obs = code_answer(flagship(), parse_number(text), "valid")
    assert obs.outcome is not Outcome.CORRECT


def test_named_wrong_values_reported_together():
    # f = 5% and P(+) = 5.85% are near-identical; 5.5% matches both.
    obs = code_answer(flagship(), parse_number("5.5%"), "misconception")
    assert obs.outcome is Outcome.NAMED_WRONG
    assert set(obs.matched) == {"false_alarm_rate", "flag_rate"}


def test_other_wrong_and_vague():
    puz = flagship()
    assert code_answer(puz, parse_number("40%"), "other_wrong").outcome is Outcome.OTHER_WRONG
    assert code_answer(puz, None, "vague").outcome is Outcome.VAGUE


def test_twin_recited_and_correct():
    twin = flagship_twin()
    assert code_answer(twin, parse_number("2/13"), "valid").outcome is Outcome.RECITED
    assert code_answer(twin, parse_number("15%"), "valid").outcome is Outcome.RECITED
    assert code_answer(twin, parse_number("18/67"), "valid").outcome is Outcome.CORRECT
    assert code_answer(twin, parse_number("27%"), "valid").outcome is Outcome.CORRECT
    assert code_answer(twin, parse_number("6.7%"), "misconception").outcome is Outcome.NAMED_WRONG


def test_recited_only_on_twins():
    obs = code_answer(flagship(), parse_number("18/67"), "valid")
    assert obs.outcome is Outcome.OTHER_WRONG


def test_abstain():
    obs = abstain("transcription_failure")
    assert obs.outcome is Outcome.ABSTAIN
    assert obs.abstain_reason == "transcription_failure"
    with pytest.raises(ValueError):
        abstain("bored")
