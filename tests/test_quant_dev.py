"""Quantitative development (app/quant_dev.py): one spoken opener from probability or
expectations (Easy or Medium), then the coding round on the quant_dev families; "Being
added" until those families have coding specs."""

import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import coding, interview_routes, voice_routes
from app.main import app
from engine.bank import Bank
from test_bank_runtime import ScriptedProvider
from test_coding import FakeSpark, out
from test_exam_session import BAG, red

FIXTURE = Path(__file__).with_name("fixtures") / "coding"
SPEC = json.loads((FIXTURE / "sw_F001.json").read_text(encoding="utf-8"))


class Provider(ScriptedProvider):
    """The scripted answer checker for the opener; the coding round's fake Spark for the rest."""

    def __init__(self):
        super().__init__()
        self.coding = FakeSpark()

    async def structured(self, text, kind, effort, schema, prompt):
        if kind.startswith("coding_"):
            return await self.coding.structured(text, kind, effort, schema, prompt)
        return await super().structured(text, kind, effort, schema, prompt)


def setup(monkeypatch, tmp_path, with_specs=True):
    specs = tmp_path / "coding"
    specs.mkdir()
    if with_specs:
        qd = {**copy.deepcopy(SPEC), "template_id": "qd_F001", "pack": "quant_dev", "topic": "Simulation"}
        (specs / "qd_F001.json").write_text(json.dumps(qd), encoding="utf-8")
    else:  # no quant-dev families yet: the role runs the opener and the software coding families
        (specs / "sw_F001.json").write_text(json.dumps(SPEC), encoding="utf-8")
    monkeypatch.setenv("CODING_DIR", str(specs))
    monkeypatch.setenv("CODING_SCALE_DIR", str(tmp_path / "none"))
    monkeypatch.setenv("CODING_TWIST_DIR", str(tmp_path / "none"))
    coding._load.cache_clear()
    coding._load_dir.cache_clear()
    monkeypatch.setattr(interview_routes, "_BANK", Bank({BAG.template_id: BAG}))
    monkeypatch.setattr(interview_routes, "_TOPICS", None)
    monkeypatch.setattr(voice_routes, "provider", lambda: Provider())


def role(client):
    quant = next(t for t in client.get("/api/interview/topics").json()["tracks"] if t["id"] == "quant")
    return next(r for r in quant["roles"] if r["id"] == "quant_dev")


def test_quant_development_is_a_quant_role_whose_coding_questions_are_being_added(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path, with_specs=False)
    client = TestClient(app)
    assert "quant_dev" not in [t["id"] for t in client.get("/api/interview/topics").json()["tracks"]]
    r = role(client)
    # No quant-dev coding families yet: still offered (opener + software coding), marked as being added.
    assert (r["name"], r["note"], r["opener"], r["coding"]) == ("Quantitative Development", "Coding questions being added", True, True)
    assert r["chips"] == [] and r["available"]  # no chip has content here (the bag is "Probability", not a chip topic)


def test_a_spoken_opener_then_the_coding_round(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    client = TestClient(app)
    assert role(client)["available"] is True and role(client)["note"] is None
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "quant", "role": "quant_dev", "topics": [], "typed_practice": True})
        events, puzzle = [], None
        while True:
            e = socket.receive_json()
            events.append(e)
            if e["type"] == "session":
                sid = e["id"]
                assert e["session_seconds"] == 45 * 60
            if e["type"] == "question" and e["kind"] != "coding":
                assert e["opener"] is True and e["topic"] == "Probability" and e["difficulty"] in {"Easy", "Medium"}
                puzzle = e
            if e["type"] == "state" and e["value"] == "listening":
                coding_started = any(x["type"] == "question" and x["kind"] == "coding" for x in events)
                if not coding_started:
                    r = int(puzzle["text"].split(" red")[0].split()[-1])
                    socket.send_json({"type": "typed", "transcript": f"My answer is {r}/{r + 11}, because red over all balls."})
                elif not any(x["type"] == "coding_open" for x in events):
                    socket.send_json({"type": "typed", "transcript": "A running sum, reset when a gain alone is bigger."})
                elif not any(x["type"] == "coding_result" for x in events):
                    socket.send_json({"type": "code_submit", "code": "...", "outputs": out(SPEC["expected"])})
                else:
                    socket.send_json({"type": "typed", "transcript": "Then it returns the largest single value."})
            if e["type"] == "session_end":
                break
    ends = [e for e in events if e["type"] == "session_end"]
    assert len(ends) == 1 and ends[0]["coding"] is True  # the opener never ends the interview
    order = [e["kind"] for e in events if e["type"] == "question"]
    assert order[0] != "coding" and order[-1] == "coding"
    report = client.get(f"/api/interview/{sid}/report").json()
    assert report["topics"] == "Quant development: spoken opener + coding round" and report["quant_dev"] is True
    assert report["track"] == "quant" and report["opener"]["cards"]
    assert [i["area"] for i in report["rating_items"]] == ["Probability", "Coding"]  # the opener's quant area; quant-dev coding
    assert report["problems"][0]["template_id"] == "qd_F001"
