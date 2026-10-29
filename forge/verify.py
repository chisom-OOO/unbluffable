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


def points_for(parameters, count=20, reserve=60):
    """Order a bounded candidate pool by coverage, retaining spare collision replacements."""
    grids, original = parameter_grid(parameters)
    capacity = math.prod(len(values) for values in grids.values())
    if count < 20 or capacity < count:
        raise Reject("parameters", "fewer_than_twenty_instances")
    mandatory = [original]
    for name, values in grids.items():
        mandatory.extend([{**original, name: values[0]}, {**original, name: values[-1]}])
    mandatory.extend([{name: values[0] for name, values in grids.items()},
                      {name: values[-1] for name, values in grids.items()}])
    pool = {}
    def add(point):
        pool.setdefault(tuple(sorted(point.items())), point)
    for point in mandatory:
        add(point)
    rng = random.Random(173)
    if capacity <= 2048:
        for values in itertools.product(*grids.values()):
            add(dict(zip(grids, values)))
    else:
        # Stratify each dimension, shuffle independently, and add a random reserve.
        strata = {}
        for name, values in grids.items():
            strata[name] = [values[i * (len(values) - 1) // 511] for i in range(512)]
            rng.shuffle(strata[name])
        for i in range(512):
            add({name: values[i] for name, values in strata.items()})
            add({name: rng.choice(values) for name, values in grids.items()})
    points = list(pool.values())
    scales = {name: {value: i / max(1, len(values) - 1) for i, value in enumerate(values)}
              for name, values in grids.items()}
    vectors = [tuple(scales[name][point[name]] for name in grids) for point in points]
    distances = [math.inf] * len(points)
    selected, used = [], set()
    def choose(index):
        selected.append(points[index])
        used.add(index)
        for i, vector in enumerate(vectors):
            distance = sum((a - b) ** 2 for a, b in zip(vector, vectors[index]))
            distances[i] = min(distances[i], distance)
        distances[index] = -1
    # Pool insertion preserves the original, individual edges and joint edges.
    mandatory_count = len({tuple(sorted(point.items())) for point in mandatory})
    target = min(len(points), max(count, mandatory_count) + reserve)
    for index in range(mandatory_count):
        choose(index)
    while len(selected) < target:
        choose(max((i for i in range(len(points)) if i not in used), key=lambda i: distances[i]))
    if len(selected) < count:
        raise Reject("parameters", "fewer_than_twenty_instances")
    return selected, original


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


def snake_case(name):
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", str(name))
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(name))
    return re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")


def normalize_variant(variant):
    variant = dict(variant)
    variant["step_names"] = [snake_case(name) for name in variant["step_names"]]
    if (len(set(variant["step_names"])) != len(variant["step_names"])
            or any(not LABEL.fullmatch(name) for name in variant["step_names"])):
        raise Reject("steps", "invalid_step_names")
    return variant


def run_code(sandbox, code, mode, params, **kwargs):
    try:
        return sandbox.run(code, mode, params, **kwargs)
    except TypeError:
        raise Reject("sandbox", "TypeError", {"component": "simulator" if mode == "sample" else "draft"}) from None
    except Reject as error:
        raise Reject(error.stage, error.reason, {**error.details,
                     "component": "simulator" if mode == "sample" else "draft"}) from None


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


def ambiguity(alternatives, answer, equivalent=None):
    if len(alternatives) > 3:
        raise Reject("readings", "too_many_readings")
    numbers, equivalent_readings = [], []
    for index, reading in enumerate(alternatives):
        value, tolerance = number(reading["answer"]), number(reading["tolerance"])
        if tolerance < 0:
            raise Reject("readings", "invalid_tolerance")
        numbers.append(str(value))
        if abs(value - answer.value) <= answer.tolerance + tolerance:
            if abs(value - answer.value) <= answer.tolerance and equivalent is not None:
                details = equivalent(reading)
                equivalent_readings.append({"reading_index": index, "status": "equivalent reading", **details})
            else:
                raise Reject("readings", "not_ruled_out", {"alternative_answer": str(value)})
    return {"passed": True, "count": len(numbers), "answers": numbers,
            "equivalent_readings": equivalent_readings}


def instances(variant, points, simulator, sandbox, tolerance, trials, *, limit=20):
    result, mc, seen, dropped = [], [], set(), 0
    for index, params in enumerate(points):
        key = tuple(sorted(params.items()))
        if key in seen:
            continue
        seen.add(key)
        solved = run_code(sandbox, variant["solver"], "solve", params)
        answer = number(solved["answer"])
        steps = [{**row, "name": snake_case(row["name"])} for row in solved["steps"]]
        if len({row["name"] for row in steps}) != len(steps):
            raise Reject("steps", "invalid_step_names")
        if {row["name"] for row in steps} != set(variant["step_names"]):
            raise Reject("steps", "names_do_not_match")
        wrong, values, gaps = [], [], []
        collision = False
        for method in variant["wrong"]:
            value = number(run_code(sandbox, method["code"], "solve", params)["answer"])
            gap = abs(value - answer)
            if gap <= tolerance:
                collision = True
            wrong.append({"value": str(value), "misconception": method["misconception"]})
            values.append(value)
            gaps.append({"misconception": method["misconception"], "absolute_gap": str(gap),
                         "relative_gap": str(gap / abs(answer)) if answer else None})
        if collision:
            dropped += 1
            continue
        pair_gap = min(abs(a - b) for a, b in itertools.combinations(values, 2))
        sampled = run_code(sandbox, simulator, "sample", params, trials=trials, seed=941 + index)
        mean, se = number(sampled["mean"]), sampled["se"]
        if (sampled["trials"] < trials or sampled["draws"] < trials or not math.isfinite(se) or se < 0
                or abs(mean - answer) > Fraction.from_float(4 * se)):
            raise Reject("monte_carlo", "outside_four_se", {"point": index, "answer": str(answer),
                         "mean": str(mean), "se": se, "trials": sampled["trials"]})
        mc.append({"params": params, "answer": str(answer), "mean": str(mean), "se": se,
                   "error": float(abs(mean - answer)), "limit": 4 * se,
                   "trials": sampled["trials"], "draws": sampled["draws"]})
        result.append({"text": render(variant["text"], params), "params": params, "answer": str(answer),
                       "tolerance": str(tolerance), "wrong": wrong, "steps": steps,
                       "separation": {"by_misconception": gaps, "min_wrong_pair_gap": str(pair_gap)}})
        if limit is not None and len(result) >= limit:
            break
    if len(result) < 20:
        raise Reject("wrong_methods", "fewer_than_twenty_instances",
                     {"survivors": len(result), "dropped_collisions": dropped})
    if not any(row["se"] > 0 for row in mc):
        raise Reject("monte_carlo", "no_stochastic_outcomes")
    return result, {"passed": True, "points": mc, "point_count": len(result),
                    "dropped_collisions": dropped, "candidates_checked": len(seen), "standard_errors": 4}
