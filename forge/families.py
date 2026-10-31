"""Import verified CSV families; forge misconceptions offline, with honest fallbacks."""
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
from fractions import Fraction
import csv
import hashlib
import itertools
import json
from pathlib import Path
import re

from forge import schemas
from forge.content import mental_arithmetic, spoken_text
from forge.data import answer_value, number
from forge.errors import BudgetStop, Reject, ReplayMissing, ResumeBlocked
from forge.models import atomic_json
from forge.sandbox import Sandbox
from forge.packs import PACK_PREFIXES, pack_name, pack_template_id
from forge.verify import LABEL, snake_case

MIN_VARIANTS = 20
PARAMETER_REVISION = 3
PROMPT_REVISION = 2  # 2: examples carry their verified answers; percentages are fractions of one
PERCENT = re.compile(r"percent|%", re.I)
DRAFT = schemas.obj({"solver": schemas.S, "step_names": schemas.arr(schemas.S),
                     "wrong": schemas.arr(schemas.WRONG)})
PROMPT = """Write an exact parameterized solver and 2-4 named misconception solvers for this family.
Only two representative variants are supplied. The code must work on ALL variants, not look up examples.
Do not rewrite the question or invent parameter ranges. Code defines solve(params).
The main solver returns {"answer": int/Fraction, "steps": {step_name: int/Fraction}}.
Wrong-method solvers return int/Fraction; each has a distinct misconception name.
step_names must exactly describe the returned named intermediate values. Use descriptive snake_case names.
Parameters keep their numeric meaning: native integers are ints, numeric strings are exact Fractions and nonnumeric labels remain strings,
arrays are immutable tuples and objects are read-only mappings. Do not mutate parameters or depend on call order.
Each variant gets fresh generated globals. No random solver. No float RETURN values; exact int/Fraction outputs only.
Each example carries its verified answer: the solver must return exactly that value on the same scale.
A percentage is returned as a fraction of one, never in percent points: 26% is Fraction(13, 50), not 26.
The same scale applies to percentage steps and to every wrong-method value.
Imports limited to math, fractions, random, itertools, functools. No files/network, introspection,
classes, decorators, dynamic execution or outside code. Never execute code at application runtime."""


@dataclass(frozen=True)
class Variant:
    source_id: str
    variant: str
    text: str
    params: dict
    answer: Fraction | str  # str: a list answer as canonical JSON (coding-only family)
    tolerance: Fraction
    verification_result: str
    topic: str
    source_topic: str
    difficulty: str
    solution: str
    reasoning_focus: str
    follow_up: dict


@dataclass(frozen=True)
class Family:
    family_id: str
    variants: tuple

    @property
    def template_id(self):
        return "family_" + self.family_id


def load_families(path):
    required = {"family_id", "variant", "question", "parameters", "verified_value", "verification_result",
                "verification_tolerance", "topic", "subtopic", "difficulty", "solution", "reasoning_focus",
                "interview_follow_up", "follow_up_discussion"}
    grouped = {}
    try:
        with Path(path).open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not required <= set(reader.fieldnames or ()):
                raise ValueError("Missing family columns")
            for row in reader:
                family_id = row["family_id"].strip()
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", family_id):
                    raise ValueError("Unsafe family identifier")
                status = row["verification_result"].strip()
                if status not in {"PASS_EXACT", "PASS_NUMERICAL"}:
                    raise ValueError("Unverified source value")
                answer = answer_value(row["verified_value"])
                if isinstance(answer, str) and status != "PASS_EXACT":
                    raise ValueError("List answers must be exact")
                tolerance = number(row["verification_tolerance"]) if status == "PASS_NUMERICAL" else Fraction(0)
                if status == "PASS_NUMERICAL" and tolerance <= 0:
                    raise ValueError("Numerical verification requires positive tolerance")
                params = json.loads(row["parameters"], parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite parameter")))
                if not isinstance(params, dict) or not row["question"].strip() or not row["variant"].strip():
                    raise ValueError("Invalid variant")
                variant = Variant(row.get("id", ""), row["variant"], row["question"], params, answer, tolerance, status,
                    row["topic"], row["subtopic"], row["difficulty"], row["solution"], row["reasoning_focus"],
                    {"question": row["interview_follow_up"], "reference": row["follow_up_discussion"]})
                grouped.setdefault(family_id, []).append(variant)
    except (Reject, KeyError, TypeError, ArithmeticError) as error:
        raise ValueError("Invalid family source") from None
    families = []
    for family_id, variants in grouped.items():
        if len(variants) < MIN_VARIANTS or len({row.variant for row in variants}) != len(variants):
            raise ValueError("Each family must have at least 20 distinct variants")
        variants.sort(key=lambda row: (0, int(row.variant)) if row.variant.isdigit() else (1, row.variant))
        families.append(Family(family_id, tuple(variants)))
    if not families:
        raise ValueError("No families")
    return families


def separation(answer, wrong):
    if isinstance(answer, str):  # list answers: grouped by exact value, no numeric gaps
        grouped = {}
        for name, value in wrong:
            grouped.setdefault(value, []).append(name)
        return ([{"value": value, "misconceptions": names} for value, names in grouped.items()],
                {"by_misconception": [], "min_wrong_pair_gap": None, "min_distinct_wrong_pair_gap": None})
    grouped, gaps, values = {}, [], []
    for name, value in wrong:
        value = Fraction(value)
        grouped.setdefault(str(value), []).append(name)
        gap = abs(value - answer)
        gaps.append({"misconception": name, "absolute_gap": str(gap),
                     "relative_gap": str(gap / abs(answer)) if answer else None})
        values.append(value)
    pair = min((abs(a - b) for a, b in itertools.combinations(values, 2)), default=None)
    distinct = min((abs(Fraction(a) - Fraction(b)) for a, b in itertools.combinations(grouped, 2)), default=None)
    return ([{"value": value, "misconceptions": names} for value, names in grouped.items()],
            {"by_misconception": gaps, "min_wrong_pair_gap": str(pair) if pair is not None else None,
             "min_distinct_wrong_pair_gap": str(distinct) if distinct is not None else None})


class FamilyForge:
    def __init__(self, models, *, output, funnel, sandbox=None, pack="quant", prefix=None):
        self.models, self.state = models, models.state
        self.pack = pack_name(pack)
        self.prefix = prefix  # a new batch's own file prefix (forge.packs.output_prefix)
        self.output, self.funnel = Path(output), Path(funnel)
        self.sandbox = sandbox or Sandbox()
        settings = {"version": 2, "minimum_variants": MIN_VARIANTS, "exact_source_tolerance": 0,
                    "repairs_per_family": 1, "typed_parameters": True, "pack": self.pack,
                    **({"prefix": prefix} if prefix else {})}
        legacy = {"version": 1, "variants_per_family": 75, "exact_source_tolerance": 0,
                  "repairs_per_family": 1, "typed_parameters": True}
        previous = self.state.data.get("family_forge_settings")
        if previous == legacy and self.pack == "quant":
            self.state.data["family_forge_settings"] = settings
        elif previous is None:
            self.state.data["family_forge_settings"] = settings
        if "verification_settings" in self.state.data or self.state.data["family_forge_settings"] != settings:
            raise ValueError("Use a separate family-forge work directory for each pack")

    def template_id(self, family):
        return pack_template_id(self.pack, family.family_id, self.prefix)

    def stage(self, item, name, passed=False):
        if name not in item.setdefault("attempted", []):
            item["attempted"].append(name)
        if passed:
            item.setdefault("passed", []).append(name)
            item["passed"] = list(dict.fromkeys(item["passed"]))
        self.state.save()

    def call(self, family, item, repair=False):
        stage = "family_repair" if repair else "family_author"
        self.stage(item, stage)
        payload = {"family_id": family.family_id, "examples": [
            {"question": row.text, "params": row.params, "solution": row.solution, "reasoning_focus": row.reasoning_focus,
             "answer": str(row.answer)}
            for row in (family.variants[0], family.variants[-1])]}
        if self.pack != "quant":
            payload["pack"] = self.pack
        if repair:
            payload.update(draft=item["draft"], error=item["repair"])
        result = self.models.call(stage, payload, DRAFT, PROMPT + (
            "\nCorrect the reported gate error; return one complete corrected draft." if repair else ""), author=True)
        self.stage(item, stage, True)
        return result

    def batch(self, code, params):
        # Bound each child request without imposing a fixed family size.
        results = []
        for start in range(0, len(params), 75):
            chunk = params[start:start + 75]
            try:
                result = self.sandbox.run_batch(code, chunk)
            except TypeError:
                raise Reject("sandbox", "TypeError") from None
            if len(result) != len(chunk):
                raise Reject("sandbox", "invalid_batch_output")
            results.extend(result)
        return results

    def verify(self, family, item, draft):
        names = [snake_case(name) for name in draft["step_names"]]
        methods = draft["wrong"]
        if (not names or len(set(names)) != len(names) or any(not LABEL.fullmatch(name) for name in names)):
            raise Reject("steps", "invalid_step_names")
        if not 2 <= len(methods) <= 4:
            raise Reject("wrong_methods", "need_two_to_four")
        method_names = [snake_case(method["misconception"]) for method in methods]
        if len(set(method_names)) != len(method_names) or any(not LABEL.fullmatch(name) for name in method_names):
            raise Reject("wrong_methods", "invalid_names")
        points = [row.params for row in family.variants]
        self.stage(item, "solver")
        solved = self.batch(draft["solver"], points)
        steps, errors = [], []
        for index, (row, result) in enumerate(zip(family.variants, solved)):
            if isinstance(row.answer, str):  # a list answer: exact JSON equality
                if result["answer"] != row.answer:
                    raise Reject("solver", "verified_value_mismatch", {"variant_index": index})
                error = Fraction(0)
            else:
                error = abs(number(result["answer"]) - row.answer)
            if error > row.tolerance:
                # Name the percent-points slip so the repair knows the fix; it is never accepted as correct.
                scaled = PERCENT.search(row.text) and abs(number(result["answer"]) - 100 * row.answer) <= 100 * row.tolerance
                raise Reject("solver", "percent_points_not_fraction" if scaled else "verified_value_mismatch",
                             {"variant_index": index})
            returned = [{**step, "name": snake_case(step["name"])} for step in result["steps"]]
            if len({step["name"] for step in returned}) != len(returned) or {step["name"] for step in returned} != set(names):
                raise Reject("steps", "invalid_step_names", {"variant_index": index})
            # Validate every returned step value as numeric as well as its name.
            steps.append([{"name": step["name"], "value": str(number(step["value"]))} for step in returned])
            errors.append(error)
        item["verified_steps"] = steps
        item["solver_verification"] = {"passed": True, "variants_checked": len(family.variants),
                                      "max_absolute_error": str(max(errors))}
        self.stage(item, "solver", True)
        self.stage(item, "wrong_methods")
        per_variant = [[] for _ in family.variants]
        for name, method in zip(method_names, methods):
            values = self.batch(method["code"], points)
            for index, (row, result) in enumerate(zip(family.variants, values)):
                value = result["answer"] if isinstance(row.answer, str) else number(result["answer"])
                if (value == row.answer) if isinstance(row.answer, str) else abs(value - row.answer) <= row.tolerance:
                    raise Reject("wrong_methods", "correct_answer_collision", {"variant_index": index})
                per_variant[index].append((name, value))
        item["computed"] = []
        for row, named_steps, wrong in zip(family.variants, steps, per_variant):
            values, gaps = separation(row.answer, wrong)
            item["computed"].append({"wrong": values, "steps": named_steps, "separation": gaps})
        item["method_count"] = len(methods)
        self.stage(item, "wrong_methods", True)

    def process(self, family, item):
        if "draft" not in item:
            item["draft"] = self.call(family, item)
            self.state.save()
        if "repair" in item and "corrected" not in item:
            item["corrected"] = self.call(family, item, repair=True)
            self.state.save()
        while True:
            try:
                self.verify(family, item, item.get("corrected", item["draft"]))
                item["status"] = "verified"
                return
            except (Reject, TypeError) as failure:
                if isinstance(failure, TypeError):
                    failure = Reject("sandbox", "TypeError")
                error = {"gate": failure.stage, "error_class": failure.reason}
                if "variant_index" in failure.details:
                    error["variant_index"] = failure.details["variant_index"]
                if "repair" in item:
                    item["failure"] = error
                    item["status"] = "fallback"
                    return
                item["repair"] = error
                self.state.save()
                item["corrected"] = self.call(family, item, repair=True)
                self.state.save()

    def recheck(self, family, item):
        """Re-evaluate only cached drafts under the corrected parameter runtime."""
        history = item.setdefault("recheck_history", [])
        if not history or history[-1]["revision"] != PARAMETER_REVISION or item["status"] != "pending":
            history.append({"revision": PARAMETER_REVISION, "previous_status": item["status"],
                            "previous_failure": item.get("failure"), "attempts": []})
        item["status"] = "pending"
        for key in ("computed", "verified_steps", "solver_verification", "method_count", "failure"):
            item.pop(key, None)
        item["passed"] = [name for name in item.get("passed", []) if name not in {"solver", "wrong_methods", "recheck"}]
        self.stage(item, "recheck")
        failure = {"gate": "cache", "error_class": "missing_cached_draft"}
        for field in ("corrected", "draft"):
            if field not in item:
                continue
            try:
                self.verify(family, item, item[field])
            except (Reject, TypeError) as error:
                if isinstance(error, TypeError):
                    error = Reject("sandbox", "TypeError")
                failure = {"gate": error.stage, "error_class": error.reason}
                if "variant_index" in error.details:
                    failure["variant_index"] = error.details["variant_index"]
                history[-1]["attempts"].append({"draft": field, "passed": False, **failure})
            else:
                history[-1]["attempts"].append({"draft": field, "passed": True})
                item.update(status="verified", rechecked_draft=field, rechecked_parameter_revision=PARAMETER_REVISION)
                item.pop("failure", None)
                self.stage(item, "recheck", True)
                return
        item.update(status="fallback", failure=failure, rechecked_parameter_revision=PARAMETER_REVISION)
        self.state.save()

    def export(self, family, item, pending_reason=None):
        verified = item["status"] == "verified"
        rows = []
        empty = separation(Fraction(0), [])[1]
        for index, source in enumerate(family.variants):
            computed = item["computed"][index] if verified else {
                "wrong": [], "steps": item.get("verified_steps", [[] for _ in family.variants])[index],
                "separation": empty}
            rows.append({"variant": source.variant, "text": source.text, "params": source.params,
                         "answer": str(source.answer), "tolerance": str(source.tolerance),
                         "topic": source.topic, "source_topic": source.source_topic, "difficulty": source.difficulty,
                         "spoken_text": spoken_text(source.text, check_wording=False),
                         **(mental_arithmetic(source.answer) if not isinstance(source.answer, str) else
                            {"interview_friendly": False, "interview_friendly_score": 0, "interview_friendly_basis": "list"}),
                         **computed, "follow_up": source.follow_up})
        first = family.variants[0]
        artifact = {"template_id": self.template_id(family), "pack": self.pack, "topic": first.topic,
            "topics": list(dict.fromkeys(row.topic for row in family.variants)), "source_topic": first.source_topic,
            "difficulty": first.difficulty, "models": {"author": self.models.author.model, "checker": None},
            "verification": {"mode": "imported_verified_families",
                "source": {"passed": True, "variants": len(family.variants),
                    "results": dict(Counter(row.verification_result for row in family.variants))},
                "solver": item.get("solver_verification", {"passed": False, "variants_checked": 0}),
                "misconceptions_verified": verified, "method_count": item.get("method_count", 0) if verified else 0,
                "repair_attempted": "repair" in item, "reason": item.get("failure") if not verified else None,
                "pending_reason": pending_reason, "all_variants_retained": True,
                "rechecked_parameter_revision": item.get("rechecked_parameter_revision"),
                "variant_followups": len({json.dumps(row.follow_up, sort_keys=True) for row in family.variants}) > 1},
            "follow_up": first.follow_up, "review_status": "pending_builder_review", "instances": rows,
            # Decision log 30: list answers ("[106,110]") are for coding rounds only, never spoken.
            **({"answer_kind": "list", "coding_only": True} if isinstance(first.answer, str) else {})}
        atomic_json(self.output / (self.template_id(family) + ".json"), artifact)
        item["exported"] = True
        self.state.data["mapping"][self.template_id(family)] = {"family_id": family.family_id,
            "source_ids": [row.source_id for row in family.variants]}
        atomic_json(self.state.root / "mapping.json", self.state.data["mapping"])
        self.stage(item, "export", True)

    def report(self, families, status):
        items = self.state.data["items"]
        def totals(selected):
            return {"families": len(selected), "exported": sum(bool(item.get("exported")) for item in selected),
                    "verified": sum(item["status"] == "verified" for item in selected),
                    "fallback": sum(item["status"] == "fallback" for item in selected),
                    "pending": sum(item["status"] == "pending" for item in selected)}
        topics = {family.variants[0].topic for family in families}
        stages = {stage: {"attempted": sum(stage in item.get("attempted", []) for item in items.values()),
                          "passed": sum(stage in item.get("passed", []) for item in items.values())}
                  for stage in ("family_author", "family_repair", "solver", "wrong_methods", "recheck", "export")}
        billing = {}
        for call in self.state.data["calls"].values():
            row = billing.setdefault(call["backend"], {"cost_usd": Decimal(0), "calls": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "latency_s": 0, "usage_unknown_calls": 0})
            row["cost_usd"] += Decimal(call["cost_usd"])
            for key in ("prompt_tokens", "completion_tokens", "latency_s"):
                row[key] += call[key]
            row["calls"] += 1
            row["usage_unknown_calls"] += int(not call["usage_known"])
        for row in billing.values():
            row["cost_usd"] = str(row["cost_usd"])
        report = {"format_version": 1, "mode": "family_forge", "pack": self.pack, "status": status,
            "families_loaded": len(families), "source_variants": sum(len(family.variants) for family in families),
            "families_exported": sum(bool(item.get("exported")) for item in items.values()),
            "misconceptions_verified": sum(item["status"] == "verified" for item in items.values()),
            "solvers_verified": sum(bool(item.get("solver_verification", {}).get("passed")) for item in items.values()),
            "fallback_families": sum(item["status"] == "fallback" for item in items.values()),
            "pending_families": sum(item["status"] == "pending" for item in items.values()),
            "unverified_exports": sum(bool(item.get("exported")) and item["status"] != "verified" for item in items.values()),
            "accepted_after_repair": sum(item["status"] == "verified" and "repair" in item for item in items.values()),
            "stages": stages, "cost_usd": str(self.models.spent()), "budget_usd": str(self.models.budget),
            "prices_per_million": self.state.data.get("prices", {}), "billing": billing,
            "latency_s": sum(row["latency_s"] for row in self.state.data["calls"].values()),
            "latency_basis": "recorded_model_calls_once",
            "per_topic": {topic: totals([items[self.template_id(family)] for family in families
                          if self.template_id(family) in items and family.variants[0].topic == topic]) for topic in sorted(topics)}}
        if getattr(self, "recheck_ids", ()):
            selected = [items[pack_template_id(self.pack, family_id, self.prefix)] for family_id in self.recheck_ids
                        if pack_template_id(self.pack, family_id, self.prefix) in items]
            report["recheck"] = {"requested": list(self.recheck_ids), "parameter_revision": PARAMETER_REVISION,
                "completed": sum(item.get("rechecked_parameter_revision") == PARAMETER_REVISION for item in selected),
                "verified": sum(item["status"] == "verified" for item in selected),
                "fallback": sum(item["status"] == "fallback" for item in selected),
                "additional_model_calls": len(self.state.data["calls"]) - self.recheck_call_count,
                "additional_cost_usd": str(self.models.spent() - self.recheck_start_cost)}
        atomic_json(self.funnel, report)
        return report

    def retry(self, item):
        """Discard a fallback's cached drafts so it is authored again under the current prompt."""
        if item.get("retry_prompt_revision") == PROMPT_REVISION or item["status"] != "fallback":
            return
        kept = {key: item.pop(key) for key in ("draft", "repair", "corrected", "failure", "computed", "verified_steps",
                                               "solver_verification", "method_count") if key in item}
        item.setdefault("retry_history", []).append({"prompt_revision": PROMPT_REVISION, **kept})
        item.update(status="pending", retry_prompt_revision=PROMPT_REVISION, attempted=[], passed=[])
        self.state.save()

    def run(self, families, *, recheck_families=(), retry_families=()):
        public_ids = [self.template_id(family) for family in families]
        if len(set(public_ids)) != len(public_ids):
            raise ValueError("Duplicate public family IDs")
        self.recheck_ids = tuple(dict.fromkeys(recheck_families))
        retry_ids = tuple(dict.fromkeys(retry_families))
        if not set(self.recheck_ids) | set(retry_ids) <= {family.family_id for family in families}:
            raise ValueError("Unknown family in recheck selection")
        if self.recheck_ids and retry_ids:
            raise ValueError("Recheck and retry are separate runs")
        self.recheck_call_count, self.recheck_start_cost = len(self.state.data["calls"]), self.models.spent()
        fingerprint = hashlib.sha256(json.dumps([asdict(family) for family in families], sort_keys=True,
                                                default=str).encode()).hexdigest()
        if self.state.data.setdefault("families_sha256", fingerprint) != fingerprint:
            raise ValueError("Family source changed; use a new private work directory")
        halt = None
        for family in families:
            if (self.recheck_ids or retry_ids) and family.family_id not in self.recheck_ids + retry_ids:
                continue
            item = self.state.data["items"].setdefault(self.template_id(family), {"status": "pending", "attempted": [], "passed": []})
            if retry_ids:
                self.retry(item)
            recheck = bool(self.recheck_ids) and item.get("rechecked_parameter_revision") != PARAMETER_REVISION
            if not recheck and item["status"] in {"verified", "fallback"}:
                if not (self.output / (self.template_id(family) + ".json")).exists():
                    self.export(family, item)
                continue
            self.models.current_topics = tuple(dict.fromkeys(row.topic for row in family.variants))
            if halt is None:
                try:
                    if recheck:
                        self.recheck(family, item)
                    else:
                        self.process(family, item)
                except BudgetStop:
                    halt = "budget_stop"
                except ReplayMissing:
                    halt = "replay_missing"
                except ResumeBlocked:
                    halt = "unresolved_call"
                except KeyboardInterrupt:
                    halt = "interrupted"
                except Reject as failure:
                    item["status"] = "fallback"
                    item["failure"] = {"gate": failure.stage, "error_class": failure.reason}
            self.export(family, item, halt if item["status"] == "pending" else None)
            self.state.save()
            self.report(families, "running")
        self.state.save()
        return self.report(families, halt or "completed")
