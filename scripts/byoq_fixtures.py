"""Write the synthetic BYOQ call fixtures (tests/fixtures/byoq/calls/), keyed exactly as app.byoq
builds its requests, so the offline tests replay the real request path with no key.

Synthetic: the responses are the hand-written outputs in tests/byoq_fakes.py, not model
output. Live recordings come from scripts/byoq_record.py. Rerun this after changing a BYOQ
prompt, schema or request:  python -m scripts.byoq_fixtures
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from app import byoq  # noqa: E402
from forge import byoq as gate  # noqa: E402
from llm import backends  # noqa: E402
from llm.replay import CallStore  # noqa: E402
import byoq_fakes  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "byoq"
CALLS = FIXTURES / "calls"
IMAGE = FIXTURES / "question.png"


class Writer:
    """Stands in for a backend: same name, model and schema handling; answers by stage."""

    def __init__(self, real, table):
        self.name, self.model, self.enforces_schema, self.table = real.name, real.model, real.enforces_schema, table

    def complete(self, request):
        stage = request["response_format"]["json_schema"]["name"].removeprefix("byoq_")
        return {"id": "synthetic", "object": "chat.completion", "model": self.model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": json.dumps(self.table[stage])}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


def main() -> None:
    for old in CALLS.glob("*.json"):
        old.unlink()
    table = {"read": byoq_fakes.READ, **byoq_fakes.outputs()}
    real = {name: backends.get_backend(name) for name in backends.BACKENDS}
    fakes = {name: Writer(backend, table) for name, backend in real.items()}
    original = backends.get_backend
    backends.get_backend = lambda name=None: fakes[name or "meta_api"]
    try:
        calls = byoq.Calls(CallStore(CALLS), "live")
        data = IMAGE.read_bytes()
        for name in backends.BACKENDS:  # the read on each backend, image and text
            byoq.read_image(data, "image/png", calls, fakes[name])
            byoq.read_text(byoq_fakes.QUESTION, calls, fakes[name])
        byoq.run_check(byoq_fakes.QUESTION, None, "Discrete probability", calls=calls, current=gate.Plan.two_models())
        byoq.run_check(byoq_fakes.QUESTION, None, "Discrete probability", calls=calls,
                       current=gate.Plan.one_model("open_weights"))
    finally:
        backends.get_backend = original
    for path in CALLS.glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        record.update(synthetic=True, recorded_at="synthetic", run_id="synthetic", latency_s=0)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(list(CALLS.glob('*.json')))} synthetic BYOQ call fixtures in {CALLS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
