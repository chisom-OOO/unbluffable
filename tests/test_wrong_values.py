"""Wrong values that name no mistake, and values two mistakes share: dropped or merged at load
and in the forge, never used to tell mistakes apart. No model calls."""

import random
from fractions import Fraction

from engine.bank import Bank, aimed_values, own_value, parse_instance, parse_template, twin_choice
from engine.checker import is_sentinel
from engine.coding import Outcome, code_answer
from engine.checker import parse_value
from forge.families import separation
from forge.verify import instances, points_for
from forge_fakes import SIM, WRONG_ONE, FakeSandbox, draft

GREEDY, LONGEST, DIRECT = "greedy_cheapest_outgoing_edge", "longest_path_instead_of_shortest", "direct_edge_only_ignores_multi_hop"


def e05_original():
    """The shape of family_F094's instance 7 (evidence item e05): answer 22, greedy and longest
    path both give 25, and the direct-edge method returns the 10**18 "unreachable" stand-in."""
    return {"text": "Starting at 0, what is the cheapest route cost to 4?", "params": {"n": 5}, "answer": "22",
            "tolerance": "0",
            "wrong": [{"value": "25", "misconceptions": [GREEDY, LONGEST]},
                      {"value": "1000000000000000000", "misconceptions": [DIRECT]}],
            "steps": [{"name": "cheapest_cost_to_target", "value": "22"}]}


# --- Sentinels ---------------------------------------------------------------------

def test_sentinels_are_infinity_stand_ins_far_from_the_answer():
    assert is_sentinel(Fraction(10 ** 18), Fraction(22))
    assert is_sentinel(Fraction(2 ** 63 - 1), Fraction(12)) and is_sentinel(Fraction(-(2 ** 31)), Fraction(7))
    assert not is_sentinel(Fraction(4500000000), Fraction(9))  # family_F008: a real large wrong value
    assert not is_sentinel(Fraction(10 ** 9), Fraction(2 * 10 ** 8))  # next to a large answer, it may be real
    assert not is_sentinel(Fraction(25), Fraction(22))


def test_a_sentinel_wrong_value_is_dropped_at_load():
    inst = parse_instance(e05_original(), "e05")
    assert [nv.value for nv in inst.wrong] == [Fraction(25)]
    assert all(DIRECT not in nv.misconception for nv in inst.wrong)


def test_saying_the_sentinel_is_not_a_named_mistake():
    template = parse_template({"template_id": "t", "topic": "Discrete optimisation", "topics": ["Discrete optimisation"], "difficulty": "Hard",
                               "instances": [e05_original()] * 8})
    from engine.bank import instance_puzzle
    puzzle = instance_puzzle(template, template.instances[0], 0)
    assert code_answer(puzzle, parse_value("1000000000000000000"), "valid").outcome is Outcome.OTHER_WRONG


def test_the_forge_drops_a_sentinel_method_value():
    values, gaps = separation(Fraction(22), [(GREEDY, Fraction(25)), (DIRECT, Fraction(10 ** 18))])
    assert values == [{"value": "25", "misconceptions": [GREEDY]}]
    assert [g["misconception"] for g in gaps["by_misconception"]] == [GREEDY]
    assert gaps["min_wrong_pair_gap"] is None


class SentinelSandbox(FakeSandbox):
    def run(self, code, mode, params, **kwargs):
        if mode == "solve" and code == WRONG_ONE:
            return {"answer": str(10 ** 18), "steps": []}
        return super().run(code, mode, params, **kwargs)


def test_forge_instances_never_ship_a_sentinel_wrong_value():
    variant = draft()
    points, _ = points_for(variant["parameters"])
    rows, _ = instances(variant, points, SIM, SentinelSandbox(), Fraction(0), 1000)
    assert len(rows) == 20
    for row in rows:
        assert all(Fraction(w["value"]) != 10 ** 18 for w in row["wrong"])
        assert {name for w in row["wrong"] for name in w["misconceptions"]} == {"uses_three_cases"}
        assert row["separation"]["min_wrong_pair_gap"] is None


# --- Shared values -------------------------------------------------------------------

def test_one_value_keeps_every_mistake_that_gives_it():
    raw = {**e05_original(), "wrong": [{"value": "25", "misconception": GREEDY}, {"value": "25", "misconception": LONGEST},
                                       {"value": "24", "misconception": DIRECT}]}
    inst = parse_instance(raw, "split rows")
    assert [(nv.value, nv.misconception) for nv in inst.wrong] == [(Fraction(25), f"{GREEDY} / {LONGEST}"),
                                                                  (Fraction(24), DIRECT)]
    values, _ = separation(Fraction(22), [(GREEDY, Fraction(25)), (LONGEST, Fraction(25))])
    assert values == [{"value": "25", "misconceptions": [GREEDY, LONGEST]}]


def test_an_answer_on_a_shared_value_names_both_mistakes():
    template = parse_template({"template_id": "t", "topic": "Discrete optimisation", "topics": ["Discrete optimisation"], "difficulty": "Hard",
                               "instances": [e05_original()] * 8})
    from engine.bank import instance_puzzle
    puzzle = instance_puzzle(template, template.instances[0], 0)
    obs = code_answer(puzzle, parse_value("25"), "valid")
    assert obs.outcome is Outcome.NAMED_WRONG and obs.misconception == f"{GREEDY} / {LONGEST}"


def _route(i, greedy, longest, answer=20):
    return {"text": f"Route {i}: cheapest cost?", "params": {"i": i}, "answer": str(answer + i), "tolerance": "0",
            "wrong": [{"value": str(greedy + i), "misconception": GREEDY}, {"value": str(longest + i), "misconception": LONGEST}],
            "steps": [{"name": "cost", "value": str(answer + i)}]}


def _template(rows):
    """Padded to the bank's eight instances with routes that name neither mistake."""
    filler = [{**_route(10 + i, 0, 0), "wrong": [{"value": str(100 + i), "misconception": DIRECT}]}
              for i in range(8 - len(rows))]
    return parse_template({"template_id": "t", "topic": "Discrete optimisation", "topics": ["Discrete optimisation"],
                           "difficulty": "Hard", "instances": rows + filler})


def test_a_shared_value_is_not_distinguishing_for_the_twin():
    """Suspected "greedy / longest" (one shared value on the original): the twin is one where
    the two give different numbers, even though a shared-value instance is further away."""
    rows = [_route(0, 25, 25), _route(1, 90, 90), _route(2, 30, 40), _route(3, 26, 27)]
    template = _template(rows)
    suspect = f"{GREEDY} / {LONGEST}"
    assert not own_value(template.instances[1], suspect) and own_value(template.instances[2], suspect)
    assert [nv.misconception for nv in aimed_values(template.instances[1], suspect)] == [suspect]
    index, why = twin_choice(template, 0, random.Random(0), suspect)
    assert index == 2  # instance 1's gap (70) is larger, but there both mistakes give 90
    # The diagnostic names the mistake whose value the twin actually shows.
    assert (why.misconception, why.wrong, why.suspected) == (GREEDY, Fraction(32), True)


def test_without_a_split_instance_the_shared_one_is_still_used():
    rows = [_route(0, 25, 25), _route(1, 90, 90), _route(2, 60, 60)]
    template = _template(rows)
    index, why = twin_choice(template, 0, random.Random(0), f"{GREEDY} / {LONGEST}")
    assert index == 1 and why.misconception == f"{GREEDY} / {LONGEST}"


def test_the_live_bank_loads_with_no_sentinel_and_no_repeated_wrong_value():
    from engine.bank import load_bank
    bank: Bank = load_bank()
    for template in bank.templates.values():
        for inst in template.instances:
            values = [nv.value for nv in inst.wrong]
            assert len(values) == len(set(values)), template.template_id
            assert not any(is_sentinel(v, inst.answer) for v in values), template.template_id
