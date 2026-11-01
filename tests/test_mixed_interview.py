"""Mixed interviews (decision log 37): special formats combine with regular topics and with each
other in one interview, run as ordered segments by each format's own session. A single special
chip still runs on its own. Scoring stays separate: the forge questions give the Bayesian label,
market making keeps its exact scorecard, behavioural and conversational stay model-judged and
out of the rating. Fake models only; no network."""

import asyncio
import random
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import behavioural, interview_report, interview_routes, market, mixed, voice_routes
from app.interview_session import ExamSession, VoiceAnalyzer
from app.main import app
from engine import market as m
from engine.bank import Bank, BankSource, parse_template
from engine.interview import Interview
from test_bank_runtime import ScriptedProvider, _raw_bag
from test_exam_session import RED, typed
from test_market_session import FakeSpark
from voice.recording import VoiceError


def bag(topic, pack=None, template_id="bag"):
    raw = _raw_bag(n=21, topic=topic, topics=[topic], template_id=template_id, pack=pack)
    raw["instances"] = [row for row in raw["instances"] if row["params"]["red"] != 11]
    return parse_template(raw)


class Models:
    """One fake for every job: forge extraction (scripted), market quotes, behavioural judging."""
    mode = "live"

    def __init__(self):
        self.forge, self.market, self.kinds = ScriptedProvider(), FakeSpark(), []

    async def structured(self, text, kind, effort, schema, prompt):
        self.kinds.append(kind)
        if kind.startswith("market_"):
            return await self.market.structured(text, kind, effort, schema, prompt)
        if kind == "behavioural":
            return {"steps": [{"step": "Situation", "quote": "Last spring"}], "relevant": [], "drift": [], "details": [],
                    "contradictions": []}, {"model": "fake"}
        if kind == "conversational":
            return {"points": [], "misconceptions": []}, {"model": "fake"}
        return await self.forge.structured(text, kind, effort, schema, prompt)


@pytest.fixture
def routes(monkeypatch):
    bank = Bank({t.template_id: t for t in (bag("Conditional probability"), bag("DCF", pack="ib", template_id="dcf"))})
    models = Models()
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    monkeypatch.setattr(voice_routes, "provider", lambda: models)
    return models


def play(begin):
    """Runs one interview over the socket with typed answers; returns (events, report)."""
    client = TestClient(app)
    events, kind, text = [], None, ""
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "typed_practice": True, **begin})
        while True:
            e = socket.receive_json()
            events.append(e)
            if e["type"] == "error":
                raise AssertionError(e["message"])
            if e["type"] == "question":
                kind, text = e["kind"], e["text"]
            if e["type"] == "state" and e["value"] == "listening":
                answer = ("0 at 2000" if kind == "market"
                          else typed(text, "right") if RED.search(text)
                          else "Last spring I led the work and we hit 3 of 4 goals.")
                socket.send_json({"type": "typed", "transcript": answer})
            if e["type"] == "session_end":
                break
        session_id = next(x["id"] for x in events if x["type"] == "session")
    return events, client.get(f"/api/interview/{session_id}/report").json()


def spoken(events):
    return [e["text"] for e in events if e["type"] == "interviewer_line"]


# --- Selection -------------------------------------------------------------------------

def test_selection_accepts_mixes_and_a_single_special_chip_still_runs_alone(routes):
    assert interview_routes.selection("quant", ["Market making"])[1] == "Market making"
    assert interview_routes.selection("ib", ["Behavioural"])[1] == "Behavioural"
    assert interview_routes.selection("quant", ["Market making", "Conditional probability"])[1] == \
        ("Market making", "Conditional probability")
    assert interview_routes.selection("ib", ["Behavioural", "DCF", "Conversational"])[1] == ("Behavioural", "DCF", "Conversational")
    assert interview_routes.selection("quant", ["Conditional probability"])[1] == "Mixed"  # only forge topics: as before
    with pytest.raises(VoiceError, match="Choose topics from this track"):
        interview_routes.selection("quant", ["Market making", "Behavioural"])


def test_role_with_one_special_chip_runs_that_session_on_its_own(routes):
    events, report = play({"pack": "ib", "role": "ib_analyst", "topics": ["Behavioural"]})
    assert [e["kind"] for e in events if e["type"] == "question"] == ["behavioural", "behavioural"]  # two questions, as today
    assert "segments" not in report and len(report["behavioural"]) == 2
    assert not any(line in spoken(events) for line in mixed.TRANSITIONS.values())


# --- The defaults table ----------------------------------------------------------------

def test_segment_order_follows_the_defaults_table():
    assert mixed.order("quant", {"market", "forge"}) == ["forge", "market"]
    assert mixed.order("ib", {"cases", "conversational", "forge", "behavioural"}) == ["behavioural", "forge", "conversational", "cases"]
    assert mixed.order("consulting", {"cases", "behavioural"}) == ["behavioural", "cases"]
    assert mixed.order("consulting", {"forge", "behavioural"}) == ["behavioural", "forge"]
    assert mixed.order("software", {"design", "coding"}) == ["coding", "design"]
    # One table: every format has an order, a share of the time, a count when mixed and a spoken line.
    for track, formats in mixed.ORDER.items():
        for f in formats:
            assert f in mixed.FORMATS, (track, f)
    for f, row in mixed.FORMATS.items():
        assert row.share > 0 and row.transition.endswith(".") and row.heading
    assert mixed.FORMATS["market"].count == 1 and mixed.FORMATS["behavioural"].count == 1
    assert mixed.FORMATS["design"].count == 1 and mixed.FORMATS["conversational"].count == 1


def test_the_topics_payload_carries_the_order_for_the_setup_note(routes):
    data = TestClient(app).get("/api/interview/topics").json()
    quant = next(t for t in data["tracks"] if t["id"] == "quant")
    assert [s["format"] for s in quant["mix"]] == ["forge", "market"]
    assert quant["mix"][1]["note"] == "a market-making game"


def test_shares_split_the_remaining_time_by_weight():
    now, end = 100.0, 700.0  # ten minutes left; forge 6, market 4
    assert mixed.share_deadline(["forge", "market"], 0, now, end) == pytest.approx(460.0)
    assert mixed.share_deadline(["forge", "market"], 1, 460.0, end) == end  # the last segment gets the rest


# --- Over the socket -------------------------------------------------------------------

def test_a_mixed_quant_interview_asks_forge_questions_then_one_market_game(routes):
    events, report = play({"pack": "quant", "role": "quant_trading", "topics": ["Market making", "Conditional probability"]})
    kinds = [e["kind"] for e in events if e["type"] == "question"]
    first_market = kinds.index("market")
    assert first_market > 0 and set(kinds[:first_market]) <= {"new", "twin", "ladder"} and kinds[first_market:] == ["market"]
    # The transition is spoken once, right before the market round, and the interview ends once.
    lines = spoken(events)
    assert lines.count(mixed.FORMATS["market"].transition) == 1
    at = next(i for i, e in enumerate(events) if e.get("text") == mixed.FORMATS["market"].transition)
    assert next(e for e in events[at:] if e["type"] == "question")["kind"] == "market"
    assert sum(e["type"] == "session_end" for e in events) == 1
    assert lines.count("That's the end of the interview. Your report is ready.") == 1
    assert events[0]["type"] == "session" and events[0]["session_seconds"] == 600
    # The report: one section per segment, in order, each its own report.
    assert [s["format"] for s in report["segments"]] == ["forge", "market"]
    forge, game = (s["report"] for s in report["segments"])
    assert report["label"] == forge["label"] and forge["cards"]
    assert len(game["market"]) == 1 and game["label"] is None
    # Rating: the same items each part gives on its own, nothing new.
    assert report["rating_items"] == forge["rating_items"] + game["rating_items"]
    assert report["track"] == "quant" and report["mixed"] is True


def test_a_mixed_ib_interview_starts_with_one_behavioural_question(routes):
    events, report = play({"pack": "ib", "role": "ib_analyst", "topics": ["DCF", "Behavioural"]})
    kinds = [e["kind"] for e in events if e["type"] == "question"]
    assert kinds[0] == "behavioural" and kinds.count("behavioural") == 1 and len(kinds) > 1
    assert set(kinds[1:]) <= {"new", "twin", "ladder"}
    question = next(e for e in events if e["type"] == "question")
    assert question["of"] == 1  # "Behavioural question 1 of 1"
    lines = spoken(events)
    assert lines.count(mixed.FORMATS["forge"].transition) == 1
    assert lines.count(behavioural.OPENING) == 1 and mixed.FORMATS["behavioural"].transition not in lines  # first: no switch line
    assert sum(e["type"] == "session_end" for e in events) == 1
    assert [s["format"] for s in report["segments"]] == ["behavioural", "forge"]
    told, forge = (s["report"] for s in report["segments"])
    assert len(told["behavioural"]) == 1 and told["rating_items"] == []  # model-judged, out of the rating
    assert report["rating_items"] == forge["rating_items"] and report["label"] == forge["label"]


def test_legacy_pack_and_topics_also_mix(routes):
    events, report = play({"pack": "quant", "topics": ["Conditional probability", "Market making"]})
    assert [s["format"] for s in report["segments"]] == ["forge", "market"]
    assert spoken(events).count(mixed.FORMATS["market"].transition) == 1


# --- Scoring is unchanged by mixing ----------------------------------------------------

def _run(session):
    asyncio.run(session.run())
    return session


async def _ignore(event):
    pass


def test_market_scorecard_is_the_same_inside_a_mixed_interview():
    game = m.dice("sum", 3, 6)

    def fresh():
        lines = []

        async def send(e):
            if e["type"] == "interviewer_line":
                lines.append(e["kind"])

        async def listen():  # explain when asked about the logic, otherwise quote the same market
            return "Because the sum moved up." if lines and lines[-1] == "probe" else "9 at 12"
        return market.MarketSession(send, listen, FakeSpark(), rng=random.Random(4), games=[game])

    alone = _run(fresh())
    inside = fresh()
    _run(mixed.MixedSession(inside.send, [mixed.Segment("market", inside)], deadline=None, track="quant", topics="Market making"))
    assert market.report(inside)["market"] == market.report(alone)["market"]
    assert market.report(inside)["rating_items"] == market.report(alone)["rating_items"]


def test_bayesian_label_is_the_same_inside_a_mixed_interview():
    template = bag("Conditional probability")
    bank = Bank({template.template_id: template})

    def fresh(send):
        source = BankSource(bank, "Mixed", "Easy", rng=random.Random(2), pack="quant")
        questions = []

        async def record(e):
            if e["type"] == "question":
                questions.append(e["text"])
            await send(e)

        async def listen():
            return typed(questions[-1], "right")
        session = ExamSession(record, listen, VoiceAnalyzer(ScriptedProvider()), Interview(rng=random.Random(5), source=source))
        session.track = "quant"  # as the route sets it
        return session

    alone = _run(fresh(_ignore))
    inside = fresh(_ignore)
    _run(mixed.MixedSession(_ignore, [mixed.Segment("forge", inside)], deadline=None, track="quant", topics="x"))
    assert inside.interview.label == alone.interview.label
    assert interview_report.build(inside)["rating_items"] == interview_report.build(alone)["rating_items"]


def test_a_wrong_number_is_never_coded_correct_in_a_mixed_interview(routes, monkeypatch):
    # The candidate gives the other colour every time: no forge card in the mixed report says correct.
    import test_mixed_interview as me
    original = me.typed
    monkeypatch.setattr(me, "typed", lambda text, role: original(text, "other"))
    _, report = play({"pack": "quant", "role": "quant_trading", "topics": ["Market making", "Conditional probability"]})
    forge = report["segments"][0]["report"]
    assert forge["cards"] and all(item["outcome"] != "correct" for item in forge["rating_items"])


# --- Setup chips (Node) -----------------------------------------------------------------

def test_chip_logic_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable for the isolated JavaScript unit check.")
    result = subprocess.run([node, str(Path(__file__).with_name("mix_unit.cjs"))], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_setup_uses_the_shared_chip_logic():
    ui = Path(__file__).resolve().parents[1] / "app"
    js = (ui / "static" / "ui" / "interview.js").read_text(encoding="utf-8")
    html = (ui / "templates" / "interview.html").read_text(encoding="utf-8")
    assert "/ui-static/mix.js" in html
    assert "isSolo" not in js and "runs on its own" not in js
    assert "UBMix.toggle(" in js and "UBMix.note(" in js
