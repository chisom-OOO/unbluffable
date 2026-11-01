"""A candidate's own question for the BYOQ tests (decision log 38), and model outputs for it.

Synthetic: written by hand for the tests, not recorded from a model. The question is an
ordinary textbook one (two reds without replacement), not an interview question.
"""

QUESTION = ("A bag has 3 red and 5 blue balls. Two balls are drawn without replacement. "
            "What is the probability that both are red?")
TEMPLATE = ("A bag has {red} red and {blue} blue balls. Two balls are drawn without replacement. "
            "What is the probability that both are red?")
PARAMETERS = [{"name": "red", "minimum": "2", "maximum": "9", "step": "1", "original": "3"},
              {"name": "blue", "minimum": "2", "maximum": "9", "step": "1", "original": "5"}]

SOLVER = """from fractions import Fraction
def solve(params):
    r, b = params["red"], params["blue"]
    first = Fraction(r, r + b)
    both = first * Fraction(r - 1, r + b - 1)
    return {"answer": both, "steps": {"first_red": first, "both_red": both}}
"""

CHECK = """import math
from fractions import Fraction
def solve(params):
    r, b = params["red"], params["blue"]
    return {"answer": Fraction(math.comb(r, 2), math.comb(r + b, 2))}
"""

SIMULATION = """import itertools
from fractions import Fraction
def solve(params):
    balls = ["r"] * params["red"] + ["b"] * params["blue"]
    pairs = list(itertools.combinations(range(len(balls)), 2))
    hits = sum(1 for i, j in pairs if balls[i] == "r" and balls[j] == "r")
    return {"answer": Fraction(hits, len(pairs))}
"""

# Agrees on the original, disagrees when there are 9 red balls (an edge, always checked).
DISAGREES = """from fractions import Fraction
def solve(params):
    r, b = params["red"], params["blue"]
    both = Fraction(r * (r - 1), (r + b) * (r + b - 1))
    return {"answer": both + (1 if r == 9 else 0)}
"""

LOOPS = """def solve(params):
    n = 0
    while True:
        n += 1
"""

WITH_REPLACEMENT = """from fractions import Fraction
def solve(params):
    return Fraction(params["red"], params["red"] + params["blue"]) ** 2
"""
ONE_DRAW = """from fractions import Fraction
def solve(params):
    return Fraction(params["red"], params["red"] + params["blue"])
"""
# Equals the right answer on the original question: it can't tell the mistake apart, so dropped.
COLLIDES = """from fractions import Fraction
def solve(params):
    r, b = params["red"], params["blue"]
    if r == 3 and b == 5:
        return Fraction(3, 28)
    return Fraction(r, r + b) ** 3
"""

WRONG = [{"misconception": "with_replacement", "code": WITH_REPLACEMENT},
         {"misconception": "one_draw_only", "code": ONE_DRAW},
         {"misconception": "squares_again", "code": WITH_REPLACEMENT}]  # the same values: dropped

READ = {"question_text": QUESTION, "given_numbers": ["3", "5", "Two"], "single_exact_numeric_answer": True,
        "topic": "Discrete probability", "stated_answer": "none"}


def outputs(*, check=CHECK, simulation=SIMULATION, enumerable=True, wrong=None, template=TEMPLATE,
            parameters=None, solver=SOLVER):
    """Each gate stage's parsed model output."""
    shared = {"template": template, "parameters": parameters or PARAMETERS}
    return {
        "parameterise": {**shared, "solver": solver, "step_names": ["first_red", "both_red"]},
        "check": {"solver": check},
        "simulation": {"enumerable": enumerable, "solver": simulation if enumerable else "none"},
        "wrong_methods": {"wrong": WRONG if wrong is None else wrong},
    }


class FakeCall:
    """call(stage, role, payload, schema, prompt) from a table; records who was asked what."""

    def __init__(self, table):
        self.table, self.calls = table, []

    def __call__(self, stage, role, payload, schema, prompt):
        self.calls.append((stage, role, payload))
        return self.table[stage]
