"""Subprocess isolation; generated code never runs in this process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from forge.errors import Reject


class Sandbox:
    def __init__(self, timeout_s=10, memory_mb=128):
        if not 0 < timeout_s <= 120 or not 64 <= memory_mb <= 1024:
            raise ValueError("Invalid sandbox limits")
        self.timeout_s, self.memory_mb = timeout_s, memory_mb

    def run(self, code, mode, params, trials=20000, seed=0):
        if mode not in {"solve", "sample"} or len(code) > 100000 or not 2 <= trials <= 1000000:
            raise Reject("sandbox", "invalid_request")
        request = json.dumps({"code": code, "mode": mode, "params": params, "trials": trials,
                              "seed": seed, "timeout_s": self.timeout_s, "memory_mb": self.memory_mb})
        if len(request) > 150000:
            raise Reject("sandbox", "request_too_large")
        env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ}
        worker = Path(__file__).with_name("worker.py").resolve()
        with tempfile.TemporaryDirectory(prefix="unbluffable-forge-") as temporary:
            process = subprocess.Popen([sys.executable, "-I", "-S", "-B", str(worker)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", cwd=temporary, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                output, _ = process.communicate(request, timeout=self.timeout_s + 1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise Reject("sandbox", "timeout") from None
        if process.returncode or len(output) > 1000000:
            raise Reject("sandbox", "process_limit_or_failure")
        try:
            result = json.loads(output)
        except ValueError:
            raise Reject("sandbox", "invalid_output") from None
        if not result.get("ok"):
            raise Reject("sandbox", result.get("error", "execution_failed"))
        return result["result"]
