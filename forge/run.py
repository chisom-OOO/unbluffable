"""Offline twin forge. Live authoring is opt-in; tests never call live models."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path

from forge.data import PRIORITY, load_csv
from forge.models import DEFAULT_PRICES, Models, State
from forge.pipeline import Pipeline
from forge.sandbox import Sandbox
from llm.backends import get_backend
from llm.client import MissingKey, _key

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def job_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / "job.lock").open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--topics", default=",".join(PRIORITY), help="Comma-separated priority order, not a filter")
    parser.add_argument("--budget-usd", type=float, default=40)
    parser.add_argument("--mode", choices=("live", "replay"), default="replay")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "data" / "forge")
    parser.add_argument("--price", action="append", default=[], metavar="BACKEND=INPUT,OUTPUT",
                        help="Budgeting USD per million input/output tokens; repeat per backend")
    parser.add_argument("--trials", type=int, default=20000)
    parser.add_argument("--max-similarity", type=float, default=.70)
    parser.add_argument("--timeout-s", type=float, default=10)
    parser.add_argument("--memory-mb", type=int, default=128)
    args = parser.parse_args(argv)
    # Private bank text, generated code and source mapping may only be written
    # under the repository's ignored data/forge directory.
    if not args.work_dir.resolve().is_relative_to((ROOT / "data" / "forge").resolve()):
        parser.error("--work-dir must be inside ignored data/forge")
    forbidden = {"captures", "recordings"}
    if (any(part.casefold() in forbidden for part in args.csv.parts)
            or any(args.csv.resolve().is_relative_to(ROOT / "scripts" / kind / "runs") for kind in ("gate", "probes"))):
        parser.error("Capture folders are not CSV input")
    if args.csv.suffix.lower() != ".csv":
        parser.error("--csv must name a CSV file")
    if args.limit <= 0:
        parser.error("--limit must be positive")
    prices = dict(DEFAULT_PRICES)
    try:
        for flag in args.price:
            backend, values = flag.split("=", 1)
            pair = values.split(",")
            if backend not in prices or len(pair) != 2:
                raise ValueError()
            prices[backend] = tuple(pair)
        if args.mode == "live":
            _key("MODEL_API_KEY")
            _key("BASETEN_API_KEY")
        author_name = os.environ.get("LLM_BACKEND", "open_weights")
        author = get_backend(author_name)
        source = hashlib.sha256(args.csv.read_bytes()).hexdigest()
        questions, counts = load_csv(args.csv)
        if hashlib.sha256(args.csv.read_bytes()).hexdigest() != source:
            raise ValueError("CSV changed during loading")
        with job_lock(args.work_dir):
            state = State(args.work_dir)
            if state.data.setdefault("csv_sha256", source) != source:
                raise ValueError("CSV changed; use a new data/forge subdirectory")
            models = Models(state, mode=args.mode, budget_usd=args.budget_usd, prices=prices, author=author)
            pipeline = Pipeline(models, output=ROOT / "content" / "forge", funnel=ROOT / "forge" / "funnel.json",
                trials=args.trials, max_similarity=args.max_similarity,
                priority=[topic.strip().casefold() for topic in args.topics.split(",") if topic.strip()],
                sandbox=Sandbox(args.timeout_s, args.memory_mb))
            report = pipeline.run(questions, counts, args.limit)
    except (OSError, ValueError, ArithmeticError, MissingKey) as error:
        # Exception text may include bank data or a path; print only the type.
        print(json.dumps({"status": "configuration_error", "type": type(error).__name__}))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
