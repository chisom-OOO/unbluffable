"""Evidence items (scripts/evidence: itemcheck, make_items, fill_items, freeze, dry_run).
Real forge content, exact checks and a fake model only; no network."""

import hashlib
import json
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "evidence"))

import dry_run  # noqa: E402
import fill_items  # noqa: E402
import freeze  # noqa: E402
import itemcheck  # noqa: E402
from engine.bank import parse_instance, same_mistake  # noqa: E402


@pytest.fixture(scope="module")
def items():
    return itemcheck.make_items()


def filled(items):
    out = json.loads(json.dumps(items))
    for item in out:
        for part in ("original", "twin"):
            item[part]["transcript"] = dry_run.synthetic(item, part)
        item["source"] = "builder"
    return out


def test_forty_pairs_from_verified_quant_families_spread_across_topics(items):
    assert len(items) == 40
    assert Counter(i["category"] for i in items) == {"memorised": 10, "misconception": 10, "slip": 5, "correct": 15}
    assert len({i["template_id"] for i in items}) == 40
    assert len({i["topic"] for i in items}) >= 15
    families = {raw["template_id"]: raw for raw, _ in itemcheck.quant_families()}
    for item in items:
        raw = families[item["template_id"]]
        assert raw.get("pack", "quant") == "quant" and raw["verification"]["misconceptions_verified"]
        original, twin = item["instance_index"]["original"], item["instance_index"]["twin"]
        assert original != twin
        assert item["original"]["question"] == raw["instances"][original] and item["twin"]["question"] == raw["instances"][twin]
        assert raw["instances"][original].get("interview_friendly") is True
        assert item["original"]["transcript"] == item["twin"]["transcript"] == "" and item["source"] == ""
        assert item["label"] == itemcheck.LABELS[item["category"]]
        first, second = (parse_instance(item[p]["question"], p) for p in ("original", "twin"))
        if item["category"] in ("memorised", "slip"):
            assert first.answer != second.answer  # repeating the original's answer is detectable
        if item["category"] == "misconception":  # the engine's twin, aimed at the named mistake
            assert any(same_mistake(w.misconception, item["misconception"]) and w.value != second.answer for w in second.wrong)
    assert itemcheck.make_items() == items  # the same seed gives the same draft


def by(items, category):
    return next(i for i in items if i["category"] == category)


def said(x):
    return f"So the answer is {x.numerator}/{x.denominator}." if x.denominator != 1 else f"So the answer is {x.numerator}."


def test_checks_are_exact_for_every_category(items):
    for category in itemcheck.COUNTS:
        item = by(items, category)
        for part in ("original", "twin"):
            assert itemcheck.check(item, part, dry_run.synthetic(item, part))[0], (category, part)
    correct = by(items, "correct")
    answer = parse_instance(correct["twin"]["question"], "t").answer
    assert itemcheck.check(correct, "twin", said(answer))[0]
    assert not itemcheck.check(correct, "twin", said(answer + 1))[0]
    assert not itemcheck.check(correct, "twin", "I'm not sure.")[0]
    assert not itemcheck.check(correct, "twin", "  ")[0]
    # Misconception: its named wrong value, not another one and not the answer.
    mis = by(items, "misconception")
    inst = parse_instance(mis["original"]["question"], "o")
    named = next(w.value for w in inst.wrong if same_mistake(w.misconception, mis["misconception"]))
    assert itemcheck.check(mis, "original", said(named))[0]
    assert not itemcheck.check(mis, "original", said(inst.answer))[0]
    # Memorised: the twin repeats the original's answer, or fails it; never the twin's answer.
    mem = by(items, "memorised")
    first, twin = (parse_instance(mem[p]["question"], p) for p in ("original", "twin"))
    assert itemcheck.check(mem, "twin", said(first.answer)) == (True, "repeats the original's answer")
    assert not itemcheck.check(mem, "twin", said(twin.answer))[0]
    assert not itemcheck.check(mem, "original", said(first.answer + 1))[0]
    # Slip: not a named wrong value and not the original's answer.
    slip = by(items, "slip")
    sfirst, stwin = (parse_instance(slip[p]["question"], p) for p in ("original", "twin"))
    assert not itemcheck.check(slip, "twin", said(stwin.wrong[0].value))[0] or stwin.wrong[0].value == stwin.answer
    assert not itemcheck.check(slip, "twin", said(sfirst.answer))[0]


def test_committed_number_is_the_last_one_said_and_reads_words():
    assert itemcheck.committed("There are 9 options and 3 good ones, so two thirds.").value == Fraction(2, 3)
    assert itemcheck.committed("No numbers here.") is None


def scripted(lines):
    queue = list(lines)

    def ask(prompt=""):
        if not queue:
            raise EOFError
        return queue.pop(0)
    return ask


def test_fill_checks_saves_after_every_item_and_resumes(tmp_path, items):
    path = tmp_path / "draft.json"
    itemcheck.write(path, items)
    first, second = items[0], items[1]
    good = lambda item, part: dry_run.synthetic(item, part)
    # Item 1: a rejected transcript, then accepted ones; item 2: skipped; then stop.
    fill_items.fill(path, scripted([
        "So the answer is 999999.", ".", good(first, "original"), ".", good(first, "twin"), ".", "t",
        "skip", "quit"]))
    saved = itemcheck.read(path)
    assert saved[0]["original"]["transcript"] == good(first, "original") and saved[0]["source"] == "tester"
    assert saved[1]["original"]["transcript"] == "" and saved[1]["source"] == ""
    # Run again: it carries on from item 2.
    fill_items.fill(path, scripted([good(second, "original"), ".", good(second, "twin"), ".", "m", "quit"]))
    saved = itemcheck.read(path)
    assert saved[1]["source"] == "model-written" and saved[0]["source"] == "tester"
    assert saved[2]["original"]["transcript"] == ""


def test_freeze_refuses_empty_or_off_category_transcripts_then_prints_the_hash(tmp_path, items, capsys):
    path = tmp_path / "items.json"
    itemcheck.write(path, items)
    assert freeze.main(["--items", str(path)]) == 1
    assert "needs a transcript" in capsys.readouterr().out
    done = filled(items)
    done[3]["twin"]["transcript"] = "My answer is 999999, because."
    itemcheck.write(path, done)
    assert freeze.main(["--items", str(path)]) == 1 and f"{done[3]['id']}.twin" in capsys.readouterr().out
    done = filled(items)
    itemcheck.write(path, done)
    assert freeze.main(["--items", str(path)]) == 0
    out = capsys.readouterr().out
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert f"sha256 {digest}" in out
    assert f"--backend meta_api --runs 3 --expect-items-sha256 {digest}" in out


def test_dry_run_runs_every_arm_with_a_fake_model_and_estimates_cost(tmp_path, items):
    path = tmp_path / "draft.json"
    itemcheck.write(path, items)
    out = dry_run.dry_run(path, runs=3)
    cost = out["cost"]
    # 3 chatbot arms x 40 items x 3 runs, and 2 answers x 2 calls x 40 items x 3 runs for Unbluffable.
    assert cost["calls_by_kind"] == {"evidence_plain": 120, "evidence_careful": 120, "evidence_careful_answers": 120,
                                     "minimal": 240, "extraction": 240}
    assert 0 < float(cost["usd_estimate"]) < float(cost["usd_upper_bound"])
    assert set(out["results"]["arms"]) == {"plain", "careful", "careful_answers", "unbluffable"}
    assert itemcheck.read(path) == items  # the draft itself is untouched
