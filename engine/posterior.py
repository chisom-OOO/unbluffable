"""Exact Bayesian update over Sound / Misconception / Gap (spec/02 §3)."""

from __future__ import annotations

from fractions import Fraction

Distribution = dict[str, Fraction]


def update(prior: Distribution, likelihood: Distribution) -> Distribution:
    """Posterior ∝ prior × likelihood, exactly."""
    joint = {c: prior[c] * likelihood[c] for c in prior}
    total = sum(joint.values())
    if total == 0:
        raise ValueError("observation has zero probability under every class")
    return {c: v / total for c, v in joint.items()}
