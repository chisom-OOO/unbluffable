"""Invented families only; never reads the real bank or generated content."""
import copy
import csv
import json
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest

from forge.errors import BudgetStop, Reject
from forge.models import State

SOLVER = "from fractions import Fraction\ndef solve(params):\n value = Fraction(params['n'], 2)\n return {'answer': value, 'steps': {'Half Reward': value}}"
WRONG_A = "def solve(params): return params['n']"
WRONG_B = "from fractions import Fraction\ndef solve(params): return Fraction(params['n'], 3)"


def draft():
    return {"solver": SOLVER, "step_names": ["half_reward"], "wrong": [
        {"misconception": "ignores_probability", "code": WRONG_A},
        {"misconception": "uses_three_cases", "code": WRONG_B}]}


def source(tmp_path, family_count=1, count=75, numerical=False):
    rows = []
    for family in range(family_count):
        for i in range(1, count + 1):
            value = str(Fraction(i, 2))
            rows.append({"id": f"private-{family}-{i}", "family_id": str(family + 1),
                         "variant": str(i), "question": f"An invented fair beacon pays {i} credits with probability one half. Expected reward?",
                         "parameters": json.dumps({"n": i}), "verified_value": value,
                         "verification_result": "PASS_NUMERICAL" if numerical else "PASS_EXACT",
                         "verification_tolerance": "0.01" if numerical else "",
                         "topic": "expected value", "subtopic": "invented beacons", "difficulty": "Easy",
                         "solution": f"The invented final answer is {value}.", "reasoning_focus": "Multiply reward by probability.",
                         "interview_follow_up": "What if the reward doubles?",
                         "follow_up_discussion": "The expected reward doubles."})
    path = tmp_path / "invented.csv"
    write_rows(path, rows)
    return path, rows


def write_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)


class FakeModels:
    def __init__(self, root):
        self.state = State(root)
        self.author = SimpleNamespace(model="test-open-weights")
        self.checker = SimpleNamespace(model="test-meta")
        self.budget, self.calls = Decimal(5), []
        self.original, self.corrected = draft(), draft()
        self.interrupt = False

    def spent(self):
        return Decimal(0)

    def call(self, stage, payload, schema, instructions, *, author=False):
        assert author
        self.calls.append((stage, copy.deepcopy(payload)))
        if stage == "family_repair" and self.interrupt:
            self.interrupt = False
            raise BudgetStop()
        return copy.deepcopy(self.corrected if stage == "family_repair" else self.original)


class FakeSandbox:
    def __init__(self):
        self.bad_last = False
        self.offset = Fraction(0)
        self.duplicate_wrong = False

    def run_batch(self, code, params):
        result = []
        for point in params:
            n = Fraction(point["n"])
            if code == SOLVER:
                value = n / 2 + self.offset + (1 if self.bad_last and n == 75 else 0)
                steps = [{"name": "Half Reward", "value": str(value)}]
            elif code == WRONG_A:
                value, steps = n, []
            elif code == WRONG_B:
                value, steps = n if self.duplicate_wrong else n / 3, []
            else:
                raise Reject("sandbox", "TypeError")
            result.append({"answer": str(value), "steps": steps})
        return result


def setup(tmp_path, **kwargs):
    from forge.families import FamilyForge, load_families
    path, rows = source(tmp_path, **kwargs)
    families = load_families(path)
    models, sandbox = FakeModels(tmp_path / "private"), FakeSandbox()
    forge = FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "report.json", sandbox=sandbox)
    return path, rows, families, models, sandbox, forge


def test_loader_has_exact_values_and_explicit_numerical_tolerances(tmp_path):
    from forge.families import load_families
    path, _ = source(tmp_path, numerical=True)
    families = load_families(path)
    assert len(families) == 1 and len(families[0].variants) == 75
    assert families[0].variants[0].answer == Fraction(1, 2)
    assert families[0].variants[0].tolerance == Fraction(1, 100)


@pytest.mark.parametrize("case", ["count", "failed", "tolerance", "params", "unsafe_id", "duplicate"])
def test_bad_sources_stop_before_models(tmp_path, case):
    from forge.families import load_families
    path, rows = source(tmp_path, numerical=True)
    if case == "count": rows = rows[:19]
    elif case == "failed": rows[0]["verification_result"] = "FAIL"
    elif case == "tolerance": rows[0]["verification_tolerance"] = ""
    elif case == "params": rows[0]["parameters"] = "[1, 2]"
    elif case == "unsafe_id": rows[0]["family_id"] = "../outside"
    elif case == "duplicate": rows[-1]["variant"] = rows[0]["variant"]
    write_rows(path, rows)
    with pytest.raises(ValueError):
        load_families(path)


def test_all_seventy_five_variants_are_exported_with_no_code(tmp_path):
    _, rows, families, models, sandbox, forge = setup(tmp_path)
    report = forge.run(families)
    assert report["families_exported"] == report["misconceptions_verified"] == 1
    artifact = json.loads((tmp_path / "public" / "family_1.json").read_text())
    assert len(artifact["instances"]) == 75
    assert artifact["verification"]["solver"]["variants_checked"] == 75
    assert artifact["verification"]["misconceptions_verified"] is True
    assert artifact["topic"] == "expected value" and artifact["source_topic"] == "invented beacons"
    assert artifact["follow_up"] == {"question": rows[0]["interview_follow_up"], "reference": rows[0]["follow_up_discussion"]}
    for row, original in zip(artifact["instances"], rows):
        assert row["text"] == original["question"] and row["params"] == json.loads(original["parameters"])
        assert row["answer"] == original["verified_value"] and row["tolerance"] == "0"
        assert row["difficulty"] == "Easy" and row["topic"] == "expected value"
        assert row["spoken_text"] and row["interview_friendly"]
        assert len(row["wrong"]) == 2 and row["steps"][0]["name"] == "half_reward"
        assert row["separation"]["by_misconception"]
    public = (tmp_path / "public" / "family_1.json").read_text()
    for private in ["def solve", rows[0]["id"], rows[0]["solution"]]:
        assert private not in public
    assert len(models.calls) == 1
    assert len(models.calls[0][1]["examples"]) == 2
    before = (tmp_path / "public" / "family_1.json").read_bytes()
    forge.run(families)
    assert len(models.calls) == 1 and (tmp_path / "public" / "family_1.json").read_bytes() == before


def test_solver_must_pass_the_last_variant_not_just_two_examples(tmp_path):
    _, _, families, models, sandbox, forge = setup(tmp_path)
    sandbox.bad_last = True
    report = forge.run(families)
    assert report["misconceptions_verified"] == 0 and report["families_exported"] == 1
    assert [stage for stage, _ in models.calls] == ["family_author", "family_repair"]
    artifact = json.loads((tmp_path / "public" / "family_1.json").read_text())
    assert artifact["verification"]["misconceptions_verified"] is False
    assert artifact["verification"]["solver"]["passed"] is False
    assert len(artifact["instances"]) == 75 and all(row["wrong"] == [] for row in artifact["instances"])


def test_wrong_collision_repair_can_pass_and_duplicates_merge(tmp_path):
    _, _, families, models, sandbox, forge = setup(tmp_path)
    models.original["wrong"][0]["code"] = SOLVER
    sandbox.duplicate_wrong = True
    report = forge.run(families)
    assert report["accepted_after_repair"] == report["misconceptions_verified"] == 1
    artifact = json.loads((tmp_path / "public" / "family_1.json").read_text())
    assert all(len(row["wrong"]) == 1 and len(row["wrong"][0]["misconceptions"]) == 2 for row in artifact["instances"])


def test_persistent_wrong_collision_exports_empty_wrong_but_verified_steps(tmp_path):
    _, _, families, models, _, forge = setup(tmp_path)
    models.original["wrong"][0]["code"] = SOLVER
    models.corrected = copy.deepcopy(models.original)
    report = forge.run(families)
    assert report["families_exported"] == 1 and report["misconceptions_verified"] == 0
    artifact = json.loads((tmp_path / "public" / "family_1.json").read_text())
    assert artifact["verification"]["solver"]["passed"] is True
    assert all(row["wrong"] == [] and row["steps"] for row in artifact["instances"])


def test_numerical_tolerance_is_used_but_exact_rows_stay_exact(tmp_path):
    _, _, families, _, sandbox, forge = setup(tmp_path, numerical=True)
    sandbox.offset = Fraction(1, 1000)
    assert forge.run(families)["misconceptions_verified"] == 1
    artifact = json.loads((tmp_path / "public" / "family_1.json").read_text())
    assert all(row["tolerance"] == "1/100" for row in artifact["instances"])


def test_variant_followups_and_imported_wording_are_preserved(tmp_path):
    from forge.families import load_families
    path, rows, _, _, _, forge = setup(tmp_path)
    rows[1]["interview_follow_up"] = "A different invented follow-up."
    rows[0]["question"] = "An invented reward is 1 * 5 credits."
    write_rows(path, rows)
    forge.run(load_families(path))
    artifact = json.loads((tmp_path / "public" / "family_1.json").read_text())
    assert artifact["instances"][0]["text"] == rows[0]["question"]
    assert "one times five" in artifact["instances"][0]["spoken_text"]
    assert artifact["instances"][1]["follow_up"]["question"] == rows[1]["interview_follow_up"]


def test_budget_stop_exports_all_families_without_spending_and_leaves_them_resumable(tmp_path):
    _, _, families, models, _, forge = setup(tmp_path, family_count=2)
    original = models.call
    models.call = lambda *a, **k: (_ for _ in ()).throw(BudgetStop())
    report = forge.run(families)
    assert report["status"] == "budget_stop" and report["families_exported"] == 2
    assert report["misconceptions_verified"] == 0
    assert all(item["status"] == "pending" for item in models.state.data["items"].values())
    models.call = original
    assert forge.run(families)["misconceptions_verified"] == 2


def test_batch_sandbox_handles_typed_lists_strings_and_fresh_globals():
    from forge.sandbox import Sandbox
    code = """from fractions import Fraction
history=[]
def solve(params):
    history.append(1)
    value = sum(params['values']) + Fraction(params['ratio'])
    if params['label'] == 'double':
        value *= 2
    return {'answer': value, 'steps': {'history_size': len(history)}}
"""
    rows = [{"values": [1, 2], "ratio": "1/2", "label": "double"},
            {"values": [4, 1], "ratio": "1/4", "label": "single"}]
    result = Sandbox().run_batch(code, rows)
    assert [row["answer"] for row in result] == ["7", "21/4"]
    assert all(row["steps"] == [{"name": "history_size", "value": "1"}] for row in result)


@pytest.mark.parametrize("code", [
    "def solve(params):\n params['values'][0] = 2\n return 1",
    "import socket\ndef solve(params): return 1",
    "def solve(params): return 0.5",
])
def test_batch_sandbox_keeps_capability_and_exact_type_guards(code):
    from forge.sandbox import Sandbox
    with pytest.raises(Reject):
        Sandbox().run_batch(code, [{"values": [1]}])


def test_repair_budget_stop_is_resumable(tmp_path):
    _, _, families, models, _, forge = setup(tmp_path)
    models.original["solver"] = "broken"
    models.interrupt = True
    assert forge.run(families)["status"] == "budget_stop"
    assert forge.run(families)["misconceptions_verified"] == 1
    assert [stage for stage, _ in models.calls].count("family_author") == 1


def test_actual_record_replay_and_usage_ledger_with_fake_backend(tmp_path, monkeypatch):
    from forge.families import FamilyForge, load_families
    from forge.models import Models
    class Backend:
        def __init__(self, name):
            self.name, self.model, self.enforces_schema = name, "test-" + name, name == "meta_api"
            self.calls = []
        def complete(self, request):
            self.calls.append(request)
            name = request["response_format"]["json_schema"]["name"]
            body = draft()
            if name == "forge_family_author":
                body["solver"] = "broken"
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 200}}
    path, _ = source(tmp_path)
    families = load_families(path)
    author, checker = Backend("open_weights"), Backend("meta_api")
    state = State(tmp_path / "private")
    models = Models(state, mode="live", budget_usd=5, author=author, checker=checker)
    forge = FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "funnel.json", sandbox=FakeSandbox())
    assert forge.run(families)["accepted_after_repair"] == 1
    assert len(author.calls) == 2 and not checker.calls
    assert len(list((state.root / "calls").glob("*.json"))) == 2
    cost, original = models.spent(), (tmp_path / "public" / "family_1.json").read_bytes()
    state.data["items"], state.data["mapping"] = {}, {}
    state.save()
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    author.complete = checker.complete = lambda request: pytest.fail("Replay tried a live call")
    replay = Models(state, mode="replay", budget_usd=5, author=author, checker=checker)
    forge = FamilyForge(replay, output=tmp_path / "public", funnel=tmp_path / "funnel.json", sandbox=FakeSandbox())
    assert forge.run(families)["accepted_after_repair"] == 1
    assert replay.spent() == cost and (tmp_path / "public" / "family_1.json").read_bytes() == original


def test_family_cli_with_fake_models_and_zero_spend_resume(tmp_path, monkeypatch, capsys):
    from forge import family_run
    path, _ = source(tmp_path)
    monkeypatch.setattr(family_run, "ROOT", tmp_path)
    class Backend:
        name, model, enforces_schema = "open_weights", "test-author", False
        def complete(self, request):
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(draft())}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 200}}
    from forge import models as model_module
    backend = Backend()
    monkeypatch.setenv("BASETEN_API_KEY", "fake-test-key")
    monkeypatch.setenv("LLM_BACKEND", "open_weights")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setattr(family_run, "get_backend", lambda name: backend)
    checker = SimpleNamespace(name="meta_api", model="test-checker", enforces_schema=True)
    monkeypatch.setattr(model_module, "get_backend", lambda name: checker)
    monkeypatch.setattr(family_run, "Sandbox", lambda *a, **k: FakeSandbox())
    work = tmp_path / "data" / "forge" / "families1"
    args = ["--csv", str(path), "--mode", "live", "--work-dir", str(work)]
    assert family_run.main([*args, "--budget-usd", "0"]) == 2
    assert json.loads(capsys.readouterr().out)["families_exported"] == 1
    assert family_run.main([*args, "--budget-usd", "5"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["misconceptions_verified"] == 1 and Decimal(report["cost_usd"]) > 0
    assert (work / "funnel.json").exists() and (tmp_path / "forge" / "funnel.json").exists()
    assert family_run.main([*args, "--mode", "replay"]) == 0


@pytest.mark.parametrize("budget", ["-1", "6", "nan", "inf"])
def test_family_cli_rejects_invalid_budget_before_source_read(tmp_path, monkeypatch, budget):
    from forge import family_run
    monkeypatch.setattr(family_run, "ROOT", tmp_path)
    monkeypatch.setattr(family_run, "load_families", lambda path: pytest.fail("Invalid budget read source"))
    with pytest.raises(SystemExit):
        family_run.main(["--csv", str(tmp_path / "invented.csv"), "--budget-usd", budget])


def test_unavailable_replay_exports_pending_families_without_invented_verification(tmp_path):
    from forge.errors import ReplayMissing
    _, _, families, models, _, forge = setup(tmp_path, family_count=2)
    models.call = lambda *a, **k: (_ for _ in ()).throw(ReplayMissing())
    report = forge.run(families)
    assert report["status"] == "replay_missing"
    assert report["families_exported"] == report["unverified_exports"] == 2
    assert report["misconceptions_verified"] == 0 and report["pending_families"] == 2


def test_family_fallback_records_model_failure_without_retrying_it(tmp_path):
    _, _, families, models, _, forge = setup(tmp_path)
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(1)
        raise Reject("model", "recorded_failure")
    models.call = fail
    report = forge.run(families)
    assert report["families_exported"] == 1 and report["fallback_families"] == 1
    forge.run(families)
    assert attempts == [1]


def test_changing_source_cannot_reuse_a_finished_family_checkpoint(tmp_path):
    from forge.families import load_families
    path, rows, families, _, _, forge = setup(tmp_path)
    forge.run(families)
    rows[0]["question"] += " A changed invented setup."
    write_rows(path, rows)
    with pytest.raises(ValueError):
        forge.run(load_families(path))


def test_real_batch_solver_checks_all_seventy_five_points():
    from forge.sandbox import Sandbox
    solved = Sandbox().run_batch(SOLVER, [{"n": n} for n in range(1, 76)])
    assert len(solved) == 75
    assert all(Fraction(row["answer"]) == Fraction(n, 2) for n, row in enumerate(solved, 1))


def test_batch_converts_numeric_strings_recursively_but_preserves_labels_and_native_ints():
    from forge.sandbox import Sandbox
    code = """from fractions import Fraction
def solve(params):
    assert isinstance(params['ratio'], Fraction)
    assert isinstance(params['whole_string'], Fraction)
    assert isinstance(params['n'], int)
    assert params['label'] == 'heads'
    value = params['ratio'] * params['n'] + sum(params['nested'][0]) + params['nested'][1]['p']
    return {'answer': value, 'steps': {'whole': params['whole_string']}}
"""
    rows = [{"ratio": "1/3", "whole_string": "3", "n": 6, "label": "heads",
             "nested": [["1/6", "5/6"], {"p": "0.25"}]}]
    result = Sandbox().run_batch(code, rows)
    assert result == [{"answer": "13/4", "steps": [{"name": "whole", "value": "3"}]}]


def test_targeted_recheck_uses_cached_drafts_and_leaves_other_items_and_exports_unchanged(tmp_path):
    _, _, families, models, sandbox, forge = setup(tmp_path, family_count=2)
    sandbox.bad_last = True
    forge.run(families)
    untouched = copy.deepcopy(models.state.data["items"]["family_2"])
    untouched_bytes = (tmp_path / "public" / "family_2.json").read_bytes()
    sandbox.bad_last = False
    before_calls = copy.deepcopy(models.calls)
    models.call = lambda *a, **k: pytest.fail("Cached recheck spent on a model call")
    report = forge.run(families, recheck_families=["1"])
    assert report["recheck"]["verified"] == 1
    assert report["recheck"]["additional_model_calls"] == 0
    assert report["recheck"]["additional_cost_usd"] == "0"
    assert models.state.data["items"]["family_2"] == untouched
    assert (tmp_path / "public" / "family_2.json").read_bytes() == untouched_bytes
    assert models.calls == before_calls
    artifact = json.loads((tmp_path / "public" / "family_1.json").read_text())
    assert artifact["verification"]["misconceptions_verified"] is True
    sandbox.run_batch = lambda *a, **k: pytest.fail("Finished recheck ran again")
    forge.run(families, recheck_families=["1"])


def test_recheck_can_recover_original_if_corrected_draft_has_unrelated_error(tmp_path):
    _, _, families, models, sandbox, forge = setup(tmp_path)
    models.corrected["solver"] = "broken"
    sandbox.bad_last = True
    forge.run(families)
    sandbox.bad_last = False
    models.call = lambda *a, **k: pytest.fail("Recheck made a new model call")
    forge.run(families, recheck_families=["1"])
    item = models.state.data["items"]["family_1"]
    assert item["status"] == "verified" and item["rechecked_draft"] == "draft"


def test_recheck_never_loosens_a_wrong_method_collision_gate(tmp_path):
    _, _, families, models, _, forge = setup(tmp_path)
    models.original["wrong"][0]["code"] = SOLVER
    models.corrected = copy.deepcopy(models.original)
    forge.run(families)
    models.call = lambda *a, **k: pytest.fail("Recheck made a new model call")
    report = forge.run(families, recheck_families=["1"])
    assert report["recheck"]["verified"] == 0 and report["recheck"]["fallback"] == 1
    artifact = json.loads((tmp_path / "public" / "family_1.json").read_text())
    assert all(row["wrong"] == [] for row in artifact["instances"])


def test_unknown_recheck_family_does_not_touch_state(tmp_path):
    _, _, families, models, _, forge = setup(tmp_path)
    before = copy.deepcopy(models.state.data)
    with pytest.raises(ValueError):
        forge.run(families, recheck_families=["not-in-source"])
    assert models.state.data == before


@pytest.mark.parametrize("selection", ["", ",", "   "])
def test_family_cli_rejects_empty_explicit_recheck_before_source_read(tmp_path, monkeypatch, selection):
    from forge import family_run
    monkeypatch.setattr(family_run, "ROOT", tmp_path)
    monkeypatch.setattr(family_run, "load_families", lambda path: pytest.fail("Empty recheck read source"))
    with pytest.raises(SystemExit):
        family_run.main(["--csv", str(tmp_path / "invented.csv"), "--recheck-families", selection])


@pytest.mark.parametrize("code", [
    "import math\ndef solve(params): return math.comb(params['n'], 2)",
    "import fractions as f\ndef solve(params): return f.Fraction(params['n'], 2)",
])
def test_plain_allowed_imports_work_in_batched_solver(code):
    from forge.sandbox import Sandbox
    result = Sandbox().run_batch(code, [{"n": 4}])
    assert result[0]["answer"] in {"6", "2"}


@pytest.mark.parametrize("code", [
    "import os\ndef solve(params): return 1",
    "import socket\ndef solve(params): return 1",
    "from fractions import sys\ndef solve(params): return 1",
])
def test_plain_import_fix_does_not_expand_allowed_modules_or_members(code):
    from forge.sandbox import Sandbox
    with pytest.raises(Reject) as error:
        Sandbox().run_batch(code, [{"n": 4}])
    assert error.value.reason == "forbidden_import"


PERCENT_POINTS = "def solve(params): return {'answer': params['n'] * 50, 'steps': {'half_reward': params['n'] * 50}}"


def percentage_setup(tmp_path):
    from forge.families import FamilyForge, load_families
    path, rows = source(tmp_path)
    for row in rows:
        row["question"] = row["question"].replace("Expected reward?", "What is the expected reward, as an exact percentage?")
    write_rows(path, rows)
    families = load_families(path)
    models, sandbox = FakeModels(tmp_path / "private"), FakeSandbox()
    original = sandbox.run_batch
    sandbox.run_batch = lambda code, params: ([{"answer": str(Fraction(p["n"]) * 50), "steps": [{"name": "half_reward", "value": "0"}]}
                                              for p in params] if code == PERCENT_POINTS else original(code, params))
    forge = FamilyForge(models, output=tmp_path / "public", funnel=tmp_path / "report.json", sandbox=sandbox)
    return families, models, forge


def test_percentage_answer_must_be_a_fraction_of_one_not_percent_points(tmp_path):
    from forge.families import PROMPT
    families, models, forge = percentage_setup(tmp_path)
    models.original["solver"] = PERCENT_POINTS  # 50% returned as 50, the stored answer is 1/2
    report = forge.run(families)
    stages = [stage for stage, _ in models.calls]
    assert stages == ["family_author", "family_repair"]
    # The model sees each example's verified answer and is told the scale.
    assert [row["answer"] for row in models.calls[0][1]["examples"]] == ["1/2", "75/2"]
    assert "26% is Fraction(13, 50), not 26" in PROMPT
    # Percent points are never accepted; the repair is told exactly what went wrong.
    assert models.calls[1][1]["error"] == {"gate": "solver", "error_class": "percent_points_not_fraction", "variant_index": 0}
    assert report["misconceptions_verified"] == report["accepted_after_repair"] == 1


def test_percent_points_with_no_repair_left_stays_a_fallback(tmp_path):
    families, models, forge = percentage_setup(tmp_path)
    models.original["solver"] = models.corrected["solver"] = PERCENT_POINTS
    report = forge.run(families)
    assert report["misconceptions_verified"] == 0 and report["fallback_families"] == 1
    item = models.state.data["items"]["family_1"]
    assert item["failure"]["error_class"] == "percent_points_not_fraction"


def test_retry_reauthors_only_named_fallbacks_and_keeps_history(tmp_path):
    from forge.families import PROMPT_REVISION
    families, models, forge = percentage_setup(tmp_path)
    models.original["solver"] = models.corrected["solver"] = PERCENT_POINTS
    forge.run(families)
    models.original, models.corrected = draft(), draft()
    calls = len(models.calls)
    report = forge.run(families, retry_families=["1"])
    assert report["misconceptions_verified"] == 1 and len(models.calls) == calls + 1
    item = models.state.data["items"]["family_1"]
    assert item["retry_prompt_revision"] == PROMPT_REVISION
    assert item["retry_history"][0]["failure"]["error_class"] == "percent_points_not_fraction"
    # A second retry of an already retried family makes no calls.
    forge.run(families, retry_families=["1"])
    assert len(models.calls) == calls + 1
    with pytest.raises(ValueError):
        forge.run(families, retry_families=["1"], recheck_families=["1"])
