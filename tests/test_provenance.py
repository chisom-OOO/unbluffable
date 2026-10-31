"""Forge provenance, visible: where each question came from (real content), the receipt row
for a verified wrong method, the report cards and /api/forge."""

import asyncio
import random

from fastapi.testclient import TestClient

from app import interview_report, interview_routes, provenance, voice_routes
from app.interview_session import ExamSession, VoiceAnalyzer
from app.main import app
from engine.bank import BankSource, instance_puzzle, load_bank
from engine.coding import code_answer
from engine.interview import Interview
from test_bank_runtime import ScriptedProvider, _packed_bank

BANK = load_bank()


def verified_family():
    return next(t for t in sorted(BANK.templates.values(), key=lambda t: t.template_id)
                if t.verification.get("misconceptions_verified") and t.verification.get("solver", {}).get("passed"))


def test_provenance_reads_the_families_verification_record():
    t = verified_family()
    p = provenance.provenance(t)
    assert p["author"] == "Muse Spark Open" and p["author_id"].startswith("meta-models/muse-spark-open")
    assert p["variants"] == len(t.instances) and p["variants_checked"] == t.verification["solver"]["variants_checked"]
    assert p["wrong_methods_verified"] and p["wrong_methods"] and all("_" not in n for n in p["wrong_methods"])
    assert p["solver_source_stored"] is False
    rows = {r["key"]: r["text"] for r in provenance.rows(p)}
    assert rows["solver"].startswith(f"Written by Muse Spark Open; reproduced the verified answer on {p['variants_checked']}/{p['variants']} variants")
    assert rows["wrong_methods"].startswith(f"{len(p['wrong_methods'])} verified in code: ")
    assert "Not stored" in rows["source"]
    assert provenance.provenance(None) is None and provenance.rows(None) == []


def test_a_matched_verified_wrong_method_says_where_it_came_from():
    t = verified_family()
    inst = next(i for i in t.instances if any(nv.value != i.answer for nv in i.wrong))
    puzzle = instance_puzzle(t, inst, t.instances.index(inst))
    nv = next(nv for nv in puzzle.named_values if nv.value != puzzle.answer)
    from engine.answers import StatedNumber
    obs = code_answer(puzzle, StatedNumber(nv.value, "fraction"), "valid")
    row = provenance.matched_row(t, puzzle, obs)
    assert row["label"] == "Where this wrong method came from"
    assert row["text"].startswith("Matches a wrong method Muse Spark Open wrote and code verified: ")
    assert provenance.matched_row(t, puzzle, code_answer(puzzle, StatedNumber(puzzle.answer, "fraction"), "valid")) is None


def test_question_events_and_report_cards_carry_it(monkeypatch):
    t = verified_family()
    bank = type(BANK)({t.template_id: t})
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    events = []

    async def send(e):
        events.append(e)

    async def listen():
        q = session.questions[-1].puzzle
        nv = next((nv for nv in q.named_values if nv.value != q.answer), None)
        value = nv.value if nv and len(session.questions) == 1 and len(session.questions[-1].answers) == 0 else q.answer
        return f"My answer is {value.numerator}/{value.denominator}, because I worked it out." if value.denominator != 1 \
            else f"My answer is {value.numerator}, because I worked it out."

    source = BankSource(bank, "Mixed", t.difficulty if t.difficulty in ("Easy", "Medium", "Hard") else "Easy",
                        rng=random.Random(1), pack=t.pack)
    session = ExamSession(send, listen, VoiceAnalyzer(ScriptedProvider()), Interview(rng=random.Random(2), source=source))
    session.track = t.pack
    asyncio.run(session.run())
    q_event = next(e for e in events if e["type"] == "question")
    assert [r["key"] for r in q_event["provenance_rows"]] == ["solver", "wrong_methods", "source"]
    report = interview_report.build(session, bank.templates)
    assert all(c["provenance"]["template_id"] == t.template_id for c in report["cards"])
    receipts = [row for q in session.questions for a in q.answers for row in a.receipt["rows"]]
    assert any(r["key"] == "forge_method" for r in receipts)  # the opening answer was the verified wrong method


def test_forge_catalogue_lists_every_family_with_totals():
    client = TestClient(app)
    data = client.get("/api/interview/forge").json()
    families = [f for track in data["tracks"] for f in track["families"]]
    assert len(families) == len(BANK.templates) == data["totals"]["families"]
    assert {t["id"] for t in data["tracks"]} == {t.pack for t in BANK.templates.values()}
    assert data["totals"]["variants"] == sum(len(t.instances) for t in BANK.templates.values())
    assert data["totals"]["wrong_methods_verified"] == sum(len(f["wrong_methods"]) for f in families)
    page = client.get("/ui/forge")
    assert page.status_code == 200 and "The question bank" in page.text and "forge.js?v=" in page.text
