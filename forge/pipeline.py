"""Resumable forge funnel. Bank text/code stays in the private state and call store."""
import hashlib
import json
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from forge import schemas
from forge.data import CLASSES, PRIORITY, number, stored_answer
from forge.errors import BudgetStop, Reject, ReplayMissing, ResumeBlocked
from forge.models import atomic_json
from forge.sandbox import Sandbox
from forge.verify import ambiguity, instances, near_verbatim, parameter_grid, points_for, render, validate_variant

STAGES = ("answer_pass", "numeric_answer", "author", "parameters", "original_answer", "novelty",
          "simulator", "simulator_independence", "wrong_methods", "steps", "monte_carlo",
          "reading_model", "readings", "blind_model", "blind_checker", "part2", "part2_blind_model", "accepted")

ANSWER_PROMPT = """Extract the final answer from the worked solution, not a count or an intermediate value.
Classify as numeric_single, symbolic, multiple_choice, multi_part, proof_or_explanation, or code.
quote must be a verbatim span of solution containing answer verbatim.
For rounded decimals provide the tolerance explicitly stated in the solution and its verbatim tolerance_quote.
Never invent tolerance. Use 0 and none for exact integer/fraction answers.
For nonnumeric answers, quote the verbatim final expression or conclusion; answer may be none when no single final expression exists."""
AUTHOR_PROMPT = """Write a substantially reworded parametric question for the same mathematical method.
Do not copy names, story wording or sentences. Do not reveal the answer or a worked solution in question text.
The answer is supplied only to anchor original parameters.
Use plain {parameter_name} fields, no conversions or format specifications. All parameters must appear in text.
Ranges are discrete exact rationals: minimum, maximum, positive step, original (all strings).
Ensure at least 8 valid distinct points, including all edges. Use independent valid parameter ranges.
solver is Python defining solve(params), returning {"answer": Fraction/int, "steps": {named_value: Fraction/int}}.
Use fractions.Fraction and exact arithmetic, never float for solvers. step_names must match the returned steps.
Supply 2-4 distinct named wrong-method solvers, each defining solve(params) returning its exact wrong value.
Misconception and step names use lowercase letters, digits, underscores. Wrong values must never match correct
values throughout ranges. Imports limited to math, fractions, random, itertools, functools.
No files, network, introspection, classes, decorators, dynamic imports or runtime generated code.
Optional part2 uses exactly the same setup/base parameters plus ONE extra named parameter with its own range,
solver, steps, and 2-4 wrong solvers. If absent: enabled false, empty strings/lists, dummy parameter strings."""
SIM_PROMPT = """Independently derive a Monte Carlo experiment from ONLY the question text in this call.
No solver, stored answer, model solution or earlier conversation is available. Do not calculate an exact
answer and return it as a fake sample. code defines sample(params, rng), returning ONE independently sampled
numeric outcome whose expectation is the requested quantity (0/1 for a probability).
At least one parameter point must have genuinely stochastic outcomes, not an exact-answer constant with dummy random calls. For conditional
probabilities use rejection sampling until the conditioning event occurs. The harness computes mean and SE.
Every sample must draw random events from rng.random/randrange/randint/choice etc. Do not seed or create Random.
No import of any solver. Imports limited to math, fractions, random, itertools, functools; no files/network,
introspection, classes or decorators. part2_code has the same sample contract for part2_question, or empty."""
READINGS_PROMPT = """Consider at most three genuinely plausible alternative interpretations of this question,
and solve each at the parameters stated. Do not invent artificial readings just to fill the list.
Return alternatives with reading, numeric answer as an exact fraction/integer, tolerance 0 unless explicitly
stated. An empty list is allowed when there is no plausible alternative. No solution key is provided."""
BLIND_PROMPT = """Solve this question independently. Return only the final numeric answer as an exact
fraction or integer string (not a rounded decimal). No reference solver or answer key is available."""


class Pipeline:
    def __init__(self, models, *, output, funnel, sandbox=None, trials=20000, max_similarity=.70,
                 priority=PRIORITY):
        if trials < 1000 or not 0 < max_similarity < 1:
            raise ValueError("Invalid forge verification settings")
        self.models, self.state = models, models.state
        self.output, self.funnel = Path(output), Path(funnel)
        self.sandbox = sandbox or Sandbox()
        self.trials, self.max_similarity, self.priority = trials, max_similarity, tuple(priority)
        settings = {"trials": trials, "max_similarity": max_similarity}
        if self.state.data.setdefault("verification_settings", settings) != settings:
            raise ValueError("Resume with the original verification settings or a new private work directory")

    def attempt(self, item, stage):
        if stage not in item["attempted"]:
            item["attempted"].append(stage)
        item["current_stage"] = stage
        self.state.save()

    def passed(self, item, stage, details=None):
        item["gates"][stage] = {"passed": True, **(details or {})}
        self.state.save()

    def call(self, item, stage, payload, schema, instructions, author=False):
        self.attempt(item, stage)
        parsed = self.models.call(stage, payload, schema, instructions, author=author)
        self.passed(item, stage)
        return parsed

    def forge_one(self, question, item, statements):
        extracted = self.call(item, "answer_pass", {"question": question.statement, "solution": question.solution},
                              schemas.ANSWER, ANSWER_PROMPT)
        if (not extracted["quote"] or extracted["quote"] not in question.solution
                or (extracted["answer"] != "none" and extracted["answer"] not in extracted["quote"])):
            raise Reject("answer_pass", "quote_not_verbatim")
        item["class"] = extracted["class"]
        self.state.save()
        if extracted["class"] != "numeric_single":
            return None
        self.attempt(item, "numeric_answer")
        answer = stored_answer(extracted, question.solution)
        self.passed(item, "numeric_answer")
        draft = self.call(item, "author", {"question": question.statement, "answer": str(answer.value),
                            "tolerance": str(answer.tolerance)}, schemas.AUTHOR, AUTHOR_PROMPT, author=True)
        template_id = "forge_" + hashlib.sha256(json.dumps(draft, sort_keys=True).encode()).hexdigest()[:16]
        existing = self.state.data["mapping"].get(template_id)
        if existing and existing["question_id"] != question.question_id:
            raise Reject("novelty", "duplicate_generated_template")
        self.attempt(item, "parameters")
        points, original = points_for(draft["parameters"])
        validate_variant(draft, original)
        self.passed(item, "parameters", {"instance_count": len(points), "original": original, "edges_included": True})
        self.attempt(item, "original_answer")
        baseline = self.sandbox.run(draft["solver"], "solve", original)
        baseline_answer = number(baseline["answer"])
        error = abs(baseline_answer - answer.value)
        if error > answer.tolerance:
            raise Reject("original_answer", "stored_answer_mismatch", {"stored": str(answer.value),
                         "computed": str(baseline_answer), "error": str(error)})
        self.passed(item, "original_answer", {"stored": str(answer.value), "computed": str(baseline_answer),
                    "error": str(error), "tolerance": str(answer.tolerance)})
        self.attempt(item, "novelty")
        similarity = max(near_verbatim(draft["text"], statements), near_verbatim(render(draft["text"], original), statements))
        if similarity >= self.max_similarity:
            raise Reject("novelty", "near_verbatim", {"similarity": similarity, "maximum": self.max_similarity})
        self.passed(item, "novelty", {"similarity": similarity, "maximum": self.max_similarity,
                    "comparisons": len(statements)})
        # Deliberately no ranges, original answer, solution, solver, wrong methods,
        # steps, author response or earlier messages in this separate request.
        simulator = self.call(item, "simulator", {
            "question": draft["text"], "part2_question": draft["part2"]["text"] if draft["part2"]["enabled"] else ""},
            schemas.SIMULATOR, SIM_PROMPT, author=True)
        self.attempt(item, "wrong_methods")
        self.attempt(item, "monte_carlo")
        computed, mc = instances(draft, points, simulator["code"], self.sandbox, answer.tolerance, self.trials)
        self.passed(item, "wrong_methods", {"method_count": len(draft["wrong"]), "points": len(points)})
        self.passed(item, "monte_carlo", mc)
        self.passed(item, "steps", {"named_values": len(draft["step_names"]), "points": len(points)})
        self.passed(item, "simulator_independence", {"question_only_call": True,
                    "allowed_imports_only": True, "random_draws_verified": True})
        readings = self.call(item, "reading_model", {"question": question.statement}, schemas.READINGS, READINGS_PROMPT)
        self.attempt(item, "readings")
        self.passed(item, "readings", ambiguity(readings["alternatives"], answer))
        # Index 0 is the stored/original point. Choose a genuinely new point.
        twin = next(value for value in computed if value["params"] != original)
        blind = self.call(item, "blind_model", {"question": twin["text"]}, schemas.BLIND, BLIND_PROMPT)
        self.attempt(item, "blind_checker")
        if number(blind["answer"]) != number(twin["answer"]):
            raise Reject("blind_checker", "answer_mismatch", {"checker": str(number(blind["answer"])), "solver": twin["answer"]})
        self.passed(item, "blind_checker", {"solver": twin["answer"], "checker": str(number(blind["answer"]))})
        part2_check = {"passed": False, "status": "not_requested"}
        if draft["part2"]["enabled"]:
            self.attempt(item, "part2")
            try:
                part2_check, part2_instances = self.part2(draft, points, original, simulator["part2_code"], statements, item)
                for instance, extra in zip(computed, part2_instances):
                    instance["part2"] = extra
                self.passed(item, "part2", part2_check)
            except Reject as failure:
                part2_check = {"passed": False, "stage": failure.stage, "reason": failure.reason, **failure.details}
                item["gates"]["part2"] = part2_check
                self.state.save()
        verification = {key: value for key, value in item["gates"].items() if key in {
            "parameters", "original_answer", "novelty", "monte_carlo", "wrong_methods", "steps", "simulator_independence",
            "readings", "blind_checker"}}
        verification["part2"] = part2_check
        topic = min(question.topics, key=lambda t: self.priority.index(t) if t in self.priority else len(self.priority))
        return {"template_id": template_id, "topic": topic, "topics": list(question.topics),
                "difficulty": question.difficulty, "models": {"author": self.models.author.model,
                "checker": self.models.checker.model}, "verification": verification,
                "review_status": "pending_builder_review", "instances": computed}

    def part2(self, draft, base_points, original, simulator, statements, item):
        variant = draft["part2"]
        extra = variant["parameter"]
        if extra["name"] in original:
            raise Reject("part2", "parameter_not_new")
        grids, part_original = parameter_grid([*draft["parameters"], extra])
        validate_variant(variant, part_original)
        similarity = max(near_verbatim(variant["text"], statements), near_verbatim(render(variant["text"], part_original), statements))
        if similarity >= self.max_similarity:
            raise Reject("part2", "near_verbatim", {"similarity": similarity})
        values = grids[extra["name"]]
        selected = [{**point, extra["name"]: values[i % len(values)]} for i, point in enumerate(base_points)]
        # Also verify all base and extra-parameter edges, even if not exported.
        edges, _ = points_for([*draft["parameters"], extra])
        points = list({tuple(sorted(p.items())): p for p in [*selected, *edges]}.values())
        computed, mc = instances(variant, points, simulator, self.sandbox, Fraction(0), self.trials)
        lookup = {tuple(sorted(row["params"].items())): row for row in computed}
        exported = [lookup[tuple(sorted(point.items()))] for point in selected]
        twin = next(row for row in exported if row["params"] != part_original)
        blind = self.call(item, "part2_blind_model", {"question": twin["text"]}, schemas.BLIND, BLIND_PROMPT)
        if number(blind["answer"]) != number(twin["answer"]):
            raise Reject("part2", "blind_mismatch")
        return {"passed": True, "monte_carlo": mc, "blind_solver": twin["answer"],
                "blind_checker": str(number(blind["answer"])), "similarity": similarity,
                "wrong_methods_verified": True}, exported

    def report(self, counts, questions, status):
        empty_stages = lambda: {name: {"attempted": 0, "passed": 0} for name in STAGES}
        all_topics = {t for question in questions for t in question.topics}
        overall, by_topic = empty_stages(), {t: empty_stages() for t in sorted(all_topics)}
        classes = Counter({kind: 0 for kind in CLASSES})
        class_topics = {t: Counter({kind: 0 for kind in CLASSES}) for t in sorted(all_topics)}
        failures = Counter()
        def stage(table, name, passed):
            row = table.setdefault(name, {"attempted": 0, "passed": 0})
            row["attempted"] += 1
            row["passed"] += int(passed)
        for item in self.state.data["items"].values():
            if "class" in item:
                classes[item["class"]] += 1
            for topic in item["topics"]:
                if "class" in item:
                    counter = class_topics.setdefault(topic, Counter())
                    counter[item["class"]] += 1
            attempted = list(dict.fromkeys([*item["attempted"], *item["gates"]]))
            for name in attempted:
                passed = item["gates"].get(name, {}).get("passed", False)
                stage(overall, name, passed)
                for topic in item["topics"]:
                    stage(by_topic.setdefault(topic, {}), name, passed)
            if item["status"] == "rejected":
                failures[item["failure"]["stage"] + ":" + item["failure"]["reason"]] += 1
            stage(overall, "accepted", item["status"] == "accepted")
            for topic in item["topics"]:
                stage(by_topic.setdefault(topic, {}), "accepted", item["status"] == "accepted")
        billing, stage_billing, topic_billing = {}, {}, {}
        def charge(table, key, row):
            total = table.setdefault(key, {"cost_usd": Decimal(0), "calls": 0, "prompt_tokens": 0,
                     "completion_tokens": 0, "latency_s": 0, "usage_unknown_calls": 0})
            total["cost_usd"] += Decimal(row["cost_usd"])
            for field in ("prompt_tokens", "completion_tokens", "latency_s"):
                total[field] += row[field]
            total["calls"] += 1
            total["usage_unknown_calls"] += int(not row["usage_known"])
        for row in self.state.data["calls"].values():
            charge(billing, row["backend"], row)
            charge(stage_billing, row.get("stage", "unknown"), row)
            for topic in row.get("topics", ()):
                charge(topic_billing, topic, row)
        for table in (billing, stage_billing, topic_billing):
            for total in table.values():
                total["cost_usd"] = str(total["cost_usd"])
        accepted = sum(item["status"] == "accepted" for item in self.state.data["items"].values())
        completed = sum(item["status"] in {"accepted", "rejected", "not_numeric"} for item in self.state.data["items"].values())
        report = {"format_version": 1, "status": status, "loader": counts,
                  "loaded_per_topic": dict(Counter(t for q in questions for t in q.topics)),
                  "loader_per_topic": getattr(counts, "per_topic", {}),
                  "completed_questions": completed, "accepted_templates": accepted,
                  "acceptance_rate": accepted / completed if completed else None,
                  "cost_per_accepted_template_usd": str(self.models.spent() / accepted) if accepted else None,
                  "stages": overall, "per_topic": by_topic, "classes": dict(classes),
                  "classes_per_topic": {k: dict(v) for k, v in class_topics.items()}, "failures": dict(failures),
                  "billing": billing, "billing_per_stage": stage_billing, "billing_per_topic": topic_billing, "cost_usd": str(self.models.spent()),
                  "budget_usd": str(self.models.budget), "prices_per_million": self.state.data.get("prices", {}),
                  "latency_s": sum(row["latency_s"] for row in self.state.data["calls"].values()),
                  "configuration": {"trials": self.trials, "max_similarity": self.max_similarity},
                  "latency_basis": "recorded_model_calls_once",
                  "live_pilot_verified": False, "builder_audit_complete": False}
        atomic_json(self.funnel, report)
        return report

    def run(self, questions, counts, limit=100):
        if limit <= 0:
            raise ValueError("Limit must be positive")
        priority = lambda q: min((self.priority.index(t) for t in q.topics if t in self.priority), default=len(self.priority))
        selected = sorted(questions, key=priority)[:limit]
        statements = [q.statement for q in questions]
        status = "completed"
        try:
            for question in selected:
                item = self.state.data["items"].setdefault(question.key, {"status": "pending", "topics": list(question.topics),
                    "question_id": question.question_id, "attempted": [], "gates": {}})
                if item["status"] in {"accepted", "rejected", "not_numeric"}:
                    continue
                self.models.current_topics = question.topics
                try:
                    artifact = self.forge_one(question, item, statements)
                    if artifact is None:
                        item["status"] = "not_numeric"
                    else:
                        atomic_json(self.output / (artifact["template_id"] + ".json"), artifact)
                        self.state.data["mapping"][artifact["template_id"]] = {
                            "question_id": question.question_id, "statement_sha256": question.statement_sha256}
                        atomic_json(self.state.root / "mapping.json", self.state.data["mapping"])
                        item["status"] = "accepted"
                except Reject as failure:
                    stage = item.get("current_stage", failure.stage) if failure.stage in {"model", "answer", "sandbox"} else failure.stage
                    item["failure"] = {"stage": stage, "reason": failure.reason, **failure.details}
                    item["gates"][stage] = {"passed": False, "reason": failure.reason, **failure.details}
                    item["status"] = "rejected"
                self.state.save()
                self.report(counts, questions, "running")
        except BudgetStop:
            status = "budget_stop"
        except ReplayMissing:
            status = "replay_missing"
        except ResumeBlocked:
            status = "unresolved_call"
        except KeyboardInterrupt:
            status = "interrupted"
        finally:
            self.state.save()
            report = self.report(counts, questions, status)
        return report
