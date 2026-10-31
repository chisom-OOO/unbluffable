"""Strength areas (decision log 23): the profile's radar axes, at most 8 per track, and
which area each forge topic counts toward. A topic with no area is not rated."""

from __future__ import annotations

from fractions import Fraction

AREAS: dict[str, dict[str, tuple[str, ...]]] = {
    "quant": {
        "Probability": ("Discrete probability", "Continuous probability", "Conditional probability",
                        "Bayesian statistics", "Probability inequalities", "Probability"),
        "Expectations": ("Expectations", "Market-style expected value puzzles"),
        "Combinatorics": ("Combinatorics", "Counting"),
        "Statistics": ("Statistics", "Variance, covariance and correlation", "Probability distributions and sampling",
                       "Statistical inference and hypothesis testing"),
        "Stochastic processes": ("Stochastic processes",),
        "Linear algebra & calculus": ("Linear algebra", "Calculus"),
        "Optimisation, decisions & pricing maths": ("Optimisation", "Discrete optimisation", "Optimal decisions",
                                                    "Pricing-model mathematics", "Game theory and strategic decisions",
                                                    "Expected utility and risk", "Betting, bankroll and optimal staking"),
        "Number theory, sequences, geometry & arithmetic": ("Number theory", "Sequences and recurrences", "Geometry",
                                                            "Quantitative arithmetic", "Percentages", "Mental math and estimation"),
        "Market making": ("Market making",),  # decision log 28: exact scorecard, outside the Bayesian label
    },
    "ib": {
        "Accounting": ("Accounting and three-statement linkages", "Accounting", "Financial statement analysis"),
        "DCF": ("DCF", "Working capital and free cash flow"),
        "LBO": ("LBO",),
        "Valuation multiples": ("Valuation multiples", "Valuation", "Trading comparables", "Precedent transactions"),
        "WACC": ("WACC", "Capital structure and financing"),
        "M&A & accretion/dilution": ("M&A", "Accretion/dilution", "Capital raising and IPOs"),
        "EV bridge & share count": ("Enterprise value and equity value bridge", "Share count"),
    },
    "consulting": {
        "Profitability": ("Profitability",),
        "Operations": ("Operations",),
        "Mix & weighted averages": ("Weighted averages and mix effects",),
        "Breakeven": ("Breakeven",),
        "Market sizing": ("Market sizing with stated assumptions", "Market sizing"),
        "Growth & investment": ("Growth", "Investment"),
        "Pricing & unit economics": ("Pricing", "Unit economics"),
    },
    "software": {
        "Dynamic programming": ("Dynamic programming",),
        "Graphs & union-find": ("Graphs", "Union-find"),
        "Sliding window, two pointers & prefix sums": ("Sliding window", "Two pointers", "Prefix sums"),
        "Binary search": ("Binary search on the answer", "Binary search"),
        "Heaps & greedy": ("Heaps", "Greedy"),
        "Intervals & monotonic stack": ("Intervals", "Monotonic stack"),
        "Bit manipulation": ("Bit manipulation",),
        "Backtracking & tries": ("Backtracking", "Tries"),
    },
}

# Quant development (the quant_dev track): the spoken opener's core quant topics, and every
# coding family under one "Coding" area (its topics are whatever the quant_dev forge writes).
AREAS["quant_dev"] = {
    "Probability & expectations": AREAS["quant"]["Probability"] + AREAS["quant"]["Expectations"],
    "Coding": (),
}

_BY_TOPIC = {(track, topic.casefold()): area for track, areas in AREAS.items()
             for area, topics in areas.items() for topic in topics}

# Difficulty cap on a correct answer's value (decision log 23).
CAPS = {"Easy": Fraction(3, 5), "Medium": Fraction(17, 20), "Hard": Fraction(1)}


def area_for(track: str, topic: str | None) -> str | None:
    found = _BY_TOPIC.get((track, (topic or "").casefold()))
    return found or ("Coding" if track == "quant_dev" and topic else None)


def answer_value(scored: str | None, weight: Fraction, difficulty: str | None) -> Fraction:
    """One scored answer's value for the rating: correct = the engine's help-discounted
    weight times the difficulty cap; any other scored outcome = 0."""
    if scored != "correct":
        return Fraction(0)
    return Fraction(weight) * CAPS.get(difficulty or "", CAPS["Medium"])
