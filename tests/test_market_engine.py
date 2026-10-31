"""Market-making games (engine/market.py): exact EV and variance by enumeration, pinned per
game type and checked against closed forms; conditional values after reveals; the
counterparty's rules; the scorecard maths; quote parsing variants."""

import random
from fractions import Fraction as F

import pytest

from engine import market as m


@pytest.mark.parametrize("game, ev, var", [
    (m.dice("sum", 2, 6), F(7), F(35, 6)),
    (m.dice("sum", 4, 12), F(26), F(143, 3)),  # 4 x (13/2, 143/12)
    (m.dice("max", 2, 6), F(161, 36), F(2555, 1296)),
    (m.dice("product", 2, 6), F(49, 4), F(11515, 144)),  # (7/2)^2; E[X^2]^2 - (49/4)^2 = (91/6)^2 - (49/4)^2
    (m.heads(10), F(5), F(5, 2)),
    (m.cards(10, 3), F(33, 2), F(77, 4)),  # without replacement: 3 x 33/4 x (10 - 3)/(10 - 1)
    (m.event("any_six", n=4), 100 * (1 - F(5, 6) ** 4), 100 ** 2 * (1 - F(5, 6) ** 4) * F(5, 6) ** 4),
    (m.event("sum_at_least", t=10), F(100, 6), 100 ** 2 * F(1, 6) * F(5, 6)),
    (m.event("all_different", n=3), F(100 * 20, 36), 100 ** 2 * F(5, 9) * F(4, 9)),
    (m.distinct(5, 6), 6 * (1 - F(5, 6) ** 5), F(919895, 1679616)),
    (m.pay_per_head(5, 10), 10 * (1 - F(1, 2 ** 5)), F(42375, 256)),
])
def test_ev_and_variance_by_enumeration_are_pinned(game, ev, var):
    assert game.stats() == (ev, var)
    assert sum(o.prob for o in game.outcomes) == 1
    assert game.sd() == pytest.approx(float(var) ** 0.5)


def test_closed_forms_for_every_parameter():
    for n in (2, 3, 4):
        for faces in (6, 8, 10, 12):
            if n == 4 and faces > 8:
                continue
            g = m.dice("sum", n, faces)
            assert g.stats() == (F(n * (faces + 1), 2), F(n * (faces ** 2 - 1), 12))
            mx = sum(F(k) * (F(k, faces) ** n - F(k - 1, faces) ** n) for k in range(1, faces + 1))
            assert m.dice("max", n, faces).ev() == mx
    for k in range(2, 11):
        assert m.heads(k).stats() == (F(k, 2), F(k, 4))
    for cap in range(2, 9):
        assert m.pay_per_head(cap, 1).ev() == 1 - F(1, 2 ** cap)


def test_conditional_values_after_each_reveal():
    g = m.dice("sum", 2, 6)
    assert g.stats((3,)) == (F(13, 2), F(35, 12))
    assert g.stats((3, 4)) == (F(7), F(0))
    c = m.cards(10, 3)  # sum of three of 1..10; first card 10: 10 + 2 x mean of the other nine
    assert c.ev((10,)) == 10 + 2 * F(45, 9)
    e = m.event("any_six", n=4)
    assert e.ev((6,)) == 100 and e.stats((6,))[1] == 0
    assert e.ev((1,)) == 100 * (1 - F(5, 6) ** 3)
    p = m.pay_per_head(5, 10)
    assert p.ev((1,)) == 10 + 10 * (1 - F(1, 16)) and p.ev((0,)) == 0
    with pytest.raises(ValueError):
        m.dice("sum", 2, 6).stats((7,))


def test_reveal_lines():
    assert m.dice("sum", 2, 6).reveal_line(0, 4) == "The first die is 4."
    assert m.heads(4).reveal_line(1, 1) == "The second flip is heads."
    assert m.cards(8, 2).reveal_line(1, 7) == "The second card is 7."


@pytest.mark.parametrize("said, quote", [
    ("9 at 12", (9, 12)), ("nine at twelve", (9, 12)), ("nine twelve", (9, 12)),
    ("9 bid, 12 offered", (9, 12)), ("bid nine, offer twelve", (9, 12)), ("twelve offered, nine bid", (9, 12)),
    ("I'd make it nine and a half at eleven", (F(19, 2), 11)), ("fifty one at fifty three", (51, 53)),
    ("9 at 12, actually 10 at 12", (10, 12)), ("3 and a half to 4 and a half", (F(7, 2), F(9, 2))),
    ("one hundred at one hundred and ten", (100, 110)),
])
def test_quote_parsing_variants(said, quote):
    assert m.parse_quote(said) == (F(quote[0]), F(quote[1]))


@pytest.mark.parametrize("said", ["twelve nine", "I'm not sure yet", "about nine"])
def test_unclear_quotes_are_none(said):
    assert m.parse_quote(said) is None


def test_counterparty_rules():
    rng = random.Random(0)
    ev, var = F(7), F(35, 6)  # SD about 2.42; 1.5 SD about 3.62
    assert m.counterparty(F(5), F(6), ev, var, rng) == m.Response("buy", F(6))  # offer below EV: lifted
    assert m.counterparty(F(8), F(9), ev, var, rng) == m.Response("sell", F(8))  # bid above EV: hit
    assert m.counterparty(F(4), F(10), ev, var, rng) == m.Response("wide")  # contains EV, width 6 > 3.62
    assert m.counterparty(F(4), F(10), ev, var, rng, tightened=True).action in {"buy", "sell", "pass"}
    assert not m.wide(F(5), F(8), var) and m.wide(F(5), F(9), var)  # 3^2 <= 2.25 x 35/6 < 4^2
    seen = {m.counterparty(F(6), F(8), ev, var, random.Random(s)).action for s in range(40)}
    assert seen == {"buy", "sell", "pass"}  # inside a tight market it sometimes trades at their price
    assert m.counterparty(F(6), F(8), ev, var, rng, trade_chance=0).action == "pass"


def test_scorecard_maths():
    g = m.dice("sum", 2, 6)
    r = m.Round(g, m.Outcome((3, 4), F(1, 36), F(7)))
    r.quotes += [m.Quote(0, F(6), F(8), *g.stats()), m.Quote(1, F(5), F(7), *g.stats((3,))),
                 m.Quote(1, F(4), F(9), *g.stats((3,))),  # re-quoted wider: 5 > 1.5 x 1.71
                 m.Quote(2, F(6), F(8), *g.stats((3, 4)))]
    r.trades += [m.Trade(-1, F(8), F(7)), m.Trade(-1, F(6), F(13, 2)), m.Trade(+1, F(6), F(7))]
    card = m.scorecard(r)
    assert [(q.stage, q.bid) for q in m.finals(r)] == [(0, 6), (1, 4), (2, 6)]  # the last quote at each stage
    assert card["contains"] == 1 and card["tight"] == F(2, 3)  # EV known at stage 2 (SD 0): width not judged
    assert [(u["ev_change"], u["mid_change"], u["direction_right"]) for u in card["updates"]] == [
        (F(-1, 2), F(-1, 2), True), (F(1, 2), F(1, 2), True)]
    assert card["updates"][0]["size_ratio"] == 1
    assert card["direction"] == 1 and card["score"] == (1 + F(2, 3) + 1) / 3
    assert card["edge_given"] == F(1, 2)  # sold at 6 when fair was 6.5
    assert card["position"] == -1
    assert card["expected_pnl"] == (8 - 7) + (6 - F(13, 2)) + (7 - 6)
    assert card["realised_pnl"] == (8 - 7) + (6 - 7) + (7 - 6)


def test_random_games_and_settlement_are_reproducible():
    for seed in range(30):
        g = m.make_game(random.Random(seed))
        assert sum(o.prob for o in g.outcomes) == 1 and g.text.endswith("Make me a market.")
        o = g.sample(random.Random(seed))
        assert o in g.outcomes and g.stats(o.draws) == (o.payoff, 0)
