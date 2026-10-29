"""Invented toy problem; no bank-derived fixtures."""
import copy
from decimal import Decimal
from fractions import Fraction
import re
from types import SimpleNamespace

from forge.data import Question
from forge.models import State

SOLVER = """from fractions import Fraction
def solve(params):
    return {"answer": Fraction(params["n"], 2), "steps": {"half": Fraction(params["n"], 2)}}
"""
WRONG_ONE = """def solve(params):
    return params["n"]
"""
WRONG_TWO = """from fractions import Fraction
def solve(params):
    return Fraction(params["n"], 3)
"""
SIM = """def sample(params, rng):
    return params["n"] if rng.random() < 0.5 else 0
"""
PART_SOLVER = """from fractions import Fraction
def solve(params):
    value = Fraction(params["n"] * params["k"], 2)
    return {"answer": value, "steps": {"half_total": value}}
"""
PART_WRONG_ONE = """def solve(params):
    return params["n"] * params["k"]
"""
PART_WRONG_TWO = """from fractions import Fraction
def solve(params):
    return Fraction(params["n"] * params["k"], 3)
"""
PART_SIM = """def sample(params, rng):
    return sum(params["n"] if rng.random() < 0.5 else 0 for i in range(params["k"]))
"""
STATEMENT = "An invented exercise asks for the arithmetic average of zero and four."
SOLUTION = "The final result is 2."


def question():
    return Question("source-private-493", "Private toy title", "Easy", ("probability",),
                    STATEMENT, SOLUTION, "f" * 64)


def draft(part2=False):
    extra = {"enabled": part2, "text": "", "parameter": {"name": "", "minimum": "", "maximum": "", "step": "", "original": ""},
             "solver": "", "wrong": [], "step_names": []}
    if part2:
        extra.update(text="A beacon flashes with probability 1/2. A flash earns {n} credits. The experiment is repeated {k} times. What is the expected total reward?",
            parameter={"name": "k", "minimum": "1", "maximum": "3", "step": "1", "original": "2"},
            solver=PART_SOLVER, wrong=[{"misconception": "ignores_probability", "code": PART_WRONG_ONE},
                                      {"misconception": "uses_three_cases", "code": PART_WRONG_TWO}],
            step_names=["half_total"])
    return {"text": "A beacon flashes with probability 1/2. A flash earns {n} credits. What is the expected reward?",
            "parameters": [{"name": "n", "minimum": "1", "maximum": "12", "step": "1", "original": "4"}],
            "solver": SOLVER, "wrong": [{"misconception": "ignores_probability", "code": WRONG_ONE},
                                       {"misconception": "uses_three_cases", "code": WRONG_TWO}],
            "step_names": ["half"], "part2": extra}


def response_for(stage, payload, blueprint=None):
    if stage == "answer_pass":
        return {"class": "numeric_single", "answer": "2", "quote": SOLUTION, "tolerance": "0", "tolerance_quote": "none"}
    if stage == "author":
        return copy.deepcopy(blueprint or draft())
    if stage == "simulator":
        return {"code": SIM, "part2_code": PART_SIM}
    if stage == "reading_model":
        return {"alternatives": []}
    if stage in {"blind_model", "part2_blind_model"}:
        n = int(re.search(r"earns (\d+) credits", payload["question"])[1])
        match = re.search(r"repeated (\d+) times", payload["question"])
        return {"answer": str(Fraction(n * (int(match[1]) if match else 1), 2))}
    raise AssertionError(stage)


class FakeModels:
    def __init__(self, root, part2=False):
        self.state = State(root)
        self.author = SimpleNamespace(model="meta-models/muse-spark-open-1026")
        self.checker = SimpleNamespace(model="muse-spark-1.3")
        self.budget = Decimal(40)
        self.calls, self.overrides = [], {}
        self.blueprint = draft(part2)

    def spent(self):
        return Decimal(0)

    def call(self, stage, payload, *args, **kwargs):
        self.calls.append((stage, copy.deepcopy(payload)))
        return copy.deepcopy(self.overrides.get(stage, response_for(stage, payload, self.blueprint)))


class FakeSandbox:
    def __init__(self):
        self.solver_offset = 0
        self.sample_offset = 0
        self.draws = True
        self.se = .01
        self.bad_steps = False
        self.part2_failure = False

    def run(self, code, mode, params, trials=20000, seed=0):
        n, k = Fraction(params["n"]), Fraction(params.get("k", "1"))
        correct = n * k / 2
        if mode == "sample":
            offset = self.sample_offset + (1 if self.part2_failure and code == PART_SIM else 0)
            return {"mean": str(correct + offset), "se": self.se, "trials": trials, "draws": trials if self.draws else 0}
        if code in {SOLVER, PART_SOLVER}:
            return {"answer": str(correct + self.solver_offset),
                    "steps": [{"name": "bad" if self.bad_steps else "half_total" if code == PART_SOLVER else "half", "value": str(correct)}]}
        if code in {WRONG_ONE, PART_WRONG_ONE}:
            return {"answer": str(n * k), "steps": []}
        if code in {WRONG_TWO, PART_WRONG_TWO}:
            return {"answer": str(n * k / 3), "steps": []}
        raise AssertionError("Unknown synthetic code")
