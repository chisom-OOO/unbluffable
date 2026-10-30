import csv
from fractions import Fraction

import pytest

from forge.data import load_csv, number, stored_answer
from forge.errors import Reject


def test_loader_filters_locked_empty_images_and_duplicate_statements(tmp_path):
    path = tmp_path / "invented.csv"
    rows = [
        {"question_id": "a", "statement": "Invented question.", "solution": "The answer is 3.", "topics": '["Probability", "Expected Value"]'},
        {"question_id": "b", "statement": "Invented question.", "solution": "3"},
        {"question_id": "c", "statement": "Locked example", "solution": "2", "locked": "true"},
        {"question_id": "d", "statement": "", "solution": "2"},
        {"question_id": "e", "statement": "See ![diagram](diagram.png)", "solution": "2"},
        {"question_id": "f", "statement": "Another invented question", "solution": "2", "images": "1"},
    ]
    rows.extend({"question_id": "locked-" + str(i), "statement": "Unused invented item", "solution": "2",
                 "topics": '["Probability", "Expected Value"]', "locked": "true"} for i in range(4))
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    questions, counts = load_csv(path)
    assert len(questions) == 1 and questions[0].question_id == "a"
    assert questions[0].topics == ("probability", "expected value")
    assert counts.per_topic["probability"]["kept"] == 1
    assert counts == {"rows": 10, "kept": 1, "duplicate": 1, "locked": 5, "empty": 1, "image": 2}


@pytest.mark.parametrize("text,expected", [("18/67", Fraction(18, 67)), ("25%", Fraction(1, 4)),
    (r"\frac{2}{13}", Fraction(2, 13)), ("0.125", Fraction(1, 8)), ("1e-3", Fraction(1, 1000)),
    ("1,024", Fraction(1024)), ("-3/7", Fraction(-3, 7))])
def test_numeric_answers_are_exact(text, expected):
    assert number(text) == expected


@pytest.mark.parametrize("text", ["sqrt(2)", "2 or 3", "1/0", "nan", "True"])
def test_numeric_parser_abstains_from_unsupported_answers(text):
    with pytest.raises(Reject):
        number(text)


def test_extracted_answer_requires_a_real_quote_and_stated_decimal_tolerance():
    solution = "The result is 0.33, with tolerance 0.01."
    data = {"answer": "0.33", "quote": solution, "tolerance": "0.01", "tolerance_quote": "tolerance 0.01"}
    answer = stored_answer(data, solution)
    assert answer.value == Fraction(33, 100) and answer.tolerance == Fraction(1, 100)
    for change in [{"quote": "invented"}, {"answer": "0.5"}]:
        with pytest.raises(Reject):
            stored_answer({**data, **change}, solution)


@pytest.mark.parametrize("text", ["1e10000000", "9" * 600])
def test_huge_numeric_literals_fail_before_allocating_large_integers(text):
    with pytest.raises(Reject):
        number(text)


def test_stated_decimal_tolerance_is_distinguished_from_implied():
    solution = "The final value is 0.33."
    answer = stored_answer({"answer": "0.33", "quote": solution, "tolerance": "0", "tolerance_quote": "none"}, solution)
    assert answer.tolerance == Fraction(1, 200) and answer.tolerance_source == "implied"
