"""Decision log 42: spend protection (per-IP limits, a global daily cost cap), security headers,
Subresource Integrity on the pinned CDN files, and the /privacy page."""

from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import byoq, interview_routes, limits, voice_routes
from app.main import app
from llm import backends
from test_exam_session import bag_routes, drain, typed  # noqa: F401  (fixture)
from voice.recording import VoiceError

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static" / "ui"
TEMPLATES = ROOT / "app" / "templates"


class Clock:
    def __init__(self, t=1_800_000_000.0):  # 2027-01-15 08:00 UTC
        self.t = t

    def __call__(self):
        return self.t


def guard(clock=None):
    return limits.Guard(clock or Clock())


# --- The one config table ---------------------------------------------------------------------

def test_the_table_holds_the_agreed_limits():
    assert limits.LIMITS["interview"] == limits.Limit(8, limits.HOUR)
    assert limits.LIMITS["byoq_read"] == limits.Limit(15, limits.DAY)
    assert limits.LIMITS["byoq_check"] == limits.Limit(15, limits.DAY)
    assert limits.LIMITS["transcription"] == limits.Limit(300, limits.DAY)
    assert limits.DAILY_COST_CAP_USD == Decimal("5")


def test_rates_are_spec_rates_and_labelled_stand_ins():
    spark = limits.RATES["muse-spark-1.3"]
    assert (spark.input_per_m, spark.output_per_m, spark.stand_in) == (Decimal("1.25"), Decimal("4.25"), False)
    open_ = limits.RATES["meta-models/muse-spark-open-1026"]
    assert (open_.input_per_m, open_.output_per_m, open_.stand_in) == (Decimal("1.25"), Decimal("4.25"), True)
    assert "stand-in" in open_.source and "not a published price" in open_.source
    assert limits.TRANSCRIBE_USD_PER_MINUTE == Decimal("0.01")
    assert "stand-in" in limits.TRANSCRIBE_SOURCE


# --- Per-IP limits ----------------------------------------------------------------------------

def test_eight_interview_starts_an_hour_then_refused_then_free_again():
    clock = Clock()
    g = guard(clock)
    for _ in range(8):
        g.admit("interview", "1.2.3.4")
    with pytest.raises(limits.Refused) as refused:
        g.admit("interview", "1.2.3.4")
    assert refused.value.status == 429 and "Try again later" in refused.value.message
    g.admit("interview", "5.6.7.8")  # another visitor is not affected
    clock.t += limits.HOUR + 1
    g.admit("interview", "1.2.3.4")


def test_byoq_limits_are_per_day_and_separate():
    clock = Clock()
    g = guard(clock)
    for _ in range(15):
        g.admit("byoq_read", "ip")
        g.admit("byoq_check", "ip")
    for kind in ("byoq_read", "byoq_check"):
        with pytest.raises(limits.Refused):
            g.admit(kind, "ip")
    clock.t += limits.HOUR * 23
    with pytest.raises(limits.Refused):
        g.admit("byoq_read", "ip")
    clock.t += limits.HOUR + 1
    g.admit("byoq_read", "ip")


def test_a_refused_request_is_not_counted():
    clock = Clock()
    g = guard(clock)
    for _ in range(8):
        g.admit("interview", "ip")
    for _ in range(20):
        with pytest.raises(limits.Refused):
            g.admit("interview", "ip")
    clock.t += limits.HOUR + 1
    for _ in range(8):
        g.admit("interview", "ip")


# --- The global daily cost cap ----------------------------------------------------------------

def test_cost_estimates():
    g = guard()
    g.add_tokens("muse-spark-1.3", {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000})
    assert g.spent_today() == Decimal("5.50")
    g.add_tokens("meta-models/muse-spark-open-1026", {"prompt_tokens": 2000, "completion_tokens": 1000})
    assert g.spent_today() == Decimal("5.50") + Decimal("0.00675")
    g.add_audio(90)
    assert g.spent_today() == Decimal("5.50") + Decimal("0.00675") + Decimal("0.015")


def test_unknown_model_or_missing_usage_counts_at_the_highest_rate():
    g = guard()
    g.add_tokens("some-new-model", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    assert g.spent_today() == Decimal("1.25")
    g.add_tokens("muse-spark-1.3", None)  # no usage reported: the request's own token cap
    assert g.spent_today() > Decimal("1.25")


def test_cap_reached_refuses_every_new_session_with_busy():
    g = guard()
    g.add_tokens("muse-spark-1.3", {"prompt_tokens": 0, "completion_tokens": 1_176_471})  # > $5
    for kind in limits.LIMITS:
        with pytest.raises(limits.Refused) as refused:
            g.admit(kind, "fresh-ip")
        assert refused.value.message == limits.BUSY == "Busy right now, try again later."
        assert refused.value.status == 503


def test_cap_resets_on_the_next_utc_day():
    clock = Clock()
    g = guard(clock)
    g.add_audio(60 * 600)  # $6
    with pytest.raises(limits.Refused):
        g.admit("interview", "ip")
    clock.t += limits.DAY
    assert g.spent_today() == 0
    g.admit("interview", "ip")


# --- Client IP --------------------------------------------------------------------------------

def test_client_ip_is_the_first_forwarded_entry_else_the_peer():
    assert limits.client_ip({"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, ("10.0.0.1", 5)) == "203.0.113.9"
    assert limits.client_ip({}, ("198.51.100.4", 5)) == "198.51.100.4"
    assert limits.client_ip({"x-forwarded-for": "  "}, None) == "unknown"


# --- Endpoints --------------------------------------------------------------------------------

def visitor(ip):
    return TestClient(app, headers={"X-Forwarded-For": ip})


def test_byoq_read_sixteenth_is_refused_without_a_model_call(monkeypatch):
    calls = []
    monkeypatch.setattr(byoq, "read_text", lambda text: calls.append(text) or {"text": text})
    client = visitor("203.0.113.1")
    for _ in range(15):
        assert client.post("/api/byoq/read", json={"text": "What is 2+2?"}).status_code == 200
    response = client.post("/api/byoq/read", json={"text": "What is 2+2?"})
    assert response.status_code == 429 and "Try again later" in response.json()["detail"]
    assert len(calls) == 15
    assert visitor("203.0.113.2").post("/api/byoq/read", json={"text": "What is 2+2?"}).status_code == 200


def test_byoq_read_bad_input_does_not_use_up_the_limit(monkeypatch):
    monkeypatch.setattr(byoq, "read_text", lambda text: {"text": text})
    client = visitor("203.0.113.3")
    for _ in range(20):
        assert client.post("/api/byoq/read", json={"text": ""}).status_code == 400
    assert client.post("/api/byoq/read", json={"text": "What is 2+2?"}).status_code == 200


def test_byoq_check_sixteenth_is_refused(monkeypatch):
    async def job(*args):
        return None

    monkeypatch.setattr(byoq, "_job", job)
    monkeypatch.setattr(byoq, "_running", 0)
    client = visitor("203.0.113.4")
    for _ in range(15):
        assert client.post("/api/byoq/check", json={"text": "What is 2+2?"}).status_code == 200
        byoq._running = 0
    response = client.post("/api/byoq/check", json={"text": "What is 2+2?"})
    assert response.status_code == 429


def test_cap_reached_byoq_says_busy_and_calls_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(byoq, "read_text", lambda text: calls.append(text) or {"text": text})
    limits.GUARD.add_audio(60 * 600)
    response = visitor("203.0.113.5").post("/api/byoq/read", json={"text": "What is 2+2?"})
    assert response.status_code == 503 and response.json()["detail"] == "Busy right now, try again later."
    assert calls == []


def test_ninth_interview_start_is_refused_before_any_model(monkeypatch):
    def provider():
        raise VoiceError("stopped here")  # an admitted start reaches the provider

    monkeypatch.setattr(voice_routes, "provider", provider)
    client = visitor("203.0.113.6")
    for _ in range(8):
        with client.websocket_connect("/api/interview/ws") as socket:
            socket.send_json({"type": "begin", "consent": True})
            assert socket.receive_json()["message"] == "stopped here"
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        event = socket.receive_json()
    assert event["type"] == "error" and event["final"] is True and "Try again later" in event["message"]


def test_a_start_without_consent_does_not_count(monkeypatch):
    monkeypatch.setattr(voice_routes, "provider", lambda: (_ for _ in ()).throw(VoiceError("stopped here")))
    client = visitor("203.0.113.7")
    for _ in range(12):
        with client.websocket_connect("/api/interview/ws") as socket:
            socket.send_json({"type": "begin", "consent": False})
            socket.receive_json()
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        assert socket.receive_json()["message"] == "stopped here"


def test_cap_reached_interview_start_says_busy(monkeypatch):
    called = []
    monkeypatch.setattr(voice_routes, "provider", lambda: called.append(1))
    limits.GUARD.add_audio(60 * 600)
    with visitor("203.0.113.8").websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        event = socket.receive_json()
    assert event == {"type": "error", "message": "Busy right now, try again later.", "final": True}
    assert called == []


def test_realtime_streams_count_as_interview_starts(monkeypatch):
    monkeypatch.setattr(voice_routes, "provider", lambda: (_ for _ in ()).throw(VoiceError("stopped here")))
    client = visitor("203.0.113.9")
    for _ in range(8):
        with client.websocket_connect("/api/voice/realtime") as socket:
            socket.send_json({"type": "start"})
            assert socket.receive_json()["message"] == "stopped here"
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        assert "Try again later" in socket.receive_json()["message"]


def test_transcription_request_endpoints_share_300_a_day(monkeypatch):
    class Fake:
        mode = "replay"

        async def transcribe(self, audio):
            return {"transcript": "four"}

    monkeypatch.setattr(voice_routes, "provider", lambda: Fake())
    for _ in range(300):
        limits.GUARD.admit("transcription", "203.0.113.10")
    client = visitor("203.0.113.10")
    response = client.post("/api/voice/transcribe", content=b"audio")
    assert response.status_code == 429
    with client.websocket_connect("/api/voice/answer") as socket:
        socket.send_json({"transcript": "four"})
        event = socket.receive_json()
    assert event["type"] == "error" and "Try again later" in event["message"]
    assert visitor("203.0.113.11").post("/api/voice/transcribe", content=b"audio").json() == {"transcript": "four"}


# --- Every live model call adds its estimate --------------------------------------------------

def usage_body(model):
    return {"model": model, "usage": {"prompt_tokens": 1000, "completion_tokens": 1000},
            "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}


def test_sync_backend_calls_add_their_cost():
    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**request):
                    return type("R", (), {"model_dump": lambda self: usage_body(request["model"])})()

    backends.MetaAPIBackend(client=Client()).complete({"model": "muse-spark-1.3", "messages": []})
    assert limits.GUARD.spent_today() == Decimal("0.0055")


@pytest.mark.anyio
async def test_async_backend_calls_add_their_cost(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "test-key")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=usage_body("meta-models/muse-spark-open-1026")))
    await backends.OpenWeightsBackend().acomplete({"model": "meta-models/muse-spark-open-1026", "messages": []},
                                                  transport=transport)
    assert limits.GUARD.spent_today() == Decimal("0.0055")


@pytest.fixture
def anyio_backend():
    return "asyncio"


# --- A judge can do several full interviews in a row -----------------------------------------

def full_interview(client):
    with client.websocket_connect("/api/interview/ws") as socket:
        socket.send_json({"type": "begin", "consent": True})
        first = next(e for e in drain(socket, {"state"}) if e["type"] == "question")["text"]
        socket.send_json({"type": "typed", "transcript": typed(first, "right")})
        seen = drain(socket, {"state"}) + drain(socket, {"state"})
        twin = next(e for e in seen if e["type"] == "question" and e["kind"] == "twin")
        socket.send_json({"type": "typed", "transcript": typed(twin["text"], "right")})
        return drain(socket, {"session_end"})[-1]


def test_a_judge_can_do_several_full_interviews_and_own_questions(bag_routes, monkeypatch):  # noqa: F811
    """One judge, one IP, within an hour: six full interviews, a placement-style restart or two,
    and a few own-question reads and checks, with nothing refused."""
    monkeypatch.setattr(byoq, "read_text", lambda text: {"text": text})
    client = visitor("198.51.100.20")
    for _ in range(6):
        assert full_interview(client)["type"] == "session_end"
    for _ in range(5):
        assert client.post("/api/byoq/read", json={"text": "What is 2+2?"}).status_code == 200
    assert full_interview(client)["type"] == "session_end"  # a seventh, still allowed
    assert limits.GUARD.remaining("interview", "198.51.100.20") == 1


# --- Security headers -------------------------------------------------------------------------

HEADERS = {"x-frame-options": "DENY", "content-security-policy": "frame-ancestors 'none'",
           "x-content-type-options": "nosniff", "referrer-policy": "strict-origin-when-cross-origin"}


@pytest.mark.parametrize("path", ["/ui", "/ui/interview", "/ui/privacy", "/health", "/api/interview/topics",
                                  "/ui-static/ui.js", "/ui-static/exam-room.css", "/no-such-page", "/"])
def test_every_response_carries_the_security_headers(path):
    response = TestClient(app).get(path, follow_redirects=False)
    for name, value in HEADERS.items():
        assert response.headers.get(name) == value, (path, name)


def test_no_full_csp_that_could_break_pyodide_codemirror_firebase_or_fonts():
    csp = TestClient(app).get("/ui").headers["content-security-policy"]
    assert csp == "frame-ancestors 'none'"


# --- Subresource Integrity --------------------------------------------------------------------

CODEMIRROR = {
    "codemirror.min.css": "sha512-uf06llspW44/LZpHzHT6qBOIVODjWtv4MxCricRxkzvopAlSWnTf6hpZTFxuuZcuNE9CBQhqE0Seu1CoRk84nQ==",
    "codemirror.min.js": "sha512-OeZ4Yrb/W7d2W4rAMOO0HQ9Ro/aWLtpW9BUSR2UOWnSV2hprXLkkYnnCGc9NeLUxxE4ZG7zN16UuT1Elqq8Opg==",
    "mode/python/python.min.js": "sha512-Vs2GKxnxnTQBRW7o2xXZ9A28njjmu5RToS42efiKNEWmikov0inZY522EtGVK5CcVo0M/FQwmXsTfl9skgRnvw==",
}
PYODIDE_SHA384 = "tVslJOEkg7nVRW3Y3/ReGX0NnonNrbcmt1R5qFbQXQdGa2chRkoJYHAjAsv3zoTq"


def test_codemirror_tags_carry_integrity_and_crossorigin():
    source = (STATIC / "coding-ui.js").read_text(encoding="utf-8")
    for name, digest in CODEMIRROR.items():
        assert f'"{name}", "{digest}"' in source or f'"{name}": "{digest}"' in source, name
    assert 'crossOrigin: "anonymous"' in source
    assert "integrity" in source


def test_pyodide_is_hash_checked_before_it_runs():
    source = (STATIC / "py-worker.js").read_text(encoding="utf-8")
    assert PYODIDE_SHA384 in source
    assert 'crypto.subtle.digest("SHA-384"' in source
    assert 'importScripts("https://cdn.jsdelivr.net' not in source  # never run unchecked
    assert "indexURL" in source  # run from a checked copy, Pyodide can't infer its own folder
    check = source.index("SHA-384")
    assert check < source.index("importScripts(")


# --- The refused start keeps its message on the interview page --------------------------------

def test_interview_page_keeps_a_final_error_after_the_socket_closes():
    source = (STATIC / "interview.js").read_text(encoding="utf-8")
    assert "event.final" in source and "closingMessage" in source
    assert 'closingMessage || "The connection closed. Reload to start again."' in source


# --- /privacy ---------------------------------------------------------------------------------

def test_privacy_page_in_the_floor_look_says_what_the_app_does():
    response = TestClient(app).get("/ui/privacy")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-cache"
    html = response.text
    assert 'data-look="floor"' in html and "<title>Privacy · Unbluffable</title>" in html
    for fact in ("never recorded", "stays on this device", "Muse Voice Transcribe", "only with your consent",
                 "not stored", "Firebase", "Google Fonts", "in memory", "never logged"):
        assert fact in html, fact
    for banned in ("terms of service", "can't be fooled", "calibrated", "proves understanding", "hiring"):
        assert banned not in html.lower(), banned


def test_every_footer_links_the_privacy_page():
    for template in sorted(TEMPLATES.glob("*.html")):
        html = template.read_text(encoding="utf-8")
        footer = html[html.index('<footer class="disclosure">'):html.index("</footer>")]
        assert '<a href="/ui/privacy">Privacy</a>' in footer, template.name
