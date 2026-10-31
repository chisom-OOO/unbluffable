"""Exam Room session controller on a forge quant family (the bag: P(red) = r / (r + 11)),
with the scripted fake model from test_bank_runtime (no network)."""

import asyncio
import random
import re
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app import exam_text as say
from app import interview_report, interview_routes, voice_routes
from app.interview_session import Analysis, ExamSession, VoiceAnalyzer, context_for, leak, numbers_in
from app.main import app
from engine.bank import Bank, BankSource, instance_puzzle, parse_template
from engine.help import strength
from engine.interview import Interview
from engine.labels import Label
from test_bank_runtime import OTHER_COLOUR, ScriptedProvider, _raw_bag
from voice.recording import VoiceError

# Without 11 red and 11 blue, where "the other colour" (11/22) would be the right answer.
_RAW = _raw_bag(n=21)
_RAW["instances"] = [row for row in _RAW["instances"] if row["params"]["red"] != 11]
BAG = parse_template(_RAW)


def bag_bank():
    return Bank({BAG.template_id: BAG})


def red(puzzle):
    return puzzle.params["red"]


# What the candidate says, for the current question. "right" commits to the exact value with
# reasoning; "other" to the named wrong value (the other colour); "bare" to the exact value with none.
def say_as(role, puzzle):
    r = red(puzzle)
    return {
        "right": f"My answer is {r}/{r + 11}, because red over all balls.",
        "other": f"My answer is 11/{r + 11}, because blue over all balls.",
        "bare": f"My answer is {r}/{r + 11}, because",
        "stuck": "I'm not sure what to count.",
        "hint": "Can I get a hint?",
        "idk": "I don't know where to start.",
        "clarify": "Could you repeat the question?",
        "no": "No thanks.",
        "garbled": "garbled",
    }[role]


class Analyzer(VoiceAnalyzer):
    """The real analyser on the scripted model; "garbled" can't be checked."""

    async def analyse(self, puzzle, text, send):
        if text == "garbled":
            return Analysis(None)
        return await super().analyse(puzzle, text, send)


def run_session(roles, deadline=None, clock=None, writer=None):
    events, queue, said = [], list(roles), []

    async def send(event):
        events.append(event)

    async def listen():
        if not queue:
            raise AssertionError("the session asked for more answers than the test gave")
        text = say_as(queue.pop(0), session.questions[-1].puzzle)
        said.append(text)
        return text

    kw = {"deadline": deadline} | ({"clock": clock} if clock else {})
    source = BankSource(bag_bank(), "Probability", "Easy", rng=random.Random(1))
    session = ExamSession(send, listen, Analyzer(ScriptedProvider()), Interview(rng=random.Random(5), source=source),
                          writer=writer, **kw)
    asyncio.run(session.run())
    assert not queue, f"unused answers: {queue}"
    return session, events


def lines(events, kind=None):
    return [e for e in events if e["type"] == "interviewer_line" and (kind is None or e["kind"] == kind)]


def frac(x):
    return f"{x.numerator}/{x.denominator}"


def test_question_then_twin_right_first_time():
    session, events = run_session(["right", "right"])
    questions = [e for e in events if e["type"] == "question"]
    assert [(q["number"], q["kind"], q["guide_seconds"]) for q in questions] == [(1, "new", 120), (2, "twin", 60)]
    q1, q2 = session.questions
    assert questions[0]["text"] == say.puzzle_text(q1.puzzle) == q1.puzzle.text
    assert q1.puzzle.template_id == q2.puzzle.template_id and q1.puzzle.instance != q2.puzzle.instance
    assert session.interview.label is Label.SUPPORTS
    assert [q.weight for q in session.questions] == [1, 1]
    assert events[-1] == {"type": "session_end", "label": Label.SUPPORTS.value, "timed_out": False}
    assert lines(events, "close")[-1]["text"] == say.SESSION_CLOSE
    # A neutral acknowledgement before every check, then "checking".
    acks = [e["acknowledgement"] for e in events if e["type"] == "answer_complete"]
    assert acks == ["Got it.", "Understood."]
    i = next(i for i, e in enumerate(events) if e["type"] == "answer_complete")
    assert events[i + 1] == {"type": "state", "value": "checking"}


def test_recovered_after_challenge_and_one_nudge_is_discounted():
    session, events = run_session(["other", "stuck", "right", "right"])
    q1 = session.questions[0]
    r = red(q1.puzzle)
    assert [c["text"] for c in lines(events, "challenge")] == [
        f"You said 11/{r + 11}. Can you walk me through how you got there?"]
    # Position 0, so the nudge asks for the first solution-map step by name (strength 1).
    assert [(n["target_step"], n["text"]) for n in lines(events, "nudge")] == [(1, say.forge_step_prompt("balls"))]
    assert (q1.challenges, q1.nudges, q1.hints, q1.help_load) == (1, 1, 0, 1)
    assert q1.recovered is True and q1.weight == Fraction(2, 4)  # 2/(2 + H + 1), H = 1
    assert q1.scored == "correct"
    assert session.interview.help_loads == [1, 0]
    assert session.interview.label is Label.SUPPORTS


def test_not_recovered_scores_the_first_wrong_answer_undiscounted():
    session, events = run_session(["other"] * 10)
    q1, q2 = session.questions
    assert (q1.challenges, q1.nudges, q1.recovered, q1.scored, q1.weight) == (1, 3, False, "named_wrong", 1)
    assert q2.scored == "named_wrong"
    assert session.interview.label is Label.MISCONCEPTION
    assert [e["text"] for e in lines(events, "close")][:2] == [say.NOT_RECOVERED_CLOSE] * 2


def test_help_request_asks_then_hints_and_counts_the_hint():
    session, events = run_session(["hint", "idk", "right", "right"])
    assert lines(events, "prompt")[0]["text"] == say.HELP_ASK
    assert [(h["target_step"], h["counts"]["hints"]) for h in lines(events, "hint")] == [(1, 1)]
    q1 = session.questions[0]
    assert (q1.hints, q1.help_load, q1.recovered, q1.weight) == (1, 1, False, Fraction(2, 3))  # 2/(2 + H)


def test_clarifying_question_repeats_the_puzzle_for_free():
    session, events = run_session(["clarify", "right", "right"])
    assert lines(events, "question")[1]["text"].startswith(say.REPEAT_INTRO)
    assert session.questions[0].weight == 1


def test_no_to_offered_help_costs_nothing():
    session, _ = run_session(["no", "right", "right"])
    assert session.questions[0].weight == 1 and len(session.questions[0].answers) == 1


def test_unchecked_answer_asks_again_without_a_round():
    session, events = run_session(["garbled", "right", "right"])
    assert lines(events, "prompt")[0]["text"] == say.UNCHECKED
    assert session.questions[0].weight == 1 and session.questions[0].challenges == 0


def test_right_number_without_reasoning_is_asked_why():
    session, events = run_session(["bare", "right", "right"])
    assert lines(events, "challenge")[0]["text"] == say.ASK_WHY
    assert session.questions[0].weight == Fraction(2, 3)  # recovered, H = 0: 2/(2 + 0 + 1)


def test_time_up_finishes_the_current_question_then_closes():
    # The clock is already past the deadline: question 1 still runs to its end.
    session, events = run_session(["right"], deadline=10, clock=lambda: 11.0)
    assert session.timed_out and len(session.questions) == 1
    assert lines(events, "close")[-1]["text"] == say.TIME_CLOSE
    assert events[-1]["timed_out"] is True


def test_context_is_each_puzzles_own_text():
    first, other = (instance_puzzle(BAG, BAG.instances[i], i) for i in (0, 5))
    assert context_for(first).startswith(f"The question asks: {first.text} ")
    assert first.text not in context_for(other) and other.text in context_for(other)
    with pytest.raises(TypeError):
        context_for(object())


def test_numbers_in_reads_spoken_and_written_counts():
    assert numbers_in("So twenty are red and 1,980 are blue, 18 out of 117") == [20, 1980, 18, 117]


# --- The socket, end to end with the scripted model (typed answers) ---------


@pytest.fixture
def bag_routes(monkeypatch):
    provider = ScriptedProvider()
    monkeypatch.setattr(interview_routes, "_BANK", bag_bank())
    monkeypatch.setattr(voice_routes, "provider", lambda: provider)
    return provider


def drain(socket, until):
    seen = []
    while True:
        event = socket.receive_json()
        seen.append(event)
        if event["type"] in until:
            return seen


RED = re.compile(r"has (\d+) red")


def typed(question_text, role):
    r = int(RED.search(question_text)[1])
    return say_as(role, type("P", (), {"params": {"red": r}})())


def test_socket_runs_question_and_twin_with_typed_answers(bag_routes):
    client = TestClient(app)
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        seen = drain(socket, {"state"})
        assert seen[0]["type"] == "session" and seen[0]["id"] and seen[0]["session_seconds"] == 600
        assert [e["type"] for e in seen[1:]] == ["question", "interviewer_line", "state"]
        first = seen[1]["text"]
        socket.send_json({"type": "typed", "transcript": typed(first, "other")})
        seen = drain(socket, {"state"})
        seen += drain(socket, {"state"})  # checking, then listening after the challenge
        assert any(e.get("kind") == "challenge" for e in seen)
        socket.send_json({"type": "typed", "transcript": typed(first, "right")})
        seen = drain(socket, {"state"})
        seen += drain(socket, {"state"})
        twin = next(e for e in seen if e["type"] == "question" and e["kind"] == "twin")
        socket.send_json({"type": "typed", "transcript": typed(twin["text"], "right")})
        seen = drain(socket, {"session_end"})
        assert seen[-1]["label"] == Label.SUPPORTS.value
    assert {kind for kind, _ in bag_routes.prompts} == {"minimal", "extraction"}
    assert any(twin["text"] in prompt for _, prompt in bag_routes.prompts)  # the twin's own context


def test_socket_needs_consent(bag_routes):
    with TestClient(app).websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": False})
        event = socket.receive_json()
        assert event["type"] == "error" and "answer text is kept" in event["message"]


def test_socket_voice_capture_uses_the_realtime_relay(bag_routes, monkeypatch):
    starts, current = [], {}

    async def capture(socket, provider, start, *args, **kwargs):
        starts.append(start)
        return typed(current["text"], "right"), {"model": "fake-asr"}

    monkeypatch.setattr(interview_routes, "realtime_answer", capture)
    with TestClient(app).websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        current["text"] = next(e for e in drain(socket, {"state"}) if e["type"] == "question")["text"]
        socket.send_json({"type": "capture", "sample_rate": 16000, "headphones": False, "interviewer_speaking": True})
        seen = drain(socket, {"state"}) + drain(socket, {"state"})
        current["text"] = next(e for e in seen if e["type"] == "question")["text"]
        socket.send_json({"type": "capture", "sample_rate": 16000, "headphones": True, "interviewer_speaking": False})
        seen = drain(socket, {"session_end"})
        assert seen[-1]["label"] == Label.SUPPORTS.value
    assert [s["type"] for s in starts] == ["start", "start"] and starts[0]["hands_free"] is True
    assert starts[1]["headphones"] is True


def test_socket_capture_error_returns_to_listening(bag_routes, monkeypatch):
    calls, current = [], {}

    async def capture(socket, provider, start, *args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise VoiceError("No intelligible speech was found. Try again or type an answer.")
        return typed(current["text"], "right"), {}

    monkeypatch.setattr(interview_routes, "realtime_answer", capture)
    with TestClient(app).websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        current["text"] = next(e for e in drain(socket, {"state"}) if e["type"] == "question")["text"]
        socket.send_json({"type": "capture"})
        seen = drain(socket, {"state"})
        assert seen[0]["type"] == "error" and seen[-1] == {"type": "state", "value": "listening"}
        socket.send_json({"type": "capture"})
        seen = drain(socket, {"answer_complete"})
        assert seen[-1]["transcript"] == typed(current["text"], "right")


# --- Leak guard and written help (spec/01, decision log 3a) -----------------

FIRST = instance_puzzle(BAG, BAG.instances[0], 0)  # 2 red, 11 blue: 2/13 ≈ 15.4%


@pytest.mark.parametrize("text, reason", [
    ("How many balls are there in total?", None),
    ("There are 2 red and 11 blue. What does that tell you?", None),  # givens
    ("You said 20. What did you divide by?", None),  # the candidate's own number
    ("So it's 2/13, right?", "answer"),
    ("That would be 2 out of 13.", "answer"),
    ("Is it about 15%?", "answer"),
    ("How many of the 99 blue ones are there?", "new number 99"),
    ("Try 1,000 balls instead.", "new number 1000"),
])
def test_leak_guard(text, reason):
    assert leak(FIRST, text, said=[Fraction(20)], population=None) == reason


def test_written_nudge_is_used_and_code_computes_its_strength():
    seen = []

    async def writer(puzzle, kind, said, at):
        seen.append((kind, said[-1], at))
        return "What share of all the balls are red?", 2

    session, events = run_session(["other", "stuck", "right", "right"], writer=writer)
    assert seen == [("nudge", "I'm not sure what to count.", 0)]
    nudge = lines(events, "nudge")[0]
    assert (nudge["text"], nudge["target_step"]) == ("What share of all the balls are red?", 2)
    q1 = session.questions[0]
    assert q1.help_load == strength(2, 0) == 2 and q1.weight == Fraction(2, 5)  # 2/(2 + 2 + 1)


def test_leaking_draft_falls_back_to_the_plain_step_prompt():
    async def writer(puzzle, kind, said, at):
        return f"It's {red(puzzle)} out of {red(puzzle) + 11}, isn't it?", 2

    session, events = run_session(["other", "stuck", "right", "right"], writer=writer)
    nudge = lines(events, "nudge")[0]
    assert (nudge["target_step"], nudge["text"]) == (1, say.forge_step_prompt("balls"))
    assert session.questions[0].help_load == 1


# --- The in-app report (decision log 8) -------------------------------------


def test_report_uses_only_recorded_values():
    session, _ = run_session(["other", "stuck", "right", "right"])
    q1, q2 = session.questions
    r1, r2 = red(q1.puzzle), red(q2.puzzle)
    report = interview_report.build(session)
    assert report["label"] == "supports" and report["misconception"] is None  # named only for "Misconception detected"
    assert report["questions"] == 2 and report["level"] == 1
    assert [{k: v for k, v in c.items() if k != "receipt"} for c in report["checks"]] == [
        {"q": "Question 1", "said": f"11/{r1 + 11}, then {r1}/{r1 + 11}", "exact": interview_report.exact_value(q1.puzzle)},
        {"q": "Question 2 (twin)", "said": f"{r2}/{r2 + 11}", "exact": interview_report.exact_value(q2.puzzle)},
    ]
    assert [o["text"] for o in report["outcomes"]] == ["Recovered after the challenge and 1 nudge", "Right, no help"]
    assert (report["challenges"], report["nudges"], report["hints"]) == (1, 1, [])
    assert [t["tab"] for t in report["report"]["breakdown"]] == ["Question 1", "Question 2 (twin)"]
    q1_items = report["report"]["breakdown"][0]["items"]
    assert q1_items[0]["number"] == {"said": f"11/{r1 + 11}", "exact": interview_report.exact_value(q1.puzzle)}
    assert q1_items[0]["quote"] == say_as("other", q1.puzzle)
    assert q1_items[-1]["number"]["said"] == f"{r1}/{r1 + 11}"
    assert [e["label"] for e in report["estimate"]] == ["Sound (S)", "Misconception (M)", "Gap (G)"]
    assert report["estimate"][0]["p"] == f"{float(session.interview.posterior['S']):.3f}"
    assert report["tip"] == interview_report.FORGE_TIP

    # Never invent numbers: every number comes from the questions, the candidate's words,
    # the exact values, the help counts, the times or the model estimates.
    from app.exam_text import value
    recorded = numbers([q.puzzle.text for q in session.questions] + [a.transcript for q in session.questions for a in q.answers]
                       + [interview_report.exact_value(q.puzzle) for q in session.questions]
                       + [value(Fraction(a.stated)) for q in session.questions for a in q.answers if a.stated is not None]
                       + [value(nv.value) for q in session.questions for nv in q.puzzle.named_values]
                       + [value(x) for q in session.questions if q.puzzle.diagnostic  # "Why these numbers?"
                          for x in (q.puzzle.diagnostic.correct, q.puzzle.diagnostic.wrong)])
    # rating_items carry the engine's weight times the difficulty cap (decision log 23).
    extra = (numbers(without_receipts(report)) - recorded - numbers(report["estimate"]) - numbers(report["rating_items"])
             - numbers([report["times"], [b["sub"] for b in report["report"]["breakdown"]]]) - {"0", "1", "2", "3", "4"})
    assert extra == set()
    # Receipts show the exact computation: numbers from the candidate's words or the engine's
    # exact values, gaps, tolerance and help weight.
    computed = set()
    for q in session.questions:
        targets = [q.puzzle.answer] + [nv.value for nv in q.puzzle.named_values]
        stated = [Fraction(a.stated) for a in q.answers if a.stated is not None]
        computed |= numbers([value(x) for x in targets + stated] + [a.transcript for a in q.answers])
        computed |= numbers([f"{float(abs(x - t)):.4g}" for x in stated for t in targets])
        computed |= numbers([q.help_load, value(q.weight)])
        if q.puzzle.diagnostic:  # the twin's "Why these numbers?": right, suspected and the gap between
            d = q.puzzle.diagnostic
            computed |= numbers([value(d.correct), value(d.wrong), value(abs(d.correct - d.wrong))])
    receipt_numbers = numbers(receipts_in(report))
    assert receipt_numbers and receipt_numbers - computed - {"0.01", "2", "1"} == set()  # tolerance; 2/(2+H+1)


def receipts_in(value):
    if isinstance(value, dict):
        return [v for k, v in value.items() if k == "receipt"] + [x for k, v in value.items() if k != "receipt" for x in receipts_in(v)]
    if isinstance(value, list):
        return [x for v in value for x in receipts_in(v)]
    return []


def without_receipts(value):
    if isinstance(value, dict):
        return {k: without_receipts(v) for k, v in value.items() if k != "receipt"}
    if isinstance(value, list):
        return [without_receipts(v) for v in value]
    return value


def numbers(value):
    return set(re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", repr(value)))


def test_report_names_the_misconception_only_for_that_label():
    session, _ = run_session(["other"] * 10)
    report = interview_report.build(session)
    assert report["label"] == "misconception" and report["misconception"] == OTHER_COLOUR
    assert [o["text"] for o in report["outcomes"]] == ["Not recovered", "Not recovered"]
    assert report["tip"] == interview_report.FORGE_TIP


def test_report_endpoint(bag_routes):
    client = TestClient(app)
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        seen = drain(socket, {"state"})
        session_id, text = seen[0]["id"], next(e for e in seen if e["type"] == "question")["text"]
        while True:
            socket.send_json({"type": "typed", "transcript": typed(text, "right")})
            seen = drain(socket, {"state", "session_end"})
            if seen[-1]["type"] == "state" and seen[-1]["value"] == "checking":
                seen += drain(socket, {"state", "session_end"})
            if seen[-1]["type"] == "session_end":
                break
            text = next((e["text"] for e in seen if e["type"] == "question"), text)
    report = client.get(f"/api/interview/{session_id}/report")
    assert report.status_code == 200 and report.json()["label"] == "supports"
    assert client.get("/api/interview/nope/report").status_code == 404
    assert client.get("/ui/end").status_code == 200  # the page loads; without a session it says so


# --- Silence-prompt commitment check for the current puzzle ------------------


class ScriptedMinimal:
    """Fake minimal extraction: text -> (committed span, is_commitment); records each prompt."""
    mode = "live"

    def __init__(self, table):
        self.table, self.prompts = table, []

    async def structured(self, text, kind, effort, schema, prompt):
        self.prompts.append((kind, prompt))
        span, commit = self.table[text]
        return {"committed_number_text": span, "is_commitment": commit}, {"model": "fake"}


OTHER = instance_puzzle(BAG, BAG.instances[5], 5)  # 7 red, 11 blue: 7/18
COMMIT = "So that's 7 out of 18."
THINKING = "I'm still working out 7 out of 18."
UNSAID = "So that's 7 out of 18."  # the model's span must appear verbatim in the words


# The restated-given guard in voice/answers.py is worded for the retired fraud alert, so it
# is not exercised here.
@pytest.mark.parametrize("text, span, expected", [(COMMIT, "7 out of 18", True), (THINKING, "7 out of 18", False),
                                                  (UNSAID, "7/18", False)])
def test_silence_check_uses_the_current_puzzle(text, span, expected):
    provider = ScriptedMinimal({text: (span, text != THINKING)})
    assert asyncio.run(VoiceAnalyzer(provider).committed(OTHER, text)) is expected
    (kind, prompt), = provider.prompts
    assert kind == "minimal" and OTHER.text in prompt and FIRST.text not in prompt


def test_socket_passes_a_puzzle_aware_silence_check_to_the_relay(bag_routes, monkeypatch):
    checks, current = [], {}

    async def capture(socket, provider, start, *args, silence_check=None, **kwargs):
        bag_routes.prompts.clear()
        answer = typed(current["text"], "right")
        checks.append((await silence_check(answer), await silence_check("There are 11 blue balls."),
                       [prompt for kind, prompt in bag_routes.prompts], current["text"]))
        return answer, {"model": "fake-asr"}

    monkeypatch.setattr(interview_routes, "realtime_answer", capture)
    with TestClient(app).websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        current["text"] = next(e for e in drain(socket, {"state"}) if e["type"] == "question")["text"]
        socket.send_json({"type": "capture"})
        seen = drain(socket, {"state"}) + drain(socket, {"state"})
        current["text"] = next(e for e in seen if e["type"] == "question")["text"]
        socket.send_json({"type": "capture"})
        drain(socket, {"session_end"})
    (c1, g1, p1, t1), (c2, g2, p2, t2) = checks
    assert (c1, g1, c2, g2) == (True, False, True, False)
    assert t1 != t2 and all(t1 in p for p in p1) and all(t2 in p and t1 not in p for p in p2)
