"""Coding specs whose parameters are records or trees with gaps (decision log 30 batches,
qd_ and swf_): a declared type the data doesn't have is corrected from the instances, so a
verified family solver is never refused for "type_mismatch". Real sandbox, fake model."""

import copy
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from forge import coding_specs as cs
from forge.errors import Reject
from forge.models import State
from forge.sandbox import Sandbox

SOLVER = """def solve(params):
    bought = sum(f["qty"] for f in params["fills"] if f["side"] == "buy")
    sold = sum(f["qty"] for f in params["fills"] if f["side"] == "sell")
    return {"answer": [bought, sold], "steps": {"net": bought - sold}}
"""
TREE = """def solve(params):
    return {"answer": [v for v in params["level_order"] if v is not None and v != params["key"]], "steps": {}}
"""


def fills_family(n=8):
    instances = []
    for i in range(n):
        fills = [{"price": 100 + i, "qty": 3 + i, "side": "buy"}, {"price": 101, "qty": 2, "side": "sell"}]
        instances.append({"text": "...", "params": {"fills": fills}, "answer": json.dumps([3 + i, 2])})
    return {"template_id": "qd_F901", "pack": "quant_dev", "topic": "P&L accounting", "difficulty": "Medium",
            "coding_only": True, "instances": instances}


def tree_family(n=8):
    instances = []
    for i in range(n):
        order = [17 + i, 6, 49, 4, 7, None, 50]
        instances.append({"text": "...", "params": {"level_order": order, "key": 6},
                          "answer": json.dumps([v for v in order if v is not None and v != 6])})
    return {"template_id": "swf_F911", "pack": "software", "topic": "Trees", "difficulty": "Easy", "coding_only": True,
            "instances": instances}


FILLS = {"function_name": "total_quantities", "parameters": [{"name": "fills", "type": "list[str]", "param": "fills"}],
         "return_type": "list[int]", "statement": "Given a list of fills, return the total quantity bought and the total sold."}
TREE_SPEC = {"function_name": "values_without_key", "parameters": [{"name": "level_order", "type": "list[int]", "param": "level_order"},
                                                                     {"name": "key", "type": "int", "param": "key"}],
             "return_type": "list[int]", "statement": "Given a tree in level order with gaps, return its values without the key."}


def test_records_declared_as_strings_are_corrected_to_list_of_dict():
    shipped = cs.verify(FILLS, fills_family(), SOLVER, [], Sandbox())
    assert shipped["parameters"][0]["type"] == "list[dict]"
    assert shipped["signature"] == "def total_quantities(fills: list[dict]) -> list[int]:"
    assert shipped["verification"]["types_corrected_from_data"] == 1
    assert shipped["tests"][0] == [[{"price": 100, "qty": 3, "side": "buy"}, {"price": 101, "qty": 2, "side": "sell"}]]
    assert shipped["expected"][0] == "[3,2]"


def test_a_level_order_tree_with_gaps_is_list_of_int_or_none():
    shipped = cs.verify(TREE_SPEC, tree_family(), TREE, [], Sandbox())
    assert [p["type"] for p in shipped["parameters"]] == ["list[int | None]", "int"]
    assert shipped["verification"]["types_corrected_from_data"] == 1


@pytest.mark.parametrize("value, annotation, ok", [
    ([{"a": 1, "b": [1, None]}], "list[dict]", True), ([{"a": object()}], "list[dict]", False), ([{1: 2}], "list[dict]", False),
    ([1, None, 3], "list[int | None]", True), ([1, "x"], "list[int | None]", False), ([True], "list[int]", False),
])
def test_the_new_types_are_checked_exactly(value, annotation, ok):
    assert cs.check_type(value, annotation) is ok


def test_a_parameter_no_type_fits_is_still_refused():
    family = fills_family()
    family["instances"][2]["params"]["fills"] = "not a list"  # mixed shapes across instances
    with pytest.raises(Reject) as error:
        cs.verify(FILLS, family, SOLVER, [], Sandbox())
    assert error.value.reason == "type_mismatch" and error.value.details == {"variant_index": 0}


class Models:
    """Returns a cached draft: the forge's retry replays recorded calls, so no new spend."""

    def __init__(self, root, draft):
        self.state, self.draft, self.calls = State(root), draft, []
        self.author, self.budget = SimpleNamespace(model="meta-models/muse-spark-open-test"), Decimal(1)

    def call(self, stage, payload, schema, instructions, *, author=False, max_tokens=4000):
        self.calls.append(stage)
        return copy.deepcopy(self.draft)

    def spent(self):
        return Decimal(0)


def test_retry_families_resets_only_the_named_failures_and_ships_them(tmp_path):
    content = tmp_path / "forge"
    content.mkdir()
    (content / "qd_F901.json").write_text(json.dumps(fills_family()), encoding="utf-8")
    models = Models(tmp_path / "work", FILLS)
    items = models.state.data["items"]
    items["qd_F901"] = {"status": "fallback", "draft": FILLS, "failure": {"gate": "spec", "error_class": "type_mismatch"}}
    items["qd_F902"] = {"status": "verified"}
    cs.retry_families(models.state, {"qd_F901", "qd_F902"})
    assert items["qd_F901"]["status"] == "pending" and items["qd_F902"]["status"] == "verified"
    family_items = {"qd_F901": {"status": "verified", "draft": {"solver": SOLVER, "wrong": []}}}
    report = cs.CodingForge(models, Sandbox(), out=tmp_path / "coding", content=content, pack="quant_dev").run(family_items)
    assert report["outcomes"]["qd_F901"] == "verified" and models.calls == ["coding_author"]
    assert json.loads((tmp_path / "coding" / "qd_F901.json").read_text(encoding="utf-8"))["parameters"][0]["type"] == "list[dict]"
