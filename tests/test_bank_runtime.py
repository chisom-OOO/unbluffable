"""Forge templates at runtime: loading, the general checker, the ladder, the Exam Room
session and its report. Hand-made fixtures in tests/fixtures/forge; fake model only."""

import asyncio
import json
import random
import re
from fractions import Fraction
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import exam_text as say
from app import interview_report, interview_routes, voice_routes
from app.interview_session import ExamSession, VoiceAnalyzer, context_for
from app.main import app
from engine.answers import StatedNumber
from engine.bank import (MIN_INSTANCES, PREVIOUS_ANSWER, BankSource, Diagnostic, ForgeError,
                         instance_puzzle, load_bank, parse_template, twin_choice)
from engine.checker import accepts, parse_exact, parse_value, values_in
from engine.coding import Outcome, code_answer
from engine.help import position
from engine.interview import Interview
from engine.labels import Label
from voice.schemas import CONTEXT

FIXTURES = Path(__file__).parent / "fixtures" / "forge"


@pytest.fixture(scope="module")
def bank():
    return load_bank(FIXTURES)


def frac(x: Fraction) -> str:
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"


# --- General numeric checker --------------------------------------------------

@pytest.mark.parametrize("text,value,form", [
    ("18/67", Fraction(18, 67), "fraction"),
    ("18 out of 67", Fraction(18, 67), "fraction"),
    ("eighteen out of sixty-seven", Fraction(18, 67), "fraction"),
    ("two thirteenths", Fraction(2, 13), "fraction"),
    ("five over thirty six", Fraction(5, 36), "fraction"),
    ("26.9%", Fraction(269, 1000), "percent"),
    ("twenty five percent", Fraction(1, 4), "percent"),
    ("nought point two five", Fraction(1, 4), "decimal"),
    ("0.25", Fraction(1, 4), "decimal"),
    ("12.4", Fraction(62, 5), "decimal"),
    ("forty-two", Fraction(42), "integer"),
    ("1,000", Fraction(1000), "integer"),
    ("minus three", Fraction(-3), "integer"),
    ("-1/2", Fraction(-1, 2), "fraction"),
])
def test_checker_reads_any_exact_answer_form(text, value, form):
    assert parse_value(f"so my answer is {text}") == StatedNumber(value, form)


def test_checker_tolerance_applies_to_decimals_not_fractions():
    answer = Fraction(18, 67)  # 0.26865...
    tol = Fraction(1, 200)
    assert accepts(parse_value("36/134"), answer, tol)  # same value, unreduced
    assert not accepts(parse_value("27/100"), answer, tol)  # a fraction must be exact
    assert accepts(parse_value("0.27"), answer, tol)
    assert accepts(parse_value("26.9%"), answer, tol)
    assert not accepts(parse_value("0.28"), answer, tol)
    assert not accepts(parse_value("0.27"), answer, Fraction(0))
    assert accepts(parse_value("twelve"), Fraction(12), Fraction(0))


def test_parse_exact_and_values():
    assert parse_exact("18/67") == Fraction(18, 67)
    assert parse_exact("-0.01") == Fraction(-1, 100)
    assert parse_exact("25%") == Fraction(1, 4)
    assert parse_exact(3) == Fraction(3)
    for bad in ("", "1/0", "about 3", True, None):
        with pytest.raises(ValueError):
            parse_exact(bad)
    assert values_in("36 outcomes, 5 of them, so 5/36 or about 13.9%") == [
        Fraction(36), Fraction(5), Fraction(5, 36), Fraction(139, 1000)]


# --- Loading the contract -------------------------------------------------------

def test_fixtures_load_with_topics_and_counts(bank):
    assert bank.errors == []
    assert bank.topics() == [("Percentages", 1), ("Probability", 1), ("Statistics", 1)]
    assert {t.difficulty for t in bank.templates.values()} == {"Easy", "Medium", "Hard"}
    assert all(len(t.instances) >= MIN_INSTANCES for t in bank.templates.values())
    mean = bank.templates["fx_mean_added"]
    assert all(i.part2 is not None for i in mean.instances)
    assert bank.templates["fx_dice_total"].instances[0].part2 is None


def test_invalid_templates_are_skipped_not_served(tmp_path):
    good = json.loads((FIXTURES / "fx_dice_total.json").read_text(encoding="utf-8"))
    (tmp_path / "good.json").write_text(json.dumps(good), encoding="utf-8")
    few = {**good, "template_id": "few", "instances": good["instances"][:MIN_INSTANCES - 1]}
    (tmp_path / "few.json").write_text(json.dumps(few), encoding="utf-8")
    bad_answer = {**good, "template_id": "bad", "instances": [{**i, "answer": "about a seventh"} for i in good["instances"]]}
    (tmp_path / "bad.json").write_text(json.dumps(bad_answer), encoding="utf-8")
    (tmp_path / "dupe.json").write_text(json.dumps(good), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    loaded = load_bank(tmp_path)
    assert list(loaded.templates) == ["fx_dice_total"]
    assert len(loaded.errors) == 4
    with pytest.raises(ForgeError):
        parse_template({**good, "difficulty": "Trivial"})


# --- Coding a forge answer -------------------------------------------------------

def test_forge_answers_code_exactly_with_named_misconceptions(bank):
    t = bank.templates["fx_dice_total"]
    q = instance_puzzle(t, t.instances[3], 3)  # total 6: 5/36
    assert q.answer == Fraction(5, 36) and q.tolerance == Fraction(1, 200)
    assert code_answer(q, parse_value("5 out of 36"), "valid").outcome is Outcome.CORRECT
    assert code_answer(q, parse_value("0.139"), "valid").outcome is Outcome.CORRECT
    assert code_answer(q, parse_value("0.15"), "valid").outcome is Outcome.OTHER_WRONG
    named = code_answer(q, parse_value("1/11"), "valid")
    assert named.outcome is Outcome.NAMED_WRONG
    assert named.misconception == "treats the eleven possible totals as equally likely"
    assert code_answer(q, parse_value("5/36"), "vague").outcome is Outcome.VAGUE
    twin = instance_puzzle(t, t.instances[0], 0, original=q)
    assert twin.answer != q.answer
    assert code_answer(twin, parse_value("5/36"), "valid").outcome is Outcome.RECITED


def test_steps_are_the_solution_map(bank):
    t = bank.templates["fx_dice_total"]
    q = instance_puzzle(t, t.instances[3], 3)
    assert position(q, []) == 0
    assert position(q, values_in("there are 36 outcomes")) == 1
    assert position(q, values_in("36 outcomes and 5 of them")) == 2
    assert position(q, values_in("so about 13.9%")) == 3


# --- Ladder and selection ---------------------------------------------------------

def test_twin_is_another_instance_with_a_different_answer(bank):
    t = bank.templates["fx_dice_total"]
    for seed in range(20):
        for original in range(len(t.instances)):
            for suspect in (None, EQUAL_TOTALS, BY_SIX):
                i, _ = twin_choice(t, original, random.Random(seed), suspect)
                assert i != original and t.instances[i].answer != t.instances[original].answer


EQUAL_TOTALS = "treats the eleven possible totals as equally likely"
BY_SIX = "divides by six instead of thirty-six outcomes"


def test_diagnostic_twin_separates_the_suspected_misconception(bank):
    """Decision log 16. Original: total 6, 5/36 (total 8 shares the answer, so it is never the twin)."""
    t = bank.templates["fx_dice_total"]
    # 1/11 everywhere: total 12 (1/36) is furthest from it.
    assert twin_choice(t, 3, random.Random(0), EQUAL_TOTALS) == (8, Diagnostic(EQUAL_TOTALS, Fraction(1, 36), Fraction(1, 11), True))
    # ways/6: totals 5 and 9 (1/9 against 2/3) tie on that gap and on the tie-break; either is drawn.
    seen = {twin_choice(t, 3, random.Random(seed), BY_SIX) for seed in range(30)}
    assert seen == {(i, Diagnostic(BY_SIX, Fraction(1, 9), Fraction(2, 3), True)) for i in (2, 5)}


def test_diagnostic_twin_tie_break_is_the_gap_to_other_wrong_methods(bank):
    """Mean template, suspected "divides the new total by the old count": totals over 4 vs 5.
    Gaps tie between instances; the tie-break keeps the other methods furthest away."""
    t = bank.templates["fx_mean_added"]
    old_count = "divides the new total by the old count"
    gaps = {i: abs(inst.answer - inst.wrong[1].value) for i, inst in enumerate(t.instances) if i != 0}
    best = max(gaps.values())
    tied = [i for i, g in gaps.items() if g == best]
    i, why = twin_choice(t, 0, random.Random(1), old_count)
    assert i in tied and why.suspected and why.wrong == t.instances[i].wrong[1].value
    def rest(j):
        inst = t.instances[j]
        return min(abs(inst.answer - inst.wrong[0].value), abs(inst.answer - t.instances[0].answer))
    assert rest(i) == max(rest(j) for j in tied)


def test_without_a_suspect_the_twin_maximises_the_smallest_gap(bank):
    t = bank.templates["fx_dice_total"]
    i, why = twin_choice(t, 3, random.Random(0))
    # total 12: 1/36 is 0.063 from 1/11, its closest wrong method (5/36 and 1/6 are further).
    assert i == 8 and why == Diagnostic(EQUAL_TOTALS, Fraction(1, 36), Fraction(1, 11), False)
    # A misconception the template does not name is not a suspect here.
    assert twin_choice(t, 3, random.Random(0), "some other error") == (i, why)
    # Repeating the previous answer counts as a wrong method.
    i, why = twin_choice(t, 8, random.Random(0))
    assert why.misconception in {EQUAL_TOTALS, PREVIOUS_ANSWER, BY_SIX}
    others = [j for j in range(9) if j != 8 and t.instances[j].answer != t.instances[8].answer]
    nearest = lambda j: min([abs(t.instances[j].answer - w.value) for w in t.instances[j].wrong]
                            + [abs(t.instances[j].answer - t.instances[8].answer)])
    assert nearest(i) == max(nearest(j) for j in others) == abs(why.correct - why.wrong)


class _Source:
    """Records the suspect each twin is aimed at."""

    def __init__(self):
        self.suspects, self.n = [], 0

    def candidates(self):
        return ["a", "b", "c"][self.n:]

    def new(self, template_id):
        self.n += 1
        return template_id

    def twin(self, puzzle, suspect=None):
        self.suspects.append(suspect)
        return puzzle + "'"


def test_interview_aims_the_twin_at_the_suspected_misconception():
    from engine.coding import Observation
    # A named wrong first answer is the suspect.
    iv = Interview(source=_Source())
    iv.next_question()
    iv.record(Observation(Outcome.NAMED_WRONG, misconception="m1"))
    assert iv.next_question().kind == "twin" and iv.source.suspects == ["m1"]
    # Recovered after a challenge: scored Correct, but the error it showed still aims the twin.
    iv = Interview(source=_Source())
    iv.next_question()
    iv.record(Observation(Outcome.CORRECT), weight=Fraction(2, 3), misconception="m2")
    iv.next_question()
    assert iv.source.suspects == ["m2"]
    # Right first time: no suspect from that question; an earlier one counts only while M leads.
    iv = Interview(source=_Source())
    iv.next_question()
    iv.record(Observation(Outcome.CORRECT))
    assert iv.suspected is None
    iv._named = ["m0"]
    iv.posterior = {"S": Fraction(2, 10), "M": Fraction(5, 10), "G": Fraction(3, 10)}
    assert iv.suspected == "m0"
    iv.posterior = {"S": Fraction(5, 10), "M": Fraction(3, 10), "G": Fraction(2, 10)}
    assert iv.suspected is None


def test_session_twin_is_aimed_and_explained_after_it_is_answered(bank):
    """Q1 named wrong and not recovered: the twin is the instance furthest from that error,
    and "Why these numbers?" arrives only once the twin is scored."""
    averages = "averages the old mean with the new number"

    def policy(session, events):
        q = session.questions[-1]
        m, x = q.puzzle.params["mean"], q.puzzle.params["added"]
        if q.kind == "new":
            return f"My answer is {frac(Fraction(m + x, 2))}, because I averaged them."
        return f"My answer is {frac(q.puzzle.answer)}, because the new total is {4 * m + x} over 5 numbers."

    session, events, _ = run(BankSource(bank, "Statistics", "Medium", rng=random.Random(4)), policy)
    q1, q2 = session.questions
    assert q1.scored == "named_wrong" and q2.kind == "twin"
    t = bank.templates["fx_mean_added"]
    gap = lambda j: abs(t.instances[j].answer - t.instances[j].wrong[0].value)
    assert gap(q2.puzzle.instance) == max(gap(j) for j in range(9) if j != q1.puzzle.instance
                                          and t.instances[j].answer != q1.puzzle.answer)
    assert q2.puzzle.diagnostic.suspected and q2.puzzle.diagnostic.misconception == averages
    scored = [e for e in events if e["type"] == "scored"]
    assert [e["why"] is None for e in scored] == [True, False]
    assert f"Suspected error ({averages})" in scored[1]["why"]
    twin_question = next(i for i, e in enumerate(events) if e["type"] == "question" and e["kind"] == "twin")
    assert events.index(scored[1]) > twin_question
    assert not any("Suspected error" in str(e) for e in events[:events.index(scored[1])])

    report = interview_report.build(session)
    why = report["report"]["breakdown"][1]["items"][-1]
    assert why["title"] == "Why these numbers?" and why["why"]["suspected"] is True
    assert why["why"]["correct"] == say.value(q2.puzzle.answer)
    assert all(item["title"] != "Why these numbers?" for item in report["report"]["breakdown"][0]["items"])


def test_ladder_starts_easy_or_medium_and_steps_on_first_answers(bank):
    with pytest.raises(ValueError):
        BankSource(bank, start="Hard")
    source = BankSource(bank, start="Easy", rng=random.Random(1))
    assert source.candidates() == ["fx_dice_total"]
    source.step(Outcome.CORRECT)
    assert source.difficulty == "Medium" and source.candidates() == ["fx_mean_added"]
    source.step(Outcome.CORRECT)
    source.step(Outcome.CORRECT)  # capped at Hard
    assert source.difficulty == "Hard" and source.candidates() == ["fx_price_change"]
    source.step(Outcome.NAMED_WRONG)
    assert source.difficulty == "Medium"
    source.step(Outcome.VAGUE)
    assert source.difficulty == "Medium"
    source.new("fx_mean_added")
    # No Medium template left: the closest level, easier first on a tie.
    assert source.candidates() == ["fx_dice_total"]
    assert BankSource(bank, "Statistics", "Medium").candidates() == ["fx_mean_added"]


def test_interview_asks_forge_questions_with_twins_up_to_four(bank):
    source = BankSource(bank, start="Medium", rng=random.Random(3))
    interview = Interview(rng=random.Random(3), source=source)
    asked = []
    while (question := interview.next_question()) is not None:
        asked.append((question.kind, question.puzzle.template_id, question.puzzle.difficulty))
        outcome = Outcome.OTHER_WRONG if question.kind == "new" else Outcome.VAGUE
        interview.record(code_answer(question.puzzle, parse_value("999999") if outcome is Outcome.OTHER_WRONG else None, "valid"))
        source.step(outcome)
    assert 2 <= len(asked) <= 4
    assert asked[0] == ("new", "fx_mean_added", "Medium")
    # Selection (spec/02 §4) chooses twin or new; a new one after a wrong first answer
    # comes from one level down, and a twin always repeats the previous new template.
    assert asked[1] == ("new", "fx_dice_total", "Easy")
    previous_new = None
    for kind, template_id, _ in asked:
        if kind == "twin":
            assert template_id == previous_new
        else:
            previous_new = template_id
    assert len({t for k, t, _ in asked if k == "new"}) == len([k for k, *_ in asked if k == "new"])


# --- The Exam Room session with a fake model ----------------------------------------

ANSWER = re.compile(r"answer is (.+?), because")


class ScriptedProvider:
    """Extracts "answer is X, because" verbatim; reasoning is valid when a because-clause follows."""

    mode = "live"

    def __init__(self):
        self.prompts = []

    async def structured(self, text, kind, effort, schema, prompt):
        self.prompts.append((kind, prompt))
        m = ANSWER.search(text)
        span = m.group(1) if m else "none"
        if kind == "minimal":
            return {"committed_number_text": span, "is_commitment": m is not None}, {"model": "fake"}
        quotes = [{"quote": text[m.end():].strip(), "step": "other"}] if m and text[m.end():].strip() else []
        return {"committed_answer_text": span, "reasoning_quotes": quotes,
                "reasoning_code": "valid" if quotes else "vague",
                "misconception_name": "none", "self_corrected": False}, {"model": "fake"}


def run(source, policy):
    """`policy(session, events)` returns the candidate's next utterance."""
    events = []
    provider = ScriptedProvider()

    async def send(event):
        events.append(event)

    async def listen():
        return policy(session, events)

    session = ExamSession(send, listen, VoiceAnalyzer(provider), Interview(rng=random.Random(5), source=source))
    asyncio.run(session.run())
    return session, events, provider


def test_statistics_session_part2_challenge_help_and_report(bank):
    script = []

    def policy(session, events):
        q = session.questions[-1]
        m, x = q.puzzle.params["mean"], q.puzzle.params["added"]
        last = [e for e in events if e["type"] == "interviewer_line"][-1]
        if q.part2 is not None:
            # Part 2: wrong (the named value) after Q1, right after the twin.
            target = q.puzzle.part2.params["target"]
            text = (f"My answer is {target}, because that is the mean."
                    if q.number == 1 else f"My answer is {m + 5}, because five numbers must total {5 * (m + 1)}.")
        elif q.number == 1:
            text = f"My answer is {frac(q.puzzle.answer)}, because the total goes from {4 * m} to {4 * m + x}, over 5 numbers."
        elif last["kind"] == "question":
            text = f"My answer is {frac(Fraction(m + x, 2))}, because I averaged them."
        elif last["kind"] == "challenge":
            text = "Can I get a hint"
        elif last["text"] == say.HELP_ASK:
            text = "I don't know where to start."
        else:
            text = f"My answer is {frac(q.puzzle.answer)}, because the new total is {4 * m + x} over 5 numbers."
        script.append(text)
        return text

    source = BankSource(bank, "Statistics", "Medium", rng=random.Random(2))
    session, events, provider = run(source, policy)

    q1, q2 = session.questions
    assert (q1.kind, q2.kind) == ("new", "twin")
    assert q1.puzzle.template_id == q2.puzzle.template_id == "fx_mean_added"
    assert q1.puzzle.instance != q2.puzzle.instance and q2.puzzle.recited == q1.puzzle.answer
    # Q1 right first time, then its part 2 (reported, not scored).
    assert (q1.scored, q1.weight, q1.recovered) == ("correct", 1, False)
    assert q1.part2.outcome == "named_wrong"
    assert q1.part2.answers[-1].misconception == "gives the target mean instead of the number needed"
    # The twin: a named wrong answer, the challenge, a hint aimed at step 1, then recovered.
    assert q2.first_wrong[0].misconception == "averages the old mean with the new number"
    hint = [e for e in events if e["type"] == "interviewer_line" and e["kind"] == "hint"]
    assert hint[0]["text"] == say.forge_step_prompt("total of the four numbers") and hint[0]["target_step"] == 1
    assert (q2.scored, q2.help_load, q2.weight, q2.recovered) == ("correct", 1, Fraction(2, 4), True)
    assert q2.part2.outcome == "correct"
    # Every model prompt carries the forge question, never the fraud context.
    assert all(q1.puzzle.text in p or q2.puzzle.text in p or "fifth number would make" in p for _, p in provider.prompts)
    assert not any(CONTEXT in p for _, p in provider.prompts)
    questions = [e for e in events if e["type"] == "question"]
    assert [(e["topic"], e["difficulty"]) for e in questions] == [("Statistics", "Medium")] * 2
    assert [e["type"] for e in events].count("part2") == 2
    assert session.interview.finished  # only one Statistics template: nothing left after the twin

    report = interview_report.build(session)
    assert report["questions"] == 2 and report["label"] in {"supports", "more-evidence"}
    q1_items, q2_items = (tab["items"] for tab in report["report"]["breakdown"])
    assert q1_items[0]["number"] == {"said": frac(q1.puzzle.answer), "exact": interview_report.exact_value(q1.puzzle)}
    assert q1_items[-1]["title"] == "Part 2: not the exact value"
    assert q1_items[-1]["misconception"] == "gives the target mean instead of the number needed"
    assert q1_items[-1]["question"] == q1.puzzle.part2.text
    assert q2_items[0]["misconception"] == "averages the old mean with the new number"
    assert q2_items[0]["quote"] in script
    assert q2_items[-2]["title"] == "Part 2: right"
    # Q1 was right first time: no suspect, so the twin keeps every wrong method far away.
    assert q2_items[-1]["title"] == "Why these numbers?" and q2_items[-1]["why"]["suspected"] is False
    assert "Statistics, Medium" in report["report"]["breakdown"][0]["sub"]
    assert report["outcomes"][1]["help_load"] == 1
    assert report["tip"] == interview_report.FORGE_TIP
    assert any(i["title"] == "Try the next step yourself before asking for help" for i in report["report"]["improve"])


def test_part2_is_never_asked_after_a_wrong_answer(bank):
    def policy(session, events):
        q = session.questions[-1]
        return "My answer is 999, because I guessed."

    session, events, _ = run(BankSource(bank, "Statistics", "Medium", rng=random.Random(4)), policy)
    assert all(q.part2 is None for q in session.questions)
    assert "part2" not in [e["type"] for e in events]
    assert all(q.scored == "other_wrong" for q in session.questions)


def test_forge_context_and_silence_check(bank):
    t = bank.templates["fx_price_change"]
    q = instance_puzzle(t, t.instances[0], 0)
    context = context_for(q)
    assert context.startswith(f"The question asks: {q.text} ") and "fraud" not in context
    provider = ScriptedProvider()
    analyzer = VoiceAnalyzer(provider)
    assert asyncio.run(analyzer.committed(q, "So the answer is 1%, because 1.1 times 0.9 is 0.99."))
    assert not asyncio.run(analyzer.committed(q, "Still working on it."))


def test_ladder_moves_between_new_questions_in_mixed(bank):
    """Wrong on an Easy dice question cannot go lower; right on the twin does not move
    the ladder until the question's first answer is scored."""
    def policy(session, events):
        q = session.questions[-1]
        if q.part2 is not None:
            return f"My answer is {frac(q.puzzle.part2.answer)}, because it follows."
        return f"My answer is {frac(q.puzzle.answer)}, because I worked it out."

    source = BankSource(bank, start="Easy", rng=random.Random(9))
    session, events, _ = run(source, policy)
    news = [q for q in session.questions if q.kind == "new"]
    assert news[0].puzzle.difficulty == "Easy"
    assert all(q.scored == "correct" for q in session.questions)
    assert session.interview.label is Label.SUPPORTS
    assert source.levels[0] == "Easy"
    assert source.difficulty == "Hard"  # stepped up after each correct first answer


# --- Routes: topic picker ------------------------------------------------------------

def test_topics_list_forge_topics_mixed_and_fraud(monkeypatch, bank):
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    data = TestClient(app).get("/api/interview/topics").json()
    assert data["default"] == "Mixed" and data["levels"] == ["Easy", "Medium"]
    assert [(t["id"], t["count"]) for t in data["topics"]] == [
        ("Mixed", 3), ("Percentages", 1), ("Probability", 1), ("Statistics", 1), ("fraud", None)]


def test_fraud_alert_is_the_default_only_without_templates(monkeypatch, tmp_path):
    monkeypatch.setattr(interview_routes, "_BANK", load_bank(tmp_path))
    data = TestClient(app).get("/api/interview/topics").json()
    assert data["default"] == "fraud" and [t["id"] for t in data["topics"]] == ["fraud"]


def test_socket_serves_the_chosen_topic_and_level(monkeypatch, bank):
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    provider = ScriptedProvider()
    monkeypatch.setattr(voice_routes, "provider", lambda: provider)
    with TestClient(app).websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "topic": "Percentages", "level": "Medium"})
        while (event := socket.receive_json())["type"] != "question":
            pass
        assert event["template"] == "fx_price_change" and event["difficulty"] == "Hard"
        assert "fraud" not in event["text"].lower()
        socket.send_json({"type": "end"})


def test_socket_without_topic_starts_mixed_not_fraud(monkeypatch, bank):
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    monkeypatch.setattr(voice_routes, "provider", lambda: ScriptedProvider())
    with TestClient(app).websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        while (event := socket.receive_json())["type"] != "question":
            pass
        assert event["template"] == "fx_dice_total" and event["difficulty"] == "Easy"
        socket.send_json({"type": "end"})


# --- Evidence meter (decision log 16) -----------------------------------------------

def test_what_if_previews_the_waiting_question_without_changing_anything():
    from engine.coding import Observation
    from engine.likelihoods import load_likelihoods
    from engine.posterior import update
    lk = load_likelihoods()
    iv = Interview(source=_Source())
    with pytest.raises(RuntimeError):
        iv.what_if(Outcome.CORRECT)
    iv.next_question()
    before = dict(iv.posterior)
    posterior, label = iv.what_if(Outcome.CORRECT)
    assert posterior == update(before, lk.first(Outcome.CORRECT)) and label is Label.MORE_EVIDENCE
    assert iv.posterior == before and iv.answers == 0
    iv.record(Observation(Outcome.NAMED_WRONG, misconception="m1"))
    assert iv.next_question().kind == "twin"
    posterior, label = iv.what_if(Outcome.NAMED_WRONG)
    assert posterior == update(iv.posterior, lk.twin(Outcome.NAMED_WRONG, Outcome.NAMED_WRONG))
    assert label is Label.MISCONCEPTION


def test_meter_after_each_scored_answer_with_what_would_change_it(bank):
    def policy(session, events):
        q = session.questions[-1]
        if q.part2 is not None:
            return f"My answer is {frac(q.puzzle.part2.answer)}, because it follows."
        return f"My answer is {frac(q.puzzle.answer)}, because I worked it out."

    seen = []

    class Watch(Interview):
        def record(self, *args, **kwargs):
            super().record(*args, **kwargs)
            seen.append({k: float(v) for k, v in self.posterior.items()})

    source = BankSource(bank, start="Easy", rng=random.Random(9))
    events = []

    async def send(event):
        events.append(event)

    session = ExamSession(send, lambda: _async(policy(session, events)), VoiceAnalyzer(ScriptedProvider()),
                          Watch(rng=random.Random(5), source=source))
    asyncio.run(session.run())
    scored = [e for e in events if e["type"] == "scored"]
    assert len(scored) == len([q for q in session.questions if q.scored]) == len(seen) >= 2
    for event, posterior in zip(scored, seen):
        rows = event["meter"]["estimate"]
        assert [r["label"] for r in rows] == ["Sound", "Misconception", "Gap"]
        assert [r["p"] for r in rows] == [posterior["S"], posterior["M"], posterior["G"]]
    first = scored[0]["meter"]["line"]
    assert first.startswith("On the twin, a right answer with reasoning would move Sound to ")
    assert "a named error would move Misconception to " in first
    assert scored[-1]["meter"]["line"] == say.METER_FINAL
    # The meter arrives before the next question is asked, and peeking asks nothing extra.
    questions = [i for i, e in enumerate(events) if e["type"] == "question"]
    assert all(events.index(s) < q for s, q in zip(scored, questions[1:]))
    assert len(questions) == len(session.questions)
    assert not any(word in str(scored).lower() for word in ("calibrated", "proves understanding", "can't be fooled"))


def test_meter_line_names_a_label_the_next_answer_would_reach():
    right = ({"S": Fraction(85, 100), "M": Fraction(1, 10), "G": Fraction(5, 100)}, Label.SUPPORTS)
    named = ({"S": Fraction(1, 10), "M": Fraction(6, 10), "G": Fraction(3, 10)}, Label.MORE_EVIDENCE)
    assert say.meter_line("new", right, named) == (
        "On the next question, a right answer with reasoning would move Sound to 85% "
        "(“Evidence supports understanding”); a named error would move Misconception to 60%.")


async def _async(value):
    return value
