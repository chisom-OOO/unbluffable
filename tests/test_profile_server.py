"""Decision log 23, server side: strength areas, answer values for the rating, placement,
and /api/interest. Fake model only."""

import asyncio
import json
import logging
import random
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app import interview_report, interview_routes, voice_routes
from app.areas import AREAS, CAPS, area_for, answer_value
from app.interview_session import ExamSession, VoiceAnalyzer
from app.main import app
from app.placement import PlacementInterview, PlacementSource
from engine.bank import Bank, BankSource, load_bank, parse_template
from test_bank_runtime import ScriptedProvider, _raw_bag


# --- Answer values: the engine's weight x the difficulty cap ---------------------------

@pytest.mark.parametrize("scored, weight, difficulty, value", [
    ("correct", Fraction(1), "Medium", Fraction(17, 20)),      # right, no help: 0.85
    ("correct", Fraction(1), "Easy", Fraction(3, 5)),          # 0.6
    ("correct", Fraction(1), "Hard", Fraction(1)),
    ("correct", Fraction(2, 4), "Easy", Fraction(3, 10)),      # recovered after the challenge, H = 1
    ("correct", Fraction(2, 3), "Hard", Fraction(2, 3)),       # one hint, H = 1
    ("correct", Fraction(2, 5), "Medium", Fraction(17, 50)),   # recovered, H = 2
    ("named_wrong", Fraction(1), "Hard", Fraction(0)),
    ("other_wrong", Fraction(1), "Easy", Fraction(0)),
    ("vague", Fraction(1), "Medium", Fraction(0)),
])
def test_answer_value_is_weight_times_the_difficulty_cap(scored, weight, difficulty, value):
    assert answer_value(scored, weight, difficulty) == value


def test_caps_are_pinned():
    assert CAPS == {"Easy": Fraction(3, 5), "Medium": Fraction(17, 20), "Hard": Fraction(1)}


# --- Strength areas -----------------------------------------------------------------

def test_every_topic_in_content_forge_has_an_area():
    """Every family file, including coding-only (list-answer) families the spoken bank never loads."""
    import json
    from pathlib import Path
    files = sorted((Path(__file__).resolve().parents[1] / "content" / "forge").glob("*.json"))
    assert files, "content/forge is empty"
    missing = set()
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        pack = raw.get("pack", "quant")
        for topic in [raw.get("topic")] + list(raw.get("topics") or []):
            if topic and area_for(pack, topic) is None:
                missing.add((pack, topic, path.stem))
    assert sorted(missing) == []
    assert load_bank().templates


def test_areas_are_the_listed_axes_at_most_eight_per_track():
    # Decision log 28 adds Market making to quant, and the swf_ Fundamentals to software, as a ninth area.
    assert all(1 <= len(areas) <= (9 if track in {"quant", "software"} else 8) for track, areas in AREAS.items())
    assert list(AREAS["quant"]) == [
        "Probability", "Expectations", "Combinatorics", "Statistics", "Stochastic processes",
        "Linear algebra & calculus", "Optimisation, decisions & pricing maths",
        "Number theory, sequences, geometry & arithmetic", "Market making"]
    assert list(AREAS["ib"]) == ["Accounting", "DCF", "LBO", "Valuation multiples", "WACC",
                                 "M&A & accretion/dilution", "EV bridge & share count"]
    assert list(AREAS["consulting"]) == ["Profitability", "Operations", "Mix & weighted averages", "Breakeven",
                                         "Market sizing", "Growth & investment", "Pricing & unit economics"]
    assert list(AREAS["software"]) == [
        "Dynamic programming", "Graphs & union-find", "Sliding window, two pointers & prefix sums", "Binary search",
        "Heaps & greedy", "Intervals & monotonic stack", "Bit manipulation", "Backtracking & tries", "Fundamentals"]
    assert area_for("software", "Hash maps and sets") == area_for("software", "Trees and binary search trees") == "Fundamentals"
    assert area_for("quant_dev", "Exact probability by code") == "Coding" and area_for("quant_dev", "Unlisted topic") is None
    assert area_for("quant", "Conditional probability") == area_for("quant", "Bayesian statistics") == "Probability"
    assert area_for("ib", "Probability") is None  # areas are per track


def test_topics_api_lists_each_tracks_areas_and_hard():
    data = TestClient(app).get("/api/interview/topics").json()
    # Quant development is a Quant role, not a track (setup redesign).
    assert {t["id"]: t["areas"] for t in data["tracks"]} == {k: list(v) for k, v in AREAS.items() if k != "quant_dev"}
    assert data["levels"] == ["Easy", "Medium", "Hard"] and data["default_level"] == "Easy"


# --- Placement: five questions, five areas, from Medium -------------------------------

PLACEMENT_TOPICS = ("Discrete probability", "Conditional probability", "Expectations", "Combinatorics",
                    "Statistics", "Stochastic processes", "Calculus")


def placement_bank():
    templates = [parse_template(_raw_bag(template_id=f"t{i}_{level}", topic=topic, difficulty=level))
                 for i, topic in enumerate(PLACEMENT_TOPICS) for level in ("Easy", "Medium", "Hard")]
    return Bank({t.template_id: t for t in templates})


def run_placement(answer_right):
    events = []

    async def send(event):
        events.append(event)

    async def listen():
        q = session.questions[-1]
        r = q.puzzle.params["red"]
        right = answer_right(len(session.questions))
        return f"My answer is {r if right else 11}/{r + 11}, because {'red' if right else 'blue'} over all balls."

    source = PlacementSource(placement_bank(), "quant", rng=random.Random(3))
    session = ExamSession(send, listen, VoiceAnalyzer(ScriptedProvider()),
                          PlacementInterview(rng=random.Random(4), source=source))
    session.track, session.placement = "quant", True
    asyncio.run(session.run())
    return session, events


def test_placement_asks_five_questions_from_five_areas_starting_at_medium():
    session, events = run_placement(lambda n: True)
    qs = session.questions
    assert len(qs) == 5 and all(q.kind == "new" for q in qs)
    areas = [area_for("quant", q.puzzle.topic) for q in qs]
    assert len(set(areas)) == 5  # Discrete and Conditional probability share one area
    assert qs[0].puzzle.difficulty == "Medium"
    assert qs[1].puzzle.difficulty == "Hard"  # the normal ladder: up after a right answer
    report = interview_report.build(session)
    assert report["placement"] is True and report["track"] == "quant"
    assert [i["area"] for i in report["rating_items"]] == areas
    assert all(i["value"] == str(answer_value("correct", 1, q.puzzle.difficulty))
               for i, q in zip(report["rating_items"], qs))


def test_placement_ladder_goes_down_and_wrong_answers_count_zero():
    session, _ = run_placement(lambda n: n != 1)  # the first answer stays wrong
    qs = session.questions
    assert len(qs) == 5 and qs[0].scored == "named_wrong" and qs[1].puzzle.difficulty == "Easy"
    assert interview_report.build(session)["rating_items"][0]["value"] == "0"


def test_placement_over_the_socket(monkeypatch):
    monkeypatch.setattr(interview_routes, "_BANK", placement_bank())
    monkeypatch.setattr(voice_routes, "provider", lambda: ScriptedProvider())
    with TestClient(app).websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "placement": True, "pack": "quant"})
        while (event := socket.receive_json())["type"] != "question":
            if event["type"] == "session":
                session_id = event["id"]
        assert event["difficulty"] == "Medium"
        socket.send_json({"type": "end"})
    session = interview_routes.SESSIONS[session_id]
    assert session.placement and session.track == "quant" and isinstance(session.interview, PlacementInterview)


def test_reports_carry_rating_items_for_originals_and_twins(monkeypatch):
    monkeypatch.setattr(interview_routes, "_BANK", placement_bank())
    interview = interview_routes.interview_for("quant", ["Statistics"], "Hard")
    assert isinstance(interview.source, BankSource) and interview.source.difficulty == "Hard"  # 70+ starts at Hard


# --- /api/interest: one log line, nothing stored ---------------------------------------

def test_interest_logs_roles_and_note_only(caplog):
    client = TestClient(app)
    with caplog.at_level(logging.INFO, logger="unbluffable.interest"):
        response = client.post("/api/interest", json={"roles": ["quant", "other"], "other_text": "Actuarial\n exams"},
                               headers={"X-Forwarded-For": "203.0.113.9"})
    assert response.status_code == 204
    records = [r for r in caplog.records if r.name == "unbluffable.interest"]
    assert len(records) == 1
    assert json.loads(records[0].getMessage()) == {"event": "interest", "roles": ["quant", "other"],
                                                   "other_text": "Actuarial exams"}
    assert "203.0.113.9" not in records[0].getMessage() and "testclient" not in records[0].getMessage()


@pytest.mark.parametrize("body", [{"roles": ["astronaut"]}, {"roles": ["quant", "quant"]},
                                  {"roles": ["quant"], "email": "a@b.c"}, {"roles": ["quant"], "other_text": "x" * 201}])
def test_interest_rejects_anything_else(body, caplog):
    with caplog.at_level(logging.INFO, logger="unbluffable.interest"):
        assert TestClient(app).post("/api/interest", json=body).status_code == 422
    assert not [r for r in caplog.records if r.name == "unbluffable.interest"]


def test_interest_rules_allow_only_a_create_with_the_three_fields_and_known_roles():
    """firestore.rules for "interest": create only, exactly roles / other_text / created_at, the
    same roles as the log line and the role presets; no client read, update or delete."""
    import re
    from pathlib import Path

    from app.interest import ROLES
    root = Path(__file__).resolve().parents[1]
    rules = (root / "firestore.rules").read_text(encoding="utf-8")
    block = rules[rules.index("match /interest/{id}"):rules.index("match /{document=**}")]
    assert "hasOnly(['roles', 'other_text', 'created_at'])" in block and "hasAll(['roles', 'other_text', 'created_at'])" in block
    assert "other_text.size() <= 200" in block and "created_at == request.time" in block
    assert "allow read, update, delete: if false;" in block and "request.auth" not in block  # guests too
    listed = re.search(r"roles\.hasOnly\(\[([^\]]*)\]\)", block)[1]
    assert [r.strip(" '") for r in listed.split(",")] == list(ROLES)
    core = (root / "app" / "static" / "ui" / "account-core.js").read_text(encoding="utf-8")
    assert re.search(r"INTEREST_ROLES = \[([^\]]*)\]", core)[1].replace('"', "").split(", ") == list(ROLES)
