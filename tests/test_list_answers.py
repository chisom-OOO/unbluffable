"""List answers (decision log 30): answers like "[106,110]" or "[8,18,13]" compare by exact JSON
equality after normalising whitespace. Such families are coding-only: the spoken bank never
loads them; coding specs and the runner compare lists exactly. Real sandbox, fake model."""

import copy
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import coding
from engine.bank import load_bank
from forge import coding_specs as cs
from forge.data import list_answer
from forge.errors import Reject
from forge.families import FamilyForge, load_families
from forge.models import State
from forge.sandbox import Sandbox
from test_forge_families import write_rows

SOLVER = '''def solve(params):
    a, b = params["a"], params["b"]
    return {"answer": [a + b, a * b], "steps": {"total": a + b}}
'''
WRONG = '''def solve(params):
    return {"answer": [params["a"] + params["b"], params["a"] + params["b"]], "steps": {}}
'''
WRONG2 = '''def solve(params):
    return {"answer": [params["a"] * params["b"], params["a"] + params["b"]], "steps": {}}
'''


@pytest.mark.parametrize("text, canon", [("[106, 110]", "[106,110]"), (" [8,18,13] ", "[8,18,13]"),
                                         ('[[1, 2], ["a b", true]]', '[[1,2],["a b",true]]')])
def test_list_answers_are_canonical_json(text, canon):
    assert list_answer(text) == canon


@pytest.mark.parametrize("text", ["[1.5, 2]", "[1, NaN]", "[1, 2", '{"a": 1}'])
def test_unusable_lists_are_refused(text):
    if text.startswith("{"):
        assert list_answer(text) is None
        return
    with pytest.raises(Reject):
        list_answer(text)


def rows(count=20):
    out = []
    for i in range(1, count + 1):
        a, b = i, i + 3
        out.append({"id": f"p-{i}", "family_id": "SWF1", "variant": str(i), "question": f"Return the sum and product of {a} and {b}.",
                    "parameters": json.dumps({"a": a, "b": b}), "verified_value": json.dumps([a + b, a * b]),  # "[5, 4]"
                    "verification_result": "PASS_EXACT", "verification_tolerance": "", "topic": "Arrays",
                    "subtopic": "pairs", "difficulty": "Easy", "solution": "Add and multiply.", "reasoning_focus": "Both values.",
                    "interview_follow_up": "What if a list is empty?", "follow_up_discussion": "Handle it first."})
    return out


class Models:
    def __init__(self, root):
        self.state = State(root)
        self.author = SimpleNamespace(model="test-open-weights")
        self.budget = Decimal(5)

    def spent(self):
        return Decimal(0)

    def call(self, stage, payload, schema, instructions, *, author=False, max_tokens=4000):
        if stage.startswith("family"):
            return {"solver": SOLVER, "step_names": ["total"], "wrong": [
                {"misconception": "repeats_the_sum", "code": WRONG}, {"misconception": "swaps_the_order", "code": WRONG2}]}
        return copy.deepcopy(SPEC)


SPEC = {"function_name": "sum_and_product", "parameters": [{"name": "a", "type": "int", "param": "a"},
                                                           {"name": "b", "type": "int", "param": "b"}],
        "return_type": "list[int]", "statement": "Given two integers a and b, return a list of their sum and their product."}


def forge_list_family(tmp_path):
    path = tmp_path / "swf.csv"
    write_rows(path, rows())
    families = load_families(path)
    assert families[0].variants[0].answer == "[5,4]"
    out = tmp_path / "forge"
    report = FamilyForge(Models(tmp_path / "w"), output=out, funnel=tmp_path / "f.json", sandbox=Sandbox(),
                         pack="software", prefix="swf").run(families)
    assert report["solvers_verified"] == 1
    artifact = json.loads((out / "swf_F001.json").read_text(encoding="utf-8"))
    assert artifact["coding_only"] is True and artifact["answer_kind"] == "list"
    assert artifact["instances"][0]["answer"] == "[5,4]" and artifact["verification"]["misconceptions_verified"]
    assert artifact["instances"][0]["wrong"][0]["value"] in {"[5,5]", "[4,5]"}
    assert "swf_F001" not in load_bank(out).templates and not load_bank(out).errors  # never in spoken mode
    # A solver whose list differs anywhere (order included) is not verified.
    bad = [{**r, "verified_value": json.dumps(list(reversed(json.loads(r["verified_value"]))))} for r in rows()]
    write_rows(path, bad)
    report = FamilyForge(Models(tmp_path / "w2"), output=tmp_path / "o2", funnel=tmp_path / "f2.json", sandbox=Sandbox(),
                         pack="software", prefix="swf").run(load_families(path))
    assert report["solvers_verified"] == 0
    return artifact


def test_a_list_family_is_forged_exactly_exported_coding_only_and_never_spoken(tmp_path):
    forge_list_family(tmp_path)


def test_coding_specs_for_a_list_family_and_exact_judging(tmp_path):
    artifact = forge_list_family(tmp_path)
    shipped = cs.verify(SPEC, artifact, SOLVER, [{"misconception": "repeats_the_sum", "code": WRONG}], Sandbox())
    assert shipped["return_type"] == "list[int]" and shipped["expected"][0] == "[5,4]"
    assert shipped["wrong_methods"][0]["outputs"][0] == "[5,5]"
    with pytest.raises(Reject):
        cs.verify({**SPEC, "return_type": "int"}, artifact, SOLVER, [], Sandbox())
    right = [{"ok": True, "value": e.replace(",", ", ")} for e in shipped["expected"]]  # whitespace normalised
    assert coding.judge(shipped, right)["passed"] == len(right)
    wrong = [{"ok": True, "value": o} for o in shipped["wrong_methods"][0]["outputs"]]
    judged = coding.judge(shipped, wrong)
    assert judged["passed"] == 0 and judged["named"] == "repeats the sum"
    reordered = [{"ok": True, "value": json.dumps(list(reversed(json.loads(e))))} for e in shipped["expected"]]
    assert coding.judge(shipped, reordered)["passed"] == 0  # exact: order matters
    from forge.coding_scale import infer
    assert infer(shipped) is None
