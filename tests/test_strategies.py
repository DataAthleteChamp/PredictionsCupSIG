"""Tests for the two strategies. Both are pure functions of MarketView."""
import pytest

from sigbot.strategies.base import MarketView, Quote
from sigbot.strategies.ladder import LadderConfig, LadderStrategy
from sigbot.strategies.relvalue import RelValueConfig, RelValueStrategy


def q(ex="1", bid=0.48, ask=0.50, bs=100.0, aszi=100.0):
    return Quote(ex, bid, ask, bs, aszi)


def view(quotes=None, fair=None, positions=None, equity=100_000.0):
    return MarketView(quotes=quotes or {}, fair=fair or {},
                      positions=positions or {}, equity=equity)


# ------------------------------------------------------------------ Quote ---

def test_quote_mid_and_spread():
    assert q(bid=0.40, ask=0.44).mid == pytest.approx(0.42)
    assert q(bid=0.40, ask=0.44).spread_ticks == 8


def test_quote_untradeable_when_missing_or_crossed():
    assert not Quote("1", None, 0.5).tradeable
    assert not Quote("1", 0.5, None).tradeable
    assert not Quote("1", 0.6, 0.5).tradeable       # crossed
    assert q().tradeable


# ----------------------------------------------------------------- ladder ---

def test_ladder_quotes_strictly_below_the_bid():
    """Core rule: never improve the touch. Measured EV there is negative."""
    orders = LadderStrategy().desired(view({"1": q(bid=0.48, ask=0.50)}))
    assert orders
    for o in orders:
        assert o.price < 0.48
        assert o.action == "buy"
        assert o.strategy == "ladder"


def test_ladder_never_bids_into_the_negative_markout_tail():
    cfg = LadderConfig(offsets=(0.08, 0.15), floor_price=0.15, min_mid=0.20)
    orders = LadderStrategy(cfg).desired(view({"1": q(bid=0.20, ask=0.22)}))
    assert all(o.price >= 0.15 for o in orders)


def test_ladder_skips_markets_outside_the_mid_band():
    s = LadderStrategy(LadderConfig(min_mid=0.20, max_mid=0.85))
    assert s.desired(view({"1": q(bid=0.04, ask=0.06)})) == []     # tail
    assert s.desired(view({"1": q(bid=0.93, ask=0.95)})) == []     # near-certain


def test_ladder_skips_untradeable_books():
    s = LadderStrategy()
    assert s.desired(view({"1": Quote("1", None, None)})) == []
    assert s.desired(view({"1": Quote("1", 0.6, 0.5)})) == []


def test_ladder_skips_markets_where_we_are_already_loaded():
    s = LadderStrategy(LadderConfig(max_existing_shares=100.0))
    v = view({"1": q()}, positions={"1": 500.0})
    assert s.desired(v) == []


def test_ladder_respects_max_markets():
    quotes = {str(i): q(str(i)) for i in range(50)}
    s = LadderStrategy(LadderConfig(max_markets=5))
    assert len({o.exchange_id for o in s.desired(view(quotes))} ) == 5


def test_ladder_prices_are_on_tick():
    orders = LadderStrategy().desired(view({"1": q(bid=0.481, ask=0.503)}))
    for o in orders:
        assert abs(o.price / 0.005 - round(o.price / 0.005)) < 1e-9


def test_ladder_sizes_less_capital_at_lower_prices():
    deep = LadderStrategy(LadderConfig(offsets=(0.30,), min_mid=0.2, floor_price=0.15))
    shallow = LadderStrategy(LadderConfig(offsets=(0.02,), min_mid=0.2))
    v = view({"1": q(bid=0.60, ask=0.62)})
    n_deep = deep.desired(v)[0]
    n_shallow = shallow.desired(v)[0]
    assert n_deep.price * n_deep.quantity < n_shallow.price * n_shallow.quantity


def test_ladder_is_deterministic():
    v = view({"1": q(), "2": q("2", 0.30, 0.32)})
    s = LadderStrategy()
    assert s.desired(v) == s.desired(v)


# --------------------------------------------------------------- relvalue ---

def test_relvalue_sells_when_venue_is_above_fair():
    """SIG overprices the tail; we should be the seller."""
    v = view({"1": q(bid=0.12, ask=0.14)}, fair={"1": 0.06})
    orders = RelValueStrategy().desired(v)
    assert len(orders) == 1
    assert orders[0].action == "sell"
    assert orders[0].price > 0.12          # passive: above the bid


def test_relvalue_buys_when_venue_is_below_fair():
    v = view({"1": q(bid=0.60, ask=0.62)}, fair={"1": 0.72})
    orders = RelValueStrategy().desired(v)
    assert len(orders) == 1
    assert orders[0].action == "buy"
    assert orders[0].price < 0.62          # passive: below the ask


def test_relvalue_will_not_buy_the_tail_even_when_cheap():
    """The measured negative-markout band is off limits for buying."""
    v = view({"1": q(bid=0.04, ask=0.06)}, fair={"1": 0.14})
    assert RelValueStrategy().desired(v) == []


def test_relvalue_may_still_sell_the_tail():
    v = view({"1": q(bid=0.10, ask=0.12)}, fair={"1": 0.04})
    orders = RelValueStrategy().desired(v)
    assert orders and orders[0].action == "sell"


def test_relvalue_ignores_markets_without_a_fair_value():
    assert RelValueStrategy().desired(view({"1": q()}, fair={})) == []


def test_relvalue_requires_minimum_edge():
    """Edge is evaluated at the price we would actually trade, not the mid."""
    s = RelValueStrategy(RelValueConfig(min_edge=0.05))
    # sell edge = ask - fair = 0.52 - 0.49 = 0.03 ; buy edge = fair - bid = -0.01
    v = view({"1": q(bid=0.50, ask=0.52)}, fair={"1": 0.49})
    assert s.desired(v) == []


def test_relvalue_skips_loaded_markets():
    s = RelValueStrategy(RelValueConfig(max_existing_shares=10.0))
    v = view({"1": q(bid=0.60, ask=0.62)}, fair={"1": 0.75},
             positions={"1": 500.0})
    assert s.desired(v) == []


def test_relvalue_respects_max_markets():
    quotes = {str(i): q(str(i), 0.60, 0.62) for i in range(20)}
    fair = {str(i): 0.75 for i in range(20)}
    s = RelValueStrategy(RelValueConfig(max_markets=3))
    assert len(s.desired(view(quotes, fair))) == 3


def test_relvalue_never_crosses_the_spread():
    v = view({"1": q(bid=0.60, ask=0.62)}, fair={"1": 0.90})
    for o in RelValueStrategy().desired(v):
        assert o.price < 0.62


def test_relvalue_is_deterministic():
    v = view({"1": q(bid=0.60, ask=0.62)}, fair={"1": 0.75})
    s = RelValueStrategy()
    assert s.desired(v) == s.desired(v)


def test_strategies_tag_their_budget_bucket():
    lad = LadderStrategy().desired(view({"1": q()}))
    rel = RelValueStrategy().desired(view({"1": q(bid=0.60, ask=0.62)},
                                          fair={"1": 0.75}))
    assert all(o.strategy == "ladder" for o in lad)
    assert all(o.strategy == "relvalue" for o in rel)
