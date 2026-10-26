"""Pinned tests from spec/02 §6 (posteriors and labels) and §4 (selection table).

Tolerance ±0.002 throughout, as the spec requires.
"""

import pytest

from engine.coding import Outcome
from engine.labels import Label, label_for
from engine.likelihoods import load_likelihoods
from engine.posterior import update
from engine.selection import information_gain_per_minute, new_puzzle_table

TOL = 0.002

C, R, N, O, V = (
    Outcome.CORRECT,
    Outcome.RECITED,
    Outcome.NAMED_WRONG,
    Outcome.OTHER_WRONG,
    Outcome.VAGUE,
)


@pytest.fixture(scope="module")
def lk():
    return load_likelihoods()


def posterior_after(lk, first, twin=None):
    post = update(lk.prior, lk.first(first))
    if twin is not None:
        post = update(post, lk.twin(first, twin))
    return post


# (first, twin, S, M, G, label after the sequence; None = fewer than 2 answers)
PINNED = [
    (C, C, 0.944, 0.028, 0.028, Label.SUPPORTS),
    (C, R, 0.058, 0.382, 0.560, Label.NOT_SHOWN),
    (N, None, 0.043, 0.745, 0.213, None),
    (N, N, 0.003, 0.910, 0.087, Label.MISCONCEPTION),
    (V, None, 0.211, 0.197, 0.592, None),
    (C, None, 0.764, 0.101, 0.135, None),
]


@pytest.mark.parametrize("first, twin, s, m, g, label", PINNED)
def test_pinned_posteriors(lk, first, twin, s, m, g, label):
    post = posterior_after(lk, first, twin)
    assert float(post["S"]) == pytest.approx(s, abs=TOL)
    assert float(post["M"]) == pytest.approx(m, abs=TOL)
    assert float(post["G"]) == pytest.approx(g, abs=TOL)
    assert sum(post.values()) == 1  # exact


@pytest.mark.parametrize("first, twin, s, m, g, label", PINNED)
def test_pinned_labels(lk, first, twin, s, m, g, label):
    post = posterior_after(lk, first, twin)
    n_answers = 1 if twin is None else 2
    if label is None:
        # Labels apply only after >= 2 answers.
        assert label_for(post, n_answers) is Label.MORE_EVIDENCE
    else:
        assert label_for(post, n_answers) is label


# §4: (first answer, twin bits/min, new puzzle bits/min, engine asks)
SELECTION = [
    (C, 0.389, 0.170, "twin"),
    (N, 0.207, 0.110, "twin"),
    (V, 0.242, 0.185, "twin"),
    (O, 0.104, 0.129, "new"),
]


@pytest.mark.parametrize("first, twin_rate, new_rate, asks", SELECTION)
def test_selection_table(lk, first, twin_rate, new_rate, asks):
    from engine.selection import choose_next

    post = posterior_after(lk, first)
    got_twin = information_gain_per_minute(post, lk.twin_table(first), minutes=1)
    got_new = information_gain_per_minute(post, new_puzzle_table(lk), minutes=2)
    assert got_twin == pytest.approx(twin_rate, abs=TOL)
    assert got_new == pytest.approx(new_rate, abs=TOL)

    choice = choose_next(
        post,
        lk,
        twin_after=first,
        unused_templates=["T2", "T3"],
    )
    assert choice.kind == asks
    if asks == "new":
        assert choice.template_id == "T2"  # tie order: twin, T1, T2, T3


def test_new_puzzle_rate_at_prior(lk):
    rate = information_gain_per_minute(lk.prior, new_puzzle_table(lk), minutes=2)
    assert rate == pytest.approx(0.249, abs=TOL)


def test_first_question_is_t1_by_tie_order(lk):
    from engine.selection import choose_next

    choice = choose_next(lk.prior, lk, twin_after=None, unused_templates=["T1", "T2", "T3"])
    assert (choice.kind, choice.template_id) == ("new", "T1")
