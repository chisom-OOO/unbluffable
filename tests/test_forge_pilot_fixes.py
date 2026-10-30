from forge_fakes import counts
"""Invented pilot regressions; no bank, content or recorded pilot reads."""
import csv
from dataclasses import replace
from fractions import Fraction

import pytest

from forge.data import load_csv, number, stored_answer
from forge.errors import Reject
from forge.pipeline import Pipeline
from forge_fakes import FakeModels, FakeSandbox, SOLVER, SIM, draft, question


@pytest.mark.parametrize("raw,expected,tolerance", [
    ("0.125", "1/8", "1/2000"), ("12.50%", "1/8", "1/20000"),
    ("1.20e-3", "3/2500", "1/200000"), ("25%", "1/4", "0"),
    ("42", "42", "0"), (r"\tfrac{2}{13}", "2/13", "0"),
])
def test_implied_precision_is_exact_and_recorded(raw, expected, tolerance):
    solution = "An invented final result: " + raw
    answer = stored_answer({"answer": raw, "quote": solution, "tolerance": "0",
                            "tolerance_quote": "none"}, solution)
    assert str(answer.value) == expected and str(answer.tolerance) == tolerance
    assert answer.tolerance_source == ("implied" if tolerance != "0" else "exact")


@pytest.mark.parametrize("raw,expected", [
    (r"\frac {2}{13}", "2/13"), (r"\dfrac{2}{13}", "2/13"), (r"\tfrac{2}{13}", "2/13"),
    ("= 25%", "1/4"), ("\u2248 0.125 credits", "1/8"),
    (r"\approx 3/4 ways in total", "3/4"), ("2.50e-3 seconds", "1/400"),
    (r"1.2 \times 10^{-3}", "3/2500"), ("-2 / 5", "-2/5"),
])
def test_numeric_answer_wrappers_units_and_scientific_forms(raw, expected):
    assert str(number(raw)) == expected


@pytest.mark.parametrize("raw", ["2 or 3", "2 + 3", "1/0", "nan", "sqrt(2)", "3 apples and 4 pears"])
def test_parser_still_abstains_on_multiple_or_non_numeric_answers(raw):
    with pytest.raises(Reject):
        number(raw)


def test_topic_vocabulary_uses_clean_whole_labels_and_frequency(tmp_path):
    path = tmp_path / "invented.csv"
    rows = []
    for i in range(8):
        labels = "['Probability', 'Combinations and Permutations', 'x', 'contributor notes by someone']"
        if i < 4:
            labels = labels[:-1] + ", 'Rare Label']"
        rows.append({"question_id": str(i), "topics": labels,
                     "statement": "Invented item " + str(i), "solution": "3"})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    questions, counts = load_csv(path)
    assert counts.topic_vocabulary == {"combinations and permutations": 8, "probability": 8}
    assert all(q.topics == ("probability", "combinations and permutations") for q in questions)
    assert set(counts.per_topic) == set(counts.topic_vocabulary)


def setup(tmp_path):
    models, sandbox = FakeModels(tmp_path / "private"), FakeSandbox()
    pipeline = Pipeline(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json",
                        sandbox=sandbox, trials=1000)
    return models, sandbox, pipeline


def run(pipeline):
    return pipeline.run([question()], counts())


@pytest.mark.parametrize("reason", ["TypeError", "invalid_template_fields", "invalid_step_names", "forbidden_import", "timeout"])
def test_one_author_repair_is_recorded_and_acceptance_counted(tmp_path, reason):
    models, sandbox, pipeline = setup(tmp_path)
    original = sandbox.run
    failed = False
    def fail_once(code, mode, params, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise Reject("sandbox", reason)
        return original(code, mode, params, **kwargs)
    sandbox.run = fail_once
    models.overrides["author_repair"] = draft()
    report = run(pipeline)
    assert report["accepted_templates"] == report["accepted_after_repair"] == 1
    assert [stage for stage, _ in models.calls].count("author") == 1
    assert [stage for stage, _ in models.calls].count("author_repair") == 1
    repair = next(payload for stage, payload in models.calls if stage == "author_repair")
    assert repair["error"]["error_class"] == reason
    assert report["stages"]["render"]["attempted"] == report["stages"]["render"]["passed"] == 1
    before = len(models.calls)
    run(pipeline)
    assert len(models.calls) == before


def test_second_gate_failure_does_not_get_another_repair(tmp_path):
    models, sandbox, pipeline = setup(tmp_path)
    sandbox.run = lambda *a, **k: (_ for _ in ()).throw(Reject("sandbox", "TypeError"))
    models.overrides["author_repair"] = draft()
    assert run(pipeline)["accepted_templates"] == 0
    assert [stage for stage, _ in models.calls].count("author_repair") == 1


def test_simulator_repair_sees_only_questions_and_safe_error(tmp_path):
    models, sandbox, pipeline = setup(tmp_path)
    original = sandbox.run
    failed = False
    def fail_once(code, mode, params, **kwargs):
        nonlocal failed
        if mode == "sample" and not failed:
            failed = True
            raise Reject("sandbox", "TypeError")
        return original(code, mode, params, **kwargs)
    sandbox.run = fail_once
    models.overrides["simulator_repair"] = {"code": SIM, "part2_code": ""}
    report = run(pipeline)
    assert report["accepted_after_repair"] == 1
    payload = next(payload for stage, payload in models.calls if stage == "simulator_repair")
    assert set(payload) == {"question", "part2_question", "error"}
    assert payload["error"]["error_class"] == "TypeError"
    assert SOLVER not in str(payload) and question().solution not in str(payload)


def test_step_names_are_normalised_in_declaration_and_returned_values(tmp_path):
    models, sandbox, pipeline = setup(tmp_path)
    models.blueprint["step_names"] = ["Half Reward"]
    original = sandbox.run
    def renamed(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[1] == "solve" and args[0] == SOLVER:
            result["steps"][0]["name"] = "halfReward"
        return result
    sandbox.run = renamed
    assert run(pipeline)["accepted_templates"] == 1
    import json
    artifact = json.loads(next((tmp_path / "public").glob("*.json")).read_text())
    assert all(row["steps"][0]["name"] == "half_reward" for row in artifact["instances"])


@pytest.mark.parametrize("matches", [True, False])
def test_reading_with_same_original_answer_needs_three_matching_twins(tmp_path, matches):
    models, _, pipeline = setup(tmp_path)
    models.overrides["reading_model"] = {"alternatives": [
        {"reading": "A different verbal description of the same experiment", "answer": "2", "tolerance": "0"}]}
    original = models.call
    def call(stage, payload, *args, **kwargs):
        if stage == "reading_twins":
            models.calls.append((stage, payload))
            import re
            answers = [str(Fraction(int(re.search(r"earns (\d+) credits", text)[1]), 2))
                       for text in payload["questions"]]
            if not matches:
                answers[-1] = "987"
            return {"answers": answers}
        return original(stage, payload, *args, **kwargs)
    models.call = call
    report = run(pipeline)
    assert report["accepted_templates"] == int(matches)
    assert len(next(payload for stage, payload in models.calls if stage == "reading_twins")["questions"]) == 3
    if matches:
        import json
        artifact = json.loads(next((tmp_path / "public").glob("*.json")).read_text())
        assert artifact["verification"]["readings"]["equivalent_readings"][0]["status"] == "equivalent reading"


def test_stratified_sampling_assigns_each_question_to_only_one_quota(tmp_path):
    from forge.pipeline import select_questions
    questions = [replace(question(), question_id=str(i), statement_sha256=str(i),
                         topics=topics) for i, topics in enumerate([
        ("probability", "expected value"), ("probability",),
        ("expected value",), ("statistics",), ("statistics",)])]
    selected, assigned, shortfalls = select_questions(questions, 4,
        ("probability", "expected value", "statistics"),
        {"probability": 2, "expected value": 1, "statistics": 1})
    assert len(selected) == len({q.key for q in selected}) == 4
    from collections import Counter
    assert Counter(assigned.values()) == {"probability": 2, "expected value": 1, "statistics": 1}
    assert not any(shortfalls.values())


def test_numeric_failure_report_has_only_unparsed_counts(tmp_path):
    models, _, pipeline = setup(tmp_path)
    models.overrides["answer_pass"] = {"class": "numeric_single", "answer": "none",
        "quote": question().solution, "tolerance": "0", "tolerance_quote": "none"}
    report = run(pipeline)
    assert report["unparsed_answers"] == 1
    assert question().solution not in str(report)


@pytest.mark.parametrize("body", ["return 0.5", "return {'answer': 1, 'steps': {'value': 0.5}}"])
def test_float_solver_or_step_is_a_repairable_type_error(body):
    from forge.sandbox import Sandbox
    with pytest.raises(Reject) as error:
        Sandbox().run("def solve(params): " + body, "solve", {})
    assert error.value.reason == "TypeError"


@pytest.mark.parametrize("literal,expected", [("3", "3"), ("Fraction(3, 2)", "3/2")])
def test_solver_and_steps_accept_int_and_fraction(literal, expected):
    from forge.sandbox import Sandbox
    code = "from fractions import Fraction\ndef solve(params):\n value = " + literal + "\n return {'answer': value, 'steps': {'value': value}}"
    result = Sandbox().run(code, "solve", {})
    assert result == {"answer": expected, "steps": [{"name": "value", "value": expected}]}


@pytest.mark.parametrize("literal", ["rng.random() < .5", "int(rng.random() < .5)",
                                     "float(rng.random() < .5)", "Fraction(int(rng.random() < .5))"])
def test_sampler_bool_int_float_fraction_share_the_same_statistics(literal):
    from forge.sandbox import Sandbox
    result = Sandbox().run("from fractions import Fraction\ndef sample(params, rng): return " + literal,
                           "sample", {}, trials=100, seed=8)
    assert result["draws"] == 100
    assert Fraction(0) < Fraction(result["mean"]) < Fraction(1) and result["se"] > 0


def test_cpu_or_wall_timeout_is_labelled_for_one_repair():
    from forge.sandbox import Sandbox
    with pytest.raises(Reject) as error:
        Sandbox(timeout_s=.1).run("def solve(params):\n while True: pass", "solve", {})
    assert error.value.reason == "timeout"


@pytest.mark.parametrize("interrupt_repair", [False, True])
def test_recorded_gate_repair_replays_keylessly_and_resumes_without_respending(tmp_path, monkeypatch, interrupt_repair):
    import json
    from forge.errors import BudgetStop
    from forge.models import Models, State
    from forge_fakes import response_for
    class Backend:
        def __init__(self, name):
            self.name, self.model = name, "test-" + name
            self.enforces_schema = name == "meta_api"
            self.calls = []
        def complete(self, request):
            self.calls.append(request)
            stage = request["response_format"]["json_schema"]["name"].removeprefix("forge_")
            payload = json.loads(request["messages"][-1]["content"])
            body = response_for(stage, payload)
            if stage == "author":
                body["solver"] = "inexact invented solver"
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 200}}
    class InexactSandbox(FakeSandbox):
        def run(self, code, *args, **kwargs):
            if code == "inexact invented solver":
                raise TypeError("never log this private exception message")
            return super().run(code, *args, **kwargs)
    author, checker = Backend("open_weights"), Backend("meta_api")
    state = State(tmp_path / "private")
    models = Models(state, mode="live", author=author, checker=checker)
    original = models.call
    interrupted = False
    def call(stage, *args, **kwargs):
        nonlocal interrupted
        if stage == "author_repair" and interrupt_repair and not interrupted:
            interrupted = True
            raise BudgetStop()
        return original(stage, *args, **kwargs)
    models.call = call
    pipeline = Pipeline(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json",
                        sandbox=InexactSandbox(), trials=1000)
    if interrupt_repair:
        assert run(pipeline)["status"] == "budget_stop"
        assert next(iter(state.data["items"].values()))["repair"]["succeeded"] is False
    assert run(pipeline)["accepted_after_repair"] == 1
    assert len(author.calls) + len(checker.calls) == 7
    assert len(list((state.root / "calls").glob("*.json"))) == 7
    cost = models.spent()
    before = next((tmp_path / "public").glob("*.json")).read_bytes()
    state.data["items"], state.data["mapping"] = {}, {}
    state.save()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    author.complete = checker.complete = lambda request: pytest.fail("Replay attempted a live call")
    replay = Models(state, mode="replay", author=author, checker=checker)
    pipeline = Pipeline(replay, output=tmp_path / "public", funnel=tmp_path / "funnel.json",
                        sandbox=InexactSandbox(), trials=1000)
    assert run(pipeline)["accepted_after_repair"] == 1
    assert replay.spent() == cost
    assert next((tmp_path / "public").glob("*.json")).read_bytes() == before


def test_original_reading_outside_stored_tolerance_cannot_use_equivalence():
    from forge.data import Answer
    from forge.verify import ambiguity
    with pytest.raises(Reject):
        ambiguity([{"reading": "Different value", "answer": "0.61", "tolerance": "0.1"}],
                  Answer(Fraction(1, 2), Fraction(1, 10)), lambda reading: pytest.fail("Different original answer got equivalence check"))


def test_quota_matching_reassigns_overlap_to_fill_a_scarce_topic():
    from forge.selection import select_questions
    questions = [replace(question(), question_id=str(i), statement_sha256=str(i),
                         topics=topics) for i, topics in enumerate([
        ("probability", "expected value"), ("probability",)])]
    selected, assigned, shortfalls = select_questions(questions, 2, ("probability", "expected value"),
                                                      {"probability": 1, "expected value": 1})
    assert len(selected) == 2 and shortfalls == {"probability": 0, "expected value": 0}
    assert set(assigned.values()) == {"probability", "expected value"}


def test_quota_shortfalls_are_explicit_and_no_other_topic_fills_them():
    from forge.selection import select_questions
    questions = [replace(question(), question_id=str(i), topics=("probability",)) for i in range(3)]
    selected, _, shortfalls = select_questions(questions, 3, (), {"probability": 1, "statistics": 2})
    assert len(selected) == 1 and shortfalls == {"probability": 0, "statistics": 2}


def test_author_repair_does_not_bypass_any_numeric_or_blind_gate(tmp_path):
    models, sandbox, pipeline = setup(tmp_path)
    models.blueprint["text"] = "Broken {unknown}."
    models.overrides["author_repair"] = draft()
    models.overrides["blind_model"] = {"answer": "999"}
    report = run(pipeline)
    assert report["accepted_templates"] == 0 and report["accepted_after_repair"] == 0
    assert report["stages"]["instances"]["passed"] == 1
    assert report["failures"]["blind_checker:answer_mismatch"] == 1

def test_rounded_original_reading_can_be_equivalent_only_after_exact_twins():
    from forge.data import Answer
    from forge.verify import ambiguity
    calls = []
    def confirm(reading):
        calls.append(reading)
        return {"point_count": 3, "answers": ["1/3", "2/3", "1"]}
    result = ambiguity([{"reading": "Same process", "answer": "1/3", "tolerance": "0"}],
                       Answer(Fraction(33, 100), Fraction(1, 200), "implied"), confirm)
    assert len(calls) == 1 and result["equivalent_readings"][0]["status"] == "equivalent reading"
