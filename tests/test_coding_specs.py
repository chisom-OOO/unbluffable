"""Coding specs (forge/coding_specs.py): verified through the forge's own solver on every
variant, wrong methods kept only when they are wrong somewhere. Real sandbox, fake model."""

import copy
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge import coding_specs as cs
from forge.errors import Reject
from forge.models import State
from forge.sandbox import Sandbox

ROOT = Path(__file__).resolve().parents[1]
FAMILY = json.loads((ROOT / "content" / "forge" / "sw_F001.json").read_text(encoding="utf-8"))  # largest consecutive sum

SOLVER = """def solve(params):
    vals = params["values"]
    best = cur = vals[0]
    for x in vals[1:]:
        cur = max(x, cur + x)
        best = max(best, cur)
    return {"answer": best, "steps": {"max_consecutive_sum": best}}
"""
WRONG = [{"misconception": "ignores_contiguity", "code": "def solve(params):\n    pos = [x for x in params['values'] if x > 0]\n    return sum(pos) if pos else max(params['values'])\n"},
         {"misconception": "always_right", "code": SOLVER.replace('{"answer": best, "steps": {"max_consecutive_sum": best}}', "best")}]
SPEC = {"function_name": "max_consecutive_gain", "parameters": [{"name": "gains", "type": "list[int]", "param": "values"}],
        "return_type": "int", "statement": "Given a list of daily gains, return the largest total of any nonempty run of consecutive days."}


def test_a_sound_spec_ships_with_tests_wrong_outputs_and_the_solver_source():
    shipped = cs.verify(SPEC, FAMILY, SOLVER, WRONG, Sandbox())
    n = len(FAMILY["instances"])
    assert shipped["signature"] == "def max_consecutive_gain(gains: list[int]) -> int:"
    assert len(shipped["tests"]) == len(shipped["expected"]) == n and shipped["tests"][0] == [FAMILY["instances"][0]["params"]["values"]]
    assert shipped["expected"] == [str(i["answer"]) for i in FAMILY["instances"]]
    # A wrong method is kept only if it is wrong on some test; one that always agrees is dropped.
    assert [m["name"] for m in shipped["wrong_methods"]] == ["ignores contiguity"]
    assert len(shipped["wrong_methods"][0]["outputs"]) == n
    assert any(o != e for o, e in zip(shipped["wrong_methods"][0]["outputs"], shipped["expected"]))
    assert shipped["solver_source"] == SOLVER and len(shipped["examples"]) == 2
    assert shipped["verification"] == {"verified": True, "variants": n, "solver_reproduced": n, "wrong_methods_kept": 1, "wrong_methods_given": 2}


@pytest.mark.parametrize("change, reason", [
    ({"parameters": [{"name": "gains", "type": "list[int]", "param": "numbers"}]}, "parameters_do_not_match"),
    ({"parameters": [{"name": "gains", "type": "list[str]", "param": "values"}]}, "type_mismatch"),
    ({"parameters": [{"name": "gains", "type": "dict", "param": "values"}]}, "unknown_type"),
    ({"function_name": "Max-Gain"}, "invalid_name_or_return_type"),
    ({"statement": "Sum."}, "statement_length"),
])
def test_unsound_specs_are_refused(change, reason):
    with pytest.raises(Reject) as error:
        cs.verify({**SPEC, **change}, FAMILY, SOLVER, WRONG, Sandbox())
    assert error.value.reason == reason


def test_the_solver_must_reproduce_every_stored_answer_through_the_signature():
    off_by_one = SOLVER.replace('{"answer": best,', '{"answer": best + (1 if vals[0] < 0 else 0),')
    with pytest.raises(Reject) as error:
        cs.verify(SPEC, FAMILY, off_by_one, WRONG, Sandbox())
    assert error.value.reason == "solver_does_not_reproduce"


class FakeModels:
    def __init__(self, root, drafts):
        self.state = State(root)
        self.author = SimpleNamespace(model="meta-models/muse-spark-open-test")
        self.drafts, self.calls, self.budget = list(drafts), [], Decimal(1)

    def call(self, stage, payload, schema, instructions, *, author=False):
        assert author and schema is cs.SPEC
        self.calls.append((stage, copy.deepcopy(payload)))
        return copy.deepcopy(self.drafts.pop(0))

    def spent(self):
        return Decimal(0)


def test_forge_run_repairs_once_ships_only_verified_specs_and_resumes(tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    (content / "sw_F001.json").write_text(json.dumps(FAMILY), encoding="utf-8")
    items = {"sw_F001": {"status": "verified", "draft": {"solver": SOLVER, "wrong": WRONG}}}
    models = FakeModels(tmp_path / "work", [{**SPEC, "return_type": "list"}, SPEC])  # bad, then repaired
    out = tmp_path / "coding"
    report = cs.CodingForge(models, Sandbox(), out=out, content=content).run(items)
    assert [stage for stage, _ in models.calls] == ["coding_author", "coding_repair"]
    assert models.calls[1][1]["error"]["error_class"] == "invalid_name_or_return_type"
    assert report["verified"] == 1 and report["status"] == "completed"
    shipped = json.loads((out / "sw_F001.json").read_text(encoding="utf-8"))
    assert shipped["models"]["spec_author"] == "meta-models/muse-spark-open-test"
    cs.CodingForge(models, Sandbox(), out=out, content=content).run(items)  # done: no more calls
    assert len(models.calls) == 2
    # A family whose spec never verifies does not ship.
    other = tmp_path / "other"
    report = cs.CodingForge(FakeModels(tmp_path / "w2", [{**SPEC, "statement": "x"}] * 2), Sandbox(), out=other, content=content).run(items)
    assert report["fallback"] == 1 and not other.exists()
