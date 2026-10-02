"""Tests for the two strategies. Both are pure functions of MarketView."""
import pytest

from sigbot.strategies.base import MarketView, Quote
from sigbot.strategies.ladder import LadderConfig, LadderStrategy
from sigbot.strategies.relvalue import RelValueConfig, RelValueStrategy


def q(ex="1", bid=0.48, ask=0.50, bs=100.0, aszi=100.0):
    return Quote(ex, bid, ask, bs, aszi)


def view(quotes=None, fair=None, positions=None, equity=100_000.0,
         activity=None):
    return MarketView(quotes=quotes or {}, fair=fair or {},
                      positions=positions or {}, equity=equity,
                      activity=activity or {})


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


# ----------------------------------------------------------- convex sleeve --

from sigbot.strategies.sleeve import SleeveConfig, SleeveStrategy


def test_sleeve_ignores_cheap_contracts_without_a_discount():
    """
    The whole point: do NOT buy a tail just because it is cheap. We measured
    sub-0.15 buckets markout negative and SIG tails at 1.98x Polymarket.
    """
    v = view({"1": q(bid=0.04, ask=0.05)}, fair={"1": 0.05})   # no discount
    assert SleeveStrategy().desired(v) == []


def test_sleeve_buys_a_tail_priced_below_the_anchor():
    """Contrary to the measured bias => a filtered signal, not a lottery."""
    v = view({"1": q(bid=0.04, ask=0.05)}, fair={"1": 0.12})
    out = SleeveStrategy().desired(v)
    assert len(out) == 1
    assert out[0].strategy == "sleeve" and out[0].action == "buy"
    assert out[0].price < 0.05           # passive, never pays the offer


def test_sleeve_rejects_insufficient_convexity():
    """A 0.50 contract pays 2x - not convex enough to matter."""
    s = SleeveStrategy(SleeveConfig(max_price=0.6, min_multiple=5.0))
    v = view({"1": q(bid=0.49, ask=0.50)}, fair={"1": 0.70})
    assert s.desired(v) == []


def test_sleeve_concentrates_on_the_best_discounts():
    quotes = {str(i): q(str(i), 0.04, 0.05) for i in range(20)}
    fair = {str(i): 0.05 + 0.005 * i for i in range(20)}
    out = SleeveStrategy(SleeveConfig(max_positions=3)).desired(view(quotes, fair))
    assert len(out) == 3
    # the three largest discounts are the highest-index markets
    assert {o.exchange_id for o in out} == {"19", "18", "17"}


def test_sleeve_is_empty_when_no_edge_exists():
    """An empty sleeve is correct when the edge is absent."""
    quotes = {str(i): q(str(i), 0.04, 0.05) for i in range(20)}
    fair = {str(i): 0.03 for i in range(20)}      # SIG richer than anchor
    assert SleeveStrategy().desired(view(quotes, fair)) == []


def test_sleeve_requires_a_fair_value():
    assert SleeveStrategy().desired(view({"1": q(bid=0.04, ask=0.05)}, fair={})) == []


def test_barbell_budgets_validate():
    from sigbot.config import StrategyBudget
    StrategyBudget().validate()
    with pytest.raises(ValueError):
        StrategyBudget(ladder=0.1, relvalue=0.1, sleeve=0.5, reserve=0.3).validate()


# ------------------------------------------------- ladder depth retuning ---

def test_ladder_quotes_near_the_measured_ev_optimum():
    """
    Bootstrap put 2-3 ticks below mid at 87% probability of being the best
    depth. The shallowest rung must land in that neighbourhood, not 16+ ticks
    out where the fill rate collapses.
    """
    from sigbot.strategies.ladder import LadderConfig
    shallowest = min(LadderConfig().offsets)
    assert 0.010 <= shallowest <= 0.020          # 2-4 ticks


def test_ladder_keeps_a_deep_rung_for_dislocations():
    from sigbot.strategies.ladder import LadderConfig
    assert max(LadderConfig().offsets) >= 0.05


def test_ladder_shallow_rung_still_never_improves_the_touch():
    """Shallower quoting must not start crossing or leading the book."""
    s = LadderStrategy()
    # 2.88-tick spread, the measured average
    v = view({"1": q(bid=0.4928, ask=0.5072)})
    for o in s.desired(v):
        assert o.price < 0.4928


# --------------------------------------------- activity-ranked selection ---

def test_quotes_are_ordered_busiest_first():
    from sigbot.strategies.base import MarketView
    v = MarketView(quotes={"1": q(), "2": q(), "3": q()}, fair={},
                   positions={}, equity=100_000.0,
                   activity={"1": 0.0, "2": 9.0, "3": 4.0})
    assert [ex for ex, _ in v.by_activity()] == ["2", "3", "1"]


def test_activity_ordering_is_stable_without_scores():
    """No activity data must fall back to a deterministic order."""
    from sigbot.strategies.base import MarketView
    v = MarketView(quotes={"3": q(), "1": q(), "2": q()}, fair={},
                   positions={}, equity=100_000.0)
    assert [ex for ex, _ in v.by_activity()] == ["1", "2", "3"]


def test_ladder_quotes_the_busiest_markets_under_its_cap():
    """
    The capital cap binds, so market CHOICE sets the fill rate. Ranking by
    exchange id put us in markets holding 12% of venue flow.
    """
    from sigbot.strategies.ladder import LadderConfig
    quotes = {str(i): q(bid=0.48, ask=0.50) for i in range(1, 21)}
    activity = {str(i): float(i) for i in range(1, 21)}   # 20 is busiest
    v = view(quotes, activity=activity)
    s = LadderStrategy(LadderConfig(max_markets=3))
    got = {o.exchange_id for o in s.desired(v)}
    assert got == {"20", "19", "18"}


def test_activity_score_counts_price_changes_and_decays():
    from sigbot.runner import update_activity, ACTIVITY_DECAY
    st = {}
    update_activity(st, {"1": {"latestPrice": 0.50}, "2": {"latestPrice": 0.30}})
    assert st["activity"] == {"1": 0.0, "2": 0.0}        # first cycle: baseline
    update_activity(st, {"1": {"latestPrice": 0.55}, "2": {"latestPrice": 0.30}})
    assert st["activity"]["1"] == pytest.approx(1.0)     # traded
    assert st["activity"]["2"] == pytest.approx(0.0)     # did not
    update_activity(st, {"1": {"latestPrice": 0.55}, "2": {"latestPrice": 0.30}})
    assert st["activity"]["1"] == pytest.approx(ACTIVITY_DECAY)   # decays


def test_activity_ignores_markets_without_a_last_price():
    from sigbot.runner import update_activity
    st = {}
    update_activity(st, {"1": {"latestPrice": None}})
    assert st["activity"] == {}
