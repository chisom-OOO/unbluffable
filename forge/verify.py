"""Code gates. No model-produced code is evaluated in this process."""
import itertools
import math
import random
import re
import string
from difflib import SequenceMatcher
from fractions import Fraction

from forge.data import number
from forge.errors import Reject

LABEL = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def parameter_grid(parameters):
    if not 1 <= len(parameters) <= 8 or len({p["name"] for p in parameters}) != len(parameters):
        raise Reject("parameters", "invalid_names")
    grids, original = {}, {}
    for param in parameters:
        name = param["name"]
        if not LABEL.fullmatch(name):
            raise Reject("parameters", "invalid_names")
        lo, hi, step, value = (number(param[key]) for key in ("minimum", "maximum", "step", "original"))
        if step <= 0 or hi < lo or (hi - lo) / step > 10000 or (hi - lo) % step or not lo <= value <= hi or (value - lo) % step:
            raise Reject("parameters", "invalid_range")
        grids[name] = [str(lo + i * step) for i in range(int((hi - lo) / step) + 1)]
        original[name] = str(value)
    return grids, original


def points_for(parameters, count=8):
    grids, original = parameter_grid(parameters)
    points = [original]
    for name, values in grids.items():
        points.extend([{**original, name: values[0]}, {**original, name: values[-1]}])
    points.extend([{name: values[0] for name, values in grids.items()},
                   {name: values[-1] for name, values in grids.items()}])
    seen, result = set(), []
    def add(point):
        key = tuple(sorted(point.items()))
        if key not in seen:
            seen.add(key)
            result.append(point)
    for point in points:
        add(point)
    rng = random.Random(173)
    for _ in range(1000):
        if len(result) >= count:
            break
        add({name: rng.choice(values) for name, values in grids.items()})
    if len(result) < count:
        # Deterministic exhaustion for small grids that random sampling missed.
        for values in itertools.islice(itertools.product(*grids.values()), 10000):
            add(dict(zip(grids, values)))
            if len(result) >= count:
                break
    if len(result) < count:
        raise Reject("parameters", "fewer_than_eight_instances")
    return result, original


def render(text, params):
    used = set()
    try:
        for _, name, spec, conversion in string.Formatter().parse(text):
            if name is not None:
                if name not in params or spec or conversion:
                    raise ValueError()
                used.add(name)
        if not used or not set(params) <= used:
            raise ValueError()
        return text.format_map(params)
    except (ValueError, KeyError):
        raise Reject("render", "invalid_template_fields") from None


def validate_variant(variant, params):
    render(variant["text"], params)
    if not 2 <= len(variant["wrong"]) <= 4 or len({w["misconception"] for w in variant["wrong"]}) != len(variant["wrong"]):
        raise Reject("wrong_methods", "need_two_to_four_named_methods")
    if not variant["step_names"] or len(set(variant["step_names"])) != len(variant["step_names"]):
        raise Reject("steps", "missing_named_steps")
    for name in [*variant["step_names"], *(w["misconception"] for w in variant["wrong"])]:
        if not LABEL.fullmatch(name):
            raise Reject("steps", "invalid_name")


def near_verbatim(text, statements):
    target = re.findall(r"\w+", text.casefold())
    if not target:
        return 1.0
    score = 0.0
    for statement in statements:
        source = re.findall(r"\w+", statement.casefold())
        a = set(zip(target, target[1:], target[2:]))
        b = set(zip(source, source[1:], source[2:]))
        containment = len(a & b) / max(1, min(len(a), len(b)))
        # Skip the expensive alignment only when there is no lexical overlap.
        ratio = SequenceMatcher(None, source, target, autojunk=False).ratio() if set(source) & set(target) else 0.0
        score = max(score, containment, ratio)
    return round(score, 6)


def ambiguity(alternatives, answer):
    if len(alternatives) > 3:
        raise Reject("readings", "too_many_readings")
    numbers = []
    for reading in alternatives:
        value, tolerance = number(reading["answer"]), number(reading["tolerance"])
        if tolerance < 0:
            raise Reject("readings", "invalid_tolerance")
        numbers.append(str(value))
        if abs(value - answer.value) <= answer.tolerance + tolerance:
            raise Reject("readings", "not_ruled_out", {"alternative_answer": str(value)})
    return {"passed": True, "count": len(numbers), "answers": numbers}


def instances(variant, points, simulator, sandbox, tolerance, trials):
    result, mc = [], []
    for index, params in enumerate(points):
        solved = sandbox.run(variant["solver"], "solve", params)
        answer = number(solved["answer"])
        steps = solved["steps"]
        if {row["name"] for row in steps} != set(variant["step_names"]):
            raise Reject("steps", "names_do_not_match")
        wrong = []
        for method in variant["wrong"]:
            value = number(sandbox.run(method["code"], "solve", params)["answer"])
            if abs(value - answer) <= tolerance:
                raise Reject("wrong_methods", "collision", {"point": index, "value": str(value)})
            wrong.append({"value": str(value), "misconception": method["misconception"]})
        sampled = sandbox.run(simulator, "sample", params, trials=trials, seed=941 + index)
        mean, se = number(sampled["mean"]), sampled["se"]
        if (sampled["trials"] < trials or sampled["draws"] < trials or not math.isfinite(se) or se < 0
                or abs(mean - answer) > Fraction.from_float(4 * se)):
            raise Reject("monte_carlo", "outside_four_se", {"point": index, "answer": str(answer),
                         "mean": str(mean), "se": se, "trials": sampled["trials"]})
        mc.append({"params": params, "answer": str(answer), "mean": str(mean), "se": se,
                   "error": float(abs(mean - answer)), "limit": 4 * se,
                   "trials": sampled["trials"], "draws": sampled["draws"]})
        result.append({"text": render(variant["text"], params), "params": params, "answer": str(answer),
                       "tolerance": str(tolerance), "wrong": wrong, "steps": steps})
    if not any(row["se"] > 0 for row in mc):
        raise Reject("monte_carlo", "no_stochastic_outcomes")
    return result, {"passed": True, "points": mc, "point_count": len(points), "standard_errors": 4}
