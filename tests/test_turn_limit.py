"""Decision log 48: one time limit per turn, the same for every format. From the moment an
answer arrives, at 10 s the status says "Still checking your answer…"; at 30 s the room gives
up on that turn's model calls, says so, and listens again on the same question. A timed-out
attempt is no answer: not coded, no help load, never Correct. Done with nothing new said sends
the same words again. Fake models; the clock is shortened here (the real values are pinned)."""

import time

import pytest

import format_fakes as ff
from app import exam_text as say
from app import interview_routes, turn_limit
from app.main import app

STOPPED = "The interview stopped unexpectedly"
SLOW, GIVE_UP = 0.3, 0.9  # seconds in these tests


@pytest.fixture
def short(monkeypatch):
    monkeypatch.setattr(turn_limit, "SLOW_SECONDS", SLOW)
    monkeypatch.setattr(turn_limit, "GIVE_UP_SECONDS", GIVE_UP)


def types(out):
    return [e["type"] for e in out["events"]]


def session_of(out):
    return interview_routes.SESSIONS[next(e["id"] for e in out["events"] if e["type"] == "session")]


def after(out, kind):
    i = next(n for n, e in enumerate(out["events"]) if e["type"] == kind)
    return out["events"][i + 1:]


def slow_first(seconds, calls):
    """The first `calls` model calls of the answer check take `seconds`; later ones are quick."""
    state = {"n": 0}

    def delay(kind):
        if kind not in ("minimal", "extraction"):
            return 0
        state["n"] += 1
        return seconds if state["n"] <= calls else 0
    return delay


PROBABILITY = ff.CASES["quant trading: Probability"]


def test_the_limits_and_lines_are_pinned():
    assert turn_limit.SLOW_SECONDS == 10 and turn_limit.GIVE_UP_SECONDS == 30
    assert turn_limit.STILL_CHECKING == "Still checking your answer…"
    assert turn_limit.GAVE_UP == "That took too long on my side. Say your answer again when you're ready."


def test_at_10_s_the_status_says_still_checking_and_the_answer_is_still_checked(monkeypatch, short):
    models = ff.install(monkeypatch, ff.Universal(delay=slow_first(0.6, 2)))  # past 10 s, before 30 s
    out = ff.play(app, PROBABILITY, "right", "typed", answers=2)
    assert out["status"] in ("moving", "ended")
    slow = [e for e in out["events"] if e["type"] == "turn_slow"]
    assert slow and slow[0]["message"] == turn_limit.STILL_CHECKING
    assert "turn_timed_out" not in types(out) and models.cancelled == 0
    first = session_of(out).questions[0]
    assert first.scored == "correct" and first.help_load == 0


def test_a_quick_turn_says_nothing_extra(monkeypatch, short):
    ff.install(monkeypatch, ff.Universal())
    out = ff.play(app, PROBABILITY, "right", "typed", answers=2)
    assert "turn_slow" not in types(out) and "turn_timed_out" not in types(out)


def test_at_30_s_the_room_gives_up_says_so_and_listens_again_on_the_same_question(monkeypatch, short):
    models = ff.install(monkeypatch, ff.Universal(delay=60))  # every answer check hangs
    t0 = time.time()
    out = ff.play(app, PROBABILITY, "right", "typed", answers=2, watch=10)
    assert out["status"] == "moving", out["status"]
    gave_up = [e for e in out["events"] if e["type"] == "turn_timed_out"]
    assert gave_up and gave_up[0]["message"] == turn_limit.GAVE_UP
    assert models.cancelled >= 2  # both lanes of the first answer were cancelled, not left running
    rest = after(out, "turn_timed_out")
    assert [e["type"] for e in rest].index("state") is not None
    assert not any(e["type"] in ("question", "scored", "session_end") for e in rest[:rest.index(next(e for e in rest if e.get("value") == "listening"))])
    assert max(out["waits"]) < GIVE_UP + 2 and time.time() - t0 < 10
    q = session_of(out).questions[0]
    assert len(session_of(out).questions) == 1  # still the same question
    assert q.answers == [] and q.scored is None and q.help_load == 0 and q.hints == q.nudges == q.challenges == 0
    assert not any(e["type"] == "interviewer_line" and e["kind"] in ("close", "challenge", "nudge", "hint") for e in out["events"])


def test_the_retry_after_a_timeout_is_checked_as_the_only_answer(monkeypatch, short):
    ff.install(monkeypatch, ff.Universal(delay=slow_first(60, 2)))  # the first answer's two lanes hang
    words = {}

    def reply(n, q, events):
        if n == 2:
            words["retry"] = ff.answer_for("right", q)
            return words["retry"]
        return "My answer is 987654, because I guessed."  # a wrong first attempt that times out

    out = ff.play(app, PROBABILITY, "right", "typed", answers=3, reply=reply)
    assert "turn_timed_out" in types(out)
    q = session_of(out).questions[0]
    assert [a.transcript for a in q.answers] == [words["retry"]]  # the timed-out attempt is not an answer
    assert q.scored == "correct" and q.help_load == 0 and q.challenges == 0  # no challenge for the wrong attempt


def test_done_with_nothing_new_sends_the_same_words_again(monkeypatch, short):
    ff.install(monkeypatch, ff.Universal(delay=slow_first(60, 2)))
    first = {}

    def reply(n, q, events):
        if n == 1:
            first["words"] = ff.answer_for("right", q)
            return first["words"]
        if n == 2:
            return {"type": "resend"}
        return None

    out = ff.play(app, PROBABILITY, "right", "typed", answers=3, reply=reply)
    done = [e["transcript"] for e in out["events"] if e["type"] == "answer_complete"]
    assert done[:2] == [first["words"], first["words"]]
    q = session_of(out).questions[0]
    assert [a.transcript for a in q.answers] == [first["words"]] and q.scored == "correct"


def test_resend_without_a_timed_out_answer_is_ignored(monkeypatch, short):
    ff.install(monkeypatch, ff.Universal())
    out = ff.play(app, PROBABILITY, "right", "typed", answers=2,
                  reply=lambda n, q, events: {"type": "resend"} if n == 1 else None, watch=3)
    assert out["status"] == "STUCK"  # nothing to resend: the room keeps listening for an answer
    assert "answer_complete" not in types(out)


def test_voice_done_with_nothing_said_after_a_timeout_sends_the_same_words(monkeypatch, short):
    ff.install(monkeypatch, ff.Universal(delay=slow_first(60, 2)))
    first = {}

    def reply(n, q, events):
        if n == 1:
            first["words"] = ff.answer_for("right", q)
            return first["words"]
        return "" if n == 2 else None  # nothing heard: the capture closes with Done and no words

    out = ff.play(app, PROBABILITY, "right", "voice", answers=3, reply=reply)
    done = [e["transcript"] for e in out["events"] if e["type"] == "answer_complete"]
    assert done[:2] == [first["words"], first["words"]]
    assert session_of(out).questions[0].scored == "correct"


@pytest.mark.parametrize("name", list(ff.CASES))
def test_every_format_gives_up_at_the_limit_and_keeps_going(monkeypatch, short, name):
    ff.install(monkeypatch, ff.Universal(delay=60))  # every model call hangs
    out = ff.play(app, ff.begin_for(name), "right", "typed", answers=3, watch=10)
    assert out["status"] in ("moving", "ended"), (out["status"], types(out)[-6:])
    assert "turn_timed_out" in types(out)
    assert not any(e["type"] == "error" and STOPPED in e.get("message", "") for e in out["events"])
    assert max(out["waits"]) < 2 * GIVE_UP + 2  # a turn never waits much past the limit
    for e in out["events"]:
        assert not (e["type"] == "scored" and e.get("outcome") == "correct")
        assert not (e["type"] == "interviewer_line" and e["kind"] == "close" and say.CORRECT_CLOSE in e["text"])


NEW_LINE_KINDS = ("question", "probe", "close")


def asked_again_after_each_give_up(out):
    """Between each give-up and the next listening turn: no new question, probe or close."""
    events, bad = out["events"], []
    for i, e in enumerate(events):
        if e["type"] != "turn_timed_out":
            continue
        for later in events[i + 1:]:
            if later["type"] == "state" and later["value"] == "listening":
                break
            if later["type"] in ("question", "follow_up", "part2", "session_end", "scored", "coding_open") or (
                    later["type"] == "interviewer_line" and later["kind"] in NEW_LINE_KINDS):
                bad.append(later["type"] + ":" + str(later.get("kind") or ""))
                break
    return bad


@pytest.mark.parametrize("name", list(ff.CASES))
def test_every_format_asks_the_same_question_again_after_a_give_up(monkeypatch, short, name):
    ff.install(monkeypatch, ff.Universal(delay=60))
    out = ff.play(app, ff.begin_for(name), "right", "typed", answers=3, watch=10)
    assert out["status"] in ("moving", "ended")
    assert asked_again_after_each_give_up(out) == []


def slow_kind(kind, seconds=60, calls=1):
    state = {"n": 0}

    def delay(k):
        if k != kind:
            return 0
        state["n"] += 1
        return seconds if state["n"] <= calls else 0
    return delay


def test_a_behavioural_answer_that_timed_out_is_replaced_by_the_retry(monkeypatch, short):
    ff.install(monkeypatch, ff.Universal(delay=slow_kind("behavioural")))
    words = iter(["First attempt, never judged.", "Second attempt: I led the launch and we hit 3 of 4 goals."])
    out = ff.play(app, ff.CASES["IB analyst: Behavioural"], "right", "typed", answers=3,
                  reply=lambda n, q, events: next(words, None))
    assert "turn_timed_out" in types(out)
    first = session_of(out).asked[0]
    assert first.first == "Second attempt: I led the launch and we hit 3 of 4 goals." and first.judged.error is None


def test_a_coding_plan_that_timed_out_is_asked_again_before_the_editor_opens(monkeypatch, short):
    ff.install(monkeypatch, ff.Universal(delay=slow_kind("coding_plan")))
    words = iter(["First plan, never checked.", "I keep a running sum, one pass, so O(n)."])
    out = ff.play(app, ff.CASES["software: coding round"], "right", "typed", answers=3,
                  reply=lambda n, q, events: next(words, None))
    kinds = types(out)
    assert kinds.index("turn_timed_out") < kinds.index("coding_open")
    assert [e["transcript"] for e in out["events"] if e["type"] == "answer_complete"][:2] ==         ["First plan, never checked.", "I keep a running sum, one pass, so O(n)."]
    problem = session_of(out).problems[0]
    assert problem.approach == "I keep a running sum, one pass, so O(n)."


def test_the_room_shows_the_slow_status_says_the_give_up_line_and_resends_on_an_empty_done():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "app" / "static" / "ui" / "interview.js").read_text(encoding="utf-8")
    slow = js[js.index('case "turn_slow":'):js.index('case "turn_timed_out":')]
    assert "setStatus(event.message);" in slow
    gave = js[js.index('case "turn_timed_out":'):]
    gave = gave[:gave.index("break;")]
    assert "resendReady = true;" in gave and 'addInterviewer(event.message, "prompt");' in gave
    typed = js[js.index("function sendTyped()"):js.index("// ---------- Coding rounds")]
    assert "!text && resendReady" in typed and 'JSON.stringify({ type: "resend" })' in typed
    for case in ('case "question":', 'case "answer_complete":'):  # a new question or answer ends the offer
        body = js[js.index(case):]
        assert "resendReady = false;" in body[:body.index("break;")]
