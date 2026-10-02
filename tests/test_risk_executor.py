"""Tests for risk vetoes and the desired-state diff."""
import pytest

from sigbot.config import RiskLimits, Settings, StrategyBudget
from sigbot.executor import DesiredOrder, LiveOrder, Plan, plan_orders
from sigbot.risk import PortfolioState, RiskManager


def settings(**kw):
    base = dict(base_url="https://x", recon_key="r", exec_key="e")
    base.update(kw)
    return Settings(**base)


def state(**kw):
    base = dict(balance=99_000.0, equity=100_000.0, cost_basis=1_000.0,
                peak_equity=100_000.0, positions={}, deployed_by_strategy={})
    base.update(kw)
    return PortfolioState(**base)


def rm(**kw):
    return RiskManager(settings(**kw))


def d(exchange_id="36", side="yes", action="buy", price=0.50, quantity=100,
      strategy="ladder"):
    return DesiredOrder(exchange_id, side, action, price, quantity, strategy)


def lo(order_id=1, exchange_id="36", side="yes", action="buy", price=0.50,
       quantity=100):
    return LiveOrder(order_id, exchange_id, side, action, price, quantity)


# ------------------------------------------------------------ config guards --

def test_budgets_must_sum_to_one():
    with pytest.raises(ValueError):
        StrategyBudget(ladder=0.5, relvalue=0.5, reserve=0.5).validate()
    StrategyBudget().validate()          # defaults are valid


def test_risk_limits_reject_inverted_band():
    with pytest.raises(ValueError):
        RiskLimits(no_buy_below=0.9, no_buy_above=0.1)


def test_trading_requires_both_latches():
    assert not settings(dry_run=True, live_trading=True).trading_enabled
    assert not settings(dry_run=False, live_trading=False).trading_enabled
    assert settings(dry_run=False, live_trading=True).trading_enabled


# ------------------------------------------------------------------ vetoes --

def test_rejects_buying_the_negative_markout_tail():
    """Measured: buckets below 0.15 markout negative. Hard veto."""
    assert rm().check(state(), exchange_id="1", action="buy", price=0.07,
                      quantity=10, strategy="ladder") is not None


def test_allows_selling_the_tail():
    """We should be SELLING overpriced longshots, not buying them."""
    assert rm().check(state(), exchange_id="1", action="sell", price=0.07,
                      quantity=10, strategy="ladder") is None


def test_rejects_buying_above_ceiling():
    assert rm().check(state(), exchange_id="1", action="buy", price=0.99,
                      quantity=10, strategy="ladder") is not None


def test_allows_midrange_buy():
    assert rm().check(state(), exchange_id="1", action="buy", price=0.45,
                      quantity=10, strategy="ladder") is None


def test_rejects_non_positive_quantity():
    assert rm().check(state(), exchange_id="1", action="buy", price=0.5,
                      quantity=0, strategy="ladder") is not None


def test_per_market_cap_enforced():
    r = rm()
    big = int(0.06 * 100_000 / 0.5)      # 6% of equity, cap is 5%
    assert r.check(state(), exchange_id="1", action="buy", price=0.5,
                   quantity=big, strategy="ladder") is not None


def test_total_deployment_cap_enforced():
    s = state(cost_basis=89_000.0)
    assert rm().check(s, exchange_id="1", action="buy", price=0.5,
                      quantity=5000, strategy="ladder") is not None


def test_strategy_budget_enforced():
    s = state(deployed_by_strategy={"ladder": 34_900.0})
    assert rm().check(s, exchange_id="1", action="buy", price=0.5,
                      quantity=1000, strategy="ladder") is not None


def test_unknown_strategy_has_zero_budget():
    assert rm().check(state(), exchange_id="1", action="buy", price=0.5,
                      quantity=1, strategy="mystery") is not None


# ------------------------------------------------------------- kill switch --

def test_kill_switch_trips_on_drawdown_and_blocks_everything():
    r = rm()
    s = state(equity=79_000.0, peak_equity=100_000.0)
    r.update(s)
    assert r.tripped
    assert r.check(s, exchange_id="1", action="buy", price=0.5,
                   quantity=1, strategy="ladder") is not None


def test_kill_switch_does_not_trip_below_threshold():
    r = rm()
    r.update(state(equity=85_000.0, peak_equity=100_000.0))
    assert r.tripped is None


def test_kill_switch_latches_and_needs_manual_reset():
    r = rm()
    r.update(state(equity=70_000.0, peak_equity=100_000.0))
    assert r.tripped
    r.update(state(equity=100_000.0, peak_equity=100_000.0))   # recovered
    assert r.tripped, "must NOT auto-unlatch"
    r.reset()
    assert r.tripped is None


# ------------------------------------------------------------------- plan ---

def test_identical_desired_and_live_is_a_noop():
    p = plan_orders([d()], [lo()], rm(), state())
    assert p.is_noop
    assert len(p.keeps) == 1


def test_plan_is_idempotent():
    """Running the same desired state twice must not churn orders."""
    desired, live = [d()], [lo()]
    first = plan_orders(desired, live, rm(), state())
    second = plan_orders(desired, live, rm(), state())
    assert first.is_noop and second.is_noop


def test_quantity_change_forces_cancel_and_replace():
    p = plan_orders([d(quantity=200)], [lo(quantity=100)], rm(), state())
    assert len(p.cancels) == 1 and len(p.places) == 1


def test_price_change_forces_cancel_and_replace():
    p = plan_orders([d(price=0.55)], [lo(price=0.50)], rm(), state())
    assert len(p.cancels) == 1 and len(p.places) == 1


def test_live_order_not_desired_is_cancelled():
    p = plan_orders([], [lo()], rm(), state())
    assert len(p.cancels) == 1 and not p.places


def test_desired_order_not_live_is_placed():
    p = plan_orders([d()], [], rm(), state())
    assert len(p.places) == 1 and not p.cancels


def test_vetoed_orders_are_not_placed_and_are_reported():
    p = plan_orders([d(price=0.05)], [], rm(), state())
    assert not p.places
    assert len(p.vetoed) == 1
    assert "no-buy floor" in p.vetoed[0][1]


def test_veto_does_not_cancel_unrelated_live_orders():
    """A vetoed desire must not cause an unrelated resting order to be kept."""
    p = plan_orders([d(price=0.05)], [lo(order_id=9, price=0.50)], rm(), state())
    assert [c.order_id for c in p.cancels] == [9]


def test_duplicate_desired_orders_match_distinct_live_orders():
    desired = [d(quantity=100), d(quantity=100)]
    live = [lo(order_id=1), lo(order_id=2)]
    p = plan_orders(desired, live, rm(), state())
    assert p.is_noop and len(p.keeps) == 2


def test_more_desired_than_live_places_the_remainder():
    desired = [d(quantity=100), d(quantity=100)]
    p = plan_orders(desired, [lo(order_id=1)], rm(), state())
    assert len(p.keeps) == 1 and len(p.places) == 1 and not p.cancels


def test_sides_do_not_cross_match():
    p = plan_orders([d(side="yes")], [lo(side="no")], rm(), state())
    assert len(p.places) == 1 and len(p.cancels) == 1


def test_different_exchanges_do_not_match():
    p = plan_orders([d(exchange_id="1")], [lo(exchange_id="2")], rm(), state())
    assert len(p.places) == 1 and len(p.cancels) == 1


def test_live_order_from_api_parses_venue_shape():
    parsed = LiveOrder.from_api({"id": 42, "exchangeId": "36", "side": "yes",
                                 "action": "buy", "priceLimit": 0.42, "quantity": 7})
    assert parsed.order_id == 42 and parsed.price == 0.42


def test_plan_summary_is_readable():
    p = plan_orders([d(), d(price=0.05)], [lo(order_id=5, price=0.9)], rm(), state())
    assert "cancel=" in p.summary()


# ---------------------------------------------------------- portfolio state --

def test_drawdown_and_deployment_fractions():
    s = state(equity=80_000.0, peak_equity=100_000.0, cost_basis=20_000.0)
    assert abs(s.drawdown - 0.20) < 1e-12
    assert abs(s.deployed_fraction - 0.25) < 1e-12


def test_drawdown_is_zero_when_at_peak():
    assert state(equity=100_000.0, peak_equity=100_000.0).drawdown == 0.0
