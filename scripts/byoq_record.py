"""Record the live BYOQ calls (decision log 38) for one of the synthetic test images.

    python -m scripts.byoq_record --image tests/fixtures/byoq/question.png

LLM_BACKEND picks the read model and the plan, as in the app: meta_api (default) reads with
Muse Spark 1.3 and checks with two models (Muse Spark Open writes, Muse Spark 1.3 checks;
needs MODEL_API_KEY and BASETEN_API_KEY); open_weights is the hosted app: Muse Spark Open
reads and checks with a solver plus a simulation (needs BASETEN_API_KEY).

Every call is recorded in --out (default replay/llm/demo/byoq/, committed on purpose), with
the image replaced by its SHA-256 digest; outcome-<backend>-<image>.json holds the result,
which tests/test_byoq_app.py replays without a key. Only the synthetic images in
tests/fixtures/byoq/ may be recorded into the committed folder: never a tester's image.
Keys come from the environment and are never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEMO = ROOT / "replay" / "llm" / "demo" / "byoq"
FIXTURES = ROOT / "tests" / "fixtures" / "byoq"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=DEMO)
    args = parser.parse_args(argv)
    image = args.image.resolve()
    if args.out.resolve() == DEMO and image.parent != FIXTURES:
        parser.error("Only the synthetic images in tests/fixtures/byoq/ are recorded into the committed folder.")
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(image.suffix.casefold())
    if mime is None:
        parser.error("Use a PNG or JPEG image.")
    os.environ["BYOQ_MODE"] = "live"
    os.environ["BYOQ_RECORD_DIR"] = str(args.out)

    from app import byoq
    from forge import byoq as gate
    from llm import backends

    reader = byoq.read_backend()
    current = byoq.plan()
    data = image.read_bytes()
    outcome = {"format_version": 1, "image": image.name, "image_sha256": hashlib.sha256(data).hexdigest(),
               "read_backend": reader.name, "read_model": reader.model,
               "plan": {"author": current.author, "checker": current.checker, "second": current.second}}
    name = f"outcome-{reader.name}-{image.stem}.json"
    print(f"Reading {image.name} with {reader.model} ...")
    try:
        found = byoq.read_image(data, mime, byoq.Calls(), reader)
    except (byoq.CallFailed, backends.BackendUnavailable) as error:
        print(f"READ FAILED ({getattr(error, 'reason', 'call_failed')}): stopping before the check.")
        if getattr(error, "status", None) or getattr(error, "detail", ""):
            print(f"HTTP {getattr(error, 'status', None)}: {getattr(error, 'detail', '')}")
        return 1
    outcome["read"] = found
    print(json.dumps(found, indent=2))
    print(f"Checking in code ({current.author} writes; second check: {current.second} by "
          f"{current.checker if current.second == 'solver' else current.author}) ...")
    try:
        token, template = byoq.run_check(found["question_text"], found["stated_answer"], found["topic"],
                                         progress=lambda stage: print(f"  {stage}"))
        variants = byoq.accepted(token)[1]
        outcome.update(stage="ready", variants=variants, answer=template.instances[0].answer_text,
                       wrong_methods=sorted({nv.misconception for i in template.instances for nv in i.wrong}))
        print(f"READY: {byoq.line(variants)}; answer {template.instances[0].answer_text}")
    except (gate.GateFailure, byoq.CallFailed, backends.BackendUnavailable) as error:
        outcome.update(stage="failed", reason=getattr(error, "reason", "call_failed"))
        print(f"NOT ACCEPTED ({outcome['reason']}): {gate.FAILED}")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / name).write_text(json.dumps(outcome, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {name}; the call records are beside it in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
