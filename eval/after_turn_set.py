"""After-turn evaluation: run extraction + coding over a CSV of transcripts.

CSV columns: clip, transcript, expected_outcome (one of correct, recited,
named_wrong, other_wrong, vague, abstain). Reports each row's outcome, pass/fail,
latency and whether the app would challenge it (a wrong number: named wrong,
other wrong or recited).

Replay is the default and needs no key. `--mode live` calls the model and records
every call. Recordings default to eval/raw/llm/ (git-ignored); this script never
reads recordings/ or any audio.

    .venv\\Scripts\\python.exe -m eval.after_turn_set --csv eval/raw/after_turn.csv
    .venv\\Scripts\\python.exe -m eval.after_turn_set --csv eval/raw/after_turn.csv --mode live
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from engine.coding import Outcome
from engine.templates import flagship, flagship_twin
from llm.replay import ROOT, CallStore
from llm.score import assess

COLUMNS = ("clip", "transcript", "expected_outcome")
DEFAULT_STORE = ROOT / "eval" / "raw" / "llm"
PUZZLES = {"flagship": flagship, "flagship_twin": flagship_twin}
CHALLENGED = {Outcome.NAMED_WRONG, Outcome.OTHER_WRONG, Outcome.RECITED}


@dataclass(frozen=True)
class RowResult:
    clip: str
    expected: str
    outcome: str
    passed: bool
    challenged: bool
    latency_s: float | None  # model call; recorded latency when replayed
    source: str  # model, fallback or system
    replayed: bool
    error: str | None


def load_rows(path: Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or not set(COLUMNS) <= set(reader.fieldnames):
            raise ValueError(f"CSV needs the columns {', '.join(COLUMNS)}")
        rows = list(reader)
    valid = {o.value for o in Outcome}
    for i, row in enumerate(rows, start=2):
        if row["expected_outcome"].strip() not in valid:
            raise ValueError(f"line {i}: expected_outcome must be one of {sorted(valid)}")
    return rows


def run_set(rows, puzzle, *, mode="replay", store=None, backend=None) -> list[RowResult]:
    results = []
    for row in rows:
        turn = assess(puzzle, row["transcript"], mode=mode, backend=backend, store=store)
        ex = turn.extraction
        outcome = turn.observation.outcome
        expected = row["expected_outcome"].strip()
        results.append(RowResult(
            clip=row["clip"],
            expected=expected,
            outcome=outcome.value,
            passed=outcome.value == expected,
            challenged=outcome in CHALLENGED,
            latency_s=ex.latency_s if ex else None,
            source=turn.source,
            replayed=bool(ex and ex.replayed),
            error=ex.error if ex else None,
        ))
    return results


def summarise(results: list[RowResult], mode: str) -> str:
    passed = sum(r.passed for r in results)
    latencies = [r.latency_s for r in results if r.latency_s is not None]
    lines = [
        f"{'clip':<10} {'expected':<12} {'outcome':<12} {'pass':<5} {'chall':<6} {'latency_s':>9}  source",
    ]
    for r in results:
        lat = f"{r.latency_s:.2f}" if r.latency_s is not None else "-"
        note = f" ({r.error})" if r.error else ""
        lines.append(
            f"{r.clip:<10} {r.expected:<12} {r.outcome:<12} {'PASS' if r.passed else 'FAIL':<5} "
            f"{'yes' if r.challenged else 'no':<6} {lat:>9}  {r.source}{note}"
        )
    label = "OFFLINE REPLAY (latencies are the recorded live latencies)" if mode == "replay" else "LIVE"
    lines.append(f"\n{label}: {passed}/{len(results)} passed; "
                 f"{sum(r.source == 'fallback' for r in results)} used the no-model fallback")
    if latencies:
        lines.append(f"Model latency: median {statistics.median(latencies):.2f} s, max {max(latencies):.2f} s "
                     f"over {len(latencies)} calls")
    return "\n".join(lines)


def write_report(results: list[RowResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(results[0])) if results else ["clip"])
        writer.writeheader()
        writer.writerows(asdict(r) for r in results)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, required=True, help="clip, transcript, expected_outcome")
    parser.add_argument("--mode", choices=["replay", "live"], default="replay")
    parser.add_argument("--puzzle", choices=sorted(PUZZLES), default="flagship")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE, help="recorded calls directory")
    parser.add_argument("--out", type=Path, help="write per-row results as CSV")
    args = parser.parse_args(argv)

    rows = load_rows(args.csv)
    results = run_set(rows, PUZZLES[args.puzzle](), mode=args.mode, store=CallStore(args.store))
    print(summarise(results, args.mode))
    if args.out:
        write_report(results, args.out)
        print(f"Report: {args.out}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
