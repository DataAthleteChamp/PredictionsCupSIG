"""
Tests for inventory exit and for risk's handling of position-reducing trades.

The strategy exists because of a measurement: the per-fill edge is worth about
one tick and is gone by 240 minutes. These tests pin the behaviour that
measurement implies.
"""
import pytest

from sigbot.config import Settings
from sigbot.risk import PortfolioState, RiskManager, collateral
from sigbot.strategies.base import Lot, MarketView, Quote
from sigbot.strategies.exit import ExitConfig, ExitStrategy


def _s(**kw):
    base = dict(base_url="https://x", recon_key="r", exec_key="e")
    base.update(kw)
    return Settings(**base)


def view(*, quotes=None, lots=None, equity=100_000.0):
    quotes = quotes or {}
    lots = lots or {}
    positions = {k: v.quantity for k, v in lots.items()}
    return MarketView(quotes=quotes, fair={}, positions=positions,
                      equity=equity, lots=lots)


def q(ex="1", bid=0.40, ask=0.45):
    return Quote(exchange_id=ex, best_bid=bid, best_ask=ask,
                 bid_size=500, ask_size=500)


# --------------------------------------------------------------- the view ---

def test_market_view_lots_default_to_empty_for_existing_strategies():
    v = MarketView(quotes={}, fair={}, positions={"1": 10.0}, equity=1.0)
    assert v.lots == {}


# ------------------------------------------------------------ fresh exits ---

def test_fresh_long_asks_for_the_measured_edge_above_cost():
    s = ExitStrategy(ExitConfig(target_ticks=2))
    v = view(quotes={"1": q(bid=0.40, ask=0.45)},
             lots={"1": Lot("1", 100, avg_cost=0.42, age_minutes=5)})
    out = s.desired(v)
    assert len(out) == 1
    o = out[0]
    assert o.action == "sell" and o.quantity == 100
    assert o.price == pytest.approx(0.43)        # 0.42 + 2 ticks


def test_fresh_short_bids_below_cost_to_close():
    s = ExitStrategy(ExitConfig(target_ticks=2))
    v = view(quotes={"1": q(bid=0.40, ask=0.45)},
             lots={"1": Lot("1", -100, avg_cost=0.44, age_minutes=5)})
    out = s.desired(v)
    assert out[0].action == "buy"
    assert out[0].price == pytest.approx(0.43)   # 0.44 - 2 ticks


def test_exit_never_crosses_the_spread():
    """
    Paying ~2 ticks of spread to rescue a 1-tick edge is self-defeating, so an
    exit must stay strictly passive -- but it must still be QUOTED.

    This previously asserted `desired(v) == []` for a lot bought at 0.30 with
    the book at 0.60/0.65: a position up 0.30/share was left entirely
    unquoted because its cost-based target of 0.31 sat below the bid. The
    cost-based target is a FLOOR, not the price; the correct response is to
    raise the offer to a passive level and harvest the gain.
    """
    s = ExitStrategy()
    v = view(quotes={"1": q(bid=0.60, ask=0.65)},
             lots={"1": Lot("1", 100, avg_cost=0.30, age_minutes=5)})
    got = s.desired(v)
    assert len(got) == 1
    assert got[0].action == "sell"
    assert got[0].price > 0.60, "must not cross the bid"
    assert got[0].price < 0.65, "should improve the ask, not sit behind it"


# ------------------------------------------------------------ stale exits ---

def test_stale_long_stops_asking_for_edge_and_quotes_to_get_out():
    """Past 240 min the measured markout is negative; holding out is unjustified."""
    s = ExitStrategy(ExitConfig(decay_minutes=240, max_scratch_ticks=2))
    fresh = view(quotes={"1": q(bid=0.40, ask=0.45)},
                 lots={"1": Lot("1", 100, avg_cost=0.42, age_minutes=10)})
    stale = view(quotes={"1": q(bid=0.40, ask=0.45)},
                 lots={"1": Lot("1", 100, avg_cost=0.42, age_minutes=600)})
    assert s.desired(stale)[0].price < s.desired(fresh)[0].price


def test_stale_long_never_chases_a_collapsing_ask():
    """
    Regression. Clamping the stale quote to the best ask looked like "quote to
    get out", but against a collapsed book it dumped: cost 0.066 with a 0.010
    ask produced a 0.010 quote, realising 5.6 cents of loss to recover 1 cent
    of capital. The scratch must hold regardless of the book.
    """
    s = ExitStrategy(ExitConfig(decay_minutes=240, target_ticks=2))
    for ask in (0.050, 0.030, 0.010):
        px = s._long_exit_price(0.066, ask, stale=True, c=s.cfg)
        assert px == pytest.approx(0.055)   # 0.056 off-grid -> nearest tick


def test_stale_scratch_is_bounded_by_configuration_not_by_the_book():
    s = ExitStrategy(ExitConfig(decay_minutes=240, target_ticks=2))
    for ask in (None, 0.001, 0.5, 0.99):
        px = s._long_exit_price(0.43, ask, stale=True, c=s.cfg)
        assert px >= 0.43 - 2 * 0.005 - 1e-9


def test_stale_short_never_chases_a_spiking_bid():
    s = ExitStrategy(ExitConfig(decay_minutes=240, target_ticks=2))
    for bid in (0.50, 0.80, 0.99):
        px = s._short_exit_price(0.28, bid, stale=True, c=s.cfg)
        assert px == pytest.approx(0.29)


# --------------------------------------------------------------- hygiene ---

def test_dust_positions_are_ignored():
    s = ExitStrategy(ExitConfig(min_shares=25))
    v = view(quotes={"1": q()}, lots={"1": Lot("1", 5, avg_cost=0.42)})
    assert s.desired(v) == []


def test_untradeable_market_is_skipped():
    s = ExitStrategy()
    v = view(quotes={"1": Quote("1", None, None)},
             lots={"1": Lot("1", 100, avg_cost=0.42)})
    assert s.desired(v) == []


def test_position_without_a_quote_is_skipped():
    s = ExitStrategy()
    v = view(quotes={}, lots={"1": Lot("1", 100, avg_cost=0.42)})
    assert s.desired(v) == []


def test_exit_respects_its_order_cap():
    s = ExitStrategy(ExitConfig(max_orders=3))
    quotes = {str(i): q(str(i), 0.40, 0.45) for i in range(20)}
    lots = {str(i): Lot(str(i), 100, avg_cost=0.42, age_minutes=5)
            for i in range(20)}
    assert len(s.desired(view(quotes=quotes, lots=lots))) == 3


def test_exit_quantity_matches_the_whole_position():
    s = ExitStrategy()
    v = view(quotes={"1": q(bid=0.40, ask=0.50)},
             lots={"1": Lot("1", 377, avg_cost=0.42, age_minutes=5)})
    assert s.desired(v)[0].quantity == 377


def test_prices_stay_on_tick_and_in_range():
    s = ExitStrategy()
    for cost in (0.02, 0.157, 0.333, 0.5, 0.871, 0.98):
        v = view(quotes={"1": q(bid=0.01, ask=0.99)},
                 lots={"1": Lot("1", 100, avg_cost=cost, age_minutes=5)})
        for o in s.desired(v):
            assert 0.005 <= o.price <= 0.995
            assert abs(round(o.price / 0.005) - o.price / 0.005) < 1e-9


# ------------------------------------- risk: position-reducing trades ------

def _state(**kw):
    base = dict(balance=90_000.0, equity=100_000.0, cost_basis=5_000.0)
    base.update(kw)
    return PortfolioState(**base)


def test_closing_a_long_is_not_charged_against_the_deployment_cap():
    settings = _s()
    """
    Regression: the deployment check charged closing trades as if they opened
    exposure, so exits were vetoed exactly when the book was fullest.
    """
    rm = RiskManager(settings)
    cap = settings.limits.max_deployed_fraction * 100_000.0
    st = _state(cost_basis=cap, positions={"1": 1_000.0})
    assert rm.check(st, exchange_id="1", action="sell", price=0.50,
                    quantity=1_000, strategy="exit") is None


def test_closing_a_long_is_not_charged_against_the_share_cap():
    settings = _s()
    """
    Regression: the share cap summed |held| + quantity even when selling,
    so a position at the cap could never be reduced.
    """
    rm = RiskManager(settings)
    n = settings.limits.max_position_shares
    st = _state(positions={"1": float(n)})
    assert rm.check(st, exchange_id="1", action="sell", price=0.50,
                    quantity=int(n), strategy="exit") is None


def test_selling_more_than_held_still_charges_the_new_short():
    settings = _s()
    """Only the closing portion is free; the rest opens fresh exposure."""
    rm = RiskManager(settings)
    st = _state(cost_basis=settings.limits.max_deployed_fraction * 100_000.0,
                positions={"1": 100.0})
    v = rm.check(st, exchange_id="1", action="sell", price=0.50,
                 quantity=10_000, strategy="exit")
    assert v is not None


def test_exit_strategy_gets_no_opening_budget():
    settings = _s()
    """It may close anything and open nothing."""
    rm = RiskManager(settings)
    assert rm.strategy_budget("exit") == 0.0
    st = _state(positions={})
    assert rm.check(st, exchange_id="1", action="buy", price=0.50,
                    quantity=10, strategy="exit") is not None


def test_kill_switch_still_blocks_exits():
    settings = _s()
    """A latched kill switch outranks everything, including risk reduction."""
    rm = RiskManager(settings)
    st = _state(equity=1.0, peak_equity=100_000.0, positions={"1": 100.0})
    rm.update(st)
    assert rm.tripped
    assert rm.check(st, exchange_id="1", action="sell", price=0.50,
                    quantity=100, strategy="exit") is not None


def test_opening_trades_are_still_capped():
    settings = _s()
    """The relaxation must not leak into position-opening trades."""
    rm = RiskManager(settings)
    st = _state(cost_basis=settings.limits.max_deployed_fraction * 100_000.0)
    assert rm.check(st, exchange_id="1", action="buy", price=0.50,
                    quantity=1_000, strategy="ladder") is not None


def test_closing_a_short_by_buying_is_also_free():
    settings = _s()
    rm = RiskManager(settings)
    st = _state(cost_basis=settings.limits.max_deployed_fraction * 100_000.0,
                positions={"1": -500.0})
    assert rm.check(st, exchange_id="1", action="buy", price=0.50,
                    quantity=500, strategy="exit") is None


def test_collateral_asymmetry_unchanged():
    assert collateral("buy", 0.02, 100) == pytest.approx(2.0)
    assert collateral("sell", 0.02, 100) == pytest.approx(98.0)


# --------------------------------------------- lot normalisation (runner) ---

from datetime import datetime, timedelta, timezone      # noqa: E402

from sigbot.runner import _parse_ts, build_lots         # noqa: E402

NOW = datetime(2026, 10, 2, 18, 0, 0, tzinfo=timezone.utc)


def _pos(ex="1", qty=100, avg=0.42, lots=None):
    return {"exchangeId": ex, "quantity": qty, "avgCost": avg,
            "lots": lots if lots is not None else
            [{"quantity": abs(qty), "entryPrice": avg,
              "openedAt": (NOW - timedelta(minutes=30)).isoformat()}]}


def test_long_cost_is_already_in_yes_space():
    lots = build_lots([_pos(qty=100, avg=0.42)], now=NOW)
    assert lots["1"].avg_cost == pytest.approx(0.42)
    assert lots["1"].quantity == 100


def test_short_cost_is_converted_from_no_space_to_yes_space():
    """
    Live example: quantity -89, avgCost 0.72, YES currentPrice 0.279. The 0.72
    is the NO entry price, so the YES-space entry is 0.28. Using 0.72 directly
    would quote the exit on the wrong side of the book.
    """
    lots = build_lots([_pos(qty=-89, avg=0.72)], now=NOW)
    assert lots["1"].avg_cost == pytest.approx(0.28)
    assert lots["1"].quantity == -89


def test_short_exit_uses_the_converted_cost():
    """End to end: the short above must bid just under 0.28, not under 0.72."""
    lots = build_lots([_pos(qty=-89, avg=0.72)], now=NOW)
    # decay is pinned so this exercises the FRAME conversion, not staleness.
    s = ExitStrategy(ExitConfig(target_ticks=2, min_shares=25,
                                decay_minutes=10_000))
    v = view(quotes={"1": q(bid=0.25, ask=0.30)}, lots=lots)
    out = s.desired(v)
    assert out[0].action == "buy"
    assert out[0].price == pytest.approx(0.27)


def test_age_is_quantity_weighted_across_lots():
    """One old scrap must not make a mostly-fresh position look stale."""
    p = _pos(qty=1000, lots=[
        {"quantity": 999, "openedAt": (NOW - timedelta(minutes=10)).isoformat()},
        {"quantity": 1, "openedAt": (NOW - timedelta(minutes=10_000)).isoformat()},
    ])
    assert build_lots([p], now=NOW)["1"].age_minutes < 30


def test_age_zero_when_timestamps_are_missing():
    p = _pos(lots=[{"quantity": 100}])
    assert build_lots([p], now=NOW)["1"].age_minutes == 0.0


def test_zero_quantity_positions_are_dropped():
    assert build_lots([_pos(qty=0)], now=NOW) == {}


def test_parses_seven_digit_fractional_seconds():
    """The venue emits .3633048 -- more precision than fromisoformat accepts."""
    assert _parse_ts("2026-10-02T14:04:50.3633048+00:00") is not None


def test_parses_trailing_z_and_naive_timestamps():
    assert _parse_ts("2026-10-02T14:04:50Z").tzinfo is not None
    assert _parse_ts("2026-10-02T14:04:50").tzinfo is not None


def test_unparseable_timestamp_does_not_raise():
    assert _parse_ts("not-a-date") is None
    assert _parse_ts("") is None


# ------------------------------- stale inventory that moved in our favour ---

def test_stale_profitable_long_is_still_quoted():
    """
    Regression: a long bought at 0.032 whose bid rose to 0.035 produced a
    stale target of 0.020, below the bid, which the passivity check then
    discarded. The position stopped being quoted and simply sat there.
    """
    px = ExitStrategy._long_exit_price(0.032, 0.035, True, ExitConfig())
    assert px > 0.035, "stale exit must not sit below the bid"
    assert px == pytest.approx(0.040)


def test_stale_exit_never_scratches_below_the_market():
    """Selling under the bid gives away a gain we already have."""
    for cost, bid in ((0.032, 0.035), (0.10, 0.20), (0.50, 0.70)):
        px = ExitStrategy._long_exit_price(cost, bid, True, ExitConfig())
        assert px > bid


def test_exit_still_refuses_to_chase_a_collapsing_book_down():
    """The original protection must survive: never clamp DOWN to a bad book."""
    px = ExitStrategy._long_exit_price(0.066, 0.010, True, ExitConfig())
    assert px == pytest.approx(0.055), "must hold its cost-based ask"


def test_stale_profitable_short_is_still_quoted():
    """Mirror image: a short whose ask fell below our stale buy-back target."""
    px = ExitStrategy._short_exit_price(0.90, 0.80, True, ExitConfig())
    assert px < 0.80, "stale short exit must not sit above the ask"
    assert px == pytest.approx(0.795)


def test_short_exit_still_refuses_to_chase_a_spiking_book_up():
    px = ExitStrategy._short_exit_price(0.20, 0.90, True, ExitConfig())
    assert px == pytest.approx(0.21)


# ------------------------------- corrected markout timing drives the config ---

def test_decay_matches_the_measured_sign_change():
    """
    Tape-timed markout is +0.00217 at 5 min (P=0.98) and -0.00104 at 30 min
    (P(>0)=0.29), so the edge is gone well before the old 240-minute setting.
    """
    assert 5.0 < ExitConfig().decay_minutes < 30.0


def test_target_is_not_many_multiples_of_the_measured_edge():
    """Asking 2 ticks for a 0.43-tick edge meant offers never filled."""
    assert ExitConfig().target_ticks == 1


def test_max_scratch_ticks_is_actually_used():
    """It was dead config: stale pricing reused target_ticks."""
    c = ExitConfig(target_ticks=1, max_scratch_ticks=6)
    px = ExitStrategy._long_exit_price(0.50, None, True, c)
    assert px == pytest.approx(0.47), "stale scratch must use max_scratch_ticks"


def test_fresh_pricing_still_uses_target_ticks():
    c = ExitConfig(target_ticks=1, max_scratch_ticks=6)
    assert ExitStrategy._long_exit_price(0.50, None, False, c) == pytest.approx(0.505)
