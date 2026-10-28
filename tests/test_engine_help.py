"""Help load and discount (spec/02 §7; decision log 3a, 3b).

Pinned values from §7 and the sample story (Q1 recovered with H = 5, twin correct).
Tolerance ±0.002 where the spec gives decimals; exact fractions where they are known.
"""

import random
from fractions import Fraction

import pytest

from engine.coding import Observation, Outcome
from engine.help import (
    T1_STEPS,
    discount,
    help_load,
    position,
    step_values,
    strength,
    weight_for,
)
from engine.interview import Interview
from engine.labels import Label
from engine.likelihoods import load_likelihoods
from engine.posterior import update
from engine.templates import flagship, flagship_twin

TOL = 0.002
C, N = Outcome.CORRECT, Outcome.NAMED_WRONG


@pytest.fixture(scope="module")
def lk():
    return load_likelihoods()


def obs(outcome, misconception=None):
    return Observation(outcome=outcome, misconception=misconception)


# --- Solution map, position, strength, help load ----------------------------


def test_t1_solution_map_has_six_steps_in_order():
    assert T1_STEPS == (
        "population",
        "fraud_count",
        "flagged_fraud",
        "flagged_genuine",
        "total_flagged",
        "divide",
    )


def test_t1_step_values_for_the_flagship_out_of_2000():
    assert step_values(flagship(), 2000) == {
        1: Fraction(2000),
        2: Fraction(20),
        3: Fraction(18),
        4: Fraction(99),
        5: Fraction(117),
        6: Fraction(2, 13),
    }


def test_position_is_the_furthest_step_stated_correctly():
    p = flagship()
    assert position(p, stated=[]) == 0
    # Restated givens (90%, 5%) are not map steps.
    assert position(p, stated=[Fraction(9, 10), Fraction(1, 20)]) == 0
    # A population on its own reaches step 1.
    assert position(p, stated=[], population=2000) == 1
    assert position(p, stated=[20, 18], population=2000) == 3
    # Furthest, not contiguous: genuine flagged without the fraud count.
    assert position(p, stated=[99], population=2000) == 4
    # Counts need a population to be checked against.
    assert position(p, stated=[20, 18]) == 0
    # The answer is a ratio and needs no population.
    assert position(p, stated=[Fraction(2, 13)]) == 6
    # Wrong numbers do not move the candidate.
    assert position(p, stated=[19, 100], population=2000) == 1
    # Another round population works too.
    assert position(p, stated=[10, 9], population=1000) == 3


def test_strength_is_steps_given_away():
    assert strength(target=4, at=0) == 4
    assert strength(target=1, at=0) == 1
    assert strength(target=2, at=3) == 0  # behind the candidate: gives nothing away
    assert strength(target=None, at=2) == 0  # a "why?" that points at no step


def test_help_load_for_the_sample_story():
    # Challenge points at no step; nudge targets step 4 and hint step 1, both at position 0.
    assert help_load([(None, 0), (4, 0), (1, 0)]) == 5


def test_step_values_only_cover_t1():
    from engine.generator import generate

    with pytest.raises(NotImplementedError):
        step_values(generate("T2", random.Random("x")), 1000)


# --- Weights and the discounted Correct row ---------------------------------


@pytest.mark.parametrize(
    "h, challenged, w",
    [
        (0, False, Fraction(1)),
        (1, False, Fraction(2, 3)),
        (2, False, Fraction(1, 2)),
        (4, False, Fraction(1, 3)),
        (0, True, Fraction(2, 3)),
        (2, True, Fraction(2, 5)),
        (3, True, Fraction(1, 3)),
        (5, True, Fraction(1, 4)),
    ],
)
def test_weight_for(h, challenged, w):
    assert weight_for(h, challenged=challenged) == w


def test_discount_with_w_1_is_the_row_itself(lk):
    row = lk.first(C)
    assert discount(row, Fraction(1)) == row


def test_discount_mixes_with_a_quarter(lk):
    assert discount(lk.first(C), Fraction(1, 4)) == {
        "S": Fraction(2, 5),
        "M": Fraction(9, 40),
        "G": Fraction(19, 80),
    }


# §7 pinned (prior, one Correct answer): after help, and recovered after a challenge.
PINNED_ONE = [
    (Fraction(2, 3), 0.684, 0.145, 0.171),  # H = 1, or challenge only
    (Fraction(1, 2), 0.633, 0.173, 0.194),  # H = 2
    (Fraction(1, 3), 0.571, 0.206, 0.222),  # H = 4, or challenge + 3 steps
    (Fraction(2, 5), 0.598, 0.192, 0.210),  # challenge + 2 steps
]


@pytest.mark.parametrize("w, s, m, g", PINNED_ONE)
def test_pinned_one_discounted_correct(lk, w, s, m, g):
    post = update(lk.prior, discount(lk.first(C), w))
    assert float(post["S"]) == pytest.approx(s, abs=TOL)
    assert float(post["M"]) == pytest.approx(m, abs=TOL)
    assert float(post["G"]) == pytest.approx(g, abs=TOL)


# --- Interview.record with a weight ----------------------------------------


def test_recovered_h5_then_twin_correct_is_exact():
    iv = Interview(rng=random.Random("test"), demo=True)
    assert iv.next_question().puzzle == flagship()
    iv.record(obs(C), weight=weight_for(5, challenged=True), help_load=5)
    assert iv.next_question().puzzle == flagship_twin()
    iv.record(obs(C))
    assert iv.posterior == {
        "S": Fraction(256, 299),
        "M": Fraction(24, 299),
        "G": Fraction(19, 299),
    }
    assert iv.label is Label.SUPPORTS
    assert iv.finished
    assert not iv.can_escalate  # H = 5 > 1


def test_not_recovered_uses_the_first_wrong_outcome_undiscounted():
    iv = Interview(rng=random.Random("test"), demo=True)
    iv.next_question()
    iv.record(obs(N, "transposed_conditional"), help_load=3)
    iv.next_question()
    iv.record(obs(N, "transposed_conditional"))
    assert float(iv.posterior["S"]) == pytest.approx(0.003, abs=TOL)
    assert float(iv.posterior["M"]) == pytest.approx(0.910, abs=TOL)
    assert float(iv.posterior["G"]) == pytest.approx(0.087, abs=TOL)
    assert iv.label is Label.MISCONCEPTION


def test_weight_applies_to_correct_only():
    iv = Interview(rng=random.Random("test"), demo=True)
    iv.next_question()
    with pytest.raises(ValueError):
        iv.record(obs(N), weight=Fraction(1, 2))
    with pytest.raises(ValueError):
        iv.record(obs(C), weight=Fraction(0))
    with pytest.raises(ValueError):
        iv.record(obs(C), weight=Fraction(3, 2))
    assert iv.answers == 0  # nothing recorded


def test_default_weight_matches_the_undiscounted_flow():
    a = Interview(rng=random.Random("test"), demo=True)
    b = Interview(rng=random.Random("test"), demo=True)
    for iv, kw in ((a, {}), (b, {"weight": Fraction(1)})):
        iv.next_question()
        iv.record(obs(C), **kw)
        iv.next_question()
        iv.record(obs(C), **kw)
    assert a.posterior == b.posterior
    assert float(a.posterior["S"]) == pytest.approx(0.944, abs=TOL)


# --- Escalation gate: H <= 1 on the scored answers -------------------------


@pytest.mark.parametrize("h1, h2, allowed", [(0, 0, True), (1, 0, True), (1, 1, True), (2, 0, False), (0, 2, False)])
def test_escalation_needs_supports_and_light_help(h1, h2, allowed):
    iv = Interview(rng=random.Random("test"), demo=True)
    iv.next_question()
    iv.record(obs(C), weight=weight_for(h1), help_load=h1)
    iv.next_question()
    iv.record(obs(C), weight=weight_for(h2), help_load=h2)
    assert iv.label is Label.SUPPORTS
    assert iv.can_escalate is allowed


def test_no_escalation_without_supports():
    iv = Interview(rng=random.Random("test"), demo=True)
    iv.next_question()
    iv.record(obs(N, "transposed_conditional"))
    iv.next_question()
    iv.record(obs(N, "transposed_conditional"))
    assert not iv.can_escalate
