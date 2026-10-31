"""Coding rounds (decision log 26), with a verified fixture spec and a fake model: exact
judging of the outputs the browser sends, named wrong methods, the question guard, and the
round over the socket end to end. No code runs on the server."""

import json
from fractions import Fraction
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import coding, interview_routes, voice_routes
from app.main import app
from test_bank_runtime import _packed_bank

FIXTURE = Path(__file__).parent / "fixtures" / "coding"
SPEC = json.loads((FIXTURE / "sw_F001.json").read_text(encoding="utf-8"))


def out(values):
    return [{"ok": True, "value": str(v)} for v in values]


def test_the_page_gets_test_inputs_but_never_the_stored_answers():
    pub = coding.public(SPEC)
    assert pub["signature"] == "def max_consecutive_gain(gains: list[int]) -> int:"
    assert len(pub["tests"]) == len(SPEC["tests"]) and "expected" not in pub and "wrong_methods" not in pub
    assert [e["expected"] for e in pub["examples"]] == [SPEC["expected"][i] for i in SPEC["examples"]]
    assert "solver_source" not in json.dumps(pub)


def test_exact_judging_and_named_wrong_methods():
    right = coding.judge(SPEC, out(SPEC["expected"]))
    assert (right["passed"], right["total"], right["named"], coding.outcome(right)) == (50, 50, None, "correct")
    wrong = SPEC["wrong_methods"][0]
    named = coding.judge(SPEC, out(wrong["outputs"]))
    assert named["named"] == "ignores contiguity" and coding.outcome(named) == "named_wrong" and named["passed"] < 50
    off = [str(Fraction(x) + 1) for x in SPEC["expected"]]
    other = coding.judge(SPEC, out(off))
    assert (other["passed"], other["named"], coding.outcome(other)) == (0, None, "other_wrong")
    # Exact: 19.0 equals 19; 19.5, True, text, errors and timeouts never do.
    mixed = out(SPEC["expected"])
    mixed[0] = {"ok": True, "value": f"{SPEC['expected'][0]}.0"}
    mixed[1] = {"ok": True, "value": "True"}
    mixed[2] = {"ok": False, "error": "IndexError: list index out of range"}
    mixed[3] = {"ok": False, "timeout": True}
    judged = coding.judge(SPEC, mixed)
    assert judged["passed"] == 47 and judged["failing"] == [1, 2, 3] and judged["errors"] == 2 and judged["timed_out"]
    assert coding.judge(SPEC, out(SPEC["expected"][:10]))["passed"] == 0  # the wrong number of outputs counts as nothing
    row = coding.receipt(SPEC, named, "Muse Spark Open")["rows"][-1]
    assert row["text"] == "Your outputs match a wrong method Muse Spark Open wrote and code verified: ignores contiguity."


@pytest.mark.parametrize("question, kept", [
    ("What does cur hold after each step?", True),
    ("Try `return max(cur, best)` instead?", False),
    ("Could you use for x in gains here?", False),
    ("Is the answer for the third test 23?", False),  # a stored answer that isn't a visible example
    ("What does your loop do", False),  # not a question
])
def test_questions_about_the_code_never_give_the_solution(question, kept):
    hidden = next(a for i, a in enumerate(SPEC["expected"]) if i not in SPEC["examples"] and a not in
                  {SPEC["expected"][j] for j in SPEC["examples"]})
    question = question.replace("23", hidden)
    assert (coding.safe_question(question, SPEC) == question) is kept


class FakeSpark:
    mode = "live"

    def __init__(self):
        self.calls = []

    async def structured(self, text, kind, effort, schema, prompt):
        self.calls.append(kind)
        if kind == "coding_plan":
            return {"plan_quotes": ["I keep a running sum and reset it when it drops below the next value", "made up"],
                    "complexity_claim": "one pass, so O(n)"}, {"model": "fake"}
        if kind == "coding_question":
            n = sum(1 for k in self.calls if k == "coding_question")
            return {"question": "What does cur hold after each step?" if n % 2 else "Why start best at the first gain?"}, {"model": "fake"}
        if kind == "coding_follow_up":
            return {"question": "What happens if every gain is negative?", "focus": "edge_case"}, {"model": "fake"}
        if kind == "coding_judge":
            return {"verdict": "yes", "quote": "it returns the largest single value"}, {"model": "fake"}
        raise AssertionError(kind)


@pytest.fixture
def coding_routes(monkeypatch):
    monkeypatch.setenv("CODING_DIR", str(FIXTURE))
    coding._load.cache_clear()
    monkeypatch.setattr(interview_routes, "_BANK", _packed_bank(("a", None, "Probability"), ("s", "software", "Dynamic programming")))
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    spark = FakeSpark()
    monkeypatch.setattr(voice_routes, "provider", lambda: spark)
    yield spark
    coding._load.cache_clear()


def test_only_the_software_track_offers_a_coding_round_once_specs_exist(coding_routes, monkeypatch):
    formats = {t["id"]: t["formats"] for t in TestClient(app).get("/api/interview/topics").json()["tracks"]}
    assert formats["software"] == ["spoken", "coding"] and formats["quant"] == ["spoken"]
    monkeypatch.setenv("CODING_DIR", str(FIXTURE / "nothing"))
    coding._load.cache_clear()
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    formats = {t["id"]: t["formats"] for t in TestClient(app).get("/api/interview/topics").json()["tracks"]}
    assert formats["software"] == ["spoken"]  # no verified specs: no coding round


def drain(socket, until):
    seen = []
    while True:
        event = socket.receive_json()
        seen.append(event)
        if event["type"] in until:
            return seen


def test_a_coding_round_end_to_end(coding_routes):
    client = TestClient(app)
    wrong = SPEC["wrong_methods"][0]["outputs"]
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "software", "format": "coding"})
        seen = drain(socket, {"state"})
        session_id = seen[0]["id"]
        question = next(e for e in seen if e["type"] == "question")
        assert question["kind"] == "coding" and question["coding"]["signature"].startswith("def max_consecutive_gain(")
        assert "expected" not in question["coding"]
        # The approach first: its plan quotes are kept only word for word.
        socket.send_json({"type": "typed", "transcript": "I keep a running sum and reset it when it drops below the next value. It is one pass, so O(n)."})
        seen = drain(socket, {"state"})
        plan = next(e for e in seen if e["type"] == "coding_plan")
        assert plan["plan_quotes"] == ["I keep a running sum and reset it when it drops below the next value"]
        assert plan["complexity_claim"] == "one pass, so O(n)" and any(e["type"] == "coding_open" for e in seen)
        # Speech while coding stays live; at most two questions about the code.
        socket.send_json({"type": "typed", "transcript": "Now I loop over the gains."})
        seen = drain(socket, {"state"})
        assert {"type": "coding_speech", "text": "Now I loop over the gains."} in seen
        probes = 0
        for trigger in ("code_run", "code_pause", "code_run"):
            socket.send_json({"type": trigger, "code": "def max_consecutive_gain(gains):\n    return sum(gains)\n"})
            seen = drain(socket, {"state"})
            probes += sum(1 for e in seen if e.get("kind") == "probe")
        assert probes == 2
        # A failing submit: named in the receipt, then one Socratic challenge.
        socket.send_json({"type": "code_submit", "code": "def max_consecutive_gain(gains): ...", "outputs": out(wrong)})
        seen = drain(socket, {"state"})
        result = next(e for e in seen if e["type"] == "coding_result")
        assert result["passed"] < 50 and result["receipt"]["rows"][-1]["key"] == "forge_method"
        challenge = next(e for e in seen if e.get("kind") == "challenge")
        assert "Walk me through" in challenge["text"] and "ignores contiguity" not in challenge["text"]
        assert not any(a in challenge["text"].split("max_consecutive_gain(")[0] for a in SPEC["expected"] if len(a) > 1)
        # Right on the second submit, then the follow-up, judged by the model.
        socket.send_json({"type": "code_submit", "code": "def max_consecutive_gain(gains): ...", "outputs": out(SPEC["expected"])})
        seen = drain(socket, {"state"})
        follow = next(e for e in seen if e.get("kind") == "follow_up")
        assert follow["text"] == "What happens if every gain is negative?"
        socket.send_json({"type": "typed", "transcript": "Then it returns the largest single value, which is still right."})
        seen = drain(socket, {"session_end"})
        assert seen[-1] == {"type": "session_end", "label": None, "coding": True, "timed_out": False}
    report = client.get(f"/api/interview/{session_id}/report").json()
    c = report["coding"]
    assert c["outcome"] == "correct" and c["weight"] == "2/3" and c["tests"] == {"passed": 50, "total": 50}  # recovered: 2/(2+0+1)
    assert [s["named"] for s in c["submits"]] == ["ignores contiguity", None]
    assert c["complexity_claim"] == "one pass, so O(n)" and c["follow_up"]["verdict"] == "yes"
    assert c["provenance"]["solver_source"].startswith("def solve(") and c["provenance"]["wrong_methods"] == ["ignores contiguity"]
    item, = report["rating_items"]
    from app.areas import CAPS
    assert (item["area"], item["outcome"], item["value"]) == ("Dynamic programming", "correct", str(Fraction(2, 3) * CAPS[SPEC["difficulty"]]))
    assert report["label"] is None and report["track"] == "software"


def test_a_software_familys_provenance_shows_its_solver_code_once_exported(coding_routes):
    from app import provenance
    from engine.bank import parse_template
    from test_bank_runtime import _raw_bag
    t = parse_template(_raw_bag(template_id="sw_F001", pack="software", topic="Dynamic programming"))
    p = provenance.provenance(t)
    assert p["solver_source_stored"] and p["solver_source"].startswith("def solve(")
    assert provenance.rows(p)[-1] == {"key": "solver_code", "label": "Solver code", "text": p["solver_source"]}
    other = provenance.provenance(parse_template(_raw_bag(template_id="bag")))
    assert not other["solver_source_stored"] and provenance.rows(other)[-1]["key"] == "source"
