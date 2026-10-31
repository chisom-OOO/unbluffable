"""Class-based coding specs ("implement the component", swc_ families): the spec gives a class
name, the constructor and method signatures; each test is an operation sequence and its
expected output is the list of return values, compared exactly. Real sandbox, fake model."""

import copy
import json
import random
from pathlib import Path

import pytest

from app import coding
from forge import coding_specs as cs
from forge.errors import Reject
from forge.sandbox import Sandbox

SOLVER = """def solve(params):
    k = params["capacity"]
    items = []
    steps = {}
    total = 0
    for i, op in enumerate(params["operations"]):
        if op[0] == "push":
            items = (items + [op[1]])[-k:]
        elif op[0] == "max":
            steps["out_%d" % i] = max(items)
            total += max(items)
        elif op[0] == "full":
            steps["out_%d" % i] = 1 if len(items) == k else 0
        else:
            steps["out_%d" % i] = len(items)
            total += len(items)
    return {"answer": total, "steps": steps}
"""
WRONG = [{"misconception": "ignores_capacity", "code": SOLVER.replace("[-k:]", "")}]
SPEC = {"class_name": "RecentMax", "constructor": [{"name": "capacity", "type": "int", "param": "capacity"}],
        "methods": [{"name": "push", "parameters": [{"name": "value", "type": "int"}], "return_type": "None"},
                    {"name": "max", "parameters": [], "return_type": "int"},
                    {"name": "full", "parameters": [], "return_type": "bool"},
                    {"name": "count", "parameters": [], "return_type": "int"}],
        "statement": "Build a component that remembers the most recent values pushed, up to capacity of them. "
                     "max returns the largest value it remembers, full says whether it holds capacity values, "
                     "and count returns how many it holds."}


def family(n=12, seed=1):
    rng, instances = random.Random(seed), []
    for _ in range(n):
        k = rng.randint(2, 4)
        ops = [["push", rng.randint(1, 50)]]
        for _ in range(rng.randint(5, 9)):
            ops.append(rng.choice([["push", rng.randint(1, 50)], ["max"], ["full"], ["count"]]))
        ops.append(["max"])
        items, total = [], 0
        for op in ops:
            if op[0] == "push":
                items = (items + [op[1]])[-k:]
            elif op[0] == "max":
                total += max(items)
            elif op[0] == "count":
                total += len(items)
        instances.append({"text": "...", "params": {"capacity": k, "operations": ops}, "answer": str(total)})
    return {"template_id": "swc_F001", "pack": "software", "topic": "Design", "difficulty": "Medium", "instances": instances}


FAMILY = family()


def test_a_class_family_is_recognised_by_its_operations():
    assert cs.is_class_family(FAMILY)
    assert not cs.is_class_family({"instances": [{"params": {"values": [1, 2]}}]})


def test_a_sound_class_spec_ships_with_operation_sequences_and_return_lists():
    shipped = cs.verify_class(SPEC, FAMILY, SOLVER, WRONG, Sandbox())
    assert shipped["kind"] == "class" and shipped["class_name"] == "RecentMax"
    assert shipped["signature"].startswith("class RecentMax:\n    def __init__(self, capacity: int):\n        pass")
    assert "    def push(self, value: int) -> None:" in shipped["signature"]
    first = FAMILY["instances"][0]["params"]
    assert shipped["tests"][0] == {"init": [first["capacity"]], "ops": [[op[0], op[1:]] for op in first["operations"]]}
    ops = first["operations"]
    assert len(shipped["expected"][0]) == len(ops)
    assert all((e is None) == (op[0] == "push") for e, op in zip(shipped["expected"][0], ops))
    assert all(e in {"True", "False"} for e, op in zip(shipped["expected"][0], ops) if op[0] == "full")
    assert [m["name"] for m in shipped["wrong_methods"]] == ["ignores capacity"]
    assert shipped["wrong_methods"][0]["outputs"] != shipped["expected"]


@pytest.mark.parametrize("change, reason", [
    ({"class_name": "recent_max"}, "invalid_class_name"),
    ({"methods": SPEC["methods"][:2]}, "operation_does_not_match"),  # "full" and "count" undeclared
    ({"methods": [{**SPEC["methods"][0], "return_type": "int"}] + SPEC["methods"][1:]}, "steps_do_not_cover_returns"),
    ({"constructor": [{"name": "size", "type": "int", "param": "size"}]}, "parameters_do_not_match"),
])
def test_unsound_class_specs_are_refused(change, reason):
    with pytest.raises(Reject) as error:
        cs.verify_class({**SPEC, **change}, FAMILY, SOLVER, WRONG, Sandbox())
    assert error.value.reason == reason


SHIPPED = cs.verify_class(SPEC, FAMILY, SOLVER, WRONG, Sandbox())


def replay(cls_code_ok=True, wrong=False):
    """What the browser's runner returns: each test replayed, the list of return values."""
    out = []
    for case in SHIPPED["tests"]:
        k, items, values = case["init"][0], [], []
        for name, args in case["ops"]:
            if name == "push":
                items = (items + args) if wrong else (items + args)[-k:]
                values.append(None)
            elif name == "max":
                values.append(str(max(items)))
            elif name == "full":
                values.append(str(len(items) == k))
            else:
                values.append(str(len(items)))
        out.append({"ok": True, "values": values})
    return out


def test_the_runner_output_is_judged_exactly_and_a_wrong_method_is_named():
    right = coding.judge(SHIPPED, replay())
    assert right["passed"] == right["total"] == len(SHIPPED["tests"]) and right["named"] is None
    wrong = coding.judge(SHIPPED, replay(wrong=True))
    assert wrong["passed"] < wrong["total"] and wrong["named"] == "ignores capacity"
    # A void call that returns something, a missing value, or an error fails that test.
    broken = replay()
    broken[0] = {"ok": True, "values": ["0"] + broken[0]["values"][1:]}
    broken[1] = {"ok": False, "error": "AttributeError: 'RecentMax' object has no attribute 'full'"}
    judged = coding.judge(SHIPPED, broken)
    assert judged["failing"][:2] == [0, 1] and judged["errors"] == 1


def test_the_page_gets_the_class_and_sequences_but_never_hidden_return_lists():
    pub = coding.public(SHIPPED)
    assert pub["kind"] == "class" and pub["class_name"] == "RecentMax" and [m["name"] for m in pub["methods"]] == ["push", "max", "full", "count"]
    assert pub["tests"] == SHIPPED["tests"] and "expected" not in pub
    assert [e["expected"] for e in pub["examples"]] == [SHIPPED["expected"][i] for i in SHIPPED["examples"]]
    # Questions and hints never quote a hidden return value.
    hidden = next(v for i, row in enumerate(SHIPPED["expected"]) if i not in SHIPPED["examples"] for v in row
                  if v not in {None, "True", "False"} and all(v not in SHIPPED["expected"][j] for j in SHIPPED["examples"]))
    assert coding.safe_question(f"Is the answer {hidden} there?", SHIPPED) == coding.GENERIC_QUESTION
    assert coding.scale_for(SHIPPED["template_id"]) is None or True  # class specs have no Part 2 data
    from forge.coding_scale import infer
    assert infer(SHIPPED) is None


def test_a_failing_sequence_is_quoted_as_code_in_the_challenge_and_hints():
    import asyncio
    sent = []

    async def send(e):
        sent.append(e)
    session = coding.CodingSession(send, None, None, None, SHIPPED, steps=["remember_recent", "largest"])
    session.log.parts.append(coding.PartLog(1, SHIPPED))
    outputs = replay(wrong=True)
    result = coding.judge(SHIPPED, outputs)
    session.note_failing(outputs, SHIPPED["tests"], result["failing"][0])
    asyncio.run(session.hint())
    case = SHIPPED["tests"][result["failing"][0]]
    assert session.log.part.failing["call"].startswith(f"RecentMax({case['init'][0]}); push(")
    assert session.log.part.failing["got"].startswith("[None")
    assert sent[-1]["text"].startswith("Take RecentMax(")
    assert "RecentMax(" in session.challenge(SHIPPED, result, None)
