"""Conversational questions (decision log 30): IB "Conversational" and Software "Design concepts".
Question, one probe, then the twist; key points and misconceptions quoted word for word
(model-judged); a capacity check, when present, checked exactly. Fake model; real content."""

import asyncio
import random

from fastapi.testclient import TestClient

from app import conversational as conv
from app import interview_routes, voice_routes
from app.main import app
from test_bank_runtime import _packed_bank

SW = {r.id: r for r in conv.load("software")}
IB = {r.id: r for r in conv.load("ib")}


class Spark:
    """Quotes the answer's first sentence for key point 1; says misconception 1 when the
    answer says "always"; invents a quote for point 2 (which code must drop)."""

    mode = "live"

    def __init__(self):
        self.calls = 0

    async def structured(self, text, kind, effort, schema, prompt):
        assert kind == "conversational"
        self.calls += 1
        answer = text.split("<answer>\n", 1)[1].split("\n</answer>")[0]
        first = answer.split(".")[0]
        out = {"points": [{"point": 1, "quote": first}, {"point": 2, "quote": "words the candidate never said"}],
               "misconceptions": []}
        if "always" in answer:
            out["misconceptions"].append({"misconception": 1, "quote": answer[answer.index("always"):].split(".")[0]})
        return out, {"model": "fake", "job": kind}


def run(rows, script, track="software"):
    events, queue = [], list(script)

    async def send(e):
        events.append(e)

    async def listen():
        return queue.pop(0)

    session = conv.ConversationalSession(send, listen, Spark(), track, rng=random.Random(1), rows=rows, count=len(rows))
    asyncio.run(session.run())
    assert not queue, queue
    return session, events


def lines(events, kind=None):
    return [e["text"] for e in events if e["type"] == "interviewer_line" and (kind is None or e["kind"] == kind)]


def test_the_content_loads_with_capacity_checks_on_twelve_design_questions():
    assert len(IB) == 40 and len(SW) == 30
    assert sum(1 for r in SW.values() if r.capacity) == 12 and not any(r.capacity for r in IB.values())
    assert all(r.key_points and r.twist_points and r.probes for r in list(IB.values()) + list(SW.values()))


def test_question_probe_twist_and_an_exact_capacity_check():
    row = SW["SDC01"]  # 1 + 1 queries per page at 200 page loads per second: 400
    session, events = run([row], ["Trace the calls first. Running them in parallel always helps.",
                                  "I would look for one query per item.",
                                  "I would reuse the result of the repeated lookup.",
                                  "That leaves four hundred queries per second."])
    asked = lines(events, "question")
    assert asked[0] == row.question and asked[1] == f"{conv.TWIST_INTRO} {row.twist}"
    assert asked[2].startswith(conv.CAPACITY_INTRO) and row.capacity["question"] in asked[2]
    assert lines(events, "probe")[0] in row.probes
    item, = conv.report(session)["conversational"]
    assert item["key_points"][0]["quote"] == "Trace the calls first" and item["key_points"][1]["quote"] is None  # invented quote dropped
    assert item["misconceptions"] == [{"misconception": row.misconceptions[0], "quote": "always helps"}]
    assert item["twist_points"][0]["quote"] == "I would reuse the result of the repeated lookup"
    assert item["capacity"]["correct"] is True and item["capacity"]["said"] == "400" and item["capacity"]["exact"] == "400"
    assert item["dropped_quotes"] == 3
    report = conv.report(session)
    assert report["label"] is None and report["rating_items"] == [] and report["topics"] == "Design concepts"


def test_a_wrong_capacity_number_is_marked_wrong_exactly():
    session, _ = run([SW["SDC01"]], ["a", "b", "c", "About four hundred and fifty, I think 450."])
    assert conv.report(session)["conversational"][0]["capacity"]["correct"] is False


def test_the_probe_aims_at_the_first_key_point_not_covered():
    row = IB["IBC01"]
    assert conv.choose_probe(row, set()) in row.probes
    assert conv.choose_probe(row, {0}) in row.probes


def test_spoken_answers_end_on_their_own_except_the_capacity_number():
    session = conv.ConversationalSession(None, None, None, "software", rows=[SW["SDC01"]], count=1)
    assert session.turn_policy() is not None
    session.stage = "capacity"
    assert session.turn_policy() is None


def test_conversational_is_its_own_topic_in_ib_and_design_concepts_in_software(monkeypatch):
    monkeypatch.setattr(interview_routes, "_BANK", _packed_bank(("a", None, "Probability"), ("v", "ib", "Valuation"),
                                                                ("s", "software", "Dynamic programming")))
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    monkeypatch.setattr(voice_routes, "provider", lambda: Spark())
    client = TestClient(app)
    tracks = {t["id"]: [o["id"] for o in t["topics"]] for t in client.get("/api/interview/topics").json()["tracks"]}
    assert "Conversational" in tracks["ib"] and "Design concepts" in tracks["software"]
    assert interview_routes.selection("ib", ["Conversational"])[1] == "Conversational"
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "ib", "topics": ["Conversational"], "typed_practice": True})
        while True:
            e = socket.receive_json()
            if e["type"] == "session":
                sid = e["id"]
            if e["type"] == "state" and e["value"] == "listening":
                socket.send_json({"type": "typed", "transcript": "Start with cash flow visibility. Then compare the costs."})
            if e["type"] == "session_end":
                assert e["conversational"] is True
                break
    report = client.get(f"/api/interview/{sid}/report").json()
    assert len(report["conversational"]) == 2 and report["topics"] == "Conversational"
    monkeypatch.setenv("CONVERSATIONAL", "0")
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    tracks = {t["id"]: [o["id"] for o in t["topics"]] for t in client.get("/api/interview/topics").json()["tracks"]}
    assert "Conversational" not in tracks["ib"]


def test_software_offers_one_design_question_after_the_coding_round_only_if_time_remains(monkeypatch, tmp_path):
    from app import coding
    from test_coding_parts import FAST, RIGHT, SAY, SPEC, Clock, Spark as CodingSpark, interview  # noqa: F401

    def session_with_design(minutes):
        clock, events = Clock(), []
        script = [SAY, RIGHT, SAY] + [{"type": "speech", "text": t} for t in
                                      ("Trace the calls first.", "Per item queries.", "Reuse the lookup.", "Four hundred.")]

        async def send(e):
            events.append(e)

        async def step():
            clock.t += minutes * 60
            return script.pop(0)

        async def listen():
            return (await step())["text"]

        monkeypatch.setenv("CODING_SCALE_DIR", str(tmp_path / "none"))
        monkeypatch.setenv("CODING_TWIST_DIR", str(tmp_path / "none"))
        coding._load_dir.cache_clear()
        s = coding.CodingSession(send, listen, step, CodingSpark(), SPEC, deadline=coding.INTERVIEW_SECONDS, clock=clock)
        s.design = conv.ConversationalSession(send, listen, Spark(), "software", rows=[SW["SDC01"]], count=1, clock=clock)
        s.design.ends_session = False
        asyncio.run(s.run())
        return s, events, script

    s, events, left = session_with_design(1)
    assert not left and lines(events, "prompt")[-1] == conv.SEGMENT_OPENING
    assert [e["type"] for e in events].count("session_end") == 1
    assert coding.report(s)["design"][0]["capacity"]["correct"] is True
    s, events, left = session_with_design(13)  # 39 minutes used: under 8 left, no design question
    assert len(left) == 4 and coding.report(s)["design"] == []
