"""Exploratory comparison (decision log 47, not pre-registered): careful_first_only against
Unbluffable on the frozen run-1 items, through the harness's own functions. Fakes only."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "evidence"))

import exploratory  # noqa: E402
import harness  # noqa: E402
from test_evidence_harness import ITEMS  # noqa: E402
from test_evidence_run2 import RUN2_PROVENANCE, Run2Spark  # noqa: E402

CATEGORY = {"sound": "correct", "recited": "memorised", "named": "misconception", "decimals": "correct"}
ITEMS_CAT = [{**i, "category": CATEGORY[i["id"]]} for i in ITEMS]
PROV = {**RUN2_PROVENANCE, "design": exploratory.DESIGN}


def run(provider):
    exploratory.register()
    failures = []
    verdicts = asyncio.run(harness.evaluate(ITEMS_CAT, provider, runs=3, design=exploratory.DESIGN, failures=failures))
    return verdicts, failures


def test_the_harness_files_are_not_changed_by_the_plan():
    assert exploratory.DESIGN not in harness.DESIGNS or harness.DESIGNS[exploratory.DESIGN] == exploratory.ARMS
    source = (ROOT / "scripts" / "evidence" / "harness.py").read_text(encoding="utf-8")
    assert "exploratory" not in source  # the two-arm plan is added at run time only
    assert {"scripts/evidence/exploratory.py", "eval/items_draft.json"} <= set(exploratory.CHECKED_PATHS)
    assert set(harness.FROZEN_PATHS) <= set(exploratory.CHECKED_PATHS)


def test_two_arms_first_only_never_sees_the_twin_and_the_report_counts_flags_per_category():
    provider = Run2Spark()  # asserts the first-only arm never sees question 2
    verdicts, failures = run(provider)
    assert list(verdicts) == ["careful_first_only", "unbluffable"] and not failures
    r = exploratory.report(ITEMS_CAT, verdicts, PROV, failures)
    assert r["status"] == "complete" and "EXPLORATORY, not pre-registered" in r["label"]
    first, ours = (r["arms"][a]["categories"] for a in exploratory.ARMS)
    # The recited answer is right on the original, so first-only cannot flag it; Unbluffable can.
    assert first["memorised"]["flagged"] == 0 and ours["memorised"]["flagged"] == 1
    assert first["misconception"]["flagged"] == 1 and first["correct"]["flagged"] == 0
    assert first["memorised"]["flagged_per_run"] == [0, 0, 0]
    assert r["recited_items"] == [{"id": "recited", "careful_first_only": "understands", "unbluffable": "does_not_understand"}]
    assert r["recited_mcnemar"]["b"] == 1 and r["recited_mcnemar"]["c"] == 0
    md = exploratory.markdown(r)
    assert md.startswith("# EXPLORATORY, not pre-registered") and "model-written" in md and "| recited | 1 |" in md
    assert "INVALID" not in md


def test_any_failed_call_makes_the_run_invalid_with_no_test():
    class Failing(Run2Spark):
        async def structured(self, text, kind, effort, schema, prompt):
            if kind.endswith("_first_only"):
                from voice.recording import VoiceError
                raise VoiceError("The model request failed. Upstream timeout.")
            return await super().structured(text, kind, effort, schema, prompt)

    verdicts, failures = run(Failing())
    assert failures
    r = exploratory.report(ITEMS_CAT, verdicts, PROV, failures)
    assert r["status"] == harness.INVALID and "recited_mcnemar" not in r
    assert "INVALID" in exploratory.markdown(r)


def test_refuses_without_a_key_with_a_wrong_hash_or_with_uncommitted_files(monkeypatch, tmp_path, capsys):
    items = ["--items", str(ROOT / "eval" / "items_draft.json")]
    monkeypatch.setattr(harness, "missing_keys", lambda names: ["MODEL_API_KEY"])
    assert exploratory.main(items + ["--expect-items-sha256", "0" * 64]) == 2
    assert "MODEL_API_KEY" in capsys.readouterr().out
    monkeypatch.setattr(harness, "missing_keys", lambda names: [])
    monkeypatch.setattr(harness, "git", lambda *a: " M scripts/evidence/harness.py")
    assert exploratory.main(items + ["--expect-items-sha256", "0" * 64]) == 2
    assert "commit these first" in capsys.readouterr().out
    monkeypatch.setattr(harness, "git", lambda *a: "")
    assert exploratory.main(items + ["--expect-items-sha256", "0" * 64]) == 2
    assert "is not the frozen" in capsys.readouterr().out
