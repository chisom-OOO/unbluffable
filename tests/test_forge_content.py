"""Invented content-quality fixtures, with no bank/pilot/content reads."""
import json
from fractions import Fraction

import pytest

from forge.errors import Reject
from forge.pipeline import Pipeline
from forge.verify import instances, points_for
from forge_fakes import FakeModels, FakeSandbox, SIM, WRONG_ONE, draft, question, counts


@pytest.mark.parametrize("value,friendly", [
    ("42", True), ("-7", True), ("18/67", True), ("99/10000", True),
    ("3/200", True), ("1/101", False), ("1/128", False), ("11/800", False),
])
def test_friendliness_uses_exact_values_not_rounded_approximations(value, friendly):
    from forge.content import mental_arithmetic
    score = mental_arithmetic(Fraction(value))
    assert score["interview_friendly"] is friendly
    assert (score["interview_friendly_score"] > 0) is friendly


class MixedAnswers(FakeSandbox):
    def __init__(self, friendly_count):
        super().__init__()
        self.friendly_count = friendly_count
    def run(self, code, mode, params, **kwargs):
        answer = Fraction(2) if int(params["n"]) <= self.friendly_count else Fraction(1, 101)
        if mode == "sample":
            return {"mean": str(answer), "se": .01, "trials": 1000, "draws": 1000}
        if code == draft()["solver"]:
            return {"answer": str(answer), "steps": [{"name": "half", "value": str(answer)}]}
        return {"answer": "4" if code == WRONG_ONE else "5", "steps": []}


@pytest.mark.parametrize("friendly_count,accepted", [(9, False), (10, True)])
def test_ten_friendly_instances_is_a_hard_gate(friendly_count, accepted):
    points = [{"n": str(i)} for i in range(1, 31)]
    if accepted:
        rows, _ = instances(draft(), points, SIM, MixedAnswers(friendly_count), Fraction(0), 1000)
        assert len(rows) >= 20 and sum(row["interview_friendly"] for row in rows) >= 10
    else:
        with pytest.raises(Reject) as error:
            instances(draft(), points, SIM, MixedAnswers(friendly_count), Fraction(0), 1000)
        assert error.value.stage == "interview_friendly"


def test_sampling_continues_after_twenty_until_ten_friendly_survive():
    points = [{"n": str(i)} for i in range(21, 41)] + [{"n": str(i)} for i in range(1, 11)]
    rows, _ = instances(draft(), points, SIM, MixedAnswers(10), Fraction(0), 1000)
    assert len(rows) == 30 and sum(row["interview_friendly"] for row in rows) == 10


def test_wrong_values_are_unique_and_keep_all_misconceptions():
    variant = draft()
    variant["wrong"][1]["code"] = WRONG_ONE
    points, _ = points_for(variant["parameters"])
    rows, _ = instances(variant, points, SIM, FakeSandbox(), Fraction(0), 1000)
    for row in rows:
        assert row["wrong"] == [{"value": row["params"]["n"],
                                "misconceptions": ["ignores_probability", "uses_three_cases"]}]
        assert len(row["separation"]["by_misconception"]) == 2
        assert row["separation"]["min_wrong_pair_gap"] == "0"


@pytest.mark.parametrize("text,expected", [
    ("A fair coin pays 25% of 1.5 credits.", "A fair coin pays twenty-five percent of one point five credits."),
    ("The chance is 2/13. What is 3 + 4?", "The chance is two over thirteen. What is three plus four?"),
    ("At most 1e-3 means x <= 0.001.", "At most one times ten to the power of minus three means x less than or equal to zero point zero zero one."),
])
def test_spoken_text_expands_numbers_and_symbols_without_changing_values(text, expected):
    from forge.content import spoken_text
    assert spoken_text(text) == expected


def setup(tmp_path):
    models = FakeModels(tmp_path / "private")
    pipeline = Pipeline(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json",
                        sandbox=FakeSandbox(), trials=1000)
    return models, pipeline


def test_topic_comes_from_own_content_and_is_restricted_to_bank_vocabulary(tmp_path):
    models, pipeline = setup(tmp_path)
    models.overrides["topic_classification"] = {"topic": "expected value"}
    assert pipeline.run([question()], counts())["accepted_templates"] == 1
    artifact = json.loads(next((tmp_path / "public").glob("*.json")).read_text())
    assert artifact["topic"] == "expected value" and artifact["source_topic"] == "probability"
    assert sum(row["interview_friendly"] for row in artifact["instances"]) >= 10
    assert all(row["spoken_text"] for row in artifact["instances"])
    payload = next(payload for stage, payload in models.calls if stage == "topic_classification")
    assert set(payload) == {"text", "vocabulary"}
    assert question().statement not in str(payload) and "source_topic" not in payload
    assert payload["vocabulary"] == ["expected value", "probability", "statistics"]


def test_out_of_vocabulary_topic_cannot_be_exported(tmp_path):
    models, pipeline = setup(tmp_path)
    models.overrides["topic_classification"] = {"topic": "invented unapproved topic"}
    assert pipeline.run([question()], counts())["accepted_templates"] == 0
    assert not list((tmp_path / "public").glob("*.json"))


@pytest.mark.parametrize("bad", [
    r"A coin pays ${n}.", r"A coin pays \frac{{n}}{{2}} credits.",
    "A coin yields 1 * {n} points.", "You see {n} squared observations.",
])
def test_unspoken_wording_gets_one_repair_then_is_rejected(tmp_path, bad):
    models, pipeline = setup(tmp_path)
    models.blueprint["text"] = bad
    models.overrides["author_repair"] = models.blueprint
    assert pipeline.run([question()], counts())["accepted_templates"] == 0
    assert [stage for stage, _ in models.calls].count("author_repair") == 1
    assert not any(stage == "topic_classification" for stage, _ in models.calls)


def test_wording_repair_can_pass_without_bypassing_existing_checks(tmp_path):
    models, pipeline = setup(tmp_path)
    models.blueprint["text"] = "A fair coin pays ${n}."
    models.overrides["author_repair"] = draft()
    report = pipeline.run([question()], counts())
    assert report["accepted_after_repair"] == 1
    assert report["stages"]["blind_checker"]["passed"] == report["stages"]["monte_carlo"]["passed"] == 1


def test_bad_optional_part_two_wording_cannot_be_silently_discarded(tmp_path):
    models, pipeline = setup(tmp_path)
    models.blueprint = draft(part2=True)
    models.blueprint["part2"]["text"] = r"A coin pays \alpha {n} with {k} repetitions."
    models.overrides["author_repair"] = models.blueprint
    assert pipeline.run([question()], counts())["accepted_templates"] == 0


def test_no_content_topic_call_for_a_failed_numeric_gate(tmp_path):
    models, pipeline = setup(tmp_path)
    models.overrides["blind_model"] = {"answer": "999"}
    assert pipeline.run([question()], counts())["accepted_templates"] == 0
    assert not any(stage == "topic_classification" for stage, _ in models.calls)


def test_topic_call_uses_checker_once_and_replay_of_finished_item_does_not_repeat_it(tmp_path):
    models, pipeline = setup(tmp_path)
    original = models.call
    author_flags = []
    def call(stage, payload, *args, **kwargs):
        if stage == "topic_classification":
            author_flags.append(kwargs.get("author", False))
            assert args[0]["properties"]["topic"]["enum"] == payload["vocabulary"]
        return original(stage, payload, *args, **kwargs)
    models.call = call
    report = pipeline.run([question()], counts())
    assert report["accepted_templates"] == 1
    assert author_flags == [False]
    pipeline.run([question()], counts())
    assert author_flags == [False]


def test_prompt_requires_explicit_assumptions_and_natural_spoken_english():
    from forge.pipeline import AUTHOR_PROMPT
    for requirement in ("fair coin", "fair die", "without replacement", "No LaTeX",
                        "1 *", "5 squared observations", "10 instances"):
        assert requirement in AUTHOR_PROMPT


def test_spoken_scientific_plus_and_negative_decimal():
    from forge.content import spoken_text
    assert spoken_text("A rate of 1e+3 and a loss of -0.25.") == "A rate of one times ten to the power of three and a loss of minus zero point two five."


def test_empty_clean_vocabulary_cannot_export_a_template(tmp_path):
    from forge.data import LoadCounts
    models, pipeline = setup(tmp_path)
    assert pipeline.run([question()], LoadCounts({"rows": 1}, {}, {}))["accepted_templates"] == 0
    assert not any(stage == "topic_classification" for stage, _ in models.calls)


def test_part_two_is_attached_by_base_parameters_not_result_order(tmp_path):
    models, pipeline = setup(tmp_path)
    models.blueprint = draft(part2=True)
    def verified_part_two(draft, base_points, original, simulator, statements, item):
        return {"passed": True}, [{"params": {**point, "k": "2"}, "answer": point["n"]}
                                 for point in reversed(base_points)]
    pipeline.part2 = verified_part_two
    assert pipeline.run([question()], counts())["accepted_templates"] == 1
    artifact = json.loads(next((tmp_path / "public").glob("*.json")).read_text())
    assert all(row["part2"]["params"]["n"] == row["params"]["n"] for row in artifact["instances"])


def test_duplicate_wrong_methods_equal_to_correct_are_still_dropped():
    variant = draft()
    for method in variant["wrong"]:
        method["code"] = variant["solver"]
    points, _ = points_for(variant["parameters"])
    with pytest.raises(Reject) as error:
        instances(variant, points, SIM, FakeSandbox(), Fraction(0), 1000)
    assert error.value.reason == "fewer_than_twenty_instances"
