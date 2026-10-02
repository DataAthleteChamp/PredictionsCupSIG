#!/usr/bin/env python3
"""
Core quantitative algorithms, validated by test_algos.py.

Every function here is pure (no I/O, no network) so it is deterministically
testable. Trading logic composes these; it never reimplements them.

References are given inline. Where a formula has a known failure mode, the
docstring says so explicitly.
"""
from __future__ import annotations
import math
import numpy as np
from scipy import stats

TICK = 0.005
MIN_PRICE = 0.005
MAX_PRICE = 0.995


# ---------------------------------------------------------------- pricing ---

def round_to_tick(p: float) -> float:
    """Snap to the 0.005 grid. Off-tick prices are rejected by the venue."""
    return round(round(p / TICK) * TICK, 3)


def valid_limit_price(p: float) -> bool:
    if p is None:
        return False
    on_tick = abs(p / TICK - round(p / TICK)) < 1e-9
    return on_tick and MIN_PRICE - 1e-12 <= p <= MAX_PRICE + 1e-12


def microprice(bid: float, ask: float, bid_size: float, ask_size: float) -> float:
    """
    Stoikov (2018) weighted mid.

        I  = Vb / (Vb + Va)
        Pw = (Pb*Va + Pa*Vb) / (Vb + Va)
           = mid + (spread/2) * (2I - 1)

    Note the cross-multiplication: ASK size multiplies BID price. A large resting
    bid pulls fair value toward the ask. Result is always inside [bid, ask].
    """
    tot = bid_size + ask_size
    if tot <= 0:
        return (bid + ask) / 2.0
    return (bid * ask_size + ask * bid_size) / tot


def imbalance(bid_size: float, ask_size: float) -> float:
    tot = bid_size + ask_size
    return 0.5 if tot <= 0 else bid_size / tot


def devig(probs: dict[str, float]) -> dict[str, float]:
    """
    Normalise the outcomes of one mutually-exclusive race to sum to 1.

    Removes the overround. On this venue the R and D markets for a race are
    separate books, so their prices do NOT sum to 1 without this step.

    A single-member group is NOT de-vigged: dividing a lone probability by
    itself returns 1.0, silently replacing a real estimate with certainty.
    Groups lose members routinely (one-sided books, a dropped CLOB request), so
    this must fail safe by passing the value through untouched.
    """
    if len(probs) < 2:
        return dict(probs)
    tot = sum(probs.values())
    if tot <= 0:
        return {k: 0.0 for k in probs}
    return {k: v / tot for k, v in probs.items()}


# ---------------------------------------------------------------- sizing ----

def equal_variance_size(price: float, scale: float = 40.0,
                        max_notional: float = 80.0) -> int:
    """
    Size so that DOLLAR variance is constant across price levels.

    Share variance of a binary contract is p(1-p), so q ∝ 1/sqrt(p(1-p)) holds
    q^2*p(1-p) constant. This deploys LESS capital at the extremes, which is the
    correct behaviour: with full-cash collateral and no leverage, fixed-capital
    sizing gives dollar variance capital^2*(1-p)/p, which diverges as p -> 0.
    """
    p = min(max(price, 1e-6), 1 - 1e-6)
    v = math.sqrt(p * (1 - p))
    q = min(scale / v, max_notional / p)
    return max(1, int(round(q)))


def kelly_fraction(p_true: float, price: float) -> float:
    """
    Kelly fraction for a binary contract bought at `price` with true probability
    `p_true`. Payoff is 1 or 0, so net odds b = (1-price)/price.

        f* = (p*b - (1-p)) / b  =  (p - price) / (1 - price)

    Returns 0 when there is no edge. NOT the right objective in a rank-based
    tournament (see PROJECT_PLAN risk policy) — provided for the core sleeve only.
    """
    if not (0 < price < 1):
        return 0.0
    f = (p_true - price) / (1.0 - price)
    return max(0.0, f)


# ------------------------------------------------- Poisson-Binomial ---------

def poisson_binomial_pmf(probs) -> np.ndarray:
    """
    Exact PMF of the sum of independent non-identical Bernoulli variables.

    DP recursion, O(n^2) time / O(n) space (Barlow & Heidtmann 1984):
        P_i(k) = (1-p_i) P_{i-1}(k) + p_i P_{i-1}(k-1)

    At n~237 this is sub-millisecond and in practice as fast as the FFT method.
    """
    p = np.asarray(probs, dtype=float)
    pmf = np.zeros(len(p) + 1)
    pmf[0] = 1.0
    for i, pi in enumerate(p):
        pmf[1:i + 2] = pmf[1:i + 2] * (1 - pi) + pmf[0:i + 1] * pi
        pmf[0] *= (1 - pi)
    return pmf


def poisson_binomial_sf(probs, k: int) -> float:
    """P(X >= k)."""
    pmf = poisson_binomial_pmf(probs)
    if k <= 0:
        return 1.0
    if k > len(pmf) - 1:
        return 0.0
    return float(pmf[k:].sum())


# ------------------------------------------- correlated outcome models ------

def one_factor_simulate(probs, rho: float = 0.25, n_sims: int = 200_000,
                        seed: int | None = None, df: int | None = None,
                        **_ignored) -> np.ndarray:
    """
    Correlated binary outcomes via a one-factor COPULA. Marginals exact.

        X_i = sqrt(rho)*Z + sqrt(1-rho)*eps_i          (each X_i ~ N(0,1))
        outcome_i = 1{ X_i <= Phi^{-1}(p_i) }          (so P(outcome_i)=p_i exactly)

    `rho` is the NATIONAL share of variance (538's congressional figure is 0.25).
    Returns per-simulation success counts.

    Set `df` to use a t-copula instead (fatter joint tails, marginals still exact):
    the Gaussian vector is divided by sqrt(W/df), W ~ chi2(df), shared across races.

    WARNING — the naive alternative is WRONG. Building this in "margin space" as
        margin_i = sigma*t^{-1}(p_i);  outcome = 1{margin_i + e_nat + e_i > 0}
    with e_nat, e_i both t-distributed does NOT preserve the marginals, because the
    sum of two independent t variates is not t. It pushes extremes outward (an input
    of 0.90 came out at 0.94, 0.10 at 0.06) and therefore misstates seat-count
    variance. test_one_factor_preserves_marginals guards against regressing to it.

    Ignoring the shared factor entirely understates tail risk badly: at rho=0.25 the
    seat-count sd roughly doubles versus independence.
    """
    p = np.clip(np.asarray(probs, dtype=float), 1e-9, 1 - 1e-9)
    rng = np.random.default_rng(seed)
    n = len(p)
    z = rng.standard_normal(n_sims)
    eps = rng.standard_normal((n_sims, n))
    x = math.sqrt(rho) * z[:, None] + math.sqrt(1.0 - rho) * eps
    if df:
        w = rng.chisquare(df, size=n_sims) / df
        x = x / np.sqrt(w)[:, None]
        thresh = stats.t.ppf(p, df)
    else:
        thresh = stats.norm.ppf(p)
    return (x <= thresh[None, :]).sum(axis=1)


def one_factor_quadrature(probs, rho: float = 0.25, n_nodes: int = 64):
    """
    Deterministic alternative to the Monte Carlo above, using the Gaussian
    one-factor (Vasicek) copula and Gauss-Hermite quadrature.

        p_i(Z) = Phi( (Phi^{-1}(p_i) - beta*Z) / sqrt(1-beta^2) ),  beta = sqrt(rho)

    Conditional on Z the outcomes are independent, so the exact Poisson-Binomial
    applies per node; integrating over Z gives the unconditional distribution.

    This is the credit-portfolio ASRF model (Vasicek 1987, Gordy 2003) — the seat
    problem is formally identical to a loan portfolio. No sampling error.
    """
    p = np.clip(np.asarray(probs, dtype=float), 1e-9, 1 - 1e-9)
    beta = math.sqrt(rho)
    nodes, weights = np.polynomial.hermite_e.hermegauss(n_nodes)
    weights = weights / weights.sum()
    out = np.zeros(len(p) + 1)
    denom = math.sqrt(max(1.0 - rho, 1e-12))
    for z, w in zip(nodes, weights):
        pz = stats.norm.cdf((stats.norm.ppf(p) - beta * z) / denom)
        out += w * poisson_binomial_pmf(pz)
    return out


# ---------------------------------------------------------------- markout ---

def markout(fill_price: float, later_mid: float, side: str = "yes") -> float:
    """
    Per-share markout of a BUY fill. Positive means the market moved our way.

    `later_mid` is always the YES-space mid. A 'no' fill's price, however, is
    quoted in NO space, and a NO share settles at (1 - yes). Comparing a NO
    price directly against a YES mid mixes frames: it inflates the markout by
    roughly (1 - 2*mid), which is enough to report a +0.0125 fill as +0.9025.

    So convert the position's value into the frame its price was quoted in,
    then subtract what we paid.

    Cartea-Jaimungal-Penalva: expected per-fill P&L ~= delta - c_adverse.
    A persistently negative markout at horizon h means our quoted distance sits
    inside the adverse-selection cost at that horizon -- widen.
    """
    value = later_mid if side == "yes" else (1.0 - later_mid)
    return value - fill_price


def brier_score(forecasts, outcomes) -> float:
    """Mean squared error of probabilistic forecasts. Lower is better."""
    f = np.asarray(forecasts, dtype=float)
    o = np.asarray(outcomes, dtype=float)
    return float(np.mean((f - o) ** 2))


def brier_decomposition(forecasts, outcomes, n_bins: int = 10):
    """
    Murphy decomposition: Brier = reliability - resolution + uncertainty.

    Reliability is the calibration term (lower better) and is the quantity that
    actually determines profitability when trading binary contracts.
    """
    f = np.asarray(forecasts, dtype=float)
    o = np.asarray(outcomes, dtype=float)
    base = o.mean()
    unc = base * (1 - base)
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(f, edges[1:-1]), 0, n_bins - 1)
    rel = res = 0.0
    n = len(f)
    for b in range(n_bins):
        m = idx == b
        k = m.sum()
        if k == 0:
            continue
        fbar, obar = f[m].mean(), o[m].mean()
        rel += k * (fbar - obar) ** 2
        res += k * (obar - base) ** 2
    return {"brier": brier_score(f, o), "reliability": rel / n,
            "resolution": res / n, "uncertainty": unc}
