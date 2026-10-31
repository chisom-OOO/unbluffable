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


class FirstOnlySpark:
    """A careful chatbot that sees one answer: it says "understands" unless the number is a named error."""

    def __init__(self):
        self.calls = []

    async def structured(self, text, kind, effort, schema, prompt):
        self.calls.append((kind, text))
        if not kind.startswith("evidence_"):
            return extraction(kind, text), {"model": "fake"}
        assert "Question 2" not in text  # run 2: the chatbots never see the twin
        return {"verdict": "does_not_understand" if "1/11" in text else "understands"}, {"model": "fake"}


def test_run2_arms_and_summary():
    provider = FirstOnlySpark()
    verdicts = asyncio.run(harness.evaluate(ITEMS, provider, runs=3, design="run2"))
    assert set(verdicts) == {"careful_first_only", "careful_answers_first_only", "unbluffable"}
    # Same prompts as the run-1 careful arms.
    prompts = harness.load_prompts()
    sent = {k: t for k, t in provider.calls if k.startswith("evidence_")}
    assert set(sent) == {"evidence_careful_first_only", "evidence_careful_answers_first_only"}
    assert "Verified exact answer to question 1" in sent["evidence_careful_answers_first_only"]
    # The recited twin (memorised) fools a chatbot that sees only the original; the engine uses the twin.
    assert verdicts["careful_first_only"][0]["recited"] == "understands"
    assert verdicts["unbluffable"][0]["recited"] == "does_not_understand"
    results = harness.summarise(ITEMS, verdicts, {"design": "run2", "runs": 3, "backend": "fake", "model": "fake", "git_commit": "abc",
                                                  "items_file": "items.json", "items_sha256": "0" * 64,
                                                  "prompt_sha256": {k: harness.sha256(v) for k, v in prompts.items()},
                                                  "created_at": "now"})
    assert set(results["mcnemar_vs_unbluffable"]) == {"careful_first_only", "careful_answers_first_only"}
    assert results["mcnemar_vs_unbluffable"]["careful_first_only"]["majority"]["b"] == 1
    rule = results["headline_rule"]
    assert rule["compared_with"] == "careful_answers_first_only" and rule["gap"] == 1
    md = harness.markdown(results)
    assert "| Careful Spark, original only | 3/4 |" in md and "| Unbluffable | 4/4 |" in md
    assert not any(word in md.lower() for word in BANNED)


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
    assert len(skipped) == 2 and "not both committed answers are right" in skipped[0] and "not an Unbluffable" in skipped[1]
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
    assert report == {"written": str(out), "items": 2, "understands": 1, "does_not_understand": 1, "left_out": []}
    assert json.loads(out.read_text(encoding="utf-8"))["design"] == "run2"
