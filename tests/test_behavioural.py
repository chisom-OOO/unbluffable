"""Behavioural questions (decision log 24) with a fake model: quotes kept only when word
for word, code-checked specificity, the probe aimed at the weakest step, contradictions
with both quotes, and the report. No network."""

import asyncio
import random
import re

import pytest
from fastapi.testclient import TestClient

from app import behavioural as b
from app import interview_routes, voice_routes
from app.main import app
from test_bank_runtime import ScriptedProvider, _packed_bank
from voice.recording import VoiceError

FIRST = ("Last spring our team had two days to rebuild a pitch book after the client changed the target. "
         "I owned the comparables section, so I rebuilt the peer set and checked every multiple against the filings. "
         "We delivered it on time and the client used 6 of our 8 pages.")
PROBE = "On the last night I checked the numbers myself. Actually the client used none of our pages."


class Judge:
    """Fake Spark for behavioural answers: returns `script` for the next call, records prompts."""
    mode = "live"

    def __init__(self, *scripts):
        self.scripts, self.calls = list(scripts), []

    async def structured(self, text, kind, effort, schema, prompt):
        assert kind == "behavioural" and effort == "low" and schema is b.SCHEMA
        self.calls.append((text, prompt))
        script = self.scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        return {"steps": [], "relevant": [], "drift": [], "details": [], "contradictions": [], **script}, {"model": "fake-spark"}


def row(type_="past_behaviour"):
    return next(r for r in b.load() if r.type == type_ and r.track == "ib")


def test_csv_loads_forty_rows_split_by_track():
    rows = b.load()
    assert len(rows) == 40 and all(r.probes and r.signals and r.question for r in rows)
    assert {r.type for r in rows} == {"past_behaviour", "situational"}
    ib, co = b.rows_for("ib"), b.rows_for("consulting")
    assert len(ib) == 25 and len(co) == 25  # "both" rows appear in each
    assert {r.track for r in ib} == {"ib", "both"} and {r.track for r in co} == {"consulting", "both"}
    assert b.rows_for("quant") == [] and b.rows_for("software") == []
    assert all(" | " not in p for r in rows for p in r.probes)


def test_quotes_are_kept_only_word_for_word_and_a_fabricated_one_is_dropped():
    judge = Judge({"steps": [
        {"step": "Situation", "quote": "our team had two days to rebuild a pitch book"},
        {"step": "Task", "quote": "I owned the comparables section"},
        {"step": "Action", "quote": "I rebuilt the peer set and checked every multiple against the filings"},
        {"step": "Result", "quote": "the client was thrilled and promoted me"},  # never said
    ], "relevant": ["I owned the comparables section", "I single-handedly won the mandate"],
        "details": [{"detail": "pages used", "quote": "the client used 6 of our 8 pages"},
                    {"detail": "invented", "quote": "a 40-page deck"}]})
    j = asyncio.run(b.judge(judge, row(), FIRST))
    assert j.steps["Result"] is None and j.steps["Task"] == "I owned the comparables section"
    assert j.relevant == ["I owned the comparables section"]
    assert j.details == [{"detail": "pages used", "quote": "the client used 6 of our 8 pages"}]
    assert j.dropped == 3
    text, prompt = judge.calls[0]
    assert "Situation, Task, Action, Result" in prompt and "<answer>" in text and row().question in text


def test_specificity_is_code_checked_and_the_probe_aims_at_the_weakest_step():
    r = row()
    steps = {"Situation": "our team had two days", "Task": "I owned the comparables section",
             "Action": "we split the work and we checked it together", "Result": "We delivered it on time"}
    spec = b.specificity(r, steps, [])
    assert (spec["outcome_has_number"], spec["action_i"], spec["action_we"], spec["action_owned"]) == (False, 0, 2, False)
    assert b.weakest(r, steps, spec) == "Result"  # every step covered; the result has no number
    probe = b.choose_probe(r, "Result")
    assert probe in r.probes and b._match(probe, "Result") == max(b._match(p, "Result") for p in r.probes)
    steps["Result"] = "the client used 6 of our 8 pages"
    spec = b.specificity(r, steps, [])
    assert spec["outcome_numbers"] == ["6", "8"] and b.weakest(r, steps, spec) == "Action"
    assert b.weakest(r, {**steps, "Task": None}, spec) == "Task"  # a missing step comes first
    assert "Avoid:" in b.tip(r, "Action", spec)  # "we" throughout: the row's own pitfall


def test_a_contradiction_is_flagged_with_both_quotes_and_an_invented_one_is_not():
    judge = Judge({"contradictions": [
        {"first": "the client used 6 of our 8 pages", "probe": "the client used none of our pages"},
        {"first": "we lost the client", "probe": "I checked the numbers myself"}]})
    j = asyncio.run(b.judge(judge, row(), PROBE, earlier=FIRST, probe="What happened next?"))
    assert j.contradictions == [{"first": "the client used 6 of our 8 pages", "probe": "the client used none of our pages"}]
    assert j.dropped == 1
    assert "Earlier answer" in judge.calls[0][0] and "Follow-up asked: What happened next?" in judge.calls[0][0]


def test_a_failed_model_call_keeps_the_session_going():
    j = asyncio.run(b.judge(Judge(VoiceError("down")), row(), FIRST))
    assert j.error and all(q is None for q in j.steps.values())


def run_session(judge, answers, track="ib"):
    events, queue = [], list(answers)

    async def send(event):
        events.append(event)

    async def listen():
        return queue.pop(0)

    session = b.BehaviouralSession(send, listen, judge, track, rng=random.Random(1))
    asyncio.run(session.run())
    return session, events


def test_session_asks_two_questions_each_with_one_probe_then_reports():
    situational_first = "I would call them and also email their deputy the same morning."
    scripts = [
        {"steps": [{"step": "Situation", "quote": "our team had two days to rebuild a pitch book"},
                   {"step": "Action", "quote": "I rebuilt the peer set"}]},
        {"steps": [{"step": "Result", "quote": "the client used none of our pages"}],
         "contradictions": [{"first": "the client used 6 of our 8 pages", "probe": "the client used none of our pages"}]},
        {"steps": [{"step": "Action", "quote": "I would call them and also email their deputy"}]},
        {"steps": [{"step": "Reasoning", "quote": "nothing else can move until they reply"}]},
    ]
    session, events = run_session(Judge(*scripts), [FIRST, PROBE, situational_first,
                                                    "Because nothing else can move until they reply."])
    questions = [e for e in events if e["type"] == "question"]
    assert [(q["kind"], q["behavioural_type"]) for q in questions] == [("behavioural", "past_behaviour"),
                                                                       ("behavioural", "situational")]
    probes = [e for e in events if e["type"] == "interviewer_line" and e["kind"] == "probe"]
    assert len(probes) == 2 and all(p["text"] in session.asked[i].row.probes for i, p in enumerate(probes))
    assert events[-1] == {"type": "session_end", "label": None, "behavioural": True, "timed_out": False}
    assert sum(e["type"] == "behavioural_judged" for e in events) == 4  # one call per answer
    report = b.report(session)
    assert report["label"] is None and report["rating_items"] == [] and report["topics"] == "Behavioural"
    first = report["behavioural"][0]
    assert [s["step"] for s in first["steps"]] == ["Situation", "Task", "Action", "Result"]
    assert first["steps"][1]["quote"] is None  # Task never covered: shown empty
    assert first["steps"][3]["quote"] == "the client used none of our pages"  # from the probe answer
    assert first["weakest"] == "Task" and first["consistency"][0]["first"] == "the client used 6 of our 8 pages"
    assert first["tip"].endswith(".")
    second = report["behavioural"][1]
    assert [s["step"] for s in second["steps"]] == ["Situation", "Action", "Reasoning", "Expected outcome"]


@pytest.fixture
def ib_routes(monkeypatch):
    monkeypatch.setattr(interview_routes, "_BANK", _packed_bank(("a", None, "Probability"), ("v", "ib", "Valuation")))
    judge = Judge(*[{"steps": [{"step": "Situation", "quote": "Last spring"}]}] * 4)
    monkeypatch.setattr(voice_routes, "provider", lambda: judge)
    return judge


def test_behavioural_is_a_topic_in_ib_and_consulting_only(ib_routes):
    data = TestClient(app).get("/api/interview/topics").json()
    topics = {t["id"]: [o["id"] for o in t["topics"]] for t in data["tracks"]}
    assert topics["ib"] == ["Mixed", "Valuation", "Behavioural", "Conversational"]  # decision log 30
    assert topics["consulting"] == ["Behavioural"]  # behavioural questions open the track
    assert "Behavioural" not in topics["quant"] and topics["software"] == []
    assert interview_routes.topic_label("ib", ["Behavioural"]) == "Behavioural"
    assert interview_routes.topic_label("ib", None) == "All topics"  # Mixed stays the forge topics
    # Decision log 37: behavioural questions mix with the technical topics.
    assert interview_routes.selection("ib", ["Behavioural", "Valuation"])[1] == ("Behavioural", "Valuation")


def test_behavioural_over_the_socket(ib_routes):
    client = TestClient(app)
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "consulting", "topics": ["Behavioural"]})
        seen = []
        while True:
            event = socket.receive_json()
            seen.append(event)
            if event["type"] == "session":
                session_id = event["id"]
            if event["type"] == "state" and event["value"] == "listening":
                socket.send_json({"type": "typed", "transcript": "Last spring I led the work and we hit 3 of 4 goals."})
            if event["type"] == "session_end":
                break
    assert [e["kind"] for e in seen if e["type"] == "question"] == ["behavioural", "behavioural"]
    report = client.get(f"/api/interview/{session_id}/report").json()
    assert report["track"] == "consulting" and len(report["behavioural"]) == 2 and report["label"] is None
    assert report["behavioural"][0]["steps"][0] == {"step": "Situation", "quote": "Last spring"}
