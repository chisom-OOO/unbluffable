"""A market-making round end to end (app/market.py): the candidate quotes by voice, code
trades against them, reveals follow with updates, one Spark-chosen question, settlement
and the exact report. Fake Spark; no network."""

import asyncio
import random
import re
from fractions import Fraction as F

from fastapi.testclient import TestClient

from app import interview_routes, market, voice_routes
from app.main import app
from engine import market as m
from test_bank_runtime import _packed_bank


class FakeSpark:
    mode = "live"

    def __init__(self, misread=None):
        self.calls, self.misread = [], misread

    async def structured(self, text, kind, effort, schema, prompt):
        self.calls.append(kind)
        if kind == "market_quote":
            found = re.findall(r"[a-z]+(?: and a half)?|\d+(?:\.\d+)?", text.lower())
            nums = [w for w in found if re.fullmatch(r"\d+(?:\.\d+)?|nine|ten|eleven|twelve|six|seven|eight|five", w)]
            if self.misread and text in self.misread:
                return {"bid_text": "none", "ask_text": "none"}, {"model": "fake"}
            return ({"bid_text": nums[0], "ask_text": nums[-1]} if len(nums) >= 2 else {"bid_text": "none", "ask_text": "none"}), {"model": "fake"}
        if kind == "market_question":
            return {"question": "Why did you move your offer?"}, {"model": "fake"}
        raise AssertionError(kind)


def play(script, games, seed=3, conditions="exam", spark=None):
    events, queue = [], list(script)

    async def send(e):
        events.append(e)

    async def listen():
        assert queue, "the session asked for more than the script gave"
        return queue.pop(0)

    session = market.MarketSession(send, listen, spark or FakeSpark(), rng=random.Random(seed), games=games)
    session.conditions = conditions
    asyncio.run(session.run())
    assert not queue, queue
    return session, events


def said(events, kind=None):
    return [e["text"] for e in events if e["type"] == "interviewer_line" and (kind is None or e["kind"] == kind)]


def test_a_round_trades_reveals_updates_asks_once_and_settles_exactly():
    game = m.dice("sum", 3, 6)  # EV 21/2, var 35/4 (SD about 2.96; 1.5 SD about 4.44)
    session = market.MarketSession(None, None, None, rng=random.Random(3), games=[game])
    r = session.rounds[0]
    draws = r.outcome.draws
    reveals = r.reveals
    assert 2 <= reveals <= 3 or reveals == len(draws) - 1
    # Quote below EV first (lifted), then a wide market (asked to tighten), then tight around EV.
    ev1 = game.ev(draws[:1])
    script = ["eight at nine",                                      # offer 9 < 10.5: they buy at 9
              f"{int(ev1) - 6} at {int(ev1) + 6}",                  # wide around the new EV
              f"{int(ev1)} at {int(ev1) + 1}"]                      # tight (contains EV: x.5 or whole)
    for i in range(1, reveals):
        ev = game.ev(draws[:i + 1])
        script.append(f"{int(ev)} at {int(ev) + 1}")
    script.append("Because the reveal moved the expected sum.")    # the logic question
    session, events = play(script, [game])
    lines = said(events)
    assert lines[1] == game.text and "I'll buy one at 9." in lines
    assert market.TIGHTEN in lines and said(events, "reveal")[0] == f"{game.reveal_line(0, draws[0])} {market.UPDATE}"
    assert said(events, "probe") == ["Why did you move your offer?"]
    settle = next(e for e in events if e["type"] == "market_settle")
    assert settle["payoff"] == str(sum(draws))
    rd = session.rounds[0].round
    assert rd.trades[0] == m.Trade(-1, F(9), F(21, 2))
    # The panel never shows fair value before settlement.
    assert all("ev" not in q for e in events if e["type"] == "market_state" for q in e["quotes"])
    rep = market.report(session)
    one = rep["market"][0]
    assert one["quotes"][0]["contains"] is False and one["quotes"][1]["wide"] is True
    assert one["edge_given"] == "1.5" and one["position"] == rd.position
    assert F(one["realised_pnl"]) == rd.realised_pnl() and F(one["expected_pnl"]) == rd.expected_pnl()
    assert one["question"] == {"question": "Why did you move your offer?", "answer": "Because the reveal moved the expected sum."}
    item, = rep["rating_items"]
    card = m.scorecard(rd)
    assert item["area"] == "Market making" and F(item["value"]) == card["score"] * F(3, 5)  # Easy cap
    assert rep["label"] is None and rep["topics"] == "Market making"


def test_unclear_quotes_are_asked_again_crossed_ones_rejected_and_doubts_confirmed():
    game = m.heads(6)
    script = ["hmm, let me see, around three",  # no quote
              "four at two",                    # crossed
              "two and a half, four",           # Spark misreads it: confirm
              "no",
              "2.5 at 3.5",
              ]
    session = market.MarketSession(None, None, None, rng=random.Random(1), games=[game])
    for i in range(session.rounds[0].reveals):
        script.append("2 at 3")
    script.append("It moved.")
    spark = FakeSpark(misread={"two and a half, four"})
    session, events = play(script, [game], seed=1, spark=spark)
    prompts = said(events, "prompt")
    assert market.ASK_AGAIN in prompts and market.CROSSED in prompts
    assert "Just to check: 2.5 bid, 4 offered?" in prompts and "Sorry, I misheard. What's your market?" in prompts
    assert session.rounds[0].round.quotes[0].bid == F(5, 2)


def test_the_quant_track_lists_market_making_on_its_own(monkeypatch):
    monkeypatch.setattr(interview_routes, "_BANK", _packed_bank(("a", None, "Probability")))
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    quant = next(t for t in TestClient(app).get("/api/interview/topics").json()["tracks"] if t["id"] == "quant")
    assert "Market making" in [o["id"] for o in quant["topics"]]
    assert interview_routes.selection("quant", ["Market making"])[1] == "Market making"
    import pytest
    from voice.recording import VoiceError
    with pytest.raises(VoiceError):
        interview_routes.selection("quant", ["Market making", "Probability"])
    assert interview_routes.selection("quant", ["Probability"])[1] == "Mixed"  # market making isn't a forge topic
    monkeypatch.setenv("MARKET_MAKING", "0")
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    quant = next(t for t in TestClient(app).get("/api/interview/topics").json()["tracks"] if t["id"] == "quant")
    assert "Market making" not in [o["id"] for o in quant["topics"]]


def test_a_market_making_interview_over_the_socket(monkeypatch):
    monkeypatch.setattr(interview_routes, "_BANK", _packed_bank(("a", None, "Probability")))
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    monkeypatch.setattr(voice_routes, "provider", lambda: FakeSpark())
    client = TestClient(app)
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "quant", "topics": ["Market making"], "typed_practice": True})
        sid, rounds = None, 0
        while True:
            e = socket.receive_json()
            if e["type"] == "session":
                sid = e["id"]
            if e["type"] == "question":
                assert e["kind"] == "market"
                rounds += 1
            if e["type"] == "state" and e["value"] == "listening":
                socket.send_json({"type": "typed", "transcript": "1 at 1000"})  # contains every EV; wide, then accepted
            if e["type"] == "session_end":
                assert e["market"] is True
                break
    report = client.get(f"/api/interview/{sid}/report").json()
    assert rounds == market.ROUNDS and len(report["market"]) == rounds
    assert all(q["contains"] for r in report["market"] for q in r["quotes"])
    assert report["conditions"].startswith("Typed practice")


def test_prices_are_shown_exactly():
    for x, shown in [(F(155, 32), "4.84375"), (F(21, 2), "10.5"), (F(16775, 324), "16775/324"), (F(-3, 4), "-0.75"), (F(7), "7")]:
        assert market.fmt(x) == shown and F(shown) == x
