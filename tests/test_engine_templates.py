"""Templates T1–T3 and the generator (spec/02 §1)."""

import random
from fractions import Fraction

import pytest

from engine.generator import collisions, generate, make_twin, passes_filters
from engine.templates import TEMPLATES, flagship, flagship_twin

PP = Fraction(1, 100)


def pct(x):
    return Fraction(x) / 100


# --- Flagship and twin -----------------------------------------------------


def test_flagship_answer_and_counts():
    puz = flagship()
    assert puz.template_id == "T1"
    assert puz.answer == Fraction(2, 13)
    assert puz.population == 2000
    assert puz.counts == {
        "population": 2000,
        "fraud": 20,
        "fraud_flagged": 18,
        "genuine": 1980,
        "genuine_flagged": 99,
    }


def test_flagship_named_wrong_values():
    values = {nv.key: nv.value for nv in flagship().named_values}
    assert values == {
        "detection_rate": pct(90),
        "one_minus_false_alarm": pct(95),
        "false_alarm_rate": pct(5),
        "flag_rate": Fraction(585, 10000),
    }
    misconceptions = {nv.key: nv.misconception for nv in flagship().named_values}
    assert misconceptions["detection_rate"] == "transposed_conditional"


def test_flagship_twin():
    twin = flagship_twin()
    assert twin.answer == Fraction(18, 67)
    assert twin.params["p"] == pct(2)
    assert twin.recited == Fraction(2, 13)
    assert twin.counts["fraud_flagged"] == 36
    assert twin.counts["genuine_flagged"] == 98
    flag_rate = {nv.key: nv.value for nv in twin.named_values}["flag_rate"]
    assert flag_rate == Fraction(67, 1000)  # P(+) = 6.7%


def test_flagship_accuracy_is_not_detection_rate():
    # 02 §1: overall accuracy is 94.95%; 90% is the detection rate.
    p = flagship().params
    accuracy = p["p"] * p["s"] + (1 - p["p"]) * (1 - p["f"])
    assert accuracy == Fraction(9495, 10000)


def test_flagship_and_twin_pass_filters():
    assert passes_filters(flagship())
    assert passes_filters(flagship_twin())


# --- Template formulas -----------------------------------------------------


def test_t2_formula_and_wrong_values():
    puz = TEMPLATES["T2"].build({"a": pct(60), "dA": pct(2), "dB": pct(5)})
    # 0.6*0.02 / (0.6*0.02 + 0.4*0.05) = 0.012 / 0.032 = 3/8
    assert puz.answer == Fraction(3, 8)
    values = {nv.key: nv.value for nv in puz.named_values}
    assert values == {
        "ignores_shares": Fraction(2, 7),
        "share_only": pct(60),
        "defect_rate_a": pct(2),
    }
    assert puz.counts == {
        "population": 1000,
        "from_a": 600,
        "defective_a": 12,
        "from_b": 400,
        "defective_b": 20,
    }


def test_t3_formula_and_wrong_values():
    puz = TEMPLATES["T3"].build({"q": pct(20), "b": Fraction(4, 5), "k": 3})
    lik = Fraction(64, 125)
    expected = Fraction(1, 5) * lik / (Fraction(1, 5) * lik + Fraction(4, 5) * Fraction(1, 8))
    assert puz.answer == expected
    values = {nv.key: nv.value for nv in puz.named_values}
    assert values == {
        "prior_only": pct(20),
        "ignores_prior": lik / (lik + Fraction(1, 8)),
        "likelihood_only": lik,
    }
    for name, count in puz.counts.items():
        assert isinstance(count, int), name


# --- Collision filter ------------------------------------------------------


def test_collision_filter_rejects_answer_near_named_wrong():
    # With a = 50% the answer equals dA / (dA + dB) exactly.
    puz = TEMPLATES["T2"].build({"a": pct(50), "dA": pct(2), "dB": pct(5)})
    assert "ignores_shares" in collisions(puz)
    assert not passes_filters(puz)


def test_collision_filter_boundary_is_two_points():
    # T3 with q = 50%: answer == b^k/(b^k + 0.5^k), the "ignores prior" value.
    puz = TEMPLATES["T3"].build({"q": pct(50), "b": Fraction(3, 4), "k": 2})
    assert "ignores_prior" in collisions(puz)


def test_twin_collision_with_recited_value_is_rejected():
    # Changing f from 5% to 4.5% moves the answer to 16.8%: within 2pp of the
    # original answer ("Recited") and short of the 10pp twin shift.
    original = flagship()
    near = TEMPLATES["T1"].build(
        {"p": pct(1), "s": pct(90), "f": pct(Fraction(9, 2))}, original=original
    )
    assert "recited" in collisions(near)
    assert "twin_shift" in collisions(near)
    assert not passes_filters(near)


@pytest.mark.parametrize("template_id", ["T1", "T2", "T3"])
@pytest.mark.parametrize("seed", range(40))
def test_generated_puzzles_satisfy_all_rules(template_id, seed):
    rng = random.Random(f"{template_id}-{seed}")
    puz = generate(template_id, rng)
    assert puz.template_id == template_id
    _assert_whole_counts(puz)
    for nv in puz.named_values:
        assert abs(puz.answer - nv.value) > 2 * PP, nv.key

    twin = make_twin(puz, rng)
    assert twin.template_id == template_id
    assert twin.recited == puz.answer
    changed = [k for k in puz.params if puz.params[k] != twin.params[k]]
    assert len(changed) == 1
    assert abs(twin.answer - puz.answer) >= 10 * PP
    _assert_whole_counts(twin)
    for nv in twin.named_values:
        assert abs(twin.answer - nv.value) > 2 * PP, nv.key
    assert abs(twin.answer - twin.recited) > 2 * PP


def test_generator_is_deterministic_for_a_seed():
    a = generate("T1", random.Random("demo"))
    b = generate("T1", random.Random("demo"))
    assert a.params == b.params and a.population == b.population


def _assert_whole_counts(puz):
    for name, count in puz.counts.items():
        assert isinstance(count, int) and count >= 0, name
    assert puz.counts["population"] == puz.population
