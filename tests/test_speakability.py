"""Freeze-day voice fixes: what the interviewer says for a question, and the speakability scan
that keeps hard-to-hear families out of the spoken pool (engine/unspoken.json)."""
import json
import re

import pytest

from engine import speakability as S
from engine.bank import UNSPOKEN_FILE, load_bank, unspoken
from forge import speakability_scan

PLAIN = "A bag has 2 red and 11 blue balls. What is the chance of red?"


@pytest.mark.parametrize("text, reason", [
    ("Values are [3, 5, 7]. What is the median?", "list"),
    ("Returns are 3, 5, 7 and 9 percent. What is the mean?", "list"),
    ("What f in [0,1) maximises growth?", "brackets"),
    ("The objective is (12)x^2 + (-19)x. What is the minimum?", "brackets"),
    ("Travel from (0,0) to (6,13). How many routes?", "tuple"),
    ("Let x_1 be the first draw. What is its mean?", "subscript"),
    ("Let x₁ be the first draw. What is its mean?", "subscript"),
    ("Cash flows 78, 216 and 432; rate 20; debt 100; cash 0; 65 shares. What per share?", "numbers"),
])
def test_hard_to_hear_questions_point_to_the_screen(text, reason):
    f = S.flags(text)
    assert f.screen_only and any(r.startswith(reason) or r.endswith(reason) for r in f.reasons), f.reasons
    said = S.spoken_question(text)
    assert said.startswith(S.ON_SCREEN + " ")
    assert said.endswith("?") and said.count("?") == 1, "only the final question sentence"
    assert not re.search(r"[\[\](){}_]", said)


def test_a_plain_question_is_said_in_full():
    assert not S.flags(PLAIN).screen_only
    assert S.spoken_question(PLAIN) == PLAIN
    # Six numbers is still fine; seven points to the screen.
    six = "Costs 1, then 2; prices 3 and 4; 5 units and 6 days. What is profit?"
    assert S.numbers(six) == 6 and not S.flags(six).numbers > S.MAX_NUMBERS
    assert S.numbers("Probabilities 1/8 and 0.25 and 3/4") == 3, "a fraction or decimal is one number"


def test_the_forge_spoken_text_is_used_and_the_final_sentence_comes_from_it():
    shown = "Let X ~ Uniform(0, 27) for 18 jobs. What is E[min]?"
    said = S.spoken_question(shown, "Eighteen jobs each finish uniformly within 27 units. What is the expected first finish?")
    assert said == f"{S.ON_SCREEN} What is the expected first finish?"


@pytest.mark.parametrize("raw, said", [
    ("Y=1", "Y equals 1"),
    ("What is P(Y=1)?", "What is the probability that Y equals 1?"),
    ("What is P(red)?", "What is the probability of red?"),
    ("What is E[X]?", "What is the expected value of X?"),
    ("Start at (2, 3).", "Start at 2 and 3."),
    ("f in [0,1)", "f in between 0 and 1"),
    ("so x_1 = 4", "so x 1 equals 4"),
    ("x <= 3 and y >= 2", "x is at most 3 and y is at least 2"),
])
def test_never_brackets_underscores_or_tuples_aloud(raw, said):
    assert S.clean_spoken(raw) == said


def test_final_question_sentence():
    assert S.final_question("A die has 6 faces. It costs 0.5 to roll. What is the value? Answer in dollars.") == "What is the value?"
    assert S.final_question("Pay 2. Find the expected profit.") == "Find the expected profit."
    assert S.sentences("Wealth grows by 1.5 times. Done.") == ["Wealth grows by 1.5 times.", "Done."]


def test_scan_only_flags_length_jargon_and_proportional():
    long = " ".join(["word"] * 46) + "?"
    assert S.flags(long).reasons == ["46 words"] and not S.flags(long).screen_only
    assert "jargon: toy payoff" in S.flags("In a toy payoff game, what do you win?").reasons
    assert "jargon: fill indicator" in S.flags("The fill indicator is one. What next?").reasons
    assert "proportional to [" in S.flags("The prior is proportional to [1, 2]. What next?").reasons


def test_lead_ins_are_a_fixed_short_list():
    assert S.LEAD_INS[:2] == ("Okay, try this one.", "Here's the next one.")
    assert all(len(x.split()) <= 5 and x.endswith(".") for x in S.LEAD_INS)


# --- The spoken pool ---------------------------------------------------------------------

def test_hidden_families_leave_the_pool_but_stay_loaded(tmp_path):
    full = load_bank(hidden=frozenset())
    some = sorted(full.templates)[:3]
    bank = load_bank(hidden=frozenset(some))
    assert set(bank.templates) == set(full.templates), "reports, drills and the forge page still find them"
    assert not any(t.template_id in some for t in bank.pool("Mixed"))
    assert sum(n for _, n in bank.topics()) == len(full.templates) - 3
    # Reversible: no file, nothing hidden; another directory (tests, FORGE_DIR) hides nothing by default.
    assert unspoken(tmp_path / "missing.json") == frozenset()
    (tmp_path / "u.json").write_text(json.dumps({"hidden": {"x": {}}}), encoding="utf-8")
    assert unspoken(tmp_path / "u.json") == {"x"}


def test_the_committed_list_matches_the_scan_and_leaves_no_topic_empty():
    committed = json.loads(UNSPOKEN_FILE.read_text(encoding="utf-8"))
    result = speakability_scan.scan()
    assert set(committed["hidden"]) == set(result["hidden"]), "rerun: python -m forge.speakability_scan"
    assert set(committed["kept_least_bad"]) == set(result["kept_least_bad"])
    bank = load_bank()
    assert bank.hidden == set(committed["hidden"])
    full = load_bank(hidden=frozenset())
    for pack in full.packs():
        before = {t for t, _ in full.topics(pack)}
        after = {t for t, _ in bank.topics(pack)}
        assert before == after, f"{pack}: a topic lost all its families: {before - after}"
    # Every hidden family has most variants flagged; every kept one is the least-bad of an otherwise empty topic.
    for tid, f in committed["hidden"].items():
        assert f["flagged"] * 2 > f["variants"]
    for tid, f in committed["kept_least_bad"].items():
        assert tid not in bank.hidden and "non-empty" in f["why"]


def test_no_role_loses_a_topic_chip():
    from app import roles
    full, bank = load_bank(hidden=frozenset()), load_bank()
    for role in roles.ROLES.values() if isinstance(roles.ROLES, dict) else roles.ROLES:
        names = lambda b: [c.name for _, c in roles.live_chips(b, role)]  # noqa: E731
        assert names(bank) == names(full), role
