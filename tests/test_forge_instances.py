"""Invented exact arithmetic fixtures for the twenty-instance gate."""
from fractions import Fraction

import pytest

from forge.errors import Reject
from forge.verify import instances, points_for
from forge_fakes import FakeSandbox, SIM, WRONG_ONE, draft


def test_points_are_distinct_spread_and_include_valid_edges():
    parameters = [{"name": "n", "minimum": "1", "maximum": "101", "step": "1", "original": "4"}]
    points, original = points_for(parameters)
    first = sorted(int(row["n"]) for row in points[:20])
    assert len(first) == len(set(first)) == 20
    assert first[0] == 1 and first[-1] == 101
    assert max(b - a for a, b in zip(first, first[1:])) <= 8
    assert original in points[:20]
    assert points_for(parameters)[0] == points


def test_multidimensional_edges_and_interior_are_spread():
    parameters = [
        {"name": name, "minimum": "1", "maximum": "101", "step": "1", "original": "51"}
        for name in ("n", "k")
    ]
    points, _ = points_for(parameters)
    first = points[:20]
    assert len({tuple(sorted(row.items())) for row in first}) == 20
    for name in ("n", "k"):
        assert {"1", "101"} <= {row[name] for row in first}
        assert any(20 <= int(row[name]) <= 40 for row in first)
        assert any(60 <= int(row[name]) <= 80 for row in first)


def test_nineteen_possible_points_fail_twenty_instance_gate():
    parameters = [{"name": "n", "minimum": "1", "maximum": "19", "step": "1", "original": "4"}]
    with pytest.raises(Reject) as error:
        points_for(parameters)
    assert error.value.reason == "fewer_than_twenty_instances"


def test_each_instance_reports_exact_misconception_and_pairwise_gaps():
    variant = draft()
    points, _ = points_for(variant["parameters"])
    rows, verification = instances(variant, points, SIM, FakeSandbox(), Fraction(0), 1000)
    assert len(rows) == 20 and verification["point_count"] == 20
    for row in rows:
        answer = Fraction(row["answer"])
        n = Fraction(row["params"]["n"])
        assert {name for wrong in row["wrong"] for name in wrong["misconceptions"]} == {
            "ignores_probability", "uses_three_cases"}
        gaps = {gap["misconception"]: gap for gap in row["separation"]["by_misconception"]}
        assert gaps["ignores_probability"]["absolute_gap"] == str(n / 2)
        assert gaps["ignores_probability"]["relative_gap"] == "1"
        assert gaps["uses_three_cases"]["absolute_gap"] == str(n / 6)
        assert gaps["uses_three_cases"]["relative_gap"] == "1/3"
        assert row["separation"]["min_wrong_pair_gap"] == str(2 * n / 3)
        assert all(Fraction(wrong["value"]) != answer for wrong in row["wrong"])


class CollisionSandbox(FakeSandbox):
    def __init__(self, collide):
        super().__init__()
        self.collide = collide

    def run(self, code, mode, params, **kwargs):
        if mode == "solve" and code == WRONG_ONE and self.collide(Fraction(params["n"])):
            return {"answer": str(Fraction(params["n"]) / 2), "steps": []}
        return super().run(code, mode, params, **kwargs)


def test_collision_is_dropped_and_replaced_instead_of_rejecting_template():
    variant = draft()
    points, _ = points_for(variant["parameters"])
    rows, verification = instances(variant, points, SIM, CollisionSandbox(lambda n: n <= 5),
                                   Fraction(0), 1000)
    assert len(rows) == 20
    assert all(Fraction(row["params"]["n"]) > 5 for row in rows)
    assert verification["dropped_collisions"] > 0
    assert len({row["params"]["n"] for row in rows}) == 20


def test_survivors_below_twenty_reject_even_when_raw_grid_is_large():
    variant = draft()
    points, _ = points_for(variant["parameters"])
    with pytest.raises(Reject) as error:
        instances(variant, points, SIM, CollisionSandbox(lambda n: n > 19), Fraction(0), 1000)
    assert error.value.stage == "wrong_methods"
    assert error.value.reason == "fewer_than_twenty_instances"


@pytest.mark.parametrize("answer", [Fraction(0), Fraction(-2)])
def test_zero_and_negative_correct_answers_and_wrong_wrong_collision(answer):
    class ExactSandbox:
        def run(self, code, mode, params, **kwargs):
            if mode == "sample":
                return {"mean": str(answer), "se": .01, "trials": 1000, "draws": 1000}
            value = answer if code == "correct" else answer + 3
            return {"answer": str(value), "steps": [{"name": "value", "value": str(value)}]}
    variant = {"text": "An invented experiment at {n}.", "solver": "correct",
               "step_names": ["value"],
               "wrong": [{"misconception": name, "code": name} for name in ("a", "b", "c")]}
    rows, _ = instances(variant, [{"n": str(i)} for i in range(20)], "sim",
                        ExactSandbox(), Fraction(0), 1000)
    for row in rows:
        assert row["separation"]["min_wrong_pair_gap"] == "0"
        for gap in row["separation"]["by_misconception"]:
            assert gap["absolute_gap"] == "3"
            assert gap["relative_gap"] == (None if not answer else "3/2")


def test_collisions_inside_stated_tolerance_are_also_dropped():
    variant = draft()
    points, _ = points_for(variant["parameters"])
    rows, verification = instances(variant, points, SIM, FakeSandbox(), Fraction(1), 1000)
    assert len(rows) == 20 and verification["dropped_collisions"] > 0
    assert all(abs(Fraction(w["value"]) - Fraction(row["answer"])) > 1
               for row in rows for w in row["wrong"])


def test_duplicate_parameter_rows_do_not_count_towards_twenty():
    variant = draft()
    with pytest.raises(Reject):
        instances(variant, [{"n": "4"}] * 20, SIM, FakeSandbox(), Fraction(0), 1000)
