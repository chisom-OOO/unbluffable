"""Exam Room session controller with fake listeners and analysers (no network)."""

import asyncio
from fractions import Fraction

import pytest
from fastapi.testclient import TestClient

from app import exam_text as say
from app import voice_routes
from app.interview_session import Analysis, ExamSession, context_for, numbers_in
from app.main import app
from engine.answers import parse_number
from engine.coding import code_answer
from engine.interview import Interview
from engine.labels import Label
from engine.templates import flagship, flagship_twin
from voice.recording import VoiceError
from voice.schemas import CONTEXT

Q1_OPEN = "So if a transaction gets flagged, it's about 90 percent likely to be fraud."
Q1_STUCK = "I'm not sure how to count the genuine ones."
Q1_RIGHT = ("So 20 are fraud and 18 of those get flagged. 1,980 are genuine and 99 get flagged. "
            "That's 18 out of 117.")
Q2_RIGHT = "40 are fraud and 36 get flagged; 1,960 genuine and 98 flagged, so 36 out of 134, 18 out of 67."


class FakeAnalyzer:
    """Codes answers from a table: text -> (committed number text or None, reasoning code)."""

    def __init__(self, table, fail=()):
        self.table, self.fail, self.calls = table, set(fail), []

    async def analyse(self, puzzle, text, send):
        self.calls.append((puzzle, text))
        if text in self.fail:
            return Analysis(None)
        number, code = self.table.get(text, (None, "vague"))
        stated = parse_number(number) if number else None
        return Analysis(code_answer(puzzle, stated, code), stated, number)


def run_session(answers, table, fail=(), deadline=None, clock=None):
    events, queue = [], list(answers)

    async def send(event):
        events.append(event)

    async def listen():
        if not queue:
            raise AssertionError("the session asked for more answers than the test gave")
        return queue.pop(0)

    analyzer = FakeAnalyzer(table, fail)
    kw = {"deadline": deadline} | ({"clock": clock} if clock else {})
    session = ExamSession(send, listen, analyzer, Interview(demo=True), **kw)
    asyncio.run(session.run())
    assert not queue, f"unused answers: {queue}"
    return session, events


def lines(events, kind=None):
    return [e for e in events if e["type"] == "interviewer_line" and (kind is None or e["kind"] == kind)]


def test_flagship_then_twin_right_first_time():
    session, events = run_session(
        [Q1_RIGHT, Q2_RIGHT],
        {Q1_RIGHT: ("18 out of 117", "valid"), Q2_RIGHT: ("18 out of 67", "valid")},
    )
    questions = [e for e in events if e["type"] == "question"]
    assert [(q["number"], q["kind"], q["guide_seconds"]) for q in questions] == [(1, "new", 120), (2, "twin", 60)]
    assert questions[0]["text"] == say.puzzle_text(flagship())
    assert "2,000" not in questions[0]["text"] and "Out of" not in questions[0]["text"]  # decision log 9
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
    session, events = run_session(
        [Q1_OPEN, Q1_STUCK, Q1_RIGHT, Q2_RIGHT],
        {Q1_OPEN: ("90 percent", "misconception"), Q1_RIGHT: ("18 out of 117", "valid"),
         Q2_RIGHT: ("18 out of 67", "valid")},
    )
    challenge = lines(events, "challenge")
    assert [c["text"] for c in challenge] == [
        "You said 90 percent. Is that the chance a flag is fraud, or the chance fraud gets flagged?"]
    nudge = lines(events, "nudge")
    # Position 0, so the nudge targets step 1 and brings in the round population (strength 1).
    assert [(n["target_step"], n["text"]) for n in nudge] == [(1, "Picture 2,000 transactions. How many of them are fraudulent?")]
    q1 = session.questions[0]
    assert (q1.challenges, q1.nudges, q1.hints, q1.help_load) == (1, 1, 0, 1)
    assert q1.recovered is True and q1.weight == Fraction(2, 4)  # 2/(2 + H + 1), H = 1
    assert q1.scored == "correct"
    assert session.interview.help_loads == [1, 0]
    assert session.interview.label is Label.SUPPORTS


def test_not_recovered_scores_the_first_wrong_answer_undiscounted():
    wrong = ["It's 90%.", "Still 90%.", "I'd say 90%.", "90%.", "Final answer 90%."]
    twin = ["90% again.", "90%.", "90%.", "90%.", "90%, final."]
    table = {t: ("90%", "misconception") for t in wrong + twin}
    session, events = run_session(wrong + twin, table)
    q1, q2 = session.questions
    assert (q1.challenges, q1.nudges, q1.recovered, q1.scored, q1.weight) == (1, 3, False, "named_wrong", 1)
    assert q2.scored == "named_wrong"
    assert session.interview.label is Label.MISCONCEPTION
    assert float(session.interview.posterior["M"]) == pytest.approx(0.910, abs=0.002)
    assert [e["text"] for e in lines(events, "close")][:2] == [say.NOT_RECOVERED_CLOSE] * 2


def test_help_request_asks_then_hints_and_counts_the_hint():
    ask = "Can I get a hint?"
    reply = "I don't know where to start."
    session, events = run_session(
        [ask, reply, Q1_RIGHT, Q2_RIGHT],
        {Q1_RIGHT: ("18 out of 117", "valid"), Q2_RIGHT: ("18 out of 67", "valid")},
    )
    assert lines(events, "prompt")[0]["text"] == say.HELP_ASK
    hint = lines(events, "hint")
    assert [(h["target_step"], h["counts"]["hints"]) for h in hint] == [(1, 1)]
    q1 = session.questions[0]
    assert (q1.hints, q1.help_load, q1.recovered, q1.weight) == (1, 1, False, Fraction(2, 3))  # 2/(2 + H)


def test_clarifying_question_repeats_the_puzzle_for_free():
    clarify = "Could you repeat the question?"
    session, events = run_session(
        [clarify, Q1_RIGHT, Q2_RIGHT],
        {Q1_RIGHT: ("18 out of 117", "valid"), Q2_RIGHT: ("18 out of 67", "valid")},
    )
    repeat = lines(events, "question")[1]
    assert repeat["text"].startswith(say.REPEAT_INTRO)
    assert session.questions[0].weight == 1


def test_no_to_offered_help_costs_nothing():
    session, _ = run_session(
        ["No thanks.", Q1_RIGHT, Q2_RIGHT],
        {Q1_RIGHT: ("18 out of 117", "valid"), Q2_RIGHT: ("18 out of 67", "valid")},
    )
    assert session.questions[0].weight == 1 and len(session.questions[0].answers) == 1


def test_unchecked_answer_asks_again_without_a_round():
    session, events = run_session(
        ["garbled", Q1_RIGHT, Q2_RIGHT],
        {Q1_RIGHT: ("18 out of 117", "valid"), Q2_RIGHT: ("18 out of 67", "valid")},
        fail={"garbled"},
    )
    assert lines(events, "prompt")[0]["text"] == say.UNCHECKED
    assert session.questions[0].weight == 1 and session.questions[0].challenges == 0


def test_right_number_without_reasoning_is_asked_why():
    bare = "It's 2/13."
    session, events = run_session(
        [bare, Q1_RIGHT, Q2_RIGHT],
        {bare: ("2/13", "vague"), Q1_RIGHT: ("18 out of 117", "valid"), Q2_RIGHT: ("18 out of 67", "valid")},
    )
    assert lines(events, "challenge")[0]["text"] == say.ASK_WHY
    assert session.questions[0].weight == Fraction(2, 3)  # recovered, H = 0: 2/(2 + 0 + 1)


def test_time_up_finishes_the_current_question_then_closes():
    # The clock is already past the deadline: question 1 still runs to its end.
    session, events = run_session([Q1_RIGHT], {Q1_RIGHT: ("18 out of 117", "valid")}, deadline=10, clock=lambda: 11.0)
    assert session.timed_out and len(session.questions) == 1
    assert lines(events, "close")[-1]["text"] == say.TIME_CLOSE
    assert events[-1]["timed_out"] is True


def test_context_for_the_flagship_is_unchanged_and_the_twin_has_its_own_rate():
    assert context_for(flagship()) == CONTEXT
    assert "2% fraud" in context_for(flagship_twin())


def test_numbers_in_reads_spoken_and_written_counts():
    assert numbers_in("So twenty are fraud and 1,980 are genuine, 18 out of 117") == [20, 1980, 18, 117]


# --- The socket, end to end with a fake provider (typed answers) ------------


class FakeProvider:
    mode = "live"

    def __init__(self):
        self.prompts = []

    async def structured(self, text, kind, effort, schema, prompt):
        self.prompts.append((kind, prompt))
        number = "18 out of 117" if "117" in text else "18 out of 67" if "67" in text else "90 percent"
        if kind == "minimal":
            return {"committed_number_text": number, "is_commitment": True}, {"model": "fake"}
        code = "misconception" if number == "90 percent" else "valid"
        quotes = [{"quote": text, "step": "posterior"}]
        return {"committed_answer_text": number, "reasoning_quotes": quotes, "reasoning_code": code,
                "misconception_name": "none", "self_corrected": False}, {"model": "fake"}


def drain(socket, until):
    seen = []
    while True:
        event = socket.receive_json()
        seen.append(event)
        if event["type"] in until:
            return seen


def test_socket_runs_flagship_and_twin_with_typed_answers(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(voice_routes, "provider", lambda: provider)
    client = TestClient(app)
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        seen = drain(socket, {"state"})
        assert seen[0]["type"] == "session" and seen[0]["id"] and seen[0]["session_seconds"] == 600
        assert [e["type"] for e in seen[1:]] == ["question", "interviewer_line", "state"]
        socket.send_json({"type": "typed", "transcript": Q1_OPEN})
        seen = drain(socket, {"state"})
        seen += drain(socket, {"state"})  # checking, then listening after the challenge
        assert any(e.get("kind") == "challenge" for e in seen)
        socket.send_json({"type": "typed", "transcript": Q1_RIGHT})
        seen = drain(socket, {"state"})
        seen += drain(socket, {"state"})
        assert any(e["type"] == "question" and e["kind"] == "twin" for e in seen)
        socket.send_json({"type": "typed", "transcript": Q2_RIGHT})
        seen = drain(socket, {"session_end"})
        assert seen[-1]["label"] == Label.SUPPORTS.value
    assert {kind for kind, _ in provider.prompts} == {"minimal", "extraction"}
    assert any("2% fraud" in prompt for _, prompt in provider.prompts)  # the twin's own context


def test_socket_needs_consent(monkeypatch):
    monkeypatch.setattr(voice_routes, "provider", lambda: FakeProvider())
    client = TestClient(app)
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": False})
        event = socket.receive_json()
        assert event["type"] == "error" and "answer text is kept" in event["message"]


def test_socket_voice_capture_uses_the_realtime_relay(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(voice_routes, "provider", lambda: provider)
    answers = [Q1_RIGHT, Q2_RIGHT]
    starts = []

    async def capture(socket, current, start, *args):
        starts.append(start)
        return answers.pop(0), {"model": "fake-asr"}

    from app import interview_routes
    monkeypatch.setattr(interview_routes, "realtime_answer", capture)
    client = TestClient(app)
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        drain(socket, {"state"})
        socket.send_json({"type": "capture", "sample_rate": 16000, "headphones": False, "interviewer_speaking": True})
        drain(socket, {"state"}); drain(socket, {"state"})
        socket.send_json({"type": "capture", "sample_rate": 16000, "headphones": True, "interviewer_speaking": False})
        seen = drain(socket, {"session_end"})
        assert seen[-1]["label"] == Label.SUPPORTS.value
    assert [s["type"] for s in starts] == ["start", "start"] and starts[0]["hands_free"] is True
    assert starts[1]["headphones"] is True


def test_socket_capture_error_returns_to_listening(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(voice_routes, "provider", lambda: provider)
    calls = []

    async def capture(socket, current, start, *args):
        calls.append(1)
        if len(calls) == 1:
            raise VoiceError("No intelligible speech was found. Try again or type an answer.")
        return Q1_RIGHT, {}

    from app import interview_routes
    monkeypatch.setattr(interview_routes, "realtime_answer", capture)
    client = TestClient(app)
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        drain(socket, {"state"})
        socket.send_json({"type": "capture"})
        seen = drain(socket, {"state"})
        assert seen[0]["type"] == "error" and seen[-1] == {"type": "state", "value": "listening"}
        socket.send_json({"type": "capture"})
        seen = drain(socket, {"answer_complete"})
        assert seen[-1]["transcript"] == Q1_RIGHT


# --- Leak guard and written help (spec/01, decision log 3a) -----------------

from app.interview_session import leak  # noqa: E402


@pytest.mark.parametrize("text, reason", [
    ("Which transactions get flagged, apart from the fraudulent ones?", None),
    ("Picture 2,000 transactions. How many of them are fraudulent?", None),  # round population
    ("The detector flags 90% of fraud and 5% of genuine ones. What does that tell you?", None),  # givens
    ("You said 20 are fraud. How many of those get flagged?", None),  # candidate's own number
    ("So it's 2/13, right?", "answer"),
    ("That would be 18 out of 117.", "answer"),
    ("Is it about 15%?", "answer"),
    ("How many of the 99 genuine flagged ones are there?", "new number 99"),
    ("Try 1,000 transactions instead.", "new number 1000"),
])
def test_leak_guard(text, reason):
    assert leak(flagship(), text, said=[Fraction(20)], population=None) == reason


def run_with_writer(writer, answers, table):
    events, queue = [], list(answers)

    async def send(event):
        events.append(event)

    async def listen():
        return queue.pop(0)

    session = ExamSession(send, listen, FakeAnalyzer(table), Interview(demo=True), writer=writer)
    asyncio.run(session.run())
    return session, events


def test_written_nudge_is_used_and_code_computes_its_strength():
    seen = []

    async def writer(puzzle, kind, said, at):
        seen.append((kind, said[-1], at))
        return "Which transactions get flagged, apart from the fraudulent ones?", 4

    session, events = run_with_writer(
        writer, [Q1_OPEN, Q1_STUCK, Q1_RIGHT, Q2_RIGHT],
        {Q1_OPEN: ("90 percent", "misconception"), Q1_RIGHT: ("18 out of 117", "valid"),
         Q2_RIGHT: ("18 out of 67", "valid")},
    )
    assert seen == [("nudge", Q1_STUCK, 0)]
    nudge = lines(events, "nudge")[0]
    assert (nudge["text"], nudge["target_step"]) == ("Which transactions get flagged, apart from the fraudulent ones?", 4)
    q1 = session.questions[0]
    assert q1.help_load == 4 and q1.weight == Fraction(2, 7)  # 2/(2 + 4 + 1)


def test_leaking_draft_falls_back_to_the_plain_step_prompt():
    async def writer(puzzle, kind, said, at):
        return "It's 18 out of 117, isn't it?", 6

    session, events = run_with_writer(
        writer, [Q1_OPEN, Q1_STUCK, Q1_RIGHT, Q2_RIGHT],
        {Q1_OPEN: ("90 percent", "misconception"), Q1_RIGHT: ("18 out of 117", "valid"),
         Q2_RIGHT: ("18 out of 67", "valid")},
    )
    nudge = lines(events, "nudge")[0]
    assert (nudge["target_step"], nudge["text"]) == (1, "Picture 2,000 transactions. How many of them are fraudulent?")
    assert session.questions[0].help_load == 1
