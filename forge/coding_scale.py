"""Part 2 of a coding round (decision log 29): "Now n is up to 100,000; make it fast."

For each verified coding spec (content/coding/), this step infers the shape of its inputs from
the family's own tests (list lengths, value ranges, sorted or distinct lists, a list that is
elementwise at least another, an int that is at least a list's length, otherwise the ints the
tests use), then has the forge's verified solver compute the expected outputs on three large
inputs that forge/scale_gen.py builds inside the sandbox. n is the largest of 100,000, 10,000
and 1,000 at which the solver finishes every input in time; a family whose solver is too slow
even at 1,000, or that errors on small generated inputs, gets no Part 2. No model calls.

Writes content/coding_scale/<template_id>.json (seeds, n, expected outputs, the solver's time
and the browser's time limit).

  python -m forge.coding_scale
"""

from __future__ import annotations

import argparse
import json
import statistics
import zlib
from pathlib import Path

from forge.coding_specs import answer_of
from forge.errors import Reject
from forge.models import atomic_json
from forge.sandbox import Sandbox

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "content" / "coding"
OUT = ROOT / "content" / "coding_scale"
GENERATOR = Path(__file__).with_name("scale_gen.py")
SIZES = (100_000, 10_000, 1_000)
SEEDS = 3
SOLVER_BUDGET_MS = 4000  # the forge solver's time per input for a size to count
SMALL_CHECKS = 12


def infer(spec: dict) -> dict | None:
    """The generator config for a spec's parameters, from its tests; None if not eligible."""
    params = spec["parameters"]
    if not all(p["type"] in {"list[int]", "int", "bool"} for p in params) or not any(p["type"] == "list[int]" for p in params):
        return None
    tests = [dict(zip([p["param"] for p in params], case)) for case in spec["tests"]]
    lists = [p["param"] for p in params if p["type"] == "list[int]"]
    config = []
    for key in lists:
        values = [v for t in tests for v in t[key]]
        if not values:
            return None
        entry = {"key": key, "kind": "list", "lo": min(values), "hi": max(values),
                 "sorted": all(list(t[key]) == sorted(t[key]) for t in tests),
                 "distinct": all(len(set(t[key])) == len(t[key]) for t in tests) and any(len(t[key]) > 1 for t in tests),
                 "same": None, "ge": None}
        for earlier in [c["key"] for c in config]:
            if all(len(t[earlier]) == len(t[key]) for t in tests):
                entry["same"] = earlier
                gaps = [b - a for t in tests for a, b in zip(t[earlier], t[key])]
                if gaps and min(gaps) >= 0:
                    entry["ge"] = {"of": earlier, "lo": min(gaps), "hi": max(gaps)}
                break
        config.append(entry)
    for p in params:
        if p["type"] == "list[int]":
            continue
        key = p["param"]
        seen = sorted({t[key] for t in tests}, key=str)
        if p["type"] == "int":
            for of in lists:
                extra = [t[key] - len(t[of]) for t in tests]
                if min(extra) >= 0:
                    config.append({"key": key, "kind": "int", "len_plus": {"of": of, "lo": min(extra), "hi": max(extra)}})
                    break
            else:
                config.append({"key": key, "kind": "int", "choices": seen})
        else:
            config.append({"key": key, "kind": "bool", "choices": seen})
    return {"params": config}


def seeds_for(template_id: str) -> list[int]:
    base = zlib.crc32(template_id.encode())
    return [base + i for i in range(SEEDS)]


def scale(spec: dict, sandbox: Sandbox, generator: str) -> dict:
    config = infer(spec)
    if config is None:
        return {"template_id": spec["template_id"], "eligible": False, "reason": "parameter_types"}
    lengths = [len(case[i]) for case in spec["tests"] for i, p in enumerate(spec["parameters"]) if p["type"] == "list[int]"]
    small = max(2, int(statistics.median(lengths)))
    try:  # the solver must run cleanly on small inputs of the same shape
        sandbox.run_generated(spec["solver_source"], generator, config, [[s, small] for s in range(1, SMALL_CHECKS + 1)])
    except Reject as failure:
        return {"template_id": spec["template_id"], "eligible": False, "reason": f"small_inputs:{failure.reason}"}
    seeds = seeds_for(spec["template_id"])
    for n in SIZES:
        try:
            results = sandbox.run_generated(spec["solver_source"], generator, config, [[s, n] for s in seeds])
        except Reject:
            continue
        times = [r["ms"] for r in results]
        if max(times) > SOLVER_BUDGET_MS:
            continue
        limit = int(min(8000, max(2000, 10 * statistics.median(times))))
        return {"template_id": spec["template_id"], "eligible": True, "n": n, "seeds": seeds,
                "expected": [str(answer_of(r)) for r in results], "config": config,
                "solver_ms": times, "time_limit_ms": limit}
    return {"template_id": spec["template_id"], "eligible": False, "reason": "solver_too_slow"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--specs", type=Path, default=SPECS)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--families", default="", help="comma-separated template ids (default: all)")
    args = parser.parse_args(argv)
    only = {x.strip() for x in args.families.split(",") if x.strip()}
    sandbox, generator = Sandbox(timeout_s=60, memory_mb=1024), GENERATOR.read_text(encoding="utf-8")
    report = {}
    for path in sorted(args.specs.glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        if only and spec["template_id"] not in only:
            continue
        row = scale(spec, sandbox, generator)
        if row["eligible"]:
            atomic_json(args.out / f"{spec['template_id']}.json", row)
        report[spec["template_id"]] = {"n": row["n"], "limit_ms": row["time_limit_ms"], "solver_ms": row["solver_ms"]} \
            if row["eligible"] else {"skipped": row["reason"]}
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
