"""One browser recording → one merged answer, never a mid-sentence challenge."""

import asyncio
from contextlib import suppress
import json
import math
import time

from voice.provider import ASR, KEYWORDS, REALTIME, api_key, metadata
from voice.recording import VoiceError, redact
from voice.turns import AnswerMerger


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


async def realtime_answer(browser, provider, start, silence_s=1.8, replay_speed=1, connect=None):
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
                        raise VoiceError("Unknown recording control.")

            async def wait_for_silence():
                while True:
                    changed.clear()
                    remaining = merger.remaining(asyncio.get_running_loop().time() - audio_start)
                    if remaining == 0:
                        return "silence"
                    try:
                        await asyncio.wait_for(changed.wait(), remaining)
                    except TimeoutError:
                        return "silence"

            reader = asyncio.create_task(receive_provider())
            writer = asyncio.create_task(receive_browser())
            timer = asyncio.create_task(wait_for_silence())
            tasks = [reader, writer, timer]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if reader in done:
                await reader
                reason = "stream_end"
            else:
                reason = await (writer if writer in done else timer)
                writer.cancel()
                with suppress(asyncio.CancelledError):
                    await writer
                await browser.send_json({"type": "capture_stopped"})
                await upstream.send(json.dumps({"type": "endStream"}))
                await asyncio.wait_for(reader, 30)
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
