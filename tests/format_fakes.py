"""Fakes that play any interview format end to end over the real socket: a model fake that
answers every job (its own fake where one exists, else a minimal reply that fits the job's JSON
schema), and a fake transcription upstream that "hears" SAY["text"] on a capture's first audio
frame. No network and no real key (a synthetic MODEL_API_KEY is set only if none is)."""

import asyncio
import json
import os
import random
import tempfile
import threading
import time

from test_coding import FakeSpark as CodingFake
from test_mixed_interview import Models

from app import byoq, coding, limits
from engine.bank import load_bank
from voice.recording import RecordStore, VoiceError

SAY = {"text": "I don't know."}  # what the candidate says on the next capture
BANK = load_bank(hidden=frozenset())
ANSWERS = {i.text: i.answer for t in BANK.templates.values() for i in t.instances}
EXPECTED = {tid: s["expected"] for pack in ("software", "quant_dev") for tid, s in coding.specs(pack).items()}


def synth(schema):
    """A minimal reply that satisfies the job's own JSON schema."""
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema:
        return synth(schema["anyOf"][0])
    t = schema.get("type")
    t = t[0] if isinstance(t, list) else t
    if t == "object":
        return {k: synth(v) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [synth(schema["items"])] * schema.get("minItems", 0) if schema.get("items") else []
    if t == "boolean":
        return False
    if t in ("integer", "number"):
        return schema.get("minimum", 0)
    return "none"


class Universal(Models):
    """`fail`: every call raises the provider's model error. `delay`: seconds each call takes
    (a callable(kind) -> seconds, or a number)."""

    def __init__(self, fail=False, delay=0.0):
        super().__init__()
        self.coding, self.fail, self.delay = CodingFake(), fail, delay
        self.cancelled = 0
        self.kinds = []

    async def structured(self, text, kind, effort, schema, prompt):
        self.kinds.append(kind)
        delay = self.delay(kind) if callable(self.delay) else self.delay
        if delay:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        if self.fail:
            raise VoiceError("The model request failed. Your transcript is available to edit or retry.")
        if kind.startswith("coding_"):
            return await self.coding.structured(text, kind, effort, schema, prompt)
        if kind in ("minimal", "full", "extraction") or kind.startswith("market_") or "verdict" in schema.get("properties", {}):
            return await super().structured(text, kind, effort, schema, prompt)
        try:
            return await super().structured(text, kind, effort, schema, prompt)
        except Exception:  # noqa: BLE001  (no scripted reply for this job)
            return synth(schema), {"model": "fake"}


class Upstream:
    """The realtime transcription socket: hears SAY["text"] on the first audio frame."""

    def __init__(self):
        self.events, self.close_code, self.spoke = asyncio.Queue(), 1000, False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def recv(self):
        return '{"sessionId":"fake"}'

    async def send(self, frame):
        if isinstance(frame, bytes):
            if not self.spoke and SAY["text"]:
                self.spoke = True
                for e in [{"type": "speechStart", "turnId": 1}, {"type": "transcript", "transcript": SAY["text"]},
                          {"type": "speechEnd", "turnId": 1}, {"type": "speechComplete", "turnId": 1, "transcript": SAY["text"]}]:
                    await self.events.put(e)
        elif json.loads(frame).get("type") == "endStream":
            await self.events.put({"type": "transcript", "transcript": "", "final": True})
            await self.events.put(None)

    def __aiter__(self):
        async def gen():
            while True:
                e = await self.events.get()
                if e is None:
                    return
                yield json.dumps(e)
        return gen()


def install(monkeypatch, models):
    """The app's provider -> `models`, live mode with a temporary record store and an endpoint
    that always says "thinking" (only Done or the silence check ends a numeric turn)."""
    import websockets.asyncio.client as wsclient
    from app import voice_routes
    if not os.environ.get("MODEL_API_KEY"):
        monkeypatch.setenv("MODEL_API_KEY", "synthetic-test-key")  # never a real key
    models.mode = "live"
    models.store = RecordStore(tempfile.mkdtemp(prefix="format-fakes-"))

    async def endpoint(text):
        return {"finished": False, "kind": "thinking"}, {"model": "fake"}

    models.endpoint = endpoint
    monkeypatch.setattr(wsclient, "connect", lambda *a, **k: Upstream())
    monkeypatch.setattr(voice_routes, "provider", lambda: models)
    return models


def answer_for(style, q):
    kind, text = q.get("kind"), q.get("text", "")
    if kind == "market":
        return "I don't know." if style == "idk" else "0 at 2000"
    if style == "idk":
        return "I don't know."
    exact = ANSWERS.get(text)
    if exact is None:
        return "Last spring I led the work and we hit 3 of 4 goals, because it mattered. That is it."
    return f"My answer is {exact}, because I worked it out."


CASES = {
    "quant trading: Probability": {"pack": "quant", "role": "quant_trading", "topics": ["Probability"], "level": "Easy"},
    "quant research: Statistics": {"pack": "quant", "role": "quant_research", "topics": ["Statistics"], "level": "Medium"},
    "quant trading: no chips": {"pack": "quant", "role": "quant_trading", "topics": [], "level": "Easy"},
    "quant dev (opener + coding)": {"pack": "quant", "role": "quant_dev", "topics": [], "level": "Easy"},
    "IB analyst: DCF": {"pack": "ib", "role": "ib_analyst", "topics": ["DCF"], "level": "Easy"},
    "IB analyst: Behavioural": {"pack": "ib", "role": "ib_analyst", "topics": ["Behavioural"]},
    "IB analyst: Conceptual": {"pack": "ib", "role": "ib_analyst", "topics": ["Conceptual questions"]},
    "consulting: Profitability": {"pack": "consulting", "role": "strategy", "topics": ["Profitability"], "level": "Easy"},
    "consulting: Full case": {"pack": "consulting", "role": "strategy", "topics": ["Full case"]},
    "software: coding round": {"pack": "software", "role": "swe", "topics": []},
    "software: Design concepts": {"pack": "software", "role": "backend", "topics": ["Design concepts"]},
    "market making alone": {"pack": "quant", "role": "quant_trading", "topics": ["Market making"]},
    "mixed: Probability + Market": {"pack": "quant", "role": "quant_trading", "topics": ["Probability", "Market making"], "level": "Easy"},
    "mixed IB: DCF + Behavioural": {"pack": "ib", "role": "ib_analyst", "topics": ["DCF", "Behavioural"], "level": "Easy"},
    "placement (quant)": {"pack": "quant", "placement": True},
    "placement (IB)": {"pack": "ib", "placement": True},
    "BYOQ (accepted question)": "byoq",
    "family link (qe_F002)": {"family": "qe_F002"},
}


def begin_for(name):
    begin = CASES[name]
    if begin == "byoq":
        token = "format-test-" + str(random.random())
        byoq.keep(token, BANK.templates["qe_F001"], 50)
        return {"byoq": token}
    return begin


def play(app, begin, style="right", mode="typed", answers=4, watch=20.0, reply=None):
    """Answer each turn (typed, or a voice capture closed with Done) until `answers` answers or
    the end. status: "moving" (it kept moving on), "ended", "STUCK" (no event for `watch` s),
    or "refused"/"exception ...". `waits`: seconds from each answer to the next turn or the end.
    `reply(n, q, events)`: the n-th answer's words instead (None: the default for `style`; a
    dict: a control message to send instead, such as {"type": "resend"})."""
    from fastapi.testclient import TestClient
    limits.GUARD.reset()
    out = {"events": [], "status": "running", "answers": 0, "waits": []}

    def run():
        try:
            with TestClient(app).websocket_connect("/api/interview/ws") as s:
                s.send_json({"type": "begin", "consent": True, "typed_practice": mode == "typed", **begin})
                q, sent_at, coding_turns = {}, None, 0
                while True:
                    e = s.receive_json()
                    out["events"].append(e)
                    out["last"] = time.time()
                    if e["type"] == "error" and e.get("final"):
                        out["status"] = "refused: " + e["message"]
                        return
                    if e["type"] in ("question", "follow_up", "part2"):
                        q = e if e["type"] == "question" else {**q, "kind": e["type"], "text": e["text"]}
                    if e["type"] == "question" and e.get("kind") == "coding":
                        coding_turns = 0  # a new problem: the plan first, code once the editor opens
                    if e["type"] == "coding_open":
                        coding_turns = 1
                    if e["type"] == "coding_closed":
                        q = {**q, "kind": "spoken_after_code"}
                    if e["type"] == "session_end":
                        if sent_at:
                            out["waits"].append(time.time() - sent_at)
                        out["status"] = "ended"
                        return
                    if e["type"] == "state" and e["value"] == "listening":
                        if sent_at:
                            out["waits"].append(time.time() - sent_at)
                        if out["answers"] >= answers:
                            out["status"] = "moving"
                            s.send_json({"type": "end"})
                            return
                        out["answers"] += 1
                        sent_at = time.time()
                        if q.get("kind") == "coding" and coding_turns:
                            tid = q["coding"]["template_id"]
                            good = style == "right" and tid in EXPECTED
                            s.send_json({"type": "code_submit", "code": "def f(*a):\n    return None\n",
                                         "outputs": EXPECTED[tid] if good else []})
                            continue
                        say = reply(out["answers"], q, out["events"]) if reply else None
                        if isinstance(say, dict):
                            s.send_json(say)
                            continue
                        if say is None:
                            say = answer_for(style, q) if q.get("kind") != "coding" else "I keep a running sum, one pass, so O(n)."
                        if mode == "typed":
                            s.send_json({"type": "typed", "transcript": say})
                        else:
                            SAY["text"] = say
                            s.send_json({"type": "capture", "sample_rate": 16000, "headphones": True, "interviewer_speaking": False})
                    if e["type"] == "ready" and mode != "typed":
                        s.send_bytes(bytes(2560))
                        time.sleep(0.2)
                        s.send_json({"type": "done"})
        except Exception as ex:  # noqa: BLE001
            out["status"] = "exception " + repr(ex)[:300]

    out["last"] = time.time()
    th = threading.Thread(target=run, daemon=True)
    th.start()
    while th.is_alive():
        th.join(0.25)
        if time.time() - out["last"] > watch:
            out["status"] = "STUCK"
            break
    return out
