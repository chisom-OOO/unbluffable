"""Allowlisted endpoint telemetry. Times are ms relative to the last partial.

Browser SpeechSynthesis provides onstart, not audio bytes. Browser stages use
the answer_complete receipt as an anchor and exclude its network transit time.
Missing/bypassed stages stay null; no candidate text is retained here.
"""

import json
import logging
import math
import re
import time
import uuid


logger = logging.getLogger("uvicorn.error")
STAGES = (
    "last_partial_received", "partial_idle_fired", "endpoint_decision_started",
    "endpoint_decision_finished", "end_stream_sent", "final_transcript_received",
    "acknowledgement_audio_first_byte", "checking_working_shown",
    "acknowledgement_speech_started",
)
CUES = {"empty", "trailing_filler_or_clause", "thinking_request", "explicit_closer",
        "help_request", "clarify_request", "model_unavailable", "done", "pending",
        "spark_answer", "spark_question", "spark_help", "spark_thinking"}


def log_event(event):
    logger.info("endpoint_decision %s", json.dumps(event, allow_nan=False))


class EndpointTiming:
    def __init__(self):
        self.last_partial = None
        self.last_final = None
        self.origin = None
        self.decision_id = None
        self.stages = dict.fromkeys(STAGES)
        self.finished, self.kind, self.cue = False, "thinking", "pending"
        self.clock = time.perf_counter

    def partial(self, at):
        self.last_partial = at

    def final(self, at):
        self.last_final = at
        if self.origin is not None and at >= self.origin:
            self.mark("final_transcript_received", at)

    def begin(self, at, idle=False):
        self.origin = self.last_partial
        self.decision_id = uuid.uuid4().hex
        self.stages = dict.fromkeys(STAGES)
        self.finished, self.kind, self.cue = False, "thinking", "pending"
        if self.origin is not None:
            self.stages["last_partial_received"] = 0
            if self.last_final is not None and self.last_final >= self.origin:
                self.mark("final_transcript_received", self.last_final)
        if idle:
            self.mark("partial_idle_fired", at)
        self.mark("endpoint_decision_started", at)

    def mark(self, stage, at):
        if self.origin is not None:
            self.stages[stage] = round((at - self.origin) * 1000, 3)

    def decision(self, result, at):
        self.finished, self.kind, self.cue = result.finished, result.kind, result.cue
        self.mark("endpoint_decision_finished", at)

    def event(self, phase, at):
        return {"type": "endpoint_decision", "decision_id": self.decision_id,
                "phase": phase, "finished": self.finished, "kind": self.kind, "cue": self.cue,
                "timing_ms": dict(self.stages),
                "observed_at_ms": round((at - self.origin) * 1000, 3) if self.origin is not None else None,
                "audio_first_byte_status": "unavailable_browser_speech_synthesis",
                "browser_clock": "answer_complete_receipt_anchor_excludes_network_transit"}

    async def emit(self, browser, phase, at, model=None):
        event = self.event(phase, at)
        log_event(event)
        event["model"] = model
        await browser.send_json(event)


def browser_timing(data):
    """Never log the browser's original body, text, arbitrary keys or labels."""
    if (not re.fullmatch(r"[a-f0-9]{32}", data.get("decision_id") or "")
            or data.get("cue") not in CUES or data.get("kind") not in {"answer", "thinking", "question", "help"}
            or type(data.get("finished")) is not bool):
        raise ValueError("Invalid timing metadata.")
    stages = {}
    supplied = data.get("timing_ms")
    if not isinstance(supplied, dict):
        raise ValueError("Invalid stage timings.")
    for stage in STAGES:
        value = supplied.get(stage)
        if value is not None and (type(value) not in {int, float} or not math.isfinite(value)
                                  or not 0 <= value <= 900_000):
            raise ValueError("Invalid stage timings.")
        stages[stage] = value
    # The browser cannot observe audio bytes through SpeechSynthesis.
    stages["acknowledgement_audio_first_byte"] = None
    return {"type": "endpoint_decision", "decision_id": data["decision_id"], "phase": "browser",
            "finished": data["finished"], "kind": data["kind"], "cue": data["cue"], "timing_ms": stages,
            "audio_first_byte_status": "unavailable_browser_speech_synthesis",
            "browser_clock": "answer_complete_receipt_anchor_excludes_network_transit"}
