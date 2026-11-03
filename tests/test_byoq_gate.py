"""Bring your own question (decision log 38): the verification gate, offline. Model outputs
are the synthetic ones in byoq_fakes; all code runs in forge's real Sandbox."""

from fractions import Fraction

import pytest

from engine.bank import parse_template
from forge.byoq import MIN_VARIANTS, GateFailure, Plan, check_question
from forge.sandbox import Sandbox
from byoq_fakes import (COLLIDES, DISAGREES, LOOPS, ONE_DRAW, QUESTION, WITH_REPLACEMENT, FakeCall,
                        outputs)

TWO = Plan.two_models()
ONE = Plan.one_model("open_weights")


def gate(table, plan=TWO, stated=None, sandbox=None, text=QUESTION):
    call = FakeCall(table)
    return check_question(text, stated, "Discrete probability", call, plan, sandbox=sandbox), call


def test_agreeing_solvers_pass_on_the_original_and_ten_or_more_variants():
    raw, call = gate(outputs())
    template = parse_template(raw)  # the runtime contract for forge templates
    first = template.instances[0]
    assert first.text == QUESTION and first.answer == Fraction(3, 28)
    assert raw["verification"]["solver"]["variants_checked"] >= MIN_VARIANTS
    assert len(template.instances) == raw["verification"]["solver"]["variants_checked"] + 1
    for inst in template.instances:
        r, b = inst.params["red"], inst.params["blue"]
        assert inst.answer == Fraction(r * (r - 1), (r + b) * (r + b - 1))
        assert all(nv.value != inst.answer for nv in inst.wrong)
    # The author parameterises; the checker model writes the second solver without the author's code.
    assert [(stage, role) for stage, role, _ in call.calls] == [
        ("parameterise", "author"), ("check", "checker"), ("wrong_methods", "author")]
    assert "solver" not in call.calls[1][2]


def test_disagreeing_solvers_are_rejected():
    with pytest.raises(GateFailure) as failure:
        gate(outputs(check=DISAGREES))
    assert failure.value.reason == "checks_disagree"


def test_a_mismatch_with_the_stated_answer_is_rejected():
    with pytest.raises(GateFailure) as failure:
        gate(outputs(), stated="3/32")
    assert failure.value.reason == "stated_answer_mismatch"


def test_a_matching_stated_answer_passes_in_any_exact_form():
    for stated in ("3/28", " 3 / 28 "):
        raw, _ = gate(outputs(), stated=stated)
        assert raw["verification"]["stated_answer_matched"] is True
    raw, _ = gate(outputs(), stated="none")
    assert raw["verification"]["stated_answer_matched"] is False


def test_an_unreadable_stated_answer_is_rejected():
    with pytest.raises(GateFailure) as failure:
        gate(outputs(), stated="about a tenth")
    assert failure.value.reason == "stated_answer_unreadable"


def test_a_sandbox_timeout_means_rejection():
    with pytest.raises(GateFailure) as failure:
        gate(outputs(check=LOOPS), sandbox=Sandbox(timeout_s=1, memory_mb=128))
    # Either way the question is rejected; on a busy CI runner the killed process can report as a failed exit.
    assert failure.value.reason in {"sandbox_timeout", "sandbox_process_limit_or_failure"}


def test_one_model_uses_a_separately_written_simulation():
    raw, call = gate(outputs(), plan=ONE)
    assert raw["verification"]["second_check"] == "simulation"
    assert [stage for stage, _, _ in call.calls] == ["parameterise", "simulation", "wrong_methods"]
    assert all(role == "author" for _, role, _ in call.calls)
    assert "solver" not in call.calls[1][2]


def test_one_model_rejects_a_question_it_cannot_enumerate():
    with pytest.raises(GateFailure) as failure:
        gate(outputs(enumerable=False), plan=ONE)
    assert failure.value.reason == "not_enumerable"


def test_one_model_rejects_a_disagreeing_simulation():
    with pytest.raises(GateFailure):
        gate(outputs(simulation=DISAGREES), plan=ONE)


def test_wrong_methods_are_kept_only_with_distinct_values():
    wrong = [{"misconception": "with_replacement", "code": WITH_REPLACEMENT},
             {"misconception": "with_replacement_again", "code": WITH_REPLACEMENT},
             {"misconception": "collides_once", "code": COLLIDES},
             {"misconception": "one_draw_only", "code": ONE_DRAW}]
    raw, _ = gate(outputs(wrong=wrong))
    names = {w["misconception"] for inst in raw["instances"] for w in inst["wrong"]}
    # At most three are tried; the duplicate and the one equal to the right answer are dropped.
    assert names == {"with_replacement"}
    raw, _ = gate(outputs(wrong=[wrong[0], wrong[3]]))
    assert {w["misconception"] for w in raw["instances"][0]["wrong"]} == {"with_replacement", "one_draw_only"}


def test_a_failing_wrong_method_is_dropped_not_the_question():
    raw, _ = gate(outputs(wrong=[{"misconception": "loops", "code": LOOPS},
                                 {"misconception": "one_draw_only", "code": ONE_DRAW}]),
                  sandbox=Sandbox(timeout_s=2, memory_mb=128))
    assert {w["misconception"] for w in raw["instances"][0]["wrong"]} == {"one_draw_only"}


def test_a_template_that_changes_the_question_numbers_is_rejected():
    changed = outputs(parameters=[{"name": "red", "minimum": "2", "maximum": "9", "step": "1", "original": "4"},
                                  {"name": "blue", "minimum": "2", "maximum": "9", "step": "1", "original": "5"}])
    with pytest.raises(GateFailure) as failure:
        gate(changed)
    assert failure.value.reason == "template_changes_numbers"


def test_too_few_variants_are_rejected():
    narrow = outputs(parameters=[{"name": "red", "minimum": "2", "maximum": "4", "step": "1", "original": "3"},
                                 {"name": "blue", "minimum": "5", "maximum": "7", "step": "1", "original": "5"}])
    with pytest.raises(GateFailure) as failure:
        gate(narrow)
    assert failure.value.reason == "too_few_variants"


def test_a_non_numeric_answer_is_rejected():
    listing = outputs(check="def solve(params):\n    return {\"answer\": [1, 2]}\n")
    with pytest.raises(GateFailure):
        gate(listing)


def test_model_code_never_runs_in_this_process(monkeypatch):
    """Every solver and wrong method goes through Sandbox.run_batch (a subprocess)."""
    ran = []
    real = Sandbox.run_batch

    def spy(self, code, params):
        ran.append(code)
        return real(self, code, params)

    monkeypatch.setattr(Sandbox, "run_batch", spy)
    monkeypatch.setattr("builtins.exec", lambda *a, **k: pytest.fail("exec in the web process"))
    gate(outputs())
    assert len(ran) == 2 + 3
