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

from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect

from app import behavioural, coding, conversational, interview_report, market, quant_dev, voice_routes
from app.areas import AREAS
from app.drill import DrillSession, drill_targets
from app.interview_session import SESSION_SECONDS, ExamSession, SessionClosed, VoiceAnalyzer
from app.placement import PlacementInterview, PlacementSource
from engine.bank import DEFAULT_PACK, DIFFICULTIES, MIXED, PACKS, START_LEVELS, Bank, BankSource, load_bank
from engine.interview import Interview
from voice.recording import VoiceError
from voice.relay import realtime_answer

router = APIRouter(prefix="/api/interview")

MAX_SESSIONS = 200
SESSIONS: OrderedDict[str, ExamSession] = OrderedDict()
_BANK: Bank | None = None


def bank() -> Bank:
    """Accepted forge templates (content/forge/, or FORGE_DIR), loaded once per process."""
    global _BANK
    if _BANK is None:
        _BANK = load_bank(os.environ.get("FORGE_DIR") or None)
    return _BANK


_TOPICS: tuple[Bank, dict, bytes] | None = None  # (bank it was built from, topics, JSON body)


def warm() -> None:
    """Load the bank and build the topics response once, at app startup (app.main lifespan),
    so the first visitor doesn't wait for 28 MB of JSON to parse."""
    cached_topics()


def cached_topics() -> tuple[dict, bytes]:
    """topics() and its JSON body, rebuilt only when the bank object changes (tests swap it)."""
    global _TOPICS
    current = bank()
    if _TOPICS is None or _TOPICS[0] is not current:
        built = _build_topics()
        _TOPICS = (current, built, json.dumps(built, separators=(",", ":")).encode())
    return _TOPICS[1], _TOPICS[2]


def topics() -> dict:
    return cached_topics()[0]


def _build_topics() -> dict:
    """Every track (template pack), each with Mixed and its topics. A track with no
    accepted templates is listed as not available ("Being added"); with no templates at
    all there is no default track and no interview can start."""
    tracks = []
    for pack, name in PACKS.items():
        if pack == quant_dev.TRACK:  # an opener and a coding round: no topic picker
            tracks.append({"id": pack, "name": name, "count": len(coding.specs(pack)), "available": quant_dev.available(bank()),
                           "topics": [], "default": None, "areas": list(AREAS[pack]), "coding": True,
                           "format": quant_dev.TOPICS_LABEL})
            continue
        found = bank().topics(pack)
        count = sum(n for _, n in found)
        options = [{"id": MIXED, "name": MIXED, "count": count}] if found else []
        options += [{"id": topic, "name": topic, "count": n} for topic, n in found]
        asked = behavioural.rows_for(pack)  # decision log 24: IB and Consulting
        if asked:
            options.append({"id": behavioural.BEHAVIOURAL, "name": behavioural.BEHAVIOURAL, "count": len(asked)})
        live = bool(options)  # Software stays coding-first: Design concepts only beside a live track
        if pack in conversational.FILES and conversational.enabled() and conversational.load(pack) and (pack == "ib" or live):
            # Decision log 30: IB "Conversational", Software "Design concepts"; each runs on its own.
            options.append({"id": conversational.TOPIC[pack], "name": conversational.TOPIC[pack], "count": len(conversational.load(pack))})
        if pack == "quant" and found and market.enabled():  # decision log 28: runs on its own, exact
            options.append({"id": market.MARKET, "name": market.MARKET, "count": 8})
        tracks.append({"id": pack, "name": name, "count": count, "available": bool(options),
                       "topics": options, "default": options[0]["id"] if options else None,
                       "areas": list(AREAS[pack]),
                       # Decision log 27: with verified specs (content/coding/), the track is always a coding round.
                       "coding": bool(coding.specs(pack))})
    open_tracks = [t["id"] for t in tracks if t["available"]]
    default = DEFAULT_PACK if DEFAULT_PACK in open_tracks else open_tracks[0] if open_tracks else None
    # Easy and Medium are chosen in setup; Hard is the start for a rating of 70+ (decision log 23).
    return {"tracks": tracks, "default_track": default, "levels": list(DIFFICULTIES),
            "default_level": START_LEVELS[0]}


def selection(pack, topic) -> tuple[dict, str | tuple[str, ...]]:
    """The track (an unavailable one falls back to the default) and the chosen topics:
    a list of the track's topics, one topic, or None / Mixed for all of them. Unknown
    topics are rejected."""
    found = topics()
    if found["default_track"] is None:
        raise VoiceError("No questions are available yet.")
    track = next((t for t in found["tracks"] if t["id"] == pack and t["available"]), None) \
        or next(t for t in found["tracks"] if t["id"] == found["default_track"])
    known = {option["id"] for option in track["topics"]}
    if topic is None:
        return track, track["default"]
    chosen = [topic] if isinstance(topic, str) else topic
    if not isinstance(chosen, list) or not chosen:
        raise VoiceError("Choose at least one topic.")
    if not all(isinstance(t, str) and t in known for t in chosen):
        raise VoiceError("Choose topics from this track.")
    for solo in (behavioural.BEHAVIOURAL, market.MARKET, *conversational.TOPIC.values()):
        if solo in chosen:
            if len(chosen) > 1:
                raise VoiceError("Behavioural questions run on their own; choose them without other topics."
                                 if solo == behavioural.BEHAVIOURAL else f"{solo} runs on its own; choose it without other topics.")
            return track, solo
    forge = known - {MIXED, behavioural.BEHAVIOURAL, market.MARKET, *conversational.TOPIC.values()}
    if MIXED in chosen or set(chosen) == forge:
        return track, MIXED
    return track, tuple(dict.fromkeys(chosen))


def placement_for(pack) -> tuple[str, Interview]:
    """Placement (decision log 23): five questions from five strength areas, from Medium."""
    track, _ = selection(pack, None)
    return track["id"], PlacementInterview(source=PlacementSource(bank(), track["id"]))


def topic_label(pack, topic) -> str:
    """For the report header: the selected topics, or "All topics"."""
    _, chosen = selection(pack, topic)
    return "All topics" if chosen == MIXED else chosen if isinstance(chosen, str) else ", ".join(chosen)


def interview_for(pack, topic, level) -> Interview:
    """A forge interview on the chosen track and topics."""
    track, chosen = selection(pack, topic)
    if chosen in {behavioural.BEHAVIOURAL, market.MARKET, *conversational.TOPIC.values()}:
        raise VoiceError(f"{chosen} is not a forge interview.")
    if level not in DIFFICULTIES:
        raise VoiceError("Choose a starting level: Easy, Medium or Hard.")
    return Interview(source=BankSource(bank(), chosen, level, pack=track["id"]))


def conditions(begin: dict, mode: str) -> str:
    """Decision log 20: "exam" (camera and microphone checked before Start), "typed" (the
    "Can't use a camera or mic?" practice mode, not exam conditions) or "replay"."""
    if mode == "replay":
        return "replay"
    return "typed" if begin.get("typed_practice") is True else "exam"


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


_FORGE: tuple[Bank, bytes] | None = None


@router.get("/forge")
def forge_catalogue():
    """Every family by track: topic, variants checked, wrong methods verified, and totals."""
    global _FORGE
    if _FORGE is None or _FORGE[0] is not bank():
        from app.provenance import catalogue
        _FORGE = (bank(), json.dumps(catalogue(bank().templates), separators=(",", ":")).encode())
    return Response(_FORGE[1], media_type="application/json", headers={"Cache-Control": "public, max-age=300"})


@router.get("/topics")
def topic_list():
    """Tracks with accepted templates; each lists Mixed and its topics with counts. Served
    from the response built at startup; browsers may keep it for five minutes."""
    return Response(cached_topics()[1], media_type="application/json", headers={"Cache-Control": "public, max-age=300"})


@router.get("/{session_id}/report")
def report(session_id: str):
    """The in-app report (decision log 8). Sessions live in memory only, so a report
    is gone after a restart or once MAX_SESSIONS newer sessions exist."""
    session = SESSIONS.get(session_id)
    if session is None:
        raise HTTPException(404, "This report is no longer available.")
    if isinstance(session, DrillSession):
        return interview_report.build_drill(session)
    if isinstance(session, coding.CodingSession):
        return coding.report(session)
    if isinstance(session, behavioural.BehaviouralSession):
        return behavioural.report(session)
    if isinstance(session, market.MarketSession):
        return market.report(session)
    if isinstance(session, conversational.ConversationalSession):
        return conversational.report(session)
    if isinstance(session, quant_dev.QuantDevSession):
        return quant_dev.report(session, bank().templates)
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
                kind, value = await receive(False)
                if kind == "speech":
                    return value

        async def next_event() -> dict:
            """Coding rounds: the next utterance, or a code run, typing pause or submit."""
            await socket.send_json({"type": "state", "value": "listening"})
            kind, value = await receive(True)
            return {"type": "speech", "text": value} if kind == "speech" else value

        async def receive(codes: bool):
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
                if codes and kind in {"code_run", "code_pause", "code_edit", "code_submit"}:
                    if len(json.dumps(control)) <= 400_000:
                        return "control", control
                    await socket.send_json({"type": "error", "message": "That code or its results are too large to check."})
                    continue
                if kind == "typed":
                    text = control.get("transcript")
                    if isinstance(text, str) and text.strip() and len(text) <= 20_000:
                        return "speech", text.strip()
                    await socket.send_json({"type": "error", "message": "Enter a nonempty answer of at most 20,000 characters."})
                    continue
                if kind == "capture":
                    try:
                        start = {**control, "type": "start", "hands_free": True}
                        text, model = await realtime_answer(socket, provider, start,
                                                            voice_routes.silence_threshold(), replay_speed(),
                                                            silence_check=session.silence_check,
                                                            turn_policy=getattr(session, "turn_policy", lambda: None)(),
                                                            keywords=getattr(session, "keywords", list)())
                    except VoiceError as error:
                        await socket.send_json({"type": "error", "message": str(error)})
                        await socket.send_json({"type": "state", "value": "listening"})
                        continue
                    await socket.send_json({"type": "transcription_model", "model": model})
                    return "speech", text
                if kind == "mic_failed" and session.conditions == "exam":
                    # Decision log 20: the microphone failed after Start, so the rest is typed practice.
                    session.conditions = "typed"
                    continue
                # interviewer_speaking and other controls outside a capture: nothing to do

        def coding_round(track, topics, deadline):
            """A coding interview (decision log 29): up to three problems from the track's specs."""
            def steps_for(spec):
                family = bank().templates.get(spec["template_id"])
                return [s.name for s in family.instances[0].steps] if family and family.instances else []

            def more():  # the next problem, never one already asked
                spec = coding.pick(track, topics, exclude=[p.spec["template_id"] for p in round_.problems])
                return (spec, steps_for(spec)) if spec else None

            spec = coding.pick(track, topics)
            round_ = coding.CodingSession(socket.send_json, listen, next_event, provider, spec, track, deadline=deadline,
                                          steps=steps_for(spec), more=more)
            if track == "software" and conversational.enabled() and conversational.load("software"):
                round_.design = conversational.ConversationalSession(socket.send_json, listen, provider, "software", count=1)
                round_.design.ends_session = False
            return round_

        deadline = time.monotonic() + SESSION_SECONDS
        if begin.get("drill") is not None:
            session = drill_for(begin["drill"], socket.send_json, listen, VoiceAnalyzer(provider), deadline)
        elif begin.get("placement") is True:
            track, interview = placement_for(begin.get("pack"))
            session = ExamSession(socket.send_json, listen, VoiceAnalyzer(provider), interview, deadline=deadline)
            session.track, session.placement, session.topics = track, True, "Placement: one question per strength area"
        elif selection(begin.get("pack"), begin["topics"] if begin.get("topics") is not None else begin.get("topic"))[1] \
                in conversational.TOPIC.values():
            # Decision log 30: conversational questions (the behavioural flow plus a twist), on their own.
            track = selection(begin.get("pack"), None)[0]["id"]
            session = conversational.ConversationalSession(socket.send_json, listen, provider, track, deadline=deadline)
        elif begin.get("pack") == quant_dev.TRACK and quant_dev.available(bank()):
            # A spoken opener (probability or expectations), then the coding round on quant_dev families.
            deadline = time.monotonic() + coding.INTERVIEW_SECONDS
            session = quant_dev.QuantDevSession(socket.send_json, listen, next_event, provider, VoiceAnalyzer(provider), bank(),
                                                coding_round(quant_dev.TRACK, None, deadline), deadline=deadline)
        elif coding.specs(selection(begin.get("pack"), None)[0]["id"]):
            # Decision log 27: a track with coding specs (Software) is always a coding round (Python).
            track = selection(begin.get("pack"), None)[0]["id"]
            topics = begin.get("topics") if isinstance(begin.get("topics"), list) else None
            deadline = time.monotonic() + coding.INTERVIEW_SECONDS  # a 45-minute coding interview
            session = coding_round(track, topics, deadline)
        elif selection(begin.get("pack"), begin["topics"] if begin.get("topics") is not None else begin.get("topic"))[1]                 == market.MARKET:
            # Decision log 28: market making, graded exactly; no engine label.
            session = market.MarketSession(socket.send_json, listen, provider, deadline=deadline)
        elif selection(begin.get("pack"), begin["topics"] if begin.get("topics") is not None else begin.get("topic"))[1]                 == behavioural.BEHAVIOURAL:
            # Decision log 24: model-judged, not exact; no engine label.
            track = selection(begin.get("pack"), behavioural.BEHAVIOURAL)[0]["id"]
            session = behavioural.BehaviouralSession(socket.send_json, listen, provider, track, deadline=deadline)
        else:
            # "topics" (a list) is what the page sends; a single "topic" or none (all) still works.
            chosen = begin["topics"] if begin.get("topics") is not None else begin.get("topic")
            interview = interview_for(begin.get("pack"), chosen, begin.get("level", START_LEVELS[0]))
            session = ExamSession(socket.send_json, listen, VoiceAnalyzer(provider), interview, deadline=deadline)
            session.topics = topic_label(begin.get("pack"), chosen)
            session.track = selection(begin.get("pack"), chosen)[0]["id"]
        session.conditions = conditions(begin, provider.mode)
        session_id = keep(session)
        long = isinstance(session, (coding.CodingSession, quant_dev.QuantDevSession))
        await socket.send_json({"type": "session", "id": session_id, "mode": provider.mode,
                                "session_seconds": coding.INTERVIEW_SECONDS if long else SESSION_SECONDS,
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
