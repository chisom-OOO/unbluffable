"""Consulting full cases (decision log 30): prompt, clarifying questions (a fact only when asked),
the structure against the key buckets (one probe for gaps), then the stages in order: exhibit
calculations exact with common mistakes named, insight and brainstorm model-judged, the
recommendation and the follow-up twist. Fake model; the real case content."""

import asyncio
import random
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app import cases, interview_routes, voice_routes
from app.main import app

CC01 = next(c for c in cases.load() if c["id"] == "CC01")


class Spark:
    """case_facts: the facts whose topic word appears in the question. case_quotes: quotes the
    answer's first sentence for point 1 and invents one for point 2 (code must drop it)."""

    mode = "live"

    async def structured(self, text, kind, effort, schema, prompt):
        if kind == "case_facts":
            question = text.split("<answer>\n", 1)[1].split("\n</answer>")[0].lower()
            listed = [line.split(". ", 1)[1].lower() for line in text.split("\n\n")[0].splitlines()[1:]]
            return {"facts": [i + 1 for i, topic in enumerate(listed) if topic.split()[0] in question]}, {"model": "fake", "job": kind}
        answer = text.split("<answer>\n", 1)[1].split("\n</answer>")[0]
        return {"points": [{"point": 1, "quote": answer.split(".")[0]}, {"point": 2, "quote": "never said this"}]}, {"model": "fake"}


def play(script, case=CC01):
    events, queue = [], list(script)

    async def send(e):
        events.append(e)

    async def listen():
        assert queue, f"the case wanted more after: {[e for e in events if e['type'] == 'interviewer_line'][-1]['text']}"
        return queue.pop(0)

    session = cases.CaseSession(send, listen, Spark(), rng=random.Random(1), case=case)
    asyncio.run(session.run())
    assert not queue, queue
    return session, events


def lines(events, kind=None):
    return [e["text"] for e in events if e["type"] == "interviewer_line" and (kind is None or e["kind"] == kind)]


STRUCTURE = ("I would split profit into revenue and costs. Revenue is price, volume and mix. Costs are variable per meal "
             "and fixed. Then I would check implementation risks like supplier reliability and food safety before acting.")


def answers_for(case, wrong_first=False):
    out = []
    for s in case["stages"]:
        if s["type"] == "exhibit_calculation":
            if wrong_first and s.get("common_mistakes"):
                out += [f"I get {s['common_mistakes'][0]['wrong_answer']}.", f"Let me redo it: the answer is {s['answer']}."]
                wrong_first = False
            else:
                out.append(f"The answer is {s['answer']}.")
        elif s["type"] == "brainstorm":
            out += ["Renegotiate ingredients. Cut waste.", "I would test the supplier first."]
        else:
            out.append("Variable costs explain the drop. Premium loses more per meal.")
    return out


def test_the_content_loads_fifteen_cases_with_exact_exhibits():
    assert len(cases.load()) == 15
    exhibits = [s for c in cases.load() for s in c["stages"] if s["type"] == "exhibit_calculation"]
    assert len(exhibits) == 30 and all("columns" in s["exhibit"] and "rows" in s["exhibit"] for s in exhibits)
    assert {k: len(cases.load(k)) for k in cases.CASE_TYPES}["Market entry"] == 3


@pytest.mark.parametrize("said, value", [("minus eight", -8), ("It drops by 8.", -8), ("a loss of 240", -240), ("39/20", Fraction(39, 20)),
                                         ("one point nine five", Fraction(39, 20)), ("I get 2,700.", 2700), ("sixty thousand", 60000),
                                         ("-10", -10), ("It is 200 thousand dollars, so 200.", 200)])
def test_case_numbers_are_read_exactly_with_their_sign(said, value):
    assert cases.numbers(said)[-1] == Fraction(value)


def test_a_full_case_end_to_end():
    script = ["What is the objective?", "What happened to prices?", STRUCTURE, "Nothing else."] + answers_for(CC01) + [
        "Pursue a controlled rollout after validating safety. Track savings by product.",
        "Reject this supplier offer. Seek a compliant ingredient instead."]
    session, events = play(script)
    clarify = lines(events, "clarify")
    assert clarify[0] == CC01["clarifying_facts"][0]["answer"]  # only the asked fact
    assert clarify[1] == cases.NO_FACT or "Prices and meal volumes" in clarify[1]
    assert lines(events, "probe")[0] == cases.STRUCTURE_PROBE  # a bucket was missing
    tables = [e for e in events if e["type"] == "case_stage" and e["kind"] == "exhibit_calculation"]
    assert tables[0]["exhibit"]["columns"][0] == "Product" and tables[0]["exhibit"]["rows"][0][0] == "Standard"
    report = cases.report(session)
    c = report["case"]
    assert c["structure"]["buckets"][0]["quote"] == "I would split profit into revenue and costs"
    assert c["structure"]["buckets"][1]["quote"] is None  # the invented quote was dropped
    calcs = [s for s in c["stages"] if s["kind"] == "exhibit_calculation"]
    assert all(s["first"]["correct"] and s["label"] == "exact" for s in calcs)
    judged = [s for s in c["stages"] if s["kind"] != "exhibit_calculation"]
    assert all(s["label"] == "model-judged, not exact" for s in judged)
    assert c["recommendation"]["key_points"][0]["quote"] == "Pursue a controlled rollout after validating safety"
    assert c["twist"]["points"][0]["quote"] == "Reject this supplier offer"
    assert [i["outcome"] for i in report["rating_items"]] == ["correct", "correct"] and report["label"] is None
    assert report["rating_items"][0]["area"] == "Profitability"


def test_a_common_mistake_is_named_and_one_challenge_follows():
    script = ["Let's go.", STRUCTURE + " That's all.", "Nothing else."] + answers_for(CC01, wrong_first=True) + ["Roll out carefully.", "Reject it."]
    session, events = play(["What is the objective?"] + script[1:])
    first = next(s for s in cases.report(session)["case"]["stages"] if s["kind"] == "exhibit_calculation")
    assert first["first"] == {"said": "225", "exact": "200", "correct": False,
                              "mistake": "Applies the unweighted average unit-cost increase to all meals."}
    assert first["after_challenge"]["correct"] is True and cases.CHALLENGE in lines(events, "challenge")
    item = cases.report(session)["rating_items"][0]
    assert item["outcome"] == "correct" and item["weight"] == "2/3"  # right only after the challenge


def test_full_case_chips_and_the_route(monkeypatch):
    from test_bank_runtime import _packed_bank
    monkeypatch.setattr(interview_routes, "_BANK", _packed_bank(("a", None, "Probability"), ("c", "consulting", "Profitability")))
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    monkeypatch.setattr(voice_routes, "provider", lambda: Spark())
    client = TestClient(app)
    consulting = next(t for t in client.get("/api/interview/topics").json()["tracks"] if t["id"] == "consulting")
    strategy = next(r for r in consulting["roles"] if r["id"] == "strategy")
    names = [c["name"] for c in strategy["chips"]]
    assert "Full case" in names and "Market entry case" in names and "Segmentation case" in names
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "consulting", "role": "strategy", "topics": ["Pricing case"],
                          "typed_practice": True})
        first = socket.receive_json()
        while first["type"] not in {"question", "error"}:
            first = socket.receive_json()
        assert first["type"] == "question" and first["kind"] == "case"  # the "Pricing case" chip runs a pricing case
    monkeypatch.setenv("CASES", "0")
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    consulting = next(t for t in client.get("/api/interview/topics").json()["tracks"] if t["id"] == "consulting")
    assert "Full case" not in [c["name"] for r in consulting["roles"] for c in r["chips"]]
