"""Spend protection (decision log 42): per-IP limits on every endpoint that makes a model call,
and a global daily cap on estimated model cost. Everything to tune is in the table below.

In memory only (one Render instance): counters reset on a restart. Client IPs are kept only as
keys of these counters, never logged or stored. The estimates are model estimates, not billing;
the Meta and Baseten billing pages are the source of truth.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

HOUR, DAY = 3600, 86400


@dataclass(frozen=True)
class Limit:
    count: int
    window_s: int


@dataclass(frozen=True)
class Rate:
    input_per_m: Decimal   # USD per million input tokens
    output_per_m: Decimal  # USD per million output tokens
    stand_in: bool
    source: str


# ---------------------------------------------------------------------------------------------
# The config table. Change limits, the cap or the rates here.
# ---------------------------------------------------------------------------------------------
LIMITS = {
    # /api/interview/ws starts (every room: forge questions, market making, coding, own
    # question, placement, drills) and each /api/voice/realtime stream, together.
    "interview": Limit(8, HOUR),
    "byoq_read": Limit(15, DAY),       # /api/byoq/read
    "byoq_check": Limit(15, DAY),      # /api/byoq/check
    "transcription": Limit(300, DAY),  # /api/voice/transcribe and /api/voice/answer, together
}
DAILY_COST_CAP_USD = Decimal("5")  # per UTC day, all visitors together
RATES = {
    "muse-spark-1.3": Rate(Decimal("1.25"), Decimal("4.25"), False, "spec/03: Spark Standard pricing"),
    "meta-models/muse-spark-open-1026": Rate(Decimal("1.25"), Decimal("4.25"), True,
                                             "stand-in at Spark Standard rates, not a published price"),
}
TRANSCRIBE_USD_PER_MINUTE = Decimal("0.01")
TRANSCRIBE_SOURCE = "stand-in (Voice Transcribe reports no tokens), not a published price"
# A call that reports no usage counts as this many input and output tokens at the highest rate.
NO_USAGE_TOKENS = 4000
# ---------------------------------------------------------------------------------------------

BUSY = "Busy right now, try again later."
NOUNS = {"interview": "interviews", "byoq_read": "question reads", "byoq_check": "question checks",
         "transcription": "transcriptions"}
MAX_VISITORS = 50_000  # bounds memory: the oldest idle counters go first


class Refused(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.message, self.status = message, status


def limited_message(kind: str) -> str:
    limit = LIMITS[kind]
    per = "hour" if limit.window_s == HOUR else "day" if limit.window_s == DAY else f"{limit.window_s} s"
    return f"You've reached the limit of {limit.count} {NOUNS[kind]} per {per}. Try again later."


def client_ip(headers, client) -> str:
    """The first X-Forwarded-For entry (Render's proxy appends to it), else the socket peer."""
    forwarded = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    host = client[0] if client else None
    return host or "unknown"


def _highest() -> Rate:
    return max(RATES.values(), key=lambda r: (r.input_per_m + r.output_per_m))


class Guard:
    def __init__(self, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.hits: dict[tuple[str, str], deque] = {}
            self.day, self.spent = None, Decimal(0)

    # --- the daily meter ---
    def _today(self) -> None:
        day = datetime.fromtimestamp(self.clock(), timezone.utc).date()
        if day != self.day:
            self.day, self.spent = day, Decimal(0)

    def spent_today(self) -> Decimal:
        with self.lock:
            self._today()
            return self.spent

    def add_usd(self, usd: Decimal) -> None:
        with self.lock:
            self._today()
            self.spent += usd

    def add_tokens(self, model: str, usage) -> None:
        rate = RATES.get(model) or _highest()
        inputs = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        outputs = usage.get("completion_tokens") if isinstance(usage, dict) else None
        if type(inputs) is not int or type(outputs) is not int:
            rate, inputs, outputs = _highest(), NO_USAGE_TOKENS, NO_USAGE_TOKENS
        self.add_usd((inputs * rate.input_per_m + outputs * rate.output_per_m) / 1_000_000)

    def add_audio(self, seconds: float) -> None:
        if seconds > 0:
            self.add_usd(Decimal(str(round(seconds, 3))) / 60 * TRANSCRIBE_USD_PER_MINUTE)

    # --- admission ---
    def _window(self, kind: str, ip: str, now: float) -> deque:
        hits = self.hits.get((kind, ip))
        if hits is None:
            if len(self.hits) >= MAX_VISITORS:
                self._prune(now)
            hits = self.hits[(kind, ip)] = deque()
        while hits and hits[0] <= now - LIMITS[kind].window_s:
            hits.popleft()
        return hits

    def _prune(self, now: float) -> None:
        for key in list(self.hits):
            hits = self.hits[key]
            if not hits or hits[-1] <= now - LIMITS[key[0]].window_s:
                del self.hits[key]
        while len(self.hits) >= MAX_VISITORS:
            del self.hits[next(iter(self.hits))]

    def admit(self, kind: str, ip: str) -> None:
        """Counts one new session or request, or raises Refused (nothing is counted then)."""
        with self.lock:
            self._today()
            if self.spent >= DAILY_COST_CAP_USD:
                raise Refused(BUSY, 503)
            now = self.clock()
            hits = self._window(kind, ip, now)
            if len(hits) >= LIMITS[kind].count:
                raise Refused(limited_message(kind), 429)
            hits.append(now)

    def remaining(self, kind: str, ip: str) -> int:
        with self.lock:
            return LIMITS[kind].count - len(self._window(kind, ip, self.clock()))


GUARD = Guard()


def admit(kind: str, connection) -> None:
    """For a FastAPI Request or WebSocket."""
    GUARD.admit(kind, client_ip(connection.headers, connection.client))
