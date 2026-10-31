"""Part 3 twists (forge/coding_twists.py): shipped only when the brute-force and fast solvers
agree on 300 random inputs and the twist really changes the answer. Real sandbox, fake model."""

import copy
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge import coding_twists as ct
from forge.errors import Reject
from forge.models import State
from forge.sandbox import Sandbox

FIXTURE = Path(__file__).with_name("fixtures") / "coding"
SPEC = json.loads((FIXTURE / "sw_F001.json").read_text(encoding="utf-8"))
GENERATOR = ct.GENERATOR.read_text(encoding="utf-8")

# The twist: the best run when you may drop at most one day from inside it.
BRUTE = """def solve(params):
    vals = list(params["values"])
    best = None
    for i in range(len(vals)):
        for j in range(i, len(vals)):
            run = vals[i:j + 1]
            options = [sum(run)]
            if len(run) > 1:
                options += [sum(run) - x for x in run]
            top = max(options)
            best = top if best is None else max(best, top)
    return best
"""
FAST = """def solve(params):
    vals = list(params["values"])
    keep = vals[0]
    drop = vals[0]
    best = vals[0]
    for x in vals[1:]:
        drop = max(drop + x, keep)
        keep = max(x, keep + x)
        best = max(best, keep, drop)
    return best
"""
TWIST = {"function_name": "best_run_dropping_one_day", "brute_force": BRUTE, "fast": FAST,
         "statement": "Given a list of daily gains, return the largest total of a run of consecutive days when you may leave out at most one day from inside the run."}


def test_a_sound_twist_ships_with_tests_examples_and_the_original_as_a_named_mistake():
    shipped = ct.verify(TWIST, SPEC, Sandbox(timeout_s=60), GENERATOR)
    assert shipped["signature"] == "def best_run_dropping_one_day(gains: list[int]) -> int:"
    assert len(shipped["tests"]) == len(shipped["expected"]) == ct.TESTS and len(shipped["examples"]) == 2
    assert shipped["verification"]["agreed_inputs"] == 300 and shipped["verification"]["differs_from_original"] > 0
    assert shipped["wrong_methods"][0]["name"] == "the original problem's answer"
    assert shipped["difficulty"] == "Hard" and shipped["brute_force_source"] == BRUTE


@pytest.mark.parametrize("change, reason", [
    ({"fast": FAST.replace("best = max(best, keep, drop)", "best = max(best, keep)")}, "solvers_disagree"),
    ({"brute_force": SPEC["solver_source"], "fast": SPEC["solver_source"]}, "not_a_twist"),
    ({"function_name": "Best Run"}, "invalid_name"),
    ({"statement": "Short."}, "statement_length"),
])
def test_unsound_twists_are_refused(change, reason):
    with pytest.raises(Reject) as error:
        ct.verify({**TWIST, **change}, SPEC, Sandbox(timeout_s=60), GENERATOR)
    assert error.value.reason == reason


class FakeModels:
    def __init__(self, root, drafts):
        self.state = State(root)
        self.author = SimpleNamespace(model="meta-models/muse-spark-open-test")
        self.drafts, self.calls, self.budget = list(drafts), [], Decimal("0.5")

    def call(self, stage, payload, schema, instructions, *, author=False, max_tokens=4000):
        assert author and schema is ct.TWIST
        self.calls.append(stage)
        return copy.deepcopy(self.drafts.pop(0))

    def spent(self):
        return Decimal(0)


def test_the_forge_repairs_once_ships_only_verified_twists_and_resumes(tmp_path):
    scale = tmp_path / "scale"
    scale.mkdir()
    (scale / "sw_F001.json").write_text("{}", encoding="utf-8")
    bad = {**TWIST, "fast": TWIST["fast"].replace("best = max(best, keep, drop)", "best = max(best, keep)")}
    models = FakeModels(tmp_path / "work", [bad, TWIST])
    out = tmp_path / "twist"
    report = ct.TwistForge(models, Sandbox(timeout_s=60), specs=FIXTURE, scale=scale, out=out).run()
    assert models.calls == ["twist_author", "twist_repair"] and report["outcomes"] == {"sw_F001": "verified"}
    assert json.loads((out / "sw_F001.json").read_text(encoding="utf-8"))["models"]["twist_author"] == "meta-models/muse-spark-open-test"
    ct.TwistForge(models, Sandbox(timeout_s=60), specs=FIXTURE, scale=scale, out=out).run()
    assert len(models.calls) == 2  # verified: not paid for again
