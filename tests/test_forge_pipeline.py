from forge_fakes import counts
import json

import pytest

from forge.pipeline import Pipeline
from forge.data import CLASSES
from forge.sandbox import Sandbox
from forge_fakes import FakeModels, FakeSandbox, SOLVER, question


def setup(tmp_path, part2=False):
    models, sandbox = FakeModels(tmp_path / "data" / "forge", part2), FakeSandbox()
    pipeline = Pipeline(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json",
                        sandbox=sandbox, trials=2000)
    return models, sandbox, pipeline


def execute(pipeline):
    return pipeline.run([question()], counts(), 100)


def test_all_gates_export_only_instances_and_finished_items_never_respend(tmp_path):
    models, _, pipeline = setup(tmp_path)
    report = execute(pipeline)
    assert report["stages"]["accepted"]["passed"] == 1
    assert report["classes"]["numeric_single"] == 1 and sum(report["classes"].values()) == 1
    assert report["classes_per_topic"]["probability"]["numeric_single"] == 1
    files = list((tmp_path / "public").glob("*.json"))
    assert len(files) == 1
    before = files[0].read_bytes()
    artifact = json.loads(before)
    assert artifact["review_status"] == "pending_builder_review"
    assert len(artifact["instances"]) >= 20
    assert artifact["verification"]["monte_carlo"]["point_count"] >= 20
    assert artifact["verification"]["instances"]["minimum"] == 20
    assert all("separation" in row for row in artifact["instances"])
    assert {"1", "4", "101"} <= {point["params"]["n"] for point in artifact["verification"]["monte_carlo"]["points"]}
    assert artifact["verification"]["steps"]["named_values"] == 1
    assert all(value["passed"] for key, value in artifact["verification"].items() if key != "part2")
    public = before.decode() + (tmp_path / "funnel.json").read_text(encoding="utf-8")
    for private in [question().question_id, question().statement, question().solution, "def solve", "def sample"]:
        assert private not in public
    mapping = json.loads((models.state.root / "mapping.json").read_text(encoding="utf-8"))
    assert next(iter(mapping.values()))["question_id"] == question().question_id
    calls = len(models.calls)
    execute(pipeline)
    assert len(models.calls) == calls and files[0].read_bytes() == before


def test_simulator_and_blind_checker_see_only_question_text(tmp_path):
    models, _, pipeline = setup(tmp_path)
    execute(pipeline)
    simulator = next(payload for stage, payload in models.calls if stage == "simulator")
    blind = next(payload for stage, payload in models.calls if stage == "blind_model")
    assert set(simulator) == {"question", "part2_question"}
    assert set(blind) == {"question"}
    assert SOLVER not in json.dumps(simulator) + json.dumps(blind)
    assert question().solution not in json.dumps(simulator) + json.dumps(blind)


@pytest.mark.parametrize("case,stage", [
    ("quote", "answer_pass"), ("range", "parameters"), ("original", "original_answer"),
    ("novelty", "novelty"), ("draws", "monte_carlo"), ("zero_variance", "monte_carlo"), ("simulation", "monte_carlo"),
    ("wrong", "wrong_methods"), ("steps", "steps"), ("reading", "readings"),
    ("too_many_readings", "readings"), ("blind", "blind_checker"),
])
def test_every_base_gate_rejects_independently(tmp_path, case, stage):
    models, sandbox, pipeline = setup(tmp_path)
    if case == "quote":
        models.overrides["answer_pass"] = {"class": "numeric_single", "answer": "2", "quote": "invented", "tolerance": "0", "tolerance_quote": "none"}
    elif case == "range":
        models.blueprint["parameters"][0].update(maximum="4")
    elif case == "original":
        sandbox.solver_offset = 1
    elif case == "novelty":
        models.blueprint["text"] = question().statement + " {n}"
    elif case == "draws":
        sandbox.draws = False
    elif case == "zero_variance":
        sandbox.se = 0
    elif case == "simulation":
        sandbox.sample_offset = 1
    elif case == "wrong":
        models.blueprint["wrong"][0]["code"] = SOLVER
    elif case == "steps":
        sandbox.bad_steps = True
    elif case in {"reading", "too_many_readings"}:
        alternative = {"reading": "A plausible alternative", "answer": "2", "tolerance": "0"}
        models.overrides["reading_model"] = {"alternatives": [alternative] * (4 if case == "too_many_readings" else 1)}
    elif case == "blind":
        models.overrides["blind_model"] = {"answer": "999"}
    report = execute(pipeline)
    assert report["stages"]["accepted"]["passed"] == 0
    item = next(iter(models.state.data["items"].values()))
    assert item["status"] == "rejected" and item["failure"]["stage"] == stage
    assert not list((tmp_path / "public").glob("*.json"))
    count = len(models.calls)
    execute(pipeline)
    assert len(models.calls) == count


@pytest.mark.parametrize("kind", [kind for kind in CLASSES if kind != "numeric_single"])
def test_other_answer_classes_are_counted_and_never_forged(tmp_path, kind):
    models, _, pipeline = setup(tmp_path)
    models.overrides["answer_pass"] = {"class": kind, "answer": "2", "quote": question().solution,
                                      "tolerance": "0", "tolerance_quote": "none"}
    report = execute(pipeline)
    assert report["classes"][kind] == 1 and sum(report["classes"].values()) == 1
    assert [stage for stage, _ in models.calls] == ["answer_pass"]
    assert next(iter(models.state.data["items"].values()))["status"] == "not_numeric"


@pytest.mark.parametrize("failure", [False, True])
def test_part_two_is_accepted_only_after_its_own_checks(tmp_path, failure):
    models, sandbox, pipeline = setup(tmp_path, part2=True)
    sandbox.part2_failure = failure
    report = execute(pipeline)
    assert report["stages"]["accepted"]["passed"] == 1
    artifact = json.loads(next((tmp_path / "public").glob("*.json")).read_text(encoding="utf-8"))
    assert artifact["verification"]["part2"]["passed"] is not failure
    assert all(("part2" in row) is not failure for row in artifact["instances"])
    if not failure:
        assert len(artifact["instances"]) >= 20
        assert all(row["part2"]["params"]["n"] == row["params"]["n"] for row in artifact["instances"])
        assert all("separation" in row["part2"] for row in artifact["instances"])


def test_real_subprocess_pipeline_with_invented_models(tmp_path):
    models, _, pipeline = setup(tmp_path)
    pipeline.sandbox = Sandbox(timeout_s=8)
    report = execute(pipeline)
    assert report["stages"]["accepted"]["passed"] == 1


def test_part_two_blind_failure_drops_only_part_two(tmp_path):
    models, sandbox, pipeline = setup(tmp_path, part2=True)
    models.overrides["part2_blind_model"] = {"answer": "999"}
    report = execute(pipeline)
    assert report["accepted_templates"] == 1
    artifact = json.loads(next((tmp_path / "public").glob("*.json")).read_text(encoding="utf-8"))
    assert artifact["verification"]["part2"]["passed"] is False
    assert all("part2" not in instance for instance in artifact["instances"])


def test_different_alternative_is_ruled_out_by_the_stored_answer(tmp_path):
    models, _, pipeline = setup(tmp_path)
    models.overrides["reading_model"] = {"alternatives": [{"reading": "Different meaning", "answer": "3", "tolerance": "0"}]}
    assert execute(pipeline)["accepted_templates"] == 1


def test_resume_cannot_silently_change_verification_thresholds(tmp_path):
    models, _, pipeline = setup(tmp_path)
    execute(pipeline)
    with pytest.raises(ValueError):
        Pipeline(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json", trials=4000)


def test_duplicate_generated_templates_do_not_inflate_the_funnel(tmp_path):
    from dataclasses import replace
    models, _, pipeline = setup(tmp_path)
    second = replace(question(), question_id="another-private-source", statement=question().statement + " Different invented framing.")
    report = pipeline.run([question(), second], counts(2, 2))
    assert report["completed_questions"] == 2 and report["accepted_templates"] == 1
    assert report["failures"]["novelty:duplicate_generated_template"] == 1
    assert len(list((tmp_path / "public").glob("*.json"))) == 1

def test_legacy_eight_instance_checkpoint_is_not_silently_reused(tmp_path):
    models, _, _ = setup(tmp_path)
    models.state.data["verification_settings"] = {"trials": 2000, "max_similarity": .70}
    models.state.save()
    with pytest.raises(ValueError, match="original verification settings"):
        Pipeline(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json",
                 sandbox=FakeSandbox(), trials=2000)
    assert not models.calls


def test_part_two_collisions_cannot_export_fewer_than_twenty(tmp_path):
    from forge_fakes import PART_SOLVER
    models, _, pipeline = setup(tmp_path, part2=True)
    models.blueprint["part2"]["wrong"][0]["code"] = PART_SOLVER
    assert execute(pipeline)["accepted_templates"] == 1
    artifact = json.loads(next((tmp_path / "public").glob("*.json")).read_text(encoding="utf-8"))
    assert len(artifact["instances"]) >= 20
    assert artifact["verification"]["part2"]["passed"] is False
    assert all("part2" not in row for row in artifact["instances"])


def test_part_two_extra_parameter_spans_its_whole_range(tmp_path):
    models, _, pipeline = setup(tmp_path, part2=True)
    models.blueprint["part2"]["parameter"]["maximum"] = "101"
    assert execute(pipeline)["accepted_templates"] == 1
    artifact = json.loads(next((tmp_path / "public").glob("*.json")).read_text(encoding="utf-8"))
    values = sorted(int(row["part2"]["params"]["k"]) for row in artifact["instances"])
    assert len(values) >= 20 and values[0] == 1 and values[-1] == 101
    assert max(b - a for a, b in zip(values, values[1:])) <= 6
