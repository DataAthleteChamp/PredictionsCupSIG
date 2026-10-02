"""Tests for outcome analysis and pair completion — the market-neutral core."""
import pytest

from sigbot.portfolio import Leg, RacePosition, portfolio_floor
from sigbot.strategies.base import MarketView, Quote
from sigbot.strategies.pair import PairConfig, PairStrategy


def rp(outcomes=("R", "D"), legs=()):
    return RacePosition("race", outcomes, list(legs))


# ------------------------------------------------------------------- Leg ----

def test_long_yes_cost_and_payout():
    l = Leg("R", 100, 0.30)
    assert l.cost == pytest.approx(30.0)
    assert l.payout_if("R") == 100
    assert l.payout_if("D") == 0


def test_short_yes_is_long_no():
    """Selling YES at 0.30 is buying NO at 0.70 and pays when R loses."""
    l = Leg("R", -100, 0.30)
    assert l.cost == pytest.approx(70.0)
    assert l.payout_if("R") == 0
    assert l.payout_if("D") == 100


# --------------------------------------------------------- guaranteed floor --

def test_single_side_is_never_risk_free():
    pos = rp(legs=[Leg("R", 100, 0.40)])
    assert pos.worst_payout == 0
    assert pos.guaranteed_floor == pytest.approx(-40.0)
    assert not pos.is_risk_free


def test_both_sides_below_one_is_risk_free():
    """The whole point: pay 0.90 combined, collect 1.00 whoever wins."""
    pos = rp(legs=[Leg("R", 100, 0.40), Leg("D", 100, 0.50)])
    assert pos.worst_payout == 100
    assert pos.guaranteed_floor == pytest.approx(10.0)
    assert pos.is_risk_free


def test_both_sides_above_one_is_a_guaranteed_loss():
    pos = rp(legs=[Leg("R", 100, 0.55), Leg("D", 100, 0.55)])
    assert pos.guaranteed_floor == pytest.approx(-10.0)


def test_unequal_quantities_leave_a_directional_tail():
    """Matches the real Alaska book: 254 D vs 217 R is only partly hedged."""
    pos = rp(legs=[Leg("D", 254, 0.667), Leg("R", 217, 0.230)])
    assert pos.worst_payout == 217
    assert pos.guaranteed_floor < 0          # the unpaired 37 shares are naked


def test_third_party_breaks_a_two_sided_pair():
    """Holding R and D is NOT risk-free when an Independent can win."""
    two_way = rp(("R", "D"), [Leg("R", 100, 0.70), Leg("D", 100, 0.03)])
    assert two_way.is_risk_free
    three_way = RacePosition("x", ("R", "D", "I"),
                             [Leg("R", 100, 0.70), Leg("D", 100, 0.03)])
    assert three_way.worst_payout == 0       # Independent wins -> both lose
    assert not three_way.is_risk_free


def test_three_way_fully_covered_is_risk_free():
    pos = RacePosition("x", ("R", "D", "I"),
                       [Leg("R", 100, 0.70), Leg("D", 100, 0.03), Leg("I", 100, 0.22)])
    assert pos.guaranteed_floor == pytest.approx(5.0)
    assert pos.is_risk_free


def test_empty_position_is_flat():
    assert rp().guaranteed_floor == 0.0
    assert rp().worst_payout == 0.0


# -------------------------------------------------------- lock price search --

def test_max_price_to_lock_is_the_complement():
    pos = rp(legs=[Leg("R", 100, 0.40)])
    px = pos.max_price_to_lock("D", 100)
    assert px == pytest.approx(0.60, abs=1e-3)   # 0.40 + 0.60 = 1.00 break-even


def test_lock_price_reflects_an_already_cheap_leg():
    pos = rp(legs=[Leg("R", 100, 0.20)])
    assert pos.max_price_to_lock("D", 100) == pytest.approx(0.80, abs=1e-3)


def test_lock_price_is_unusably_small_when_leg_already_near_one():
    """A 0.999 leg leaves almost nothing to pay: the lock price is below the
    venue's minimum tick, so the strategy cannot act on it."""
    from sigbot.config import MIN_PRICE
    pos = rp(legs=[Leg("R", 100, 0.999)])
    px = pos.max_price_to_lock("D", 100)
    assert px is None or px < MIN_PRICE


def test_lock_price_rejects_unknown_party():
    assert rp(legs=[Leg("R", 100, 0.4)]).max_price_to_lock("Z", 100) is None


def test_lock_price_rejects_non_positive_quantity():
    assert rp(legs=[Leg("R", 100, 0.4)]).max_price_to_lock("D", 0) is None


def test_buying_at_the_lock_price_yields_a_nonnegative_floor():
    pos = rp(legs=[Leg("R", 100, 0.35)])
    px = pos.max_price_to_lock("D", 100)
    completed = rp(legs=pos.legs + [Leg("D", 100, px)])
    assert completed.guaranteed_floor >= -1e-6


# ------------------------------------------------------------ aggregation ---

def test_portfolio_floor_sums_independent_races():
    a = rp(legs=[Leg("R", 100, 0.40), Leg("D", 100, 0.50)])     # +10
    b = rp(legs=[Leg("R", 100, 0.40)])                           # -40
    agg = portfolio_floor([a, b])
    assert agg["guaranteed_floor"] == pytest.approx(-30.0)
    assert agg["n_risk_free"] == 1
    assert agg["risk_free_floor"] == pytest.approx(10.0)


def test_portfolio_best_case_exceeds_floor():
    agg = portfolio_floor([rp(legs=[Leg("R", 100, 0.40)])])
    assert agg["best_case"] > agg["guaranteed_floor"]


# --------------------------------------------------------- pair strategy ----

def view(quotes):
    return MarketView(quotes=quotes, fair={}, positions={}, equity=100_000.0)


def test_pair_strategy_bids_the_complement_to_lock():
    races = {"race": rp(legs=[Leg("R", 100, 0.30)])}
    px = {("race", "D"): "77"}
    quotes = {"77": Quote("77", 0.50, 0.55)}
    out = PairStrategy().desired(view(quotes), races, px)
    assert len(out) == 1
    o = out[0]
    assert o.exchange_id == "77" and o.action == "buy"
    assert o.price < 0.55                  # passive, never crosses
    assert o.price <= 0.70                 # must still lock against the 0.30 leg


def test_pair_strategy_skips_already_locked_races():
    races = {"race": rp(legs=[Leg("R", 100, 0.40), Leg("D", 100, 0.50)])}
    out = PairStrategy().desired(view({"77": Quote("77", 0.4, 0.5)}),
                                 races, {("race", "D"): "77"})
    assert out == []


def test_pair_strategy_requires_minimum_lock_edge():
    """If the ask is already at the break-even price there is nothing to lock."""
    races = {"race": rp(legs=[Leg("R", 100, 0.30)])}
    quotes = {"77": Quote("77", 0.695, 0.70)}
    s = PairStrategy(PairConfig(min_lock_edge=0.05))
    assert s.desired(view(quotes), races, {("race", "D"): "77"}) == []


def test_pair_strategy_targets_the_worst_outcome():
    """With R and D held but I uncovered, it must bid the Independent."""
    races = {"race": RacePosition("race", ("R", "D", "I"),
                                  [Leg("R", 100, 0.60), Leg("D", 100, 0.05)])}
    px = {("race", "I"): "99", ("race", "D"): "88"}
    quotes = {"99": Quote("99", 0.20, 0.25), "88": Quote("88", 0.04, 0.06)}
    out = PairStrategy().desired(view(quotes), races, px)
    assert len(out) == 1 and out[0].exchange_id == "99"


def test_pair_strategy_needs_both_inputs():
    s = PairStrategy()
    assert s.desired(view({}), None, None) == []
    assert s.desired(view({}), {"r": rp()}, None) == []


def test_pair_strategy_skips_untradeable_books():
    races = {"race": rp(legs=[Leg("R", 100, 0.30)])}
    quotes = {"77": Quote("77", None, None)}
    assert PairStrategy().desired(view(quotes), races, {("race", "D"): "77"}) == []


def test_pair_strategy_is_deterministic():
    races = {"race": rp(legs=[Leg("R", 100, 0.30)])}
    px = {("race", "D"): "77"}
    quotes = {"77": Quote("77", 0.50, 0.55)}
    s = PairStrategy()
    assert s.desired(view(quotes), races, px) == s.desired(view(quotes), races, px)


def test_pair_strategy_uses_the_ladder_budget():
    assert PairStrategy().name == "ladder"
