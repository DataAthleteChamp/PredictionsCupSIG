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
    # Lift the GLOBAL cap so only the per-strategy budget can bind; otherwise
    # the order is refused for the right reason by the wrong rule, and this
    # stops testing what it claims to.
    s = settings(limits=RiskLimits(max_deployed_fraction=1.0))
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


def test_global_cap_has_real_margin_above_the_budget_sum():
    """
    The global deployment cap is the ONLY check that spans strategies; the
    per-strategy checks cannot protect ladder/relvalue from settlement any
    more than settlement's own budget can.

    Measured 2026-10-19: with the cap set exactly equal to the budget sum
    (0.97 == 0.97), settlement's cost basis crept to 96.67% of equity within
    24 hours -- a short's collateral GROWS as price converges toward the
    anchor, so the budget sum is a floor on real usage, not a ceiling. That
    left under 0.5% of headroom shared across every other strategy, and
    ladder/relvalue had 133 of 142 orders vetoed by the GLOBAL cap in a single
    cycle, not their own limits. Managed order count fell from 29 to 1 before
    this was caught.

    The margin asserted here (2 points) is the minimum that let the book
    recover in practice; it is not a formal bound on how far settlement's
    collateral can drift.
    """
    b = StrategyBudget()
    budget_sum = b.settlement + b.ladder + b.relvalue + b.sleeve
    default_cap = RiskLimits().max_deployed_fraction
    assert default_cap - budget_sum >= 0.02, (
        f"cap {default_cap} leaves only {default_cap - budget_sum:.3f} above "
        f"the {budget_sum} budget sum -- settlement's organic growth alone "
        f"measured 2.67 points in 24 hours")


def test_relvalue_and_sleeve_are_retired_from_the_live_budget():
    """
    Pins the 2026-10-21 simplification. Measured over the preceding 7 days,
    relvalue placed 4,387 orders for 255 fills (5.8%) and net -28.68 on its
    0.5% allocation -- a weaker, uncapitalised shadow of the same signal
    settlement already runs at far larger scale and a 12%+ realised return.
    Sleeve had placed zero orders in 19 days by design (see its own
    docstring). Both strategy FILES and their unit tests stay (the research
    is real), but neither is called from runner.py's live loop any more, and
    neither should be budgeted: a budget with no caller is capital doing
    nothing. If either field goes positive again, it must be because the
    strategy was re-added to the loop, not a stray rebalance.
    """
    b = StrategyBudget()
    assert b.relvalue == 0.0
    assert b.sleeve == 0.0


def test_settlement_budget_has_not_crept_past_its_proven_safe_ceiling():
    """
    Pins a same-day regression. Raising settlement from 94% to 95% (to
    reabsorb relvalue+sleeve's freed point) kept the nominal budget-SUM vs
    cap margin at 2 points either way -- the only invariant the OTHER margin
    test checks -- yet caused a real recurrence of the 2026-10-19 starvation.

    Measured: under 94%, deployed% never once exceeded 97.2% across 306
    cycles / 30 hours, and no cycle crowded ladder below managed=10 (bar one
    cold-start cycle). Under 95%, 79 of the next 218 cycles hit >=97.5%,
    peaking at 97.9%, and ladder's managed order count collapsed to 4-5 for a
    continuous 6.5-hour, 42-cycle window. The nominal sum-vs-cap margin was
    identical in both configurations; settlement's OWN ceiling is what
    actually bounds how far its organic growth pushes total deployed, because
    that growth happens through top-ups the per-strategy check does not stop
    until settlement's own number is reached.

    94% is the highest value measured safe in practice. Raising it again
    requires re-running this exact before/after deployed%-distribution and
    managed-order-count check against live data, not just re-checking that
    the sum still adds up.
    """
    assert StrategyBudget().settlement <= 0.94


# -------------------------------------------------- degraded anchor feed ----

def lot(ex, qty, cost=0.85, age=120.0):
    from sigbot.strategies.base import Lot
    return Lot(exchange_id=ex, quantity=qty, avg_cost=cost, age_minutes=age)


def test_missing_anchor_protects_a_held_position():
    """
    A missing anchor is absence of evidence, not evidence of no edge, and
    settlement_edge() returns 0.0 for both. Measured 2026-10-08: one cycle
    fetched 117 of 228 anchors and ExitStrategy immediately went from 2 orders
    to 12, targeting settlement shorts whose fair value had merely vanished.
    """
    v = MarketView(quotes={"a": q("a"), "b": q("b")},
                   fair={"a": 0.007},            # "b" has no anchor
                   positions={"a": -1_000.0, "b": -1_000.0}, equity=100_000.0,
                   lots={"a": lot("a", -1_000.0), "b": lot("b", -1_000.0)})
    assert "b" in v.protected(0.02, 0.92), "unknown edge must mean do-not-touch"


def test_unanchored_by_design_does_not_protect_everything():
    """
    With no anchor at all we are running --no-polymarket on purpose, and
    protecting every position would freeze the exit strategy permanently.
    """
    v = MarketView(quotes={"a": q("a")}, fair={}, positions={"a": -1_000.0},
                   equity=100_000.0, lots={"a": lot("a", -1_000.0)})
    assert v.protected(0.02, 0.92) == set()


def test_unknown_anchors_do_not_consume_the_hold_budget():
    """
    The budget bounds capital we deliberately commit to holds. Refusing to act
    on absent data is not a commitment, and charging it would let an outage
    evict genuinely high-edge positions.
    """
    v = MarketView(quotes={"known": q("known", 0.145, 0.155),
                           "gap": q("gap", 0.145, 0.155)},
                   fair={"known": 0.007},
                   positions={"known": -1_000.0, "gap": -50_000.0},
                   equity=100_000.0,
                   lots={"known": lot("known", -1_000.0),
                         "gap": lot("gap", -50_000.0)})
    out = v.protected(0.02, 0.10)
    assert out == {"known", "gap"}, "a huge unknown must not evict the known hold"


def test_anchor_coverage_is_a_fraction_of_quoted_markets():
    v = MarketView(quotes={str(i): q(str(i)) for i in range(10)},
                   fair={"0": 0.01, "1": 0.02}, positions={}, equity=100_000.0)
    assert v.anchor_coverage() == pytest.approx(0.2)
    assert MarketView(quotes={}, fair={}, positions={},
                      equity=1.0).anchor_coverage() == 0.0


def test_coverage_threshold_separates_jitter_from_failure():
    """
    Coverage is bimodal: 171 of 172 cycles returned 228/228, one returned 117.
    The threshold must pass normal jitter and catch the real failure.
    """
    from sigbot.config import MIN_ANCHOR_COVERAGE
    assert 226 / 228 >= MIN_ANCHOR_COVERAGE, "99% coverage is healthy jitter"
    assert 117 / 228 < MIN_ANCHOR_COVERAGE, "51% coverage is a failed fetch"


# ------------------------------------------- ladder price band (capital) ----

def test_ladder_band_excludes_the_capital_inefficient_top():
    """
    The ladder's upper bound is a CAPITAL decision, not a markout one.

    Measured on 2,063 live fills, markout per share is nearly flat from 0.20 to
    1.00 (+0.00251 down to +0.00111) while return on capital falls 7x (+0.88%
    to +0.13%), because the same edge costs three times as much cash at 0.775
    as at 0.265. Every tool we had scored by markout per share and was
    therefore blind to this.
    """
    from sigbot.strategies.ladder import LadderConfig
    c = LadderConfig()
    assert c.max_mid <= 0.50, "0.50-0.85 returns a third of 0.20-0.50 on capital"
    assert c.min_mid >= 0.20


def test_ladder_still_refuses_the_cheap_tail():
    """
    research/band_experiment.py scored the 0.00-0.05 band at +48% return on
    capital per fill. Our own live fills below 0.10 returned -4.36%. The
    simulator has no queue position and over-counts fills where books are
    thinnest, so the floor stays.
    """
    from sigbot.strategies.ladder import LadderConfig
    assert LadderConfig().floor_price >= 0.15


# ------------------------------------------------------ the trading close ---

def test_hours_to_close_is_signed():
    from datetime import datetime, timezone
    from sigbot.runner import hours_to_close
    assert hours_to_close(datetime(2026, 11, 4, 14, 0, tzinfo=timezone.utc)) \
        == pytest.approx(3.0)
    assert hours_to_close(datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc)) \
        == pytest.approx(-1.0)
    assert hours_to_close(datetime(2026, 10, 9, 17, 0, tzinfo=timezone.utc)) > 600


def test_grind_window_closes_before_settlement_does():
    """
    The grind must stop opening with enough time to round-trip what it already
    holds; the settlement book must not, because selling an overpriced tail an
    hour before resolution is the best version of that trade.
    """
    from sigbot.config import GRIND_STOP_HOURS_BEFORE_CLOSE
    assert GRIND_STOP_HOURS_BEFORE_CLOSE > 0
    # Comfortably longer than the exit strategy's decay horizon, or inventory
    # opened just before the cutoff still cannot be scratched out in time.
    from sigbot.strategies.exit import ExitConfig
    assert GRIND_STOP_HOURS_BEFORE_CLOSE * 60 > ExitConfig().decay_minutes * 3


# ---------------------------------------------------------- rotation --------

def _rot_view(held_roc_markets, candidate_mids):
    """Build a view with held shorts and unheld candidates at given edges."""
    quotes, fair, positions = {}, {}, {}
    for ex, (mid, f) in held_roc_markets.items():
        quotes[ex] = Quote(ex, mid - 0.005, mid + 0.005)
        fair[ex] = f
        positions[ex] = -2_000.0
    for ex, (mid, f) in candidate_mids.items():
        quotes[ex] = Quote(ex, mid - 0.005, mid + 0.005)
        fair[ex] = f
    return MarketView(quotes=quotes, fair=fair, positions=positions,
                      equity=100_000.0)


def test_rotation_closes_a_badly_outclassed_holding():
    """
    Measured 2026-10-13: 11 of 32 holdings carried 2.6-5.4% return on
    collateral while unheld markets offered 5.9-9.5%. `desired` only ever adds,
    and with the deployment cap binding there was never room to add anything
    better, so the book stayed frozen in whatever it bought first.
    """
    s = SettlementStrategy()
    v = _rot_view({"weak": (0.20, 0.185)},                 # ROC ~1.9%
                  {f"c{i}": (0.10, 0.01) for i in range(12)})   # ROC ~10%
    rot = s.rotations(v)
    assert [o.exchange_id for o in rot] == ["weak"]
    o = rot[0]
    assert (o.side, o.action) == ("yes", "buy"), "closing a short BUYS yes back"
    assert o.strategy == "settlement"


def test_rotation_leaves_a_merely_slightly_worse_holding_alone():
    """Round-tripping costs ~1 tick each way; a small gap is pure cost."""
    s = SettlementStrategy()
    v = _rot_view({"ok": (0.10, 0.028)},                   # ROC ~8%
                  {f"c{i}": (0.10, 0.012) for i in range(12)})  # ROC ~9.8%
    assert s.rotations(v) == []


def test_rotation_is_bounded_per_cycle():
    s = SettlementStrategy()
    weak = {f"w{i}": (0.20, 0.19) for i in range(8)}
    v = _rot_view(weak, {f"c{i}": (0.10, 0.005) for i in range(12)})
    assert len(s.rotations(v)) <= SettlementConfig().rotate_max_markets


def test_rotation_never_buys_and_sells_the_same_market():
    """
    A market that is both a rotation target and a top candidate would otherwise
    get a closing BUY and an opening SELL in the same cycle, which crosses our
    own book and pays the spread to stand still.
    """
    s = SettlementStrategy()
    v = _rot_view({"x": (0.20, 0.19)},
                  {f"c{i}": (0.10, 0.005) for i in range(12)})
    orders = s.desired(v)
    by_market = {}
    for o in orders:
        by_market.setdefault(o.exchange_id, set()).add(o.action)
    for ex, actions in by_market.items():
        assert actions != {"buy", "sell"}, f"{ex} quoted both ways"


def test_rotation_ignores_longs():
    s = SettlementStrategy()
    v = _rot_view({}, {f"c{i}": (0.10, 0.005) for i in range(12)})
    v = MarketView(quotes=v.quotes, fair=v.fair, positions={"c0": +5_000.0},
                   equity=100_000.0)
    assert all(o.action != "buy" for o in s.rotations(v))


def test_per_market_cap_leaves_room_for_the_risk_limit():
    """
    The strategy's own per-market size must sit UNDER the risk manager's
    DEFAULT cap, not merely under whatever .env happens to set. Reading the
    environment here made this test pass only when run with .env sourced, and
    hid the fact that the shipped default (0.05) was below the size the
    strategy asks for (0.08) -- so without the override every top-up was
    vetoed and the book silently stopped concentrating.
    """
    from sigbot.config import RiskLimits
    assert SettlementConfig().per_market_fraction < RiskLimits().max_per_market_fraction


def test_rotate_rank_reflects_how_fast_candidates_decay():
    """
    Measured 2026-10-13: #1=11.3%, #2=7.4%, #3=7.0%, #8=5.5% return on
    collateral. Judging a holding against the eighth-best compares it to a
    target barely better than itself, and rotation then correctly finds
    nothing to do.
    """
    assert SettlementConfig().rotate_rank <= 4


def test_hold_survives_a_position_drifting_above_the_opening_band():
    """
    `max_sell_price` is an OPENING rule -- where the measured favourite
    -longshot bias lives. Whether to KEEP a position is a different question,
    and answering it with the opening rule punishes exactly the positions that
    have moved against us.

    Measured 2026-10-14: four shorts drifted to 0.362-0.438 while still
    carrying +0.023 to +0.073 of edge, and all four silently lost both the
    kill-switch exemption and protection from ExitStrategy -- the trade was
    going against us, so we made it eligible to be closed at a loss.
    """
    s = SettlementStrategy()
    drifted = MarketView(quotes={"1": Quote("1", 0.430, 0.440)},
                         fair={"1": 0.365}, positions={"1": -1_000.0},
                         equity=100_000.0)
    assert drifted.quotes["1"].mid > SettlementConfig().max_sell_price
    assert s.holds(drifted) == {"1"}, "edge is +0.07; it must stay held"


def test_opening_still_respects_the_tail_band():
    """Keeping is not the same as opening: we still refuse to START there."""
    s = SettlementStrategy()
    v = MarketView(quotes={"1": Quote("1", 0.430, 0.440)}, fair={"1": 0.365},
                   positions={}, equity=100_000.0)
    assert s.candidates(v) == []


# ---------------------------------------------- total anchor fetch failure --

def test_total_fetch_failure_is_degraded_not_unanchored():
    """
    The bug, reproduced directly. `bool(fair)` was the old gate, and it cannot
    tell a TOTAL fetch failure (attempted, got nothing) apart from a
    deliberate --no-polymarket run (never attempted) -- both leave fair == {}.

    Measured 2026-10-16T16:49: one cycle returned 0 of 228 anchors. Under the
    old gate this was judged NOT degraded, so the skip-cycle guard never fired
    and ExitStrategy treated the whole settlement book as ordinary decaying
    inventory, placing 39 buy-back orders including nine of 9,000+ shares.
    2,150 of a 2,216-share short filled before the next cycle recovered.
    """
    from sigbot.runner import is_degraded_fetch
    assert is_degraded_fetch(True, 0.0) is True, \
        "a fetch that was attempted and returned nothing must be degraded"


def test_partial_fetch_failure_is_still_degraded():
    from sigbot.runner import is_degraded_fetch
    assert is_degraded_fetch(True, 117 / 228) is True


def test_healthy_fetch_is_not_degraded():
    from sigbot.runner import is_degraded_fetch
    assert is_degraded_fetch(True, 1.0) is False
    assert is_degraded_fetch(True, 226 / 228) is False


def test_deliberately_unanchored_run_is_never_degraded():
    """
    --no-polymarket sets use_polymarket=False and fair stays {} for the whole
    run by design. This must never trigger the skip-cycle guard, or the bot
    would skip every single cycle forever.
    """
    from sigbot.runner import is_degraded_fetch
    assert is_degraded_fetch(False, 0.0) is False
