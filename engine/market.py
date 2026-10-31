"""Market-making games (decision log 28): exact fair value and spread by enumeration, a
reveal sequence with exact conditional values, quote parsing, the counterparty's rules and
the scorecard. Pure: no network, no model.

A game is every outcome of its random draws (dice, flips or cards, revealed one at a time)
with its exact probability and payoff. EV and variance are Fractions; the standard deviation
is shown rounded, but every comparison against it is made exactly on squares.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import permutations, product

from engine.answers import normalise_numbers

WIDE_SDS = Fraction(3, 2)  # a market wider than 1.5 SD is "wide"
ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth")


@dataclass(frozen=True)
class Outcome:
    draws: tuple  # each revealable component, in reveal order
    prob: Fraction
    payoff: Fraction


@dataclass(frozen=True)
class Game:
    kind: str
    params: dict
    text: str  # the interviewer's statement of the game
    noun: str  # "die", "flip", "card"
    outcomes: tuple[Outcome, ...]
    difficulty: str
    points: bool = False  # an event contract, quoted in points (pays 100)

    def stats(self, revealed: tuple = ()) -> tuple[Fraction, Fraction]:
        """(EV, variance) of the payoff given the first len(revealed) components."""
        rows = [o for o in self.outcomes if o.draws[:len(revealed)] == tuple(revealed)]
        total = sum(o.prob for o in rows)
        if not rows or total == 0:
            raise ValueError("revealed draws are impossible in this game")
        ev = sum(o.prob * o.payoff for o in rows) / total
        var = sum(o.prob * (o.payoff - ev) ** 2 for o in rows) / total
        return ev, var

    def ev(self, revealed: tuple = ()) -> Fraction:
        return self.stats(revealed)[0]

    def sd(self, revealed: tuple = ()) -> float:
        return math.sqrt(self.stats(revealed)[1])

    def reveal_line(self, i: int, value) -> str:
        shown = {"flip": "heads" if value else "tails"}.get(self.noun, str(value))
        return f"The {ORDINALS[i]} {self.noun} is {shown}."

    def sample(self, rng: random.Random) -> Outcome:
        x, acc = Fraction(rng.random()), Fraction(0)
        for o in self.outcomes:
            acc += o.prob
            if x < acc:
                return o
        return self.outcomes[-1]


def _uniform(draws: list[tuple], pay) -> tuple[Outcome, ...]:
    p = Fraction(1, len(draws))
    return tuple(Outcome(d, p, Fraction(pay(d))) for d in draws)


def dice(how: str, n: int, faces: int) -> Game:
    """The sum, max or product of n fair dice with `faces` faces."""
    if how not in {"sum", "max", "product"} or not 2 <= n <= 4 or faces not in {6, 8, 10, 12}:
        raise ValueError("dice: sum/max/product of 2-4 dice with 6, 8, 10 or 12 faces")
    pay = {"sum": sum, "max": max, "product": math.prod}[how]
    rolls = list(product(range(1, faces + 1), repeat=n))
    difficulty = {"sum": "Easy", "max": "Medium", "product": "Hard"}[how]
    return Game(f"dice_{how}", {"n": n, "faces": faces},
                f"I roll {n} fair {faces}-sided dice. The contract pays the {how} of the dice. Make me a market.",
                "die", _uniform(rolls, pay), difficulty)


def heads(k: int) -> Game:
    if not 2 <= k <= 10:
        raise ValueError("heads: 2-10 flips")
    return Game("heads", {"k": k}, f"I flip a fair coin {k} times. The contract pays the number of heads. Make me a market.",
                "flip", _uniform(list(product((0, 1), repeat=k)), sum), "Easy")


def cards(deck: int, m: int) -> Game:
    """The sum of m cards drawn without replacement from cards numbered 1 to `deck`."""
    if not 4 <= deck <= 13 or not 2 <= m <= 4 or m >= deck:
        raise ValueError("cards: 2-4 cards from a deck of 4-13")
    return Game("cards", {"deck": deck, "m": m},
                f"A deck has {deck} cards numbered 1 to {deck}. I draw {m} without replacement. "
                f"The contract pays their sum. Make me a market.",
                "card", _uniform(list(permutations(range(1, deck + 1), m)), sum), "Medium")


EVENTS = {
    "any_six": "at least one six in {n} rolls of a fair die",
    "sum_at_least": "the sum of two fair dice is at least {t}",
    "all_different": "{n} rolls of a fair die all show different numbers",
}


def event(name: str, **params) -> Game:
    """An event contract paying 100 if the event happens, else 0; quoted in points."""
    if name == "any_six":
        n = params["n"]
        rolls, hit = list(product(range(1, 7), repeat=n)), lambda d: 6 in d
    elif name == "sum_at_least":
        n, t = 2, params["t"]
        rolls, hit = list(product(range(1, 7), repeat=2)), lambda d: sum(d) >= t
    elif name == "all_different":
        n = params["n"]
        rolls, hit = list(product(range(1, 7), repeat=n)), lambda d: len(set(d)) == n
    else:
        raise ValueError("unknown event")
    if not 2 <= n <= 4:
        raise ValueError("events use 2-4 rolls")
    words = EVENTS[name].format(**params)
    return Game(f"event_{name}", {"event": name, **params},
                f"This contract pays 100 if {words}, and 0 otherwise. Quote it in points. Make me a market.",
                "die", _uniform(rolls, lambda d: 100 if hit(d) else 0), "Medium", points=True)


def distinct(n: int = 5, faces: int = 6) -> Game:
    return Game("distinct", {"n": n, "faces": faces},
                f"I roll a fair {faces}-sided die {n} times. The contract pays the number of distinct values that come up. "
                f"Make me a market.", "die", _uniform(list(product(range(1, faces + 1), repeat=n)), lambda d: len(set(d))), "Hard")


def pay_per_head(cap: int, pay: int) -> Game:
    """Flip until tails, at most `cap` flips; pays `pay` per head."""
    if not 2 <= cap <= 8 or pay <= 0:
        raise ValueError("pay per head: cap 2-8")
    rows = [Outcome((1,) * h + (0,), Fraction(1, 2 ** (h + 1)), Fraction(pay * h)) for h in range(cap)]
    rows.append(Outcome((1,) * cap, Fraction(1, 2 ** cap), Fraction(pay * cap)))
    return Game("pay_per_head", {"cap": cap, "pay": pay},
                f"I flip a fair coin until it lands tails, at most {cap} times. The contract pays {pay} for every head. "
                f"Make me a market.", "flip", tuple(rows), "Hard")


def make_game(rng: random.Random, kind: str | None = None) -> Game:
    """A random game of each kind's parameter ranges."""
    kinds = ["dice_sum", "dice_max", "dice_product", "heads", "cards", "event", "distinct", "pay_per_head"]
    kind = kind or rng.choice(kinds)
    if kind.startswith("dice_"):
        how = kind[5:]
        n = rng.choice([2, 3] if how == "product" else [2, 3, 4])
        return dice(how, n, rng.choice([6, 8, 10, 12] if n < 4 else [6, 8]))
    if kind == "heads":
        return heads(rng.randint(4, 10))
    if kind == "cards":
        return cards(rng.randint(6, 10), rng.randint(2, 4))
    if kind == "event":
        name = rng.choice(list(EVENTS))
        return event(name, **({"t": rng.randint(8, 11)} if name == "sum_at_least" else {"n": rng.randint(2, 4)}))
    if kind == "distinct":
        return distinct(5, 6)
    if kind == "pay_per_head":
        return pay_per_head(rng.randint(3, 6), rng.choice([1, 5, 10]))
    raise ValueError("unknown game kind")


# --- Quotes --------------------------------------------------------------------------

_NUM = r"\d+(?:\.\d+)?(?: and a half| and a quarter| and three quarters)?"
_QUOTE = [
    (re.compile(rf"\bbid(?:ding)?\s+(?:at\s+)?(?P<bid>{_NUM})\b.*?\b(?:offer(?:ed)?|ask(?:ing)?|offering)\s+(?:at\s+)?(?P<ask>{_NUM})"), False),
    (re.compile(rf"(?P<bid>{_NUM})\s+bid\b.*?(?P<ask>{_NUM})\s+(?:offered|offer|ask)\b"), False),
    (re.compile(rf"(?P<ask>{_NUM})\s+(?:offered|offer|ask)\b.*?(?P<bid>{_NUM})\s+bid\b"), False),
    (re.compile(rf"(?P<bid>{_NUM})\s+(?:at|to|-|–)\s+(?P<ask>{_NUM})"), False),
    (re.compile(rf"(?P<bid>{_NUM})\s*,?\s+(?P<ask>{_NUM})\s*$"), True),  # "nine twelve"
]


def _value(text: str) -> Fraction:
    base, _, extra = text.partition(" and ")
    return Fraction(base) + {"": 0, "a half": Fraction(1, 2), "a quarter": Fraction(1, 4),
                             "three quarters": Fraction(3, 4)}[extra]


def parse_quote(text: str) -> tuple[Fraction, Fraction] | None:
    """(bid, ask) from a spoken quote: "9 at 12", "nine twelve", "9 bid, 12 offered",
    "bid 9 offer 12", "12 offered, 9 bid", "nine and a half at eleven". None if unclear."""
    plain = normalise_numbers(text.lower()).replace(",", " ").strip().rstrip(".!? ")
    plain = re.sub(r"\s+", " ", plain)
    for pattern, bare in _QUOTE:
        found = list(pattern.finditer(plain))
        if found:
            m = found[-1]  # a self-correction: the last quote wins
            bid, ask = _value(m["bid"]), _value(m["ask"])
            if bare and bid > ask:
                return None
            return bid, ask
    return None


# --- The counterparty ------------------------------------------------------------------

@dataclass(frozen=True)
class Response:
    action: str  # "buy" (they buy at the ask), "sell" (they sell at the bid), "wide", "pass"
    price: Fraction | None = None


def wide(bid: Fraction, ask: Fraction, var: Fraction) -> bool:
    """Width over 1.5 SD, compared exactly: width² > (1.5)² · variance."""
    return var > 0 and (ask - bid) ** 2 > WIDE_SDS ** 2 * var


def counterparty(bid: Fraction, ask: Fraction, ev: Fraction, var: Fraction, rng: random.Random,
                 tightened: bool = False, trade_chance: float = 0.5) -> Response:
    """Code trades against a mispriced market; a wide one is asked to tighten (once per
    quote stage); otherwise it sometimes trades at their price to build a position."""
    if ask < ev:
        return Response("buy", ask)
    if bid > ev:
        return Response("sell", bid)
    if wide(bid, ask, var) and not tightened:
        return Response("wide")
    if rng.random() < trade_chance:
        return Response("buy", ask) if rng.random() < 0.5 else Response("sell", bid)
    return Response("pass")


# --- The scorecard ---------------------------------------------------------------------

@dataclass
class Quote:
    stage: int  # 0 = before any reveal, then 1, 2, 3 after each reveal
    bid: Fraction
    ask: Fraction
    ev: Fraction
    var: Fraction

    @property
    def contains(self) -> bool:
        return self.bid <= self.ev <= self.ask

    @property
    def width(self) -> Fraction:
        return self.ask - self.bid

    @property
    def mid(self) -> Fraction:
        return (self.bid + self.ask) / 2


@dataclass
class Trade:
    side: int  # +1: the candidate bought (counterparty sold at the bid); -1: the candidate sold
    price: Fraction
    ev: Fraction  # fair value when it traded

    @property
    def edge_given(self) -> Fraction:
        """Expected value the candidate gave away on this trade (0 when it went their way)."""
        return max(Fraction(0), self.side * (self.price - self.ev))

    @property
    def expected_pnl(self) -> Fraction:
        return self.side * (self.ev - self.price)


@dataclass
class Round:
    game: Game
    outcome: Outcome
    quotes: list[Quote] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)

    @property
    def position(self) -> int:
        return sum(t.side for t in self.trades)

    def realised_pnl(self) -> Fraction:
        return sum((t.side * (self.outcome.payoff - t.price) for t in self.trades), Fraction(0))

    def expected_pnl(self) -> Fraction:
        return sum((t.expected_pnl for t in self.trades), Fraction(0))


def finals(r: Round) -> list[Quote]:
    """The last quote at each stage (a tightened market replaces the wide one)."""
    last = {}
    for q in r.quotes:
        last[q.stage] = q
    return [last[s] for s in sorted(last)]


def updates(r: Round) -> list[dict]:
    """Each reveal's update: the exact EV change, the candidate's mid change, whether it
    moved the right way (no move when EV didn't move counts as right) and its size."""
    out = []
    stages = finals(r)
    for before, after in zip(stages, stages[1:]):
        ev_move, mid_move = after.ev - before.ev, after.mid - before.mid
        right = (ev_move > 0 and mid_move > 0) or (ev_move < 0 and mid_move < 0) or (ev_move == 0 and mid_move == 0)
        out.append({"stage": after.stage, "ev_change": ev_move, "mid_change": mid_move, "direction_right": right,
                    "size_ratio": (mid_move / ev_move) if ev_move else None})
    return out


def scorecard(r: Round) -> dict:
    """Exact per-round figures, and a score in [0, 1]: the mean of (share of final quotes
    containing EV, share not wider than 1.5 SD, share of updates in the right direction)."""
    stages = finals(r)
    ups = updates(r)
    contain = Fraction(sum(q.contains for q in stages), len(stages)) if stages else Fraction(0)
    tight = Fraction(sum(not wide(q.bid, q.ask, q.var) for q in stages), len(stages)) if stages else Fraction(0)
    direction = Fraction(sum(u["direction_right"] for u in ups), len(ups)) if ups else contain
    return {"quotes": len(r.quotes), "contains": contain, "tight": tight, "direction": direction,
            "score": (contain + tight + direction) / 3, "updates": ups,
            "edge_given": sum((t.edge_given for t in r.trades), Fraction(0)),
            "position": r.position, "realised_pnl": r.realised_pnl(), "expected_pnl": r.expected_pnl()}
