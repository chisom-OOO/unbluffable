"""Record/replay of model calls (spec/03 Ops; CLAUDE.md rule 8).

Every live call is recorded; replay looks the call up by a hash of the backend
and the exact request, so it needs no key and no network. Records never contain
the API key: auth-like fields are dropped and any echoed key is redacted.

Recordings hold the candidate's answer text. The default directory is
`replay/llm/` (demo runs); point LLM_REPLAY_DIR at a git-ignored folder such as
`eval/raw/llm/` for tester or evaluation answers.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "replay" / "llm"
FORMAT_VERSION = 1
_SECRET_FIELDS = {"authorization", "accesstoken", "api_key", "apikey", "model_api_key"}


def request_hash(backend: str, request: dict) -> str:
    canonical = json.dumps({"backend": backend, "request": request}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sanitize(value, key: str | None = None):
    if key is None:
        key = os.environ.get("MODEL_API_KEY", "").strip()
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in _SECRET_FIELDS else sanitize(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, key) for v in value]
    if isinstance(value, str) and key:
        return value.replace(key, "[REDACTED]")
    return value


class CallStore:
    def __init__(self, directory: Path | str | None = None):
        if directory is None:
            directory = os.environ.get("LLM_REPLAY_DIR") or DEFAULT_DIR
        self.directory = Path(directory)

    def path(self, backend: str, request: dict) -> Path:
        return self.directory / f"{request_hash(backend, request)}.json"

    def save(self, backend: str, request: dict, response: dict, latency_s: float) -> dict:
        record = sanitize({
            "format_version": FORMAT_VERSION,
            "run_id": uuid.uuid4().hex,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "backend": backend,
            "request_sha256": request_hash(backend, request),
            "latency_s": round(latency_s, 3),
            "request": request,
            "response": response,
        })
        path = self.path(backend, request)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return record

    def load(self, backend: str, request: dict) -> dict | None:
        path = self.path(backend, request)
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("format_version") != FORMAT_VERSION:
            return None
        return record
