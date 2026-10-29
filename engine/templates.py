"""Puzzle templates T1–T3 with exact-fraction answers (spec/02 §1).

Every value is a `fractions.Fraction`. A template turns parameters into a
`Puzzle`: the exact answer, the named wrong values, and whole-number natural
frequencies for a round population size.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from math import lcm
from typing import Callable

from engine.answers import StatedNumber, matches

HALF = Fraction(1, 2)

# Round population sizes for natural frequencies ("out of 2,000 transactions").
POPULATIONS = (1000, 2000, 5000, 10000, 20000, 50000, 100000)


def pct(x: int | str | Fraction) -> Fraction:
    return Fraction(x) / 100


@dataclass(frozen=True)
class NamedValue:
    """A classic wrong answer. `misconception` uses the extraction enum in spec/03."""

    key: str
    value: Fraction
    misconception: str
    description: str


@dataclass(frozen=True)
class Puzzle:
    template_id: str
    params: dict[str, Fraction]
    population: int
    answer: Fraction
    named_values: tuple[NamedValue, ...]
    counts: dict[str, int]
    # The original puzzle's answer when this puzzle is a twin ("Recited").
    recited: Fraction | None = None
    changed_param: str | None = None
    givens: tuple[Fraction, ...] = field(default=())

    @property
    def is_twin(self) -> bool:
        return self.recited is not None

    def accepts(self, stated: StatedNumber, target: Fraction) -> bool:
        """The tolerance rule of spec/02 §1; forge puzzles use their instance's tolerance."""
        return matches(stated, target)


@dataclass(frozen=True)
class Template:
    template_id: str
    name: str
    param_names: tuple[str, ...]
    answer: Callable[[dict], Fraction]
    named_values: Callable[[dict], tuple[NamedValue, ...]]
    # Natural-frequency shares (each times the population must be whole).
    shares: Callable[[dict], dict[str, Fraction]]
    # Parameter grids the generator draws from.
    grid: dict[str, tuple[Fraction, ...]]

    def build(
        self,
        params: dict,
        population: int | None = None,
        original: Puzzle | None = None,
    ) -> Puzzle:
        """Build a puzzle. Raises ValueError if no round population gives whole counts."""
        params = {k: Fraction(params[k]) for k in self.param_names}
        shares = self.shares(params)
        if population is None:
            population = smallest_population(shares.values())
        counts = {}
        for name, share in shares.items():
            count = share * population
            if count.denominator != 1:
                raise ValueError(f"{name} is not a whole number out of {population}")
            counts[name] = int(count)
        changed = None
        if original is not None:
            diff = [k for k in self.param_names if original.params[k] != params[k]]
            changed = diff[0] if len(diff) == 1 else None
        return Puzzle(
            template_id=self.template_id,
            params=params,
            population=population,
            answer=self.answer(params),
            named_values=self.named_values(params),
            counts={"population": population, **counts},
            recited=original.answer if original is not None else None,
            changed_param=changed,
            givens=tuple(params[k] for k in self.param_names),
        )


def smallest_population(shares) -> int:
    need = lcm(*(Fraction(s).denominator for s in shares))
    for n in POPULATIONS:
        if n % need == 0:
            return n
    raise ValueError(f"no round population is a multiple of {need}")


# --- T1: Fraud alert (flagship) ---------------------------------------------
# p = base rate, s = detection rate, f = false-alarm rate.


def _t1_answer(v):
    return v["p"] * v["s"] / (v["p"] * v["s"] + (1 - v["p"]) * v["f"])


def _t1_named(v):
    flag_rate = v["p"] * v["s"] + (1 - v["p"]) * v["f"]
    return (
        NamedValue("detection_rate", v["s"], "transposed_conditional",
                   "detection rate read as P(fraud | flagged)"),
        # 02 §1 groups 1 − f, f and P(+) as base rate / denominator errors.
        NamedValue("one_minus_false_alarm", 1 - v["f"], "base_rate_neglect",
                   "1 − false-alarm rate"),
        NamedValue("false_alarm_rate", v["f"], "base_rate_neglect",
                   "false-alarm rate"),
        NamedValue("flag_rate", flag_rate, "base_rate_neglect",
                   "share of all transactions flagged, P(flagged)"),
    )


def _t1_shares(v):
    return {
        "fraud": v["p"],
        "fraud_flagged": v["p"] * v["s"],
        "genuine": 1 - v["p"],
        "genuine_flagged": (1 - v["p"]) * v["f"],
    }


T1 = Template(
    template_id="T1",
    name="Fraud alert",
    param_names=("p", "s", "f"),
    answer=_t1_answer,
    named_values=_t1_named,
    shares=_t1_shares,
    grid={
        "p": tuple(pct(x) for x in (1, 2, 3, 4, 5, 8, 10)),
        "s": tuple(pct(x) for x in (75, 80, 85, 90, 95)),
        "f": tuple(pct(x) for x in (2, 3, 4, 5, 6, 8, 10)),
    },
)


# --- T2: Two machines --------------------------------------------------------
# a = share made by machine A, dA / dB = defect rates.


def _t2_answer(v):
    return v["a"] * v["dA"] / (v["a"] * v["dA"] + (1 - v["a"]) * v["dB"])


def _t2_named(v):
    return (
        NamedValue("ignores_shares", v["dA"] / (v["dA"] + v["dB"]), "base_rate_neglect",
                   "dA / (dA + dB), ignoring production shares"),
        NamedValue("share_only", v["a"], "ignores_data",
                   "machine A's production share only"),
        NamedValue("defect_rate_a", v["dA"], "transposed_conditional",
                   "P(defect | A) read as P(A | defect)"),
    )


def _t2_shares(v):
    return {
        "from_a": v["a"],
        "defective_a": v["a"] * v["dA"],
        "from_b": 1 - v["a"],
        "defective_b": (1 - v["a"]) * v["dB"],
    }


T2 = Template(
    template_id="T2",
    name="Two machines",
    param_names=("a", "dA", "dB"),
    answer=_t2_answer,
    named_values=_t2_named,
    shares=_t2_shares,
    grid={
        "a": tuple(pct(x) for x in (20, 25, 30, 40, 60, 70, 75, 80)),
        "dA": tuple(pct(x) for x in (1, 2, 3, 4, 5, 6, 8, 10)),
        "dB": tuple(pct(x) for x in (1, 2, 3, 4, 5, 6, 8, 10)),
    },
)


# --- T3: Two coins -----------------------------------------------------------
# q = chance the biased coin is drawn, b = its P(heads), k = flips, all heads.


def _t3_answer(v):
    k = int(v["k"])
    return v["q"] * v["b"] ** k / (v["q"] * v["b"] ** k + (1 - v["q"]) * HALF ** k)


def _t3_named(v):
    k = int(v["k"])
    return (
        NamedValue("prior_only", v["q"], "ignores_data",
                   "chance of drawing the biased coin, ignoring the flips"),
        NamedValue("ignores_prior", v["b"] ** k / (v["b"] ** k + HALF ** k), "ignores_prior",
                   "b^k / (b^k + 0.5^k), ignoring the prior"),
        NamedValue("likelihood_only", v["b"] ** k, "transposed_conditional",
                   "b^k, the likelihood rather than the posterior"),
    )


def _t3_shares(v):
    k = int(v["k"])
    return {
        "biased": v["q"],
        "biased_all_heads": v["q"] * v["b"] ** k,
        "fair": 1 - v["q"],
        "fair_all_heads": (1 - v["q"]) * HALF ** k,
    }


T3 = Template(
    template_id="T3",
    name="Two coins",
    param_names=("q", "b", "k"),
    answer=_t3_answer,
    named_values=_t3_named,
    shares=_t3_shares,
    grid={
        "q": tuple(pct(x) for x in (1, 2, 5, 10, 20, 25, 50)),
        # Denominators of 2 and 5 only, so counts are whole for round populations.
        "b": (Fraction(3, 5), Fraction(4, 5), Fraction(9, 10), Fraction(1)),
        "k": tuple(Fraction(x) for x in (2, 3, 4)),
    },
)


TEMPLATES: dict[str, Template] = {"T1": T1, "T2": T2, "T3": T3}
TEMPLATE_ORDER = ("T1", "T2", "T3")  # also the selection tie order

FLAGSHIP_PARAMS = {"p": pct(1), "s": pct(90), "f": pct(5)}
FLAGSHIP_TWIN_PARAMS = {"p": pct(2), "s": pct(90), "f": pct(5)}


def flagship() -> Puzzle:
    """Fixed demo puzzle: 1% fraud, 90% detected, 5% false alarms → 2/13."""
    return T1.build(FLAGSHIP_PARAMS, population=2000)


def flagship_twin() -> Puzzle:
    """Fixed demo twin: base rate 2% → 18/67."""
    return T1.build(FLAGSHIP_TWIN_PARAMS, population=2000, original=flagship())
