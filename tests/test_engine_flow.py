"""Likelihood loading, labels, stopping and the interview loop (spec/02 §3–5)."""

import random
from fractions import Fraction

import pytest
import yaml

from engine.coding import Observation, Outcome
from engine.interview import Interview
from engine.labels import Label, label_for, should_stop
from engine.likelihoods import DEFAULT_PATH, LikelihoodError, load_likelihoods


# --- Likelihood tables -----------------------------------------------------


def test_tables_load_exactly_and_are_versioned():
    lk = load_likelihoods()
    assert lk.version == 1
    assert lk.prior == {"S": Fraction(2, 5), "M": Fraction(3, 10), "G": Fraction(3, 10)}
    assert lk.first(Outcome.CORRECT) == {
        "S": Fraction(17, 20),
        "M": Fraction(3, 20),
        "G": Fraction(1, 5),
    }
    assert lk.twin(Outcome.CORRECT, Outcome.RECITED)["G"] == Fraction(11, 20)


def test_every_table_sums_to_one_per_class():
    lk = load_likelihoods()
    tables = [lk.first_table()] + [lk.twin_table(o) for o in lk.twin_firsts]
    for table in tables:
        for cls in lk.classes:
            assert sum(row[cls] for row in table.values()) == 1


def test_recited_only_exists_after_correct():
    lk = load_likelihoods()
    assert Outcome.RECITED in lk.twin_table(Outcome.CORRECT)
    for first in (Outcome.NAMED_WRONG, Outcome.OTHER_WRONG, Outcome.VAGUE):
        assert Outcome.RECITED not in lk.twin_table(first)


def test_bad_table_is_rejected(tmp_path):
    data = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    data["first_answer"]["vague"]["S"] = "0.09"  # S column now sums to 1.01
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(LikelihoodError):
        load_likelihoods(path)


# --- Labels and stopping ---------------------------------------------------


def post(s, m, g):
    return {"S": Fraction(s), "M": Fraction(m), "G": Fraction(g)}


def test_label_order_and_thresholds():
    assert label_for(post("0.80", "0.10", "0.10"), 2) is Label.SUPPORTS
    assert label_for(post("0.10", "0.70", "0.20"), 2) is Label.MISCONCEPTION
    assert label_for(post("0.10", "0.30", "0.60"), 2) is Label.NOT_SHOWN
    assert label_for(post("0.50", "0.25", "0.25"), 2) is Label.MORE_EVIDENCE
    assert label_for(post("0.95", "0.03", "0.02"), 1) is Label.MORE_EVIDENCE


def test_label_text():
    assert Label.SUPPORTS.value == "Evidence supports understanding"
    assert Label.MISCONCEPTION.value == "Misconception detected"
    assert Label.NOT_SHOWN.value == "Understanding not shown"
    assert Label.MORE_EVIDENCE.value == "More evidence needed"


def test_stopping():
    assert should_stop(Label.SUPPORTS, 2)
    assert not should_stop(Label.MORE_EVIDENCE, 3)
    assert should_stop(Label.MORE_EVIDENCE, 4)


# --- Interview loop --------------------------------------------------------


def obs(outcome, misconception=None):
    return Observation(outcome=outcome, misconception=misconception)


def test_interview_flagship_correct_then_twin_correct():
    iv = Interview(rng=random.Random("test"), demo=True)
    q1 = iv.next_question()
    assert (q1.kind, q1.puzzle.answer) == ("new", Fraction(2, 13))
    iv.record(obs(Outcome.CORRECT))
    q2 = iv.next_question()
    assert (q2.kind, q2.puzzle.answer) == ("twin", Fraction(18, 67))
    iv.record(obs(Outcome.CORRECT))
    assert iv.finished
    assert iv.label is Label.SUPPORTS
    assert float(iv.posterior["S"]) == pytest.approx(0.944, abs=0.002)


def test_interview_recited_twin():
    iv = Interview(rng=random.Random("test"), demo=True)
    iv.next_question()
    iv.record(obs(Outcome.CORRECT))
    iv.next_question()
    iv.record(obs(Outcome.RECITED))
    assert iv.finished and iv.label is Label.NOT_SHOWN


def test_interview_misconception_is_named():
    iv = Interview(rng=random.Random("test"), demo=True)
    iv.next_question()
    iv.record(obs(Outcome.NAMED_WRONG, "transposed_conditional"))
    assert not iv.finished  # one answer: no label yet
    assert iv.next_question().kind == "twin"
    iv.record(obs(Outcome.NAMED_WRONG, "transposed_conditional"))
    assert iv.finished
    assert iv.label is Label.MISCONCEPTION
    assert iv.misconception == "transposed_conditional"


def test_interview_other_wrong_moves_to_new_template():
    iv = Interview(rng=random.Random("test"), demo=True)
    iv.next_question()
    iv.record(obs(Outcome.OTHER_WRONG))
    q2 = iv.next_question()
    assert (q2.kind, q2.puzzle.template_id) == ("new", "T2")
    # The new puzzle's first answer uses the first-answer table again.
    iv.record(obs(Outcome.CORRECT))
    assert iv.next_question().kind == "twin"


def test_abstain_does_not_update_or_count():
    iv = Interview(rng=random.Random("test"), demo=True)
    q1 = iv.next_question()
    before = dict(iv.posterior)
    iv.record(Observation(outcome=Outcome.ABSTAIN, abstain_reason="empty_audio"))
    assert iv.posterior == before
    assert iv.answers == 0
    assert iv.next_question() is q1  # same question is asked again


def test_interview_stops_after_four_questions():
    # Mixed evidence never reaches a threshold, so the 4-question cap stops it.
    iv = Interview(rng=random.Random("test"))
    sequence = [Outcome.CORRECT, Outcome.NAMED_WRONG, Outcome.CORRECT, Outcome.NAMED_WRONG]
    kinds = []
    for outcome in sequence:
        assert not iv.finished
        kinds.append(iv.next_question().kind)
        iv.record(obs(outcome))
    assert kinds == ["new", "twin", "new", "twin"]
    assert iv.finished
    assert iv.label is Label.MORE_EVIDENCE
    assert iv.next_question() is None


def test_two_other_wrong_answers_stop_early():
    iv = Interview(rng=random.Random("test"))
    for _ in range(2):
        iv.next_question()
        iv.record(obs(Outcome.OTHER_WRONG))
    assert iv.finished and iv.label is Label.NOT_SHOWN


def test_recited_after_wrong_first_uses_other_wrong_row():
    # The twin table has no "recited" column after a wrong first answer.
    iv_a = Interview(rng=random.Random("x"), demo=True)
    iv_b = Interview(rng=random.Random("x"), demo=True)
    for iv, second in ((iv_a, Outcome.RECITED), (iv_b, Outcome.OTHER_WRONG)):
        iv.next_question()
        iv.record(obs(Outcome.VAGUE))
        assert iv.next_question().kind == "twin"
        iv.record(obs(second))
    assert iv_a.posterior == iv_b.posterior
