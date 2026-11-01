"""Bring your own question (decision log 38): the read, the recorded calls, the check
endpoint and the one-question interview. Offline: replay of the synthetic fixtures in
tests/fixtures/byoq/calls (scripts/byoq_fixtures.py), or fake backends; no key."""

import base64
import builtins
import io
import json
import logging
import time
from fractions import Fraction
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import byoq, interview_report
from app.main import app
from engine.coding import Outcome
from forge import byoq as gate
from llm import backends
from llm.replay import CallStore
from byoq_fakes import QUESTION, READ, outputs
from test_bank_runtime import run

FIXTURES = Path(__file__).parent / "fixtures" / "byoq"
IMAGE = (FIXTURES / "question.png").read_bytes()
B64 = base64.b64encode(IMAGE).decode("ascii")


def replay():
    return byoq.Calls(CallStore(FIXTURES / "calls"), "replay")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in ("BYOQ_MODE", "BYOQ_SOLVERS", "LLM_BACKEND", "VOICE_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BYOQ_RECORD_DIR", str(tmp_path / "records"))
    for name in ("MODEL_API_KEY", "BASETEN_API_KEY"):
        monkeypatch.delenv(name, raising=False)  # replay and fakes need no key


class Fake:
    """A backend that answers from a table by stage; `finish` can cut a reply off."""

    def __init__(self, name="meta_api", table=None, finish="stop"):
        real = backends.get_backend(name)
        self.name, self.model, self.enforces_schema = real.name, real.model, real.enforces_schema
        self.table = table or {"read": READ, **outputs()}
        self.finish, self.requests = finish, []

    def complete(self, request):
        self.requests.append(request)
        stage = request["response_format"]["json_schema"]["name"].removeprefix("byoq_").removesuffix("_repair")
        return {"choices": [{"finish_reason": self.finish, "message": {"content": json.dumps(self.table[stage])}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


# --- Recorded fixtures --------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["meta_api", "open_weights"])
def test_the_recorded_read_replays_without_a_key(backend):
    found = byoq.read_image(IMAGE, "image/png", replay(), backends.get_backend(backend))
    assert found["question_text"] == QUESTION and found["single_exact_numeric_answer"] is True
    assert found["stated_answer"] is None and found["topic"] == "Discrete probability"
    assert byoq.read_text(QUESTION, replay(), backends.get_backend(backend))["question_text"] == QUESTION


def test_the_read_request_is_strict_low_effort_and_capped():
    fake = Fake()
    byoq.read_image(IMAGE, "image/png", byoq.Calls(current_mode="live"), fake)
    request = fake.requests[0]
    assert request["model"] == "muse-spark-1.3" and request["reasoning_effort"] == "low"
    assert request["max_tokens"] >= 4000 and request["response_format"]["json_schema"]["strict"] is True
    parts = request["messages"][1]["content"]
    assert parts[1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64," + B64}}
    assert "Never work the answer out yourself." in request["messages"][0]["content"]


@pytest.mark.parametrize("current", [gate.Plan.two_models(), gate.Plan.one_model("open_weights")])
def test_the_recorded_solver_calls_replay_through_the_gate(current):
    token, template = byoq.run_check(QUESTION, None, "Discrete probability", calls=replay(), current=current)
    assert byoq.accepted(token)[0] is template
    assert template.instances[0].answer == Fraction(3, 28)
    assert byoq.accepted(token)[1] >= gate.MIN_VARIANTS


def test_a_missing_recording_in_replay_is_a_failure_not_a_live_call():
    with pytest.raises(byoq.CallFailed) as failure:
        byoq.read_text("A fair coin is flipped 3 times. What is the probability of 3 heads?", replay(),
                       backends.get_backend("meta_api"))
    assert failure.value.reason == "replay_missing"


# --- Truncation ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["meta_api", "open_weights"])
def test_a_truncated_read_counts_as_a_failure(backend):
    fake = Fake(backend, finish="length")
    with pytest.raises(byoq.CallFailed) as failure:
        byoq.read_image(IMAGE, "image/png", byoq.Calls(current_mode="live"), fake)
    assert failure.value.reason == "truncated_or_refused"
    assert len(fake.requests) == 1  # no repair after a cut-off reply


def test_a_truncated_read_through_the_endpoint_says_it_could_not_read(monkeypatch):
    monkeypatch.setenv("BYOQ_MODE", "live")
    monkeypatch.setattr(byoq, "read_backend", lambda: Fake(finish="length"))
    response = TestClient(app).post("/api/byoq/read", content=IMAGE, headers={"content-type": "image/png"})
    assert response.status_code == 502 and response.json()["detail"] == byoq.READ_FAILED


def test_a_truncated_solver_call_fails_the_gate():
    fake = Fake("open_weights", finish="length")
    calls = byoq.Calls(current_mode="live")

    def call(stage, role, payload, schema, prompt):
        return calls.structured(stage, fake, prompt, json.dumps(payload), schema, 8000)

    with pytest.raises(byoq.CallFailed) as failure:
        gate.check_question(QUESTION, None, "Discrete probability", call, gate.Plan.one_model("open_weights"))
    assert failure.value.reason == "truncated_or_refused"


# --- The image is never stored -----------------------------------------------------------


def test_the_image_is_never_written_to_disk_logs_or_the_session(monkeypatch, tmp_path, caplog):
    written = []
    real_open, real_io_open = builtins.open, io.open

    def spy(opener):
        def wrapped(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                written.append(Path(file))
            return opener(file, mode, *args, **kwargs)
        return wrapped

    monkeypatch.setenv("BYOQ_MODE", "live")
    fake = Fake()
    monkeypatch.setattr(byoq, "read_backend", lambda: fake)
    monkeypatch.setattr(builtins, "open", spy(real_open))
    monkeypatch.setattr(io, "open", spy(real_io_open))
    caplog.set_level(logging.DEBUG)
    response = TestClient(app).post("/api/byoq/read", content=IMAGE, headers={"content-type": "image/png"})
    monkeypatch.setattr(builtins, "open", real_open)
    monkeypatch.setattr(io, "open", real_io_open)
    assert response.status_code == 200 and response.json()["question_text"] == QUESTION
    assert B64 in json.dumps(fake.requests)  # it was sent to the model once
    assert written, "the call is recorded"
    for path in written:
        if path.exists() and path.is_file():
            stored = path.read_bytes()
            assert B64.encode() not in stored and IMAGE[:64] not in stored and b"data:image" not in stored
    records = list(Path(byoq.record_dir()).glob("*.json"))
    assert records and all("image:sha256=" in r.read_text(encoding="utf-8") for r in records)
    assert B64 not in caplog.text and "data:image" not in caplog.text
    assert B64 not in response.text
    # The session and its report only ever see the confirmed text.
    token, template = byoq.run_check(QUESTION, None, "Discrete probability", calls=replay(), current=gate.Plan.two_models())
    session, events, _ = run(byoq.ByoqSource(template), lambda s, e: f"My answer is 3/28, because {s.questions[-1].puzzle.answer_text}")
    session.byoq = byoq.accepted(token)
    log = json.dumps([events, byoq.report(session, interview_report.build)], default=str)
    assert B64 not in log and "data:image" not in log and "sha256" not in log


@pytest.mark.parametrize("body,kind,status", [
    (b"GIF89a" + b"0" * 100, "image/gif", 415),
    (b"not a png at all", "image/png", 415),
    (b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024), "image/png", 413),
], ids=["gif", "not-png", "over-5mb"])
def test_only_png_or_jpeg_up_to_five_megabytes(body, kind, status, monkeypatch):
    monkeypatch.setattr(byoq, "read_backend", lambda: pytest.fail("no model call for a refused file"))
    assert TestClient(app).post("/api/byoq/read", content=body, headers={"content-type": kind}).status_code == status


# --- Check endpoint -----------------------------------------------------------------------


def poll(client, job, until=60):
    end = time.monotonic() + until
    while time.monotonic() < end:
        state = client.get(f"/api/byoq/check/{job}").json()
        if state["stage"] in {"ready", "failed"}:
            return state
        time.sleep(0.2)
    raise AssertionError("the check did not finish")


def test_the_check_endpoint_reports_progress_then_ready(monkeypatch):
    monkeypatch.setenv("BYOQ_MODE", "replay")
    monkeypatch.setenv("BYOQ_RECORD_DIR", str(FIXTURES / "calls"))
    with TestClient(app) as client:
        started = client.post("/api/byoq/check", json={"text": QUESTION, "stated": None, "topic": "Discrete probability"}).json()
        assert started["stage"] == "solvers"
        state = poll(client, started["job"])
    assert state["stage"] == "ready" and state["variants"] >= gate.MIN_VARIANTS
    assert state["href"].startswith("/ui/interview?byoq=")


def test_a_failed_check_says_so_plainly_and_offers_a_shipped_family(monkeypatch):
    monkeypatch.setenv("BYOQ_MODE", "replay")
    monkeypatch.setenv("BYOQ_RECORD_DIR", str(FIXTURES / "calls"))
    with TestClient(app) as client:
        job = client.post("/api/byoq/check", json={"text": QUESTION + " (edited)", "topic": "Discrete probability"}).json()["job"]
        state = poll(client, job)
    assert state["stage"] == "failed" and state["message"] == "We couldn't check this one in code, so we won't score it."
    assert state["similar"]["href"].startswith("/ui/interview?family=")
    assert "href" not in state or not state.get("href", "").startswith("/ui/interview?byoq=")


# --- The interview ------------------------------------------------------------------------


def accepted_template():
    return byoq.run_check(QUESTION, None, "Discrete probability", calls=replay(), current=gate.Plan.two_models())


@pytest.mark.parametrize("wrong", ["9/64", "3/32", "3/8", "1/5", "28/3"])
def test_a_wrong_committed_number_on_a_byoq_question_is_never_correct(wrong):
    _, template = accepted_template()
    said = []

    def policy(session, events):
        said.append(len(said))
        return f"My answer is {wrong}, because that's my reasoning."

    session, events, _ = run(byoq.ByoqSource(template), policy)
    first = session.questions[0]
    assert first.puzzle.instance == 0 and first.puzzle.text == QUESTION  # the candidate's own question first
    assert first.scored is not None and first.scored != Outcome.CORRECT.value
    assert all(a.outcome is not Outcome.CORRECT for q in session.questions for a in q.answers)
    assert any(e.get("kind") == "challenge" for e in events)  # the usual challenge of the committed number


def test_the_byoq_interview_is_the_question_then_its_twin_and_is_never_rated():
    token, template = accepted_template()
    session, events, _ = run(byoq.ByoqSource(template), lambda s, e: (
        f"My answer is {s.questions[-1].puzzle.answer_text}, because both draws must be red."))
    kinds = [q.kind for q in session.questions]
    assert kinds[:2] == ["new", "twin"]
    assert session.questions[1].puzzle.instance != 0 and session.questions[1].puzzle.template_id == template.template_id
    session.byoq = byoq.accepted(token)
    report = byoq.report(session, interview_report.build)
    assert report["byoq"]["line"] == f"Your question · checked in code on {byoq.accepted(token)[1]} variants"
    assert report["rating_items"] == [] and report["track"] is None and report["drills"] == []


def test_the_socket_refuses_an_unknown_token():
    from app.interview_routes import byoq_session
    from voice.recording import VoiceError
    with pytest.raises(VoiceError):
        byoq_session("not-a-token", None, None, None, 0)


# --- Live recordings (scripts/byoq_record.py), once the builder has made them ---------------

DEMO = Path(__file__).resolve().parents[1] / "replay" / "llm" / "demo" / "byoq"
OUTCOMES = sorted(DEMO.glob("outcome-*.json"))


@pytest.mark.skipif(not OUTCOMES, reason="no live BYOQ recordings yet: run scripts/byoq_record.py")
@pytest.mark.parametrize("path", OUTCOMES or [None], ids=[p.stem for p in OUTCOMES] or ["none"])
def test_the_live_recordings_replay_to_the_same_outcome(path, monkeypatch):
    outcome = json.loads(path.read_text(encoding="utf-8"))
    monkeypatch.setenv("LLM_BACKEND", outcome["read_backend"])
    monkeypatch.setenv("BYOQ_SOLVERS", "two" if outcome["plan"]["second"] == "solver" else "one")
    calls = byoq.Calls(CallStore(DEMO), "replay")
    image = FIXTURES / outcome["image"]
    mime = "image/png" if image.suffix == ".png" else "image/jpeg"
    found = byoq.read_image(image.read_bytes(), mime, calls)
    assert found == outcome["read"]
    for record in DEMO.glob("*.json"):  # recorded with the digest, never the image
        assert "data:image" not in record.read_text(encoding="utf-8")
    try:
        token, template = byoq.run_check(found["question_text"], found["stated_answer"], found["topic"], calls=calls)
    except (gate.GateFailure, byoq.CallFailed) as error:
        assert outcome["stage"] == "failed" and error.reason == outcome["reason"]
    else:
        assert outcome["stage"] == "ready" and byoq.accepted(token)[1] == outcome["variants"]
        assert template.instances[0].answer_text == outcome["answer"]
