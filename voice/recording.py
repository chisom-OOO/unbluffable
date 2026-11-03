"""Private, credential-free development records. Replay never reads a key."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

from llm.replay import recording_on


class VoiceError(Exception):
    """Client-safe message only; provider exception text must never be exposed."""


def redact(value, key=""):
    if isinstance(value, dict):
        return {name: ("[REDACTED]" if name.lower() in {
            "authorization", "accesstoken", "api_key", "model_api_key",
        } else redact(item, key)) for name, item in value.items()}
    if isinstance(value, list):
        return [redact(item, key) for item in value]
    return value.replace(key, "[REDACTED]") if isinstance(value, str) and key else value


def fingerprint(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()


class Record:
    def __init__(self, store, kind, request, key=""):
        self.store, self.key = store, key
        self.data = {
            "format_version": 1, "run_id": uuid.uuid4().hex,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "kind": kind, "request": request, "fingerprint": fingerprint(request),
            "status": "running", "events": [],
        }
        self.save()

    def save(self):
        self.data = redact(self.data, self.key)
        if not recording_on():
            return  # decision log 42: on the hosted app the record stays in memory only
        self.store.root.mkdir(parents=True, exist_ok=True)
        path = self.store.root / (self.data["run_id"] + ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def event(self, event, elapsed):
        self.data["events"].append({"elapsed_s": elapsed, "event": redact(event, self.key)})
        self.save()

    def finish(self, response=None, error=None, latency_s=None):
        self.data.update(status="failed" if error else "passed", response=response,
                         error=error, latency_s=latency_s)
        self.save()


class RecordStore:
    def __init__(self, root):
        self.root = Path(root)

    def create(self, kind, request, key=""):
        return Record(self, kind, request, key)

    def load(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id or ""):
            raise VoiceError("Choose a valid recorded run.")
        try:
            data = json.loads((self.root / (run_id + ".json")).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise VoiceError("Recorded run is unavailable.") from error
        if data.get("format_version") != 1 or data.get("status") != "passed":
            raise VoiceError("Recorded run did not complete successfully.")
        return data

    def find(self, kind, request):
        wanted = fingerprint(request)
        for path in sorted(self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not re.fullmatch(r"[a-f0-9]{32}", path.stem):
                continue
            try:
                data = self.load(path.stem)
            except VoiceError:
                continue
            if data["kind"] == kind and data["fingerprint"] == wanted:
                return data
        raise VoiceError("No recorded result matches this answer. Use an existing replay or live mode.")

    def realtime_runs(self):
        result = []
        for path in self.root.glob("*.json"):
            if not re.fullmatch(r"[a-f0-9]{32}", path.stem):
                continue
            try:
                data = self.load(path.stem)
            except VoiceError:
                continue
            if data["kind"] == "realtime":
                result.append({"run_id": data["run_id"], "recorded_at": data["recorded_at"]})
        return sorted(result, key=lambda row: row["recorded_at"], reverse=True)
