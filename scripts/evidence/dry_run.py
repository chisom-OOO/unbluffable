"""Dry run of the evidence comparison with a fake model, and a cost estimate for the live run.

Fills a copy of the draft with synthetic transcripts that pass each item's category check
("My answer is X, because ..."), runs every arm through harness.evaluate on a fake provider
that records the size of each request, and estimates the live cost from those sizes. No
network, no key, and the draft itself is not changed.

  python scripts/evidence/dry_run.py [--items eval/items_draft.json] [--runs 3]

Cost basis (assumptions, not provider pricing): about 4 characters per input token; the
budgeting prices in forge/models.py (USD 1.25 input / 4.25 output per million tokens);
an assumed 500 output tokens per call (verdict or extraction, reasoning effort low), and an
upper bound at the 4,000-token cap on every call.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re
import sys
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
import itemcheck  # noqa: E402
from engine.bank import parse_instance, same_mistake  # noqa: E402

PRICE_IN, PRICE_OUT = Decimal("1.25"), Decimal("4.25")  # USD per million tokens, forge/models.py budgeting
OUT_TOKENS, CAP_TOKENS = 500, 4000
ANSWER = re.compile(r"answer is (.+?), because")


def _frac(x: Fraction) -> str:
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"


def synthetic(item: dict, part: str) -> str:
    """A transcript that passes the item's check: synthetic, for the dry run only."""
    inst = parse_instance(item[part]["question"], part)
    first = parse_instance(item["original"]["question"], "original")
    c = item["category"]
    if c == "correct" or part == "original" and c in ("memorised", "slip"):
        value = inst.answer
    elif c == "misconception":
        value = next(w.value for w in inst.wrong if same_mistake(w.misconception, item["misconception"]))
    elif c == "memorised":
        value = first.answer
    else:  # slip: off by a little, away from every named value
        taken = {inst.answer, first.answer, *(w.value for w in inst.wrong)}
        value = next(inst.answer + d for d in (Fraction(1), Fraction(-1), Fraction(1, 7), Fraction(2)) if inst.answer + d not in taken)
    return f"My answer is {_frac(value)}, because I worked through the steps."


class CountingProvider:
    """Fake Spark: extraction reads "answer is X, because"; chatbot arms say "understands"
    unless both answers are the same number. Records each request's size."""

    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    async def structured(self, text, kind, effort, schema, prompt):
        self.calls.append((kind, len(text) + len(prompt)))
        if kind.startswith("evidence_"):
            said = ANSWER.findall(text)
            same = len(said) == 2 and said[0] == said[1]
            return {"verdict": "does_not_understand" if same else "understands"}, {"model": "fake"}
        m = ANSWER.search(text)
        span = m.group(1) if m else "none"
        if kind == "minimal":
            return {"committed_number_text": span, "is_commitment": m is not None}, {"model": "fake"}
        return {"committed_answer_text": span, "reasoning_quotes": [{"quote": "I worked through the steps", "step": "other"}],
                "reasoning_code": "valid", "misconception_name": "none", "self_corrected": False}, {"model": "fake"}


def estimate(calls: list[tuple[str, int]]) -> dict:
    tokens_in = sum(size for _, size in calls) // 4
    per_kind = Counter(kind for kind, _ in calls)
    cost = lambda out: (Decimal(tokens_in) * PRICE_IN + Decimal(len(calls) * out) * PRICE_OUT) / Decimal(1_000_000)
    return {"calls": len(calls), "calls_by_kind": dict(per_kind), "input_tokens": tokens_in,
            "usd_estimate": f"{cost(OUT_TOKENS):.2f}", "usd_upper_bound": f"{cost(CAP_TOKENS):.2f}"}


def dry_run(path: Path, runs: int = 3) -> dict:
    items = copy.deepcopy(itemcheck.read(path))
    for item in items:
        for part in ("original", "twin"):
            item[part]["transcript"] = synthetic(item, part)
            assert itemcheck.check(item, part, item[part]["transcript"])[0], (item["id"], part)
        item["source"] = "model-written"
    assert not itemcheck.problems(items), itemcheck.problems(items)
    provider = CountingProvider()
    verdicts = asyncio.run(harness.evaluate(items, provider, runs=runs))
    results = harness.summarise(items, verdicts, {"dry_run": True})
    return {"results": results, "cost": estimate(provider.calls)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--items", type=Path, default=itemcheck.DRAFT)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)
    out = dry_run(args.items, args.runs)
    accuracy = {arm: out["results"]["arms"][arm]["majority"]["accuracy"] for arm in harness.ARMS}
    print("Dry run with a fake model (synthetic transcripts): every arm ran; accuracy is not a result.")
    print(json.dumps({"majority_accuracy": accuracy, "cost_estimate": out["cost"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
