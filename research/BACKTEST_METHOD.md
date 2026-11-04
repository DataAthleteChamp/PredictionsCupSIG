Agent is idle (waiting for messages). agent_id: e5785160-8dca-4511-bde9-10398046f090, agent_type: research, status: idle, description: Backtesting methodology for market making, elapsed: 1279s, total_turns: 1

[Turn 0]
**ov (2017)** show execution probability is governed by P(order flow ≥ queue ahead of you) — a naive "touch = fill" rule implicitly sets queue-ahead to zero for every order, which is the most optimistic possible assumption in a FIFO market, and the bias this introduces scales with how deep the queue typically is at your quoted distance. That's a direction and a mechanism, not a number.

**What I recommend instead of borrowing someone else's figure:** compute your own bias directly. You have ~2,300 real fills. Run the optimistic rule and the conservative rule over the *same* historical order log and compare each to your realized fill count and P&L. The gap between the two bounds, benchmarked against your actual fills, **is** your overstatement factor — specific to your tick size, your markets, and your quoting distance — and it is strictly more trustworthy than any number from a different market structure. Treat the published "5–10×" claims as a plausibility prior (expect the bias to be large and in the optimistic direction), not as a quantity to adopt.

---

## 2. Validating a backtest against live results

### Calibrate, then validate — on disjoint data

The single most important discipline here is **never calibrate and validate on the same fills**. Concretely:

1. **Split your 2,300 fills by time**, not randomly — e.g., first 70% by calendar date for calibration, last 30% held out. A random split leaks information because fills are autocorrelated (Section 3); a time split also tests whether your fill model survives regime drift, which is the realistic failure mode in production.
2. **Fit the Cox hazard model (or the Avellaneda-Stoikov λ(δ) curve) on the calibration set**, including every canceled/repriced order as a censored observation, not just the fills — fitting on fills-only massively overstates fill probability (survivorship: you only see the orders that *did* fill).
3. **Generate simulated fills over the held-out period** by replaying your actual historical order log (prices, sizes, timestamps you really posted) through the fitted model, and compare simulated outcomes against the real fills that occurred in that same held-out window.
4. Repeat the split **by market** as a second, orthogonal check (train on ~56 of your ~80 markets, test on the other ~24) — this tests whether the model generalizes across markets rather than overfitting to the idiosyncrasies of a few liquid ones.

### Metrics that must match between sim and live

| Metric | What to compare | Why it catches optimism |
|---|---|---|
| **Fill rate per order-hour** | Simulated fills/hour vs. realized fills/hour, bucketed by distance-to-mid (ticks) | An optimistic sim will systematically show higher fill rate per bucket, especially at 4–6 ticks where real queues are long |
| **Fill price distribution** | KS test of simulated vs. realized distribution of (fill price − mid-at-post-time) | Naive sims cluster fills unrealistically close to the touch |
| **Markout curve** | Mean (and CI) of price change at 1 min, 5 min, 30 min after each fill, sim vs. live, following the impulse-response/markout methodology of **Hasbrouck (1991), "Measuring the Information Content of Stock Trades,"** *Journal of Finance* 46(1), 179–207 | This is the sharpest diagnostic: an optimistic sim fills you indiscriminately, including during informed/toxic flow, so its markout curve will look *better* than reality (less adverse selection) rather than worse — counterintuitively, a too-rosy markout curve is itself evidence of an optimistic simulator, not evidence of a good strategy |
| **Inventory path** | Simulated running inventory vs. realized running inventory over the same calendar window | Divergence here reveals compounding errors — e.g., a sim that over-fills one side will show an inventory path that drifts in a direction the real book never did |

### Detecting optimism before you trust the simulator

Three concrete tests, in order of diagnostic power:

1. **Conditional markout test** (the most important one): compare the markout of *simulated* fills against the markout of *real* fills, split by distance-to-mid bucket. If sim markout is less negative (less adverse-selected) than live markout at the same bucket, your sim is filling you too easily during exactly the moments a real queue would have protected you — this is the signature of optimism, not of a better model.
2. **Fill-rate monotonicity check**: fill rate must decrease with distance from mid in both sim and live, and the *rate of decay* should roughly match (this is literally re-deriving the Avellaneda-Stoikov k parameter from two independent samples and checking they agree).
3. **Backtest-vs-live P&L ratio over the validation window**: if simulated P&L exceeds realized P&L by a wide margin even after calibration, treat that gap as a standing, unexplained liability on every future backtest number until you can attribute it to a specific mechanism (queue priority, latency, adverse selection) rather than writing it off as noise.

---

## 3. Statistical power and overfitting

### How many fills to detect a 20% improvement

This is a standard two-sample (or one-sample) comparison-of-means power calculation. Let σ = 0.02 (per-fill SD), baseline edge μ₀ = 0.002, and a 20% relative improvement, i.e., Δ = 0.2 × 0.002 = **0.0004**.

**Standardized effect size:** d = Δ/σ = 0.0004/0.02 = **0.02** — by any conventional yardstick (Cohen's small = 0.2) this is a *tiny* effect, ten times smaller than the "small effect" benchmark.

**One-sample framing** (new config vs. a known, fixed historical constant):
n = (z₁₋α/2 + z₁₋β)² σ² / Δ²

With two-sided α = 0.05 (z = 1.96) and power 80% (z = 0.8416):
n = (1.96 + 0.8416)² × (0.02)² / (0.0004)² = 7.849 × 2500 = **≈19,600 fills**

**Two-sample / A-B framing** (both configs' edges estimated from data, equal allocation — the realistic case):
n_per_arm = 2(z₁₋α/2 + z₁₋β)² σ² / Δ² = 2 × 7.849 × 2500 = **≈39,250 per arm, ≈78,500 total**

At 90% power (z = 1.2816), these numbers rise to ~26,300 (one-sample) and ~105,000 (two-sample total).

(As a sanity check, this matches the standard biostatistics shorthand **n ≈ 16σ²/Δ² per arm** for 80%-power two-sided tests — **Lehr, M.L. (1992), "Sixteen S-squared over D-squared," *Statistics in Medicine* 11(8), 1099–1102** — 16 × 2500 = 40,000, consistent with the 39,250 above.)

**The reconciling insight that matters practically:** it is comparatively *easy* to confirm your baseline strategy has *some* nonzero edge — that's effect size 0.002/0.02 = 0.1, requiring only ~785–1,570 fills (one-/two-sample), which you plausibly already have close to. It is an order of magnitude *harder* to tell whether a tweak improved that edge by 20%, because the improvement itself (0.0004) is a small fraction of an already-small effect while the noise floor (0.02) stays fixed. **You have 2,300 fills. You need ~78,500 for this specific comparison. You are underpowered by roughly 34×, before any clustering correction.**

### Effective sample size under autocorrelation and cross-sectional correlation

Your fills violate the iid assumption two ways simultaneously: temporal clustering (fills bunch up in dislocations) and cross-sectional clustering (shared national factor across markets). The standard tool is **Kish's design effect**:

DEFF = 1 + (m − 1)ρ,  effective N = raw N / DEFF

— **Kish, L. (1965), *Survey Sampling*, Wiley** — generalized to two simultaneous clustering dimensions (time-event and market/day) via:

- **Petersen, M.A. (2009), "Estimating Standard Errors in Finance Panel Data Sets: Comparing Approaches,"** *Review of Financial Studies* 22(1), 435–480 — the standard finance reference showing that ignoring within-cluster correlation (by firm, or by time) typically understates standard errors by a factor of 2–10× in ordinary finance panel data.
- **Cameron, Gelbach & Miller (2011), "Robust Inference with Multiway Clustering,"** *Journal of Business & Economic Statistics* 29(2), 238–249 — the formal extension to *two* non-nested clustering dimensions, exactly your situation (dislocation-event clustering × market/day clustering).

**Illustrative calculation** (I want to be explicit these ρ values are assumptions you must estimate from your own data, not literature-derived constants): if an average dislocation event produces m₁ = 8 correlated fills at ρ₁ = 0.4, DEFF₁ = 1 + 7×0.4 = 3.8. If a shared national-factor day correlates fills across m₂ = 15 markets at ρ₂ = 0.2, DEFF₂ = 1 + 14×0.2 = 3.8. Treating these as roughly multiplicative (a common approximation for crossed, not nested, clustering — not exact, but directionally right): combined DEFF ≈ 3.8 × 3.8 ≈ **14.4**. Your 2,300 raw fills become an **effective N of roughly 160**. To reach the 78,500 effective fills needed for the 20%-detection test, you'd need **≈1.13 million raw fills** — roughly **490× your current count**.

**How to actually estimate your true ρ/DEFF** (not just assume it): fit a mixed-effects model with random intercepts for dislocation-event ID and market/day on per-fill markout, and read off variance components; or, more robustly, run a **block bootstrap** that resamples whole dislocation-events or whole market-days (never individual fills) and compare the resulting SE to the naive iid SE — the squared ratio of these two SEs *is* your empirical design effect. Methodological root: **Künsch (1989), "The jackknife and the bootstrap for general stationary observations,"** *Annals of Statistics* 17(3), 1217–1241, and **Politis & Romano (1994), "The Stationary Bootstrap,"** *JASA* 89(428), 1303–1313.

**The literature does not give you a single "typical" multiplier for this exact situation** — it's application-specific and you must estimate it. What the finance-panel literature does support is that 5–20× reductions in effective N are common once both dimensions are accounted for, which is consistent with (and motivates) the illustrative ~14× above.

### Multiple-testing correction for 15–20 variants

Two complementary, both well-established corrections:

**Simple threshold (Bonferroni-style):** with ~18 variants tested, family-wise α = 0.05 implies per-comparison α' = 0.05/18 ≈ 0.0028, two-sided z ≈ 2.98. This lines up almost exactly with:

- **Harvey, Liu & Zhu (2016), "…and the Cross-Section of Expected Returns,"** *Review of Financial Studies* 29(1), 5–68 — recommend a **t-statistic > 3.0** threshold for any newly "discovered" factor/strategy, specifically because of the multiple-testing problem in a field that has tried hundreds of variants.
- **Harvey & Liu (2015), "Backtesting,"** *Journal of Portfolio Management* 42(1), 13–28 — the companion "haircut Sharpe ratio" method: converts your Sharpe ratio to a t-stat, haircuts it for the number of trials N, and converts back. Their own worked example: a 10-year backtest with Sharpe 1.2 (t ≈ 3.79) gets haircut to ~0.93 after 10 trials and ~0.54 after 1,000 trials — the haircut is steep and nonlinear.

**More complete correction (accounts for non-normal, fat-tailed returns too):**

- **Bailey & López de Prado (2014), "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality,"** *Journal of Portfolio Management* 40(5), 94–107 (SSRN 2460551, [PDF](http://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)). The **expected maximum Sharpe ratio you'd see from N trials under pure luck** (zero true skill, iid normal trial outcomes) is:

  E[max SR_n] ≈ (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(Ne))

  where γ ≈ 0.5772 (Euler-Mascheroni). Computing this for your situation:

  | N (variants tried) | E[max Sharpe] under pure noise |
  |---|---|
  | 15 | ≈ 1.77 |
  | 20 | ≈ 1.90 |

  This means: if you tested 15–20 configurations with genuinely zero skill, you should *expect* to see a best-performing variant with a (standardized) Sharpe ratio around 1.8–1.9 purely from chance. The Deflated Sharpe Ratio then asks whether your actual best variant clears this bar, using the **Probabilistic Sharpe Ratio** machinery that additionally corrects for sample skewness γ₃ and kurtosis γ₄ (important here, since binary-settlement P&L and clustered dislocation fills are almost certainly fat-tailed/skewed, not Gaussian):

  σ̂(ŜR) = √[(1 − γ₃·ŜR + (γ₄−1)/4·ŜR²) / (T−1)],  PSR = Φ[(ŜR − SR*)/σ̂(ŜR)]

  — **DSR substitutes SR\* = E[max SR_n] from the table above.**

- **Bailey, Borwein, López de Prado & Zhu (2014), "The Probability of Backtest Overfitting,"** arXiv:1302.4258 (Journal of Computational Finance) — introduces **Combinatorially Symmetric Cross-Validation (CSCV)**, a resampling procedure purpose-built to estimate the probability that your *best-in-sample* configuration is overfit rather than skilled, without assuming normality. Given you have 15–20 variants, this is directly runnable on your own backtest outputs and is arguably more appropriate than a parametric DSR correction for exactly your situation.
- **Bailey, Borwein, López de Prado & Zhu (2014), "Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance,"** *Notices of the AMS* 61(5), 458–471 ([PDF](https://obj.portfolioconstructionforum.edu.au/articles_perspectives/Pseudo-mathematics-and-financial-charlatanism.pdf)). Introduces the **Minimum Backtest Length (MinBTL)** concept: the expected maximum Sharpe ratio under N trials grows only as √(2 ln N), so the number of periods of data you need to distinguish a target Sharpe ratio from pure overfitting luck scales approximately as:

  MinBTL (in years, for annualized SR\*) ≈ 2 ln(N) / SR\*²

  I'll flag directly: I could confirm this paper's existence, thesis, and the √(2 ln N) asymptotic independently across multiple sources, but I could not fully re-extract the paper's exact worked numerical example from the PDF in this session to verify the precise constant beyond the asymptotic approximation above — treat the formula as the standard asymptotic form used to discuss this result, and check the original for the exact finite-sample correction before using it as a hard gate.

  The qualitative lesson that **is** robust: MinBTL grows only *logarithmically* in N, meaning going from 15 to 20 variants barely changes the data requirement — but it is strongly inverse in SR², meaning your *tiny* effect size (not your trial count) is what makes this hard. This is consistent with everything found in Part 3's power calculation.

---

## 4. Alternatives to full backtesting

### Counterfactual replay on your own order log

What you **can** legitimately infer: for any configuration change that only alters *where/when/how big* you quote (different tick-offset, different reprice interval, different inventory-skew rule, different market selection) as a deterministic function of already-observed market data, you can replay your decision logic against the **real, already-realized mid-price/spread path** to generate the counterfactual quote schedule with zero look-ahead. This sidesteps simulating how other participants would behave — a legitimate simplification **as long as your resting size is small relative to the market's liquidity** (you are a price-taker with no footprint). Combined with the fill model from Part 1/2, this gives you a full counterfactual P&L path for each candidate configuration without needing a multi-agent market simulator.

What you **cannot** infer this way: anything involving how the realized trade tape itself would have differed under the new policy. The trade tape you have was generated *under your old policy*; if a new policy pulls your quotes further from mid, other makers might step into the gap you vacated, changing which trades print and at what price. This is the standard "non-reactive backtest" limitation and is the reason full agent-based market simulators exist (e.g., the ABIDES framework from Byrd, Hybinette Balch et al.) — building one is a large undertaking and, given your team size and the urgency implied here, I would not recommend it as a first step. The practical test for whether this assumption is even safe: check what fraction of total market volume in each of your 80 markets coincides with your own resting size — if you're a material fraction of displayed liquidity in the thinner contracts, the "no footprint" assumption is shaky exactly where you most need it to hold.

### Live A/B testing: design, pitfalls, and required duration

**Design:** randomize at the **market** level (not within-market, since within a single market treatment and control would directly interfere), stratified by liquidity/category to balance arms, running concurrently (not before/after) to avoid confounding config changes with time-varying market regime.

**Pitfall 1 — cross-market contamination.** If multiple contracts reference the same underlying event (e.g., several markets on the same election), they are not independent units; randomizing them into different arms creates exactly the test-control interference documented in:

- **Blake, T. & Coey, D. (2014), "Why Marketplace Experimentation is Harder than it Seems: The Role of Test-Control Interference,"** *Proceedings of the 15th ACM Conference on Economics and Computation (EC'14)*. Their eBay case study found that ignoring marketplace interference overstated a campaign's effect by roughly **2×**. Fix: cluster-randomize at the level of the correlated-event group, not the individual market.

**Pitfall 2 — non-stationarity.** Market conditions (volatility regime, days-to-expiry, news flow) change within the test window and interact with which arm looks better by pure timing. Block your randomization by date and/or days-to-settlement, and consider a **switchback** design (alternating which arm each market is in, over time, rather than a single persistent split) if cross-sectional randomization alone leaves you worried about market-level confounds:

- **Bojinov, Simchi-Levi & Zhao (2023, orig. 2020), "Design and Analysis of Switchback Experiments,"** *Management Science* 69(7), 3759–3777, arXiv:2009.00148. Gives a minimax-optimal design for the switching cadence and valid (randomization-based) inference under unknown carryover effects — directly applicable if you worry that inventory or quote-state carries over between treatment and control periods for the same market.

**Pitfall 3 — the same power problem as Part 3, now worse.** Splitting ~80 active markets 50/50 doesn't just need ~78,500 total fills at 80% power for a 20%-relative effect — once you apply the ~14× illustrative clustering deflation from Part 3, you need on the order of **a million raw fills**, split across two arms, meaning each arm independently needs to accumulate roughly half that. At your apparent fill rate, this points to a test that would need to run for a very long time relative to the lifetime of the underlying prediction-market cycle (most individual binary contracts resolve within weeks) — by the time you've accumulated enough data, the specific markets you started with have settled and been replaced, so the "same experiment" is really a rolling design across waves of new markets, which reintroduces non-stationarity concerns.

**Practical resolution:** don't try to power a live test for 20%-relative effects. Reserve live A/B testing for **a small number (≤3–5) of candidates you believe could plausibly move the edge by 2× or more** (effect size ≈ 0.1, needing only ~785–1,570 fills per arm before clustering, i.e., achievable), and use markout at a fixed short horizon (not raw settlement P&L) as the primary endpoint, since markout has a cleaner noise profile and doesn't require waiting for settlement.

### Is live A/B testing statistically superior to backtesting here? Both sides

**For A/B superiority:** it requires no fill simulator at all — real queue priority, real adverse selection, real latency, and real counterparty reactions (including other makers responding to your changed quotes) are captured automatically. It is the only method that can validate effects that depend on how *other participants* react to your policy, which no non-reactive replay (Part 4, above) can ever capture, and which even a well-calibrated fill model (Parts 1–2) does not attempt to model.

**Against A/B superiority:** it is slow and capital-costly in direct proportion to how tiny your effect size is — as shown, a live test adequately powered for the effect sizes you actually care about (20% relative) is likely impractical given your current fill rate and clustering structure, while a backtest costs nothing to re-run. Running 15–20 variants live simultaneously fragments your already-thin ~80-market sample into even smaller, less powerful sub-experiments — the opposite of what you want when statistical power is already the binding constraint. And a live test that's stopped early because an interim result "looks good" (peeking) inflates the false-positive rate; avoiding this requires a pre-committed sample size or a formal sequential-testing correction, neither of which is natural to enforce under commercial pressure to ship.

**The resolution is not "which is better" but sequencing them as complements:** use a *validated* (Part 2) backtest as a cheap, fast filter to eliminate clearly bad ideas and rank the remaining candidates; reserve live A/B testing, sized per the power calculation, for the few highest-conviction, largest-expected-effect candidates that survive the backtest filter.

---

## 5. Settlement-horizon validation

Held-to-settlement positions have a real, auditable outcome (0/1) at a known future date — this is not actually a worse validation problem than the scalping side; it's a **different** one, and proper scoring rules make it tractable.

### Proper scoring rules and calibration

- **Brier, G.W. (1950), "Verification of forecasts expressed in terms of probability,"** *Monthly Weather Review* 78(1), 1–3. Brier score = (p − outcome)², strictly proper for binary forecasts.
- **Gneiting, T. & Raftery, A.E. (2007), "Strictly Proper Scoring Rules, Prediction, and Estimation,"** *JASA* 102(477), 359–378 ([PDF](https://www.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf)). Establishes why strict propriety matters (it's only incentive-compatible to report your true belief under a strictly proper rule) and formalizes the log score, −log(p), as the other standard choice — log score punishes confident-and-wrong forecasts far more severely than Brier, which matters if you ever quote very near 0.005 or 0.995.
- **Murphy, A.H. (1973), "A New Vector Partition of the Probability Score,"** *Journal of Applied Meteorology* 12(4), 595–600 — the classical decomposition of Brier score into **reliability** (calibration error) + **resolution** (discrimination skill) − **uncertainty**. Use this decomposition, not the raw Brier score, to tell whether a bad score is a calibration problem (fixable by recalibration) or a genuine lack of skill (not fixable by recalibration).

**Concrete procedure:** log your implied probability for every held position at standardized checkpoints (entry, weekly, T−7d, T−1d). As each of your 237 markets resolves, compute Brier and log score per position, and build a reliability diagram (predicted-probability deciles vs. realized frequency) **per checkpoint horizon separately** — calibration at T−1d and calibration at T−28d are different questions and will have very different confidence intervals, since you likely have far fewer *resolved* markets than live quote-snapshots. With a plausibly small number of resolutions so far, use Wilson score intervals per bin rather than naive normal-approximation CIs, which will be badly miscalibrated themselves at small counts.

### Using Polymarket as an external reference, without circularity

The single most important methodological rule, independently confirmed by directly examining a public calibration analysis of Polymarket itself: **never use a market's own near-resolution price as the truth proxy for that same market** — by construction it converges to the outcome, so "predicting" with it trivially looks perfectly calibrated regardless of whether the market is actually any good. This exact point is made explicit in an empirical calibration study I verified directly (GitHub, `GitHubMagnus/polymarket-calibration`, "How Well-Calibrated Are Prediction Markets? An Empirical Analysis of Polymarket," analyzing 3,018 resolved markets closing Oct 2025–Jul 2026): *"the final price of a resolved market must never be used... 'predicting' outcomes with final prices is circular and would certify any market, however inefficient, as perfectly calibrated."* I'm citing this as a grey-literature/non-peer-reviewed source — it's a single-author GitHub analysis, not a journal paper — but I verified its content and methodology directly and it is sound.

That same analysis found expected calibration error (ECE) of **1.6 percentage points at a 1-day horizon**, degrading to **3.9pp at 7 days** and **5.1pp at 30 days** out. Critically for you: it also found a specific miscalibration at longer horizons — **events priced 50–70% resolved YES 84% of the time when measured 30 days out** (vs. ~69% at 7 days, converging to accurate by 1 day) — i.e., Polymarket prices are measurably **underconfident / compressed toward 50%** at roughly your ~28-day settlement horizon specifically. Do not use Polymarket's price at your matched horizon as literal ground truth without a horizon-dependent correction; the evidence says it's exactly at that horizon that the proxy is most biased.

A related, more heavily-cited academic caution about treating *any* prediction-market price as a probability at all:

- **Manski, C.F. (2006), "Interpreting the Predictions of Prediction Markets,"** *Economics Letters* 91(3), 425–429. Shows that under heterogeneous risk-neutral beliefs, the equilibrium price only partially identifies the *mean* belief, not a unique probability — the price-equals-probability identification is an approximation that holds under restrictive assumptions, not a theorem.
- **Wolfers, J. & Zitzewitz, E. (2004), "Prediction Markets,"** *Journal of Economic Perspectives* 18(2), 107–126 — the balancing empirical result: across many historical markets (Iowa Electronic Markets, Oscars, Super Bowl), prices have historically tracked realized frequencies well in aggregate, which is why the proxy is *useful* despite Manski's theoretical caution — just not exact, and not immune to the horizon-specific bias found above.

**Practical recipe:** (1) use the realized 0/1 outcome as your actual scoring target whenever a market has settled — this is real ground truth, not a proxy, and is available on a ~28-day lag, which is a manageable (not actually that slow) feedback loop if you start logging now; (2) use Polymarket's price at a *matched horizon* purely as an early-warning divergence monitor on *still-open* positions, explicitly discounted for the horizon-dependent bias documented above, never as a final truth source; (3) treat large, persistent divergence between your book's implied probability and Polymarket's matched-horizon price as a trigger for manual investigation, not as an automatic "you're wrong" signal, given Manski's point that neither price is uniquely "the" probability.

Two additional secondary sources I verified exist but could not fully extract for precise numbers (flagging lower confidence accordingly): a Princeton senior thesis (**Walker, A.M. (2026), "The Price is (Almost) Right: A Calibration Analysis of Polymarket Pricing Data,"** OR&FE Dept.) analyzing 188,509 resolved markets, and **Bürgi, Deng & Whelan (2026), "Makers and Takers: The Economics of the Kalshi Prediction Market,"** CESifo Working Paper (PDF confirmed hosted at karlwhelan.com), which documents a favorite-longshot bias and persistently positive **maker** (liquidity-provider) returns on Kalshi using 300k+ contracts — directly relevant context for whether your passive-maker edge is structural or likely to be arbitraged away, but I was not able to parse exact figures from the PDF in this session and would independently verify before quoting specific numbers from it.

---

## Deliverable: what to build first

In priority order, each buildable on data you already have:

**1. A Cox proportional-hazards fill-time model on your own order log (build this first, this week).** Event = fill, censoring = cancel/reprice, covariates = distance-to-mid in ticks, spread, recent trade intensity, time since repricing. This requires no theory about other participants, uses your actual 2,300 fills as ground truth, and is auditable via standard survival diagnostics (concordance index, Schoenfeld residuals). *Pitfall:* with only 2,300 fills and strong clustering (Part 3), keep covariates to ≤4–6 and validate with a time-based split, not a random one — a model that looks great in-sample with 10 features is the most likely source of your next shipped regression.

**2. A two-sided (optimistic/pessimistic) bracketing simulator for counterfactual replay of configuration changes**, with the Cox model's distance-based hazard curve as the point estimate inside the bracket. Trust a configuration-ranking conclusion only if it holds under both bounds. *Pitfall:* if the bracket is too wide to distinguish two configurations, that is itself the answer — it means you don't have enough data to decide, and forcing a decision anyway is exactly the pattern that produced your past shipped regressions.

**3. A zero-capital shadow-quoting harness** that runs 3–5 finalist configurations' quote logic in real time (not historical replay) to generate fresh out-of-sample data for re-validating the Cox model going forward, closing the loop described in Part 2. *Pitfall:* shadow quotes can't be filled reactively by real counterparties, so this validates your quote-generation and repricing logic, not a way to avoid fill modeling — don't oversell it internally as "live testing without risk."

**4. A pre-registered live A/B test reserved only for candidates with plausible ≥2× effect size**, cluster-randomized by correlated-event group (not raw market), with a pre-committed minimum duration computed from the power formula in Part 3 and markout-at-fixed-horizon as the primary endpoint rather than raw P&L. *Pitfall:* do not use this mechanism to test 15–20 variants, and do not stop it early on an interim look — both guarantee a false "win."

**5. A settlement-horizon scoring pipeline, started immediately in parallel with everything else**, logging implied probability at standardized checkpoints for every held position, scored with Brier/log score and Murphy's decomposition as markets resolve, cross-checked (never substituted) against horizon-matched, never-final Polymarket prices. *Pitfall:* every day you delay starting this log is calibration data you cannot reconstruct later — this is the cheapest, lowest-risk item on this list and should not wait on 1–4.

**The pitfalls that would make any of this misleading, collected:** treating a single venue's price (yours or Polymarket's) as ground truth for an unresolved event; declaring a win on backtested P&L without clearing a multiple-testing-adjusted bar (Bonferroni/Harvey-Liu-Zhu t>3, or DSR) given you've tried 15–20 variants; computing significance as if your 2,300 fills were independent when clustering plausibly cuts effective N by an order of magnitude or more; and — the one I'd flag as most likely to explain your past regressions specifically — presenting output from a naive "touch = fill" simulator with the implied rigor of the queue-reactive literature, when that literature's core assumption (observed queue size) was never satisfied by your data in the first place.