"""Subprocess isolation; generated code never runs in this process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from forge.errors import Reject


class Sandbox:
    def __init__(self, timeout_s=10, memory_mb=128):
        if not 0 < timeout_s <= 120 or not 64 <= memory_mb <= 1024:
            raise ValueError("Invalid sandbox limits")
        self.timeout_s, self.memory_mb = timeout_s, memory_mb

    def run(self, code, mode, params, trials=20000, seed=0):
        if mode not in {"solve", "sample"} or len(code) > 100000 or not 2 <= trials <= 1000000:
            raise Reject("sandbox", "invalid_request")
        return self._execute({"code": code, "mode": mode, "params": params, "trials": trials,
                              "seed": seed, "timeout_s": self.timeout_s, "memory_mb": self.memory_mb})

    def run_batch(self, code, params):
        if len(code) > 100000 or not 1 <= len(params) <= 75:
            raise Reject("sandbox", "invalid_request")
        result = self._execute({"code": code, "mode": "solve", "params": {}, "batch_params": params,
            "structured_params": True, "trials": 20000, "seed": 0,
            "timeout_s": self.timeout_s, "memory_mb": self.memory_mb})
        if not isinstance(result, dict) or len(result.get("results", [])) != len(params):
            raise Reject("sandbox", "invalid_batch_output")
        return result["results"]

    def run_generated(self, code, generator, config, points):
        """The solver on inputs the worker builds itself from (seed, n) with the trusted
        generator (forge/scale_gen.py); each result carries its solve time in ms."""
        if len(code) > 100000 or len(generator) > 20000 or not 1 <= len(points) <= 75:
            raise Reject("sandbox", "invalid_request")
        result = self._execute({"code": code, "mode": "solve", "params": {}, "structured_params": True,
            "generate": {"code": generator, "config": config, "points": points},
            "trials": 20000, "seed": 0, "timeout_s": self.timeout_s, "memory_mb": self.memory_mb})
        if not isinstance(result, dict) or len(result.get("results", [])) != len(points):
            raise Reject("sandbox", "invalid_batch_output")
        return result["results"]

    def _execute(self, request):
        request = json.dumps(request)
        if len(request) > 150000:
            raise Reject("sandbox", "request_too_large")
        env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ}
        worker = Path(__file__).with_name("worker.py").resolve()
        started = time.perf_counter()
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
        if process.returncode and time.perf_counter() - started >= self.timeout_s:
            raise Reject("sandbox", "timeout")
        if process.returncode or len(output) > 1000000:
            raise Reject("sandbox", "process_limit_or_failure")
        try:
            result = json.loads(output)
        except ValueError:
            raise Reject("sandbox", "invalid_output") from None
        if not result.get("ok"):
            raise Reject("sandbox", result.get("error", "execution_failed"))
        return result["result"]
