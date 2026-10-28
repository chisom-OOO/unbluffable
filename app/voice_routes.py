"""Voice endpoints. Client input never supplies a model API credential."""

import asyncio
from contextlib import suppress
import math
import os

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from voice.answers import QUESTION, analyse_answer, silence_commitment_check
from voice.provider import MetaVoice
from voice.recording import VoiceError
from voice.relay import realtime_answer


router = APIRouter(prefix="/api/voice")


def provider():
    return MetaVoice.configured()


def silence_threshold():
    value = float(os.environ.get("VOICE_PARTIAL_IDLE_SECONDS", "0.8"))
    if not math.isfinite(value) or value <= 0:
        raise VoiceError("VOICE_PARTIAL_IDLE_SECONDS must be finite and positive.")
    return value


@router.get("/config")
async def config():
    try:
        current = provider()
        return {"mode": current.mode, "silence_s": silence_threshold(), "question": QUESTION,
                "replays": current.store.realtime_runs() if current.mode == "replay" else []}
    except (VoiceError, ValueError) as error:
        raise HTTPException(503, "Voice configuration is unavailable.") from error


@router.post("/transcribe")
async def file_transcription(request: Request):
    audio = bytearray()
    async for chunk in request.stream():
        audio.extend(chunk)
        if len(audio) > 32_000_000:
            raise HTTPException(413, "Recording exceeds 32 MB.")
    try:
        return await provider().transcribe(bytes(audio))
    except VoiceError as error:
        raise HTTPException(422, str(error)) from None


def same_origin(socket):
    origin = socket.headers.get("origin")
    return not origin or origin.rstrip("/") in {f"http://{socket.headers.get('host')}", f"https://{socket.headers.get('host')}"}


@router.websocket("/answer")
async def typed_answer(socket: WebSocket):
    if not same_origin(socket):
        await socket.close(code=1008)
        return
    await socket.accept()
    try:
        message = await asyncio.wait_for(socket.receive_json(), 30)
        text = message.get("transcript")
        if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
            raise VoiceError("Enter a nonempty answer of at most 20,000 characters.")
        await analyse_answer(provider(), text, socket.send_json)
    except WebSocketDisconnect:
        return
    except VoiceError as error:
        with suppress(WebSocketDisconnect, RuntimeError):
            await socket.send_json({"type": "error", "message": str(error)})
    except Exception:
        with suppress(WebSocketDisconnect, RuntimeError):
            await socket.send_json({"type": "error", "message": "The answer could not be checked. Your transcript remains editable."})
    finally:
        with suppress(RuntimeError):
            await socket.close()


@router.websocket("/realtime")
async def live_answer(socket: WebSocket):
    if not same_origin(socket):
        await socket.close(code=1008)
        return
    await socket.accept()
    analyses = set()
    try:
        start = await asyncio.wait_for(socket.receive_json(), 10)
        if start.get("type") != "start":
            raise VoiceError("Start a recording before sending audio.")
        current = provider()
        speed = float(os.environ.get("VOICE_REPLAY_SPEED", "1"))
        if not math.isfinite(speed) or speed < 0:
            raise VoiceError("VOICE_REPLAY_SPEED must be finite and nonnegative.")

        async def silence_check(text):
            return await silence_commitment_check(current, text)

        while True:
            text, model = await realtime_answer(socket, current, start, silence_threshold(), speed,
                                               silence_check=silence_check)
            await socket.send_json({"type": "transcription_model", "model": model})
            if not start.get("hands_free") or current.mode == "replay":
                await analyse_answer(current, text, socket.send_json)
                break
            acknowledged = asyncio.Event()

            async def send(event, acknowledged=acknowledged):
                await socket.send_json(event)
                if event["type"] == "answer_complete":
                    acknowledged.set()

            analysis = asyncio.create_task(analyse_answer(current, text, send))
            analyses.add(analysis)
            # Enqueue the spoken acknowledgement before opening the next capture.
            acknowledgement = asyncio.create_task(acknowledged.wait())
            try:
                await asyncio.wait([analysis, acknowledgement], return_when=asyncio.FIRST_COMPLETED)
                if analysis.done():
                    await analysis
            finally:
                acknowledgement.cancel()
                with suppress(asyncio.CancelledError):
                    await acknowledgement
            for completed in list(analyses):
                if completed.done():
                    await completed
                    analyses.remove(completed)
    except WebSocketDisconnect:
        return
    except VoiceError as error:
        with suppress(WebSocketDisconnect, RuntimeError):
            await socket.send_json({"type": "error", "message": str(error)})
    except Exception:
        with suppress(WebSocketDisconnect, RuntimeError):
            await socket.send_json({"type": "error", "message": "Recording could not finish. Try file transcription or type your answer."})
    finally:
        for task in analyses:
            task.cancel()
        for task in analyses:
            with suppress(asyncio.CancelledError, Exception):
                await task
        with suppress(RuntimeError):
            await socket.close()
