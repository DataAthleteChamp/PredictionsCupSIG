"""Tests for microstructure measurement."""
import math

import numpy as np
import pytest

from sigbot.microstructure import (QueueModel, decompose, decompose_fill,
                                   fit_queue_decay, kyle_lambda,
                                   prefers_more_variance, safety_first_ratio)


# ------------------------------------------------ Huang-Stoll decomposition --

def test_passive_buy_below_mid_captures_the_half_spread():
    eff, real = decompose_fill(0.40, mid_at_fill=0.42, mid_later=0.42)
    assert eff == pytest.approx(0.02)
    assert real == pytest.approx(0.02)


def test_adverse_selection_is_what_the_mid_takes_back():
    """Bought at 0.40 against a 0.42 mid; mid then fell to 0.405."""
    eff, real = decompose_fill(0.40, 0.42, 0.405)
    assert eff == pytest.approx(0.02)
    assert real == pytest.approx(0.005)
    assert eff - real == pytest.approx(0.015)


def test_realized_equals_markout():
    """The decomposition explains a markout, it does not replace one."""
    from sigbot.algos import markout
    for side in ("yes", "no"):
        _, real = decompose_fill(0.30, 0.35, 0.33, side=side, action="buy")
        assert real == pytest.approx(markout(0.30, 0.33, side))


def test_no_fills_are_converted_once_and_correctly():
    """A NO price against a YES mid is the frame error that cost us 17x."""
    eff, real = decompose_fill(0.945, mid_at_fill=0.0475, mid_later=0.0425,
                               side="no")
    assert eff == pytest.approx(0.0075)
    assert real == pytest.approx(0.0125)
    assert abs(eff) < 1.0 and abs(real) < 1.0


def test_passive_sell_is_the_mirror_image():
    eff, real = decompose_fill(0.45, 0.42, 0.42, action="sell")
    assert eff == pytest.approx(0.03)
    assert real == pytest.approx(0.03)


def test_sell_adverse_selection_when_mid_rises():
    eff, real = decompose_fill(0.45, 0.42, 0.44, action="sell")
    assert eff == pytest.approx(0.03)
    assert real == pytest.approx(0.01)


def test_decompose_aggregates_and_reports_retention():
    fills = [(0.40, 0.42, 0.42), (0.40, 0.42, 0.41)]
    d = decompose(fills)
    assert d.n == 2
    assert d.effective == pytest.approx(0.02)
    assert d.realized == pytest.approx(0.015)
    assert d.adverse_selection == pytest.approx(0.005)
    assert d.retention == pytest.approx(0.75)


def test_decompose_handles_empty_input():
    d = decompose([])
    assert d.n == 0 and d.retention == 0.0


def test_full_giveback_is_zero_retention():
    d = decompose([(0.40, 0.42, 0.40)])
    assert d.realized == pytest.approx(0.0)
    assert d.retention == pytest.approx(0.0)


def test_retention_can_exceed_one_when_the_mid_moves_our_way():
    d = decompose([(0.40, 0.42, 0.45)])
    assert d.retention > 1.0


# ----------------------------------------------------------- queue decay ---

def test_fit_recovers_a_known_geometric_decay():
    true = QueueModel(base=3.17, ratio=0.775)
    obs = [(k, true.fill_rate(k)) for k in (1, 3, 6, 11, 20)]
    fit = fit_queue_decay(obs)
    assert fit.base == pytest.approx(3.17, rel=1e-6)
    assert fit.ratio == pytest.approx(0.775, rel=1e-6)


def test_fit_matches_our_measured_endpoints():
    """3.17/order-hr at the touch, 0.025 at 20 ticks deep -> r ~ 0.775."""
    fit = fit_queue_decay([(1, 3.17), (20, 0.025)])
    assert fit.ratio == pytest.approx(0.775, abs=0.01)
    assert fit.fill_rate(1) == pytest.approx(3.17, rel=1e-9)
    assert fit.fill_rate(20) == pytest.approx(0.025, rel=1e-9)


def test_interpolates_untested_depths_monotonically():
    fit = fit_queue_decay([(1, 3.17), (20, 0.025)])
    rates = [fit.fill_rate(k) for k in range(1, 21)]
    assert all(a > b for a, b in zip(rates, rates[1:]))


def test_mu_over_theta_is_reported_for_falsification():
    fit = fit_queue_decay([(1, 3.17), (20, 0.025)])
    assert fit.mu_over_theta == pytest.approx(0.775 / 0.225, abs=0.2)


def test_fit_needs_two_positive_points():
    with pytest.raises(ValueError):
        fit_queue_decay([(1, 3.17)])
    with pytest.raises(ValueError):
        fit_queue_decay([(1, 0.0), (20, 0.0)])


def test_fit_tolerates_noise():
    rng = np.random.default_rng(0)
    true = QueueModel(3.0, 0.8)
    obs = [(k, true.fill_rate(k) * math.exp(rng.normal(0, 0.05)))
           for k in range(1, 21)]
    fit = fit_queue_decay(obs)
    assert fit.ratio == pytest.approx(0.8, abs=0.03)


# --------------------------------------------------------- Kyle's lambda ---

def test_kyle_lambda_recovers_a_known_impact():
    q = np.array([100.0, -50.0, 200.0, -300.0, 75.0])
    dp = 0.0004 * q
    assert kyle_lambda(q, dp) == pytest.approx(0.0004)


def test_kyle_lambda_is_zero_without_impact():
    q = [100.0, -50.0, 200.0]
    assert kyle_lambda(q, [0.0, 0.0, 0.0]) == pytest.approx(0.0)


def test_kyle_lambda_undefined_on_degenerate_input():
    assert math.isnan(kyle_lambda([], []))
    assert math.isnan(kyle_lambda([0.0, 0.0], [1.0, 1.0]))
    assert math.isnan(kyle_lambda([1.0, 2.0], [1.0]))


# ------------------------------------------------------- safety-first -----

def test_safety_first_prefers_the_closer_book_when_ahead():
    """Ahead of target: lower variance is better."""
    ahead_tight = safety_first_ratio(120.0, 5.0, target=100.0)
    ahead_wide = safety_first_ratio(120.0, 50.0, target=100.0)
    assert ahead_tight > ahead_wide


def test_safety_first_prefers_variance_when_behind():
    """
    The result that contradicts Sharpe. Behind the target, more variance is
    better, because only the tail reaches the threshold.
    """
    behind_tight = safety_first_ratio(50.0, 5.0, target=100.0)
    behind_wide = safety_first_ratio(50.0, 50.0, target=100.0)
    assert behind_wide > behind_tight
    assert behind_wide < 0


def test_prefers_more_variance_flips_exactly_at_the_target():
    assert prefers_more_variance(99.0, 100.0)
    assert not prefers_more_variance(101.0, 100.0)
    assert not prefers_more_variance(100.0, 100.0)


def test_safety_first_matches_our_actual_position():
    """Equity ~100k against a ~700k podium: deeply behind, so seek variance."""
    assert prefers_more_variance(100_044.0, 700_557.0)
    assert safety_first_ratio(100_044.0, 2_000.0, 700_557.0) < 0


def test_zero_variance_is_decided_by_the_target_alone():
    assert safety_first_ratio(110.0, 0.0, 100.0) == math.inf
    assert safety_first_ratio(90.0, 0.0, 100.0) == -math.inf


# ------------------------------------------------------ frame conversion ---

from sigbot.microstructure import crosses_book, quote_depth_ticks, to_yes_frame


def test_yes_orders_pass_through_unchanged():
    assert to_yes_frame("yes", "buy", 0.30) == ("buy", 0.30)
    assert to_yes_frame("yes", "sell", 0.70) == ("sell", 0.70)


def test_buying_no_is_selling_yes_at_the_complement():
    a, p = to_yes_frame("no", "buy", 0.77)
    assert a == "sell" and p == pytest.approx(0.23)


def test_selling_no_is_buying_yes_at_the_complement():
    a, p = to_yes_frame("no", "sell", 0.77)
    assert a == "buy" and p == pytest.approx(0.23)


def test_conversion_is_an_involution_on_no_orders():
    """Converting a NO order twice must return the original order."""
    for action in ("buy", "sell"):
        a1, p1 = to_yes_frame("no", action, 0.37)
        a2, p2 = to_yes_frame("no", a1, p1)
        assert a2 == action and p2 == pytest.approx(0.37)


def test_the_real_order_that_looked_like_it_crossed_by_110_ticks():
    """
    Live order: exchange 1004, no/buy 71 @ 0.77, book 0.210/0.225 in YES space.
    Naively this reads as a buy 110 ticks through the mid. Correctly framed it
    is a sell of YES at 0.23 -- one tick behind the ask, perfectly passive.
    """
    assert not crosses_book("no", "buy", 0.77, 0.210, 0.225)
    d = quote_depth_ticks("no", "buy", 0.77, 0.210, 0.225)
    assert d == pytest.approx(2.5)          # 0.23 vs mid 0.2175


def test_depth_is_positive_when_passive_and_negative_when_aggressive():
    assert quote_depth_ticks("yes", "buy", 0.48, 0.49, 0.51) > 0
    assert quote_depth_ticks("yes", "buy", 0.52, 0.49, 0.51) < 0
    assert quote_depth_ticks("yes", "sell", 0.52, 0.49, 0.51) > 0
    assert quote_depth_ticks("yes", "sell", 0.48, 0.49, 0.51) < 0


def test_crosses_book_detects_real_aggression_in_both_frames():
    assert crosses_book("yes", "buy", 0.51, 0.49, 0.51)
    assert crosses_book("yes", "sell", 0.49, 0.49, 0.51)
    # no/buy @ 0.49 == sell YES @ 0.51: passive, above the ask
    assert not crosses_book("no", "buy", 0.49, 0.49, 0.51)
    # no/buy @ 0.52 == sell YES @ 0.48: crosses the bid
    assert crosses_book("no", "buy", 0.52, 0.49, 0.51)
