"""Spoken number forms (spec/03 number normalisation) read by engine.answers."""

from fractions import Fraction

import pytest

from engine.answers import StatedNumber, committed_number, matches, normalise_numbers, parse_number
from engine.coding import Outcome, code_answer
from engine.templates import flagship


def F(n, d=1):
    return Fraction(n, d)


@pytest.mark.parametrize(
    "spoken, value, form",
    [
        # spec/03 list
        ("two over thirteen", F(2, 13), "fraction"),
        ("two thirteenths", F(2, 13), "fraction"),
        ("fifteen point four percent", F(154, 1000), "percent"),
        ("about fifteen percent", F(15, 100), "percent"),
        ("nought point one five", F(15, 100), "decimal"),
        ("0.15", F(15, 100), "decimal"),
        ("15%", F(15, 100), "percent"),
        # task list
        ("point nine", F(9, 10), "decimal"),
        ("nought point nine", F(9, 10), "decimal"),
        ("ninety-five percent", F(95, 100), "percent"),
        ("five point eight five percent", F(585, 10000), "percent"),
        ("two in thirteen", F(2, 13), "fraction"),
        ("eighteen over a hundred and seventeen", F(18, 117), "fraction"),
        ("fifteen, sixteen percent", F(15, 100), "percent"),  # take the first
        # more shapes
        ("eighteen out of a hundred and seventeen", F(18, 117), "fraction"),
        ("one third", F(1, 3), "fraction"),
        ("Ninety Percent", F(90, 100), "percent"),
        ("fifteen per cent", F(15, 100), "percent"),
        ("zero point one five", F(15, 100), "decimal"),
        ("point oh five", F(5, 100), "decimal"),
        ("15 point 4 percent", F(154, 1000), "percent"),
        ("eighteen over one hundred seventeen", F(18, 117), "fraction"),
        ("thirty-six over a hundred and thirty-four", F(36, 134), "fraction"),
        ("eighteen sixty-sevenths", F(18, 67), "fraction"),
        ("one thousand nine hundred and eighty out of two thousand", F(1980, 2000), "fraction"),
        ("fifteen to sixteen percent", F(15, 100), "percent"),
    ],
)
def test_spoken_forms(spoken, value, form):
    assert parse_number(spoken) == StatedNumber(value, form)


def test_flagship_spoken_answers_match():
    for spoken in ("two thirteenths", "about fifteen percent", "nought point one five",
                   "eighteen over a hundred and seventeen", "fifteen, sixteen percent"):
        assert matches(parse_number(spoken), F(2, 13)), spoken


def test_bare_spoken_counts_are_not_answers():
    assert parse_number("out of two thousand transactions") is None
    assert parse_number("there are a hundred and seventeen flagged") is None


def test_words_that_are_not_numbers_survive():
    text = "At this point I trust a third party."
    assert normalise_numbers(text) == text
    assert parse_number(text) is None


def test_thousands_separators_and_lists_are_not_ranges():
    assert normalise_numbers("out of 2,000, 99 percent") == "out of 2,000, 99 percent"


# --- Committed claims in spoken form ---------------------------------------


@pytest.mark.parametrize(
    "text, value, form",
    [
        ("So the answer is two thirteenths.", F(2, 13), "fraction"),
        ("So it's about fifteen, sixteen percent.", F(15, 100), "percent"),
        ("So it's roughly nought point one five.", F(15, 100), "decimal"),
        ("So the probability is eighteen over a hundred and seventeen.", F(18, 117), "fraction"),
        ("So if a transaction gets flagged, it's about ninety percent likely to be fraud.",
         F(90, 100), "percent"),
    ],
)
def test_spoken_committed_claims(text, value, form):
    assert committed_number(text) == StatedNumber(value, form)


@pytest.mark.parametrize(
    "text",
    [
        "The detector catches ninety percent of fraud.",
        "The false alarm rate is five percent.",
        "If it were ninety percent, that would be odd.",
        "So it's maybe point nine, no wait.",
    ],
)
def test_spoken_non_claims(text):
    assert committed_number(text) is None


def test_spoken_named_wrong_is_coded():
    stated = committed_number("So the answer is five point eight five percent.")
    obs = code_answer(flagship(), stated, "misconception")
    assert obs.outcome is Outcome.NAMED_WRONG
    assert "flag_rate" in obs.matched
