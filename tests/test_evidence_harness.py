"""Evidence harness (scripts/evidence): statistics, items, arms, record/replay.
Fake model only: a scripted provider, or MetaVoice over an httpx mock transport
with a dummy key. No network."""

import asyncio
import json
import re
import sys
from fractions import Fraction
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "evidence"))

import harness  # noqa: E402
import stats  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "forge" / "fx_dice_total.json"
BANNED = ("can't be fooled", "calibrated", "proves understanding", "first")


def instance(i):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return data["instances"][i]


def item(item_id, label, original_said, twin_said, reasoning=True):
    why = ", because there are 36 outcomes and I counted the ways." if reasoning else "."
    return {"id": item_id, "label": label, "template_id": "fx_dice_total",
            "original": {"question": instance(3), "transcript": f"My answer is {original_said}{why}"},
            "twin": {"question": instance(0), "transcript": f"My answer is {twin_said}{why}"}}


# instance 3: total 6, 5/36; instance 0: total 3, 1/18
ITEMS = [
    item("sound", "understands", "5/36", "1/18"),
    item("recited", "does_not_understand", "5/36", "5/36"),
    item("named", "does_not_understand", "1/11", "1/11"),
    item("decimals", "understands", "0.139", "0.056"),
]


# --- Statistics ----------------------------------------------------------------------

def test_exact_mcnemar():
    assert stats.mcnemar_exact(0, 0) == 1.0
    assert stats.mcnemar_exact(5, 0) == 2 / 32
    assert stats.mcnemar_exact(1, 9) == pytest.approx(float(Fraction(22, 1024)))
    assert stats.mcnemar_exact(9, 1) == stats.mcnemar_exact(1, 9)
    assert stats.mcnemar_exact(3, 3) == 1.0


def test_majority_flips_and_scores():
    assert stats.majority(["understands", "understands", "error"]) == "understands"
    assert stats.majority(["understands", "does_not_understand", "error"]) == "no_majority"
    runs = [{"a": "understands", "b": "understands"}, {"a": "understands", "b": "does_not_understand"}]
    assert stats.flips(runs) == ["b"]
    labels = {"a": "understands", "b": "understands", "c": "does_not_understand"}
    s = stats.score(labels, {"a": "understands", "b": "does_not_understand", "c": "error"})
    assert (s["correct"], s["false_flags"], s["false_flag_rate"], s["errors"]) == (1, 1, 0.5, 1)
    assert stats.compare(labels, {"a": "understands", "b": "understands", "c": "understands"},
                         {"a": "understands", "b": "does_not_understand", "c": "does_not_understand"}) == \
        {"b": 1, "c": 1, "p": 1.0}


# --- Items ---------------------------------------------------------------------------

def test_item_file_is_validated_and_hashed(tmp_path):
    path = tmp_path / "items.json"
    path.write_text(json.dumps({"version": 1, "items": ITEMS}), encoding="utf-8")
    items, digest = harness.load_items(path)
    assert [i["id"] for i in items] == ["sound", "recited", "named", "decimals"] and len(digest) == 64
    for broken in ({**ITEMS[0], "label": "maybe"}, {**ITEMS[0], "twin": {"question": instance(0), "transcript": " "}},
                   {**ITEMS[0], "original": {"question": {**instance(3), "answer": "roughly"}, "transcript": "x"}}):
        path.write_text(json.dumps({"version": 1, "items": [broken]}), encoding="utf-8")
        with pytest.raises(harness.ItemError):
            harness.load_items(path)
    path.write_text(json.dumps({"version": 1, "items": [ITEMS[0], ITEMS[0]]}), encoding="utf-8")
    with pytest.raises(harness.ItemError):
        harness.load_items(path)


def test_chatbot_messages_hold_answers_only_for_the_answers_arm():
    plain = harness.chatbot_message(ITEMS[0], with_answers=False)
    given = harness.chatbot_message(ITEMS[0], with_answers=True)
    assert instance(3)["text"] in plain and instance(0)["text"] in plain
    assert "Verified exact answer" not in plain
    assert "Verified exact answer to question 1: 5/36" in given and "question 2: 1/18" in given


def test_prompts_are_in_the_repo_and_hashed_with_normalised_line_endings():
    prompts = harness.load_prompts()
    assert set(prompts) == {"plain", "careful", "careful_answers"}
    assert all('{"verdict": "understands"}' in p and "\r" not in p for p in prompts.values())
    assert "verified exact answer" in prompts["careful_answers"] and "verified" not in prompts["careful"]
    assert harness.sha256("a\n") == harness.sha256("a\r\n".replace("\r\n", "\n"))


# --- Arms with a scripted model ----------------------------------------------------

ANSWER = re.compile(r"answer is (.+?)[,.](?:\s|$)")


def extraction(kind, text):
    """Extraction for the Unbluffable arm: the span after "answer is", valid with a because-clause."""
    m = ANSWER.search(text)
    span = m.group(1) if m else "none"
    if kind == "minimal":
        return {"committed_number_text": span, "is_commitment": m is not None}
    quotes = [{"quote": "because there are 36 outcomes", "step": "other"}] if "because" in text else []
    return {"committed_answer_text": span, "reasoning_quotes": quotes,
            "reasoning_code": "valid" if quotes else "vague", "misconception_name": "none", "self_corrected": False}


class ScriptedProvider:
    """Plain Spark says "understands" to everything; careful arms flag repeats; run 2 of
    plain flips one item."""

    def __init__(self):
        self.calls = []

    async def structured(self, text, kind, effort, schema, prompt):
        self.calls.append((kind, effort))
        if not kind.startswith("evidence_"):
            return extraction(kind, text), {"model": "fake"}
        plain_calls = sum(1 for k, _ in self.calls if k == "evidence_plain")
        if kind == "evidence_plain":
            verdict = "does_not_understand" if plain_calls == 5 else "understands"
        else:
            answers = re.findall(r"answer is (.+?)[,.]\s", text)
            verdict = "understands" if answers[0] != answers[1] and "1/11" not in text else "does_not_understand"
        return {"verdict": verdict}, {"model": "fake"}


def test_four_arms_three_runs_and_summary():
    provider = ScriptedProvider()
    verdicts = asyncio.run(harness.evaluate(ITEMS, provider, runs=3))
    assert set(verdicts) == set(harness.ARMS) and all(len(v) == 3 for v in verdicts.values())
    # Unbluffable: the engine decides from exact checks; a recited twin and a named error are not understanding.
    assert verdicts["unbluffable"][0] == {"sound": "understands", "recited": "does_not_understand",
                                          "named": "does_not_understand", "decimals": "understands"}
    assert {e for k, e in provider.calls if k.startswith("evidence_")} == {harness.CHATBOT_EFFORT}

    results = harness.summarise(ITEMS, verdicts, {"runs": 3, "backend": "fake", "model": "fake", "git_commit": "abc",
                                                  "items_file": "items.json", "items_sha256": "0" * 64,
                                                  "prompt_sha256": {"plain": "1"}, "created_at": "now"})
    arms = results["arms"]
    assert arms["unbluffable"]["majority"]["correct"] == 4 and arms["unbluffable"]["flip_rate"] == 0
    assert arms["plain"]["majority"]["correct"] == 2  # says "understands" to all four
    assert arms["plain"]["flipped_items"] == ["sound"] and arms["plain"]["flip_rate"] == 0.25
    assert arms["plain"]["runs"][1]["false_flags"] == 1 and arms["plain"]["majority"]["false_flag_rate"] == 0
    assert results["mcnemar_vs_unbluffable"]["plain"]["majority"] == {"b": 2, "c": 0, "p": 0.5}
    rule = results["headline_rule"]
    assert (rule["unbluffable_correct"], rule["compared_correct"], rule["close"]) == (4, 4, True)
    assert rule["compared_with"] == results["headline_comparison"] == "careful_answers"  # run 1 (no design given)
    assert results["secondary_comparisons"] == ["plain", "careful"]
    assert rule["headline"] == harness.HEADLINE_IF_CLOSE
    md = harness.markdown(results)
    assert "| Unbluffable | 4/4 |" in md and "Exact McNemar" in md
    assert not any(word in md.lower() for word in BANNED)


def test_unbluffable_arm_reports_an_error_when_the_model_fails():
    from voice.recording import VoiceError

    class Failing:
        async def structured(self, *args):
            raise VoiceError("down")

    assert asyncio.run(harness.unbluffable_verdict(Failing(), ITEMS[0])) == "error"
    assert asyncio.run(harness.chatbot_verdict(Failing(), "plain", "p", ITEMS[0])) == "error"


# --- Record, then replay without a key ------------------------------------------------

def test_live_calls_are_recorded_and_replay_needs_no_key(tmp_path, monkeypatch):
    from voice.provider import MetaVoice

    seen = []

    def handler(request):
        body = json.loads(request.content)
        assert request.url.host == "api.meta.ai" and body["model"] == "muse-spark-1.3"
        name = body["response_format"]["json_schema"]["name"]
        text = body["messages"][1]["content"]
        seen.append(name)
        if name.startswith("evidence_"):
            content = {"verdict": "understands" if "1/11" not in text else "does_not_understand"}
        else:
            content = extraction(name, text)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": json.dumps(content)}}]})

    monkeypatch.setenv("LLM_BACKEND", "meta_api")
    monkeypatch.setenv("MODEL_API_KEY", "dummy-test-key")
    live = MetaVoice("live", str(tmp_path), transport=httpx.MockTransport(handler))
    recorded = asyncio.run(harness.evaluate(ITEMS, live, runs=1))
    assert seen and set(seen) >= {"evidence_plain", "evidence_careful", "evidence_careful_answers", "minimal", "extraction"}
    files = list(tmp_path.glob("*.json"))
    assert files and not any("dummy-test-key" in f.read_text(encoding="utf-8") for f in files)

    monkeypatch.delenv("MODEL_API_KEY")
    replayed = asyncio.run(harness.evaluate(ITEMS, MetaVoice("replay", str(tmp_path)), runs=1))
    assert replayed == recorded
    assert recorded["unbluffable"][0]["recited"] == "does_not_understand"
