from fractions import Fraction

import pytest

from forge.sandbox import Sandbox
from forge.errors import Reject


EXACT = """from fractions import Fraction
def solve(params):
    return {"answer": Fraction(params["n"], 2), "steps": {"half": Fraction(params["n"], 2)}}
"""
SIM = """def sample(params, rng):
    return params["n"] if rng.random() < 0.5 else 0
"""


def test_subprocess_exact_solver_and_independent_sample_statistics():
    sandbox = Sandbox(timeout_s=5, memory_mb=128)
    solved = sandbox.run(EXACT, "solve", {"n": "4"})
    sampled = sandbox.run(SIM, "sample", {"n": "4"}, trials=2000, seed=7)
    assert solved["answer"] == "2" and solved["steps"] == [{"name": "half", "value": "2"}]
    assert sampled["draws"] >= 2000 and sampled["trials"] == 2000
    assert abs(float(Fraction(sampled["mean"])) - 2) <= 4 * sampled["se"]


@pytest.mark.parametrize("code", [
    "import socket\ndef solve(params): return 1",
    "import os\ndef solve(params): return 1",
    "from fractions import sys\ndef solve(params): return 1",
    "def solve(params): return params.__class__",
    "def solve(params): return open('forbidden').read()",
    "def solve(params): return __import__('socket')",
])
def test_forbidden_capabilities_fail_closed(code):
    with pytest.raises(Reject):
        Sandbox().run(code, "solve", {})


def test_simulator_must_draw_events_and_cannot_reseed_per_sample():
    for code in ["def sample(params, rng): return 0.5",
                 "import random\ndef sample(params, rng):\n random.seed(7)\n return random.random()"]:
        with pytest.raises(Reject):
            Sandbox().run(code, "sample", {}, trials=20)


def test_infinite_loop_is_terminated():
    with pytest.raises(Reject):
        Sandbox(timeout_s=.3).run("def solve(params):\n while True: pass", "solve", {})


def test_generated_code_has_no_environment_access_and_memory_is_bounded():
    with pytest.raises(Reject):
        Sandbox(memory_mb=96).run("def solve(params): return [0] * 100000000", "solve", {})


def test_random_constructor_alias_cannot_reseed_the_simulator():
    code = "from random import Random as R\ndef sample(params, rng): return R(7).random()"
    with pytest.raises(Reject):
        Sandbox().run(code, "sample", {}, trials=20)


def test_each_sample_gets_fresh_generated_globals():
    code = "history = []\ndef sample(params, rng):\n history.append(1)\n rng.random()\n return len(history)"
    result = Sandbox().run(code, "sample", {}, trials=20)
    assert result["mean"] == "1" and result["se"] == 0 and result["draws"] == 20


@pytest.mark.parametrize("code", [
    "def sample(params, rng):\n params['n'] = 3\n return rng.random()",
    "import random\ndef sample(params, rng):\n random.random = lambda: 1\n return rng.random()",
])
def test_parameters_and_shared_random_facade_cannot_be_mutated(code):
    with pytest.raises(Reject):
        Sandbox().run(code, "sample", {"n": "1"}, trials=20)
