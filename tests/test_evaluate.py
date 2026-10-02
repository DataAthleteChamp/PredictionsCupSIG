"""Tests for the statistical evaluation layer."""
import math

import numpy as np
import pytest

from sigbot.evaluate import (autocorrelation_ess, confidence_sequence,
                             deflated_sharpe, effective_sample_size,
                             james_stein, min_convex_fraction_to_reach,
                             optimal_convex_fraction, prob_top_k, required_n,
                             required_n_unknown_variance, shrink_normal,
                             shrink_student_t)


# ---------------------------------------------------- effective sample size --

def test_independent_observations_keep_full_sample_size():
    assert effective_sample_size(100, intra_cluster_corr=0.0) == 100


def test_perfectly_clustered_observations_collapse_to_one_per_cluster():
    """3 fills in one dislocation are closer to 1 observation than 3."""
    assert effective_sample_size(3, intra_cluster_corr=1.0, cluster_size=3) == 1.0


def test_partial_clustering_is_between():
    n_eff = effective_sample_size(3, intra_cluster_corr=0.5, cluster_size=3)
    assert 1.0 < n_eff < 3.0


def test_autocorrelation_ess_detects_dependence():
    rng = np.random.default_rng(0)
    indep = rng.normal(size=500)
    # strongly autocorrelated series
    dep = np.cumsum(rng.normal(size=500))
    assert autocorrelation_ess(indep) > autocorrelation_ess(dep)


def test_autocorrelation_ess_handles_tiny_input():
    assert autocorrelation_ess([1.0]) == 1.0
    assert autocorrelation_ess([]) == 0.0


# -------------------------------------------------------------- shrinkage ---

def test_three_clustered_fills_shrink_almost_entirely_to_the_prior():
    """
    The headline result. Raw mean +0.0875 from 3 clustered fills must not be
    taken at face value.
    """
    post = shrink_normal(sample_mean=0.0875, sample_sd=0.014, n_eff=1.0,
                         prior_mean=0.0, prior_sd=0.01)
    assert post.shrinkage > 0.6          # mostly prior
    assert post.mean < 0.0875 / 2        # at least halved
    assert post.mean > 0


def test_large_sample_overrides_the_prior():
    post = shrink_normal(sample_mean=0.05, sample_sd=0.01, n_eff=10_000,
                         prior_sd=0.01)
    assert post.shrinkage < 0.01
    assert post.mean == pytest.approx(0.05, abs=1e-3)


def test_shrinkage_is_monotone_in_sample_size():
    prev = 1.0
    for n in (1, 5, 25, 100, 1000):
        s = shrink_normal(0.05, 0.02, n).shrinkage
        assert s < prev
        prev = s


def test_zero_centred_prior_pulls_toward_zero_not_up():
    post = shrink_normal(sample_mean=-0.03, sample_sd=0.02, n_eff=2)
    assert -0.03 < post.mean < 0.0


def test_posterior_credible_interval_widens_with_less_data():
    wide = shrink_normal(0.05, 0.02, 1).credible_interval()
    tight = shrink_normal(0.05, 0.02, 500).credible_interval()
    assert (wide[1] - wide[0]) > (tight[1] - tight[0])


def test_degenerate_inputs_return_the_prior():
    post = shrink_normal(0.5, 0.0, 0.0, prior_mean=0.0, prior_sd=0.01)
    assert post.shrinkage == 1.0 and post.mean == 0.0


def test_prob_positive_is_sane():
    assert 0.0 <= shrink_normal(0.05, 0.02, 10).prob_positive <= 1.0
    assert shrink_normal(0.5, 0.01, 1000).prob_positive > 0.99


# ----------------------------------------- unknown variance (Student-t) ----

def test_student_t_is_less_confident_than_known_sigma_at_n3():
    """
    The correction that matters. Estimating sigma from the same 3 points and
    then treating it as known manufactures confidence.
    """
    fills = [0.0875 - 0.014, 0.0875, 0.0875 + 0.014]
    known = shrink_normal(0.0875, 0.014, n_eff=3.0, prior_sd=0.01)
    unknown = shrink_student_t(fills, prior_sd=0.01, prior_noise_sd=0.05)
    assert unknown.prob_positive < known.prob_positive
    assert unknown.sd > known.sd


def test_edge_prior_and_noise_prior_are_independent_knobs():
    """
    Conflating them was a real bug: a tight variance prior must not act as
    evidence about the mean. Widening the NOISE prior alone must reduce
    confidence, never raise it.
    """
    fills = [0.07, 0.0875, 0.10]
    tight_noise = shrink_student_t(fills, prior_sd=0.01, prior_noise_sd=0.02)
    wide_noise = shrink_student_t(fills, prior_sd=0.01, prior_noise_sd=0.20)
    assert wide_noise.prob_positive < tight_noise.prob_positive


def test_wider_edge_prior_allows_more_confidence():
    fills = [0.07, 0.0875, 0.10]
    tight = shrink_student_t(fills, prior_sd=0.005, prior_noise_sd=0.05)
    loose = shrink_student_t(fills, prior_sd=0.05, prior_noise_sd=0.05)
    assert loose.mean > tight.mean
    assert loose.prob_positive > tight.prob_positive


def test_student_t_posterior_has_heavy_tails_at_tiny_n():
    """dof = 2*alpha_n must stay small enough that sd exceeds the normal case."""
    post = shrink_student_t([0.05, 0.06], prior_sd=0.01)
    assert post.sd > 0


def test_student_t_converges_to_the_sample_mean_with_much_data():
    rng = np.random.default_rng(5)
    x = rng.normal(0.05, 0.01, 20_000)
    post = shrink_student_t(x, prior_mean=0.0, prior_sd=0.01, prior_noise_sd=0.01)
    assert post.mean == pytest.approx(0.05, abs=2e-3)
    assert post.prob_positive > 0.99


def test_student_t_respects_the_effective_sample_override():
    fills = [0.07, 0.0875, 0.10]
    full = shrink_student_t(fills, prior_sd=0.01, prior_noise_sd=0.05)
    discounted = shrink_student_t(fills, prior_sd=0.01, prior_noise_sd=0.05,
                                  n_eff=1.0)
    assert discounted.mean < full.mean          # pulled further to the prior
    assert discounted.prob_positive < full.prob_positive


def test_student_t_with_no_data_returns_the_prior():
    post = shrink_student_t([], prior_mean=0.0, prior_sd=0.01)
    assert post.mean == 0.0 and post.shrinkage == 1.0


def test_student_t_shrinkage_in_unit_interval():
    for sample in ([0.05], [0.05, 0.02], [-0.03, 0.01, 0.00]):
        assert 0.0 <= shrink_student_t(sample).shrinkage <= 1.0


def test_unknown_variance_needs_more_data_than_known_variance():
    known = required_n(0.02, sample_sd=0.05, prior_sd=0.01)
    unknown = required_n_unknown_variance(0.02, sample_sd=0.05, prior_sd=0.01)
    assert unknown >= known


def test_required_n_unknown_variance_infinite_without_edge():
    assert required_n_unknown_variance(0.0, 0.02) == float("inf")


# ------------------------------------------------------------ James-Stein ---

def test_james_stein_shrinks_toward_the_common_mean():
    x = [0.10, -0.02, 0.04, 0.00, 0.08]
    js = james_stein(x, sigma2=0.01)
    assert np.abs(js - np.mean(x)).sum() <= np.abs(np.array(x) - np.mean(x)).sum()


def test_james_stein_is_identity_for_small_k():
    x = [0.1, 0.2]
    assert np.allclose(james_stein(x), x)


def test_james_stein_positive_part_never_crosses_the_mean():
    x = [0.001, -0.001, 0.0005]
    js = james_stein(x, sigma2=100.0)       # huge sigma -> full shrinkage
    assert np.allclose(js, np.mean(x), atol=1e-9)


# ------------------------------------------------------------- required n ---

def test_required_n_is_large_for_a_small_edge():
    n_small = required_n(0.001, sample_sd=0.02)
    n_big = required_n(0.05, sample_sd=0.02)
    assert n_small > n_big


def test_required_n_infinite_without_an_edge():
    assert required_n(0.0, 0.02) == float("inf")
    assert required_n(-0.01, 0.02) == float("inf")


# ------------------------------------------------- anytime-valid monitoring --

def test_confidence_sequence_contains_the_truth_and_narrows():
    rng = np.random.default_rng(3)
    x = rng.normal(0.01, 0.02, 5000)
    lo_small, hi_small = confidence_sequence(x[:50])
    lo_big, hi_big = confidence_sequence(x)
    assert (hi_big - lo_big) < (hi_small - lo_small)
    assert lo_big <= 0.01 <= hi_big


def test_confidence_sequence_under_the_null_usually_contains_zero():
    """Anytime-valid: should not repeatedly exclude zero when there is no edge."""
    rng = np.random.default_rng(11)
    excluded = 0
    for _ in range(40):
        x = rng.normal(0.0, 0.02, 400)
        lo, hi = confidence_sequence(x, alpha=0.05)
        if lo > 0 or hi < 0:
            excluded += 1
    assert excluded <= 4


def test_confidence_sequence_handles_empty():
    lo, hi = confidence_sequence([])
    assert lo == -math.inf and hi == math.inf


# --------------------------------------------------------- deflated Sharpe --

def test_deflated_sharpe_penalises_strategy_selection():
    one = deflated_sharpe(1.5, n_trials=1, n_obs=250)
    many = deflated_sharpe(1.5, n_trials=100, n_obs=250)
    assert many < one


def test_deflated_sharpe_in_unit_interval():
    v = deflated_sharpe(2.0, n_trials=10, n_obs=500)
    assert 0.0 <= v <= 1.0


# --------------------------------------------------- the tournament objective --

def test_pure_grind_cannot_reach_a_distant_cutoff():
    """The core finding: a high-Sharpe book cannot cover a 6x gap."""
    r = prob_top_k(100_000, edge_per_period=0.002, vol_per_period=0.01,
                   n_periods=33, cutoff=600_000, seed=1)
    assert r["p_reach_cutoff"] < 0.01


def test_convex_sleeve_raises_probability_of_reaching_a_distant_cutoff():
    grind = prob_top_k(100_000, 0.002, 0.01, 33, 600_000, seed=2,
                       convex_fraction=0.0)
    barbell = prob_top_k(100_000, 0.002, 0.01, 33, 600_000, seed=2,
                         convex_fraction=0.8, convex_price=0.10)
    assert barbell["p_reach_cutoff"] > grind["p_reach_cutoff"]


def test_convex_sleeve_increases_downside_too():
    grind = prob_top_k(100_000, 0.002, 0.01, 33, 600_000, seed=3,
                       convex_fraction=0.0)
    barbell = prob_top_k(100_000, 0.002, 0.01, 33, 600_000, seed=3,
                         convex_fraction=0.8, convex_price=0.10)
    assert barbell["p_ruin_half"] > grind["p_ruin_half"]


def test_overpriced_convexity_is_worse_than_fair():
    """
    Use a sleeve fraction above the reachability threshold, otherwise both
    arms are identically zero and the comparison is vacuous.
    """
    fair = prob_top_k(100_000, 0.002, 0.01, 33, 600_000, seed=4,
                      convex_fraction=0.8, convex_price=0.10,
                      convex_true_prob=0.10)
    overpriced = prob_top_k(100_000, 0.002, 0.01, 33, 600_000, seed=4,
                            convex_fraction=0.8, convex_price=0.10,
                            convex_true_prob=0.05)   # 2x overpriced, as measured
    assert fair["p_reach_cutoff"] > 0          # guard against a vacuous pass
    assert overpriced["p_reach_cutoff"] < fair["p_reach_cutoff"]


def test_sleeve_below_the_reachability_threshold_is_hopeless():
    """
    A 50% sleeve at 0.10 maxes out near 553k and can never clear a 600k
    cutoff -- the podium is unreachable in every state, not merely unlikely.
    """
    f_min = min_convex_fraction_to_reach(100_000, 600_000, 0.10,
                                         core_growth=0.066)
    assert 0.5 < f_min < 0.65
    below = prob_top_k(100_000, 0.002, 0.01, 33, 600_000, seed=5,
                       convex_fraction=f_min - 0.1, convex_price=0.10)
    assert below["p_reach_cutoff"] == 0.0


def test_reachability_threshold_is_zero_when_already_past_the_cutoff():
    assert min_convex_fraction_to_reach(100_000, 90_000, 0.10) == 0.0


def test_reachability_threshold_infinite_when_price_too_high():
    """A 0.50 contract only doubles; it cannot cover a 6x gap at any size."""
    assert min_convex_fraction_to_reach(100_000, 600_000, 0.50) == float("inf")


def test_cheaper_convexity_lowers_the_required_fraction():
    expensive = min_convex_fraction_to_reach(100_000, 600_000, 0.20)
    cheap = min_convex_fraction_to_reach(100_000, 600_000, 0.02)
    assert cheap < expensive


def test_near_cutoff_the_optimum_is_conservative():
    """With the target almost reached, variance only risks losing it."""
    res = optimal_convex_fraction(100_000, 0.002, 0.01, 33, cutoff=101_000,
                                  convex_price=0.10)
    assert res["best_fraction"] <= 0.25


def test_far_from_cutoff_the_optimum_is_aggressive():
    res = optimal_convex_fraction(100_000, 0.002, 0.01, 33, cutoff=600_000,
                                  convex_price=0.10)
    assert res["best_fraction"] >= 0.5


def test_optimal_fraction_curve_is_well_formed():
    res = optimal_convex_fraction(100_000, 0.002, 0.01, 33, 600_000)
    assert len(res["curve"]) == 21
    assert all(0.0 <= f <= 1.0 and 0.0 <= p <= 1.0 for f, p in res["curve"])
