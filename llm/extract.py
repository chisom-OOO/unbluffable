"""Muse Spark extraction with the strict schema (spec/03).

`strict: true`, `reasoning_effort: "low"`, a 4,000-token cap, and any finish
other than "stop" is a failure. Code finds every quote verbatim in the
transcript and drops the rest; outcomes are decided by llm.score / engine.coding.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from engine.templates import Puzzle
from llm.backends import BackendUnavailable, get_backend
from llm.client import STANDARD_MODEL, assert_standard_model
from llm.prompt import build_messages
from llm.replay import CallStore
from llm.schema import EXTRACTION_SCHEMA, SCHEMA_NAME, SchemaError, validate_extraction

MAX_TOKENS = 4000
MODES = ("live", "replay")


@dataclass(frozen=True)
class Quote:
    quote: str
    step: str


@dataclass(frozen=True)
class ExtractionResult:
    ok: bool
    error: str | None = None
    extraction: dict | None = None
    quotes: tuple[Quote, ...] = field(default=())  # found verbatim in the transcript
    dropped_quotes: tuple[Quote, ...] = field(default=())  # not found verbatim
    committed_text: str | None = None  # None when the model said "none"
    committed_verbatim: bool = False
    latency_s: float | None = None
    run_id: str | None = None
    replayed: bool = False
    backend: str = ""


def build_request(puzzle: Puzzle, transcript: str, model: str = STANDARD_MODEL) -> dict:
    assert_standard_model(model)
    return {
        "model": model,
        "messages": build_messages(puzzle, transcript),
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": SCHEMA_NAME, "strict": True, "schema": EXTRACTION_SCHEMA},
        },
        "reasoning_effort": "low",
        "max_tokens": MAX_TOKENS,
    }


def extract(
    puzzle: Puzzle,
    transcript: str,
    *,
    mode: str | None = None,
    backend=None,
    store: CallStore | None = None,
) -> ExtractionResult:
    """Run (live) or look up (replay) one extraction. Never raises for model failures."""
    mode = mode or os.environ.get("LLM_MODE", "replay")
    if mode not in MODES:
        raise ValueError(f"LLM_MODE must be one of {MODES}, not {mode!r}")
    backend = backend or get_backend()
    store = store or CallStore()
    request = build_request(puzzle, transcript)
    meta = {"backend": backend.name, "replayed": mode == "replay"}

    if mode == "replay":
        record = store.load(backend.name, request)
        if record is None:
            return ExtractionResult(ok=False, error="replay_missing", **meta)
    else:
        start = time.perf_counter()
        try:
            response = backend.complete(request)
        except BackendUnavailable:
            return ExtractionResult(ok=False, error="backend_unavailable", **meta)
        except Exception as exc:  # exception text can echo request details: keep only the type
            return ExtractionResult(ok=False, error=f"call_failed:{type(exc).__name__}", **meta)
        record = store.save(backend.name, request, response, time.perf_counter() - start)

    meta |= {"latency_s": record["latency_s"], "run_id": record["run_id"]}
    return _parse(record["response"], transcript, meta)


def _parse(response: dict, transcript: str, meta: dict) -> ExtractionResult:
    choices = response.get("choices") or []
    if not choices:
        return ExtractionResult(ok=False, error="no_choices", **meta)
    choice = choices[0]
    finish = choice.get("finish_reason")
    if finish != "stop":
        return ExtractionResult(ok=False, error=f"finish_{finish}", **meta)
    message = choice.get("message") or {}
    if message.get("refusal"):
        return ExtractionResult(ok=False, error="refusal", **meta)
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return ExtractionResult(ok=False, error="empty_content", **meta)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return ExtractionResult(ok=False, error="invalid_json", **meta)
    try:
        validate_extraction(parsed)
    except SchemaError:
        return ExtractionResult(ok=False, error="schema_invalid", **meta)

    kept, dropped = [], []
    for row in parsed["reasoning_quotes"]:
        quote = Quote(row["quote"], row["step"])
        (kept if quote.quote.strip() and quote.quote in transcript else dropped).append(quote)
    committed = parsed["committed_answer_text"]
    committed = None if committed.strip().lower() == "none" else committed
    return ExtractionResult(
        ok=True,
        extraction=parsed,
        quotes=tuple(kept),
        dropped_quotes=tuple(dropped),
        committed_text=committed,
        committed_verbatim=committed is None or (bool(committed.strip()) and committed in transcript),
        **meta,
    )
