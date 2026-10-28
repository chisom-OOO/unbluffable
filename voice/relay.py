"""One browser recording → one merged answer, never a mid-sentence challenge."""

import asyncio
from contextlib import suppress
import json
import math
import re
import time

from voice.provider import ASR, KEYWORDS, REALTIME, api_key, metadata
from voice.recording import VoiceError, redact
from voice.turns import AnswerMerger
from voice.endpointing import PROMPT, safe_classify


async def wait_for_endpoint(merger, provider, browser, changed, now, silence_check=None):
    """Speech keeps flowing during Spark; a newer partial invalidates its result."""
    pending = None
    snapshot = None
    silence_pending = None
    silence_snapshot = None
    try:
        while True:
            changed.clear()
            if silence_pending and (silence_snapshot != merger.revision or merger.paused):
                silence_pending.cancel()
                await asyncio.gather(silence_pending, return_exceptions=True)
                silence_pending = None
            if pending and (snapshot != merger.revision or merger.paused):
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending
                pending = None
            if pending and pending.done():
                result = await pending
                pending = None
                await browser.send_json({"type": "endpoint_decision", "finished": result.finished,
                                         "kind": result.kind, "cue": result.cue, "model": result.model})
                if result.finished and snapshot == merger.revision and not merger.paused:
                    merger.accepted_revision = snapshot
                    return result.cue
            if silence_pending and silence_pending.done():
                try:
                    committed = await silence_pending
                except VoiceError:
                    committed = False
                silence_pending = None
                if silence_snapshot == merger.revision and not merger.paused:
                    if committed:
                        await browser.send_json({"type": "endpoint_decision", "finished": True,
                                                 "kind": "answer", "cue": "silence_commitment", "model": None})
                        if silence_snapshot == merger.revision and not merger.paused:
                            merger.accepted_revision = silence_snapshot
                            return "silence_commitment"
                    else:
                        await browser.send_json({"type": "listening_prompt", "message": PROMPT})
            check = None if merger.paused else merger.remaining(now())
            if check == 0 and pending is None:
                snapshot = merger.revision
                merger.checked_revision = snapshot
                pending = asyncio.create_task(safe_classify(provider, merger.transcript))
            prompt = None if merger.paused else merger.prompt_remaining(now())
            if prompt == 0:
                merger.prompted_revision = merger.revision
                if silence_check is None:
                    await browser.send_json({"type": "listening_prompt", "message": PROMPT})
                else:
                    silence_snapshot = merger.revision
                    silence_pending = asyncio.create_task(silence_check(merger.transcript))
            delays = [value for value in (
                None if merger.paused else merger.remaining(now()),
                None if merger.paused else merger.prompt_remaining(now()),
            ) if value is not None]
            signal = asyncio.create_task(changed.wait())
            try:
                await asyncio.wait([signal] + ([pending] if pending else []) + ([silence_pending] if silence_pending else []),
                                   timeout=min(delays) if delays else None,
                                   return_when=asyncio.FIRST_COMPLETED)
            finally:
                signal.cancel()
                with suppress(asyncio.CancelledError):
                    await signal
    finally:
        if silence_pending:
            silence_pending.cancel()
            await asyncio.gather(silence_pending, return_exceptions=True)
        if pending:
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending


async def replay_realtime(browser, provider, start, silence_s, speed=1):
    record = provider.store.load(start.get("replay_id"))
    if record["kind"] != "realtime":
        raise VoiceError("Choose a realtime recorded run.")
    model = metadata(record, "replay", "transcription")
    await browser.send_json({"type": "ready", "model": model, "silence_s": silence_s})
    merger, previous = AnswerMerger(silence_s), 0
    for row in record["events"]:
        elapsed = row["elapsed_s"]
        if speed:
            await asyncio.sleep(max(0, elapsed - previous) / speed)
        previous = elapsed
        merger.feed(row["event"], elapsed)
        if row["event"].get("type") in {"transcript", "speechComplete"}:
            await browser.send_json({"type": "transcript", "transcript": merger.transcript})
    answer = merger.finish("recorded_end")
    if not answer or not answer["transcript"]:
        raise VoiceError("Recorded run contains no complete answer.")
    await browser.send_json({"type": "capture_stopped"})
    return answer["transcript"], model


async def realtime_answer(browser, provider, start, silence_s=0.8, replay_speed=1, connect=None, silence_check=None):
    if not math.isfinite(silence_s) or silence_s <= 0:
        raise VoiceError("Silence threshold must be finite and positive.")
    if provider.mode == "replay":
        return await replay_realtime(browser, provider, start, silence_s, replay_speed)
    if start.get("sample_rate", 16000) not in {16000, 24000}:
        raise VoiceError("Microphone PCM must use 16 or 24 kHz.")
    rate = start.get("sample_rate", 16000)
    key = api_key()
    settings = {"model": ASR, "audioEncoding": f"PCM_{rate // 1000}KHZ", "mode": "ENDPOINTING",
                "partialMode": "CUMULATIVE", "keywords": KEYWORDS, "emitAudioProgress": False}
    record = provider.store.create("realtime", {**settings, "silence_s": silence_s}, key)
    merger = AnswerMerger(silence_s)
    merger.paused = bool(start.get("interviewer_speaking")) and not start.get("headphones", False)
    tasks = []
    if connect is None:
        from websockets.asyncio.client import connect
    began = time.perf_counter()
    try:
        async with connect(REALTIME, open_timeout=30, close_timeout=5, max_size=2**20) as upstream:
            await upstream.send(json.dumps({**settings, "authorization": {"accessToken": "Bearer " + key}}))
            acknowledgement = json.loads(await asyncio.wait_for(upstream.recv(), 10))
            if not acknowledgement.get("sessionId") or acknowledgement.get("type") == "error":
                raise VoiceError("Transcription could not start. Try file transcription or type your answer.")
            audio_start = asyncio.get_running_loop().time()
            record.event(acknowledgement, 0)
            await browser.send_json({"type": "ready", "silence_s": silence_s,
                                     "model": metadata(record.data, "live", "transcription")})
            changed = asyncio.Event()

            async def receive_provider():
                async for raw in upstream:
                    if not isinstance(raw, str):
                        raise VoiceError("Unexpected transcription response.")
                    event = redact(json.loads(raw), key)
                    elapsed = asyncio.get_running_loop().time() - audio_start
                    record.event(event, elapsed)
                    if event.get("type") == "error":
                        raise VoiceError("Live transcription stopped. Try file transcription or type your answer.")
                    merger.feed(event, elapsed)
                    changed.set()
                    if event.get("type") == "speechStart" and not merger.paused:
                        await browser.send_json({"type": "candidate_speech"})
                    if event.get("type") in {"transcript", "speechComplete"}:
                        await browser.send_json({"type": "transcript", "transcript": merger.transcript})
                if upstream.close_code != 1000:
                    raise VoiceError("Transcription ended unexpectedly. Your partial transcript is available to edit.")

            async def receive_browser():
                sent = 0
                while True:
                    message = await browser.receive()
                    if message["type"] == "websocket.disconnect":
                        raise VoiceError("Recording disconnected.")
                    if message.get("bytes") is not None:
                        pcm = message["bytes"]
                        if not pcm or len(pcm) % 2 or len(pcm) > rate * 2:
                            raise VoiceError("Unsupported microphone frame.")
                        # The browser captures in real time; bound buffering and pace
                        # any frames that arrive in a short WebSocket burst.
                        sent += len(pcm)
                        if sent > rate * 2 * 600:
                            raise VoiceError("Recordings are limited to ten minutes.")
                        due = audio_start + (sent - len(pcm)) / (rate * 2)
                        await asyncio.sleep(max(0, due - asyncio.get_running_loop().time()))
                        await upstream.send(pcm)
                    elif message.get("text"):
                        control = json.loads(message["text"])
                        if control.get("type") == "done":
                            return "done"
                        if control.get("type") == "interviewer_speaking":
                            merger.paused = bool(control.get("value")) and not control.get("headphones", False)
                            merger.last_activity = asyncio.get_running_loop().time() - audio_start
                            merger.revision += 1
                            changed.set()
                            continue
                        raise VoiceError("Unknown recording control.")

            reader = asyncio.create_task(receive_provider())
            writer = asyncio.create_task(receive_browser())
            timer = asyncio.create_task(wait_for_endpoint(merger, provider, browser, changed,
                lambda: asyncio.get_running_loop().time() - audio_start, silence_check=silence_check))
            tasks = [reader, writer, timer]
            while True:
                done, _ = await asyncio.wait([reader, writer, timer], return_when=asyncio.FIRST_COMPLETED)
                if timer in done and writer not in done and reader not in done:
                    await timer
                    if merger.accepted_revision != merger.revision:
                        timer = asyncio.create_task(wait_for_endpoint(merger, provider, browser, changed,
                            lambda: asyncio.get_running_loop().time() - audio_start, silence_check=silence_check))
                        tasks.append(timer)
                        continue
                break
            if reader in done and writer not in done and timer not in done:
                await reader
                raise VoiceError("Transcription ended before an answer boundary. Your transcript remains editable.")
            else:
                reason = await (writer if writer in done else timer)
                decided_text = merger.transcript
                timer.cancel()
                with suppress(asyncio.CancelledError):
                    await timer
                writer.cancel()
                with suppress(asyncio.CancelledError):
                    await writer
                await browser.send_json({"type": "capture_stopped"})
                await upstream.send(json.dumps({"type": "endStream"}))
                await asyncio.wait_for(reader, 30)
                if reason != "done" and re.findall(r"\w+", decided_text.lower()) != re.findall(r"\w+", merger.transcript.lower()):
                    revised = await safe_classify(provider, merger.transcript)
                    if not revised.finished:
                        raise VoiceError("The final transcript changed during completion. Please review it or continue your answer.")
                    reason = revised.cue
            answer = merger.finish(reason)
            if not answer or not answer["transcript"]:
                raise VoiceError("No intelligible speech was found. Try again or type an answer.")
            record.finish({"transcript": answer["transcript"], "reason": reason}, latency_s=time.perf_counter() - began)
            return answer["transcript"], metadata(record.data, "live", "transcription")
    except BaseException as error:
        record.finish(error="Realtime recording failed or was cancelled.", latency_s=time.perf_counter() - began)
        if isinstance(error, asyncio.CancelledError):
            raise
        if isinstance(error, VoiceError):
            raise
        raise VoiceError("Live transcription failed. Try file transcription or type your answer.") from None
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await task
