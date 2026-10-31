"""Target roles (setup redesign): each role's chips map to topics that exist, chips with no
content are hidden, no chips selected = a role-weighted mix (about 70% Core, 25% Supporting,
5% Specialist), Quantitative Development is a Quant role (not a track), and a role-based start
asks questions from the chosen chips."""

import random
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from app import interview_routes, roles
from app.main import app
from engine.bank import Bank, load_bank, parse_template
from test_bank_runtime import _raw_bag

BANK = load_bank()


@pytest.mark.parametrize("role", [r for r in roles.ROLES if not r.coding], ids=lambda r: r.id)
def test_every_topic_chip_of_a_spoken_role_maps_to_content_that_exists(role):
    live = {t for t, _ in BANK.topics(role.track)}
    for tier, chips in role.tiers():
        for chip in chips:
            if chip.kind == "topic":
                assert any(t in live for t in chip.topics), (role.id, chip.name, chip.topics)


def test_chips_with_no_content_are_hidden_and_special_rounds_need_theirs():
    small = Bank({t.template_id: t for t in (parse_template(_raw_bag(template_id="cp", topic="Conditional probability")),
                                             parse_template(_raw_bag(template_id="st", topic="Statistics")))})
    view = roles.view(small, roles.BY_ID["quant_trading"])
    assert [c["name"] for c in view["chips"]] == ["Conditional probability", "Market making", "Statistics"]
    assert [c["tier"] for c in view["chips"]] == ["core", "core", "supporting"]
    assert view["areas"] == ["Conditional probability", "Market making"]  # the radar follows the Core chips
    full = roles.view(BANK, roles.BY_ID["swe"])
    shown = {c["name"] for c in full["chips"]}
    assert "Arrays & strings" not in shown or any(  # swf_ fundamentals: hidden until merged
        "Arrays" in t for t in roles.live_topics(BANK, roles.BY_ID["swe"]))


def test_no_chips_selected_is_a_role_weighted_mix_of_about_70_25_5():
    role = roles.BY_ID["quant_trading"]
    live = {t for t, _ in BANK.topics("quant")}
    w = roles.weights(role, live)
    tier_of = {t: tier for tier, c in roles.topic_chips(role) for t in c.topics}
    mass = Counter()
    for topic, value in w.items():
        mass[tier_of[topic]] += value
    # Market making (a Core chip) runs on its own, so the topic mix renormalises over the live tiers.
    assert mass["core"] == pytest.approx(0.70 / 1.0, abs=0.001)
    assert mass["supporting"] == pytest.approx(0.25, abs=0.001) and mass["specialist"] == pytest.approx(0.05, abs=0.001)
    # Sampled: new questions follow the weights.
    counts = Counter()
    for seed in range(600):
        source, _ = roles.weighted_source(BANK, role, "Medium", random.Random(seed))
        tid = source.candidates()[0]
        counts[tier_of[BANK.templates[tid].topic]] += 1
    share = {k: v / 600 for k, v in counts.items()}
    assert 0.6 < share["core"] < 0.8 and 0.15 < share["supporting"] < 0.35 and share.get("specialist", 0) < 0.12


def test_chosen_chips_share_equally_and_only_their_topics_are_asked():
    role = roles.BY_ID["quant_research"]
    live = {t for t, _ in BANK.topics("quant")}
    w = roles.weights(role, live, ["Probability", "Calculus"])
    assert set(w) <= {"Discrete probability", "Continuous probability", "Calculus"}
    assert w["Calculus"] == pytest.approx(0.5) and w["Discrete probability"] + w["Continuous probability"] == pytest.approx(0.5)


def test_quant_development_is_a_role_not_a_track():
    data = TestClient(app).get("/api/interview/topics").json()
    assert [t["id"] for t in data["tracks"]] == ["quant", "ib", "consulting", "software"]
    quant = next(t for t in data["tracks"] if t["id"] == "quant")
    assert [r["id"] for r in quant["roles"]] == ["quant_trading", "quant_research", "quant_dev"]
    assert [r["name"] for t in data["tracks"] for r in t["roles"]] == [
        "Quantitative Trading", "Quantitative Research", "Quantitative Development", "Investment Banking Analyst",
        "M&A Analyst", "Capital Markets Analyst", "Strategy Consulting", "Management Consulting", "Operations Consulting",
        "Software Engineer"]


def test_a_role_based_start_asks_from_the_chosen_chips_and_rates_by_the_roles_chips(monkeypatch):
    from app import voice_routes
    from test_exam_session import Analyzer  # noqa: F401
    from test_bank_runtime import ScriptedProvider
    bank = Bank({t.template_id: t for t in (parse_template(_raw_bag(template_id="cp", topic="Conditional probability")),
                                            parse_template(_raw_bag(template_id="dp", topic="Discrete probability")))})
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    monkeypatch.setattr(voice_routes, "provider", lambda: ScriptedProvider())
    client = TestClient(app)
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "quant", "role": "quant_trading", "topics": ["Probability"],
                          "level": "Easy", "typed_practice": True})
        asked = []
        while True:
            e = socket.receive_json()
            if e["type"] == "session":
                sid = e["id"]
            if e["type"] == "question":
                asked.append(e["topic"])
                r = int(e["text"].split(" red")[0].split()[-1])
            if e["type"] == "state" and e["value"] == "listening":
                socket.send_json({"type": "typed", "transcript": f"My answer is {r}/{r + 11}, because red over all balls."})
            if e["type"] == "session_end":
                break
    assert asked and set(asked) == {"Discrete probability"}
    report = client.get(f"/api/interview/{sid}/report").json()
    assert report["topics"] == "Probability (Quantitative Trading)"
    assert {i["area"] for i in report["rating_items"]} == {"Probability"}
    with client.websocket_connect("/api/interview/ws") as socket:  # a chip from another role is refused
        socket.send_json({"type": "begin", "consent": True, "pack": "quant", "role": "quant_trading", "topics": ["DCF"]})
        assert socket.receive_json()["message"] == "Choose topics from this role."


def test_a_software_role_start_is_a_45_minute_coding_interview(monkeypatch, tmp_path):
    from app import coding, voice_routes
    from test_coding import FIXTURE, FakeSpark
    monkeypatch.setenv("CODING_DIR", str(FIXTURE))
    monkeypatch.setenv("CONVERSATIONAL", "0")
    coding._load.cache_clear()
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    monkeypatch.setattr(voice_routes, "provider", lambda: FakeSpark())
    with TestClient(app).websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "software", "role": "swe", "topics": [], "typed_practice": True})
        first = socket.receive_json()
        while first["type"] != "session":
            first = socket.receive_json()
        assert first["session_seconds"] == 45 * 60
        import time
        session = interview_routes.SESSIONS[first["id"]]
        assert session.deadline - time.monotonic() > 44 * 60  # not the 10-minute spoken session
    coding._load.cache_clear()
