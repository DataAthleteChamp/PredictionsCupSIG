Agent is idle (waiting for messages). agent_id: a06ca9cd-0eaa-4d98-a36d-f76e28b45a4b, agent_type: research, status: idle, description: Bayesian evaluation of trading edge, elapsed: 9055s, total_turns: 1

[Turn 0]
# Estimating and Validating a Trading Edge from a Small, Noisy Sample: A Formula-First Methodology

*Research-only deliverable. No code was written or executed against your data; all arithmetic below is generic sensitivity analysis using the summary statistics you provided. All citations verified via direct primary-source fetch where noted; secondary-source reconstructions are flagged explicitly in §7.*

---

## HEADLINE ANSWER

**Your 3 fills tell you almost nothing, and the arithmetic says so quantitatively, not just qualitatively.**

You gave me a mean (+0.0875/share) but not a within-bucket standard deviation, so no literal posterior is computable — this is itself the first finding (see §0). Running the normal–normal shrinkage model (§1) across a defensible range of assumptions for the per-fill noise scale σ and the prior scale τ (how big you'd a priori believe a genuine passive-quoting edge could be):

| Scenario | σ (per-fill SD) | τ (prior SD) | Shrinkage B | Posterior mean |
|---|---|---|---|---|
| Optimistic (low noise, generous prior) | 0.03 | 0.02 | 43% | +0.0500 |
| Central / most defensible | 0.08 | 0.01 | 95.5% | **+0.0039** |
| Central + honest clustering (ρ=1, n_eff≈1) | 0.08 | 0.01 | 98.5% | **+0.0013** |
| Conservative (high noise, tight prior) | 0.15 | 0.005 | 99.7% | +0.0003 |

**Central, defensible answer: your posterior belief about the true deep-ladder edge should move from the raw +0.0875/share to roughly +0.001 to +0.004/share — a 95–99% shrinkage toward zero** — with a posterior standard deviation (≈0.0098) that puts a 95% credible interval comfortably straddling zero (and small negative values). The raw number is almost entirely noise amplified by a single clustered event; treat it as **weak, inconclusive evidence**, not a discovered edge.

**Sample size needed:** for the data to merely draw *even* with the prior (B=0.5), you need n* = σ²/τ² ≈ **64–100 independent fills** under the central scenario (full grid: 9–900, §1.3); to let the data dominate (B≤0.1) you need **~9×** that, i.e. **600–900+**. Critically, **n must count independent events, not fills** — your 3 fills are one event. With within-event correlation ρ≈0.8–1.0, three fills carry the statistical weight of **~1 independent observation** (design effect deff=1+(m−1)ρ → n_eff≈1, §3.4). So the honest requirement is **on the order of 60–100+ independent dislocation events** (not fills-within-events), which at ~3 fills/event could mean low thousands of raw fills, collected across genuinely different dates/regimes (not just more fills in the same overnight window, and ideally not all loading on the same national swing factor — see §3.4's nested-clustering caveat). **Do not size up on this bucket.**

**Contrast that disciplines the rest of this report:** your favourite–longshot result (104 matched markets, sign-test p=3×10⁻⁸ ⟺ z≈5.54) is **robust to severe clustering** — it would survive design effects up to ~8× (i.e., effective clusters of size ~8 at ρ=1) and remain significant at p<0.05 (computed in §3.4/§6). That result is real; the 3-fill markout result, on current information, is not distinguishable from noise. The gulf between these two cases *is* the point of this whole report.

---

## §0. The one data gap you must close before any of this is literal

Every formula below that needs a noise scale (σ, variance, SE) requires the **standard deviation of markouts within each bucket**, which you did not give me (only the means). I have run full sensitivity grids rather than fabricate a number. **Before acting on any of this, compute and report**: (a) per-fill markout SD at each horizon (1/5/30/240 min) for each bucket; (b) the realized intra-bucket correlation of markouts within the same dislocation window (directly estimates ρ in §3.4); (c) how many *distinct* dislocation events (not fills) underlie the 3, ~20, and 16 fills respectively, and how many distinct calendar days/regimes they span (needed for the nested-clustering point in §3.4). These three numbers make every formula below literal rather than illustrative.

---

## §1. Bayesian shrinkage / hierarchical estimation

### 1.1 The James–Stein estimator

**Setup.** X = (X₁,...,X_k) ~ N_k(θ, σ²I), σ² known. The MLE/sample-mean estimator δ(X)=X has constant risk E‖X−θ‖² = kσ² for every θ.

**Formula (shrink toward a fixed point, e.g. the origin):**
```
δ_JS(X) = (1 − (k−2)σ²/‖X‖²) · X,   clipped to 0 if the factor is negative ("positive-part" JS, δ_JS⁺)
```
**Risk:** E_θ‖δ_JS(X)−θ‖² ≤ kσ² − (k−2)²σ⁴/(kσ²+‖θ‖²) < kσ² = risk of X, **for every θ**, whenever **k ≥ 3**. At k=1,2 no such uniform improvement exists — this is the precise boundary of "Stein's paradox."

**Shrinking toward an arbitrary fixed point μ₀** (not just the origin) uses the identical formula in (X−μ₀); still needs only k≥3 because μ₀ is *not* estimated from the data.

**Shrinking toward the *data-estimated* common/grand mean** (Efron–Morris form) costs one extra degree of freedom and uses **(k−3)**, not (k−2):
```
δ_i = X̄ + (1 − (k−3)σ²/S)·(X_i − X̄),   S = Σ(X_i − X̄)²
```
This is a distinction I verified arithmetically because it matters for your exact situation (§1.3): with k=3 groups, (k−3)=0, i.e. **this version is degenerate at k=3** — the "estimate your own prior from the data" route provides *zero* indicated shrinkage with only 3 groups, whereas shrinking to a fixed, externally-chosen point still works at k=3 (barely: k−2=1).

**Worked historical benchmark (for calibration of what "shrinkage factor" numbers look like in practice):** Efron & Morris's baseball example, k=18 players' early-season batting averages (45 at-bats each): shrinkage retention factor c≈0.212, i.e. **≈79% shrinkage** of each player's deviation toward the grand mean .265 — and the shrunk estimates had dramatically lower total squared error predicting the rest of the season than the raw averages.

- **Citations:** Stein, C. (1956). "Inadmissibility of the usual estimator for the mean of a multivariate normal distribution." *Proc. Third Berkeley Symp. Math. Stat. Prob.*, Vol. 1, pp. 197–206. Univ. of California Press. — James, W. & Stein, C. (1961). "Estimation with Quadratic Loss." *Proc. Fourth Berkeley Symp. Math. Stat. Prob.*, Vol. 1, pp. 361–379. — Efron, B. & Morris, C. (1975). "Data Analysis Using Stein's Estimator and its Generalizations." *JASA* 70(350):311–319. — Efron, B. & Morris, C. (1977). "Stein's Paradox in Statistics." *Scientific American* 236(5):119–127.
- **Assumptions:** known (or pluggable) common σ²; squared-error/total risk criterion; k≥3 simultaneous quantities.
- **When it breaks:** k≤2 (no improvement); any single θ_i of interest in isolation gets *worse* expected squared error for that *particular* coordinate even though the *sum* improves (JS trades individual accuracy for aggregate accuracy — ensemble/portfolio framing, not single-strategy framing); unequal/unknown σ_i² per group requires the Morris generalization (§1.2), not vanilla JS.
- **Cost:** closed-form, O(k).
- **Verdict for you:** with only k=3 price-placement buckets, you sit exactly at the minimum k where *any* version of this works, and at the point where the "estimate-your-own-mean" version is mathematically degenerate. **Worth knowing, not worth relying on as a self-contained engine** — see §1.3.

### 1.2 Empirical Bayes — hierarchical normal–normal model

**Model.** Y_i | θ_i ~ N(θ_i, V_i) independently (V_i known or estimated, e.g. V_i = s_i²/n_i), with θ_i ~ N(μ, A) iid across i=1..k (the "many related quantities" — here, your 3 price-placement buckets, or more granular contract/strategy buckets).

**Posterior mean (the actual shrinkage formula you want):**
```
E[θ_i | Y_i] = (1 − B_i)·Y_i + B_i·μ,      B_i = V_i / (A + V_i)
```
B_i is the shrinkage weight toward the prior mean μ; it depends on each group's *own* V_i, so noisier groups (your n=3 bucket) shrink harder than better-measured ones (your n=20 bucket) — exactly the unequal-variance generalization that vanilla JS doesn't handle natively.

**Hyperparameter estimation — two routes:**
- **Method of moments** (closed-form, what Efron–Morris/Morris actually compute): μ̂ = mean(Y_i) [or inverse-variance-weighted]; **Â = max{0, (1/(k−1))Σ(Y_i−μ̂)² − (1/k)ΣV_i}**. Cheap, but with small k this variance-of-a-variance estimate is itself extremely noisy (built from only k−1 degrees of freedom), and the max{0,·} floor means it frequently reports "no between-group heterogeneity at all" even when some genuinely exists.
- **Marginal maximum likelihood**: the marginal law is Y_i ~ N(μ, A+V_i) independently; maximize the resulting log-likelihood over (μ,A) directly (e.g. via EM, since conditional on A this is a weighted-least-squares step for μ). More statistically efficient with unequal V_i and small k than MoM, but iterative and still fundamentally data-starved at k=3.
- **Citation:** Morris, C.N. (1983). "Parametric Empirical Bayes Inference: Theory and Applications." *JASA* 78(381):47–55.
- **Assumptions:** exchangeability of the θ_i a priori (normal with common μ, A); V_i known/well-estimated.
- **When it breaks:** k small (your case) — Â is estimated off only k−1=2 "data points" when k=3, making it nearly as noisy as the thing it's trying to regularize; also breaks if the groups are not really exchangeable (plausible here: deep-ladder, near-touch, and price-improvement fills arise from structurally different economic mechanisms, so a shared-prior assumption across them is already a modeling choice, not a given).
- **Cost:** O(k) for MoM; a handful of EM iterations for MLE — trivial either way.
- **Verdict:** **Worth running as a cross-check (I did, below), not worth trusting as your primary answer** — at k=3 it's barely distinguishable from "guessing."

### 1.3 The actual arithmetic: what a 3-observation sample shrinks to

**(a) Single-bucket Bayesian shrinkage with an *externally specified* prior** (the right tool, because §1.2 shows self-contained EB is unreliable at k=3). Model: X̄ | θ ~ N(θ, σ²/n), θ ~ N(0, τ²). Posterior:
```
E[θ | X̄] = (1−B)·X̄,     B = (σ²/n) / (σ²/n + τ²),     Var[θ|X̄] = (1−B)·σ²/n
```
With n=3, X̄=+0.0875, sensitivity grid over plausible σ (per-fill markout noise, $/share) and τ (prior SD of a genuine edge, $/share):

| σ \ τ | 0.005 | 0.010 | 0.020 |
|---|---|---|---|
| 0.03 | B=92.3%, post=+0.0067 | B=75.0%, post=+0.0219 | B=42.9%, post=+0.0500 |
| 0.05 | B=97.1%, post=+0.0026 | B=89.3%, post=+0.0094 | B=67.6%, post=+0.0284 |
| 0.08 | B=98.8%, post=+0.0010 | **B=95.5%, post=+0.0039** | B=84.2%, post=+0.0138 |
| 0.10 | B=99.3%, post=+0.0007 | B=97.1%, post=+0.0026 | B=89.3%, post=+0.0094 |
| 0.15 | B=99.7%, post=+0.0003 | B=98.7%, post=+0.0012 | B=94.9%, post=+0.0044 |

Across **every single cell of this grid, shrinkage exceeds 40%, and the realistic central region (σ 0.05–0.10, τ 0.005–0.01, i.e. "noise is a few cents, true edges are fractions of a cent") gives 95–99.7% shrinkage.** This is the "near-total shrinkage" you anticipated, now with actual numbers.

**(b) Accounting for clustering.** Your 3 fills share one overnight dislocation — they are not 3 independent draws. Using the design-effect formula (derived properly in §3.4), n_eff = n/(1+(n−1)ρ). At σ=0.08, τ=0.01:

| ρ | deff | n_eff | B | Posterior mean |
|---|---|---|---|---|
| 0.5 | 2.00 | 1.50 | 97.7% | +0.0020 |
| 0.8 | 2.60 | 1.15 | 98.2% | +0.0016 |
| 0.95 | 2.90 | 1.03 | 98.4% | +0.0014 |
| 1.0 (plausible here — single common cause) | 3.00 | 1.00 | 98.5% | +0.0013 |

**With honest clustering, you are statistically in a 1-observation world; shrinkage is 98%+; the posterior mean is ~0.0013–0.0020/share** (posterior SD ≈0.0098, so the 95% credible interval is roughly [−0.018, +0.021] — comfortably includes zero).

**(c) Cross-check via self-contained 3-bucket Empirical Bayes** (§1.2's MoM formula, applied literally to your 3 buckets Y=[0.0875, 0.00125, −0.00469], n=[3,20,16], assuming a common per-fill σ_f): this gives *milder*, not stronger, shrinkage (27–74% on the deep-ladder bucket depending on σ_f) because the MoM prior-variance estimate Â is itself computed by averaging in the very outlier you're trying to discipline — with only 2 degrees of freedom to estimate "how much true heterogeneity exists across strategies," the method cannot tell apart "one noisy fluke" from "genuine cross-strategy variation," and ends up attributing too much of the deep-ladder number to signal. **This is a cautionary, not a reassuring, result**: it demonstrates that the naïve "let 3 groups estimate their own prior" route under-corrects here, reinforcing that an externally grounded prior (§1.4) — not a self-referential one — is the right tool for k=3.

### 1.4 Priors for trading edges — what's defensible, and why centered at/near zero

**Argument for centering at zero (or slightly negative):**
1. **Market-microstructure theory**: in the Glosten–Milgrom framework, the bid–ask spread exists precisely to compensate a passive liquidity provider for expected losses to better-informed counterparties; an *arbitrary* mechanical passive-quoting rule, absent a genuine informational or structural edge, should expect to roughly break even against the spread it captures from uninformed flow net of what it loses to informed flow — i.e., **zero is the theoretically neutral point**, and realistic departures from zero (in either direction) should be small relative to the spread, not large. *Citation:* Glosten, L.R. & Milgrom, P.R. (1985). "Bid, Ask and Transaction Prices in a Specialist Market with Heterogeneously Informed Traders." *Journal of Financial Economics* 14(1):71–100.
2. **Multiple-testing/backtesting skepticism**: in a world where many strategy variants get tried (you tested several placement distances — see §3.5), the base rate of "apparently significant but actually noise" findings is high; Harvey & Liu argue for a much higher evidentiary bar than the conventional t>2, and Harvey's AFA presidential address pushes this further into an explicit call for pre-registration and skepticism of discovered effects in financial economics generally. *Citations:* Harvey, C.R. & Liu, Y. (2015). "Backtesting." *Journal of Portfolio Management* 42(1):13–28. Harvey, C.R., Liu, Y. & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies* 29(1):5–68. Harvey, C.R. (2017). "Presidential Address: The Scientific Outlook in Financial Economics." *Journal of Finance* 72(4):1399–1440.
3. **Direct precedent for shrinking noisy trading means toward a common/zero center**: Jorion's Bayes–Stein estimator does exactly this for portfolio expected-return estimation, precisely because sample means of returns are so noisy that unregularized use destroys out-of-sample portfolio performance. *Citation:* Jorion, P. (1986). "Bayes–Stein Estimation for Portfolio Analysis." *Journal of Financial and Quantitative Analysis* 21(3):279–292.

**Principled scale for τ:** tie it to the instrument's own tick size / plausible spread-capture, not to the observed markout (that would be circular). Binary prediction-contracts of this kind trade in cents on a $0–1 range; a defensible prior says "we would not be surprised by a genuine, repeatable mechanical edge of a few tenths of a cent up to ~1–2 cents per share; we would be very surprised by a persistent, repeatable 5+ cent (5%+ of notional) edge surviving in a competitively quoted market without a real informational or latency advantage." That reasoning is what motivates τ≈0.005–0.02 used throughout §1.3 — **report this as a modeling assumption to be debated, not as a literature-established constant**, since no paper specifically derives "the prior SD of a market-making edge."

**One-line verdict for §1 overall: this is the highest-value, lowest-cost thing you can implement — it is closed-form, costs nothing computationally, and directly answers "is this real" with an honest, quantified "almost certainly not yet."**

---

## §2. Sequential / anytime-valid testing

### 2.1 Wald's SPRT
```
Λ_n = Π_{i=1}^n [f₁(x_i)/f₀(x_i)]     (likelihood ratio, simple H0:θ₀ vs simple H1:θ₁)
Continue while B < Λ_n < A; stop and accept H1 if Λ_n ≥ A; stop and accept H0 if Λ_n ≤ B
A ≈ (1−β)/α,   B ≈ β/(1−α)             (Wald's boundary approximations)
```
**ASN (average sample number)**, via Wald's identity on the log-LR random walk S_n=ΣZ_i, Z_i=log(f₁/f₀):
```
E_θ[N] ≈ E_θ[S_N] / E_θ[Z]
E_θ₀[N] ≈ [α·log A + (1−α)·log B] / E_θ₀[Z]        E_θ₀[Z] = −KL(f₀‖f₁)
E_θ₁[N] ≈ [(1−β)·log A + β·log B] / E_θ₁[Z]        E_θ₁[Z] = +KL(f₁‖f₀)
```
- **Citation:** Wald, A. (1945). "Sequential Tests of Statistical Hypotheses." *Annals of Mathematical Statistics* 16(2):117–186. Wald, A. (1947). *Sequential Analysis*. Wiley.
- **Assumptions:** i.i.d. observations; a *specific* point alternative θ₁ must be chosen in advance.
- **When it breaks:** composite alternatives ("mean > 0" without a specific effect size) aren't handled natively; your fills are not i.i.d. (they cluster).
- **Cost:** O(1) per observation.
- **Verdict:** the historical ancestor of everything below; **not directly implementable as-is given your composite alternative and dependence** — use §2.2 instead, which generalizes it correctly.

### 2.2 e-values, e-processes, and always-valid p-values

**e-variable**: nonnegative E with E_P[E] ≤ 1 for every P in the null. **Test (super)martingale**: M_t = Π_{i=1}^t B_i, each "unit bet" B_i satisfying E_P[B_i | ℱ_{i−1}] ≤ 1. **e-process** extends this to composite nulls: E_t ≤ some test-martingale family for every null P.

**Ville's inequality — the engine that licenses optional stopping:**
```
P( sup_t M_t ≥ a ) ≤ 1/a      for every a ≥ 1
⟺  P( ∃t≥1 : M_t ≥ 1/α ) ≤ α      for α∈(0,1)
```
This is a **single, time-uniform** statement over *all* t jointly — whatever (possibly data-dependent, possibly post-hoc) time you actually stop at is a sub-event, so the false-positive budget α is never exceeded **no matter when or how often you look.**

**Explicit betting construction, testing mean ≤ 0 vs mean > 0:**
```
K_t = Π_{i=1}^t [1 + λ_i·X_i],     λ_i predictable (ℱ_{i−1}-measurable), chosen to keep K_t ≥ 0
```
If true mean = 0, K_t is a nonnegative martingale (E[K_t]=1 ∀t); a well-chosen λ drives K_t→∞ if the true mean is positive. By Ville's inequality, **C_t := {m : K_t(m) < 1/α}** is a valid time-uniform (1−α) confidence sequence (bridges to §2.3), and the **always-valid p-value** is:
```
p_t = min(1,  1 / max_{s≤t} K_s)
```
Comparing p_t to α at any random stopping time never inflates the false-positive rate (direct corollary of Ville).

**Choosing the bet size λ:** (i) **GRO** (growth-rate-optimal/Kelly-style) — maximize expected log-growth under a targeted alternative; for simple-vs-simple this reduces exactly to the Wald LR; (ii) **mixture method** — integrate the per-round LR over a mixing distribution on λ (no commitment to one effect size, costs a little power); (iii) **predictable plug-in** — set λ_t as a function only of past data (e.g. λ_t ∝ 1/σ̂_{t−1}), the most practical choice when you don't know the true effect size in advance.

- **Citations:** Shafer, G. (2021). "Testing by betting: A strategy for statistical and scientific communication." *JRSS-A* 184(2):407–431. Ramdas, A., Grünwald, P., Vovk, V. & Shafer, G. (2023). "Game-Theoretic Statistics and Safe Anytime-Valid Inference." *Statistical Science* 38(4):576–601. Vovk, V. & Wang, R. (2021). "E-values: Calibration, combination and applications." *Annals of Statistics* 49(3):1736–1754. Grünwald, P., de Heide, R. & Koolen, W.M. (2024). "Safe Testing." *JRSS-B* 86(5):1091–1128. Waudby-Smith, I. & Ramdas, A. (2024). "Estimating Means of Bounded Random Variables by Betting." *JRSS-B* 86(1):1–27. (Ville-type optional-stopping inequality also independently in: Robbins, H. (1970). "Statistical Methods Related to the Law of the Iterated Logarithm." *Annals of Mathematical Statistics* 41(5):1397–1409 — shows P(∃n: Λ_n≥ε) ≤ 1/ε.)
- **Assumptions:** E_P[bet]≤1 under the null at every bet time, conditional on all prior info; bounded or sub-Gaussian markouts for the concrete constructions.
- **When it breaks:** wrong support/tail assumption (e.g. an occasional huge fill outside assumed bounds) voids the guarantee; a badly-chosen λ costs *power*, not validity — it fails safe, not falsely.
- **Cost:** O(1) amortized per fill (one running product update); predictable-plug-in needs no root-finding.
- **Verdict: this is the single best-fit tool for "keep collecting fills and monitor continuously without inflating false positives." Cheap, robust, worth implementing essentially unconditionally** — the only honest cost is low power with single-digit-to-dozens of fills, which is a fact about your data, not a flaw in the method.

### 2.3 Confidence sequences

**Definition**: (CI_t) with P(∀t≥1: μ_t∈CI_t) ≥ 1−α (time-uniform; stronger than ordinary coverage at one n).

**Closed-form two-sided normal-mixture boundary** (exact via method of mixtures, a function of the running variance process v=V_t, tuning ρ>0, significance α):
```
u(v) = sqrt( (v+ρ) · log( (v+ρ) / (α²ρ) ) )
CS_t = X̄_t  ±  u(V_t)/t
```
This boundary is minimax-tight in the sub-Gaussian case. A related closed-form "stitched"/LIL-type boundary:
```
X̄_t ± 1.7·sqrt( (loglog(2t) + 0.72·log(10.4/α)) / t )
```
— note the **loglog(t)** growth rate, which is exactly the rate needed to survive forever without the crossing probability running away (see §2.4).

**Betting-based CS for bounded variables** (relevant since prices live in [0,1]): empirical-Bernstein construction with predictable plug-in bet size
```
λ_t = sqrt(2·log(2/α) / (σ̂²_{t−1}·t·log(1+t))) ∧ c,     c∈(0,1)
CS_t = (Σλ_i X_i / Σλ_i)  ±  (log(2/α) + Σv_i·ψ_E(λ_i)) / Σλ_i
```
reported as >500× faster to compute than earlier conjugate-mixture variants (no root-finding).

- **Citations:** Howard, S.R., Ramdas, A., McAuliffe, J. & Sekhon, J. (2021). "Time-Uniform, Nonparametric, Nonasymptotic Confidence Sequences." *Annals of Statistics* 49(2):1055–1080 (arXiv:1810.08240). Waudby-Smith, I. & Ramdas, A. (2024), as above.
- **Assumptions:** known/estimable sub-Gaussian variance proxy or known boundedness; no i.i.d. requirement (a real robustness win over SPRT) — only a filtration/conditional-mean structure.
- **When it breaks:** variance-proxy/boundedness misspecification breaks coverage; with single-digit-to-low-dozens of fills, the additive loglog(t)+log(1/α) terms dominate — expect wide, usually-zero-straddling intervals (correct, not a bug).
- **Cost:** O(1) per fill, closed-form.
- **Verdict: the most directly "report-ready" tool here — gives you a number (an interval) to put in front of a risk committee at any time, honestly wide given your n.** Worth implementing alongside §2.2.

### 2.4 Why naive repeated peeking is wrong, quantified

If you run a fixed-sample z/t-test at nominal α=0.05 every time new fills arrive and act the first time p≤0.05, the **true** cumulative false-positive probability over K equally-spaced looks is:

| K (number of looks) | 1 | 2 | 3 | 5 | 10 | 20 | 100 | ∞ |
|---|---|---|---|---|---|---|---|---|
| True overall type-I error | 0.05 | 0.08 | 0.11 | 0.14 | 0.19 | 0.25 | 0.37 | **1.00** |

*(Source: Armitage, McPherson & Rowe (1969), JRSS-A 132(2):235–244, Table 2, and Pocock, S.J. (1977), "Group sequential methods in the design and analysis of clinical trials," Biometrika 64(2):191–199 — this exact table is independently reproduced across multiple secondary pedagogical sources with consistent values; treat third-decimal precision with mild caution, order of magnitude is solid — see §7.)*

**Why it hits 1 in the limit (not just "gets worse"):** under the null, the standardized cumulative statistic Z_t behaves like a driftless random walk, and the Law of the Iterated Logarithm guarantees
```
limsup_{t→∞}  S_t / sqrt(2·t·loglog t) = σ     almost surely
```
— i.e. Z_t is unbounded above infinitely often, with probability 1. **Any fixed critical value (e.g. z=1.96) will almost surely be crossed eventually if you simply wait long enough.** This is exactly why valid anytime boundaries (§2.3) must grow at the sqrt(t·loglog t) rate rather than stay flat. *Citations:* Hartman, P. & Wintner, A. (1941). "On the Law of the Iterated Logarithm." *American Journal of Mathematics* 63(1):169–176. Robbins (1970), as above.

**Verdict: this is very likely your desk's current default behavior ("run a t-test after every fill, act if p<0.05") and is precisely the failure mode §2.2–2.3 fix at the same O(1)-per-fill compute cost. There is no engineering excuse to keep doing this once it's flagged.**

---

## §3. Dependence-aware inference

### 3.1 Block bootstrap (moving-block)

Form all overlapping length-ℓ blocks of a stationary series, draw k=⌈n/ℓ⌉ of them with replacement, concatenate (truncate to length n).
```
σ̂²_MBB = (b/Q)·Σ_{i=1}^Q (X̄_{i,b} − X̄_N)²,     Q = N−b+1
```
**Block-length rate** (Hall, Horowitz & Jing 1995): ℓ_opt ~ n^{1/3} for variance/SE estimation, ~n^{1/4} for one-sided, ~n^{1/5} for two-sided CIs. **Automatic plug-in selector** (Politis & White 2004; corrected Patton, Politis & White 2009): based on the estimated spectral density at zero via a flat-top lag window; stationary-bootstrap optimal block length b_opt,SB = (2Ĝ²/D̂_SB)^{1/3}·N^{1/3}, with the corrected constant D_SB=2g²(0) (Nordman 2008 found an error in the prior literature's constant).
- **Citations:** Künsch, H.R. (1989). "The Jackknife and the Bootstrap for General Stationary Observations." *Annals of Statistics* 17(3):1217–1241. Hall, P., Horowitz, J.L. & Jing, B.-Y. (1995). "On Blocking Rules for the Bootstrap with Dependent Data." *Biometrika* 82(3):561–574. Politis, D.N. & White, H. (2004). "Automatic Block-Length Selection for the Dependent Bootstrap." *Econometric Reviews* 23(1):53–70. Patton, A., Politis, D.N. & White, H. (2009). Correction, *Econometric Reviews* 28(4):372–375.
- **Assumptions:** stationarity, mixing, ℓ→∞ with ℓ/n→0.
- **When it breaks:** exactly your situation — bursty/regime-switching, non-stationary data. With n≤40, ℓ_opt~n^{1/3}≈3–4, giving ~10 "blocks" at most, and with only 1–3 true independent bursts, resampling blocks *within* one burst just reshuffles noise from the same realized event rather than synthesizing between-event uncertainty.
- **Cost:** O(B·n), trivial.
- **Verdict: not feasible, not honest at your n. Do not use — it would manufacture false precision.**

### 3.2 Stationary bootstrap
Block lengths drawn i.i.d. Geometric(p), mean block length 1/p; the only block bootstrap whose resample is itself exactly stationary.
- **Citation:** Politis, D.N. & Romano, J.P. (1994). "The Stationary Bootstrap." *JASA* 89(428):1303–1313.
- **When it breaks:** same as §3.1, arguably worse — its entire rationale (stationarity of the resampled path) is undermined when the source process is itself a regime-switching/bursty one. Also less efficient than MBB for variance estimation: ARE_{CB/SB} = (2/3)^{2/3} ≈ 0.763 (i.e. needs ~24% more data to match MBB accuracy).
- **Verdict: not feasible here, for the same reason as §3.1 — do not use.**

### 3.3 Cluster-robust standard errors
```
V̂_clu[β̂] = (X'X)⁻¹ B̂_clu (X'X)⁻¹,     B̂_clu = Σ_{g=1}^G X_g'û_g û_g' X_g
```
(sandwich/GEE form, generalizes to unbalanced clusters). **Finite-sample correction**: scale residuals by c=√[G/(G−1)·(N−1)/(N−K)], use T(G−1) critical values. **Even so, few-cluster over-rejection is severe** — Monte Carlo actual size of a nominal 5% test: G=30/20/10/5 → 0.068/0.081/0.118/0.208. **Wild cluster bootstrap** for very few clusters: flip Rademacher weights d_g=±1 per cluster on the null-restricted residuals, re-estimate, repeat. **Critically, at G=3 there are only 2³=8 sign patterns — the smallest achievable p-value is 1/8, full stop**, regardless of formula sophistication.
- **Citations:** Liang, K.-Y. & Zeger, S.L. (1986). "Longitudinal Data Analysis Using Generalized Linear Models." *Biometrika* 73(1):13–22. Cameron, A.C. & Miller, D.L. (2015). "A Practitioner's Guide to Cluster-Robust Inference." *Journal of Human Resources* 50(2):317–372. Cameron, A.C., Gelbach, J.B. & Miller, D.L. (2008). "Bootstrap-Based Improvements for Inference with Clustered Errors." *Review of Economics and Statistics* 90(3):414–427.
- **When it breaks:** degenerate at G=1 (no between-cluster replication exists at all); G=2–3 is below where even the "few clusters" fixes were empirically validated (≈G≥5).
- **Cost:** trivial; wild bootstrap at low G can be **fully enumerated** rather than simulated.
- **Verdict: conceptually the right frame (cluster = dislocation event) but numerically below the floor of the literature. Report the fully-enumerated wild-bootstrap bound explicitly (e.g. "p ≥ 1/8 given G=3") as an honest statement of ignorance rather than a spuriously precise normal-theory p-value.**

### 3.4 Effective sample size under clustering/autocorrelation
```
deff = 1 + (m−1)·ρ,     n_eff = n / deff            (cluster/ICC version, Kish 1965)
n_eff = n / τ,    τ = 1 + 2·Σ_{k≥1} ρ_k              (IACT version, Geyer 1992)
```
**Your number:** 3 fills, one burst (m=3), common-cause correlation plausibly ρ∈[0.8,1.0]: deff≈2.6–3.0, **n_eff ≈ 1.0–1.15**. Honest effective sample size from 3 clustered fills is **~1**.

**Second-order compounding point (worth a line, not fully worked here):** your 3 fills aren't just correlated *within* the overnight window — all 237 contracts (and any future dislocation events) load on one *persistent* national swing factor. That means even if you later accumulate many "independent-looking" dislocation events across different calendar days, they may still share a common factor loading (ρ_between > 0 across events, not just within them), capping your achievable n_eff via a **nested** design effect (fills-within-events-within-regime) below what counting "number of distinct overnight windows" alone would suggest. Diversify across genuinely different causal regimes, not just different dates.

- **Citations:** Kish, L. (1965). *Survey Sampling*. Wiley. Geyer, C.J. (1992). "Practical Markov Chain Monte Carlo." *Statistical Science* 7(4):473–483.
- **When it breaks:** ρ itself needs replication across many clusters to estimate — with G=1–3 it's nearly unidentifiable; IACT needs enough lags to see ACF decay, impossible at n=3–40.
- **Cost:** O(1)–O(n), free.
- **Verdict: the single cheapest, most honest "reality check" tool in this entire report. It manufactures nothing — it just states "you effectively have ~1 data point" — and should frame every other number you report.**

### 3.5 Deflated Sharpe Ratio & multiple-testing adjustment

**(a) Expected maximum Sharpe ratio across N independent trials** (extreme-value approximation):
```
E[max_n{ŜR_n}] ≈ sqrt(V[{ŜR_n}]) · [ (1−γ)·Z⁻¹(1−1/N) + γ·Z⁻¹(1−1/(Ne)) ]
```
γ≈0.5772 (Euler–Mascheroni), Z⁻¹ = inverse normal CDF, e≈2.71828.

**(b) Deflated Sharpe Ratio:**
```
DSR = Z[ (ŜR − SR*)·sqrt(T−1) / sqrt(1 − γ̂₃·ŜR + ((γ̂₄−1)/4)·ŜR²) ],     SR* = E[max SR] from (a)
```
T = sample length, γ̂₃/γ̂₄ = skewness/kurtosis (reduces to Mertens/Lo's √(1+ŜR²/2) under normality). **Corrects jointly for selection bias (via SR\*) and non-normality (via the skew/kurtosis denominator) — exactly your situation (you tried several placement distances and kept the best).**
- **Citation:** Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality." *Journal of Portfolio Management* 40(5):94–107.

**Simpler complementary formula (Harvey & Liu 2015):** under independence across N trials, p_M = 1 − (1−p_S)^N (single-test p-value p_S inflated to a multiple-testing p-value p_M); solve for the "haircut Sharpe ratio" that keeps p_M fixed as N grows. For *dependent* tests (more realistic, given your 237 contracts share one factor) they extend to Bonferroni/Holm (FWER) and Benjamini–Hochberg–Yekutieli (FDR) procedures.
- **Citation:** Harvey, C.R. & Liu, Y. (2015), as above.

**Probability of Backtest Overfitting (PBO) / CSCV:** partition the P&L series into S slices, form all C(S, S/2) complementary IS/OOS splits, rank where the IS-optimal configuration falls in the OOS distribution; PBO = fraction of splits implying below-median OOS performance (logit-transformed for a continuous measure).
- **Citation:** Bailey, D.H., Borwein, J.M., López de Prado, M. & Zhu, Q.J. (2017). "The Probability of Backtest Overfitting." *Journal of Computational Finance* 20(4):39–69.

- **Assumptions:** DSR — trial Sharpes approximately normal across trials (EVT step), 4 moments estimable. Harvey–Liu — independence (simple case) or specified correlation (BHY case). CSCV — enough observations per slice to be non-degenerate.
- **When it breaks:** DSR's EVT approximation degrades for small/unknown N or highly correlated trials; CSCV needs dozens of observations per slice minimum — **not computable with T≈3–40 total fills.**
- **Cost:** DSR/haircut — closed-form, O(N), trivial. CSCV — O(C(S,S/2)) refits, irrelevant cost-wise since data volume (not compute) is binding.
- **Verdict: DSR/haircut is feasible and worth running specifically on your placement-distance search — expect it to show non-significance once N-variants and non-normality are priced in, which is the valuable, honest output. PBO/CSCV is conceptually the right citation for "we searched and picked the best" but is not computable at your current T — cite the concept, skip the computation until T is much larger.**

---

## §4. Evaluating a probabilistic forecaster

### 4.1 Proper scoring rules
```
Brier:  BS = (1/N)Σ(p_i − o_i)²                    Log score: S(p,i) = log p_i   (loss = −log p_i)
```
**Propriety** (the design criterion, not a statistical test): a rule is **proper** if S(Q,Q) ≥ S(P,Q) for all P,Q in the forecast class (truth-telling P=Q is a best response in expectation); **strictly proper** if equality holds iff P=Q. Both Brier and log score are strictly proper. **Why it matters:** incentive compatibility — the forecaster cannot improve its expected score by hedging/misreporting, which is a precondition for any fair head-to-head comparison. **Explicit warning directly relevant to you:** skill-score ratios (e.g. Brier Skill Score) are **generally improper even when the base score is proper** — Murphy (1973) showed the BSS admits hedging strategies; prefer raw loss differentials (§4.4) over skill-score ratios when comparing your forecaster to Polymarket.
- **Citations:** Brier, G.W. (1950). "Verification of Forecasts Expressed in Terms of Probability." *Monthly Weather Review* 78(1):1–3. Gneiting, T. & Raftery, A.E. (2007). "Strictly Proper Scoring Rules, Prediction, and Estimation." *JASA* 102(477):359–378.
- **When it breaks:** log score explodes if the forecaster ever reports p=0 or 1 and is wrong — a real risk in favourite-longshot contexts where quoted probabilities sit near the boundary; winsorize to [ε,1−ε].
- **Cost:** O(n).
- **Verdict: always report both; at n≈104 this is unconditionally safe and cheap.**

### 4.2 Murphy decomposition
```
BS = Reliability − Resolution + Uncertainty
Reliability = (1/N)Σ_k n_k(f̄_k − ō_k)²      Resolution = (1/N)Σ_k n_k(ō_k − ō)²      Uncertainty = ō(1−ō)
```
**Operationally:** Reliability = calibration gap within bins (0 = perfect, same quantity visualized by a reliability diagram); Resolution = ability to discriminate (0 for an "always predict the base rate" forecaster); Uncertainty = base-rate variance, forecaster-independent, sets the scale.
- **Citation:** Murphy, A.H. (1973). "A New Vector Partition of the Probability Score." *Journal of Applied Meteorology* 12(4):595–600.
- **When it breaks:** binned, so inherits the same small-sample binning bias as ECE (§4.3) — with n≈104 and K=10 bins you get only ~10/bin, too sparse; use K=4–5.
- **Verdict: useful diagnostic decomposition, but at n≈104 prefer the bin-free Spiegelhalter test (§4.3) as your primary calibration test and use this as a secondary/illustrative breakdown with coarse bins.**

### 4.3 Calibration tests

**Reliability diagrams**: bin forecasts, plot mean forecast vs. observed frequency per bin against the 45° line. *Citation:* Murphy, A.H. & Winkler, R.L. (1977). "Reliability of Subjective Probability Forecasts of Precipitation and Temperature." *JRSS-C* 26(1):41–47.

**Spiegelhalter's Z-test** (bin-free, closed-form — the standardized uncalibrated Brier score):
```
Z = Σ(y_i − p_i)(1 − 2p_i)  /  sqrt( Σ(1 − 2p_i)² p_i(1 − p_i) )   →d N(0,1) under H0 ("stated p_i are the true probabilities")
```
*(Verified via algebraic derivation: with B=Σ(y_i−p_i)², E[B]=Σp_i(1−p_i) under H0, and the identity (y_i−p_i)²−p_i(1−p_i)=(1−2p_i)(y_i−p_i) gives Z=(B−E[B])/√Var[B].)* *Citation:* Spiegelhalter, D.J. (1986). "Probabilistic prediction in patient management and clinical trials." *Statistics in Medicine* 5(5):421–433.

**ECE:**
```
ECE = Σ_i P(i)·|o_i − e_i|     (P(i)=bin mass, o_i=observed freq, e_i=mean forecast in bin i)
```
*Citation:* Naeini, M.P., Cooper, G.F. & Hauskrecht, M. (2015). "Obtaining Well Calibrated Probabilities Using Bayesian Binning into Quantiles." *AAAI-15*, pp. 2901–2907.

**Known biases**: binning choice drives the result and can hide error via cancellation within bins (Nixon et al. 2019); formally, **binning provably underestimates calibration error** — CE(f_B) ≤ CE(f) for any binning scheme B (Kumar, Liang & Ma 2019, Prop. 3.3), with an explicit example where binning gives CE=0 while the true CE≥0.49. *Citations:* Nixon, J. et al. (2019). "Measuring Calibration in Deep Learning." *CVPR Workshops* (arXiv:1904.01685). Kumar, A., Liang, P. & Ma, T. (2019). "Verified Uncertainty Calibration." *NeurIPS 32* (arXiv:1909.10155). Modern alternative: Vaicenavicius, J. et al. (2019). "Evaluating model calibration in classification." *AISTATS*, PMLR 89:3459–3467.

- **When it breaks:** Spiegelhalter — needs independence across the n predictions (violated if your 104 matched markets share correlated macro shocks, same national-swing-factor issue as §3.4); asymptotic (CLT-based). ECE — biased, no native p-value without bootstrapping.
- **Cost:** Spiegelhalter O(n), closed form — cheapest test here; ECE O(n log n).
- **Verdict: Spiegelhalter's Z is your best-suited primary calibration test at n≈104 — no sparse-bin problem, closed-form. Use ECE only as an illustrative complement, never as a bare point estimate.**

### 4.4 Diebold–Mariano and successors

```
d_t = L(e_1t) − L(e_2t)                DM = d̄ / sqrt(ĝ(0)/T)   →d N(0,1)  under H0: E[d_t]=0
```
ĝ(0) = HAC/spectral-density-at-zero estimator of the long-run variance of the loss differential.

**Small-sample correction (Harvey, Leybourne & Newbold 1997):**
```
DM*_HLN = DM × sqrt[ (T+1−2h+(h/T)(h−1)) / T ],     referred to Student-t(T−1), not N(0,1)
```
h = forecast horizon (h=1 for non-overlapping single-resolution markets — the natural case for your 104 distinct events, where the correction factor is just √[(T−1)/T]≈0.995, but the **switch to t(103) critical values matters more than the rescaling itself**).

**Generalization (Giacomini & White 2006)** — tests *conditional* equal predictive ability, incorporating estimation uncertainty and permitting heterogeneity beyond stationarity:
```
T^h_{n,m} = n·Z̄'_{m,n} Ω̂_n⁻¹ Z̄_{m,n}  →d χ²_q,     Z_{m,t+1} = h_t·ΔL_{m,t+1}
```
computable as n·R² from regressing a constant on h_t·ΔL (Corollary 2). Setting h_t = [1, 𝟙(favourite)] lets you test whether your relative accuracy vs. Polymarket is *conditional* on the favourite/longshot regime you already found significant at p=3×10⁻⁸.
- **Citations:** Diebold, F.X. & Mariano, R.S. (1995). "Comparing Predictive Accuracy." *JBES* 13(3):253–263. Harvey, D., Leybourne, S. & Newbold, P. (1997). "Testing the equality of prediction mean squared errors." *International Journal of Forecasting* 13(2):281–291. Giacomini, R. & White, H. (2006). "Tests of Conditional Predictive Ability." *Econometrica* 74(6):1545–1578.
- **When it breaks:** DM is explicitly "a test for comparing forecasts, not models" (Diebold's own caveat) — misusing it to compare estimated models with overlapping-data uncertainty invalidates it; if your 104 markets are closer to an independent cross-section than a serially dependent time series, a simple paired t-test/Wilcoxon on d_t may be more appropriate than importing HAC machinery.
- **Cost:** O(n) plus a cheap HAC estimate; Giacomini–White is a cheap regression.
- **Verdict: use the HLN-corrected DM against t(103) as your primary forecaster-vs-Polymarket test; Giacomini–White with h_t including a favourite/longshot indicator is the natural next step to connect this to your existing p=3×10⁻⁸ finding.**

---

## §5. Forward / walk-forward validation

### 5.1 Walk-forward validation
Train on an expanding or rolling window, test on the next out-of-sample block, roll forward, aggregate OOS performance. Standard citation: Pardo, R. (2008). *The Evaluation and Optimization of Trading Strategies*. Wiley (Ch. 11, "Walk-Forward Analysis"). **Weakness this whole report circles back to**: a single walk-forward path is one realization — it tells you nothing about the *distribution* of outcomes you could have gotten, which is exactly the backtest-overfitting risk §3.5 quantifies.
- **Verdict: necessary baseline, not sufficient alone — pair with §5.3.**

### 5.2 Purged and embargoed cross-validation
**Why standard k-fold leaks in finance:** training and test observations whose label/evaluation windows *overlap in time* (or are serially correlated through nearby features) let test-set information leak into training, inflating apparent OOS performance.

**Purging rule:** remove any training observation i (with evaluation window [t_i, t_i+h_i], h_i = your markout horizon) whose window overlaps the test window [t₀,test, t₁,test]:
```
remove i  if  [t_i, t_i+h_i] ∩ [t₀,test, t₁,test] ≠ ∅
```
**Embargo rule:** additionally remove training observations starting in (t₁,test, t₁,test+embargo] for a chosen embargo length, to clear residual serial correlation not caught by pure window-overlap purging.
- **Citation:** López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. Ch. 7, "Cross-Validation in Finance."
- **Assumptions:** you know/can bound each observation's label/evaluation horizon (you do — 1/5/30/240 min).
- **When it breaks:** embargo too short relative to the longest horizon used leaves leakage; too long starves you of training data at small T.
- **Cost:** O(n) to compute the purge/embargo mask — trivial.
- **Verdict: directly actionable and cheap — set the embargo to at least your longest markout horizon (≥240 min) around every test block. This is a free, mechanical fix with no statistical sophistication required to implement.**

### 5.3 Combinatorial Purged Cross-Validation (CPCV)
Split the sample into N contiguous groups; for each of C(N,k) ways of choosing k groups as the test set (train on the rest, with purging/embargo applied at every boundary), score OOS. The number of distinct **reconstructable backtest paths** (not just train/test combinations) is:
```
φ(N,k) = (k/N)·C(N,k)
```
*Worked example:* N=6, k=2: C(6,2)=15 combinations → φ(6,2) = (2/6)×15 = **5 distinct OOS paths**. This gives you a *distribution* of OOS Sharpe ratios/performance rather than one number — directly feeding the PBO calculation of §3.5.
- **Citation:** López de Prado, M. (2018), as above, Ch. 12, "Backtesting Through Cross-Validation." Bailey, Borwein, López de Prado & Zhu (2017), as above (the combinatorial-splits machinery underlying both PBO/CSCV and CPCV).
- **When it breaks:** needs enough total data to split into N≥6–16 meaningful groups with viable purge/embargo margins between them — **this is the binding constraint for you**: cost scales as C(N,k) model refits, which is computationally trivial, but **statistically you need enough fills to make even N=6 groups non-degenerate**, and you currently don't (T≈3–40 total across all buckets).
- **Verdict: the right target architecture once you have materially more data; not computable as a meaningful backtest-overfitting check today given your T. Implement the mechanical purge/embargo (§5.2) now; adopt full CPCV once each bucket has enough fills to support ≥6 non-trivial groups.**

### 5.4 A defensible forward-test protocol for a 33-day competition

Given you cannot wait for a long OOS period, the literature-grounded and reasoned recommendations are:
1. **Pre-register** the strategy variants and the decision rule *before* trading starts (which placement distances will be tried, what statistic and threshold decide "promote to size up") — directly following Harvey's (2017) call for pre-specification in financial economics, and mechanically preventing the exact selection-bias problem §3.5's DSR/haircut machinery would otherwise have to correct for after the fact.
2. **Set embargo ≥ longest markout horizon in use (≥240 min)** around every evaluation boundary (§5.2) — cheap, mechanical, and removes one whole category of leakage immediately.
3. **Treat the 33 days as (at best) a handful of independent blocks**, not 33 independent days — apply the effective-sample-size discipline of §3.4 to the *day/regime* level, not just the fill level, given the shared national swing factor.
4. **Report posterior credible intervals (§1), not point Sharpe ratios** — given the severe sample constraint, a shrinkage-based interval that is honest about "still consistent with zero" is more defensible to a risk committee than a backtest-overfitting-prone point estimate dressed up with a single walk-forward path.
5. **Pool across the 237 contracts via the hierarchical model of §1.2** rather than evaluating each contract (or each bucket) in isolation — this is my own extension of the Empirical Bayes/James–Stein logic to your specific setting; I could not find finance-specific prior art that prescribes this exact application, so present it as a reasoned recommendation, not an established result.

---

## §6. Priority ranking given your actual sample size

1. **Implement now, free:** embargo/purge rule (§5.2) and the design-effect "honesty anchor" n_eff≈deff (§3.4) — both are mechanical, cost nothing, and immediately stop you from over-claiming precision.
2. **Implement now, cheap, highest information value:** the single-bucket Bayesian shrinkage of §1.3 with an explicit, debated prior — this is the one calculation that directly answers "is the edge real," and it already tells you: **not yet, probably not, and here's the honest posterior.**
3. **Implement for ongoing monitoring:** an e-process/confidence-sequence pair (§2.2–§2.3) in place of whatever naive repeated-testing logic you likely have now — same engineering cost, removes a real and quantified failure mode (§2.4).
4. **Run once, cheaply, as a gut-check on the placement-distance search:** Harvey–Liu haircut / DSR (§3.5) — expect (and should expect) non-significance; that is the correct and valuable answer at your T.
5. **Not worth it yet:** block/stationary bootstrap (§3.1–3.2), CSCV/PBO and full CPCV (§3.5/§5.3) — all require more data per group than you currently have; revisit once each bucket supports ≥6 non-degenerate sub-groups.
6. **For the forecaster-comparison workstream (separate from the markout question):** Spiegelhalter's Z plus HLN-corrected Diebold–Mariano (§4) are both well-matched to n≈104 and cheap — your favourite-longshot result is strong enough to survive this scrutiny; the markout edge is not.

---

## §7. Sourcing confidence notes (transparency on verification depth)

Most formulas above were confirmed against primary full text (fetched directly): Gneiting & Raftery (2007), Naeini/Cooper/Hauskrecht (2015), Nixon et al. (2019), Kumar/Liang/Ma (2019), Vaicenavicius et al. (2019), Cameron & Miller (2015), Politis & White (2004) + Patton/Politis/White (2009) corrigendum, Bailey & López de Prado (2014), Harvey & Liu (2015), Bailey/Borwein/López de Prado/Zhu (2017, partial), Giacomini & White (2006, working-paper version), Robbins (1970), Ramdas/Grünwald/Vovk/Shafer (2023), Vovk & Wang (2021), Waudby-Smith & Ramdas (2024), Howard/Ramdas/McAuliffe/Sekhon (2021). A smaller set rest on high-confidence secondary reconstruction because the primary text was paywalled behind institutional logins or bot-walls on every attempted route: **Wald (1945)** (SPRT/ASN formulas — standard, cross-checked via Wikipedia + Wald's 1947 book); **Armitage et al. (1969) and Pocock (1977)** (the peeking-inflation table — cross-confirmed via two independent secondary routes, both converging on the same values); **Künsch (1989), Hall/Horowitz/Jing (1995), Politis & Romano (1994)** (block-bootstrap constructions — confirmed via the authors' own later self-citations); **Kish (1965)** (pre-digital book, design-effect formula via convergent secondary sources); **Murphy (1973), Murphy & Winkler (1977), Brier (1950), Spiegelhalter (1986), Diebold & Mariano (1995), Harvey/Leybourne/Newbold (1997)** (AMS/Wiley/Elsevier paywalls — Spiegelhalter and HLN formulas were specifically cross-verified against actively-maintained, citation-documented open-source implementations — Frank Harrell's `rms` package and the `forecast` R package respectively — rather than trusted from search-engine summaries alone, which in Spiegelhalter's case **contradicts** a simplified and likely-incorrect formula circulating on several SEO-style sites); **López de Prado (2018) AFML** (book not freely accessible — purge/embargo and CPCV mechanics triangulated across multiple independent open-source reimplementations citing the book's snippet numbers verbatim). No finance-specific literature was found connecting purged-CV/CPCV/PBO machinery specifically to binary prediction-market or markout-style labels — the mapping (markout horizon ↔ label horizon) is a direct, low-risk analogy, not a pre-existing citation.

---

## Consolidated references

Armitage, P., McPherson, C.K. & Rowe, B.C. (1969). "Repeated Significance Tests on Accumulating Data." *JRSS-A* 132(2):235–244.
Bailey, D.H. & López de Prado, M. (2014). "The Deflated Sharpe Ratio." *Journal of Portfolio Management* 40(5):94–107.
Bailey, D.H., Borwein, J.M., López de Prado, M. & Zhu, Q.J. (2017). "The Probability of Backtest Overfitting." *Journal of Computational Finance* 20(4):39–69.
Brier, G.W. (1950). "Verification of Forecasts Expressed in Terms of Probability." *Monthly Weather Review* 78(1):1–3.
Cameron, A.C. & Miller, D.L. (2015). "A Practitioner's Guide to Cluster-Robust Inference." *Journal of Human Resources* 50(2):317–372.
Cameron, A.C., Gelbach, J.B. & Miller, D.L. (2008). "Bootstrap-Based Improvements for Inference with Clustered Errors." *Review of Economics and Statistics* 90(3):414–427.
Diebold, F.X. & Mariano, R.S. (1995). "Comparing Predictive Accuracy." *JBES* 13(3):253–263.
Efron, B. & Morris, C. (1975). "Data Analysis Using Stein's Estimator and its Generalizations." *JASA* 70(350):311–319.
Efron, B. & Morris, C. (1977). "Stein's Paradox in Statistics." *Scientific American* 236(5):119–127.
Geyer, C.J. (1992). "Practical Markov Chain Monte Carlo." *Statistical Science* 7(4):473–483.
Giacomini, R. & White, H. (2006). "Tests of Conditional Predictive Ability." *Econometrica* 74(6):1545–1578.
Glosten, L.R. & Milgrom, P.R. (1985). "Bid, Ask and Transaction Prices..." *Journal of Financial Economics* 14(1):71–100.
Gneiting, T. & Raftery, A.E. (2007). "Strictly Proper Scoring Rules, Prediction, and Estimation." *JASA* 102(477):359–378.
Grünwald, P., de Heide, R. & Koolen, W.M. (2024). "Safe Testing." *JRSS-B* 86(5):1091–1128.
Hall, P., Horowitz, J.L. & Jing, B.-Y. (1995). "On Blocking Rules for the Bootstrap with Dependent Data." *Biometrika* 82(3):561–574.
Hartman, P. & Wintner, A. (1941). "On the Law of the Iterated Logarithm." *American Journal of Mathematics* 63(1):169–176.
Harvey, C.R. (2017). "Presidential Address: The Scientific Outlook in Financial Economics." *Journal of Finance* 72(4):1399–1440.
Harvey, C.R. & Liu, Y. (2015). "Backtesting." *Journal of Portfolio Management* 42(1):13–28.
Harvey, C.R., Liu, Y. & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies* 29(1):5–68.
Harvey, D., Leybourne, S. & Newbold, P. (1997). "Testing the equality of prediction mean squared errors." *International Journal of Forecasting* 13(2):281–291.
Howard, S.R., Ramdas, A., McAuliffe, J. & Sekhon, J. (2021). "Time-Uniform, Nonparametric, Nonasymptotic Confidence Sequences." *Annals of Statistics* 49(2):1055–1080.
James, W. & Stein, C. (1961). "Estimation with Quadratic Loss." *Proc. 4th Berkeley Symp.* Vol. 1:361–379.
Jorion, P. (1986). "Bayes–Stein Estimation for Portfolio Analysis." *JFQA* 21(3):279–292.
Kish, L. (1965). *Survey Sampling*. Wiley.
Kumar, A., Liang, P. & Ma, T. (2019). "Verified Uncertainty Calibration." *NeurIPS 32*.
Künsch, H.R. (1989). "The Jackknife and the Bootstrap for General Stationary Observations." *Annals of Statistics* 17(3):1217–1241.
Liang, K.-Y. & Zeger, S.L. (1986). "Longitudinal Data Analysis Using Generalized Linear Models." *Biometrika* 73(1):13–22.
López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
Morris, C.N. (1983). "Parametric Empirical Bayes Inference." *JASA* 78(381):47–55.
Murphy, A.H. (1973). "A New Vector Partition of the Probability Score." *Journal of Applied Meteorology* 12(4):595–600.
Murphy, A.H. & Winkler, R.L. (1977). "Reliability of Subjective Probability Forecasts..." *JRSS-C* 26(1):41–47.
Naeini, M.P., Cooper, G.F. & Hauskrecht, M. (2015). "Obtaining Well Calibrated Probabilities..." *AAAI-15*, 2901–2907.
Nixon, J. et al. (2019). "Measuring Calibration in Deep Learning." *CVPR Workshops*.
Pocock, S.J. (1977). "Group sequential methods in the design and analysis of clinical trials." *Biometrika* 64(2):191–199.
Politis, D.N. & Romano, J.P. (1994). "The Stationary Bootstrap." *JASA* 89(428):1303–1313.
Politis, D.N. & White, H. (2004). "Automatic Block-Length Selection..." *Econometric Reviews* 23(1):53–70; correction: Patton, A., Politis, D.N. & White, H. (2009), *Econometric Reviews* 28(4):372–375.
Ramdas, A., Grünwald, P., Vovk, V. & Shafer, G. (2023). "Game-Theoretic Statistics and Safe Anytime-Valid Inference." *Statistical Science* 38(4):576–601.
Robbins, H. (1970). "Statistical Methods Related to the Law of the Iterated Logarithm." *Annals of Mathematical Statistics* 41(5):1397–1409.
Shafer, G. (2021). "Testing by betting." *JRSS-A* 184(2):407–431.
Spiegelhalter, D.J. (1986). "Probabilistic prediction in patient management and clinical trials." *Statistics in Medicine* 5(5):421–433.
Stein, C. (1956). "Inadmissibility of the usual estimator..." *Proc. 3rd Berkeley Symp.* Vol. 1:197–206.
Vaicenavicius, J. et al. (2019). "Evaluating model calibration in classification." *AISTATS*, PMLR 89:3459–3467.
Vovk, V. & Wang, R. (2021). "E-values: Calibration, combination and applications." *Annals of Statistics* 49(3):1736–1754.
Wald, A. (1945). "Sequential Tests of Statistical Hypotheses." *Annals of Mathematical Statistics* 16(2):117–186.
Waudby-Smith, I. & Ramdas, A. (2024). "Estimating Means of Bounded Random Variables by Betting." *JRSS-B* 86(1):1–27.