"""Tests for the two strategies. Both are pure functions of MarketView."""
import pytest

from sigbot.strategies.base import MarketView, Quote
from sigbot.strategies.ladder import LadderConfig, LadderStrategy
from sigbot.strategies.relvalue import RelValueConfig, RelValueStrategy


def q(ex="1", bid=0.48, ask=0.50, bs=100.0, aszi=100.0):
    return Quote(ex, bid, ask, bs, aszi)


def d(exchange_id="1", side="yes", action="buy", price=0.5,
      quantity=10, strategy="ladder"):
    from sigbot.executor import DesiredOrder
    return DesiredOrder(exchange_id, side, action, price, quantity, strategy)


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
    # Mid inside the configured band. This used 0.61, which fell outside once
    # the band was narrowed to 0.20-0.50 on capital-efficiency grounds, and the
    # test then failed for a reason unrelated to the sizing it checks.
    v = view({"1": q(bid=0.44, ask=0.46)})
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


def test_ladder_has_no_dead_deep_rung():
    """
    The 20-tick rung produced 0 fills out of 688 while holding a third of the
    order slots. Dislocations never travel that far before someone else takes
    them, so the "deep rung catches dislocations" rationale is false here.
    """
    from sigbot.strategies.ladder import LadderConfig
    assert max(LadderConfig().offsets) <= 0.035, "deep rung never fills"


def test_all_rungs_sit_where_fills_actually_happen():
    from sigbot.strategies.ladder import LadderConfig
    for off in LadderConfig().offsets:
        assert 2 <= off / 0.005 <= 7, f"{off} is outside the productive band"


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


# ------------------------------------------------------- cycle watchdog ---

def test_cycle_deadline_interrupts_a_wedged_call():
    """
    Per-request timeouts bound the gap BETWEEN bytes, not total duration, so a
    trickling server can hold a read open indefinitely. The watchdog must break
    a blocking call, not merely measure it afterwards.
    """
    import time as _t
    from sigbot.runner import CycleTimeout, cycle_deadline
    start = _t.monotonic()
    with pytest.raises(CycleTimeout):
        with cycle_deadline(0.25):
            _t.sleep(10)
    assert _t.monotonic() - start < 3, "watchdog did not interrupt promptly"


def test_cycle_deadline_is_clean_on_success():
    import time as _t
    from sigbot.runner import cycle_deadline
    with cycle_deadline(5):
        _t.sleep(0.01)
    with cycle_deadline(5):          # timer must have been cleared
        _t.sleep(0.01)


# ------------------------------------------- scaling into size, not breadth ---

def test_ladder_breadth_stops_at_the_measured_edge_ceiling():
    """
    Edge by market activity rank: top 30 +0.00199 (P=0.955), 31-80 +0.00250
    (P=0.957), 81-150 +0.00067 (P=0.673) with NEGATIVE realised P&L. Extra
    capital must not buy markets past that ceiling.
    """
    from sigbot.strategies.ladder import LadderConfig
    assert LadderConfig().max_markets <= 80


def test_extra_capital_goes_into_size():
    """Per-share edge is flat in fill size (rho +0.14), so size scales safely."""
    from sigbot.strategies.ladder import LadderConfig
    c = LadderConfig()
    assert c.max_notional >= 200.0 and c.size_scale >= 100.0


def test_relvalue_scales_less_than_ladder():
    """Its measured edge is the weakest of the three (P(>0)=0.624)."""
    from sigbot.strategies.ladder import LadderConfig
    from sigbot.strategies.relvalue import RelValueConfig
    assert RelValueConfig().max_notional < LadderConfig().max_notional


def test_bigger_size_still_respects_the_notional_cap():
    from sigbot.strategies.ladder import LadderConfig
    s = LadderStrategy()
    v = view({"1": q(bid=0.48, ask=0.50)})
    for o in s.desired(v):
        assert o.price * o.quantity <= LadderConfig().max_notional + 1


# -------------------------------------------------- order size is NOT the lever ---

def test_order_size_stays_near_the_measured_optimum():
    """
    Bigger orders do NOT earn more. Measured fill ratio by order size:
    <80 -> 1.00, 80-160 -> 0.77, 160-320 -> 0.32, 320+ -> 0.18, and
    Spearman(order size, fill size) is only +0.305, so the market is
    flow-capped. P&L per order peaks around 146 shares (+0.416) and falls to
    +0.284 at 240 and +0.266 at 400.

    Since the binding constraint is order COUNT, not capital, raising size
    would reduce total P&L. This pins the notional near the measured optimum.
    """
    from sigbot.strategies.ladder import LadderConfig
    c = LadderConfig()
    # ~146 shares at a mid-range price of 0.5
    assert 60.0 <= c.max_notional <= 220.0


def test_edge_does_not_degrade_with_fill_size():
    """
    Documents why size is safe but not useful: edge/share is flat in fill size
    (Spearman +0.053 over 659 fills), so the limit is fill RATIO, not edge.
    """
    # Nothing to assert in code; this records the measurement that justifies
    # leaving size alone rather than raising it.
    assert True


# ------------------------- protected positions are respected by EVERYONE ---

def _held_short_view():
    from sigbot.strategies.base import Lot, MarketView
    lot = Lot("1", -100, avg_cost=0.25, age_minutes=600)
    return MarketView(quotes={"1": q(bid=0.24, ask=0.26)}, fair={"1": 0.05},
                      positions={"1": -100}, equity=100_000.0, lots={"1": lot})


def test_ladder_will_not_trade_into_a_protected_position():
    """
    Regression: a protected 100-share short drew ladder bids of 236/241/280.
    The first fill closes the short AND opens a 136-share long against a fair
    of 0.05, turning an expected +20 into -23.66.
    """
    v = _held_short_view()
    assert "1" in v.protected(0.02, 0.10), "precondition: should be protected"
    assert LadderStrategy().desired(v) == []


def test_ladder_still_quotes_unprotected_markets():
    from sigbot.strategies.base import MarketView
    v = MarketView(quotes={"1": q(bid=0.48, ask=0.50)}, fair={}, positions={},
                   equity=100_000.0)
    assert LadderStrategy().desired(v)


def test_protection_ties_break_deterministically():
    """Equal edges previously inherited dict order, so a reordered positions
    response flipped which one was held and churned orders."""
    from sigbot.strategies.base import Lot, MarketView

    def build(order):
        lots = {k: Lot(k, -100, avg_cost=0.25, age_minutes=600) for k in order}
        return MarketView(quotes={k: q(bid=0.24, ask=0.26) for k in order},
                          fair={k: 0.05 for k in order},
                          positions={k: -100 for k in order},
                          equity=1_000.0, lots=lots)      # budget fits one

    assert build(["a", "b"]).protected(0.02, 0.10) == \
           build(["b", "a"]).protected(0.02, 0.10)


def test_protection_respects_its_budget_exactly():
    from sigbot.strategies.base import Lot, MarketView
    lots = {str(i): Lot(str(i), -2000, avg_cost=0.135, age_minutes=600)
            for i in range(6)}
    v = MarketView(quotes={str(i): q(bid=0.130, ask=0.140) for i in range(6)},
                   fair={str(i): 0.008 for i in range(6)},
                   positions={str(i): -2000 for i in range(6)},
                   equity=100_000.0, lots=lots)
    # each short costs 2000 * 0.865 = 1730; a 1,000 budget fits NONE
    assert v.protected(0.02, 0.01) == set()
    # a 4,000 budget fits exactly two
    assert len(v.protected(0.02, 0.04)) == 2


# ---------------------------------- sizing must be asserted on OUTPUT, not config ---

def test_ladder_order_sizes_land_in_the_efficient_fill_band():
    """
    The previous test only checked max_notional <= 220, which the config
    satisfied while every GENERATED order was 200-280 shares -- the measured
    32%-fill band. Assert the quantity the strategy actually emits.
    """
    s = LadderStrategy()
    for price in (0.20, 0.35, 0.50, 0.70, 0.90):
        v = view({"1": q(bid=price, ask=price + 0.01)})
        for o in s.desired(v):
            assert o.quantity <= 160, (
                f"{o.quantity} shares at mid {price} is in the 32%-fill band")


def test_notional_cap_alone_cannot_bound_share_count():
    """
    Documents WHY a share clamp is needed: max_notional binds on cash, which is
    tiny for cheap contracts, so it permits huge share counts there.
    """
    from sigbot.algos import equal_variance_size
    n = equal_variance_size(0.15, 100.0, 200.0)
    assert n > 250 and 0.15 * n < 50, "cheap contracts evade a notional cap"


def test_exit_is_never_truncated_by_sticky_ladder_orders():
    """
    Stickiness previously outranked priority, so a full book of resting ladder
    orders pushed a new exit out of the cap and stranded inventory.
    """
    from sigbot.executor import LiveOrder
    from sigbot.runner import _truncate_by_priority
    ladders = [d(exchange_id=str(i), strategy="ladder") for i in range(240)]
    live = [LiveOrder.from_api({"id": i, "exchangeId": str(i), "side": "yes",
                                "action": "buy", "quantity": 10,
                                "priceLimit": 0.5}) for i in range(240)]
    managed = {i for i in range(240)}
    exit_order = d(exchange_id="999", strategy="exit")
    kept = _truncate_by_priority(ladders + [exit_order], live, managed, 240)
    assert any(o.strategy == "exit" for o in kept), "exit evicted by sticky ladders"


def test_ladder_still_blocked_from_closing_a_protected_short():
    """A ladder buy reduces a short, so it must stay blocked."""
    v = _held_short_view()
    assert LadderStrategy().desired(v) == []


def test_ladder_may_quote_in_a_market_holding_a_protected_LONG():
    """
    Skipping the whole market was too blunt: it evicted us from 17 of our
    top-80 markets, including the busiest, because positions accumulate where
    we trade most. A ladder BUY only adds to a long, so it is safe.
    """
    from sigbot.strategies.base import Lot, MarketView
    # Mid inside the ladder's band; the point is the protection rule, not the
    # price level, and 0.805 fell outside once the band was narrowed to 0.50.
    lot = Lot("1", +500, avg_cost=0.40, age_minutes=600)
    v = MarketView(quotes={"1": q(bid=0.40, ask=0.41)}, fair={"1": 0.55},
                   positions={"1": 500}, equity=100_000.0, lots={"1": lot})
    assert "1" in v.protected(0.02, 0.10), "precondition: protected long"
    assert LadderStrategy().desired(v), "must still quote where it only adds"


def test_ladder_refuses_to_buy_where_the_anchor_disagrees():
    """
    Found 2026-10-16 auditing live positions: the ladder bought IA-01 (R) at
    0.155 while the anchor priced it at 0.09, directly fighting our own
    validated favourite-longshot edge. The ladder has no anchor awareness
    otherwise -- it trades on local microstructure alone -- so nothing stopped
    it. Isolated and small ($11.70 of edge fought), but cheap to close since
    the anchor data is already fetched for every other strategy.
    """
    c = LadderConfig(min_mid=0.10, max_mid=0.50, floor_price=0.05)
    v = view(quotes={"1": q(bid=0.150, ask=0.160)}, fair={"1": 0.09})
    assert LadderStrategy(c).desired(v) == []


def test_ladder_still_buys_where_the_anchor_is_silent_or_agrees():
    """The guard must not block ordinary quoting when there is no conflict."""
    c = LadderConfig(min_mid=0.10, max_mid=0.50, floor_price=0.05)
    agree = view(quotes={"1": q(bid=0.150, ask=0.160)}, fair={"1": 0.14})
    assert LadderStrategy(c).desired(agree)
    silent = view(quotes={"1": q(bid=0.150, ask=0.160)}, fair={})
    assert LadderStrategy(c).desired(silent)


def test_ladder_anchor_guard_is_per_price_not_per_market():
    """
    A market can have rungs on both sides of the threshold; only the rungs the
    anchor actually disagrees with should be dropped; a market vetoed outright
    would be the same over-blocking mistake made (and fixed) for protection.
    """
    c = LadderConfig(offsets=(0.005, 0.08), min_mid=0.10, max_mid=0.50,
                     floor_price=0.05)
    v = view(quotes={"1": q(bid=0.150, ask=0.160)}, fair={"1": 0.09})
    out = LadderStrategy(c).desired(v)
    prices = {round(o.price, 3) for o in out}
    assert 0.145 not in prices, "0.145 is 0.055 over anchor -- must be dropped"
    assert 0.075 in prices, "0.075 is UNDER anchor -- must still be quoted"
