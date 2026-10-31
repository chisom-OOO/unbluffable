"""Evidence run 2: chatbots that see only the original question and transcript, Unbluffable on
the original and its twin, and items built from exported interview timelines. Fakes only."""

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "evidence"))

import freeze  # noqa: E402
import from_sessions  # noqa: E402
import harness  # noqa: E402
from engine import mathtext  # noqa: E402
from test_evidence_harness import BANNED, ITEMS, FIXTURE, extraction, instance  # noqa: E402


def test_first_only_messages_hold_the_original_alone():
    plain = harness.chatbot_message(ITEMS[0], with_answers=False, first_only=True)
    assert "Question 1" in plain and "Question 2" not in plain and ITEMS[0]["twin"]["transcript"] not in plain
    answers = harness.chatbot_message(ITEMS[0], with_answers=True, first_only=True)
    assert "Verified exact answer to question 1" in answers and "question 2" not in answers.lower().split("verified")[-1]


class Run2Spark:
    """First-only arms see one answer and say "understands" unless it is a named error; careful
    sees both and flags a repeat or a named error; plain says "understands" to everything."""

    def __init__(self):
        self.calls = []

    async def structured(self, text, kind, effort, schema, prompt):
        self.calls.append((kind, text))
        if not kind.startswith("evidence_"):
            return extraction(kind, text), {"model": "fake"}
        if kind.endswith("_first_only"):
            assert "Question 2" not in text  # the first-only chatbots never see the twin
            return {"verdict": "does_not_understand" if "1/11" in text else "understands"}, {"model": "fake"}
        assert "Question 2" in text  # careful and plain see the original and the twin, as in run 1
        if kind == "evidence_plain":
            return {"verdict": "understands"}, {"model": "fake"}
        answers = re.findall(r"answer is (.+?)[,.]\s", text)
        ok = answers[0] != answers[1] and "1/11" not in text
        return {"verdict": "understands" if ok else "does_not_understand"}, {"model": "fake"}


RUN2_PROVENANCE = {"design": "run2", "runs": 3, "backend": "fake", "model": "fake", "git_commit": "abc",
                   "items_file": "items.json", "items_sha256": "0" * 64, "created_at": "now"}


def test_run2_arms_and_summary():
    provider = Run2Spark()
    verdicts = asyncio.run(harness.evaluate(ITEMS, provider, runs=3, design="run2"))
    assert list(verdicts) == ["careful_first_only", "careful_answers_first_only", "careful", "plain", "unbluffable"]
    # Same prompts as the run-1 arms.
    prompts = harness.load_prompts()
    sent = {k: t for k, t in provider.calls if k.startswith("evidence_")}
    assert set(sent) == {"evidence_careful_first_only", "evidence_careful_answers_first_only",
                         "evidence_careful", "evidence_plain"}
    assert "Verified exact answer to question 1" in sent["evidence_careful_answers_first_only"]
    # The recited twin (memorised) fools a chatbot that sees only the original; the engine uses the twin.
    assert verdicts["careful_first_only"][0]["recited"] == "understands"
    assert verdicts["careful"][0]["recited"] == "does_not_understand"
    assert verdicts["unbluffable"][0]["recited"] == "does_not_understand"
    results = harness.summarise(ITEMS, verdicts, {**RUN2_PROVENANCE,
                                                  "prompt_sha256": {k: harness.sha256(v) for k, v in prompts.items()}})
    # The headline comparison is read from the design: Unbluffable against careful_first_only.
    assert results["headline_comparison"] == "careful_first_only"
    assert results["secondary_comparisons"] == ["careful_answers_first_only", "careful", "plain"]
    assert list(results["mcnemar_vs_unbluffable"])[0] == "careful_first_only"
    assert results["mcnemar_vs_unbluffable"]["careful_first_only"]["majority"]["b"] == 1
    assert results["mcnemar_vs_unbluffable"]["plain"]["majority"]["b"] == 2
    rule = results["headline_rule"]
    assert rule["compared_with"] == "careful_first_only" and (rule["unbluffable_correct"], rule["compared_correct"]) == (4, 3)
    md = harness.markdown(results)
    assert "| Careful Spark, original only | 3/4 |" in md and "| Unbluffable | 4/4 |" in md
    head, secondary = md.split("Secondary comparisons:")
    assert "Headline comparison: Unbluffable against Careful Spark, original only." in head
    assert "| Careful Spark, original only | 1 | 0 |" in head.split("Headline comparison:")[1]
    assert all(f"| {name} |" in secondary.split("## ")[0] for name in ("Careful Spark", "Plain Spark"))
    assert "Careful Spark, original only 3/4" in md
    assert not any(word in md.lower() for word in BANNED)


def test_the_headline_arm_must_have_run():
    verdicts = asyncio.run(harness.evaluate(ITEMS, Run2Spark(), runs=1, design="run1"))
    try:
        harness.summarise(ITEMS, verdicts, {**RUN2_PROVENANCE, "prompt_sha256": {}})
    except ValueError as error:
        assert "careful_first_only" in str(error)
    else:
        raise AssertionError("a run-1 run summarised as run 2 must be refused")


def test_a_run2_item_file_only_runs_with_design_run2(tmp_path, monkeypatch, capsys):
    started = []
    for name in ("evaluate", "load_items", "missing_keys"):
        monkeypatch.setattr(harness, name, lambda *a, _n=name, **k: started.append(_n))
    items = write(tmp_path, "items.json", {"version": 1, "design": "run2", "items": []})
    assert harness.main(["--items", str(items), "--out", str(tmp_path / "out")]) == 2
    assert harness.main(["--items", str(items), "--design", "run1", "--out", str(tmp_path / "out")]) == 2
    assert not started and "--design run2" in capsys.readouterr().out
    # A file that names run 1 does not run as run 2 either.
    old = write(tmp_path, "old.json", {"version": 1, "design": "run1", "items": []})
    assert harness.main(["--items", str(old), "--design", "run2", "--out", str(tmp_path / "out")]) == 2
    assert not started and not (tmp_path / "out").exists()


def test_an_unknown_design_in_the_item_file_is_refused(tmp_path):
    path = write(tmp_path, "bad.json", {"version": 1, "design": "run9", "items": []})
    ok, problems, _ = freeze.freeze(path)
    assert not ok and "design must be one of" in problems[0]


# --- Items from exported interviews -----------------------------------------------------------

def export(original_answer, twin_answer, original=3, twin=0):
    """An Exam Room export: question events show the instance's display text."""
    shown = lambda i: mathtext.display(instance(i)["text"])  # noqa: E731
    return {"version": 1, "kind": "unbluffable-recorded-interview", "exported_at": "2026-11-01T10:00:00Z", "label": None,
            "events": [{"t": 0, "type": "question", "number": 1, "kind": "new", "text": shown(original)},
                       {"t": 1, "type": "answer_complete", "transcript": original_answer},
                       {"t": 2, "type": "interviewer_line", "kind": "close", "text": "Thanks."},
                       {"t": 3, "type": "question", "number": 2, "kind": "twin", "text": shown(twin)},
                       {"t": 4, "type": "answer_complete", "transcript": twin_answer},
                       {"t": 5, "type": "answer_complete", "transcript": "A later answer is not used."},
                       {"t": 6, "type": "session_end", "label": "supports"}]}


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_items_from_sessions_label_bluffs_and_keep_only_right_genuine_ones(tmp_path):
    index = from_sessions.instance_index(FIXTURE.parent)
    files = [("bluff", write(tmp_path, "b1.json", export("It is 5/36, I remember it.", "Again 5/36."))),
             ("genuine", write(tmp_path, "g1.json", export("Five of the outcomes work, so 5/36.", "Two outcomes work, so 1/18."))),
             ("genuine", write(tmp_path, "g2.json", export("Five ways, so 5/36.", "I think 1/12."))),  # twin wrong
             ("bluff", write(tmp_path, "bad.json", {"version": 1, "kind": "something else"}))]
    data, skipped = from_sessions.build(files, index)
    assert [(i["id"], i["category"], i["label"]) for i in data["items"]] == [
        ("s01", "bluff", "does_not_understand"), ("s02", "genuine", "understands")]
    first = data["items"][0]
    assert first["template_id"] == "fx_dice_total" and first["instance_index"] == {"original": 3, "twin": 0}
    assert first["original"]["transcript"] == "It is 5/36, I remember it." and first["twin"]["transcript"] == "Again 5/36."
    assert [(s["file"], s["category"]) for s in skipped] == [("g2.json", "genuine"), ("bad.json", "bluff")]
    assert "not both committed answers are right" in skipped[0]["reason"] and "not an Unbluffable" in skipped[1]["reason"]
    assert from_sessions.genuine_excluded(skipped) == {
        "count": 1, "by_reason": {"genuine, but not both committed answers are right": 1}, "files": ["g2.json"]}
    # freeze.py checks the file unchanged, and the harness loads it.
    path = write(tmp_path, "items_run2_draft.json", data)
    ok, problems, digest = freeze.freeze(path)
    assert ok and problems == [] and len(digest) == 64
    items, _ = harness.load_items(path)
    assert len(items) == 2


def test_a_run2_file_needs_both_kinds(tmp_path):
    index = from_sessions.instance_index(FIXTURE.parent)
    data, _ = from_sessions.build([("bluff", write(tmp_path, "b.json", export("5/36", "5/36")))], index)
    ok, problems, _ = freeze.freeze(write(tmp_path, "one.json", data))
    assert not ok and "needs both bluff and genuine" in problems[0]


def test_the_command_line_writes_the_draft(tmp_path, monkeypatch, capsys):
    real = from_sessions.instance_index
    monkeypatch.setattr(from_sessions, "instance_index", lambda directory=None: real(FIXTURE.parent))
    out = tmp_path / "eval" / "items_run2_draft.json"
    assert from_sessions.main(["--bluff", str(write(tmp_path, "b.json", export("5/36", "5/36"))),
                               "--genuine", str(write(tmp_path, "g.json", export("5/36", "1/18"))), "--out", str(out)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {"written": str(out), "items": 2, "understands": 1, "does_not_understand": 1, "genuine_sessions": 1,
                      "genuine_excluded": {"count": 0, "by_reason": {}, "files": []}, "left_out": []}
    assert json.loads(out.read_text(encoding="utf-8"))["design"] == "run2"


def test_the_report_counts_genuine_sessions_left_out_and_why(tmp_path, monkeypatch, capsys):
    real = from_sessions.instance_index
    monkeypatch.setattr(from_sessions, "instance_index", lambda directory=None: real(FIXTURE.parent))
    out = tmp_path / "items.json"
    genuine = [write(tmp_path, "g1.json", export("5/36", "1/18")),
               write(tmp_path, "g2.json", export("5/36", "1/12")),  # twin wrong
               write(tmp_path, "g3.json", export("1/11", "1/18")),  # original wrong
               write(tmp_path, "g4.json", {"version": 1, "kind": "something else"}),
               tmp_path / "missing.json"]
    assert from_sessions.main(["--bluff", str(write(tmp_path, "b.json", export("5/36", "5/36"))),
                               "--genuine", *map(str, genuine), "--out", str(out)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["genuine_sessions"] == 5 and report["understands"] == 1
    assert report["genuine_excluded"] == {
        "count": 4,
        "by_reason": {"genuine, but not both committed answers are right": 2, "not an Unbluffable interview export": 1,
                      "unreadable (FileNotFoundError)": 1},
        "files": ["g2.json", "g3.json", "g4.json", "missing.json"]}
    assert len(report["left_out"]) == 4


def test_freeze_prints_the_design_and_the_real_counts(tmp_path, capsys):
    index = from_sessions.instance_index(FIXTURE.parent)
    files = [("bluff", write(tmp_path, "b.json", export("5/36", "5/36"))),
             ("genuine", write(tmp_path, "g.json", export("5/36", "1/18"))),
             ("genuine", write(tmp_path, "h.json", export("Five ways, 5/36.", "So 1/18.")))]
    data, _ = from_sessions.build(files, index)
    path = write(tmp_path, "items_run2.json", data)
    assert freeze.main(["--items", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Live run (5 arms x 3 runs x 3 items):" in out and "(design run2)" in out
    commands = [line.strip() for line in out.splitlines() if line.strip().startswith("python ")]
    assert len(commands) == 2 and all("--design run2" in c for c in commands)
    assert commands[1].endswith("--design run2 --open-weights") and "2 more arms" in out
