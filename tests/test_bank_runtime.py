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
from voice.recording import VoiceError
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
    assert not accepts(parse_value("0.2"), answer, Fraction(0))  # one significant figure
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


def test_ladder_starts_at_a_known_level_and_steps_on_first_answers(bank):
    with pytest.raises(ValueError):
        BankSource(bank, start="Expert")
    assert BankSource(bank, start="Hard").difficulty == "Hard"  # a rating of 70+ starts here (decision log 23)
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
        if "verdict" in schema["properties"]:  # follow-up judge: "<verdict>: <quote>"
            verdict, _, quote = text.partition(": ")
            verdict = verdict.lower()
            return {"verdict": verdict if verdict in ("yes", "partly", "no") else "no",
                    "quote": quote or "none"}, {"model": "fake"}
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

def test_topics_list_forge_topics_and_mixed(monkeypatch, bank):
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    data = TestClient(app).get("/api/interview/topics").json()
    assert data["default_track"] == "quant" and data["levels"] == ["Easy", "Medium", "Hard"]
    track, *rest = data["tracks"]  # the fixtures carry no pack, so all are Quant
    assert (track["id"], track["name"], track["default"], track["available"]) == ("quant", "Quant", "Mixed", True)
    assert [(t["id"], t["available"], t["topics"]) for t in rest] == [
        ("ib", False, []), ("consulting", False, []), ("software", False, [])]
    assert [(t["id"], t["count"]) for t in track["topics"]] == [
        ("Mixed", 3), ("Percentages", 1), ("Probability", 1), ("Statistics", 1)]


def test_without_templates_no_track_is_open_and_no_interview_starts(monkeypatch, tmp_path):
    monkeypatch.setattr(interview_routes, "_BANK", load_bank(tmp_path))
    data = TestClient(app).get("/api/interview/topics").json()
    assert data["default_track"] is None and not any(t["available"] for t in data["tracks"])
    with pytest.raises(VoiceError, match="No questions are available yet"):
        interview_routes.interview_for(None, None, "Easy")


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


def test_socket_without_topic_starts_mixed(monkeypatch, bank):
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


# --- Receipts (decision log 16) --------------------------------------------------------

def _named_then_right(bank, seed=4):
    def policy(session, events):
        q = session.questions[-1]
        if q.part2 is not None:
            return f"My answer is {frac(q.puzzle.part2.answer)}, because it follows."
        m, x = q.puzzle.params["mean"], q.puzzle.params["added"]
        last = [e for e in events if e["type"] == "interviewer_line"][-1]
        if q.kind == "new" and last["kind"] == "question":
            return f"My answer is {frac(Fraction(m + x, 2))}, because I averaged them."
        return f"My answer is {frac(q.puzzle.answer)}, because the new total is {4 * m + x} over 5 numbers."

    return run(BankSource(bank, "Statistics", "Medium", rng=random.Random(seed)), policy)


def test_judgement_receipts_show_words_and_computation_but_not_the_answer_mid_question(bank):
    session, events, _ = _named_then_right(bank)
    q1 = session.questions[0]
    lines = [e for e in events if e["type"] == "interviewer_line"]
    challenge = next(e for e in lines if e["kind"] == "challenge")
    r = challenge["receipt"]
    assert r["words"] == q1.answers[0].transcript and r["span"] in r["words"]
    assert [row["key"] for row in r["rows"]] == ["said", "reasoning"] and r["note"]
    # The exact answer and the matched error stay hidden until the question ends.
    assert str(q1.puzzle.answer) not in " ".join(row["text"] for row in r["rows"])
    assert "averages the old mean" not in str(r)
    # Closes carry the full receipt once the question is scored.
    closes = [e for e in lines if e["kind"] == "close" and e["receipt"]]
    full = closes[0]["receipt"]
    keys = [row["key"] for row in full["rows"]]
    assert keys[:3] == ["said", "exact", "check"] and "methods" in keys and "coded" in keys
    text = {row["key"]: row["text"] for row in full["rows"]}
    assert text["exact"] == say.value(q1.puzzle.answer)
    # Q1 was recovered: its close is about the final, right answer.
    assert text["coded"].startswith("Correct") and "matches it" not in text["methods"]
    assert "or within" in text["check"] and text["check"].endswith("so it matches.")
    # The opening answer's receipt, in the report, shows the matched wrong method.
    opening = interview_report.build(session)["report"]["breakdown"][0]["items"][0]["receipt"]
    rows = {row["key"]: row["text"] for row in opening["rows"]}
    assert "averages the old mean with the new number: " in rows["methods"] and "(your number matches it)" in rows["methods"]
    assert rows["coded"] == "A known wrong method (averages the old mean with the new number)"


def test_every_report_line_opens_a_receipt(bank):
    session, events, _ = _named_then_right(bank)
    report = interview_report.build(session)
    r = report["report"]
    items = r["well"] + r["improve"] + [i for tab in r["breakdown"] for i in tab["items"]]
    assert items and all(i["receipt"]["rows"] for i in items)
    assert all(e["receipt"]["words"] == e["quote"] for e in report["evidence"])
    assert all(c["receipt"] for c in report["checks"]) and all(o["receipt"] for o in report["outcomes"])
    # Numbers: the words quoted are the candidate's own, verbatim.
    said = {a.transcript for q in session.questions for a in q.answers + (q.part2.answers if q.part2 else [])}
    said |= {t for q in session.questions for t in q.said}
    assert all(i["receipt"]["words"] in said for i in items if i["receipt"]["words"])
    # The twin's "Why these numbers?" quotes the answer that showed the suspected error.
    why = r["breakdown"][1]["items"][-1]
    assert why["title"] == "Why these numbers?"
    assert why["receipt"]["words"] == session.questions[0].answers[0].transcript
    gap = next(row for row in why["receipt"]["rows"] if row["key"] == "gap")["text"]
    d = session.questions[1].puzzle.diagnostic
    assert gap.endswith(say.value(abs(d.correct - d.wrong)))
    # The help weight is shown as computed.
    q1_outcome = report["outcomes"][0]["receipt"]
    assert any(row["key"] == "weight" for row in q1_outcome["rows"])


def test_receipt_check_uses_the_instance_tolerance(bank):
    from app import receipts
    t = bank.templates["fx_dice_total"]
    q = instance_puzzle(t, t.instances[3], 3)  # 5/36, tolerance 0.005
    assert receipts.check_text(q, parse_value("0.139"), q.answer) == (
        "A decimal counts when it is the exact value rounded to the nearest 0.001 (as you said it), "
        "with at least 2 significant figures, or within 0.005: it is 0.0001111 away, so it matches.")
    assert receipts.check_text(q, parse_value("15%"), q.answer).endswith(
        "rounded to the nearest 1% (as you said it), with at least 2 significant figures, "
        "or within 0.005: it is 0.01111 away, so it does not match.")
    assert receipts.check_text(q, parse_value("5/37"), q.answer) == "Fractions must match exactly: 5/37 ≠ 5/36."


# --- Drill mode (decision log 16) --------------------------------------------------------

def test_drill_plan_aims_every_instance_at_the_misconception(bank):
    from engine.bank import drill_plan
    t = bank.templates["fx_dice_total"]
    # Gaps to 1/11: total 12 (1/36) .063, total 8 (5/36) .048, totals 3 and 11 (1/18) .035, ...
    drill, check = drill_plan(t, EQUAL_TOTALS, {3})
    assert check == 8 and drill == [4, 0, 7]
    assert drill_plan(t, EQUAL_TOTALS, set(range(8))) == ([], 8)
    assert drill_plan(t, "not in this template", set()) == ([], None)


def _dice_interview(bank):
    """A Probability session: 1/11 (the named error) on every question."""
    def policy(session, events):
        return "My answer is 1/11, because there are 11 totals."
    return run(BankSource(bank, "Probability", "Easy", rng=random.Random(1)), policy)


def _drill(bank, parent, policy, index=0):
    from app.drill import DrillSession, drill_targets
    target = drill_targets(parent, bank.templates)[index]
    events = []

    async def send(event):
        events.append(event)

    async def listen():
        return policy(session, events)

    session = DrillSession(send, listen, VoiceAnalyzer(ScriptedProvider()), bank.templates[target.template_id], target)
    asyncio.run(session.run())
    return session, events


def test_report_offers_a_drill_for_each_detected_misconception(bank):
    parent, _, _ = _dice_interview(bank)
    report = interview_report.build(parent, bank.templates)
    assert report["drills"] == [{"index": 0, "misconception": EQUAL_TOTALS}]
    assert interview_report.build(parent)["drills"] == []  # no templates: nothing to drill


def test_drill_socratic_questions_then_a_check_still_showing(bank):
    from app.drill import STILL_SHOWING
    parent, _, _ = _dice_interview(bank)

    def policy(session, events):
        last = [e for e in events if e["type"] == "interviewer_line"][-1]
        if last["kind"] == "challenge":
            return "Can I get a hint"
        if last["text"] == say.HELP_ASK:
            return "I don't know where to start."
        return "My answer is 1/11, because there are 11 totals."

    session, events = _drill(bank, parent, policy)
    used = {q.puzzle.instance for q in parent.questions}
    drills = [q for q in session.questions]
    assert [q.kind for q in drills] == ["drill"] * 3 and session.check.kind == "check"
    instances = [q.puzzle.instance for q in drills] + [session.check.puzzle.instance]
    assert len(set(instances)) == 4 and not used & set(instances)
    assert all(q.puzzle.diagnostic.misconception == EQUAL_TOTALS and q.puzzle.part2 is None for q in drills)
    assert all(q.scored == "named_wrong" and q.challenges == 1 and q.hints for q in drills)
    assert session.check.scored == "named_wrong" and session.result == STILL_SHOWING
    # Socratic only: every challenge, nudge and hint is a question or an invitation to talk it through.
    lines = [e for e in events if e["type"] == "interviewer_line"]
    helps = [e["text"] for e in lines if e["kind"] in {"challenge", "nudge", "hint"}]
    assert helps and all(t.endswith("?") or t == say.FORGE_NUDGE for t in helps)
    assert not any(e["type"] in {"part2"} for e in events)
    assert all(e["meter"] is None and e["why"] for e in events if e["type"] == "scored")
    # The check gets no help.
    check_at = next(i for i, e in enumerate(events) if e["type"] == "question" and e["kind"] == "check")
    assert not any(e["type"] == "interviewer_line" and e["kind"] in {"challenge", "nudge", "hint"} for e in events[check_at:])
    assert events[-1] == {"type": "session_end", "drill": True, "result": STILL_SHOWING, "timed_out": False}

    report = interview_report.build_drill(session)
    assert report["drill"]["result"] == STILL_SHOWING and report["drill"]["misconception"] == EQUAL_TOTALS
    assert report["label"] is None and report["tip"] is None and report["estimate"] == []
    assert [t["tab"] for t in report["report"]["breakdown"]] == ["Drill 1", "Drill 2", "Drill 3", "Check"]
    assert all(i["receipt"] for t in report["report"]["breakdown"] for i in t["items"])
    assert [t["items"][0]["seen_names"] for t in report["report"]["breakdown"]] == [["Drill 1"], ["Drill 2"], ["Drill 3"], ["Check"]]


def test_drill_right_first_time_moves_to_the_check_and_clears(bank):
    from app.drill import CLEARED
    parent, _, _ = _dice_interview(bank)

    def policy(session, events):
        q = session.check or session.questions[-1]
        return f"My answer is {frac(q.puzzle.answer)}, because there are 36 equally likely outcomes."

    session, events = _drill(bank, parent, policy)
    assert len(session.questions) == 1 and session.questions[0].scored == "correct"
    assert session.check.scored == "correct" and session.result == CLEARED
    assert interview_report.build_drill(session)["drill"]["result"] == CLEARED


def test_drill_over_the_socket_is_chosen_by_the_server(monkeypatch, bank):
    parent, _, _ = _dice_interview(bank)
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    from collections import OrderedDict
    monkeypatch.setattr(interview_routes, "SESSIONS", OrderedDict(**{"parent-id": parent}))
    monkeypatch.setattr(voice_routes, "provider", lambda: ScriptedProvider())
    client = TestClient(app)
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "drill": {"session": "parent-id", "index": 0}})
        session_event = socket.receive_json()
        assert session_event["type"] == "session" and session_event["drill"] == EQUAL_TOTALS
        while (event := socket.receive_json())["type"] != "question":
            pass
        assert event["kind"] == "drill" and event["template"] == "fx_dice_total"
        socket.send_json({"type": "end"})
    for bad in ({"session": "parent-id", "index": 5}, {"session": "missing", "index": 0}, "parent-id",
                {"session": "parent-id", "index": True}):
        with client.websocket_connect("/api/interview/ws") as socket:
            socket.send_json({"type": "begin", "consent": True, "drill": bad})
            assert socket.receive_json() == {"type": "error", "message": "That drill is no longer available."}
    drill_id = next(k for k, v in interview_routes.SESSIONS.items() if type(v).__name__ == "DrillSession")
    data = client.get(f"/api/interview/{drill_id}/report").json()
    assert data["drill"]["misconception"] == EQUAL_TOTALS and data["label"] is None


# --- Runtime fixes for forge content -------------------------------------------------

OTHER_COLOUR = "picks the other colour"
BY_BLUE = "divides red by blue"


def _raw_bag(n=20, friendly=(), spoken=False, latex=False, names=None, **top):
    """A forge-shaped template: r = i + 2 red and 11 blue balls; P(red) = r / (r + 11)."""
    instances = []
    for i in range(n):
        r = i + 2
        text = (f"A bag has {r} red and 11 blue balls, so $n = {r + 11}$. What is $P(\\text{{red}})$?" if latex
                else f"A bag has {r} red and 11 blue balls. What is the probability a ball drawn is red?")
        row = {"text": text, "params": {"red": r}, "answer": f"{r}/{r + 11}", "tolerance": "0",
               "wrong": [{"value": f"11/{r + 11}", "misconception": OTHER_COLOUR if names is None else names},
                         {"value": f"{r}/11", "misconception": BY_BLUE}],
               "steps": [{"name": "balls", "value": str(r + 11)}, {"name": "probability", "value": f"{r}/{r + 11}"}]}
        if i in friendly:
            row["interview_friendly"] = True
        if spoken:
            row["spoken_text"] = f"A bag has {r} red balls and eleven blue. What is the chance of red?"
        instances.append(row)
    raw = {"template_id": "bag", "topic": "Probability", "topics": ["Probability"], "difficulty": "Easy",
           "instances": instances, **top}
    return {k: v for k, v in raw.items() if v is not None}


def _bag(**kwargs):
    return parse_template(_raw_bag(**kwargs))


def _bag_bank(template):
    from engine.bank import Bank
    return Bank({template.template_id: template})


@pytest.mark.parametrize("said,exact,ok", [
    ("15%", Fraction(2, 13), True),                    # 15.38%: right at the precision said
    ("fifteen percent", Fraction(2, 13), True),
    ("15.4%", Fraction(2, 13), True),
    ("15.3%", Fraction(2, 13), False),
    ("16%", Fraction(2, 13), False),
    ("0.15", Fraction(2, 13), True),
    ("nought point one five", Fraction(2, 13), True),
    ("0.2", Fraction(2, 13), False),                   # one significant figure
    ("2/13", Fraction(2, 13), True),
    ("3/20", Fraction(2, 13), False),                  # a fraction must be exact
    ("1", Fraction(39, 40), False),                    # 0.975: "1" has one significant figure
    ("0.98", Fraction(39, 40), True),
    ("0.97", Fraction(39, 40), True),                  # an exact half rounds either way
    ("97.5%", Fraction(39, 40), True),
    ("98%", Fraction(39, 40), True),
    ("96%", Fraction(39, 40), False),
    ("123", Fraction(1234, 10), True),
    ("120", Fraction(123), False),
    ("-0.15", Fraction(-2, 13), True),
    ("0", Fraction(0), True),                          # exact, whatever its figures
])
def test_spoken_answers_count_when_correctly_rounded_at_the_precision_said(said, exact, ok):
    assert accepts(parse_value(said), exact, Fraction(0)) is ok


def test_rounding_rule_also_matches_wrong_method_values():
    t = _bag()
    q = instance_puzzle(t, t.instances[0], 0)  # 2/13 = 15.4%; other colour 11/13 = 84.6%; by blue 2/11 = 18.2%
    assert code_answer(q, parse_value("85%"), "valid").outcome is Outcome.NAMED_WRONG
    assert code_answer(q, parse_value("85%"), "valid").misconception == OTHER_COLOUR
    assert code_answer(q, parse_value("0.18"), "valid").misconception == BY_BLUE
    assert code_answer(q, parse_value("0.2"), "valid").outcome is Outcome.OTHER_WRONG  # 1 s.f. matches nothing
    assert code_answer(q, parse_value("15%"), "valid").outcome is Outcome.CORRECT
    assert code_answer(q, parse_value("16%"), "valid").outcome is Outcome.OTHER_WRONG


def test_session_codes_a_whole_percent_correct():
    def policy(session, events):
        return f"My answer is {float(session.questions[-1].puzzle.answer) * 100:.0f}%, because red over all balls."
    session, events, _ = run(BankSource(_bag_bank(_bag()), "Probability", "Easy", rng=random.Random(2)), policy)
    assert session.questions and all(q.scored == Outcome.CORRECT.value for q in session.questions)


def test_interview_friendly_instances_are_preferred_and_separation_decides_among_them():
    from engine.bank import drill_plan
    t = _bag(friendly={2, 5, 9, 12, 15})
    assert {BankSource(_bag_bank(t), rng=random.Random(s)).new("bag").instance for s in range(40)} <= {2, 5, 9, 12, 15}
    # Other colour: gap |r - 11| / (r + 11). Instance 0 (r = 2) is furthest but not friendly;
    # among the friendly ones 5 (r = 7, 4/18) beats 15 (r = 17, 6/28); 9 (r = 11) has no gap.
    first = instance_puzzle(t, t.instances[2], 2)
    assert BankSource(_bag_bank(t), rng=random.Random(0)).twin(first, OTHER_COLOUR).instance == 5
    assert all(twin_choice(t, 2, random.Random(s))[0] in {5, 9, 12, 15} for s in range(20))
    assert drill_plan(t, OTHER_COLOUR, {2}) == ([15, 12], 5)
    # None flagged: every instance qualifies, as before.
    plain = _bag()
    assert twin_choice(plain, 2, random.Random(0), OTHER_COLOUR)[0] == 0
    assert drill_plan(plain, OTHER_COLOUR, {2})[1] == 0
    with pytest.raises(ForgeError):
        parse_template({**_raw_bag(), "instances": [{**row, "interview_friendly": "yes"} for row in _raw_bag()["instances"]]})


def test_spoken_text_is_said_and_text_is_shown():
    t = _bag(spoken=True, latex=True)
    q = instance_puzzle(t, t.instances[0], 0)
    assert q.text == "A bag has 2 red and 11 blue balls, so n = 13. What is P(red)?"
    assert q.speech == "A bag has 2 red balls and eleven blue. What is the chance of red?"
    assert Fraction(13) in q.givens


def test_latex_without_spoken_text_is_read_as_words_and_shown_as_unicode():
    from engine import mathtext
    t = _bag(latex=True)
    q = instance_puzzle(t, t.instances[0], 0)
    assert q.speech == "A bag has 2 red and 11 blue balls, so n equals 13. What is P(red)?"
    cases = {
        r"Find $\frac{2}{13}$ of $x^2 + y_1$.": ("Find 2/13 of x² + y₁.", "Find 2 over 13 of x squared plus y sub 1."),
        r"$\binom{10}{3} \times \frac{1}{2^{10}}$": ("C(10, 3) × 1/2¹⁰", "10 choose 3 times 1 over 2 to the power 10"),
        r"$\sqrt{n+1} \le \pi$ at 5\% a year": ("√(n+1) ≤ π at 5% a year",
                                                "the square root of n plus 1 is at most pi at 5 percent a year"),
        r"$P(A \mid B) = \dfrac{P(A \cap B)}{P(B)}$": ("P(A | B) = P(A ∩ B)/P(B)",
                                                       "P(A given B) equals P(A intersect B) over P(B)"),
    }
    for latex, (shown, said) in cases.items():
        assert (mathtext.display(latex), mathtext.spoken(latex)) == (shown, said)
    for plain in ("It costs $5 and $10 in total.", "A well-known 15% of 2/13 - no maths."):
        assert mathtext.display(plain) == mathtext.spoken(plain) == plain


def test_question_lines_carry_speech_only_when_it_differs(bank):
    def policy(session, events):
        return f"My answer is {frac(session.questions[-1].puzzle.answer)}, because red over all balls."
    for template, said in ((_bag(spoken=True, latex=True), "eleven blue"), (_bag(latex=True), "n equals")):
        session, events, _ = run(BankSource(_bag_bank(template), "Probability", "Easy", rng=random.Random(3)), policy)
        asked = [e for e in events if e["type"] == "interviewer_line" and e["kind"] == "question"]
        assert asked and all(said in e["speech"] and "n = " in e["text"] for e in asked)
        assert asked[0]["text"].endswith(say.OPENING) and asked[0]["speech"].endswith(say.OPENING)
        shown = [e for e in events if e["type"] == "question"]
        assert all("$" not in e["text"] and "\\" not in e["text"] for e in shown)
    _, plain, _ = _dice_interview(bank)
    assert not any("speech" in e for e in plain if e["type"] == "interviewer_line")


def test_several_misconception_names_for_one_value_are_one_mistake():
    from types import SimpleNamespace
    from app.drill import drill_targets
    from engine.bank import aimed_puzzle, drill_plan, same_mistake
    both = [OTHER_COLOUR, "counts blue as success"]
    named = " / ".join(both)
    as_list = _bag(names=both)
    as_plural = parse_template({**_raw_bag(), "instances": [
        {**row, "wrong": [{"value": row["wrong"][0]["value"], "misconceptions": both}, row["wrong"][1]]}
        for row in _raw_bag()["instances"]]})
    for t in (as_list, as_plural):
        q = instance_puzzle(t, t.instances[0], 0)
        assert [nv.misconception for nv in q.named_values] == [named, BY_BLUE]
        assert code_answer(q, parse_value("11/13"), "valid").misconception == named
        assert drill_plan(t, named, {0}) == drill_plan(t, OTHER_COLOUR, {0}) != ([], None)
        assert f"({named})" in say.why_numbers(aimed_puzzle(t, 5, named).diagnostic)
        # Named once as both and once by one name: one drill.
        session = SimpleNamespace(questions=[
            SimpleNamespace(puzzle=q, answers=[SimpleNamespace(misconception=named)]),
            SimpleNamespace(puzzle=instance_puzzle(t, t.instances[1], 1),
                            answers=[SimpleNamespace(misconception=OTHER_COLOUR)])])
        assert [d.misconception for d in drill_targets(session, {"bag": t})] == [named]
    assert same_mistake("a / b", "b") and not same_mistake("a / b", "c") and not same_mistake(None, "a")
    for bad in ([], [""], 3):
        with pytest.raises(ForgeError):
            _bag(names=bad)


def test_topic_falls_back_to_source_topic():
    assert _bag(topic=None, source_topic="Counting").topic == "Counting"
    assert _bag(topic="", source_topic="Counting").topic == "Counting"
    assert _bag(topic="Probability", source_topic="Counting").topic == "Probability"
    assert _bag_bank(_bag(topic=None, source_topic="Counting")).topics() == [("Counting", 1)]
    with pytest.raises(ForgeError):
        _bag(topic=None)


# --- Conceptual follow-ups (model-matched, never scored) -----------------------------

FOLLOW = {"question": "Why must the chance of red go up when you add a red ball?",
          "reference": "Red grows faster than the total, so the share of red rises."}


def _follow_session(replies, follow=FOLLOW, provider=None, first="right"):
    """A bag session. `replies`: the candidate's follow-up replies in order."""
    template = parse_template(_raw_bag(follow_up=follow))
    replies = list(replies)
    def policy(session, events):
        q = session.questions[-1]
        last = [e for e in events if e["type"] == "interviewer_line"][-1]
        if last["text"].startswith((say.FOLLOW_UP_INTRO, say.REPEAT_INTRO + " Why", say.FOLLOW_UP_NO_HINT)):
            return replies.pop(0)
        if first == "wrong":
            return "My answer is 11/13, because blue over all."
        return f"My answer is {frac(q.puzzle.answer)}, because red over all balls."
    events, provider = [], provider or ScriptedProvider()

    async def send(event):
        events.append(event)

    async def listen():
        return policy(session, events)

    source = BankSource(_bag_bank(template), "Probability", "Easy", rng=random.Random(3))
    session = ExamSession(send, listen, VoiceAnalyzer(provider), Interview(rng=random.Random(5), source=source))
    asyncio.run(session.run())
    return session, events, provider


def test_follow_up_is_parsed_and_kept_out_of_drills_and_part2():
    from engine.bank import FollowUp, aimed_puzzle
    t = parse_template(_raw_bag(follow_up=FOLLOW))
    assert t.follow_up == FollowUp(FOLLOW["question"], FOLLOW["reference"])
    assert instance_puzzle(t, t.instances[0], 0).follow_up == t.follow_up
    assert aimed_puzzle(t, 3, OTHER_COLOUR).follow_up is None
    assert _bag().follow_up is None
    for bad in ({"question": "Why?"}, {"question": "", "reference": "x"}, {"question": "Why?", "reference": 3}):
        with pytest.raises(ForgeError):
            parse_template(_raw_bag(follow_up=bad))


def test_follow_up_asked_aloud_after_a_correct_answer_once_per_template_and_judged_by_one_call():
    reply = "Yes: red grows faster than the total"
    session, events, provider = _follow_session([reply])
    asked = [e for e in events if e["type"] == "follow_up"]
    assert len(asked) == 1 and asked[0]["text"] == FOLLOW["question"]  # the twin, same template: not asked again
    lines = [e for e in events if e["type"] == "interviewer_line"]
    question = next(e for e in lines if e["text"].startswith(say.FOLLOW_UP_INTRO))
    assert question["kind"] == "question" and question["text"].endswith(FOLLOW["question"])
    judged = [p for k, p in provider.prompts if FOLLOW["reference"] in p]
    assert len(judged) == 1 and FOLLOW["question"] in judged[0]
    result = next(e for e in events if e["type"] == "follow_up_result")
    assert result["verdict"] == "yes" and result["quote"] == "red grows faster than the total"
    q = session.questions[0]
    assert q.follow_up.label == "Model-matched: makes the key point" and q.follow_up.reply == reply
    close = lines[lines.index(question) + 1]
    assert close["kind"] == "close" and close["receipt"]["words"] == reply
    assert close["receipt"]["span"] == "red grows faster than the total"
    rows = {r["key"]: r["text"] for r in close["receipt"]["rows"]}
    assert rows["reference"] == FOLLOW["reference"] and rows["verdict"] == "Model-matched: makes the key point"
    assert "Model-matched, not an exact check, and never scored" in rows["rule"]


def test_follow_up_is_never_scored_by_the_engine():
    with_follow, _, _ = _follow_session(["No: nothing"])
    template = _bag()
    def policy(session, events):
        return f"My answer is {frac(session.questions[-1].puzzle.answer)}, because red over all balls."
    without, _, _ = run(BankSource(_bag_bank(template), "Probability", "Easy", rng=random.Random(3)), policy)
    assert with_follow.interview.posterior == without.interview.posterior
    assert with_follow.interview.label == without.interview.label
    assert [(q.scored, q.weight, q.help_load) for q in with_follow.questions] == \
           [(q.scored, q.weight, q.help_load) for q in without.questions]


def test_follow_up_shown_in_the_report_beside_the_exact_checks():
    session, _, _ = _follow_session(["Partly: red grows"])
    report = interview_report.build(session)
    f = report["follow_ups"]
    assert f == [{"q": "Question 1", "question": FOLLOW["question"], "verdict": "Model-matched: partly makes the key point",
                  "quote": "red grows", "receipt": session.questions[0].follow_up.receipt}]
    assert report["checks"]  # the exact checks are still there
    items = report["report"]["breakdown"][0]["items"]
    item = next(i for i in items if i["title"].startswith("Follow-up"))
    assert item["title"] == "Follow-up: partly makes the key point (model-matched)"
    assert item["verdict"] == "Model-matched: partly makes the key point" and item["receipt"]["rows"]
    # "Keep doing this" stays on the exact answer, not the follow-up.
    assert not any(i["title"].startswith("Follow-up") for i in report["report"]["well"])


def test_follow_up_not_judged_without_a_verbatim_quote_or_on_a_model_error():
    from voice.recording import VoiceError
    session, _, _ = _follow_session(["Yes"])  # a "yes" with no quote
    assert session.questions[0].follow_up.verdict is None
    assert session.questions[0].follow_up.label == "Model-matched: not judged"
    session, _, _ = _follow_session(["No: none of this"])  # quote "none of this" is verbatim
    assert session.questions[0].follow_up.verdict == "no"

    class Paraphrasing(ScriptedProvider):
        async def structured(self, text, kind, effort, schema, prompt):
            if "verdict" in schema["properties"]:
                return {"verdict": "yes", "quote": "words the candidate never said"}, {"model": "fake"}
            return await super().structured(text, kind, effort, schema, prompt)

    session, _, _ = _follow_session(["Red rises."], provider=Paraphrasing())
    log = session.questions[0].follow_up
    assert log.verdict is None and "not in your words" in log.note and log.receipt["note"] == log.note

    class Failing(ScriptedProvider):
        async def structured(self, text, kind, effort, schema, prompt):
            if "verdict" in schema["properties"]:
                raise VoiceError("model down")
            return await super().structured(text, kind, effort, schema, prompt)

    session, events, _ = _follow_session(["Red rises."], provider=Failing())
    assert session.questions[0].follow_up.verdict is None
    assert any(e["type"] == "model_error" and e["job"] == "follow_up" for e in events)


def test_follow_up_help_gets_no_hint_and_a_wrong_answer_gets_no_follow_up():
    session, events, _ = _follow_session(["Can I have a hint?", "Yes: red grows faster than the total"])
    texts = [e["text"] for e in events if e["type"] == "interviewer_line"]
    assert say.FOLLOW_UP_NO_HINT in texts
    assert session.questions[0].hints == 0 and session.questions[0].help_load == 0
    assert session.questions[0].follow_up.verdict == "yes"
    session, events, _ = _follow_session([], first="wrong")
    assert not any(e["type"] == "follow_up" for e in events)


# --- One more digit: a rounded answer that fits two methods ----------------------------

def _close_bag():
    """Each instance's first wrong value is 1/1000 above the answer: "15%" for 2/13 (15.38%)
    rounds from both; "15.4%" from the answer only."""
    raw = _raw_bag()
    for row in raw["instances"]:
        r = row["params"]["red"]
        near = Fraction(r, r + 11) + Fraction(1, 1000)
        row["wrong"][0]["value"] = f"{near.numerator}/{near.denominator}"
    return parse_template(raw)


def test_coarse_answers_are_detected():
    from app.interview_session import Analysis, coarse
    t = _close_bag()
    q = instance_puzzle(t, t.instances[0], 0)
    def analysis(said):
        stated = parse_value(said)
        return Analysis(code_answer(q, stated, "valid"), stated, said)
    assert coarse(q, analysis("15%")) and coarse(q, analysis("0.15"))
    assert not coarse(q, analysis("15.4%")) and not coarse(q, analysis("2/13")) and not coarse(q, analysis("85%"))
    plain = _bag()
    assert not coarse(instance_puzzle(plain, plain.instances[0], 0), analysis("15%"))


def test_one_more_digit_is_asked_once_without_counting_as_help():
    def policy(session, events):
        q = session.questions[-1]
        last = [e for e in events if e["type"] == "interviewer_line"][-1]
        digits = 1 if last["text"] == say.ONE_MORE_DIGIT else 0
        return f"My answer is {float(q.puzzle.answer) * 100:.{digits}f}%, because red over all balls."
    session, events, _ = run(BankSource(_bag_bank(_close_bag()), "Probability", "Easy", rng=random.Random(2)), policy)
    asks = [e for e in events if e["type"] == "interviewer_line" and e["text"] == say.ONE_MORE_DIGIT]
    assert len(asks) == len(session.questions) >= 1
    for q in session.questions:
        assert q.scored == Outcome.CORRECT.value and q.asked_digit
        assert (q.challenges, q.nudges, q.hints, q.help_load, q.recovered) == (0, 0, 0, 0, False)
        assert q.answers[0].outcome is None and q.answers[1].outcome == Outcome.CORRECT.value

    # Still coarse after the one ask: coded as before (the exact answer is checked first).
    def stubborn(session, events):
        return f"My answer is {float(session.questions[-1].puzzle.answer) * 100:.0f}%, because red over all balls."
    session, events, _ = run(BankSource(_bag_bank(_close_bag()), "Probability", "Easy", rng=random.Random(2)), stubborn)
    assert all(q.scored == Outcome.CORRECT.value for q in session.questions)
    asks = [e for e in events if e["type"] == "interviewer_line" and e["text"] == say.ONE_MORE_DIGIT]
    assert len(asks) == len(session.questions)


# --- Tracks: template packs -------------------------------------------------------------

def _packed_bank(*specs):
    """specs: (template_id, pack, topic); pack None leaves the field out."""
    from engine.bank import Bank
    templates = [parse_template(_raw_bag(template_id=tid, pack=pack, topic=topic)) for tid, pack, topic in specs]
    return Bank({t.template_id: t for t in templates})


def test_pack_is_parsed_and_missing_means_quant():
    assert _bag().pack == "quant"
    assert _bag(pack="ib").pack == "ib" and _bag(pack="software").pack == "software"
    for bad in ("banking", "Quant", 3):
        with pytest.raises(ForgeError):
            parse_template(_raw_bag(pack=bad))


def test_bank_lists_packs_and_topics_per_pack():
    bank = _packed_bank(("a", None, "Probability"), ("b", "ib", "Valuation"),
                        ("c", "ib", "Probability"), ("d", "software", "Complexity"))
    assert bank.packs() == ["quant", "ib", "software"]  # PACKS order; no consulting templates
    assert bank.topics("ib") == [("Probability", 1), ("Valuation", 1)]
    assert bank.topics() == [("Complexity", 1), ("Probability", 2), ("Valuation", 1)]
    assert [t.template_id for t in bank.pool("Probability", "ib")] == ["c"]
    assert sorted(t.template_id for t in bank.pool("Mixed", "ib")) == ["b", "c"]
    assert set(BankSource(bank, "Mixed", pack="ib").templates) == {"b", "c"}
    with pytest.raises(ValueError):
        BankSource(bank, "Valuation", pack="quant")


def test_topic_route_groups_topics_by_track_and_marks_empty_tracks(monkeypatch):
    bank = _packed_bank(("a", None, "Probability"), ("b", "ib", "Valuation"), ("c", "consulting", "Market sizing"))
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    data = TestClient(app).get("/api/interview/topics").json()
    assert data["default_track"] == "quant"
    assert [(t["id"], t["name"], t["count"], t["available"]) for t in data["tracks"]] == [
        ("quant", "Quant", 1, True), ("ib", "Investment banking", 1, True), ("consulting", "Consulting", 1, True),
        ("software", "Software engineering", 0, False)]  # no software templates: "Being added"
    topics = {t["id"]: [(o["id"], o["count"]) for o in t["topics"]] for t in data["tracks"]}
    assert topics == {"quant": [("Mixed", 1), ("Probability", 1)],
                      "ib": [("Mixed", 1), ("Valuation", 1)],
                      "consulting": [("Mixed", 1), ("Market sizing", 1)], "software": []}


def test_default_track_is_the_first_shown_when_quant_has_no_templates(monkeypatch):
    monkeypatch.setattr(interview_routes, "_BANK", _packed_bank(("b", "ib", "Valuation"), ("d", "software", "Complexity")))
    data = TestClient(app).get("/api/interview/topics").json()
    assert data["default_track"] == "ib"
    assert [t["id"] for t in data["tracks"] if t["available"]] == ["ib", "software"]
    assert data["tracks"][0]["topics"] == []  # Quant: no templates


def test_interview_uses_the_chosen_track_and_only_its_topics(monkeypatch):
    bank = _packed_bank(("a", None, "Probability"), ("b", "ib", "Probability"), ("c", "ib", "Valuation"))
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    assert set(interview_routes.interview_for("ib", "Probability", "Easy").source.templates) == {"b"}
    assert set(interview_routes.interview_for(None, "Probability", "Easy").source.templates) == {"a"}  # default: Quant
    # A topic from another track is rejected; an unavailable track falls back to the default.
    for pack, topic in (("ib", "fraud"), ("software", "Valuation")):
        with pytest.raises(VoiceError):
            interview_routes.interview_for(pack, topic, "Easy")
    assert set(interview_routes.interview_for("software", "Mixed", "Easy").source.templates) == {"a"}
    # A track being added can't be picked: the default track is used.
    assert set(interview_routes.interview_for("consulting", "Mixed", "Easy").source.templates) == {"a"}


def test_socket_serves_the_chosen_track(monkeypatch):
    bank = _packed_bank(("a", None, "Probability"), ("b", "ib", "Valuation"))
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    monkeypatch.setattr(voice_routes, "provider", lambda: ScriptedProvider())
    with TestClient(app).websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "ib", "topic": "Mixed", "level": "Easy"})
        while (event := socket.receive_json())["type"] != "question":
            pass
        assert event["template"] == "b"
        socket.send_json({"type": "end"})


# --- Decision log 20: the report shows which mode was used ----------------------------

def test_report_shows_exam_typed_practice_or_replay(monkeypatch):
    from app import interview_report
    bank = _packed_bank(("a", None, "Probability"))
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    monkeypatch.setattr(voice_routes, "provider", lambda: ScriptedProvider())
    client = TestClient(app)
    for begin, expected in (({}, "exam"), ({"typed_practice": True}, "typed")):
        with client.websocket_connect("/api/interview/ws") as socket:
            socket.send_json({"type": "begin", "consent": True, "pack": "quant", "level": "Easy", **begin})
            while (event := socket.receive_json())["type"] != "session":
                pass
            session_id = event["id"]
            socket.send_json({"type": "end"})
        session = interview_routes.SESSIONS[session_id]
        assert session.conditions == expected
        assert interview_report.build(session)["conditions"] == interview_report.CONDITIONS[expected]
    assert interview_routes.conditions({"typed_practice": True}, "replay") == "replay"
    assert interview_report.CONDITIONS["typed"] == "Typed practice: not exam conditions"


# --- Report: each quote once, in one evidence card per question -----------------------

def test_report_cards_quote_each_answer_once(bank):
    from app import interview_report
    session, _, _ = _named_then_right(bank)
    report = interview_report.build(session)
    cards = report["cards"]
    scored = [q for q in session.questions if q.scored is not None]
    assert [c["q"] for c in cards] == [interview_report.name(q) for q in scored]
    assert [c["anchor"] for c in cards] == [f"card-{i + 1}" for i in range(len(cards))]
    q1, first = cards[0], scored[0]
    # Named wrong, then right: the opening answer and where you ended up, each quoted once.
    assert [w["when"] for w in q1["words"]] == ["Opening answer", "Where you ended up"]
    assert [w["text"] for w in q1["words"]] == [first.answers[0].transcript, first.answers[-1].transcript]
    assert q1["exact"] == interview_report.exact(first) and ", then " in q1["said"]
    assert q1["receipt"]["rows"] and q1["outcome"] == interview_report.outcome_text(first)
    quotes = [w["text"] for c in cards for w in c["words"]]
    assert len(quotes) == len(set(quotes))
    # Doing well / to improve point at a card instead of quoting again.
    r = report["report"]
    assert r["well"] and r["improve"]
    for item in r["well"] + r["improve"]:
        assert item["anchor"] in {c["anchor"] for c in cards}
        assert item["see"] == next(c["q"] for c in cards if c["anchor"] == item["anchor"])


def test_mic_failure_after_start_turns_exam_into_typed_practice(monkeypatch):
    from app import interview_report
    bank = _packed_bank(("a", None, "Probability"))
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    monkeypatch.setattr(voice_routes, "provider", lambda: ScriptedProvider())
    client = TestClient(app)
    for begin, expected in (({}, "typed"), ({"typed_practice": True}, "typed")):
        with client.websocket_connect("/api/interview/ws") as socket:
            socket.send_json({"type": "begin", "consent": True, "pack": "quant", "level": "Easy", **begin})
            while (event := socket.receive_json())["type"] != "session":
                pass
            session_id = event["id"]
            while not ((event := socket.receive_json())["type"] == "state" and event["value"] == "listening"):
                pass
            socket.send_json({"type": "mic_failed"})
            socket.send_json({"type": "end"})
        session = interview_routes.SESSIONS[session_id]
        assert session.conditions == expected
        assert interview_report.build(session)["conditions"] == "Typed practice: not exam conditions"


# --- Topic selection: several topics at once ------------------------------------------

def _topic_bank(*specs):
    """specs: (template_id, topic, difficulty), all Quant."""
    from engine.bank import Bank
    templates = [parse_template(_raw_bag(template_id=tid, topic=topic, difficulty=level)) for tid, topic, level in specs]
    return Bank({t.template_id: t for t in templates})


TOPIC_SPECS = (("p1", "Probability", "Easy"), ("p2", "Probability", "Medium"), ("p3", "Probability", "Hard"),
               ("c1", "Counting", "Easy"), ("c2", "Counting", "Medium"), ("c3", "Counting", "Hard"),
               ("s1", "Statistics", "Easy"), ("s2", "Statistics", "Medium"), ("s3", "Statistics", "Hard"))


def test_multi_topic_draws_stay_inside_the_selection():
    bank = _topic_bank(*TOPIC_SPECS)
    assert {t.template_id for t in bank.pool(["Probability", "Counting"])} == {"p1", "p2", "p3", "c1", "c2", "c3"}
    assert bank.pool(("Statistics",)) == bank.pool("Statistics")
    for seed in range(30):
        rng = random.Random(seed)
        source = BankSource(bank, ["Probability", "Counting"], "Easy", rng=rng)
        drawn = []
        while source.candidates():
            drawn.append(source.new(source.candidates()[0]).template_id)
            source.step(rng.choice([Outcome.CORRECT, Outcome.NAMED_WRONG]))
        assert sorted(drawn) == ["c1", "c2", "c3", "p1", "p2", "p3"]  # every one, and nothing from Statistics


def test_ladder_uses_the_union_at_the_current_level_then_the_nearest_level():
    bank = _topic_bank(*TOPIC_SPECS)
    source = BankSource(bank, ["Probability", "Counting"], "Medium", rng=random.Random(1))
    first = source.new(source.candidates()[0])
    assert first.template_id in {"p2", "c2"}  # the level asked, from either selected topic
    source.step(Outcome.CORRECT)
    assert source.candidates()[0] in {"p3", "c3"}
    # Only Hard questions selected, starting at Easy: the nearest level within the selection.
    hard = _topic_bank(("p3", "Probability", "Hard"), ("c3", "Counting", "Hard"), ("s1", "Statistics", "Easy"))
    source = BankSource(hard, ["Probability", "Counting"], "Easy", rng=random.Random(2))
    assert source.candidates()[0] in {"p3", "c3"}  # never Statistics, though it has an Easy one
    # Medium wanted, Easy and Hard selected: a tie goes to the easier level.
    mixed = _topic_bank(("p1", "Probability", "Easy"), ("c3", "Counting", "Hard"))
    assert BankSource(mixed, ["Probability", "Counting"], "Medium", rng=random.Random(3)).candidates() == ["p1"]


def test_begin_takes_a_list_of_topics_a_single_topic_or_none(monkeypatch):
    bank = _topic_bank(*TOPIC_SPECS)
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    pool = lambda topic: set(interview_routes.interview_for("quant", topic, "Easy").source.templates)
    assert pool(["Probability", "Counting"]) == {"p1", "p2", "p3", "c1", "c2", "c3"}
    assert pool("Statistics") == {"s1", "s2", "s3"}
    assert pool(None) == pool("Mixed") == {t for t, _, _ in TOPIC_SPECS}
    for bad in (["Probability", "Valuation"], "Valuation", [], ["Probability", 3], ["fraud"], "fraud"):
        with pytest.raises(VoiceError):
            interview_routes.interview_for("quant", bad, "Easy")
    assert interview_routes.topic_label("quant", ["Counting", "Probability"]) == "Counting, Probability"
    assert interview_routes.topic_label("quant", ["Counting", "Probability", "Statistics"]) == "All topics"
    assert interview_routes.topic_label("quant", None) == "All topics"


def test_report_header_lists_the_selected_topics(monkeypatch):
    bank = _topic_bank(*TOPIC_SPECS)
    monkeypatch.setattr(interview_routes, "_BANK", bank)
    monkeypatch.setattr(voice_routes, "provider", lambda: ScriptedProvider())
    client = TestClient(app)
    for topics, label in ((["Probability", "Counting"], "Probability, Counting"), (None, "All topics")):
        with client.websocket_connect("/api/interview/ws") as socket:
            socket.send_json({"type": "begin", "consent": True, "pack": "quant", "topics": topics, "level": "Easy"})
            while (event := socket.receive_json())["type"] != "question":
                if event["type"] == "session":
                    session_id = event["id"]
            assert event["topic"] in (topics or ["Probability", "Counting", "Statistics"])
            socket.send_json({"type": "end"})
        assert interview_report.build(interview_routes.SESSIONS[session_id])["topics"] == label
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True, "pack": "quant", "topics": ["Valuation"], "level": "Easy"})
        assert socket.receive_json() == {"type": "error", "message": "Choose topics from this track."}
