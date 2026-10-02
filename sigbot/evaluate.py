"""
Statistical evaluation of a trading edge.

Why this module exists: we had **3 fills** on the ladder with a raw mean markout
of +0.0875/share, all clustered in one overnight window. Acting on that number
would have been a mistake twice over -- the sample was far too small, and the
number itself turned out to be an artifact of a frame bug (algos.markout scored
NO fill prices against YES mids). This module makes both failure modes visible
rather than arguable.

Three things it does:

1. **Bayesian shrinkage.** A normal-normal hierarchical model pulls a small,
   noisy sample toward a prior centred on zero edge. With n_eff ≈ 1 the
   posterior is almost entirely prior.
2. **Dependence-aware sample size.** Fills cluster during dislocations, so the
   honest sample size is far below the raw count.
3. **Anytime-valid monitoring.** Confidence sequences let us watch a running
   mean continuously without the false-positive inflation of repeatedly peeking
   at a fixed-sample p-value.

Plus a Monte Carlo of the actual objective: P(finishing top-3), which is what
the payoff depends on — not expected wealth and not Sharpe.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats


# ------------------------------------------------------ effective sample ----

def effective_sample_size(n: int, intra_cluster_corr: float = 0.0,
                          cluster_size: float = 1.0) -> float:
    """
    Design effect: n_eff = n / (1 + (m - 1) * rho).

    With m observations per cluster and intra-cluster correlation rho, clustered
    observations carry less information than independent ones. Three fills that
    all occurred in one dislocation are closer to ONE observation than three.
    """
    if n <= 0:
        return 0.0
    deff = 1.0 + (max(cluster_size, 1.0) - 1.0) * max(0.0, intra_cluster_corr)
    return n / deff


def autocorrelation_ess(x) -> float:
    """
    Effective sample size from the autocorrelation function:
        n_eff = n / (1 + 2 * sum_k rho_k)
    Truncated at the first non-positive autocorrelation (initial positive
    sequence rule).
    """
    a = np.asarray(x, dtype=float)
    n = len(a)
    if n < 3:
        return float(n)
    a = a - a.mean()
    denom = float(np.dot(a, a))
    if denom <= 0:
        return float(n)
    total = 0.0
    for k in range(1, min(n - 1, 50)):
        rho = float(np.dot(a[:-k], a[k:])) / denom
        if rho <= 0:
            break
        total += rho
    return max(1.0, n / (1.0 + 2.0 * total))


# ------------------------------------------------------ Bayesian shrinkage --

@dataclass(frozen=True)
class Posterior:
    mean: float
    sd: float
    shrinkage: float          # 1.0 = entirely prior, 0.0 = entirely data
    n_eff: float
    prob_positive: float

    def credible_interval(self, level: float = 0.95) -> tuple[float, float]:
        z = stats.norm.ppf(0.5 + level / 2)
        return (self.mean - z * self.sd, self.mean + z * self.sd)


def shrink_normal(sample_mean: float, sample_sd: float, n_eff: float,
                  prior_mean: float = 0.0, prior_sd: float = 0.01) -> Posterior:
    """
    Normal-normal conjugate update.

        precision_data  = n_eff / sigma^2
        precision_prior = 1 / tau^2
        posterior_mean  = (prec_d * xbar + prec_p * mu0) / (prec_d + prec_p)
        shrinkage       = prec_p / (prec_d + prec_p)

    The prior defaults to mean 0 — "an arbitrary passive quoting rule has no
    edge" — with a tight scale, because Glosten-Milgrom says the default
    outcome of quoting is to lose to informed flow, not to break even.
    """
    if n_eff <= 0 or sample_sd <= 0:
        return Posterior(prior_mean, prior_sd, 1.0, max(n_eff, 0.0),
                         float(stats.norm.sf(0, prior_mean, prior_sd)))
    prec_d = n_eff / (sample_sd ** 2)
    prec_p = 1.0 / (prior_sd ** 2)
    post_prec = prec_d + prec_p
    mean = (prec_d * sample_mean + prec_p * prior_mean) / post_prec
    sd = math.sqrt(1.0 / post_prec)
    return Posterior(mean=mean, sd=sd, shrinkage=prec_p / post_prec, n_eff=n_eff,
                     prob_positive=float(stats.norm.sf(0.0, mean, sd)))


def james_stein(means, overall_mean: float | None = None,
                sigma2: float = 1.0) -> np.ndarray:
    """
    James-Stein shrinkage toward a common mean.

        JS_i = mu + (1 - (k-2)*sigma^2 / sum((x_i - mu)^2)) * (x_i - mu)

    Dominates the sample mean in total squared error for k >= 3. Use for
    per-bucket edges (we estimate one per price bucket) rather than for a
    single number.
    """
    x = np.asarray(means, dtype=float)
    k = len(x)
    mu = float(x.mean()) if overall_mean is None else overall_mean
    if k < 3:
        return x.copy()
    ss = float(((x - mu) ** 2).sum())
    if ss <= 0:
        return x.copy()
    factor = max(0.0, 1.0 - (k - 2) * sigma2 / ss)      # positive-part JS
    return mu + factor * (x - mu)


def shrink_student_t(samples, prior_mean: float = 0.0, prior_sd: float = 0.01,
                     prior_noise_sd: float = 0.05, prior_dof: float = 2.0,
                     n_eff: float | None = None) -> Posterior:
    """
    Normal-inverse-gamma update: the honest small-sample model.

    `shrink_normal` assumes sigma is KNOWN. When sigma is estimated from the
    same handful of points, that assumption manufactures confidence that is not
    there -- with 3 fills it will happily report P(edge>0) = 1.000. Treating the
    variance as unknown yields a Student-t posterior whose heavy tails survive
    small n.

    Two genuinely different scales must stay separate:

      * `prior_sd`       -- prior scale on the EDGE (how big a mean is credible)
      * `prior_noise_sd` -- prior scale of per-fill NOISE (how scattered fills are)

    Tying them together is a modelling error: it makes a tight variance prior
    masquerade as evidence about the mean. The prior strength in pseudo-
    observations follows from their ratio,

        kappa_0 = (prior_noise_sd / prior_sd)^2

    so claiming "an edge of 0.01 is credible while fills scatter by 0.05"
    automatically demands ~25 observations' worth of evidence to be moved.

        mu | data ~ t_{2*alpha_n}(mu_n, beta_n / (alpha_n * kappa_n))

    `n_eff` overrides the raw count so clustered fills can be discounted.
    """
    x = np.asarray(list(samples), dtype=float)
    n_raw = len(x)
    if n_raw == 0:
        return Posterior(prior_mean, prior_sd, 1.0, 0.0,
                         float(stats.norm.sf(0, prior_mean, prior_sd)))
    n = float(n_raw if n_eff is None else n_eff)
    xbar = float(x.mean())
    ss = float(((x - xbar) ** 2).sum())
    if n_eff is not None and n_raw > 1:
        ss *= n / n_raw                       # scale SS with the discount

    noise = max(prior_noise_sd, 1e-12)
    k0 = (noise / max(prior_sd, 1e-12)) ** 2  # prior strength in observations
    a0 = max(prior_dof / 2.0, 0.5)
    b0 = a0 * noise ** 2                      # InvGamma centred on the noise

    kn = k0 + n
    mn = (k0 * prior_mean + n * xbar) / kn
    an = a0 + n / 2.0
    bn = b0 + ss / 2.0 + (k0 * n * (xbar - prior_mean) ** 2) / (2.0 * kn)

    dof = 2.0 * an
    scale = math.sqrt(max(bn / (an * kn), 1e-18))
    sd = scale * math.sqrt(dof / (dof - 2.0)) if dof > 2 else float("inf")
    shrink = (1.0 - (mn - prior_mean) / (xbar - prior_mean)) if xbar != prior_mean else 1.0
    return Posterior(
        mean=mn,
        sd=sd,
        shrinkage=min(max(shrink, 0.0), 1.0),
        n_eff=n,
        prob_positive=float(stats.t.sf(0.0, dof, loc=mn, scale=scale)),
    )


def required_n(target_edge: float, sample_sd: float, prior_sd: float = 0.01,
               want_prob_positive: float = 0.95) -> float:
    """
    How many INDEPENDENT observations before the posterior is confident the
    edge is positive, given a zero-centred prior.

    NOTE: assumes sigma is known. If sigma was estimated from a handful of the
    same observations this is optimistic -- use `required_n_unknown_variance`.
    """
    if target_edge <= 0 or sample_sd <= 0:
        return float("inf")
    z = stats.norm.ppf(want_prob_positive)
    prec_p = 1.0 / prior_sd ** 2
    for n in range(1, 2_000_001):
        prec_d = n / sample_sd ** 2
        post_prec = prec_d + prec_p
        mean = (prec_d * target_edge) / post_prec
        if mean / math.sqrt(1.0 / post_prec) >= z:
            return float(n)
    return float("inf")


def required_n_unknown_variance(target_edge: float, sample_sd: float,
                                prior_sd: float = 0.01,
                                want_prob_positive: float = 0.95,
                                max_n: int = 100_000) -> float:
    """
    Same question as `required_n`, but under the Student-t posterior where the
    variance is estimated rather than assumed. Always >= the known-sigma
    answer, and far larger at small n where the heavy tails dominate.

    Evaluated on an idealised sample whose mean is `target_edge` and whose
    sample sd is `sample_sd`, so it isolates sample size from sampling luck.
    """
    if target_edge <= 0 or sample_sd <= 0:
        return float("inf")
    n = 2
    while n <= max_n:
        # synthetic sample with exactly the stated mean and sd
        half = sample_sd * math.sqrt((n - 1) / n)
        x = np.full(n, target_edge)
        x[: n // 2] -= half
        x[n // 2:] += half * (n // 2) / max(1, n - n // 2)
        x = x - x.mean() + target_edge
        post = shrink_student_t(x, prior_mean=0.0, prior_sd=prior_sd,
                                prior_noise_sd=sample_sd)
        if post.prob_positive >= want_prob_positive:
            return float(n)
        n = n + 1 if n < 50 else int(n * 1.15) + 1
    return float("inf")


# ------------------------------------------------- anytime-valid monitoring --

def confidence_sequence(x, alpha: float = 0.05) -> tuple[float, float]:
    """
    Time-uniform confidence interval for a running mean (sub-Gaussian
    normal-mixture bound). Valid at ALL sample sizes simultaneously, so it can
    be checked continuously.

    Repeatedly checking a fixed-sample p-value and stopping when it dips below
    0.05 does NOT control error — under the null it eventually crosses with
    probability 1. This bound does.
    """
    a = np.asarray(x, dtype=float)
    n = len(a)
    if n == 0:
        return (-math.inf, math.inf)
    s = float(a.std(ddof=1)) if n > 1 else 1.0
    if s <= 0:
        s = 1e-9
    rho = 1.0
    width = s * math.sqrt(
        2.0 * (n * rho + 1.0) / (n ** 2 * rho)
        * math.log(math.sqrt(n * rho + 1.0) / alpha))
    m = float(a.mean())
    return (m - width, m + width)


def deflated_sharpe(observed_sharpe: float, n_trials: int, n_obs: int,
                    skew: float = 0.0, kurt: float = 3.0) -> float:
    """
    Probability the observed Sharpe exceeds what the BEST of `n_trials` random
    strategies would produce by chance (Bailey & Lopez de Prado).

    We tested several placement distances and reported the best. That is
    selection bias and must be penalised.
    """
    if n_trials < 1 or n_obs < 2:
        return float("nan")
    e = 0.5772156649
    maxz = ((1 - e) * stats.norm.ppf(1 - 1.0 / n_trials)
            + e * stats.norm.ppf(1 - 1.0 / (n_trials * math.e)))
    denom = math.sqrt(max(1e-12,
                          1 - skew * observed_sharpe
                          + (kurt - 1) / 4 * observed_sharpe ** 2))
    return float(stats.norm.cdf(
        (observed_sharpe - maxz) * math.sqrt(n_obs - 1) / denom))


# ------------------------------------------------------- the real objective --

def prob_top_k(current_equity: float, edge_per_period: float,
               vol_per_period: float, n_periods: int, cutoff: float,
               n_sims: int = 50_000, seed: int | None = None,
               convex_fraction: float = 0.0, convex_price: float = 0.10,
               convex_true_prob: float | None = None) -> dict:
    """
    Monte Carlo of P(final equity >= cutoff) — the quantity the prize actually
    depends on. Expected wealth and Sharpe are both the wrong objective under a
    step-function payoff.

    A `convex_fraction` of capital may be allocated to a binary paying 1/price
    with probability `convex_true_prob` (defaults to the price, i.e. fairly
    priced). This lets us compare a pure grind against a barbell directly.
    """
    rng = np.random.default_rng(seed)
    core = current_equity * (1.0 - convex_fraction)
    sleeve = current_equity * convex_fraction

    drift = edge_per_period * n_periods
    diffusion = vol_per_period * math.sqrt(n_periods)
    core_final = core * (1.0 + rng.normal(drift, diffusion, n_sims))
    core_final = np.maximum(core_final, 0.0)

    if sleeve > 0:
        p = convex_price if convex_true_prob is None else convex_true_prob
        wins = rng.random(n_sims) < p
        sleeve_final = np.where(wins, sleeve / convex_price, 0.0)
    else:
        sleeve_final = np.zeros(n_sims)

    final = core_final + sleeve_final
    return {
        "p_reach_cutoff": float((final >= cutoff).mean()),
        "median_final": float(np.median(final)),
        "mean_final": float(final.mean()),
        "p_ruin_half": float((final < current_equity * 0.5).mean()),
        "cutoff": cutoff,
    }


def min_convex_fraction_to_reach(current_equity: float, cutoff: float,
                                 convex_price: float,
                                 core_growth: float = 0.0) -> float:
    """
    Smallest sleeve fraction for which the cutoff is reachable AT ALL.

    Maximum attainable wealth with fraction f, if the sleeve wins, is

        W_max(f) = E*(1-f)*(1+g) + E*f/price

    Solving W_max(f) >= cutoff gives

        f >= (cutoff/E - (1+g)) / (1/price - (1+g))

    Below this fraction the podium is unreachable in EVERY state of the world,
    so the trade is not merely unlikely — it is impossible. Returns inf when no
    fraction suffices (the sleeve price is too high for the gap).
    """
    if current_equity <= 0 or not (0 < convex_price < 1):
        return float("inf")
    g = 1.0 + core_growth
    need = cutoff / current_equity
    if need <= g:
        return 0.0
    denom = (1.0 / convex_price) - g
    if denom <= 0:
        return float("inf")
    f = (need - g) / denom
    return f if f <= 1.0 else float("inf")


def optimal_convex_fraction(current_equity: float, edge_per_period: float,
                            vol_per_period: float, n_periods: int,
                            cutoff: float, convex_price: float = 0.10,
                            convex_true_prob: float | None = None,
                            grid: int = 21, seed: int | None = 7) -> dict:
    """
    Sweep the sleeve fraction and report the allocation maximising P(top-k).

    This is the barbell sizing question answered numerically rather than by
    appeal to intuition.
    """
    best = None
    curve = []
    for i in range(grid):
        f = i / (grid - 1)
        r = prob_top_k(current_equity, edge_per_period, vol_per_period,
                       n_periods, cutoff, n_sims=20_000, seed=seed,
                       convex_fraction=f, convex_price=convex_price,
                       convex_true_prob=convex_true_prob)
        curve.append((f, r["p_reach_cutoff"]))
        if best is None or r["p_reach_cutoff"] > best[1]:
            best = (f, r["p_reach_cutoff"])
    return {"best_fraction": best[0], "best_prob": best[1], "curve": curve}
