"""The Easy quant pack (decision log row 45): 30 qe_ families, every one cross-checked."""
from __future__ import annotations

import json
from pathlib import Path

from app import roles
from engine.bank import DEFAULT_DIR, load_bank, unspoken

FILES = sorted(Path(DEFAULT_DIR).glob("qe_*.json"))
RAW = [json.loads(p.read_text(encoding="utf-8")) for p in FILES]


def test_all_30_easy_quant_families_ship_and_load():
    assert [r["template_id"] for r in RAW] == [f"qe_F{i:03d}" for i in range(1, 31)]
    assert all(r["pack"] == "quant" and r["difficulty"] == "Easy" for r in RAW)
    bank = load_bank(hidden=frozenset())
    assert all(r["template_id"] in bank.templates for r in RAW)


def test_every_solver_reproduces_every_variant_exactly():
    for r in RAW:
        solver = r["verification"]["solver"]
        assert solver["passed"] and solver["variants_checked"] == len(r["instances"]) == 50, r["template_id"]
        assert solver["max_absolute_error"] == "0", r["template_id"]


def test_24_have_verified_wrong_methods_and_the_other_6_name_no_misconception():
    verified = [r for r in RAW if r["verification"]["misconceptions_verified"]]
    assert len(verified) == 24
    for r in RAW:
        if r not in verified:
            assert not any(i["wrong"] for i in r["instances"]), r["template_id"]


def test_only_the_two_five_number_lists_leave_the_spoken_pool():
    assert sorted(t for t in unspoken() if t.startswith("qe_")) == ["qe_F013", "qe_F014"]


def test_every_quant_chip_on_a_new_topic_offers_an_easy_spoken_question():
    bank, topics = load_bank(), {r["topic"] for r in RAW}
    for role in roles.ROLES:
        if role.track != "quant":
            continue
        for _, chip in roles.live_chips(bank, role):
            if chip.kind == "topic" and topics & set(chip.topics):
                easy = [t for t in bank.pool(chip.topics, pack="quant") if t.difficulty == "Easy"]
                assert easy, (role.id, chip.name)
