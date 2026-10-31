"""Part 3 of a coding round, the bonus (decision log 29): a harder twist on the same problem.

Muse Spark Open writes, for each family that has Part 2 data, a twist that keeps exactly the
same parameters: a statement, a brute-force solver and a fast solver (both `def solve(params)`
over the instance parameters, returning an int). Code ships it only if:

- the brute-force and fast solvers agree on 300 random inputs shaped like the family's
  tests (forge/scale_gen.py builds them inside the sandbox; small n, so brute force finishes);
- the twist is really different: the original solver disagrees with it on some input.

Shipped twists are written to content/coding_twist/<template_id>.json in the coding-spec
format (50 tests with the brute-force answers, two examples, the original problem's
answers kept as a named wrong method). Live calls are recorded under the work directory;
replay needs no key. Tests use fakes.

  python -m forge.coding_twists --work-dir data/forge/twist1 --mode live --budget-usd 0.5
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from decimal import Decimal
from pathlib import Path

from forge import scale_gen, schemas
from forge.coding_scale import infer
from forge.coding_specs import IDENT, SPEC_TOKENS, answer_of, signature
from forge.errors import BudgetStop, Reject, ReplayMissing, ResumeBlocked
from forge.models import DEFAULT_PRICES, Models, State, atomic_json
from forge.sandbox import Sandbox

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "content" / "coding"
SCALE = ROOT / "content" / "coding_scale"
OUT = ROOT / "content" / "coding_twist"
GENERATOR = Path(__file__).with_name("scale_gen.py")
AGREE = 300  # random inputs on which brute force and the fast solver must agree
TESTS = 50
SMALL_MAX = 8  # brute force must finish: small inputs only
BATCH = 75  # the sandbox's batch limit
TWIST = schemas.obj({"function_name": schemas.S, "statement": schemas.S, "brute_force": schemas.S, "fast": schemas.S})
PROMPT = """Write a harder follow-up ("Part 3") to this verified coding problem, the kind an interviewer
asks once the candidate has solved it efficiently. Keep EXACTLY the same parameters (the same
instance keys, types and meaning), and the answer must still be one integer.
- function_name: snake_case, describes the new task.
- statement: 2-5 plain sentences describing the new task in general terms using the argument
  names; no specific numbers, no hints at the method, no solution.
- brute_force: Python source of `def solve(params):` that computes the answer by exhaustive,
  obviously-correct search over small inputs. params is a dict keyed by the instance keys.
- fast: Python source of `def solve(params):` that computes the same answer efficiently.
Both may use only the standard library modules math, itertools, functools and fractions, and
must return an int. The twist must change the answer on some inputs (not a restatement)."""


def small_n(spec: dict) -> int:
    lengths = [len(case[i]) for case in spec["tests"] for i, p in enumerate(spec["parameters"]) if p["type"] == "list[int]"]
    return max(2, min(SMALL_MAX, int(statistics.median(lengths))))


def answers(sandbox: Sandbox, code: str, generator: str, config: dict, points: list) -> list:
    out = []
    for i in range(0, len(points), BATCH):
        out += [answer_of(r) for r in sandbox.run_generated(code, generator, config, points[i:i + BATCH])]
    return out


def verify(draft: dict, spec: dict, sandbox: Sandbox, generator: str) -> dict:
    """Raise Reject unless the twist is sound; return the twist spec that ships."""
    name, statement = draft.get("function_name", ""), draft.get("statement", "").strip()
    if not IDENT.fullmatch(name):
        raise Reject("twist", "invalid_name")
    if not 20 <= len(statement) <= 900:
        raise Reject("twist", "statement_length")
    config = infer(spec)
    if config is None:
        raise Reject("twist", "not_eligible")
    n = small_n(spec)
    points = [[seed, n] for seed in range(1, AGREE + 1)]
    brute = answers(sandbox, draft["brute_force"], generator, config, points)
    fast = answers(sandbox, draft["fast"], generator, config, points)
    if any(b.denominator != 1 for b in brute):
        raise Reject("twist", "answers_are_not_integers")
    disagree = sum(b != f for b, f in zip(brute, fast))
    if disagree:
        raise Reject("twist", "solvers_disagree", {"inputs": disagree})
    original = answers(sandbox, spec["solver_source"], generator, config, points[:TESTS])
    if all(o == b for o, b in zip(original, brute[:TESTS])):
        raise Reject("twist", "not_a_twist")
    keys = [p["param"] for p in spec["parameters"]]
    tests = []
    for seed, size in points[:TESTS]:
        made = scale_gen.generate(config, seed, size)
        tests.append([made[k] for k in keys])
    expected = [str(b) for b in brute[:TESTS]]
    examples = []
    for i in range(TESTS):
        if len(examples) < 2 and all(expected[i] != expected[j] for j in examples):
            examples.append(i)
    twist = {"function_name": name, "parameters": spec["parameters"], "return_type": "int"}
    return {
        "template_id": spec["template_id"], "pack": spec.get("pack", "software"), "topic": spec["topic"], "difficulty": "Hard",
        "function_name": name, "signature": signature(twist), "parameters": spec["parameters"], "return_type": "int",
        "statement": statement, "examples": examples, "tests": tests, "expected": expected,
        "wrong_methods": [{"name": "the original problem's answer", "outputs": [str(o) for o in original],
                           "source": spec["solver_source"]}],
        "solver_source": draft["fast"], "brute_force_source": draft["brute_force"],
        "verification": {"verified": True, "variants": TESTS, "solver_reproduced": TESTS, "agreed_inputs": AGREE,
                         "differs_from_original": sum(o != b for o, b in zip(original, brute[:TESTS]))},
    }


class TwistForge:
    def __init__(self, models, sandbox, specs: Path = SPECS, scale: Path = SCALE, out: Path = OUT):
        self.models, self.state, self.sandbox = models, models.state, sandbox
        self.specs, self.scale, self.out = Path(specs), Path(scale), Path(out)
        self.generator = GENERATOR.read_text(encoding="utf-8")

    def families(self) -> list[dict]:
        """Specs with Part 2 data: Part 3 is offered only after Part 2 passed."""
        found = []
        for path in sorted(self.specs.glob("*.json")):
            spec = json.loads(path.read_text(encoding="utf-8"))
            if (self.scale / path.name).exists():
                found.append(spec)
        return found

    def write(self, stage: str, payload: dict, instructions: str) -> dict:
        for limit in SPEC_TOKENS:
            try:
                return self.models.call(stage, payload, TWIST, instructions, author=True, max_tokens=limit)
            except Reject as failure:
                if failure.details.get("finish") != "length" or limit == SPEC_TOKENS[-1]:
                    raise

    def one(self, spec: dict) -> None:
        record = self.state.data["items"].setdefault(spec["template_id"], {"status": "pending"})
        if record["status"] in {"verified", "fallback"}:
            return
        examples = [{"args": spec["tests"][i], "answer": spec["expected"][i]} for i in spec["examples"]]
        payload = {"template_id": spec["template_id"], "statement": spec["statement"], "signature": spec["signature"],
                   "parameters": spec["parameters"], "examples": examples, "verified_solver": spec["solver_source"]}
        for attempt in ("author", "repair"):
            if attempt == "repair":
                payload = {**payload, "draft": record["draft"], "error": record["failure"]}
            record["draft"] = self.write("twist_" + attempt, payload,
                                         PROMPT + ("\nCorrect the reported error; return one complete twist." if attempt == "repair" else ""))
            self.state.save()
            try:
                shipped = verify(record["draft"], spec, self.sandbox, self.generator)
            except Reject as failure:
                record["failure"] = {"gate": failure.stage, "error_class": failure.reason, **failure.details}
                if attempt == "repair":
                    record["status"] = "fallback"
                self.state.save()
                continue
            shipped["models"] = {"twist_author": self.models.author.model}
            atomic_json(self.out / (spec["template_id"] + ".json"), shipped)
            record.update(status="verified", failure=None)
            return

    def run(self, only: set[str] | None = None) -> dict:
        halt = None
        families = [s for s in self.families() if not only or s["template_id"] in only]
        for spec in families:
            if halt is None:
                try:
                    self.one(spec)
                except (BudgetStop, ReplayMissing, ResumeBlocked) as stop:
                    halt = type(stop).__name__
                except Reject as failure:  # a model failure fails this family only
                    self.state.data["items"][spec["template_id"]].update(
                        status="failed", failure={"gate": failure.stage, "error_class": failure.reason, **failure.details})
            self.state.save()
        items = self.state.data["items"]
        report = {"status": halt or "completed", "families": len(families),
                  "outcomes": {s["template_id"]: (items.get(s["template_id"]) or {}).get("status", "not_run") for s in families},
                  "failures": {k: i.get("failure") for k, i in items.items() if i.get("status") in {"fallback", "failed"}},
                  "cost_usd": str(self.models.spent()), "budget_usd": str(self.models.budget)}
        atomic_json(self.state.root / "report.json", report)
        return report


def main(argv=None) -> int:
    from llm.backends import get_backend
    from llm.client import MissingKey, _key

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "data" / "forge" / "twist1")
    parser.add_argument("--mode", choices=("live", "replay"), default="replay")
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal("0.5"))
    parser.add_argument("--families", default="", help="comma-separated template ids (default: every family with Part 2 data)")
    args = parser.parse_args(argv)
    if not args.work_dir.resolve().is_relative_to((ROOT / "data" / "forge").resolve()):
        parser.error("--work-dir must stay inside ignored data/forge")
    if not 0 <= args.budget_usd <= Decimal("0.5"):
        parser.error("Twists have a budget of at most 0.50 USD")
    try:
        if args.mode == "live":
            _key("BASETEN_API_KEY")
        author = get_backend(os.environ.get("LLM_BACKEND", "open_weights"))
        if author.name != "open_weights":
            raise ValueError("Twists are written by Muse Spark Open (open_weights)")
        models = Models(State(args.work_dir), mode=args.mode, budget_usd=args.budget_usd, prices=dict(DEFAULT_PRICES), author=author)
        only = {x.strip() for x in args.families.split(",") if x.strip()} or None
        report = TwistForge(models, Sandbox(timeout_s=60, memory_mb=512)).run(only)
    except (OSError, ValueError, KeyError, MissingKey) as error:
        print(json.dumps({"status": "configuration_error", "type": type(error).__name__}))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
