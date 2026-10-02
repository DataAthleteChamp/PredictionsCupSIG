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


# ------------------------------------------------- managed-order scoping ----

def test_unmanaged_orders_are_never_cancelled():
    """The bot must not touch manual experiments or another process's orders."""
    external = lo(order_id=999, price=0.30)
    p = plan_orders([], [external], rm(), state(), managed_order_ids=set())
    assert p.cancels == []
    assert p.is_noop


def test_managed_orders_are_cancelled_when_not_desired():
    mine = lo(order_id=7, price=0.30)
    p = plan_orders([], [mine], rm(), state(), managed_order_ids={7})
    assert [c.order_id for c in p.cancels] == [7]


def test_mixed_managed_and_unmanaged():
    mine, theirs = lo(order_id=1, price=0.30), lo(order_id=2, price=0.30)
    p = plan_orders([], [mine, theirs], rm(), state(), managed_order_ids={1})
    assert [c.order_id for c in p.cancels] == [1]


def test_unmanaged_order_does_not_satisfy_a_desire():
    """An identical external order must not stop us placing our own."""
    external = lo(order_id=42, price=0.50, quantity=100)
    p = plan_orders([d(price=0.50, quantity=100)], [external], rm(), state(),
                    managed_order_ids=set())
    assert len(p.places) == 1
    assert p.cancels == []


def test_none_means_manage_everything():
    p = plan_orders([], [lo(order_id=5)], rm(), state(), managed_order_ids=None)
    assert len(p.cancels) == 1


# ------------------------------------------------------ executor batching ---

class _StubClient:
    def __init__(self, dry=False):
        from sigbot.config import Settings
        self.s = Settings(base_url="x", recon_key="r", exec_key="e",
                          dry_run=dry, live_trading=not dry)
        self.batches = []
        self.singles = []
        self.cancelled = []

    def place_batch(self, orders, idempotency_key=None):
        self.batches.append(orders)
        return {"results": [{"ok": True, "index": i} for i in range(len(orders))]}

    def place_order(self, *a, **k):
        self.singles.append(a)
        return {}

    def cancel_order(self, oid):
        self.cancelled.append(oid)


def test_executor_batches_placements():
    from sigbot.executor import Executor
    cl = _StubClient()
    places = [d(exchange_id=str(i), price=0.50) for i in range(120)]
    plan = Plan(cancels=[], places=places, keeps=[], vetoed=[])
    out = Executor(cl, rm()).apply(plan)
    assert len(cl.batches) == 3            # 50 + 50 + 20
    assert out["placed"] == 120
    assert out["requests"] == 3            # not 120
    assert not cl.singles


def test_executor_single_place_when_only_one():
    from sigbot.executor import Executor
    cl = _StubClient()
    plan = Plan(cancels=[], places=[d()], keeps=[], vetoed=[])
    Executor(cl, rm()).apply(plan)
    assert len(cl.singles) == 1 and not cl.batches


def test_executor_dry_run_places_nothing():
    from sigbot.executor import Executor
    cl = _StubClient(dry=True)
    plan = Plan(cancels=[lo()], places=[d(), d(price=0.4)], keeps=[], vetoed=[])
    out = Executor(cl, rm()).apply(plan)
    assert out["dry_run"] and out["placed"] == 0
    assert not cl.batches and not cl.singles and not cl.cancelled
    assert len(out["would_place"]) == 2


def test_executor_cancels_before_placing():
    from sigbot.executor import Executor
    cl = _StubClient()
    plan = Plan(cancels=[lo(order_id=3)], places=[d(), d(price=0.4)],
                keeps=[], vetoed=[])
    Executor(cl, rm()).apply(plan)
    assert cl.cancelled == [3]


# ------------------------------------------ cumulative risk accumulation ----

def test_many_small_orders_cannot_collectively_breach_a_budget():
    """
    The bug this guards: evaluating every order against the SAME starting state
    lets 200 individually-valid orders blow through a cap none of them breaches.
    """
    # ladder budget is 35% of 100k = 35,000. Each order is 1,000 notional.
    desired = [d(exchange_id=str(i), price=0.50, quantity=2000)
               for i in range(60)]
    p = plan_orders(desired, [], rm(), state())
    approved = len(p.places) + len(p.keeps)
    assert p.vetoed, "some orders must be vetoed once the budget is exhausted"
    assert approved * 1000 <= 35_000 + 1000


def test_cumulative_per_market_cap_across_repeated_orders():
    """Repeated orders on the SAME market must accumulate toward its cap."""
    desired = [d(exchange_id="1", price=0.50, quantity=2000) for _ in range(10)]
    p = plan_orders(desired, [], rm(), state())
    # per-market cap is 5% of 100k = 5,000 -> at 1,000 each, ~5 fit
    assert len(p.places) <= 6
    assert p.vetoed


def test_cumulative_accounting_does_not_mutate_caller_state():
    s = state()
    before_cost = s.cost_basis
    before_pos = dict(s.positions)
    plan_orders([d(), d(exchange_id="2")], [], rm(), s)
    assert s.cost_basis == before_cost
    assert s.positions == before_pos


def test_kept_orders_still_consume_budget():
    """A kept resting order is live exposure and must count against the cap."""
    desired = [d(exchange_id="1", price=0.50, quantity=2000) for _ in range(10)]
    live = [lo(order_id=1, exchange_id="1", price=0.50, quantity=2000)]
    p = plan_orders(desired, live, rm(), state(), managed_order_ids={1})
    assert len(p.keeps) == 1
    assert p.vetoed            # the keep consumed budget like a place would


# ------------------------------------------------------ ownership safety ----

def test_executor_reports_only_ids_it_placed():
    from sigbot.executor import Executor

    class C(_StubClient):
        def place_order(self, *a, **k):
            return {"orderId": 4242}

    cl = C()
    out = Executor(cl, rm()).apply(Plan([], [d()], [], []))
    assert out["placed_order_ids"] == [4242]


def test_executor_collects_batch_order_ids():
    from sigbot.executor import Executor

    class C(_StubClient):
        def place_batch(self, orders, idempotency_key=None):
            return {"results": [{"ok": True, "index": i,
                                 "data": {"orderId": 100 + i}}
                                for i in range(len(orders))]}

    cl = C()
    out = Executor(cl, rm()).apply(Plan([], [d(), d(price=0.4)], [], []))
    assert sorted(out["placed_order_ids"]) == [100, 101]
    assert out["placed"] == 2


def test_executor_counts_failed_batch_items_as_errors_not_placed():
    from sigbot.executor import Executor

    class C(_StubClient):
        def place_batch(self, orders, idempotency_key=None):
            return {"results": [{"ok": True, "index": 0, "data": {"orderId": 1}},
                                {"ok": False, "index": 1,
                                 "data": {"code": "VALIDATION_ERROR"}}]}

    out = Executor(C(), rm()).apply(Plan([], [d(), d(price=0.4)], [], []))
    assert out["placed"] == 1
    assert out["placed_order_ids"] == [1]
    assert len(out["errors"]) == 1
