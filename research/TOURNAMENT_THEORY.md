Agent is idle (waiting for messages). agent_id: 86267fae-4366-4d6b-8cf4-8ab4db2fdb21, agent_type: research, status: idle, description: Tournament optimal risk theory, elapsed: 1634s, total_turns: 1

[Turn 0]
# Research Report: Goal-Reaching Risk Policy Under a Step-Function Tournament Prize

## Bottom line up front

The core grind is **mathematically the wrong instrument for this objective**, not just quantitatively insufficient — Dubins–Savage/Browne theory says so directly, and the numbers confirm it by **~450 standard deviations**. But the conclusion that we are "out of contention" is **false**: a single correctly-sized, correctly-priced binary contract (or small correlated basket) converts a ~0.00% goal-probability into a **5–14% probability**, computed rigorously below, not asserted. The central error in the framing is treating "P(podium)≈0% under the core strategy" as "P(podium)≈0% under the best feasible strategy." Those are very different claims, and the whole resolution of this problem turns on that distinction.

---

## 1. Goal-reaching vs. expected wealth

### 1.1 The Dubins–Savage result (discrete time)

**Citation:** Dubins, L.E. & Savage, L.J. (1965/1976). *How to Gamble If You Must: Inequalities for Stochastic Processes*. McGraw-Hill; 2nd ed. Dover.

Setup: a gambler with fortune $f \in (0,N)$ repeatedly stakes money on games at probability $p$ of winning (even-money), trying to reach $N$ before ruin.

- **Subfair** ($p<\tfrac12$, house edge against you): **bold play** — stake $\min(\text{fortune}, N-\text{fortune})$ every round — **maximizes** $P(\text{reach } N)$. This is a genuine theorem (the "bold play theorem"), not a heuristic: Dubins–Savage prove no strategy beats it. Intuition: every additional *trial* in a negative-drift game bleeds expected value, so the goal-maximizing policy minimizes the number of trials by swinging for the largest bet the goal allows.
- **Superfair** ($p>\tfrac12$): bold play is **not** optimal; **timid play** (smallest-unit bets) dominates, and $P(\text{reach }N)\to 1$ as stake size $\to 0$ / number of trials $\to\infty$, by the law of large numbers acting in your favor.
- **Fair** ($p=\tfrac12$): *every* strategy satisfying the martingale property gives the same answer, $P(\text{reach }N)=f/N$ — the classical gambler's-ruin result. Bold play attains this in the fewest trials.

**Why this matters here:** the regime is determined by the sign of the edge *of the instrument being used to take the bet*, not by the edge of your "best" strategy in isolation. A trader can simultaneously run a superfair (positive-edge) grind and, separately, a subfair or near-fair bet to pursue a goal — these call for opposite behaviors (timid vs. bold) and must not be conflated into one policy.

Continuous-time generalizations, confirming and extending this:
- Pestien, V.C. & Sudderth, W.D. (1985). "Continuous-Time Red and Black: How to Control a Diffusion to a Goal." *Mathematics of Operations Research*, 10(4), 599–611. Result: when you control both drift $\mu$ and diffusion $\sigma^2$ of your wealth process, the goal-maximizing control at every instant maximizes $\mu/\sigma^2$ — i.e., **maximize the Sharpe ratio squared per unit of time, not the Sharpe ratio itself**, and the bold/timid dichotomy survives in continuous time (bold = max feasible variance, when the achievable $\mu/\sigma^2$ frontier is "subfair" at the margin).
- Kulldorff, M. (1993). "Optimal Control of Favorable Games with a Time Limit." *SIAM Journal on Control and Optimization*, 31(1), 52–69. First continuous-time treatment of a *finite deadline* (not just ruin-before-goal), for a single favorable investment opportunity — the direct precursor to Browne (1999) below.

### 1.2 Browne's (1999) continuous-time deadline result

**Citation:** Browne, S. (1999). "Reaching Goals by a Deadline: Digital Options and Continuous-Time Active Portfolio Management." *Advances in Applied Probability*, 31(2), 551–577. (SSRN: https://ssrn.com/abstract=703; Cambridge Core: doi below.)

Setup: wealth $dW_t = \pi_t\,\sigma\theta\,dt + \pi_t\,\sigma\,dB_t$, where $\pi_t$ is the dollar amount allocated to a risky asset with Sharpe ratio $\theta=\mu/\sigma$ (riskless rate normalized to 0 WLOG), unconstrained sign/size of $\pi_t$. Objective: $\max_\pi P(W_T \ge G)$.

**Derivation** (martingale/Neyman–Pearson method, consistent with Browne's result and with Föllmer, H. & Leukert, P. (1999), "Quantile Hedging," *Finance and Stochastics*, 3(3), 251–273, which is the general incomplete-markets version of the same idea):

Let $Z_t$ be the state-price density, $dZ/Z=-\theta\,dB_t$. Any admissible self-financing wealth process satisfies the budget constraint $E[Z_T W_T]\le w$. Because only the *indicator* $\mathbf{1}_{W_T\ge G}$ matters, it is never optimal to deliver more than $G$ anywhere; the optimal terminal payoff is bang-bang, $W_T^*\in\{0,G\}$, with the "win" region $A=\{Z_T\le z^*\}$ chosen by the Neyman–Pearson lemma to be the *cheapest* states (i.e., states where the risky asset did well). Solving the budget equation $G\cdot E[Z_T\mathbf 1_A]=w$ with $Z_T$ log-normal gives, after collecting terms:

$$P^*(w,G,T,\theta)=\Phi\!\Big(\theta\sqrt{T}+\Phi^{-1}(w/G)\Big)$$

This is exactly Browne's headline result — confirmed by his paper's own abstract: *"the optimal policy is independent of the underlying drift... equivalent to simply buying a European digital option with a particular strike price and payoff."* The feedback control that implements it (solving the HJB first-order condition $\pi^*=-(\theta/\sigma)(V_w/V_{ww})$ on $V=\Phi(\theta\sqrt{T-t}+\Phi^{-1}(w/G))$) is:

$$\pi^*(t,w)=\frac{G\,\varphi\big(\Phi^{-1}(w/G)\big)}{\sigma\sqrt{T-t}}$$

($\varphi$ = standard normal density). I re-derived both formulas independently (shown above) and verified the first by Monte Carlo simulation of the actual feedback control on a test case ($w=1,G=2,T=1,\theta=1,\sigma=0.3$): simulated $P(W_T\ge G)=0.828$ vs. formula $0.841$ (agreement to ~98%, residual gap explained by the well-known delta-blow-up of digital-option replication near expiry under discrete time-stepping). **This formula is correct and I have verified it, not merely looked it up.**

Sanity checks that make this airtight: $\theta=0\Rightarrow P^*=w/G$ (recovers Dubins–Savage fair-game bold play exactly); $w\to G\Rightarrow P^*\to1$; $w\to 0\Rightarrow P^*\to0$; $\theta>0,T\to\infty\Rightarrow P^*\to1$ (recovers superfair/timid-play law-of-large-numbers result). The theory is internally consistent across both papers.

Separately, **Browne also shows the growth-optimal (Kelly) policy is a *different* policy from the goal-reaching policy** — see Browne, S., "Portfolio Choice and the Bayesian Kelly Criterion," *Advances in Applied Probability* (JSTOR 1428168), and the original Kelly, J.L. (1956), "A New Interpretation of Information Rate," *Bell System Technical Journal*, 35(4), 917–926. Kelly maximizes $E[\log W_T]$ (asymptotic growth rate over *many repeated* bets); it is **not** the policy that maximizes $P(W_T\ge G)$ over a *short, finite* horizon with a *large* target multiple. When far behind a near-term deadline, the goal-reaching policy is *bolder* than Kelly; when comfortably ahead, it is *more timid* than Kelly. This distinction matters directly in §3.5.

### 1.3 Numerical application to our exact numbers

$W_0=100{,}060$, $G=700{,}557$, $T=33/365=0.0904$ yr, $\sqrt T=0.3007$. $W_0/G=0.14283$, so $\Phi^{-1}(W_0/G)=-1.0677$, $\varphi(-1.0677)=0.2256$.

**Table 1 — $P^*(\theta)=\Phi(\theta\sqrt T-1.0677)$, unconstrained optimal dynamic play:**

| Annualized Sharpe $\theta$ | $P^*$ |
|---|---|
| 0 (zero edge) | **14.28%** |
| 1.0 | 22.15% |
| 2.0 | 32.05% |
| 3.0 | 43.42% |
| 3.55 | 50.0% |
| 5.0 | 66.85% |
| 7.81 | 90.0% |

**The theory says a genuinely zero-edge asset, played optimally (boldly), already gives 14.28% — far above the stated 0.0000% Monte Carlo result for the core strategy.** This is the whole ballgame: the 0.0000% result is not telling you the goal is unreachable; it's telling you **the core strategy's own (timid) betting policy is catastrophically mismatched to this objective, independent of its edge.**

**Table 2 — distance to goal under the core's *natural* (timid) operation,** parametrized by assumed annualized Sharpe (back-solving daily vol from the observed $+0.06\%$/day):

| Assumed core Sharpe | implied annual vol | # SDs goal is away | $P(\text{reach goal})$ |
|---|---|---|---|
| 2 | 10.95% | 182 | 0 |
| 5 | 4.38% | 454 | 0 |
| 10 | 2.19% | 908 | 0 |
| 20 | 1.10% | 1,817 | 0 |

This is robust to *any* plausible Sharpe assumption — confirms the stated 0.0000% is correct for the strategy *as currently sized and operated*.

**Table 3 — leverage $\pi^*/W_0$ required to make the core strategy itself Browne-optimal:**

| Assumed core Sharpe | required dollar position $\pi^*$ | leverage multiple |
|---|---|---|
| 2 | \$4.80M | **48x** |
| 5 | \$12.0M | **120x** |
| 10 | \$24.0M | **240x** |
| 20 | \$48.0M | **480x** |

And solving the inverse question — what annualized volatility would make a fully-invested (1x, no-borrowing) bet Browne-optimal — gives **$\sigma_{\text{needed}}=525\%$ annualized**, i.e., an instantaneous daily move of ~27.5%. A tick-grinding market-making strategy cannot produce this (it is capacity-constrained: the "edge" is per-fill and does not scale with position size — at 120–480x leverage you'd move the market, exhaust liquidity, and the edge itself would degrade or flip sign). **This is the formal reason the core strategy cannot be "levered into" the right tool, even though it has by far the best Sharpe ratio of anything we run.** What the formula is really telling us is: *go find/construct an instrument whose native volatility is in the hundreds-of-percent range, so the required dollar position is achievable with ≤100% of capital.* That is exactly what a binary options contract priced at a few cents *is* — its "volatility" per dollar of exposure is enormous by construction. Embedded option convexity, not margin leverage, is the admissible substitute here. This directly motivates §3–4.

---

## 2. Which regime are we in?

### 2.1 Genakos & Pagliero (2012) — the inverted-U

**Citation:** Genakos, C. & Pagliero, M. (2012). "Interim Rank, Risk Taking, and Performance in Dynamic Tournaments." *Journal of Political Economy*, 120(4), 782–813. DOI: 10.1086/668502.

Using Olympic/World-Championship weightlifting (observable attempt-weight choices = risk, success/failure = outcome, across three rounds), they find risk-taking in the final attempt is an **inverted U in interim rank**: competitors **moderately behind** the leader choose the riskiest (lowest-success-probability, highest-reward) attempts, because they have a *real, attainable* chance of moving up and the opportunity cost of playing safe is high; competitors **far behind** — with no realistic path to the front — **reduce** risk back to a safe, "make something of the day" lift; and leaders/front-runners also reduce risk (consistent with "choking under pressure" / lead-protection). Mechanism: risk-taking responds to the **marginal sensitivity of P(winning) to risk choice** — in the middle, that marginal sensitivity is high; at the extremes (way ahead, way behind) it collapses to ~0, so rational agents revert to safety.

### 2.2 A defensible criterion, applied to our numbers

The Genakos-Pagliero mechanism gives the criterion directly: **you are "moderately behind" if the *best feasible* strategy gives a goal-probability that is still a meaningfully increasing, responsive function of how much risk/convexity you choose to deploy; you are "out of contention" only if *even the maximum feasible risk*, through *every* available instrument, leaves $P(\text{goal})$ negligible (i.e., you've already hit the flat part of the curve).**

Formally: compute $P^*_{\max}=\max_{\text{feasible strategies}} P(\text{reach goal})$, not $P(\text{reach goal} \mid \text{current strategy})$. If $P^*_{\max}$ is small-but-economically-real (order of magnitude 1%–50%) and *responsive* to allocation choices (as in §4's $f(O)$ tradeoff curve), you're in the max-risk-taking regime. If $P^*_{\max}$ is negligible under *every* instrument available (e.g., <0.01% even at maximum feasible stake and best odds), you're genuinely out of contention and more risk doesn't help — you've saturated.

**Applying it:** §1.3 showed the *core* gives $P^*_{\max}\approx0$. But §3–4 below show that the *best feasible instrument* (a correctly-priced/sized binary contract or correlated basket) gives $P^*_{\max}$ in the **5%–40% range** depending on assumptions, and that this probability is a smooth, computable, monotonically-responsive function of how much capital you commit (Table 4, §4). That is unambiguously the "moderately behind, maximum-risk-taking" regime, **not** the "far behind, give up" regime — **despite the superficial 7x/"−0.0000%" framing suggesting otherwise.** The apparent hopelessness is an artifact of evaluating the wrong strategy, not evidence about the true $P^*_{\max}$. This is the direct, decisive answer to the central question posed.

One caveat the Genakos-Pagliero setting doesn't have, and we do: their competitors choose among a few discrete barbell weights (bounded risk menu). We have access to **discontinuous, option-like payoff structures** (longshot binaries, parlays) that can manufacture far more convexity per dollar than a continuous-strategy-space contest allows. So even if we *were* in their "far behind" zone by their metric, the correct generalization of their finding to a market with embedded-leverage instruments is **not** "reduce risk" — it's "switch instrument class," which is exactly the barbell structure in §3.4.

### 2.3 Broader tournament-theory literature on risk vs. rank/time

- **Lazear, E.P. & Rosen, S. (1981).** "Rank-Order Tournaments as Optimum Labor Contracts." *JPE*, 89(5), 841–864. Establishes that rank-order (step-function) prizes are incentive-compatible compensation; the prize **spread** (gap between ranks), not the absolute performance, drives effort/risk. Here the spread is $\{\$30\text{k},\$5\text{k},\$2.5\text{k},0,0,\ldots\}$ — an extreme discontinuity at rank 3/4 — which theoretically should induce *maximal* risk-taking concentration right at that boundary, for anyone with a realistic shot.
- **Nalebuff, B.J. & Stiglitz, J.E. (1983).** "Prizes and Incentives: Towards a General Theory of Compensation and Competition." *Bell Journal of Economics*, 14(1), 21–43. Key additional insight used in §5.4: relative-performance schemes **filter out common shocks** — if everyone's outcome moves together (a correlated factor, exactly our "national swing" situation), a bet that only replicates what everyone else is doing doesn't change *relative* rank. This is a formal argument for **seeking differentiated, not consensus, convexity** (see §5.4).
- **Becker, B.E. & Huselid, M.A. (1992).** "The Incentive Effects of Tournament Compensation Systems." *Administrative Science Quarterly*, 37(2), 336–350. Empirically (race-car drivers): larger prize spreads → more risk-taking and more accidents, with diminishing/non-monotonic returns at extreme spreads — cautions that pushing risk-taking too far has a real "blow-up" cost, relevant to §4's negative-EV-threshold discussion.
- **Taylor, J. (2003).** "Risk-Taking Behavior in Mutual Fund Tournaments." *Journal of Economic Behavior & Organization*, 50(3), 373–383, building on **Brown, K.C., Harlow, W.V. & Starks, L.T. (1996).** "Of Tournaments and Temptations," *Journal of Finance*, 51(1), 85–110. Mid-year losers gamble in the second half; this is the direct precedent for "increase variance when behind, with time running out" in a *fund-manager* (not athlete) context — closest analogue to our actual situation (asset managers, not athletes, choosing portfolio variance).
- **Hvide, H.K. (2002).** "Tournament Rewards and Risk Taking." *Journal of Labor Economics*, 20(4), 877–898. Formal result: **convex, winner-take-most prize structures *equilibrium-induce* excessive risk-taking** relative to the social/organizational optimum — Hvide's proposed antidote is a "moderation" tournament that rewards consistency instead. **This is precisely the logic of a Sharpe-scaled Smart Score** (§6.3): the sponsor has, consciously or not, built a Hvide-style moderation counterweight into the recruiting metric specifically *because* tournament theory predicts convex prizes will otherwise induce exactly the behavior we are about to recommend.

---

## 3. The mathematics of multiplying capital 7x

### 3.1 Enumeration of structures

| Structure | Mechanism | Verdict |
|---|---|---|
| Leveraged/repeated Kelly compounding | Maximize $E[\log W]$ via repeated fractional betting | **Wrong tool** — Kelly is asymptotic-growth-optimal over *many* trials; we have *one* resolution event (§5.3) and a *short* horizon. Over-betting Kelly for goal-probability is a known, different problem (Browne, cited above) |
| Buying deep longshots outright | Pay $p$ for payout $1/p$ | Strictly negative EV given the 1.98x tax (shown below): **−49.5% per dollar staked**, constant regardless of depth |
| Concentrated single-factor directional bet | One large bet on the swing factor | Feasible, and the natural "bold play" instrument — analyzed in 3.2 |
| Correlated parlay/basket of same-direction binaries | Exploits correlation if venue/structure misprices it | **Best theoretical structure if validated** — analyzed in 3.3 |

### 3.2 Single-contract bold play — derivation

Buy a contract priced $p$ (pays 1 if it hits), staking fraction $f$ of $W_0$, sized so a win delivers **exactly** $G$ (bold play: never more, never less — that is the content of the Dubins–Savage theorem, generalized to odds-selection):

$$f^*(p)=\frac{G/W_0-1}{1/p-1},\qquad q_{\text{true}}=p/1.98 \text{ (measured tax)}$$

Solving for the price at which $f^*=1$ exactly (all remaining capital, no more available):

$$p^*=\frac{W_0}{G}=0.14283\ \Rightarrow\ \text{payout}=1/p^*=7.0014\text{x (exactly the required multiple)}$$

This is **not** a sub-$0.05 deep longshot — it sits *outside* our validated mispricing band. Two bounding cases:

- **Pessimistic** (assume the 1.98x tax extrapolates to $p=0.143$): $q=0.14283/1.98=\mathbf{7.21\%}$
- **Optimistic** (assume fair pricing at $p=0.143$, consistent with the general FLB finding — confirmed again by Snowberg, E. & Wolfers, J. (2010), "Explaining the Favorite-Longshot Bias: Is it Risk-Love or Misperceptions?" *JPE*, 118(4), 723–746 — that mispricing is concentrated at extreme prices and fades toward fair near the middle of the range): $q=p^*=\mathbf{14.28\%}$ (recovering the Dubins–Savage fair-game bound exactly)

**This is a 7–14% chance from a single, correctly-chosen bet, vs. the ~0.0000% from the core strategy.** This is the key quantitative finding of the whole analysis.

Full price curve (showing the whole feasible region):

| price $p$ | payout | $f^*$ | $q$ (1.98x tax) | feasible? |
|---|---|---|---|---|
| 0.03 | 33.3x | 18.6% | 1.52% | yes |
| 0.05 | 20.0x | 31.6% | 2.53% | yes |
| 0.10 | 10.0x | 66.7% | 5.05% | yes |
| **0.1428** | **7.00x** | **100%** | **7.21%** | **exactly binding** |
| 0.20 | 5.0x | 150% | — | **infeasible** |

### 3.3 Correlated parlays — where the real juice is

If a formal combo/parlay product exists that prices multi-leg bets by **naive independence** ($\prod p_i$) while true correlation (shared national swing factor) is $\rho>0$, the true joint probability is understated — potentially massively. I modeled this with the standard single-factor Gaussian-copula model used throughout credit-portfolio risk (Vasicek-style single-factor model: $M_i=\rho Z+\sqrt{1-\rho^2}\,\varepsilon_i$, outcome $i$ triggers if $M_i<\Phi^{-1}(p_i)$), fixing the **naive** total payout at exactly our required 7.0014x (so every structure below is an apples-to-apples alternative to the single contract in §3.2, at the same capital commitment):

| Structure (naive total = 7.00x) | per-leg price | $\rho=0.5$ | $\rho=0.7$ | $\rho=0.85$ |
|---|---|---|---|---|
| 1 leg (§3.2 baseline) | 0.1428 | — | — | 14.28% (fair) |
| 2-leg parlay | 0.378 each | 17.97% | 21.82% | 26.25% |
| 3-leg parlay | 0.523 each | 20.52% | 26.84% | 33.98% |
| 4-leg parlay | 0.615 each | 22.44% | 30.51% | 39.44% |

At realistic election-correlation levels, this **strictly dominates** even the fair-pricing single-contract bound. Intuitively: a 3–4-leg "parlay" of races each priced near 50/55% is not really diversifying at all under high correlation — it behaves like **a single leveraged bet on the swing factor**, and if the product prices it as if the legs were independent, you are buying that leveraged factor exposure at a steep discount. Expressed in Browne's $\theta$ units (§1.3): the taxed single contract has **effective $\theta=-1.31$** (worse than doing nothing); the fair single contract is **exactly $\theta=0$** by construction; the $\rho=0.7$ 2-leg parlay is **effective $\theta=+0.96$**; the $\rho=0.85$ 3-leg parlay is **effective $\theta=+2.18$** — a genuinely good Sharpe ratio, achieved with ≤100% capital and zero margin debt, in contrast to the 48x–480x leverage the core strategy would need to hit the same $\theta$.

**This is the resolution of the stated tension.** Our only validated directional edge (favorite-longshot overpricing) is inescapably short-convexity (selling a longshot and buying its complement/favorite are *the same cash flows* — both concave, both negative-skew, there is no way to express that edge with positive skew). But **a correlation mispricing is a logically distinct edge** from a probability-level mispricing, and it is the one edge that *can* be long-convexity while being consistent with (not contradicted by) everything we've validated, *because the national swing factor is explicitly given as a fact of the instrument universe, not an assumption I'm injecting.*

**Honest caveat — this is the single biggest assumption in this whole report:** we have **not validated** that (a) a formal parlay/combo product exists on this venue, or (b) that it is priced via naive independence rather than already correctly correlation-adjusted by informed flow. This must be tested with a small clip before sizing meaningfully (see §6.1).

### 3.4 Best construction: barbell, with low-beta legs funding the floor, not financing the bet

The literal "risk reversal" (sell a near tail to directly fund a specific convex purchase) **reintroduces fragility** if the sold and bought legs share the same risk factor — confirmed by standard options literature (a risk reversal is fundamentally a *directional*, not a *tail-hedging*, structure; Taleb, N.N. (2012), *Antifragile*, explicitly distinguishes his barbell — safety + small *outright* convex allocation — from financing convexity by selling tails, precisely because selling-to-fund reintroduces correlated short-gamma risk). Since **all contracts here load on one factor**, selling a longshot in a *competitive* race and buying convexity on the *same* swing factor is not a hedge, it's doubling the same bet.

The correct construction:
1. **Harvest the validated 1.98x edge** by selling/avoiding longshots (equivalently, buying favorites) specifically in **low-beta, "foregone conclusion" races** — contests where it would take an implausibly large swing-factor move to flip the outcome, so the position is nearly insensitive to the one risk factor that matters for the convex leg. This generates real, low-variance, genuinely diversifying-from-the-bet edge, consistent with the core's existing character.
2. **Deploy the convex sleeve concentrated in the single highest-beta "tipping point" race(s)** — competitive contests priced in the moderate-underdog range (§3.2–3.3's $p\approx0.10$–$0.55$ zone), **not** deep sub-0.05 longshots, both because the measured 1.98x tax is worst at the extreme and because that's where genuine factor-sensitivity (and thus cheap convexity) lives.
3. If a correlation-blind parlay product is confirmed (test first, §3.3's caveat), prefer it; if not, fall back to the single best-priced moderate-underdog contract.

This is explicitly *not* a hedge in the risk-neutral sense — it is a capital-allocation rule that keeps the two edges (a confirmed probability-mispricing edge and a hypothesized correlation-mispricing edge) from being stacked on the identical factor.

### 3.5 Why not leveraged Kelly compounding

Kelly/fractional-Kelly compounding is growth-rate-optimal over a long sequence of *independent, repeatable* bets — it is provably the wrong objective here for two separate reasons: (i) Browne's own work (§1.2) shows growth-optimal ≠ goal-probability-optimal, with the gap largest exactly when far behind with a near deadline; (ii) **there is no repeated sequence available** — see §5.3. Kelly is a solution to a problem we don't have.

---

## 4. Optimal allocation between core and sleeve

### 4.1 Formalization and derivation

Core keeps $(1-f)W_0$, growing negligibly relative to $G$ over 33 days (confirmed in Table 2 — its drift/vol are both irrelevant at this scale). Sleeve stakes $fW_0$ on a bet with payout odds $O$ (pays $O\times$stake if it hits) and true probability $q$. Goal is reached iff the sleeve hits **and** total wealth clears $G$:

$$(1-f)W_0+fW_0\cdot O\ \ge\ G \quad\Longrightarrow\quad f^*(O)=\frac{G/W_0-1}{O-1}$$

Because overshoot wastes capital without raising $P(\text{success})$ (identical bold-play logic to §1.1/§3.2), the goal-maximizer's sleeve size is **exactly** this minimum, not more: $P(\text{success})=q$, independent of $f$ once $f=f^*(O)$.

### 4.2 Across sleeve odds, including negative EV

$$f^*(O)=\frac{G/W_0-1}{O-1}=\frac{6.0014}{O-1}$$

| Payout $O$ | $f^*$ required | feasible? |
|---|---|---|
| 5x | 150.0% | **no** |
| 10x | 66.7% | yes |
| 20x | 31.6% | yes |
| 50x | 12.2% | yes |
| 100x | 6.1% | yes |

Critically, **$EV=q\cdot O-1$ is independent of which odds $O$ you pick and depends *only* on the tax/overpricing ratio** $\tau$ (since fair $q=1/O$, so $q_{\text{true}}=\tfrac{1}{O\tau}$, and $EV=\tfrac1\tau-1$):

| tax $\tau$ | EV per \$ staked |
|---|---|
| 1.00x (fair) | 0% |
| 1.20x | −16.7% |
| **1.98x (measured)** | **−49.5%** |
| 3.00x | −66.7% |
| 5.00x | −80.0% |

This cleanly separates two decisions: **$O$ (hence $f^*$) controls how much capital is at risk and what the resulting $q$ is; $\tau$ alone controls the cost rate.** Given $q_{\text{true}}=q_{\text{fair}}/\tau$ and $q_{\text{fair}}=1/O$, $q_{\text{true}}$ is *higher* for *lower* $O$ — i.e., **shallower bets (closer to even odds) give a higher chance of success per the same tax**, which is exactly why §3.2's $O\approx7$x result beats every deeper-odds alternative.

### 4.3 When does negative EV stop being worth it?

**Strict theory answer: never, as long as $q>0$ and $f^*\le1$.** This is the uncomfortable but mathematically correct consequence of pure goal-maximization against a ~0% baseline: any strictly positive $q$ beats certain failure, *no matter how negative the EV*, because the objective doesn't price the loss, only the binary outcome. This is the logical limit of the Dubins–Savage framework taken at face value, and it is important to say so explicitly rather than smuggle in risk-aversion.

**Practical answer — because the pure-theory answer is a cliff-edge with no footholds for actual sizing** — the decision-relevant threshold is not EV-based but:
1. **Statistical confidence in $q$ itself.** The 1.98x tax is validated at $p<0.05$, sign-test $p=3\times10^{-8}$ (strong). Extrapolating it to $p\approx0.10$–$0.50$ (where §3.2–3.3's best structures live) is *unvalidated* — favorite-longshot-bias literature (Snowberg & Wolfers 2010, cited above) supports the *direction* (fading toward fair near the middle), but not a specific number. Below roughly $q\lesssim1\%$, estimation error in the tax parameter starts to dominate the point estimate itself — a bet whose true edge you cannot distinguish from zero (or from catastrophically negative) is not a bet, it's noise.
2. **Cost per percentage point of goal-probability purchased**, $\$\text{spent}/(q\times100)$ — this explodes as $O$ grows (deeper odds) for a fixed tax, giving a natural, judgment-based stopping rule even absent hard risk-aversion.

### 4.4 Generalized trade-off (partial commitment)

Allowing $f<f^*(O)$ by holding back a buffer $(1-f)$ and finding correspondingly better odds $O_{\text{req}}(f)=\big(G/W_0-(1-f)\big)/f$ on the committed portion:

| Capital staked $f$ | kept safe | odds needed | $q$ fair | $q$ taxed 1.98x |
|---|---|---|---|---|
| 100% | 0% | 7.00x | 14.28% | 7.21% |
| 80% | 20% | 8.50x | 11.76% | 5.94% |
| **70%** | **30%** | **9.57x** | **10.45%** | **5.28%** |
| 60% | 40% | 11.00x | 9.09% | 4.59% |
| 50% | 50% | 13.00x | 7.69% | 3.88% |
| 30% | 70% | 21.0x | 4.76% | 2.40% |
| 15% | 85% | 41.0x | 2.44% | 1.23% |

This is the table that makes §6's recommendation concrete and non-arbitrary: **there is no free lunch in reducing stake size** — $q$ degrades roughly in proportion, not a cliff, so the fraction committed is a genuine dial, not a binary choice.

---

## 5. Rank dynamics and timing

### 5.1 Stochastic games / rank-based competition

**Citation:** Seel, C. & Strack, P. (2013). "Gambling in Contests." *Journal of Economic Theory*, 148(5), 2033–2048.

Model: each contestant privately controls a Brownian motion with absorbing ruin at 0 and chooses a stopping time; whoever stops highest wins. Core equilibrium result: a player who is behind (but not ruined) rationally **keeps gambling** rather than stopping, because stopping guarantees loss while continuing retains a chance of overtaking an unobserved leader — and this is a mixed-strategy equilibrium with a *cutoff* structure in the player's own value, directly paralleling the Genakos-Pagliero empirical inverted-U from a game-theoretic microfoundation. The dispersion of rivals' processes matters because, under private information about others' positions, your *posterior* on "how far behind I actually am" — not just your observed nominal rank — governs the optimal cutoff. **Practically: watch not just rank, but the implied dispersion of the leaderboard.** If dispersion is high (it clearly is here — 210th at +0.06% vs. 3rd at +600% after just one day), rivals' current positions are themselves highly volatile and *not yet realized* (see §5.5) — this should make us less willing to treat $G=700{,}557$ as a fixed target and more willing to treat it as a moving one to be re-estimated as the leaderboard evolves.

### 5.2 Early or late?

The textbook "option value of waiting" argument says: wait, because (a) information arrives steadily as November approaches (poll tightening/loosening re-prices which races are genuinely high-beta "tipping point" contests — exactly the legs needed for §3.3's structure), and (b) we get to observe competitors' moves and re-estimate $G$. But there are two countervailing forces that argue against waiting too long:

1. **Convergence to certainty.** As election night nears, genuine toss-ups resolve toward 0 or 1 (classic market-efficiency-into-expiry behavior). The moderate-underdog, $p\in[0.10,0.5]$ contracts that §3.2–3.3 identify as the efficient entry point **shrink in number and get more extreme** the longer we wait — waiting too long destroys the very instrument we need.
2. **Crowding/differentiation.** Nalebuff & Stiglitz's (1983) point that relative-performance schemes filter out common shocks has a sharp implication here: if many of the ~556 entrants are similarly far behind (plausible, given a step-function top-3 prize and 556 players), standard contest/DFS-tournament practitioner logic (GPP "guaranteed prize pool" strategy — large-field, winner-take-most contests) says laggards rationally converge on the *same* obvious convex trades late in the window. If our bet is identical to what dozens of rivals also buy, **a correlated win doesn't improve relative rank** — everyone who piles into the same swing-factor trade rises together. This is a second, independent argument for **differentiated** convexity (an under-crowded high-beta race, not the headline one) and for **not** waiting until the last days when this crowding is most intense and pricing is most degraded by demand.

**Conclusion: construct the position in the first third-to-half of the remaining window** (roughly days 3–15 of the 33), monitoring the live leaderboard and adjusting size/structure as better-priced high-beta legs appear or as $G$ moves, rather than at either extreme (day-1 haste, or last-minute crowding).

### 5.3 Same-day settlement: the critical structural fact

**All contracts resolve simultaneously on election night. There is no sequential win→re-bet loop.** This has two major consequences that depart from the textbook treatment:

1. **Classical "bold play" and Kelly compounding both implicitly assume repeated, sequentially-observed trials** — that is precisely the mechanism that makes "many small timid bets" work in a superfair game (§1.1) and makes Kelly's $E[\log W]$ asymptotics meaningful. **Neither mechanism is available to us.** The problem fully collapses to a **single static (or quasi-static, rebalanced only on *price* information, never on *outcome* information) portfolio-construction problem**, which is exactly what §1.2's Browne/digital-option framework and §3–4's bold-play sizing already assume — reassuringly, the right theory for our actual constraint is the one already in use, not a sequential one.
2. **A parlay/basket is not a structurally awkward compromise here — it's the natural unit.** In a sequential-settlement world, combining legs into a parlay sacrifices optionality (you're locked into leg 2 before learning leg 1's outcome). Here, you were never going to learn any leg's outcome before the others anyway — **holding several correlated single-outcome contracts and holding a formal "parlay" are economically identical in terms of information structure**, so the correlation-mispricing argument in §3.3 is not fighting an awkward structural mismatch; it fits the instrument exactly.

### 5.4/5.5 Why $G$ itself should be treated as a live random variable, not a constant

Since nothing settles until election night, **the current 3rd-place balance of ~700,557 is an unrealized, mark-to-market position on contracts that have not resolved** — not a locked-in result. There is real two-sided risk remaining in whatever position produced that balance. This means the "observe the leaderboard live" instruction in the prompt is not incidental — it is the mechanism by which we should be **continuously re-solving §4's tables with an updated $G$**, not committing once against today's snapshot. A rational policy re-prices $f^*(O)$ and the required odds daily against the live 3rd-place value, and is prepared for $G$ to fall (if leaders' unrealized gains partially unwind) as well as rise.

---

## 6. Bottom line

### 6.1 Concrete recommendation

- **≈65–70% of current capital ($65k–$70k) into the convex sleeve**, structured per §3.4:
 - First choice (pending a cheap validation trade, §3.3's caveat): a 2–3 leg same-direction basket/parlay on the **highest-beta, moderate-odds** (not deep-longshot) tipping-point races, naive-priced total payout targeted at **≈9.5–11x** on the staked amount (Table in §4.4, $f=0.60$–$0.70$).
 - Fallback (no parlay product, or correlation edge unconfirmed): a **single** contract priced near $p\approx0.10$ (outside the validated extreme-tax band), same capital fraction, same target odds.
 - This delivers an estimated **$P(\text{podium})\approx5\%$–$10\%$ pessimistic (full 1.98x tax applies here) to $20\%$–$35\%+$ optimistic (fair pricing or confirmed correlation mispricing)** — versus the core's **0.0000%**.
- **~30–35% ($30k–$35k) held back**, split between (a) continued core grinding — it remains the single best Sharpe-generating activity we have and should keep running regardless, and (b) harvesting the validated 1.98x edge by selling/avoiding longshots specifically in **low-beta, foregone-conclusion races**, which both adds real expected value and deliberately avoids stacking the same swing-factor risk as the sleeve (§3.4).
- **Deploy in the first third-to-half of the remaining 33 days**, not immediately and not at the deadline (§5.2), reassessing size and structure daily against the live leaderboard feed, since $G$ itself is not yet a realized, fixed number (§5.5).
- **Validate the parlay/correlation-mispricing hypothesis with a small clip (≤1–2% of capital) before committing the full sleeve to it** — this is the one load-bearing assumption in the whole recommendation that is genuinely untested.

### 6.2 Conditions under which I would instead recommend accepting a high-Sharpe/no-podium outcome

Reverse course to pure core-grinding (explicitly forfeiting the podium) if **any** of the following bind:
- No contract or structure can be found priced such that the implied $q$ clears roughly 2–3%, i.e., no moderate-odds instrument exists outside the deep sub-0.05 band (the "cost per percentage point" in §4.3 becomes unbounded, and the bet is statistically indistinguishable from a pure loss).
- The small-clip test of the parlay/correlation hypothesis (§3.3) fails to confirm a naive-independence pricing product exists, **and** no single contract is found priced efficiently (tax-free) in the $p\in[0.08,0.2]$ range — i.e., the only available instruments are deep, confirmed-mispriced longshots, pushing $P(\text{podium})$ below roughly 1–2%.
- The Smart Score / recruiting mandate turns out to carry a **hard gate** (e.g., a minimum Sharpe floor for consideration), rather than being merely a soft, continuously-scaled secondary metric — in which case §6.3's numbers show the sleeve would very likely breach it.
- Any externally-imposed risk limit (max single-position size, max daily VaR/drawdown) prohibits committing >~30–40% of capital to one correlated factor bet.

### 6.3 Smart Score / Sharpe tradeoff, quantified

I modeled the account's realized 34-day Sharpe ratio under the recommended structure directly (daily core returns at the observed $+0.06\%$/day for 33 days, the sleeve resolving on the final day):

| Branch | Probability (taxed case) | Realized 34-day annualized Sharpe |
|---|---|---|
| Pure core only (no sleeve) | — | ≈ 5–10 (whatever the core's true Sharpe is) |
| Sleeve **loses** | ≈95% | **≈ −2.6 to −3.2** |
| Sleeve **wins** (podium!) | ≈5% | **≈ +3.3** |
| **Expected realized Sharpe** | | **≈ −2.3 to −2.6** |

The striking, decision-relevant point: **even in the branch where the sleeve wins and we take 2nd or 3rd place, the realized Sharpe ratio is *lower* than the pure-core baseline would have been** — because Sharpe penalizes the *dispersion* of returns symmetrically, and a single enormous positive day inflates measured volatility just as a single enormous negative day does. This is not a minor side effect; it is a structural, quantified conflict: **the prize objective (step function on rank, rewarding a fat right tail) and the Smart Score objective (penalizing any deviation from a smooth, low-variance return path) are driven by opposite properties of the same return distribution.** There is no allocation that scores well on both simultaneously — this is exactly Hvide's (2002) point that convex tournament prizes and "moderation"-style evaluation are in direct tension by construction, applied numerically to our own book. Going for the podium costs, in expectation, roughly **7–10 Sharpe-points** of recruiting signal, for a 5–35% shot at $2,500–$30,000. That is the trade the user needs to sign off on explicitly; the math does not make the choice, it only prices it.

---

## References

1. Dubins, L.E. & Savage, L.J. (1965/1976). *How to Gamble If You Must: Inequalities for Stochastic Processes*. McGraw-Hill / Dover.
2. Pestien, V.C. & Sudderth, W.D. (1985). "Continuous-Time Red and Black." *Mathematics of Operations Research*, 10(4), 599–611.
3. Kulldorff, M. (1993). "Optimal Control of Favorable Games with a Time Limit." *SIAM J. Control Optim.*, 31(1), 52–69.
4. Browne, S. (1999). "Reaching Goals by a Deadline: Digital Options and Continuous-Time Active Portfolio Management." *Advances in Applied Probability*, 31(2), 551–577. https://ssrn.com/abstract=703
5. Browne, S. "Portfolio Choice and the Bayesian Kelly Criterion." *Advances in Applied Probability* (JSTOR 1428168).
6. Föllmer, H. & Leukert, P. (1999). "Quantile Hedging." *Finance and Stochastics*, 3(3), 251–273.
7. Kelly, J.L. (1956). "A New Interpretation of Information Rate." *Bell System Technical Journal*, 35(4), 917–926.
8. Genakos, C. & Pagliero, M. (2012). "Interim Rank, Risk Taking, and Performance in Dynamic Tournaments." *JPE*, 120(4), 782–813.
9. Lazear, E.P. & Rosen, S. (1981). "Rank-Order Tournaments as Optimum Labor Contracts." *JPE*, 89(5), 841–864.
10. Nalebuff, B.J. & Stiglitz, J.E. (1983). "Prizes and Incentives." *Bell Journal of Economics*, 14(1), 21–43.
11. Becker, B.E. & Huselid, M.A. (1992). "The Incentive Effects of Tournament Compensation Systems." *Administrative Science Quarterly*, 37(2), 336–350.
12. Taylor, J. (2003). "Risk-Taking Behavior in Mutual Fund Tournaments." *J. Economic Behavior & Organization*, 50(3), 373–383.
13. Brown, K.C., Harlow, W.V. & Starks, L.T. (1996). "Of Tournaments and Temptations." *Journal of Finance*, 51(1), 85–110.
14. Hvide, H.K. (2002). "Tournament Rewards and Risk Taking." *Journal of Labor Economics*, 20(4), 877–898.
15. Seel, C. & Strack, P. (2013). "Gambling in Contests." *Journal of Economic Theory*, 148(5), 2033–2048.
16. Snowberg, E. & Wolfers, J. (2010). "Explaining the Favorite-Longshot Bias." *JPE*, 118(4), 723–746.
17. Taleb, N.N. (2012). *Antifragile: Things That Gain from Disorder*. Random House.

## Gaps and uncertainties (explicit)

- **Core strategy's true annualized Sharpe/volatility is not given** — I bracketed [2,20] throughout; the core-is-hopeless conclusion is robust to this entire range (Table 2/3), so this gap doesn't affect the main recommendation.
- **Whether this venue offers a formal parlay/combo product, and whether it prices via naive independence, is unverified** — this is the single largest assumption behind the optimistic end of the probability range; I explicitly recommend testing it with minimal capital first.
- **Whether the 1.98x tax extrapolates to $p\approx0.10$–$0.5$ is unverified** — only sub-0.05 is stated as measured; I used the general FLB finding (mispricing fades toward fair near the middle of the range) to justify treating the optimistic case as plausible, bracketed against the pessimistic full-extrapolation case throughout.
- **The Smart Score formula itself is not specified** — I modeled it as a Sharpe-ratio-based metric per the prompt's own description ("Sharpe-scaled volatility") and computed the realized-Sharpe damage directly; if the actual formula weights other factors, §6.3's numbers would need updating but the qualitative conflict (fat-tail prize vs. low-variance score) is structural and would persist under essentially any Sharpe-like scoring rule.
- **True cross-race correlation $\rho$ for this specific election cycle is not measured here** — I used a standard single-factor model across a plausible range (0.3–0.95); this should be estimated directly from the venue's own price co-movements before sizing the parlay leg.