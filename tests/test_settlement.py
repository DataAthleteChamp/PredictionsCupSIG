"""
Tests for the held-to-settlement convergence book.

The things that can go wrong here are not subtle, and several of them have
already gone wrong once in this codebase:

  * quoting the wrong side of the book (seven YES/NO frame bugs to date)
  * sizing to the target instead of the shortfall, so every cycle re-requests
    a position already held
  * a kill switch that liquidates the trade on a mark it was told to ignore
  * an exemption that survives the thesis it was granted for
"""
from __future__ import annotations

import pytest

from sigbot.config import RiskLimits, Settings, StrategyBudget
from sigbot.risk import PortfolioState, RiskManager
from sigbot.strategies.base import MarketView, Quote
from sigbot.strategies.settlement import SettlementConfig, SettlementStrategy


def q(ex="1", bid=0.145, ask=0.150):
    return Quote(ex, bid, ask)


def view(quotes=None, fair=None, positions=None, equity=100_000.0,
         targeted=None):
    # `is None` rather than `or`: an explicitly empty dict is a meaningful
    # input here (no anchor available) and must not fall back to the default.
    return MarketView(
        quotes={"1": q()} if quotes is None else quotes,
        fair={"1": 0.007} if fair is None else fair,
        positions={} if positions is None else positions, equity=equity,
        targeted_minutes={} if targeted is None else targeted)


def settings(**kw):
    base = dict(base_url="https://x", recon_key="r", exec_key="e")
    base.update(kw)
    return Settings(**base)


# ------------------------------------------------------------- selection ----

def test_ranks_by_return_on_collateral_not_raw_edge():
    """
    A 0.205 contract against 0.095 has a bigger raw gap (0.110) than a 0.150
    contract against 0.007 (0.143 -- wait, smaller). Use a case where raw edge
    and return-on-collateral genuinely disagree: 0.30 vs 0.18 has raw edge 0.12
    and ROC 0.171; 0.10 vs 0.02 has raw edge 0.08 and ROC 0.089. Raw edge
    prefers the first and so does ROC, so construct the real inversion:
    0.50->0.38 (edge 0.12, ROC 0.24) against 0.10->0.005 (edge 0.095, ROC
    0.106). Collateral is the scarce resource, so ROC must decide.
    """
    s = SettlementStrategy(SettlementConfig(max_sell_price=0.60))
    v = view(quotes={"big_edge": q("big_edge", 0.495, 0.50),
                     "small_edge": q("small_edge", 0.095, 0.10)},
             fair={"big_edge": 0.38, "small_edge": 0.005})
    ranked = [ex for ex, _px, _roc in s.candidates(v)]
    assert ranked[0] == "big_edge"
    rocs = {ex: roc for ex, _px, roc in s.candidates(v)}
    assert rocs["big_edge"] == pytest.approx(0.12 / 0.50, rel=1e-6)
    assert rocs["small_edge"] == pytest.approx(0.095 / 0.90, rel=1e-6)


def test_ignores_activity_entirely():
    """
    The bug this strategy exists to fix: RelValue walks by_activity() and stops
    at 60, but the convergence edge lives in the ILLIQUID tails. A market with
    zero activity and a huge edge must still be selected.
    """
    s = SettlementStrategy()
    v = MarketView(quotes={"dead": q("dead"), "busy": q("busy", 0.145, 0.15)},
                   fair={"dead": 0.007, "busy": 0.140},
                   positions={}, equity=100_000.0,
                   activity={"busy": 999.0, "dead": 0.0})
    ranked = [ex for ex, _px, _roc in s.candidates(v)]
    assert ranked == ["dead"], "illiquid high-edge market must rank first"


def test_skips_markets_without_an_anchor():
    s = SettlementStrategy()
    assert s.candidates(view(fair={})) == []


def test_requires_min_edge_at_the_price_we_would_trade():
    """Edge is evaluated at the offer, not at an unreachable mid."""
    s = SettlementStrategy(SettlementConfig(min_edge=0.02))
    assert s.candidates(view(fair={"1": 0.135})) == []      # 0.150-0.135 < 0.02
    assert len(s.candidates(view(fair={"1": 0.125}))) == 1   # 0.025 >= 0.02


def test_does_not_sell_outside_the_tail_band():
    s = SettlementStrategy(SettlementConfig(max_sell_price=0.35))
    v = view(quotes={"1": q("1", 0.60, 0.605)}, fair={"1": 0.40})
    assert s.candidates(v) == [], "0.605 is not a longshot"


# ------------------------------------------------------------- the orders ---

def test_sells_yes_and_never_buys_the_tail():
    """
    Frame correctness. Shorting an overpriced YES tail is a SELL of YES. Seven
    separate frame bugs in this codebase have inverted exactly this.
    """
    s = SettlementStrategy()
    out = s.desired(view())
    assert len(out) == 1
    o = out[0]
    assert (o.side, o.action) == ("yes", "sell")
    assert o.price == pytest.approx(0.150)
    assert o.strategy == "settlement"


def test_sizes_to_shortfall_not_to_target():
    """
    Sizing to the target would re-request the whole position every cycle, and
    the executor would place a second order on top of a filled one.
    """
    s = SettlementStrategy(SettlementConfig(per_market_fraction=0.05,
                                            max_shares_per_order=50_000))
    # target collateral 5,000 at 0.85/share -> 5,882 shares
    full = s.desired(view())[0].quantity
    assert full == pytest.approx(int(5_000 / 0.85), abs=2)
    half = s.desired(view(positions={"1": -3_000.0}))[0].quantity
    assert half == pytest.approx(full - 3_000, abs=2)


def test_emits_nothing_once_the_target_is_held():
    s = SettlementStrategy()
    assert s.desired(view(positions={"1": -100_000.0})) == []


def test_respects_the_book_budget_across_markets():
    s = SettlementStrategy(SettlementConfig(
        per_market_fraction=0.05, max_book_fraction=0.10))
    quotes = {str(i): q(str(i)) for i in range(10)}
    fair = {str(i): 0.007 for i in range(10)}
    out = s.desired(view(quotes=quotes, fair=fair))
    committed = sum(o.quantity * (1 - o.price) for o in out)
    assert committed <= 0.10 * 100_000.0 + 1.0


def test_caps_shares_per_order():
    s = SettlementStrategy(SettlementConfig(max_shares_per_order=500))
    assert s.desired(view())[0].quantity == 500


# ------------------------------------------------------------- the hybrid ---

def test_rests_passive_before_the_cross_window():
    s = SettlementStrategy(SettlementConfig(cross_after_minutes=12.0))
    o = s.desired(view(targeted={"1": 5.0}))[0]
    assert o.price == pytest.approx(0.150), "should still be at the offer"


def test_crosses_the_bid_after_waiting():
    s = SettlementStrategy(SettlementConfig(cross_after_minutes=12.0))
    o = s.desired(view(targeted={"1": 30.0}))[0]
    assert o.price == pytest.approx(0.145), "should take the bid"


def test_refuses_to_cross_when_the_bid_no_longer_clears_the_edge():
    """
    We cross to buy certainty, never to chase. A bid that has fallen to the
    anchor is not worth lifting.
    """
    s = SettlementStrategy(SettlementConfig(cross_after_minutes=12.0,
                                            min_edge=0.02))
    v = view(quotes={"1": q("1", bid=0.020, ask=0.150)}, fair={"1": 0.007},
             targeted={"1": 30.0})
    o = s.desired(v)[0]
    assert o.price == pytest.approx(0.150), "bid edge 0.013 < 0.02, stay passive"


# --------------------------------------------------------------- the holds --

def test_holds_only_shorts_the_anchor_still_supports():
    s = SettlementStrategy()
    v = view(quotes={"good": q("good", 0.145, 0.155),
                     "gone": q("gone", 0.145, 0.155),
                     "long": q("long", 0.145, 0.155)},
             fair={"good": 0.007, "gone": 0.148, "long": 0.007},
             positions={"good": -1_000.0, "gone": -1_000.0, "long": +1_000.0})
    assert s.holds(v) == {"good"}


def test_hold_lapses_when_the_anchor_moves_to_meet_the_price():
    """
    The exemption is conditional on the thesis, not on how we got in. Once the
    anchor agrees with the venue there is no convergence left to wait for, and
    the position must be marked like anything else.
    """
    s = SettlementStrategy()
    base = dict(quotes={"1": q("1", 0.145, 0.155)}, positions={"1": -1_000.0},
                equity=100_000.0)
    assert s.holds(MarketView(fair={"1": 0.007}, **base)) == {"1"}
    assert s.holds(MarketView(fair={"1": 0.145}, **base)) == set()


# ----------------------------------------------------------- kill switch ----

def pstate(**kw):
    base = dict(balance=50_000.0, equity=80_000.0, cost_basis=30_000.0,
                peak_equity=100_000.0, peak_adjusted_equity=100_000.0,
                positions={}, deployed_by_strategy={})
    base.update(kw)
    return PortfolioState(**base)


def test_settlement_marks_do_not_trip_the_kill_switch():
    """
    A 20% mark loss concentrated entirely in the settlement book must NOT halt
    trading. The venue's tail marks moved ~15% in an hour on 2026-10-06 without
    any news; halting on that would liquidate the trade at the worst moment,
    which is the limits-to-arbitrage failure this exemption exists to prevent.
    """
    risk = RiskManager(settings())
    risk.update(pstate(settlement_unrealised=-20_000.0))
    assert risk.tripped is None
    assert pstate(settlement_unrealised=-20_000.0).drawdown == pytest.approx(0.20)


def test_losses_outside_the_settlement_book_still_trip_it():
    risk = RiskManager(settings())
    risk.update(pstate(settlement_unrealised=0.0))
    assert risk.tripped is not None, "ordinary 20% drawdown must still halt"


def test_mixed_losses_count_only_the_unexempt_part():
    """Half the loss is exempt, so the halt must not fire at 20% total."""
    risk = RiskManager(settings())
    risk.update(pstate(equity=80_000.0, settlement_unrealised=-10_000.0))
    assert risk.tripped is None
    deeper = RiskManager(settings())
    deeper.update(pstate(equity=60_000.0, settlement_unrealised=-10_000.0))
    assert deeper.tripped is not None, "30% loss, 10% exempt -> 20% counts"


def test_adjusted_equity_values_holds_at_cost():
    st = pstate(equity=80_000.0, settlement_unrealised=-15_000.0)
    assert st.adjusted_equity == pytest.approx(95_000.0)
    assert st.adjusted_drawdown == pytest.approx(0.05)


def test_exemption_cannot_unlatch_a_tripped_switch():
    risk = RiskManager(settings())
    risk.update(pstate(settlement_unrealised=0.0))
    assert risk.tripped is not None
    risk.update(pstate(equity=100_000.0, settlement_unrealised=-50_000.0))
    assert risk.tripped is not None, "kill switch must never un-latch"


# ------------------------------------------------------------- the budget ---

def test_settlement_has_a_budget_or_every_order_is_vetoed():
    """
    strategy_budget() returns 0.0 for unknown tags, so a strategy that is wired
    into the runner but not into the budget map silently places nothing.
    """
    risk = RiskManager(settings())
    assert risk.strategy_budget("settlement") > 0.0


def test_already_deployed_capital_counts_against_the_budget():
    """
    A per-strategy budget that starts empty every cycle is not a budget: it can
    be re-spent in full, forever. The settlement book reached 89.4% of equity
    against a configured 74% allocation before this was caught, and only the
    global deployment cap stopped it.

    Seeded with the budget already consumed, the next order must be refused.
    """
    from sigbot.executor import DesiredOrder, plan_orders
    s = settings()
    budget = s.budgets.settlement * 100_000.0
    spent = PortfolioState(
        balance=10_000.0, equity=100_000.0, cost_basis=budget,
        peak_equity=100_000.0, peak_adjusted_equity=100_000.0, positions={},
        deployed_by_strategy={"settlement": budget})
    p = plan_orders([DesiredOrder("1", "yes", "sell", 0.15, 100, "settlement")],
                    [], RiskManager(s), spent)
    assert not p.places, "budget already spent, yet another order was approved"
    assert "settlement budget" in p.vetoed[0][1]


def test_budgets_still_sum_to_one_with_settlement():
    StrategyBudget().validate()


def test_hold_budget_covers_the_settlement_budget():
    """
    ExitStrategy may only refrain from recycling what the hold budget covers.
    If the settlement book is larger than that budget, the excess is handed
    straight back to the exit strategy for a sub-tick profit.
    """
    from sigbot.config import SETTLEMENT_HOLD_BUDGET
    assert SETTLEMENT_HOLD_BUDGET >= StrategyBudget().settlement


def test_deployment_cap_allows_the_settlement_book():
    s = settings(limits=RiskLimits(max_deployed_fraction=0.95))
    assert s.max_deployable_fraction >= StrategyBudget().settlement
