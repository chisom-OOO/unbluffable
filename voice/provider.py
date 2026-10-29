"""Server-only Meta calls with private records and exact offline replay."""

import asyncio
import hashlib
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import wave

import logging

import httpx

from llm import backends
from llm.client import MissingKey, _key
from llm.http_diagnostics import request_id

from voice.recording import RecordStore, VoiceError, redact
from voice.schemas import ENDPOINT, ENDPOINT_PROMPT, FULL, FULL_PROMPT, MINIMAL, MINIMAL_PROMPT, validate


LOG = logging.getLogger("uvicorn.error")
BASE = "https://api.meta.ai/v1"
REALTIME = "wss://api.meta.ai/v1/asr/realtime"
SPARK = "muse-spark-1.3"
ASR = "muse-voice-transcribe-1.0"
KEYWORDS = ["fraud", "flagged", "false alarm", "base rate", "defective", "biased coin"]


def api_key():
    try:
        key = os.environ["MODEL_API_KEY"]
    except KeyError as error:
        raise VoiceError("Live mode needs MODEL_API_KEY in the server environment. Recorded replay needs no key.") from error
    key = key.strip()  # pasted keys often carry a trailing newline, which is illegal in HTTP headers
    if not key:
        raise VoiceError("The server API key is empty.")
    return key


def metadata(data, mode, job):
    response = data.get("response") or {}
    usage = response.get("usage") or {}
    inputs, outputs = usage.get("prompt_tokens"), usage.get("completion_tokens")
    cost = None
    spark = data["kind"] in {"endpoint", "minimal", "extraction"}
    model = data["request"].get("model", SPARK) if spark else ASR
    if spark and model == SPARK and type(inputs) is int and type(outputs) is int:
        cost = (inputs * 1.25 + outputs * 4.25) / 1_000_000  # spec/03 assumed rates.
    return {"model": model,
            "job": job, "effort": data["request"].get("reasoning_effort"),
            "latency_s": data.get("latency_s"), "estimated_cost_usd": cost,
            "mode": mode, "run_id": data["run_id"], "recorded_at": data["recorded_at"]}


async def convert_to_wav(audio):
    executable = os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg")
    if not executable:
        raise VoiceError("File transcription needs ffmpeg on the server. You can still type an answer.")
    with tempfile.TemporaryDirectory(prefix="unbluffable-audio-") as temporary:
        source, target = Path(temporary) / "input.audio", Path(temporary) / "output.wav"
        source.write_bytes(audio)
        process = await asyncio.create_subprocess_exec(
            executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-t", "601", "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            "-map_metadata", "-1", str(target),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            await asyncio.wait_for(process.communicate(), 30)
        except BaseException as error:
            process.kill()
            await process.communicate()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise VoiceError("Audio conversion timed out. Try a shorter recording or type your answer.") from None
        if process.returncode or not target.exists():
            raise VoiceError("Audio could not be decoded. Try another recording or type your answer.")
        wav = target.read_bytes()
    try:
        with wave.open(io.BytesIO(wav), "rb") as parsed:
            valid = (parsed.getnchannels() == 1 and parsed.getsampwidth() == 2
                     and parsed.getframerate() == 16000 and parsed.getcomptype() == "NONE"
                     and 0 < parsed.getnframes() <= 16000 * 600)
    except (wave.Error, EOFError) as error:
        raise VoiceError("Converted audio is not a supported WAV.") from error
    if not valid or len(wav) > 32_000_000:
        raise VoiceError("Recording must be at most ten minutes and 32 MB after conversion.")
    return wav


class IncompleteOutput(VoiceError):
    """A truncated/refused response must never get a schema repair."""


class MetaVoice:
    def __init__(self, mode="live", record_dir="recordings/voice", transport=None):
        if mode not in {"live", "replay"}:
            raise VoiceError("VOICE_MODE must be live or replay.")
        self.mode, self.store, self.transport = mode, RecordStore(record_dir), transport
        try:
            self.spark_backend = backends.get_backend()
        except ValueError:
            raise VoiceError("LLM_BACKEND must be meta_api or open_weights.") from None

    @classmethod
    def configured(cls):
        return cls(os.environ.get("VOICE_MODE", "live"), os.environ.get("VOICE_RECORD_DIR", "recordings/voice"))

    async def post(self, kind, request, endpoint, files=None):
        if endpoint == "/chat/completions":
            return await self.spark_post(kind, request)
        if self.mode == "replay":
            return self.store.find(kind, request)
        key = api_key()
        record = self.store.create(kind, request, key)
        start = time.perf_counter()
        body = None
        try:
            async with httpx.AsyncClient(timeout=90, follow_redirects=False, transport=self.transport) as client:
                response = await client.post(BASE + endpoint,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    **({"files": files} if files is not None else {"json": request}))
            try:
                body = redact(response.json(), key)
            except ValueError:
                LOG.warning("model call %s failed: HTTP %s, request_id=%s, non-JSON body",
                            endpoint, response.status_code, request_id(response, (key,)))
                raise VoiceError("The model request failed. Your transcript is available to edit or retry.") from None
            if response.status_code != 200 or not isinstance(body, dict) or body.get("error") or body.get("type") == "error":
                detail = body.get("error") if isinstance(body, dict) else None
                if isinstance(detail, dict):
                    detail = {k: str(detail.get(k))[:200] for k in ("type", "code", "message", "param") if k in detail}
                LOG.warning("model call %s failed: HTTP %s, request_id=%s, error=%s",
                            endpoint, response.status_code, request_id(response, (key,)), str(detail)[:400])
                raise VoiceError("The model request failed. Your transcript is available to edit or retry.")
            record.finish(body, latency_s=time.perf_counter() - start)
        except BaseException as error:
            record.finish(body, error="Model request failed or was cancelled.", latency_s=time.perf_counter() - start)
            if isinstance(error, asyncio.CancelledError):
                raise
            if isinstance(error, VoiceError):
                raise
            LOG.warning("model call %s failed before a response: %s", endpoint, type(error).__name__)
            raise VoiceError("The model request failed. Your transcript is available to edit or retry.") from None
        return record.data

    async def spark_post(self, kind, request):
        if self.mode == "replay":
            return self.store.find(kind, request)
        try:
            key = api_key() if self.spark_backend.name == "meta_api" else _key(self.spark_backend.key_variable)
        except MissingKey:
            raise VoiceError("Live mode needs BASETEN_API_KEY in the server environment. Recorded replay needs no key.") from None
        record = self.store.create(kind, request, key)
        start = time.perf_counter()
        body = None
        try:
            body = redact(await self.spark_backend.acomplete(request, transport=self.transport), key)
            record.finish(body, latency_s=time.perf_counter() - start)
        except BaseException as error:
            response = getattr(error, "response", None)
            if response is not None:
                try:
                    body = redact(response.json(), key)
                except (ValueError, TypeError):
                    pass
            record.finish(body, error="Model request failed or was cancelled.", latency_s=time.perf_counter() - start)
            if isinstance(error, asyncio.CancelledError):
                raise
            LOG.warning("model call /chat/completions failed: %s", type(error).__name__)
            raise VoiceError("The model request failed. Your transcript is available to edit or retry.") from None
        return record.data

    @staticmethod
    def structured_request(backend, text, kind, effort, schema, prompt):
        if not backend.enforces_schema:
            prompt += (" Reply with only one JSON object, with no other text or code fences, matching "
                       "this JSON Schema exactly: " + json.dumps(schema, separators=(",", ":")))
            effort = "low"  # Muse Spark Open always reasons; matches the measured probe arm.
        return {"model": backend.model, "reasoning_effort": effort, "max_tokens": 4000,
                "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
                "response_format": {"type": "json_schema", "json_schema": {"name": kind, "strict": True, "schema": schema}}}

    @staticmethod
    def parse_structured(body, schema, open_weights=False):
        try:
            choice = body["choices"][0]
            if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
                raise IncompleteOutput("Incomplete or refused model output was rejected.")
            content = choice["message"]["content"]
            if open_weights and isinstance(content, str):
                content = re.sub(r"^\s*<think>.*?</think>\s*", "", content, flags=re.DOTALL)
            parsed = json.loads(content)
            validate(parsed, schema)
            return parsed
        except (KeyError, IndexError, TypeError, ValueError):
            raise VoiceError("The model returned an invalid extraction.") from None

    async def structured(self, text, kind, effort, schema, prompt):
        if not text.strip() or len(text) > 20_000:
            raise VoiceError("Enter a nonempty answer of at most 20,000 characters.")
        backend = self.spark_backend
        request = self.structured_request(backend, text, kind, effort, schema, prompt)
        record = None
        if self.mode == "replay":
            # Prefer an exact legacy Meta request when present, independent of the
            # live switch. Existing flagship records and emitted metadata stay intact.
            candidates = [backends.get_backend("meta_api"), backend, backends.get_backend("open_weights")]
            for candidate in {item.name: item for item in candidates}.values():
                candidate_request = self.structured_request(candidate, text, kind, effort, schema, prompt)
                try:
                    record = self.store.find(kind, candidate_request)
                except VoiceError:
                    continue
                backend, request = candidate, candidate_request
                break
            if record is None:
                raise VoiceError("No recorded result matches this answer. Use an existing replay or live mode.")
        if record is None:
            record = await self.post(kind, request, "/chat/completions")
        repaired = False
        first_latency = 0
        try:
            parsed = self.parse_structured(record["response"], schema, not backend.enforces_schema)
        except IncompleteOutput:
            raise
        except VoiceError:
            if backend.enforces_schema:
                raise
            # Open weights does not enforce the schema. One repair only; both
            # HTTP calls have their own exact request/response record for replay.
            repaired = True
            first_latency = record.get("latency_s") or 0
            try:
                previous = record["response"]["choices"][0]["message"].get("content")
            except (KeyError, IndexError, TypeError):
                previous = None
            repair = {**request, "messages": [*request["messages"],
                {"role": "assistant", "content": previous if isinstance(previous, str) else ""},
                {"role": "user", "content": "Your previous reply was invalid JSON for the requested schema. Reply again with only one JSON object matching the JSON Schema in the system message."}]}
            record = await self.post(kind, repair, "/chat/completions")
            parsed = self.parse_structured(record["response"], schema, True)
        model = metadata(record, self.mode, kind)
        if not backend.enforces_schema:
            model["repaired"] = repaired
            model["latency_s"] = first_latency + (model["latency_s"] or 0)
        return parsed, model

    async def endpoint(self, text):
        return await self.structured(text, "endpoint", "minimal", ENDPOINT, ENDPOINT_PROMPT)

    async def extract(self, text, full=False):
        kind, effort = ("extraction", "low") if full else ("minimal", "minimal")
        schema, prompt = (FULL, FULL_PROMPT) if full else (MINIMAL, MINIMAL_PROMPT)
        parsed, model = await self.structured(text, kind, effort, schema, prompt)
        if full:
            parsed["reasoning_quotes"] = [row for row in parsed["reasoning_quotes"] if row["quote"] and row["quote"] in text]
            if parsed["committed_answer_text"] not in text:
                parsed["committed_answer_text"] = "none"
            if not parsed["reasoning_quotes"]:
                parsed["reasoning_code"] = "vague"
        else:
            span = parsed["committed_number_text"]
            if not parsed["is_commitment"]:
                parsed["committed_number_text"] = "none"
            elif not span or span == "none" or span not in text:
                raise VoiceError("The committed number was not found verbatim in your answer.")
        return parsed, model

    async def transcribe(self, audio):
        if not audio or len(audio) > 32_000_000:
            raise VoiceError("Choose a nonempty recording no larger than 32 MB.")
        settings = {"model": ASR, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
        request = {"audio_sha256": hashlib.sha256(audio).hexdigest(), "settings": settings}
        if self.mode == "replay":
            record = self.store.find("file", request)
        else:
            wav = await convert_to_wav(audio)
            record = await self.post("file", request, "/asr/transcribe", files={
                "request": (None, json.dumps(settings), "application/json"),
                "audio": ("answer.wav", wav, "audio/wav"),
            })
        transcript = record["response"].get("transcript")
        if not isinstance(transcript, str) or not transcript.strip():
            raise VoiceError("No intelligible speech was found. Edit the transcript or type your answer.")
        return {"transcript": transcript, "editable": True, "model": metadata(record, self.mode, "transcription")}
