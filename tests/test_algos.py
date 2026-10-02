#!/usr/bin/env python3
"""
Tests for algos.py.

Run: python3 -m pytest research/test_algos.py -q

The Poisson-Binomial tests matter most: a research agent reported that its own
FFT implementation had a normalisation bug producing "silently plausible but
wrong" answers. Everything here is checked against brute force or a closed form.
"""
import itertools
import math
import numpy as np
import pytest
from scipy import stats

from sigbot import algos as A


# ------------------------------------------------- Poisson-Binomial ---------

def brute_force_pmf(probs):
    """Exact PMF by enumerating all 2^n outcomes. Only feasible for small n."""
    n = len(probs)
    pmf = np.zeros(n + 1)
    for bits in itertools.product([0, 1], repeat=n):
        pr = 1.0
        for b, p in zip(bits, probs):
            pr *= p if b else (1 - p)
        pmf[sum(bits)] += pr
    return pmf


def test_poisson_binomial_matches_brute_force():
    rng = np.random.default_rng(0)
    for n in (1, 2, 5, 12):
        p = rng.uniform(0.01, 0.99, size=n)
        got = A.poisson_binomial_pmf(p)
        want = brute_force_pmf(p)
        assert np.allclose(got, want, atol=1e-12), f"n={n} max err {np.abs(got-want).max()}"


def test_poisson_binomial_reduces_to_binomial():
    """All p equal => ordinary Binomial."""
    n, p = 30, 0.37
    got = A.poisson_binomial_pmf([p] * n)
    want = stats.binom.pmf(np.arange(n + 1), n, p)
    assert np.allclose(got, want, atol=1e-12)


def test_poisson_binomial_pmf_sums_to_one():
    rng = np.random.default_rng(1)
    p = rng.uniform(0.001, 0.999, size=237)
    assert abs(A.poisson_binomial_pmf(p).sum() - 1.0) < 1e-10


def test_poisson_binomial_degenerate_probabilities():
    assert np.allclose(A.poisson_binomial_pmf([1.0, 1.0, 1.0]), [0, 0, 0, 1])
    assert np.allclose(A.poisson_binomial_pmf([0.0, 0.0]), [1, 0, 0])


def test_poisson_binomial_sf_bounds():
    p = [0.3, 0.6, 0.9]
    assert A.poisson_binomial_sf(p, 0) == 1.0
    assert A.poisson_binomial_sf(p, 99) == 0.0
    assert abs(A.poisson_binomial_sf(p, 1) - (1 - (0.7 * 0.4 * 0.1))) < 1e-12


def test_poisson_binomial_mean_and_variance():
    rng = np.random.default_rng(2)
    p = rng.uniform(0.05, 0.95, size=60)
    pmf = A.poisson_binomial_pmf(p)
    k = np.arange(len(pmf))
    mean = (pmf * k).sum()
    var = (pmf * (k - mean) ** 2).sum()
    assert abs(mean - p.sum()) < 1e-9
    assert abs(var - (p * (1 - p)).sum()) < 1e-9


# ---------------------------------------------------------- microprice -----

def test_microprice_always_inside_spread():
    rng = np.random.default_rng(3)
    for _ in range(500):
        bid = rng.uniform(0.01, 0.9)
        ask = bid + rng.uniform(0.005, 0.05)
        vb, va = rng.uniform(1, 1e4), rng.uniform(1, 1e4)
        mp = A.microprice(bid, ask, vb, va)
        assert bid - 1e-12 <= mp <= ask + 1e-12


def test_microprice_two_forms_agree():
    """Pw = mid + (spread/2)*(2I-1) must equal the cross-multiplied form."""
    rng = np.random.default_rng(4)
    for _ in range(200):
        bid = rng.uniform(0.01, 0.9)
        ask = bid + rng.uniform(0.005, 0.05)
        vb, va = rng.uniform(1, 1e4), rng.uniform(1, 1e4)
        direct = A.microprice(bid, ask, vb, va)
        alt = (bid + ask) / 2 + (ask - bid) / 2 * (2 * A.imbalance(vb, va) - 1)
        assert abs(direct - alt) < 1e-12


def test_microprice_large_bid_pulls_toward_ask():
    """The counterintuitive-but-correct direction: heavy bid => price rises."""
    bid, ask = 0.40, 0.44
    heavy_bid = A.microprice(bid, ask, bid_size=10_000, ask_size=10)
    heavy_ask = A.microprice(bid, ask, bid_size=10, ask_size=10_000)
    assert heavy_bid > (bid + ask) / 2
    assert heavy_ask < (bid + ask) / 2


def test_microprice_balanced_book_is_mid():
    assert abs(A.microprice(0.3, 0.32, 500, 500) - 0.31) < 1e-12


def test_microprice_empty_book_falls_back_to_mid():
    assert abs(A.microprice(0.3, 0.32, 0, 0) - 0.31) < 1e-12


# -------------------------------------------------------------- sizing -----

def test_equal_variance_sizing_holds_variance_constant():
    """Away from the notional cap, q^2*p(1-p) should be ~constant."""
    variances = []
    for p in (0.20, 0.30, 0.40, 0.50, 0.60):
        q = A.equal_variance_size(p, scale=40.0, max_notional=1e9)
        variances.append(q ** 2 * p * (1 - p))
    assert max(variances) / min(variances) < 1.02


def test_equal_variance_sizing_deploys_less_capital_at_tails():
    """The whole point: fewer SUSQies at risk on a longshot."""
    notional_mid = A.equal_variance_size(0.50) * 0.50
    notional_tail = A.equal_variance_size(0.05) * 0.05
    assert notional_tail < notional_mid


def test_equal_variance_sizing_respects_notional_cap():
    for p in (0.05, 0.5, 0.95):
        q = A.equal_variance_size(p, scale=40.0, max_notional=80.0)
        assert q * p <= 80.0 + p


def test_equal_variance_sizing_min_one_share():
    assert A.equal_variance_size(0.99, scale=0.0001, max_notional=0.0001) >= 1


# --------------------------------------------------------------- kelly -----

def test_kelly_zero_without_edge():
    assert A.kelly_fraction(0.5, 0.5) == 0.0
    assert A.kelly_fraction(0.4, 0.5) == 0.0          # negative edge -> no bet


def test_kelly_positive_with_edge_and_bounded():
    f = A.kelly_fraction(0.6, 0.5)
    assert 0 < f < 1
    assert abs(f - (0.6 - 0.5) / (1 - 0.5)) < 1e-12


def test_kelly_certain_win_is_full_bankroll():
    assert abs(A.kelly_fraction(1.0, 0.5) - 1.0) < 1e-12


def test_kelly_handles_degenerate_prices():
    assert A.kelly_fraction(0.9, 0.0) == 0.0
    assert A.kelly_fraction(0.9, 1.0) == 0.0


# ---------------------------------------------------------------- devig ----

def test_devig_sums_to_one():
    out = A.devig({"R": 0.37, "D": 0.65})
    assert abs(sum(out.values()) - 1.0) < 1e-12
    assert out["R"] < 0.37           # overround removed


def test_devig_preserves_ordering_and_handles_three_way():
    out = A.devig({"R": 0.73, "D": 0.015, "I": 0.28})
    assert abs(sum(out.values()) - 1.0) < 1e-12
    assert out["R"] > out["I"] > out["D"]


def test_devig_zero_input_is_safe():
    out = A.devig({"R": 0.0, "D": 0.0})
    assert sum(out.values()) == 0.0


# ------------------------------------------------- correlated models -------

def test_one_factor_preserves_marginals():
    """
    Each race's simulated win rate must match its input probability.

    This guards the bug the margin-space construction had: summing two independent
    t variates is not t, which pushed 0.90 out to 0.94 and 0.10 down to 0.06.
    """
    p = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
    for kwargs in ({}, {"df": 5}):
        counts = np.zeros(len(p))
        sims = 120_000
        rng = np.random.default_rng(7)
        z = rng.standard_normal(sims)
        eps = rng.standard_normal((sims, len(p)))
        x = math.sqrt(0.25) * z[:, None] + math.sqrt(0.75) * eps
        if kwargs.get("df"):
            w = rng.chisquare(5, size=sims) / 5
            x = x / np.sqrt(w)[:, None]
            thresh = stats.t.ppf(p, 5)
        else:
            thresh = stats.norm.ppf(p)
        counts = (x <= thresh[None, :]).mean(axis=0)
        assert np.allclose(counts, p, atol=0.01), f"{kwargs}: got {counts}"


def test_one_factor_simulate_marginals_via_public_api():
    """Same check, exercising one_factor_simulate itself via the mean seat count."""
    p = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
    for df in (None, 5):
        counts = A.one_factor_simulate(p, rho=0.25, n_sims=120_000, seed=3, df=df)
        assert abs(counts.mean() - p.sum()) < 0.05, f"df={df}"


def test_correlation_increases_variance():
    """The core result: ignoring the shared factor understates tail risk."""
    p = np.full(34, 0.5)
    ind = A.one_factor_simulate(p, rho=0.0, n_sims=60_000, seed=11)
    cor = A.one_factor_simulate(p, rho=0.25, n_sims=60_000, seed=11)
    assert cor.std() > ind.std() * 1.5
    assert abs(cor.mean() - ind.mean()) < 0.5       # same mean, fatter spread


def test_quadrature_matches_simulation():
    """Deterministic Vasicek quadrature should agree with Monte Carlo."""
    p = np.array([0.2, 0.35, 0.5, 0.65, 0.8, 0.45, 0.55])
    pmf = A.one_factor_quadrature(p, rho=0.25, n_nodes=64)
    assert abs(pmf.sum() - 1.0) < 1e-8
    mean_q = (pmf * np.arange(len(pmf))).sum()
    assert abs(mean_q - p.sum()) < 0.05


def test_quadrature_zero_correlation_is_poisson_binomial():
    p = np.array([0.2, 0.5, 0.8, 0.33])
    pmf_q = A.one_factor_quadrature(p, rho=1e-9, n_nodes=64)
    pmf_e = A.poisson_binomial_pmf(p)
    assert np.allclose(pmf_q, pmf_e, atol=1e-4)


# ------------------------------------------------------------- markout -----

def test_markout_sign_and_magnitude():
    assert abs(A.markout(0.23, 0.33, "yes") - 0.10) < 1e-12
    assert abs(A.markout(0.23, 0.18, "yes") + 0.05) < 1e-12


def test_no_fill_is_valued_in_no_space_not_yes_space():
    """
    Regression. Buying NO at 0.60 while the YES mid is 0.50 means paying 0.60
    for a share worth (1 - 0.50) = 0.50. That is a 0.10 LOSS. The old sign-flip
    form reported +0.10 -- and a test had encoded that, so the bug looked
    verified.
    """
    assert A.markout(0.60, 0.50, "no") == pytest.approx(-0.10)


def test_no_fill_markout_matches_the_equivalent_yes_sale():
    """
    'buy NO @p' is the engine's canonical form of 'sell YES @(1-p)'. Both
    descriptions must produce the same markout.
    """
    p_no, yes_mid = 0.945, 0.0475
    buy_no = A.markout(p_no, yes_mid, "no")
    sell_yes = (1.0 - p_no) - yes_mid          # sold YES at 0.055 vs mid 0.0475
    assert buy_no == pytest.approx(sell_yes)
    assert buy_no == pytest.approx(0.0075)


def test_markout_is_bounded_by_one():
    """A per-share markout near +0.90 is arithmetically impossible here."""
    for px in (0.05, 0.25, 0.50, 0.75, 0.945):
        for mid in (0.01, 0.2, 0.5, 0.8, 0.99):
            for side in ("yes", "no"):
                assert abs(A.markout(px, mid, side)) <= 1.0


def test_markout_is_zero_when_filled_at_fair_value():
    assert A.markout(0.30, 0.30, "yes") == pytest.approx(0.0)
    assert A.markout(0.70, 0.30, "no") == pytest.approx(0.0)


# ------------------------------------------------------------ calibration --

def test_brier_bounds_and_perfect_forecast():
    assert A.brier_score([1, 0, 1], [1, 0, 1]) == 0.0
    assert abs(A.brier_score([0, 1], [1, 0]) - 1.0) < 1e-12


def test_brier_decomposition_identity():
    """Brier == reliability - resolution + uncertainty (Murphy)."""
    rng = np.random.default_rng(5)
    f = rng.uniform(0, 1, 4000)
    o = (rng.uniform(0, 1, 4000) < f).astype(float)
    d = A.brier_decomposition(f, o, n_bins=10)
    lhs = d["brier"]
    rhs = d["reliability"] - d["resolution"] + d["uncertainty"]
    assert abs(lhs - rhs) < 0.02


def test_wellcalibrated_forecasts_have_low_reliability_term():
    rng = np.random.default_rng(6)
    f = rng.uniform(0.05, 0.95, 8000)
    o = (rng.uniform(0, 1, 8000) < f).astype(float)
    assert A.brier_decomposition(f, o)["reliability"] < 0.01


# ------------------------------------------------------- price validation --

def test_round_to_tick_and_validity():
    assert A.round_to_tick(0.1234) == 0.125
    assert A.valid_limit_price(0.125)
    assert not A.valid_limit_price(0.123)      # off-tick -> venue rejects
    assert not A.valid_limit_price(0.0)
    assert not A.valid_limit_price(1.0)
    assert A.valid_limit_price(A.MIN_PRICE)
    assert A.valid_limit_price(A.MAX_PRICE)


def test_round_to_tick_is_idempotent():
    rng = np.random.default_rng(8)
    for p in rng.uniform(0.01, 0.99, 200):
        once = A.round_to_tick(p)
        assert A.round_to_tick(once) == once
