"""Live report (decision log 48): after Done the room never moved on. Every track and format,
typed and voice (a capture closed with Done), right answers and "I don't know", and with every
model call failing: after each answer the room must move on (listen again, or end) and never
stop unexpectedly. Fake models and a fake transcription upstream; no network."""

import pytest

import format_fakes as ff
from app.main import app

STOPPED = "The interview stopped unexpectedly"


def check(out):
    assert out["status"] in ("moving", "ended"), (out["status"], [e["type"] for e in out["events"][-6:]])
    assert not any(e["type"] == "error" and STOPPED in e.get("message", "") for e in out["events"])
    assert out["waits"] and max(out["waits"]) < 10


@pytest.mark.parametrize("name", list(ff.CASES))
@pytest.mark.parametrize("mode,style", [("typed", "right"), ("typed", "idk"), ("voice", "right")])
def test_every_format_moves_on_after_each_answer(monkeypatch, name, mode, style):
    ff.install(monkeypatch, ff.Universal())
    check(ff.play(app, ff.begin_for(name), style, mode))


@pytest.mark.parametrize("name", list(ff.CASES))
def test_every_format_moves_on_when_every_model_call_fails(monkeypatch, name):
    ff.install(monkeypatch, ff.Universal(fail=True))
    check(ff.play(app, ff.begin_for(name), "right", "typed"))
