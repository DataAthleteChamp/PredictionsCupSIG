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


def test_batch_with_unrecognised_response_does_not_claim_success():
    """Failing open here would overstate placements and lose order ids."""
    from sigbot.executor import Executor

    class C(_StubClient):
        def place_batch(self, orders, idempotency_key=None):
            return {"unexpected": True}

    out = Executor(C(), rm()).apply(Plan([], [d(), d(price=0.4)], [], []))
    assert out["placed"] == 0
    assert out["errors"]


# ------------------------------------------------ short collateral ---------

def test_selling_the_cheap_tail_is_charged_full_collateral():
    """Selling YES at 0.02 is a long NO at 0.98 and ties up 980, not 20."""
    from sigbot.risk import collateral
    assert collateral("sell", 0.02, 1000) == pytest.approx(980.0)
    assert collateral("buy", 0.02, 1000) == pytest.approx(20.0)


def test_tail_sells_exhaust_the_strategy_budget_at_the_right_rate():
    """
    The fix is about ACCOUNTING, not a single veto: 980 of collateral is under
    the 5% per-market cap, but it consumes the relvalue budget 49x faster than
    the old price*quantity math did.

    The relvalue budget is constructed EXPLICITLY rather than read from the
    live default. A previous version hardcoded "roughly 25" (the then-current
    25% allocation) and failed when the budget was reallocated for unrelated
    reasons; a later version derived the expectation from the live default
    instead, which fixed that but created the same coupling one step removed --
    it broke again once relvalue's real-world allocation shrank to 0.5% (too
    small for even one 980-collateral sell to fit at all). The invariant this
    checks is the divisor -- budget/980, not budget/20 -- which has nothing to
    do with what relvalue is actually funded at any given day, so the test now
    picks its own budget to demonstrate it.
    """
    budgets = StrategyBudget(settlement=0.0, ladder=0.0, relvalue=0.25,
                             sleeve=0.0, reserve=0.75)
    budget = budgets.relvalue * 100_000.0
    expect = int(budget // 980.0)
    assert expect >= 1, "relvalue budget too small for this test to say anything"
    desired = [d(exchange_id=str(i), action="sell", price=0.02, quantity=1000,
                 strategy="relvalue") for i in range(expect * 2 + 5)]
    p = plan_orders(desired, [], rm(budgets=budgets), state())
    assert len(p.places) == expect, (
        f"approved {len(p.places)}, expected {expect}: a tail sell must be "
        f"charged (1-p)*q collateral, not p*q")
    assert p.vetoed


def test_repeated_sells_cannot_walk_past_the_per_market_cap():
    """
    Unsigned accounting let a growing short free its own capacity.

    Priced in the tail, where RelValue actually sells: a short of YES at 0.02
    risks 0.98/share, so a 4,000 short already consumes 3,920 of the 5,000
    per-market cap and only one more 1,000-lot (980) fits.

    This previously used price=0.90, where the OLD `abs(held) * price` formula
    made the cap look binding (4,000 * 0.90 = 3,600) purely by accident. The
    real residual risk of a short at 0.90 is 4,000 * 0.10 = 400, so the test
    was asserting a limit produced by the frame bug rather than by economics.
    """
    s = state(positions={"1": -4000.0})
    desired = [d(exchange_id="1", action="sell", price=0.02, quantity=1000,
                 strategy="relvalue") for _ in range(12)]
    p = plan_orders(desired, [], rm(), s)
    assert len(p.places) <= 2, f"approved {len(p.places)} sells on top of a short"
    assert p.vetoed


def test_short_residual_risk_is_small_when_the_price_is_already_high():
    """
    The mirror of the above: a short at 0.90 genuinely has little left to lose,
    so the cap must NOT bind the way the old formula made it appear to.
    """
    s = state(positions={"1": -4000.0})
    desired = [d(exchange_id="1", action="sell", price=0.90, quantity=1000,
                 strategy="relvalue") for _ in range(12)]
    # Give relvalue room explicitly, so the PER-MARKET cap is the only thing
    # that can bind. Reading the live allocation turned this into a test of the
    # strategy budget the moment that allocation was reweighted.
    risk = rm(budgets=StrategyBudget(settlement=0.0, ladder=0.0, relvalue=0.50,
                                     sleeve=0.0, reserve=0.50))
    p = plan_orders(desired, [], risk, s)
    assert len(p.places) == 12, "correct framing leaves ample room at 0.90"


def test_position_reducing_trade_is_not_blocked_by_the_cap():
    """Charging an exit against the cap would trap us in a position."""
    s = state(positions={"1": 4000.0})
    v = rm().check(s, exchange_id="1", action="sell", price=0.90,
                   quantity=100, strategy="relvalue")
    assert v is None


# ------------------------------------------------------------ hysteresis ----

def test_sub_tick_drift_does_not_churn_the_book():
    """
    The ladder recomputes from a moving mid. Without hysteresis a 1-tick drift
    cancels and replaces every order each cycle, burning rate limit and - worse
    - surrendering queue position, which is the only thing that fills a passive
    order under price-time priority.
    """
    live = [lo(order_id=1, price=0.500, quantity=100)]
    p = plan_orders([d(price=0.505, quantity=100)], live, rm(), state(),
                    managed_order_ids={1})
    assert p.is_noop and len(p.keeps) == 1


def test_large_price_move_still_requotes():
    live = [lo(order_id=1, price=0.500, quantity=100)]
    p = plan_orders([d(price=0.560, quantity=100)], live, rm(), state(),
                    managed_order_ids={1})
    assert len(p.cancels) == 1 and len(p.places) == 1


def test_small_quantity_drift_is_tolerated():
    live = [lo(order_id=1, price=0.500, quantity=100)]
    p = plan_orders([d(price=0.500, quantity=108)], live, rm(), state(),
                    managed_order_ids={1})
    assert p.is_noop


def test_large_quantity_change_requotes():
    live = [lo(order_id=1, price=0.500, quantity=100)]
    p = plan_orders([d(price=0.500, quantity=300)], live, rm(), state(),
                    managed_order_ids={1})
    assert len(p.cancels) == 1 and len(p.places) == 1


def test_tolerance_zero_restores_exact_matching():
    live = [lo(order_id=1, price=0.500, quantity=100)]
    p = plan_orders([d(price=0.505, quantity=100)], live, rm(), state(),
                    managed_order_ids={1}, price_tolerance_ticks=0,
                    qty_tolerance=0.0)
    assert len(p.cancels) == 1 and len(p.places) == 1


def test_two_desires_do_not_both_match_one_live_order():
    live = [lo(order_id=1, price=0.500, quantity=100)]
    p = plan_orders([d(price=0.500, quantity=100), d(price=0.505, quantity=100)],
                    live, rm(), state(), managed_order_ids={1})
    assert len(p.keeps) == 1 and len(p.places) == 1


def test_hysteresis_never_matches_an_unmanaged_order():
    live = [lo(order_id=999, price=0.500, quantity=100)]
    p = plan_orders([d(price=0.502, quantity=100)], live, rm(), state(),
                    managed_order_ids=set())
    assert len(p.places) == 1 and p.cancels == []


# ------------------------------------------- effective-cap transparency ---

def test_env_override_is_read_for_the_deployment_cap(monkeypatch):
    """
    Regression: the live bot ran on the 0.90 default because the 5% cap was
    only ever a shell export. The override must be read from the environment.
    """
    monkeypatch.setenv("SIG_BASE_URL", "https://x")
    monkeypatch.setenv("SIG_RECON_KEY", "r")
    monkeypatch.setenv("SIG_MAX_DEPLOYED_FRACTION", "0.05")
    s = Settings.from_env()
    assert s.limits.max_deployed_fraction == 0.05


def test_deployment_cap_falls_back_to_the_documented_default(monkeypatch):
    """
    Asserted against RiskLimits()'s own default, not a hardcoded number. The
    two used to be separate literals in from_env() and the dataclass field,
    and they had already drifted apart (0.90 here vs 0.99 there) before this
    was caught; a test pinning either one by value is exactly how that
    drift goes unnoticed a second time.
    """
    monkeypatch.setenv("SIG_BASE_URL", "https://x")
    monkeypatch.setenv("SIG_RECON_KEY", "r")
    monkeypatch.delenv("SIG_MAX_DEPLOYED_FRACTION", raising=False)
    assert (Settings.from_env().limits.max_deployed_fraction
            == RiskLimits().max_deployed_fraction)


def test_risk_banner_shows_the_numbers_that_actually_bind():
    s = settings(limits=RiskLimits(max_deployed_fraction=0.05,
                                   max_per_market_fraction=0.01))
    b = s.risk_banner()
    assert "deployed<=5.0%" in b
    assert "per_market<=1.0%" in b


def test_binding_cap_is_the_lower_of_limit_and_budgets():
    tight = settings(limits=RiskLimits(max_deployed_fraction=0.05))
    assert tight.max_deployable_fraction == 0.05        # limit binds

    # Budgets bind when they total less than the limit. Constructed explicitly
    # rather than read from the live allocation, so this keeps testing min()
    # in BOTH directions however the book is reweighted.
    narrow = settings(limits=RiskLimits(max_deployed_fraction=0.90),
                      budgets=StrategyBudget(settlement=0.30, ladder=0.10,
                                             relvalue=0.05, sleeve=0.05,
                                             reserve=0.50))
    assert abs(narrow.max_deployable_fraction - 0.50) < 1e-9

    # The limit binds when the budgets total more than it.
    wide = settings(limits=RiskLimits(max_deployed_fraction=0.60),
                    budgets=StrategyBudget(settlement=0.74, ladder=0.12,
                                           relvalue=0.04, sleeve=0.04,
                                           reserve=0.06))
    assert abs(wide.max_deployable_fraction - 0.60) < 1e-9


def test_deployment_cap_actually_vetoes_at_the_limit():
    risk = RiskManager(settings(
        limits=RiskLimits(max_deployed_fraction=0.05,
                          max_per_market_fraction=0.05)))
    st = state(cost_basis=4_990.0, equity=100_000.0)
    v = risk.check(st, exchange_id="1", action="buy", price=0.5,
                   quantity=100, strategy="ladder")
    assert v is not None and "total deployment cap" in v.reason

def test_no_sell_is_a_yes_buy_and_must_face_the_tail_guard():
    """A no/sell @ 0.97 is economically a YES buy at 0.03, below the floor."""
    risk = RiskManager(settings())
    v = risk.check(state(), exchange_id="1", side="no", action="sell",
                   price=0.97, quantity=100, strategy="ladder")
    assert v is not None and "floor" in v.reason

def test_no_buy_is_a_yes_sell_and_must_not_face_the_buy_guard():
    """
    The mirror: no/buy @ 0.97 == SELL YES @ 0.03. Selling tails is our
    validated edge and must not be vetoed by a buy-side ceiling.
    """
    risk = RiskManager(settings())
    v = risk.check(state(), exchange_id="1", side="no", action="buy",
                   price=0.97, quantity=100, strategy="ladder")
    assert v is None, f"blocked our own edge trade: {v}"

def test_build_races_converts_short_cost_to_yes_frame():
    """A short's avgCost is NO-space; the YES entry is its complement."""
    from sigbot.runner import build_races
    markets = [{"id": "1", "title": "Will the Republican Party win the Georgia Senate race?",
                "exchanges": [{"id": "100"}]}]
    positions = [{"exchangeId": "100", "quantity": -100.0, "avgCost": 0.72}]
    races, _ = build_races(markets, positions)
    leg = list(races.values())[0].legs[0]
    assert leg.avg_cost == pytest.approx(0.28), \
        f"short entry left in NO frame: {leg.avg_cost}"


# ------------------------------------------- batch idempotency durability ---

def test_batch_idempotency_key_is_derived_from_durable_journal_state():
    """
    The venue deduplicates on the batch key. A fresh uuid per call means an
    ambiguous failure retries under a DIFFERENT key and the venue places the
    batch twice. The key must be a deterministic function of the journal keys.
    """
    from sigbot.executor import Executor
    from sigbot.journal import OrderJournal

    seen = []

    class Recorder:
        def __init__(self):
            self.s = settings(dry_run=False, live_trading=True)

        def place_batch(self, orders, idempotency_key=None):
            seen.append(idempotency_key)
            return {"results": [{"index": i, "ok": True,
                                 "data": {"orderId": 900 + i}}
                                for i in range(len(orders))]}

    j = OrderJournal(":memory:")
    places = [d(exchange_id="1"), d(exchange_id="2")]
    Executor(Recorder(), rm(), journal=j).apply(Plan([], places, [], []))

    assert seen and seen[0] is not None, "no idempotency key was sent"
    assert seen[0].startswith("sigbot-batch-")

    # The key is a pure function of the durable journal keys, so replaying the
    # same chunk presents the same key and the venue deduplicates it.
    seen2 = []
    j2 = OrderJournal(":memory:")

    class Recorder2(Recorder):
        def place_batch(self, orders, idempotency_key=None):
            seen2.append(idempotency_key)
            return {"results": []}

    Executor(Recorder2(), rm(), journal=j2).apply(Plan([], places, [], []))
    assert seen2[0] != seen[0], "distinct journal keys must give distinct batches"


def test_distinct_batches_get_distinct_keys():
    """Two different batches must not collide onto one key."""
    seen = []

    class Recorder:
        def __init__(self):
            self.s = settings(dry_run=False, live_trading=True)

        def place_batch(self, orders, idempotency_key=None):
            seen.append(idempotency_key)
            return {"results": [{"index": i, "ok": True,
                                 "data": {"orderId": 900 + i}}
                                for i in range(len(orders))]}

    from sigbot.executor import Executor
    from sigbot.journal import OrderJournal
    # >1 place so the batch path is taken rather than single placement.
    for ex in ("1", "2"):
        Executor(Recorder(), rm(), journal=OrderJournal(":memory:")).apply(
            Plan([], [d(exchange_id=ex), d(exchange_id=ex + "0")], [], []))
    assert len(set(seen)) == 2


# ------------------------------------------- kill switch at the boundary ---

def test_kill_switch_suppresses_placements_at_execution_time():
    """
    A Plan is data. It can be built before the switch trips and applied after,
    and planning-time vetoes never run again on that path.
    """
    from sigbot.executor import Executor
    calls = []

    class Venue:
        def __init__(self):
            self.s = settings(dry_run=False, live_trading=True)

        def place_batch(self, orders, idempotency_key=None):
            calls.append(("place", len(orders)))
            return {"results": []}

        def place_order(self, *a, **k):
            calls.append(("place", 1))
            return {"orderId": 1}

        def cancel_order(self, oid):
            calls.append(("cancel", oid))

    r = rm()
    plan = Plan([], [d(exchange_id="1"), d(exchange_id="2")], [], [])
    r.update(state(equity=50_000.0, peak_equity=100_000.0))   # 50% drawdown
    assert r.tripped
    out = Executor(Venue(), r).apply(plan)
    assert not [c for c in calls if c[0] == "place"], "placed while tripped"
    assert out["placed"] == 0
    assert "kill switch" in " ".join(out["errors"])


def test_kill_switch_still_allows_cancellations():
    """Getting flat is exactly what a tripped switch wants."""
    from sigbot.executor import Executor
    calls = []

    class Venue:
        def __init__(self):
            self.s = settings(dry_run=False, live_trading=True)

        def cancel_order(self, oid):
            calls.append(oid)

    r = rm()
    r.update(state(equity=50_000.0, peak_equity=100_000.0))
    live = [LiveOrder.from_api({"id": 7, "exchangeId": "1", "side": "yes",
                                "action": "buy", "quantity": 10,
                                "priceLimit": 0.3})]
    Executor(Venue(), r).apply(Plan(live, [], [], []))
    assert calls == [7]


# ------------------------------ tail guards apply only to opening exposure ---

def test_winning_tail_short_can_be_bought_back():
    """
    Our validated edge is selling overpriced tails. When the price then falls
    below 0.15 the trade has WORKED; buying it back realises the profit and
    releases the collateral. The guard that stops us OPENING tail longs must
    not stop us CLOSING a tail short.
    """
    risk = RiskManager(settings())
    st = state(positions={"1": -100.0})
    assert risk.check(st, exchange_id="1", action="buy", price=0.07,
                      quantity=100, strategy="exit") is None


def test_opening_a_tail_long_is_still_blocked():
    risk = RiskManager(settings())
    v = risk.check(state(), exchange_id="1", action="buy", price=0.07,
                   quantity=100, strategy="ladder")
    assert v is not None and "floor" in v.reason


def test_closing_more_than_held_still_guards_the_opening_residual():
    """Buying 150 against a 100 short closes 100 and OPENS 50 in the tail."""
    risk = RiskManager(settings())
    st = state(positions={"1": -100.0})
    v = risk.check(st, exchange_id="1", action="buy", price=0.07,
                   quantity=150, strategy="exit")
    assert v is not None and "floor" in v.reason


def test_ladder_outranks_relvalue_under_the_order_cap():
    """
    Ladder measures the best EV per order-hour, so truncation must fall on
    relvalue first. An ascending sort over {"ladder": 3, "relvalue": 2} put
    ladder last and truncated the best strategy instead.
    """
    from sigbot.runner import _truncate_by_priority
    desired = ([d(exchange_id=str(i), strategy="relvalue") for i in range(10)]
               + [d(exchange_id=str(100 + i), strategy="ladder")
                  for i in range(10)])
    kept = _truncate_by_priority(desired, [], set(), 10)
    assert all(o.strategy == "ladder" for o in kept)


def test_exit_outranks_everything():
    from sigbot.runner import _truncate_by_priority
    desired = ([d(exchange_id=str(i), strategy="ladder") for i in range(10)]
               + [d(exchange_id="999", strategy="exit")])
    kept = _truncate_by_priority(desired, [], set(), 1)
    assert [o.strategy for o in kept] == ["exit"]


def test_deployment_cap_matches_the_configuration_it_must_fund():
    """
    The cap is sized to the book the strategies can actually produce, not
    picked round:

        full resting book  240 orders x ~73 collateral = 17.4%
                           (240 = 80 markets x 3 rungs = the edge ceiling)
        peak inventory observed                          7.1%
        total                                           24.5%

    Beyond that the order cap binds first, so extra capital buys no extra
    orders -- markets past rank 80 measured +0.00067/share with P(>0)=0.673
    and our own fills there lost money.
    """
    s = settings(limits=RiskLimits(max_deployed_fraction=0.25))
    assert s.max_deployable_fraction == 0.25
    orders, collat_each, peak_inventory = 240, 73, 0.071
    book = orders * collat_each / 100_000
    assert book + peak_inventory <= 0.25 + 1e-9, "cap cannot fund its own book"
    assert book + peak_inventory > 0.20, "20% was genuinely too small"


# ---------------------------- orders the mid has crossed must be cancelled ---

def test_hysteresis_does_not_protect_an_order_the_mid_crossed():
    """
    A buy resting at 0.48 is passive against a 0.50 mid and AGGRESSIVE against
    a 0.47 one. Hysteresis exists to leave near-matching orders alone, so it
    was preserving exactly the orders that had turned toxic: 14.7% of fills,
    earning -0.00276/share against +0.00368 passive.
    """
    live = [LiveOrder.from_api({"id": 7, "exchangeId": "1", "side": "yes",
                                "action": "buy", "quantity": 100,
                                "priceLimit": 0.48})]
    want = [d(exchange_id="1", action="buy", price=0.48, quantity=100)]
    kept = plan_orders(want, live, rm(), state())
    assert [o.order_id for o in kept.keeps] == [7], "precondition: normally kept"
    forced = plan_orders(want, live, rm(), state(), force_cancel_ids={7})
    assert forced.keeps == []
    assert [o.order_id for o in forced.cancels] == [7]


def test_crossed_orders_detects_only_aggressive_resting_orders():
    from sigbot.runner import crossed_orders
    from sigbot.strategies.base import Quote
    quotes = {"1": Quote("1", 0.46, 0.48)}        # mid 0.47
    live = [
        LiveOrder.from_api({"id": 1, "exchangeId": "1", "side": "yes",
                            "action": "buy", "quantity": 10, "priceLimit": 0.48}),
        LiveOrder.from_api({"id": 2, "exchangeId": "1", "side": "yes",
                            "action": "buy", "quantity": 10, "priceLimit": 0.44}),
        LiveOrder.from_api({"id": 3, "exchangeId": "1", "side": "yes",
                            "action": "sell", "quantity": 10, "priceLimit": 0.46}),
    ]
    got = crossed_orders(live, quotes)
    assert 1 in got, "buy above mid is aggressive"
    assert 2 not in got, "buy below mid is still passive"
    assert 3 in got, "sell below mid is aggressive"


def test_crossed_orders_handles_a_no_side_order_in_the_right_frame():
    """no/buy at 0.77 is economically a YES sell at 0.23."""
    from sigbot.runner import crossed_orders
    from sigbot.strategies.base import Quote
    quotes = {"1": Quote("1", 0.20, 0.22)}        # mid 0.21
    live = [LiveOrder.from_api({"id": 9, "exchangeId": "1", "side": "no",
                                "action": "buy", "quantity": 10,
                                "priceLimit": 0.77})]
    # YES sell at 0.23 against a 0.21 mid is still passive
    assert crossed_orders(live, quotes) == set()


def test_crossed_orders_ignores_markets_without_a_mid():
    from sigbot.runner import crossed_orders
    from sigbot.strategies.base import Quote
    live = [LiveOrder.from_api({"id": 1, "exchangeId": "1", "side": "yes",
                                "action": "buy", "quantity": 10,
                                "priceLimit": 0.48})]
    assert crossed_orders(live, {"1": Quote("1", None, 0.48)}) == set()
    assert crossed_orders(live, {}) == set()
