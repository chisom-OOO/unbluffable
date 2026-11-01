"""Exam Room interview socket. One in-memory session per connection; nothing is
persisted here and audio is never stored. Turn-taking reuses
voice.relay.realtime_answer; the analysis is app.interview_session's own."""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import secrets
import time
from collections import OrderedDict
from contextlib import suppress

from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect

from app import behavioural, byoq, coding, conversational, interview_report, market, mixed, quant_dev, roles, voice_routes
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
CASE_SECONDS = 30 * 60  # decision log 30: a full consulting case
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
        if pack == quant_dev.TRACK:  # setup redesign: Quantitative Development is a Quant role, not a track
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
                       # Decision log 37: the order a mixed interview runs in, for the setup note.
                       "mix": mixed.mix_view(pack),
                       # Decision log 27: with verified specs (content/coding/), the track is always a coding round.
                       "coding": bool(coding.specs(pack)),
                       # Setup redesign: the track's target roles, each with its live topic chips by tier.
                       "roles": [roles.view(bank(), r) for r in roles.roles_for(pack)]})
    open_tracks = [t["id"] for t in tracks if t["available"]]
    default = DEFAULT_PACK if DEFAULT_PACK in open_tracks else open_tracks[0] if open_tracks else None
    # Easy and Medium are chosen in setup; Hard is the start for a rating of 70+ (decision log 23).
    return {"tracks": tracks, "default_track": default, "levels": list(DIFFICULTIES),
            "default_level": START_LEVELS[0]}


# Topic ids (pack-based setup) that are a format of their own, and the format each runs as.
SPECIAL_TOPICS = {behavioural.BEHAVIOURAL: "behavioural", market.MARKET: "market",
                  conversational.TOPIC["ib"]: "conversational", conversational.TOPIC["software"]: "design"}


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
    picked = tuple(dict.fromkeys(chosen))
    if any(t in SPECIAL_TOPICS for t in picked):
        # Decision log 37: a special topic alone runs on its own; with others, a mixed interview.
        return track, picked[0] if len(picked) == 1 else picked
    forge = known - {MIXED, behavioural.BEHAVIOURAL, market.MARKET, *conversational.TOPIC.values()}
    if MIXED in chosen or set(chosen) == forge:
        return track, MIXED
    return track, tuple(dict.fromkeys(chosen))


def role_session(begin, send, listen, next_event, provider, deadline, coding_round):
    """A role-based start (setup redesign): the chosen chips, or none for the role-weighted mix
    (about 70% Core, 25% Supporting, 5% Specialist). A special chip (market making, behavioural,
    conversational, design concepts) runs on its own."""
    role = roles.BY_ID.get(begin.get("role"))
    track = selection(begin.get("pack"), None)[0]["id"]
    if role is None or role.track != track:
        raise VoiceError("Choose a role for this track.")
    view = roles.view(bank(), role)
    if not view["available"]:
        raise VoiceError("Questions for this role are being added.")
    live = {c["id"]: c for c in view["chips"]}
    chosen = begin.get("topics") or []
    if not isinstance(chosen, list) or any(c not in live for c in chosen):
        raise VoiceError("Choose topics from this role.")
    special = [live[c]["kind"] for c in chosen if live[c]["kind"] != "topic"]
    label = (", ".join(chosen) if chosen else "Role-weighted mix") + f" ({role.name})"
    level = begin.get("level", START_LEVELS[0])
    if level not in DIFFICULTIES:
        raise VoiceError("Choose a starting level: Easy, Medium or Hard.")
    if role.coding:
        deadline = time.monotonic() + coding.INTERVIEW_SECONDS  # a 45-minute coding interview (decision log 29)
    if role.opener:  # Quantitative Development: the spoken opener, then the coding round
        pack = quant_dev.TRACK if coding.specs(quant_dev.TRACK) else "software"
        code_topics = sorted({t for c in chosen if c in roles.QD for t in roles.QD[c].topics}) or None
        opener = sorted({t for c in chosen if c in roles.Q for t in roles.Q[c].topics}) or None
        session = quant_dev.QuantDevSession(send, listen, next_event, provider, VoiceAnalyzer(provider), bank(),
                                            coding_round(pack, code_topics, deadline), deadline=deadline,
                                            track=track, opener_choice=opener)
        session.opener.role = session.coding.role = role
    elif special and len(chosen) > 1 and role.coding:
        # Decision log 37: Software mixes inside the coding round (design concepts after the code).
        topics = sorted({t for tier, c in roles.topic_chips(role, chosen) for t in c.topics}) or None
        session = coding_round(track, topics, deadline, None if topics else roles.weights(role, roles.live_topics(bank(), role)),
                               design_questions=mixed.FORMATS["design"].count)
    elif special and len(chosen) > 1:
        # Decision log 37: special formats with regular topics, or with each other, in one interview.
        forge_chips = [c for c in chosen if live[c]["kind"] == "topic"]
        formats = {mixed.KIND_FORMAT[k] for k in special} | ({"forge"} if forge_chips else set())
        case_chips = [x for tier, xs in role.tiers() for x in xs if x.id in chosen and x.kind == roles.CASES]
        types = [x.case_type for x in case_chips]
        case_type = None if not types or None in types else random.choice(types)  # "Full case": any type

        def forge_interview():
            return Interview(source=roles.weighted_source(bank(), role, level, random.Random(), forge_chips, pack=track)[0])

        session = mixed_session(send, listen, provider, track, formats, forge_interview,
                                f"{', '.join(forge_chips)} ({role.name})", label, case_type)
    elif special:
        kind = special[0]
        if kind == roles.MARKET:
            session = market.MarketSession(send, listen, provider, deadline=deadline)
        elif kind == roles.BEHAVIOURAL:
            session = behavioural.BehaviouralSession(send, listen, provider, track, deadline=deadline)
        elif kind in {roles.CONVERSATIONAL, roles.DESIGN}:
            session = conversational.ConversationalSession(send, listen, provider, "ib" if kind == roles.CONVERSATIONAL else "software",
                                                           deadline=deadline)
        elif kind == roles.CASES:  # decision log 30: a full case, or one of a case type
            from app import cases
            chip = next(c for tier, cs in role.tiers() for c in cs if c.id == chosen[0])
            session = cases.CaseSession(send, listen, provider, deadline=time.monotonic() + CASE_SECONDS, case_type=chip.case_type)
        else:
            raise VoiceError("That format isn't available yet.")
    elif role.coding:  # Software: the chips filter coding problems; none = weighted by tier
        topics = sorted({t for tier, c in roles.topic_chips(role, chosen) for t in c.topics}) if chosen else None
        session = coding_round(track, topics, deadline, None if chosen else roles.weights(role, roles.live_topics(bank(), role)),
                               design_questions=role.design_questions)
    else:
        source, _ = roles.weighted_source(bank(), role, level, random.Random(), chosen or None, pack=track)
        session = ExamSession(send, listen, VoiceAnalyzer(provider), Interview(source=source), deadline=deadline)
    session.track, session.role = track, role
    if not role.opener and (not special or len(chosen) > 1):
        session.topics = label
    return session


def mixed_session(send, listen, provider, track: str, formats, forge_interview, forge_label: str, topics: str,
                  case_type: str | None = None) -> mixed.MixedSession:
    """Decision log 37: one interview from several formats, each run by its own session, in the
    track's default order, sharing the interview's usual length (a case's when one is chosen)."""
    guard = mixed.Guard(listen)
    total = CASE_SECONDS if "cases" in formats else SESSION_SECONDS
    segments = []
    for f in mixed.order(track, formats):
        count = mixed.FORMATS[f].count
        if f == "forge":
            session = ExamSession(send, guard.listen, VoiceAnalyzer(provider), forge_interview())
            session.topics = forge_label
        elif f == "market":
            session = market.MarketSession(send, guard.listen, provider)
            session.rounds = session.rounds[:count]
        elif f == "behavioural":
            session = behavioural.BehaviouralSession(send, guard.listen, provider, track)
            session.asked = session.asked[:count]
        elif f == "conversational":
            session = conversational.ConversationalSession(send, guard.listen, provider, "ib", count=count)
        elif f == "cases":
            from app import cases
            session = cases.CaseSession(send, guard.listen, provider, case_type=case_type)
        else:
            raise VoiceError("That format can't be mixed yet.")
        segments.append(mixed.Segment(f, session))
    return mixed.MixedSession(send, segments, time.monotonic() + total, track, topics, guard=guard, session_seconds=total)


def legacy_mix(begin: dict):
    """The pack-based start (no role): a mix of forge topics and special ones, or None. Returns a
    builder taking (send, listen, provider)."""
    if begin.get("role") is not None or begin.get("placement") is True or begin.get("drill") is not None:
        return None
    chosen = begin["topics"] if begin.get("topics") is not None else begin.get("topic")
    track, picked = selection(begin.get("pack"), chosen)
    if coding.specs(track["id"]) or not isinstance(picked, tuple) or not any(t in SPECIAL_TOPICS for t in picked):
        return None
    forge = [t for t in picked if t not in SPECIAL_TOPICS]
    formats = {SPECIAL_TOPICS[t] for t in picked if t in SPECIAL_TOPICS} | ({"forge"} if forge else set())
    level = begin.get("level", START_LEVELS[0])

    def forge_interview():
        return interview_for(track["id"], forge, level)

    return lambda send, listen, provider: mixed_session(send, listen, provider, track["id"], formats, forge_interview,
                                                         topic_label(track["id"], forge) if forge else "", ", ".join(picked))


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
    if getattr(session, "byoq", None) is not None:
        return byoq.report(session, interview_report.build)  # decision log 38: never rated
    if isinstance(session, DrillSession):
        return interview_report.build_drill(session)
    if isinstance(session, mixed.MixedSession):
        return mixed.report(session, bank().templates)
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
    from app import cases
    if isinstance(session, cases.CaseSession):
        return cases.report(session)
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


def byoq_session(token, send, listen, analyzer, deadline: float) -> ExamSession:
    """Decision log 38: the candidate's own checked question, then its twin. Not rated."""
    found = byoq.accepted(token)
    if found is None:
        raise VoiceError("That question is no longer available. Upload it again.")
    template, variants = found
    session = ExamSession(send, listen, analyzer, Interview(source=byoq.ByoqSource(template)), deadline=deadline)
    session.byoq = (template, variants)
    session.topics = byoq.line(variants)
    return session


def family_session(template_id, send, listen, analyzer, deadline: float) -> ExamSession:
    """One shipped family (offered when a candidate's own question can't be checked): its
    question and twin, scored and rated like any forge interview."""
    template = bank().templates.get(template_id) if isinstance(template_id, str) else None
    if template is None or template.template_id in bank().hidden:
        raise VoiceError("That question is no longer available.")
    session = ExamSession(send, listen, analyzer, Interview(source=BankSource(Bank({template_id: template}), MIXED,
                          template.difficulty, pack=template.pack)), deadline=deadline)
    session.track, session.topics = template.pack, template.topic
    return session


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
                                                            keywords=getattr(session, "keywords", list)(),
                                                            silence_prompts=getattr(session, "silence_prompts", lambda: None)())
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

        def coding_round(track, topics, deadline, weights=None, design_questions=1):
            """A coding interview (decision log 29): up to three problems from the track's specs;
            `weights`: a role-weighted mix over topics (setup redesign)."""
            def steps_for(spec):
                family = bank().templates.get(spec["template_id"])
                return [s.name for s in family.instances[0].steps] if family and family.instances else []

            def more():  # the next problem, never one already asked
                spec = coding.pick(track, topics, exclude=[p.spec["template_id"] for p in round_.problems], weights=weights)
                return (spec, steps_for(spec)) if spec else None

            spec = coding.pick(track, topics, weights=weights)
            round_ = coding.CodingSession(socket.send_json, listen, next_event, provider, spec, track, deadline=deadline,
                                          steps=steps_for(spec), more=more)
            if track == "software" and conversational.enabled() and conversational.load("software"):
                round_.design = conversational.ConversationalSession(socket.send_json, listen, provider, "software",
                                                                     count=design_questions, deadline=deadline)
                round_.design.ends_session = False
            return round_

        deadline = time.monotonic() + SESSION_SECONDS
        if begin.get("byoq") is not None:
            session = byoq_session(begin["byoq"], socket.send_json, listen, VoiceAnalyzer(provider), deadline)
        elif begin.get("family") is not None:
            session = family_session(begin["family"], socket.send_json, listen, VoiceAnalyzer(provider), deadline)
        elif begin.get("drill") is not None:
            session = drill_for(begin["drill"], socket.send_json, listen, VoiceAnalyzer(provider), deadline)
        elif begin.get("role") is not None and begin.get("placement") is not True:
            session = role_session(begin, socket.send_json, listen, next_event, provider, deadline, coding_round)
        elif begin.get("placement") is True:
            track, interview = placement_for(begin.get("pack"))
            session = ExamSession(socket.send_json, listen, VoiceAnalyzer(provider), interview, deadline=deadline)
            session.track, session.placement, session.topics = track, True, "Placement: one question per strength area"
        elif selection(begin.get("pack"), begin["topics"] if begin.get("topics") is not None else begin.get("topic"))[1] \
                in conversational.TOPIC.values():
            # Decision log 30: conversational questions (the behavioural flow plus a twist), on their own.
            track = selection(begin.get("pack"), None)[0]["id"]
            session = conversational.ConversationalSession(socket.send_json, listen, provider, track, deadline=deadline)
        elif legacy_mix(begin) is not None:
            # Decision log 37: special topics mixed with forge topics, or with each other.
            session = legacy_mix(begin)(socket.send_json, listen, provider)
        elif begin.get("pack") == quant_dev.TRACK and quant_dev.available(bank()):
            # A spoken opener (probability or expectations), then the coding round on quant_dev families.
            deadline = time.monotonic() + coding.INTERVIEW_SECONDS
            session = quant_dev.QuantDevSession(socket.send_json, listen, next_event, provider, VoiceAnalyzer(provider), bank(),
                                                coding_round(quant_dev.TRACK, None, deadline), deadline=deadline)
        elif coding.specs(selection(begin.get("pack"), None)[0]["id"]):
            # Decision log 27: a track with coding specs (Software) is always a coding round (Python).
            track = selection(begin.get("pack"), None)[0]["id"]
            topics = begin.get("topics") if isinstance(begin.get("topics"), list) else None
            topics = [t for t in topics or [] if t not in SPECIAL_TOPICS] or None  # design concepts follow the code anyway
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
        case = type(session).__name__ == "CaseSession"
        seconds = getattr(session, "session_seconds", None) or (
            coding.INTERVIEW_SECONDS if long else CASE_SECONDS if case else SESSION_SECONDS)
        await socket.send_json({"type": "session", "id": session_id, "mode": provider.mode,
                                "session_seconds": seconds,
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
