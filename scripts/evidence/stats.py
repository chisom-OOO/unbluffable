"""Statistics for the pre-registered evidence run (decision log 15). Pure functions.

Correct = an arm's verdict equals the item's label. False flag = "does_not_understand"
on an item labelled "understands". A run that failed ("error") is never correct and
never a flag. Across runs an item's verdict is the strict majority, else "no_majority".
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from math import comb

UNDERSTANDS = "understands"
NOT_UNDERSTANDS = "does_not_understand"
LABELS = (UNDERSTANDS, NOT_UNDERSTANDS)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs (binomial, p = 1/2)."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(Fraction(comb(n, k), 2 ** n) for k in range(min(b, c) + 1))
    return float(min(Fraction(1), 2 * tail))


def binomial_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def upper_bound(k: int, n: int, confidence: float = 0.95) -> float:
    """Exact one-sided Clopper-Pearson upper bound for a rate seen k times in n: the largest p
    with P(X <= k | n, p) >= 1 - confidence (1 when k = n). Bisection to below 1e-12."""
    if not 0 <= k <= n or n == 0:
        raise ValueError("need 0 <= k <= n and n > 0")
    if k == n:
        return 1.0
    alpha, lo, hi = 1 - confidence, k / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if binomial_cdf(k, n, mid) > alpha else (lo, mid)
    return lo


def majority(verdicts: list[str]) -> str:
    value, count = Counter(verdicts).most_common(1)[0]
    return value if count * 2 > len(verdicts) else "no_majority"


def score(labels: dict[str, str], verdicts: dict[str, str]) -> dict:
    """Accuracy, false flags and errors for one set of verdicts (one run, or the majority)."""
    correct = [i for i in labels if verdicts[i] == labels[i]]
    positives = [i for i in labels if labels[i] == UNDERSTANDS]
    flags = [i for i in positives if verdicts[i] == NOT_UNDERSTANDS]
    return {
        "correct": len(correct),
        "accuracy": len(correct) / len(labels) if labels else 0.0,
        "false_flags": len(flags),
        "false_flag_rate": len(flags) / len(positives) if positives else 0.0,
        "false_flag_items": flags,
        "errors": sum(1 for i in labels if verdicts[i] in {"error", "no_majority"}),
    }


def flips(runs: list[dict[str, str]]) -> list[str]:
    """Items whose verdict was not the same in every run."""
    return [i for i in runs[0] if len({run[i] for run in runs}) > 1]


def compare(labels: dict[str, str], ours: dict[str, str], theirs: dict[str, str]) -> dict:
    """b: ours right and theirs wrong; c: ours wrong and theirs right."""
    b = sum(1 for i in labels if ours[i] == labels[i] and theirs[i] != labels[i])
    c = sum(1 for i in labels if ours[i] != labels[i] and theirs[i] == labels[i])
    return {"b": b, "c": c, "p": mcnemar_exact(b, c)}
