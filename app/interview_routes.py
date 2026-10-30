"""Exam Room interview socket. One in-memory session per connection; nothing is
persisted here and audio is never stored. Turn-taking reuses
voice.relay.realtime_answer; the analysis is app.interview_session's own."""

from __future__ import annotations

import asyncio
import json
import math
import os
import secrets
import time
from collections import OrderedDict
from contextlib import suppress

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app import interview_report, voice_routes
from app.drill import DrillSession, drill_targets
from app.interview_session import SESSION_SECONDS, ExamSession, SessionClosed, VoiceAnalyzer
from engine.bank import DEFAULT_PACK, MIXED, PACKS, START_LEVELS, Bank, BankSource, load_bank
from engine.interview import Interview
from voice.recording import VoiceError
from voice.relay import realtime_answer

router = APIRouter(prefix="/api/interview")

MAX_SESSIONS = 200
SESSIONS: OrderedDict[str, ExamSession] = OrderedDict()
FRAUD = "fraud"  # the classic T1-T3 interview with the fraud alert flagship; selectable, not the default
_BANK: Bank | None = None


def bank() -> Bank:
    """Accepted forge templates (content/forge/, or FORGE_DIR), loaded once per process."""
    global _BANK
    if _BANK is None:
        _BANK = load_bank(os.environ.get("FORGE_DIR") or None)
    return _BANK


def topics() -> dict:
    """Tracks (template packs) with accepted templates, each with Mixed and its topics.
    The fraud alert sits under Quant; with no templates at all it is the only choice."""
    tracks = []
    for pack in bank().packs():
        found = bank().topics(pack)
        options = [{"id": MIXED, "name": MIXED, "count": sum(n for _, n in found)}]
        options += [{"id": name, "name": name, "count": n} for name, n in found]
        tracks.append({"id": pack, "name": PACKS[pack], "topics": options, "default": MIXED})
    if not tracks:
        tracks.append({"id": DEFAULT_PACK, "name": PACKS[DEFAULT_PACK], "topics": [], "default": FRAUD})
    for track in tracks:
        if track["id"] == DEFAULT_PACK:
            track["topics"].append({"id": FRAUD, "name": "Fraud alert (classic)", "count": None})
    default = DEFAULT_PACK if any(t["id"] == DEFAULT_PACK for t in tracks) else tracks[0]["id"]
    return {"tracks": tracks, "default_track": default, "levels": list(START_LEVELS),
            "default_level": START_LEVELS[0]}


def interview_for(pack, topic, level) -> Interview:
    """The fraud alert is the fallback only when no forge template is accepted yet."""
    found = topics()
    track = next((t for t in found["tracks"] if t["id"] == pack), None)         or next(t for t in found["tracks"] if t["id"] == found["default_track"])
    topic = topic if topic in {option["id"] for option in track["topics"]} else track["default"]
    if topic == FRAUD:
        return Interview(demo=True)
    if level not in START_LEVELS:
        raise VoiceError("Choose a starting level: Easy or Medium.")
    return Interview(source=BankSource(bank(), topic, level, pack=track["id"]))


def keep(session: ExamSession) -> str:
    session_id = secrets.token_urlsafe(16)
    SESSIONS[session_id] = session
    while len(SESSIONS) > MAX_SESSIONS:
        SESSIONS.popitem(last=False)
    return session_id


def replay_speed() -> float:
    speed = float(os.environ.get("VOICE_REPLAY_SPEED", "1"))
    if not math.isfinite(speed) or speed < 0:
        raise VoiceError("VOICE_REPLAY_SPEED must be finite and nonnegative.")
    return speed


@router.get("/topics")
def topic_list():
    """Tracks with accepted templates; each lists Mixed and its topics with counts (Quant also the fraud alert)."""
    return topics()


@router.get("/{session_id}/report")
def report(session_id: str):
    """The in-app report (decision log 8). Sessions live in memory only, so a report
    is gone after a restart or once MAX_SESSIONS newer sessions exist."""
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(404, "This report is no longer available.")
    if isinstance(session, DrillSession):
        return interview_report.build_drill(session)
    return interview_report.build(session, bank().templates)


def drill_for(request, send, listen, analyzer, deadline: float) -> DrillSession:
    """Drill mode (decision log 16): {"session": parent id, "index": n} picks one of the
    parent report's "Drill this mistake" targets; the server decides what is drilled."""
    if not isinstance(request, dict):
        raise VoiceError("That drill is no longer available.")
    parent = SESSIONS.get(request.get("session")) if isinstance(request.get("session"), str) else None
    index = request.get("index")
    targets = drill_targets(parent, bank().templates) if parent is not None and not isinstance(parent, DrillSession) else []
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(targets):
        raise VoiceError("That drill is no longer available.")
    target = targets[index]
    return DrillSession(send, listen, analyzer, bank().templates[target.template_id], target, deadline=deadline)


@router.websocket("/ws")
async def interview_socket(socket: WebSocket):
    if not voice_routes.same_origin(socket):
        await socket.close(code=1008)
        return
    await socket.accept()
    try:
        begin = await asyncio.wait_for(socket.receive_json(), 30)
        if begin.get("type") != "begin":
            raise VoiceError("Start the interview first.")
        if begin.get("consent") is not True:
            raise VoiceError("Please agree that your answer text is kept before starting.")
        provider = voice_routes.provider()

        async def listen() -> str:
            await socket.send_json({"type": "state", "value": "listening"})
            while True:
                message = await socket.receive()
                if message["type"] == "websocket.disconnect":
                    raise SessionClosed
                if message.get("text") is None:
                    continue  # stray microphone frames between captures
                control = json.loads(message["text"])
                kind = control.get("type")
                if kind == "end":
                    raise SessionClosed
                if kind == "typed":
                    text = control.get("transcript")
                    if isinstance(text, str) and text.strip() and len(text) <= 20_000:
                        return text.strip()
                    await socket.send_json({"type": "error", "message": "Enter a nonempty answer of at most 20,000 characters."})
                    continue
                if kind == "capture":
                    try:
                        start = {**control, "type": "start", "hands_free": True}
                        text, model = await realtime_answer(socket, provider, start,
                                                            voice_routes.silence_threshold(), replay_speed(),
                                                            silence_check=session.silence_check)
                    except VoiceError as error:
                        await socket.send_json({"type": "error", "message": str(error)})
                        await socket.send_json({"type": "state", "value": "listening"})
                        continue
                    await socket.send_json({"type": "transcription_model", "model": model})
                    return text
                # interviewer_speaking and other controls outside a capture: nothing to do

        deadline = time.monotonic() + SESSION_SECONDS
        if begin.get("drill") is not None:
            session = drill_for(begin["drill"], socket.send_json, listen, VoiceAnalyzer(provider), deadline)
        else:
            interview = interview_for(begin.get("pack"), begin.get("topic"), begin.get("level", START_LEVELS[0]))
            session = ExamSession(socket.send_json, listen, VoiceAnalyzer(provider), interview, deadline=deadline)
        session_id = keep(session)
        await socket.send_json({"type": "session", "id": session_id, "mode": provider.mode,
                                "session_seconds": SESSION_SECONDS,
                                "drill": session.target.misconception if isinstance(session, DrillSession) else None})
        await session.run()
    except (WebSocketDisconnect, SessionClosed):
        return
    except VoiceError as error:
        with suppress(WebSocketDisconnect, RuntimeError):
            await socket.send_json({"type": "error", "message": str(error)})
    except Exception:
        with suppress(WebSocketDisconnect, RuntimeError):
            await socket.send_json({"type": "error", "message": "The interview stopped unexpectedly. Your report so far is kept for this session."})
    finally:
        with suppress(RuntimeError):
            await socket.close()
