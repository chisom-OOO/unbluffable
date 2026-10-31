"""Coding specs for software families (decision log 26): Muse Spark Open writes a Python
function signature for each family (name, typed parameters mapped to the instance params,
return type) and a short problem statement. Code verifies the spec before it ships:

- every parameter's type matches the instance values on every variant;
- the forge's own solver, called through the signature, reproduces every stored answer;
- each forge wrong method, called the same way, is kept only if it gives a wrong output on at
  least one test; its output on every test is stored, so a candidate's failing outputs can be
  named.

Only verified specs are written, to content/coding/<template_id>.json, with the solver and
wrong-method source exported for the provenance receipt. Live calls are recorded under the
work directory; replay needs no key. Tests use fakes.

  python -m forge.coding_specs --family-state PATH/data/forge/sw2/state.json \\
      --work-dir data/forge/coding1 --mode live --budget-usd 1
"""

from __future__ import annotations

import argparse
import json
import os
import re
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from forge import schemas
from forge.data import number
from forge.errors import BudgetStop, Reject, ReplayMissing, ResumeBlocked
from forge.models import DEFAULT_PRICES, Models, State, atomic_json
from forge.sandbox import Sandbox

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content" / "forge"
OUT = ROOT / "content" / "coding"
IDENT = re.compile(r"[a-z_][a-z0-9_]{0,40}")
TYPES = {"int", "float", "str", "bool", "list[int]", "list[float]", "list[str]", "list[bool]",
         "list[list[int]]", "list[list[str]]", "list[list[float]]"}
SPEC = schemas.obj({
    "function_name": schemas.S,
    "parameters": schemas.arr(schemas.obj({"name": schemas.S, "type": schemas.S, "param": schemas.S})),
    "return_type": schemas.S,
    "statement": schemas.S,
})
PROMPT = """Turn this verified interview question family into a Python coding exercise.
Return a function signature for the candidate to implement and a short problem statement.
- function_name: snake_case, describes the task.
- parameters: one per instance parameter, in a natural order. name: snake_case argument name.
  type: one of int, float, str, bool, list[int], list[float], list[str], list[bool],
  list[list[int]], list[list[str]], list[list[float]]. param: the exact instance parameter key it receives.
- return_type: int, float, str or bool, matching the answer.
- statement: 2-5 plain sentences describing the task in general terms using the argument
  names; no specific numbers from the examples, no hints at the method, no solution.
The forge's verified solver is included only so the mapping and types are right; never
describe its method in the statement."""
# A spec plus the model's reasoning can outrun 4,000 tokens. A response cut off at the limit
# is retried once with a higher one; the higher limit is a different request, so it never
# replays the cached truncated response.
SPEC_TOKENS = (12000, 24000)


def check_type(value, annotation: str) -> bool:
    if annotation.startswith("list[") and annotation.endswith("]"):
        inner = annotation[5:-1]
        return isinstance(value, list) and all(check_type(v, inner) for v in value)
    return {"int": lambda v: isinstance(v, int) and not isinstance(v, bool), "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "str": lambda v: isinstance(v, str), "bool": lambda v: isinstance(v, bool)}.get(annotation, lambda v: False)(value)


def signature(spec: dict) -> str:
    args = ", ".join(f"{p['name']}: {p['type']}" for p in spec["parameters"])
    return f"def {spec['function_name']}({args}) -> {spec['return_type']}:"


def through_signature(code: str, keys: list[str]) -> str:
    """The forge program, called the way a candidate's function is: with the arguments
    the signature takes, rebuilt into the params it expects. A missing or extra key fails."""
    renamed = re.sub(r"\bsolve\b", "_forge_solve", code)
    return (renamed + "\n\n_KEYS = " + json.dumps(keys) + "\n"
            "def solve(params):\n"
            "    args = [params[k] for k in _KEYS]\n"
            "    if sorted(_KEYS) != sorted(params):\n"
            "        raise KeyError('the signature does not cover the parameters')\n"
            "    return _forge_solve(dict(zip(_KEYS, args)))\n")


def plain(value):
    """Instance params as plain JSON (the sandbox gives tuples for lists)."""
    return [plain(v) for v in value] if isinstance(value, (list, tuple)) else value


def answer_of(result) -> Fraction:
    return number(result["answer"] if isinstance(result, dict) else result)


def verify(spec: dict, family: dict, solver: str, wrong: list[dict], sandbox) -> dict:
    """Raise Reject unless the spec is sound; return what ships."""
    if not IDENT.fullmatch(spec.get("function_name", "")) or spec.get("return_type") not in {"int", "float", "str", "bool"}:
        raise Reject("spec", "invalid_name_or_return_type")
    params = spec.get("parameters") or []
    names = [p["name"] for p in params]
    keys = [p["param"] for p in params]
    if not params or len(set(names)) != len(names) or len(set(keys)) != len(keys) or not all(IDENT.fullmatch(n) for n in names):
        raise Reject("spec", "invalid_parameters")
    if any(p["type"] not in TYPES for p in params):
        raise Reject("spec", "unknown_type")
    statement = spec.get("statement", "").strip()
    if not 20 <= len(statement) <= 900:
        raise Reject("spec", "statement_length")
    instances = family["instances"]
    for i, inst in enumerate(instances):
        if sorted(inst["params"]) != sorted(keys):
            raise Reject("spec", "parameters_do_not_match", {"variant_index": i})
        for p in params:
            if not check_type(inst["params"][p["param"]], p["type"]):
                raise Reject("spec", "type_mismatch", {"variant_index": i})
    expected = [number(inst["answer"]) for inst in instances]
    if spec["return_type"] == "int" and any(x.denominator != 1 for x in expected):
        raise Reject("spec", "answers_are_not_integers")
    points = [inst["params"] for inst in instances]
    solved = sandbox.run_batch(through_signature(solver, keys), points)
    for i, (got, want) in enumerate(zip(solved, expected)):
        if answer_of(got) != want:
            raise Reject("spec", "solver_does_not_reproduce", {"variant_index": i})
    methods = []
    for method in wrong:
        try:
            outputs = [answer_of(r) for r in sandbox.run_batch(through_signature(method["code"], keys), points)]
        except Reject:
            continue
        if any(o != e for o, e in zip(outputs, expected)):
            methods.append({"name": method["misconception"].replace("_", " "), "outputs": [str(o) for o in outputs],
                            "source": method["code"]})
    tests = [[plain(inst["params"][k]) for k in keys] for inst in instances]
    friendly = [i for i, inst in enumerate(instances) if inst.get("interview_friendly")] or list(range(len(instances)))
    examples = []
    for i in friendly:
        if len(examples) < 2 and all(expected[i] != expected[j] for j in examples):
            examples.append(i)
    return {
        "template_id": family["template_id"], "pack": family.get("pack", "software"), "topic": family["topic"],
        "difficulty": family["difficulty"], "function_name": spec["function_name"], "signature": signature(spec),
        "parameters": params, "return_type": spec["return_type"], "statement": statement,
        "examples": examples, "tests": tests, "expected": [str(x) for x in expected],
        "wrong_methods": methods, "solver_source": solver,
        "verification": {"verified": True, "variants": len(instances), "solver_reproduced": len(instances),
                         "wrong_methods_kept": len(methods), "wrong_methods_given": len(wrong)},
    }


def programs(item: dict) -> tuple[str, list[dict]] | None:
    """The family's verified solver and wrong methods, from the family forge's state."""
    if item.get("status") != "verified" and not (item.get("solver_verification") or {}).get("passed"):
        return None
    field = item.get("rechecked_draft") or ("corrected" if "repair" in item and "corrected" in item else "draft")
    draft = item.get(field)
    if not draft:
        return None
    return draft["solver"], (draft.get("wrong") or []) if item.get("status") == "verified" else []


class CodingForge:
    def __init__(self, models, sandbox, out: Path = OUT, content: Path = CONTENT):
        self.models, self.state, self.sandbox = models, models.state, sandbox
        self.out, self.content = Path(out), Path(content)

    def families(self) -> list[dict]:
        out = []
        for path in sorted(self.content.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("pack") == "software":
                out.append(raw)
        return out

    def one(self, family: dict, item: dict) -> None:
        found = programs(item)
        record = self.state.data["items"].setdefault(family["template_id"], {"status": "pending"})
        if record["status"] in {"verified", "fallback"}:
            return
        if found is None:
            record.update(status="fallback", failure={"gate": "family", "error_class": "no_verified_solver"})
            return
        solver, wrong = found
        examples = [{"question": inst["text"], "params": inst["params"], "answer": inst["answer"]}
                    for inst in (family["instances"][0], family["instances"][-1])]
        payload = {"template_id": family["template_id"], "topic": family["topic"], "examples": examples, "solver": solver}
        for attempt in ("author", "repair"):
            if attempt == "repair":
                payload = {**payload, "draft": record["draft"], "error": record["failure"]}
            record["draft"] = self.write("coding_" + attempt, payload,
                                         PROMPT + ("\nCorrect the reported error; return one complete spec." if attempt == "repair" else ""))
            self.state.save()
            try:
                shipped = verify(record["draft"], family, solver, wrong, self.sandbox)
            except Reject as failure:
                record["failure"] = {"gate": failure.stage, "error_class": failure.reason, **failure.details}
                if attempt == "repair":
                    record["status"] = "fallback"
                self.state.save()
                continue
            shipped["models"] = {"spec_author": self.models.author.model}
            atomic_json(self.out / (family["template_id"] + ".json"), shipped)
            record.update(status="verified", failure=None)
            return

    def write(self, stage: str, payload: dict, instructions: str) -> dict:
        for limit in SPEC_TOKENS:
            try:
                return self.models.call(stage, payload, SPEC, instructions, author=True, max_tokens=limit)
            except Reject as failure:
                if failure.details.get("finish") != "length" or limit == SPEC_TOKENS[-1]:
                    raise

    def run(self, family_items: dict, only: set[str] | None = None) -> dict:
        halt = None
        for family in self.families():
            if only and family["template_id"] not in only:
                continue
            if halt is None:
                try:
                    self.one(family, family_items.get(family["template_id"], {}))
                except (BudgetStop, ReplayMissing, ResumeBlocked) as stop:
                    halt = type(stop).__name__
                except Reject as failure:
                    # A model failure fails this family only; a later run tries it again
                    # (recorded calls replay at no cost).
                    self.state.data["items"][family["template_id"]].update(
                        status="failed", failure={"gate": failure.stage, "error_class": failure.reason, **failure.details})
            self.state.save()
        items = self.state.data["items"]
        ids = [f["template_id"] for f in self.families() if not only or f["template_id"] in only]
        report = {"status": halt or "completed", "families": len(self.families()),
                  "verified": sum(i.get("status") == "verified" for i in items.values()),
                  "fallback": sum(i.get("status") == "fallback" for i in items.values()),
                  "failed": sum(i.get("status") == "failed" for i in items.values()),
                  "failures": {k: i.get("failure") for k, i in items.items() if i.get("status") in {"fallback", "failed"}},
                  "outcomes": {k: (items.get(k) or {}).get("status", "not_run") for k in ids},
                  "cost_usd": str(self.models.spent()), "budget_usd": str(self.models.budget)}
        atomic_json(self.state.root / "report.json", report)
        return report


def main(argv=None) -> int:
    from llm.backends import get_backend
    from llm.client import MissingKey, _key

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--family-state", type=Path, required=True, help="the software family forge's state.json (read only)")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "data" / "forge" / "coding1")
    parser.add_argument("--mode", choices=("live", "replay"), default="replay")
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal(1))
    parser.add_argument("--families", default="", help="comma-separated template ids (default: all software families)")
    args = parser.parse_args(argv)
    if not args.work_dir.resolve().is_relative_to((ROOT / "data" / "forge").resolve()):
        parser.error("--work-dir must stay inside ignored data/forge")
    if not 0 <= args.budget_usd <= 1:
        parser.error("Coding specs have a budget of at most one USD")
    try:
        if args.mode == "live":
            _key("BASETEN_API_KEY")
        family_items = json.loads(args.family_state.read_text(encoding="utf-8"))["items"]
        author = get_backend(os.environ.get("LLM_BACKEND", "open_weights"))
        if author.name != "open_weights":
            raise ValueError("Coding specs are written by Muse Spark Open (open_weights)")
        state = State(args.work_dir)
        models = Models(state, mode=args.mode, budget_usd=args.budget_usd, prices=dict(DEFAULT_PRICES), author=author)
        only = {x.strip() for x in args.families.split(",") if x.strip()} or None
        report = CodingForge(models, Sandbox()).run(family_items, only)
    except (OSError, ValueError, KeyError, MissingKey) as error:
        print(json.dumps({"status": "configuration_error", "type": type(error).__name__}))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
