Agent is idle (waiting for messages). agent_id: c9616810-cd2e-4c32-988b-a930d5414cc6, agent_type: research, status: idle, description: Optimal market making theory, elapsed: 1825s, total_turns: 1

[Turn 0]
# Optimal Market Making for Binary Election Contracts: Theory, Gaps, and Implementation

**Notation used throughout:** $p$ = current mid/fair probability (price); $q$ = signed inventory (shares, + = long "Yes"); $\gamma$ = CARA risk-aversion coefficient; $\tau = T-t$ = time to settlement; $\delta$ = quote depth (distance from mid); $\lambda(\delta)=Ae^{-k\delta}$ = fill-intensity; $\sigma^2$ = instantaneous variance rate of $p$. I mark every claim **[ESTABLISHED]** (published result, cited) or **[DERIVED]** (my own derivation — steps shown) or **[GAP]** (literature does not cover this case). Tick size = 0.005, price $\in[0.005,0.995]$.

---

## 0. Calibration snapshot (from your numbers)

I fit $\lambda(\delta)=Ae^{-k\delta}$ ($\delta$ in ticks) to your five measured points by log-linear regression:

| δ (ticks) | 1 | 3 | 6 | 16 | 30 |
|---|---|---|---|---|---|
| measured λ | 3.17 | 1.90 | 0.886 | 0.069 | 0.002 |
| fitted $Ae^{-k\delta}$ | 3.156 | 1.899 | 0.886 | 0.0698 | 0.0020 |

**Result: $A = 4.07$ fills/order-hour, $k = 0.254$/tick ($R^2=0.99999$ in log-space).** The local secant slope between *every* consecutive pair is 0.253–0.256 — this is a genuinely clean exponential over the full 1–30 tick range, not a local approximation. In price units, $k_{price}=k/\text{tick}=50.8$ per unit probability. Half-life of fill rate = $\ln2/k = 2.73$ ticks. This single calibrated pair feeds Sections 1, 4 and 6 directly.

---

## 1. Avellaneda–Stoikov and descendants

### 1.1 Canonical formulas **[ESTABLISHED]**

Avellaneda & Stoikov (2008), *"High-frequency trading in a limit order book,"* Quantitative Finance 8(3):217–224 (reprint: https://www.math.nyu.edu/~avellane/HighFrequencyTrading.pdf). Mid-price $dS_t=\sigma dW_t$ (arithmetic BM, no drift), CARA utility $-e^{-\gamma W_T}$, order arrivals Poisson with $\lambda(\delta)=Ae^{-k\delta}$.

**Reservation price:**
$$r(s,q,t) = s - q\,\gamma\,\sigma^2\,(T-t)$$

**Optimal (total) spread:**
$$\delta^a+\delta^b = \gamma\sigma^2(T-t) + \frac{2}{\gamma}\ln\!\Big(1+\frac{\gamma}{k}\Big)$$

Quotes: $\text{bid}=r-\delta^b$, $\text{ask}=r+\delta^a$ (symmetric split in the original paper; GLFT below gives the exact asymmetric split).

### 1.2 Guéant–Lehalle–Fernandez-Tapia (GLFT) — exact and closed-form **[ESTABLISHED]**

Guéant, Lehalle & Fernandez-Tapia (2013), *"Dealing with the inventory risk: a solution to the market making problem,"* Math. & Financial Economics 7(4):477–507, arXiv:1105.3115. They reduce the HJB PDE to a linear ODE system $\dot v_q(t)=\alpha q^2 v_q(t)-\eta(v_{q-1}+v_{q+1})$, $\alpha=\tfrac{k}{2}\gamma\sigma^2$, $\eta=A(1+\gamma/k)^{-(1+k/\gamma)}$, giving the **exact** (not approximate) optimal quotes (their Thm. 1):
$$\delta^{b*}(t,q)=\frac1k\ln\!\frac{v_q(t)}{v_{q+1}(t)}+\frac1\gamma\ln\!\Big(1+\frac\gamma k\Big),\qquad \delta^{a*}(t,q)=\frac1k\ln\!\frac{v_q(t)}{v_{q-1}(t)}+\frac1\gamma\ln\!\Big(1+\frac\gamma k\Big)$$

As $T-t\to\infty$ this converges to a **closed-form asymptotic approximation** (their Prop. 3, via a Gaussian eigenfunction approximation):
$$\delta^{b*}_\infty(q)\simeq \underbrace{\frac1\gamma\ln\!\Big(1+\frac\gamma k\Big)}_{c_1\text{ (microstructure floor)}} + \frac{2q+1}{2}\underbrace{\sqrt{\frac{\sigma^2\gamma}{2kA}\Big(1+\frac\gamma k\Big)^{1+k/\gamma}}}_{c_2\text{ (inventory slope)}},\qquad \delta^{a*}_\infty(q)\simeq c_1 - \frac{2q-1}{2}c_2$$
$$\Rightarrow \text{spread } \psi_\infty^*=2c_1+c_2,\qquad \text{quote-center skew} = -q\cdot c_2$$

Note the $(T-t)$-dependence has *vanished* — this is the stationary/turnpike regime, valid whenever $T-t$ is large relative to the order-flow relaxation time $\sim 1/k$ (minutes–hours here, so valid almost everywhere in your 33-day window except the final hours — see §1.4).

### 1.3 The right diffusion for a [0,1] terminal-binary martingale

**AS's arithmetic BM is wrong for you** — unbounded support, constant variance, no mechanism to land on $\{0,1\}$. Candidates, and what the literature actually says:

- **Jacobi / Wright–Fisher diffusion** $dp_t=\sigma_0\sqrt{p_t(1-p_t)}\,dW_t$ (plus optional mean-reversion $\kappa(\theta-p_t)dt$). **[ESTABLISHED as a modeling tool, but not for order-book market making.]** This is literally the classical population-genetics diffusion (Karlin & Taylor, *A Second Course in Stochastic Processes*, 1981; Ethier & Kurtz, *Markov Processes*, 1986) and is the standard choice in finance **when a bounded [0,1]-valued state variable is needed**: Ackerer, Filipović & Pulido (2018), *"The Jacobi Stochastic Volatility Model,"* Finance and Stochastics 22(3):667–700, arXiv:1605.07099 (general form $dV_t=\kappa(\theta-V_t)dt+\sigma\sqrt{Q(V_t)}dW_t$, $Q(v)=\frac{(v-v_{\min})(v_{\max}-v)}{(\sqrt{v_{\max}}-\sqrt{v_{\min}})^2}$, which collapses to exactly $v(1-v)$ on $[0,1]$); Delbaen & Shirakawa (2002) use it for bounded interest rates; Gourieroux & Jasiak (2006, J. Econometrics) for stochastic correlation; Ahdida & Alfonsi, and Bernis & Scotti, for correlation matrices / CDS indices. **The diffusion coefficient $\sqrt{p(1-p)}$ is the unique (up to scale) power-law local-vol function consistent with 0 and 1 being attainable/natural boundaries** (Feller test) — this is *why* it's standard, not an arbitrary choice.
- **Logit-OU** ($\ln\frac{p}{1-p}$ mean-reverting / random walk). **[ESTABLISHED for forecasting, NOT for the tradeable price.]** This is the workhorse of the *election-forecasting* literature (e.g., Linzer (2013), *"Dynamic Bayesian Forecasting of Presidential Elections in the States,"* JASA 108:124–134, uses a random walk on a transformed vote-share). **Important critique [DERIVED]:** if $z_t=\text{logit}(p_t)$ is a driftless martingale, $p_t=\text{sigmoid}(z_t)$ is *not* a martingale (Jensen's inequality — sigmoid is neither convex nor concave globally, so $E[\sigma(z_t)]$ drifts). A tradeable, efficiently-priced contract's $p_t$ must be a martingale (it *is* the conditional expectation of the $\{0,1\}$ payoff). So logit-OU is appropriate for modeling the *latent fundamental* (what forecasters do), not the *price process* a market maker needs for its own risk model. Don't import election-forecasting dynamics directly into the quoting engine.
- **Brownian-bridge-to-$\{0,1\}$:** a classical bridge has a *known* deterministic terminal value; here the terminal value is *random* ($X\sim\text{Bernoulli}(p_t)$, revealed at $T$). This is not a bridge in the technical sense — it's closer to a martingale observed up to a fixed horizon followed by an independent reveal. The cleanest rigorous statement of the constraint this implies is the identity in §1.3.1 below.

**[GAP, explicit]:** I did not find any published paper that solves an Avellaneda-Stoikov/GLFT-style HJB control problem with a Jacobi (or any bounded-martingale) price process. Everything below in §1.3.1–1.4 combining AS/GLFT control with bounded dynamics is **my own derivation**, built from established pieces (GLFT's control framework + the Jacobi functional form + a martingale identity below). Practitioner treatments I found (quant blogs, GitHub AS implementations) handle boundedness by **clipping quotes to $[0,1]$ post-hoc** with constant $\sigma$ — this is exactly the naive approach the prompt (correctly) flags as wrong: it doesn't make volatility vanish near the boundary, it just truncates a wrong quote.

#### 1.3.1 The exact model-free variance constraint **[DERIVED, grounded in Augenblick & Rabin 2021]**

Let $p_t=E[X\mid\mathcal F_t]$, $X\in\{0,1\}$ revealed at $T$. By the law of total variance applied across $[t,T]$ and Itô's lemma on $f(p)=p(1-p)$ (so $df=-\sigma(p_u)^2\,du + \text{mart.}$):
$$E\big[p_T(1-p_T)\mid\mathcal F_t\big] - p_t(1-p_t) = -E\Big[\int_t^T \sigma(p_u,u)^2\,du \,\Big|\,\mathcal F_t\Big]$$
Since $X\in\{0,1\}\Rightarrow p_T(1-p_T)=0$ always:
$$\boxed{E\Big[\int_t^T \sigma(p_u,u)^2\,du\,\Big|\,\mathcal F_t\Big] = p_t(1-p_t)}$$

This is an *exact*, model-free identity: **expected remaining quadratic variation equals current Bernoulli variance.** I verified it is precisely the continuous-time (quadratic-variation) analogue of the discrete-time result in **Augenblick & Rabin (2021), *"Belief Movement, Uncertainty Reduction, and Rational Updating,"* QJE 136(2):933–985**, who define uncertainty $\pi_t(1-\pi_t)$ and prove that for *any* Bayesian belief sequence, **expected movement = expected uncertainty reduction** — i.e., $E[\sum(\Delta\pi)^2] = \pi_0(1-\pi_0) - E[\pi_{\text{final}}(1-\pi_{\text{final}})]$, which is exactly my identity when the terminal belief is $\{0,1\}$. They use this as a statistical test of rational updating on real prediction-market and sports-prediction data — it is empirically tractable, not just theory.

**Implication [DERIVED]:** if you posit the self-consistent "crude" functional form (freezing $p_u\approx p_t$ over $[t,T]$, consistent with Jacobi's $\sigma(p)=\sigma_0\sqrt{p(1-p)}$ form):
$$\sigma(p_t,\tau)^2 \;=\; \kappa\cdot\frac{p_t(1-p_t)}{\tau},\qquad \tau=T-t,\ \kappa\approx 1\text{ (calibrate)}$$
i.e. **instantaneous variance rate must *rise* as $\tau\to0$** (not fall) to deliver the fixed total variance $p(1-p)$ over a shrinking window — the opposite of naive-AS's implicit assumption of constant $\sigma$.

### 1.4 Behavior as $T\to0$ and near $p\to\{0,1\}$ — the corrected skew **[DERIVED]**

Substitute $\sigma(p,\tau)^2=p(1-p)/\tau$ into AS's reservation skew:
$$r = p - q\gamma\sigma^2\tau = p - q\gamma\cdot\frac{p(1-p)}{\tau}\cdot\tau = p - q\gamma\, p(1-p)$$
**The $\tau$ cancels.** This is the headline result for your "T→0" question:

| Regime | Naive constant-$\sigma$ AS | Corrected (Jacobi-consistent) |
|---|---|---|
| $p\to\{0,1\}$, any $\tau$ | skew/spread stay whatever constant-$\sigma$ says — **wrong, doesn't vanish** | skew $\to0$, spread risk-term $\to0$ ∝ $p(1-p)$ — **correct** |
| $\tau\to0$, $p\approx0.5$ | skew/spread $\to0$ — **wrong: a true coin-flip two hours before resolution is not low-risk** | skew stays at $-q\gamma p(1-p)$, **does not shrink** — captures that terminal uncertainty is still being resolved |
| $\tau\to0$ **and** $p\to\{0,1\}$ | shrinks for wrong reason | shrinks for right reason (bounded martingale pinned near boundary has ~no variance left to resolve) |

**This is the corrected inventory-skew term you asked for:**
$$\text{skew}(p,\tau\to\text{anything away from 0})\;\approx\;-q\,\gamma\, p(1-p)\quad(\tau\text{-independent})$$
Practical reading: **don't mechanically tighten spread/skew as election day approaches just because "less time is left."** Tighten only because $p$ itself has moved toward 0/1. A 50/50 toss-up race two days out carries just as much per-share inventory risk as the same race three weeks out — arguably more, since the ways by which 0.50 can still jump to 0 or 1 are compressed into less calendar time (news arrival rate ramps up, not down, into election night).

**Caveat [DERIVED/honest]:** the Jacobi/diffusion picture is a *continuous* approximation. Real tail risk near an election is partly **discontinuous/jump** (a scandal, a called race, a leaked exit poll) that a diffusion coefficient — however correctly shaped — does not price. This is consistent with what I found in the **Kalshi microstructure data**: Bürgi, Deng & Whelan (2026), *"Makers and Takers: The Economics of the Kalshi Prediction Market,"* GWU CER WP 2026-001 (https://www2.gwu.edu/~forcpgm/2026-001.pdf), report **bid-ask spreads larger as a fraction of price for cheap (longshot) contracts**, and Dubach (2026), *"The Anatomy of a Decentralized Prediction Market,"* arXiv:2604.24366, finds on Polymarket a **longshot spread premium**: quoted half-spread ≈ 400bps at mid-range prices, climbing to **650–900bps below $p=0.10$** — asymmetric (wide on the low-probability side only), which the author attributes to "a bounded upside and asymmetric downside for the maker" on longshots. **Recommendation:** keep a small *jump-risk floor* added to the diffusive spread near the boundary — don't let the theoretical $p(1-p)\to0$ term drive the quoted spread literally to zero. Calibrate this floor from the empirical tape (e.g., realized jump frequency/size for contracts that were at $p<0.05$ and still moved the full way against you), not from the diffusion model.

### 1.5 Does the GLFT closed form survive? **[DERIVED answer: partially, as a local approximation]**

GLFT's $c_1,c_2$ assume **constant** $\sigma,k,A$ over $[t,T]$. With $\sigma(p,\tau)^2=p(1-p)/\tau$ time- *and* state-varying, the exact ODE system no longer applies as stated. Two usable facts:

1. **The microstructure floor $c_1=\frac1\gamma\ln(1+\gamma/k)$ never involved $\sigma$ at all** — it comes purely from the $\lambda$ vs. margin trade-off (§4). It survives unchanged.
2. **The inventory slope $c_2$ can be used as a "frozen-coefficient" / adiabatic approximation:** recompute $\sigma_t^2=p_t(1-p_t)/\tau$ at every quote refresh and plug into $c_2$ as if constant over the next instant. This is valid exactly when $\sigma_t^2$ changes slowly relative to the order-flow relaxation time $1/k\approx 3.9$ ticks worth of time $\approx$ minutes — true for essentially your whole 33-day horizon, **false in the final hours** (§6, regime switch).

**I numerically checked how much $c_2$'s Gaussian approximation diverges from the exact CARA-binary formula of §2** (illustrative $\gamma$ calibrated so 100 shares ≈ 1 tick of skew at $p=0.5$): the ratio (GLFT-asymptotic skew)/(exact skew) ranges **0.5× at $p=0.5$, far from close, to 3.1× at $p=0.05$, 3 days out** — i.e., **GLFT's Gaussian approximation materially over- or under-states skew specifically in the regime you care about most (extreme $p$, close to $T$).** 

**Recommendation [DERIVED]:** use GLFT's $c_1$ for the spread floor (unaffected by boundedness), but replace $c_2\cdot q$ with the **exact** CARA-binary skew from §2 for the inventory term. This is a hybrid I'm proposing, not a published result — but each half is separately well-founded, and it is strictly simpler to implement than GLFT's $c_2$ (one `exp()` call, no square root of $(1+\gamma/k)^{1+k/\gamma}$).

---

## 2. Inventory skewing, specialized

### 2.1 Exact CARA utility on a Bernoulli terminal payoff **[DERIVED]**

For a binary contract, terminal wealth is $W_T=C_T+qX$, $X\sim\text{Bernoulli}(p)$ — **exactly**, no Gaussian approximation needed (unlike AS, where $W_T$ is treated as approximately Gaussian via $q\cdot\sigma\sqrt T$). CARA utility:
$$-E[e^{-\gamma W_T}] = -e^{-\gamma C_T}\big[(1-p) + p\,e^{-\gamma q}\big]$$
Certainty-equivalent value of carrying $q$ (ignoring cash, which enters additively): $f(q) = -\frac1\gamma\ln\big[(1-p)+pe^{-\gamma q}\big]$. The marginal/continuous reservation price is $f'(q)$:
$$f'(q) = \frac{p\,e^{-\gamma q}}{(1-p)+p\,e^{-\gamma q}}$$

Rewritten (verified symbolically with `sympy`), this is **a pure shift in log-odds**:
$$\boxed{r(p,q) = \text{sigmoid}\big(\text{logit}(p) - \gamma q\big)},\qquad \text{logit}(p)=\ln\frac{p}{1-p}$$

**Properties (symbolically verified):**
- $r(p,0)=p$ ✓.
- $\dfrac{\partial r}{\partial q} = -\gamma\, r(1-r)$ — **exactly** the "maximal at $p=0.5$, vanishes at boundaries" shape you asked for, derived from first principles, not assumed. At $p=0.5$: slope $=-\gamma/4$ (max magnitude). As $p\to0,1$: slope $\to0$.
- $r\in(0,1)$ for **every finite $q$** — unlike linear-in-$q$ AS skew $p-q\gamma\sigma^2\tau$, which can blow through 0 or 1 for large $q$ (a real bug risk in a naive port of AS to a probability-bounded book). Boundary limits: $r\to0$ as $q\to+\infty$, $r\to1$ as $q\to-\infty$ (you become unwilling to pay anything more once very long; willing to pay almost 1 to cover once very short) — economically correct.
- **Taylor expansion confirms consistency with §1.4:** $r(p,q)\approx p - \gamma q\,p(1-p) + O(q^2)$ — the linear-in-$q$ term has coefficient $-\gamma p(1-p)$, exactly matching the $\tau$-independent corrected AS skew derived above. The exact binary-CARA formula is the natural *bounded completion* of that result.
- This exact formula needs **no $\sigma$, no $\tau$ at all** — a major practical simplification: the skew model and the diffusion/vol model can be estimated and maintained completely independently.

(Historical note: this is a special case of **exponential-tilting / Esscher-transform utility-indifference pricing** — a standard technique, e.g. Gerber & Shiu (1994); I am not aware of it being written out for the binary/prediction-market case specifically, hence flagged [DERIVED].)

### 2.2 Three risk measures, three skew formulas

| Risk measure | Objective | Resulting skew | Notes |
|---|---|---|---|
| **Variance of terminal wealth (mean-variance)** | $\max\; E[W_T]-\frac\gamma2\mathrm{Var}(W_T)$; $\mathrm{Var}(qX)=q^2p(1-p)$ | $r_{MV}=p-\gamma q\,p(1-p)$ **[DERIVED]** | Linear in $q$; identical to the small-$q$ limit of the exact formula above. Cheapest to compute, breaks boundedness for large $|q|$. |
| **CARA (exact)** | $\max -E[e^{-\gamma W_T}]$, exact Bernoulli | $r=\text{sigmoid}(\text{logit}(p)-\gamma q)$ **[DERIVED, §2.1]** | Recommended default — bounded, exact, cheap (one exp call). |
| **Drawdown/ruin (chance-constrained)** | choose position limits s.t. $P(\text{loss}>L)\le\varepsilon$ | position cap $q_{\max}$ such that $(1-p)\,q_{\max}\cdot\bar c \le$ risk budget, where $\bar c$=avg cost basis **[DERIVED]**; portfolio level: $\text{VaR}_\varepsilon\approx z_\varepsilon\sqrt{q^\top\Sigma q}$ using the covariance structure of §5 | This is a **position-size cap**, not a skew — it sets the boundary of $q$ beyond which you stop quoting on the adding side entirely, independent of price. |

**Kelly/growth-optimal cross-check [ESTABLISHED, Kelly (1956), *"A New Interpretation of Information Rate,"* Bell Syst. Tech. J. 35(4):917–926]:** for a single binary contract bought at price $p$ with true probability estimate $\hat p$, the growth-optimal (log-utility) stake fraction of bankroll is
$$f^* = \frac{\hat p - p}{1-p}$$
This is a **different utility paradigm** (relative risk aversion, growth-optimal) from CARA (constant absolute risk aversion) used everywhere else in this report — don't mix them in the same formula. Its practical use here is narrower and specific: it's the right tool for setting your **overall capital deployment fraction** (your 3%/5% cap), not for per-quote skewing. With a typical edge of one tick ($\hat p-p\approx0.005$) and average $p\approx0.3$, a single-market Kelly stake is $\approx0.005/0.7\approx0.7\%$ of bankroll — but across ~120 simultaneously correlated opportunities, naively summing single-asset Kelly fractions **over-levers** (ignores the covariance structure). The correct correction uses the same factor decomposition as §5: scale down the naive sum by a diversification ratio computed from net factor exposure vs. gross exposure (§5.3) — i.e., Kelly, mean-variance VaR, and the multi-asset covariance penalty are three views of the *same* underlying quadratic form $q^\top\Sigma q$.

---

## 3. Adverse selection and queue position

### 3.1 Glosten-Milgrom, specialized to a binary payoff

**[ESTABLISHED]** Glosten & Milgrom (1985), *"Bid, ask and transaction prices in a specialist market with heterogeneously informed traders,"* J. Financial Economics 14(1):71–100. Setup: value $V\in\{V_H,V_L\}$, prior $\theta$, fraction $\pi$ of arriving flow informed (always trades correctly), $1-\pi$ noise (trades randomly). Zero-profit, competitive, risk-neutral dealer sets $a=E[V\mid\text{buy}]$, $b=E[V\mid\text{sell}]$.

**[DERIVED]** — specializing exactly to our case, $V_H=1,V_L=0,\theta=p$ (so the prior *is* the market price, as it must be for a well-formed binary contract), I derive (full algebra, verified symbolically) the **general-$p$** spread:
$$\text{spread}(p,\pi) = \frac{4\pi\,p(1-p)}{1-\pi^2(2p-1)^2}$$
Checks: at $p=0.5$: spread$=\pi$ (matches the textbook symmetric-prior case). At $\pi=1$: spread$=1$ for all $p$ (full revelation). **At $p\to0$ or $p\to1$ (any $\pi<1$): spread $\to0$.** This is an entirely independent confirmation — from pure adverse-selection theory, with zero reference to diffusion models — of the same qualitative result as §1.4: **the informed-trading component of spread must vanish near the boundary.** Two unrelated mechanisms (bounded-diffusion variance vanishing, and adverse-selection-driven spread vanishing) point to the same quoting behavior, which is reassuring.

**Practical use:** given an estimate $\hat\pi$ of informed-flow probability, $\text{spread}(p,\hat\pi)$ is your **minimum viable spread against informed flow alone** (floor; add the inventory and microstructure-floor terms on top, they are additive/separate effects in this literature — GM is pure adverse selection, AS/GLFT is pure inventory+flow-elasticity, real quoted spread should reflect both).

### 3.2 Your measured 119%/138% retention: genuine, or an artifact?

Recall your numbers: effective half-spread captured at execution ≈ 0.0049; markout improves to +0.006 by 5–30 min (retention ≈122–138%); **then decays through zero to −0.0019 by 240 min** (retention ≈ −39%). The sign **flips within the measurement window itself** — this is the single most informative fact in your dataset and should shape the strategy, not just the risk model.

**When is genuinely positive realized spread (short-horizon) possible? [ESTABLISHED mechanisms]**
1. **Compensated liquidity provision into a transient, non-informational order-flow imbalance.** Grossman & Miller (1988), *"Liquidity and Market Structure,"* J. Finance 43(3):617–633: liquidity providers absorb temporary imbalances and are compensated via subsequent price *reversal* toward their execution price — i.e., genuinely positive short-horizon realized spread by construction, not a measurement error.
2. **Nagel (2012), *"Evaporating Liquidity,"* Review of Financial Studies 25(7):2005–2039:** short-term reversal strategies (the empirical proxy for market-making/liquidity-provision returns) earn predictable, time-varying positive returns, higher precisely when liquidity is scarce (high VIX analogue) — i.e. the mechanism is compensation for bearing short-horizon inventory risk against order-flow imbalance, not informational edge.
3. **Informedness need not be uniformly bad for market makers.** Ochedzan & Antulov-Fantulin (2026), *"Market Informedness and Market-Maker Profitability,"* arXiv:2606.05882 — an agent-based/RL computational study (not a closed-form theorem; treat as suggestive, recent preprint) — find informed flow is **most harmful when aggregate informedness is low** (poor price discovery ⇒ slow correction ⇒ the few informed trades do more lasting damage); profitability trends **up**, not down, as informedness rises, because faster price discovery lets market makers re-quote before damage compounds. This is directly consistent with your pattern: if most of your counterparties are retail/noise flow with only slow, diffuse information arrival (poll releases digested over hours, not milliseconds), you'd expect exactly "good in the first few minutes, eroding over hours" — informed flow here operates on an **hours** timescale (poll digestion, news-cycle discussion), not a **milliseconds** timescale (HFT), so your effective-spread window (minutes) catches the liquidity-provision reversal, while your markout window (hours) starts to catch the genuine, slower information diffusion.
4. **Behavioral mispricing specific to prediction markets.** The Kalshi paper above fits a structural model and finds a **favorite-longshot bias** (low-price contracts overpriced, high-price contracts slightly underpriced) driven by traders overweighting small probabilities (Kahneman & Tversky, 1979, prospect theory) — a real, exploitable, non-artifact source of edge concentrated near $p\to0$, decaying as $p\to0.5$. If your flow includes this kind of retail bias, positive realized spread against it is genuine and persistent, not noise.

**Measurement-artifact checks you should run before trusting this [DERIVED, concrete]:**
- **Sample size.** You have **91 fills.** If per-fill markout has standard deviation $s$ comparable to a couple of ticks ($s\approx0.01$, a reasonable order of magnitude), $SE(\bar m)\approx s/\sqrt{91}\approx0.00105$. A "138% retention" excess of $0.0049\times0.38\approx0.0019$ over zero gives $t\approx1.8$ — **marginal, not safely significant**, under illustrative assumptions. Retention is a *ratio* of two noisy quantities, compounding the imprecision. **Bootstrap a CI on both the markout and the retention ratio from your actual 91 fills before changing behavior based on these numbers.**
- **Mid-price construction.** Confirm the reference mid used for effective/realized spread excludes your own resting order (self-referential bias inflates retention artificially if your own quote is part of the NBBO/mid calc).
- **Survivorship/selection in which 91 fills you have.** With ~2,880 order-hours of quoting needed to generate 91 fills at these intensities, check whether fills cluster in particular contracts/regimes (e.g., disproportionately in fast-mean-reverting liquid races) that wouldn't generalize across all 237.
- **Extend the markout horizon past 240 minutes.** You don't know if markout keeps declining, stabilizes, or itself mean-reverts again. This is a **high-value, cheap analysis** against your 79k-trade tape (§6).

**Direct actionable implication (ties §2 and §3 together) [DERIVED]:** because the markout curve **peaks around 5–30 min and crosses zero before 240 min**, treat held inventory as having a **decaying edge**, and bias the skew formula in §2 to more aggressively favor flattening *aged* inventory — see §6 pseudocode.

### 3.3 Queue-reactive models and depth choice

**[ESTABLISHED]** Cont & de Larrard (2013), *"Price dynamics in a Markovian limit order market,"* SIAM J. Financial Math. 4(1):1–25, arXiv:1104.4596: order book as a Markov queueing system (limit rate $\lambda$, market+cancel rate $\mu+\theta$); their Prop. 2 gives the closed-form probability that the **next price move** is up given queue state $(n,p)$ (bid/ask queue sizes) via a discrete Dirichlet problem (harmonic function on $\mathbb Z_+^2$, solved in closed form by Fourier/eigenfunction expansion). Huang, Lehalle & Rosenbaum (2015), *"Simulating and analyzing order book data: the queue-reactive model,"* JASA 110(509):107–122, arXiv:1312.0563, extend this to state-dependent (not just Poisson) order-flow intensities at every level, matched to real LOB data. Cont & Kukanov (2017), *"Optimal order placement in limit order markets,"* Quantitative Finance 17(1):21–39, give the canonical **fill-probability-vs-queue-position** result: for queue position $Q$ (orders ahead of you) and horizon $T$, with outflow (market orders + cancellations ahead of you) a counting process $N(T)$, $P_{\text{fill}}(Q,T)=P(N(T)\ge Q)$ — i.e., you get filled iff cumulative outflow clears your queue position before you cancel/the price moves.

**For your implementation, this theory motivates *why* $\lambda(\delta)=Ae^{-k\delta}$ is a reasonable functional form (queue depletion races naturally produce roughly geometric decay in depth)** — but you already have the **directly measured** empirical curve (§0), which dominates any theoretical queueing derivation for calibration purposes. Use the queue-reactive literature for a secondary cross-check (e.g., does $k$ vary by contract liquidity in a way consistent with measured $\lambda,\mu,\theta$ at each book) rather than as a primary estimation route — you don't have L2/L3 queue data stated in your setup, only aggregate fill counts.

---

## 4. Optimal depth selection

### 4.1 General first-order condition **[DERIVED]**

Maximize expected PnL rate $g(\delta)=\lambda(\delta)\,e(\delta)$ (fill rate × edge-per-fill), $\lambda(\delta)=Ae^{-k\delta}$:
$$g'(\delta) = \lambda'(\delta)e(\delta) + \lambda(\delta)e'(\delta) = \lambda(\delta)\big[e'(\delta)-k\,e(\delta)\big] = 0 \;\;\Longrightarrow\;\; \boxed{e'(\delta^*) = k\cdot e(\delta^*)}$$
Equivalently: $\dfrac{d}{d\delta}\ln e(\delta)\Big|_{\delta^*}=k$ — **quote deeper only as long as the proportional growth rate of edge-per-fill exceeds $k$; stop where they're equal.** Second-order condition for a max (not min) requires $e(\delta)$ not to be "too convex" — formally, an interior optimum exists iff $e(\delta)e^{-k\delta}\to0$ as $\delta\to\infty$ and the log-slope of $e$ is decreasing through $k$ from above; if $e'(\delta)/e(\delta)>k$ at every measured depth, the solution is a **corner** (quote at the deepest depth you have good data for / your risk limits allow).

**Unifying check [DERIVED]:** in the textbook AS/GLFT problem, edge *is* the quoted distance itself, $e(\delta)=\delta$ (no separate markout concept — the "edge" is definitionally the spread captured). Then $e'(\delta)/e(\delta)=1/\delta$, and the FOC gives $\delta^*=1/k$ — and indeed, GLFT's floor term $\frac1\gamma\ln(1+\gamma/k)\to\frac1k$ as $\gamma\to0$ (risk-neutral limit) — **exactly matching this same FOC applied to $e(\delta)=\delta$.** Your situation is a genuine generalization: your *own* measured $e(\delta)$ (markout as a function of fill depth) replaces the naive $e(\delta)=\delta$ assumption.

### 4.2 Why this matters a lot here: your calibrated $k$ sets a high bar

Using $A=4.07$/hr, $k=0.254$/tick (§0), I computed $g(\delta)=\lambda(\delta)\cdot e_0(1+\eta\delta)$ for a grid of proportional edge-growth rates $\eta$ (%/tick):

| edge growth $\eta$ | optimal depth $\delta^*$ | PnL-rate improvement vs. 1-tick quoting |
|---|---|---|
| 0 – 25%/tick | **1 tick (corner)** | 0% |
| 30%/tick | 1 tick (corner) | 0% |
| 40%/tick | 1.44 ticks | +0.7% |
| 60%/tick | 2.27 ticks | +6.9% |
| 100%/tick | 2.94 ticks | +20.3% |
| 150%/tick | 3.27 ticks | +32.7% |

**Headline finding [DERIVED from your own calibrated data]:** because your fill rate decays 25.4%/tick (half-life 2.73 ticks), **edge-per-fill must grow faster than ≈25–30%/tick just to break even with quoting at the inside, and must grow ≳60%/tick to make deepening worth more than a few percent of PnL rate.** The premise "deeper fills catch bigger dislocations" is very plausibly true in direction, but your own $k$ is fast enough that it is *not* automatically true in magnitude — this must be checked against your actual $e(\delta)$ curve, not assumed. **This is a cheap, high-value, concrete test to run against the 79k-trade tape:** bucket fills (or simulated resting-order fills against the tape) by depth-at-fill, compute mean markout per bucket, and check whether the empirical $\frac{d\ln e}{d\delta}$ exceeds 0.254/tick anywhere.

### 4.3 Shift with remaining time **[DERIVED / reasoned, flagged as inference]**

Three separate effects, not one:
1. **Pure inventory-risk term:** under the corrected §1.4 model, this term is $\tau$-*independent* away from the boundary — it should **not** mechanically shift the optimal depth as $\tau\to0$ for a mid-probability race.
2. **Microstructure floor $c_1$:** depends only on $(\gamma,k)$. If $k$ rises as the event nears (more participants/competition piling into closing days, pushing fill-intensity decay faster, i.e., tighter competing quotes), $c_1$ and the depth-FOC optimum both fall — **pushes toward shallower quoting near close.**
3. **$e(\delta)$ itself likely changes**: information arrival accelerates sharply into election night (more, bigger dislocations to catch — argues for deeper/bigger edge) but so does competition for it (other sophisticated participants arb it away faster — argues for smaller realized edge per fill). Net direction is ambiguous a priori and **must be estimated on a rolling, shrinking lookback window** as $\tau$ falls, not extrapolated from the 33-day-out calibration.
4. A **hard regime switch** is still needed for the final hours (bridge/jump dynamics dominate, no smooth diffusion control applies there) — see §6.

---

## 5. Multi-asset / correlated inventory

### 5.1 The multi-asset result and its quadratic-form penalty **[ESTABLISHED]**

Guéant (2017), *"Optimal market making,"* Applied Mathematical Finance 24(2):112–154 (arXiv:1605.01862), and in full generality **Bergault & Guéant (2021), *"Size matters for OTC market makers: general results and dimensionality reduction techniques,"* Mathematical Finance 31(1):279–322, arXiv:1907.01225**: with $d$ correlated assets, $\Sigma=(\rho_{ij}\sigma_i\sigma_j)$ the price covariance matrix, the inventory risk penalty in the (CARA/mean-variance) objective is the **quadratic form** $q^\top\Sigma q$ (generalizing scalar $q^2\sigma^2$), and the reservation-price *vector* skew generalizes to:
$$\text{skew}_i = -\gamma(T-t)\,(\Sigma q)_i = -\gamma(T-t)\sum_j \Sigma_{ij}\,q_j$$
i.e. **contract $i$'s skew depends on the covariance-weighted sum of every position in the book, not just its own inventory.**

**Dimensionality reduction [ESTABLISHED, Bergault-Guéant §3]:** if prices follow a $k$-factor model, $\Sigma=\beta V\beta^\top$ ($\beta$: $d\times k$ loadings, $V$: $k\times k$ factor covariance; residual $R\to0$ assumed small), the inventory penalty collapses to $f^\top V f$ where $f=\beta^\top q\in\mathbb R^k$ is the **portfolio's factor-exposure vector** — the HJB problem is solved in $k$ dimensions, not $d$. This directly reduces your 237×237 (or at least 120×120) covariance problem to a handful of numbers.

### 5.2 Your specific structure: race-level netting **[DERIVED]**

Your setup has two layers: (a) a national swing factor common to all races, and (b) **near-perfect anti-correlation between a race's R- and D-contracts.** For a genuinely two-candidate race, $p_D\approx1-p_R$ exactly (both settle, and exactly one pays $1), so **D's payoff is literally $1-$R's payoff.** Holding $q_R$ shares of R and $q_D$ shares of D is economically:
$$q_R\cdot X_R + q_D\cdot(1-X_R) = q_D + (q_R-q_D)\cdot X_R$$
— a **risk-free cash leg $q_D$ plus a risky exposure of only $n_{\text{race}}=q_R-q_D$ shares to the race outcome.** Do not size-limit or skew $R$ and $D$ as if they were two independent $d=2$ risk factors — compute **net race exposure $n_{\text{race}}$** first; that is the only quantity that should enter the risk/skew calculation for that race's idiosyncratic component. (Caveat: breaks down if a race has a viable third-party candidate with non-trivial probability mass — check $p_R+p_D$ against 1 before netting fully; the residual $1-p_R-p_D$ is the "other" exposure.)

### 5.3 Practical, O(1)-per-update reduced-form rule **[DERIVED, directly actionable]**

Combine §5.1's factor reduction with §5.2's race netting, and use §2's exact per-contract skew for the idiosyncratic piece (since each individual contract's own terminal payoff really is exactly Bernoulli, even though the *joint* 237-way distribution is not analytically tractable — combining an exact univariate term with a linear multivariate factor correction is **my own hybrid construction**, not published, but each half is separately grounded):

1. For every race $r$, maintain net exposure $n_r = q_{R,r}-q_{D,r}$ (shares), updated on every fill — O(1).
2. Maintain a single running scalar: **net national-factor exposure** $F=\sum_r \beta_r\, n_r$ — O(1) update per fill ($\beta_r$ = race $r$'s loading on the national swing factor, estimated once via regression of historical race-level price moves on a national index/generic-ballot proxy, or simply set $\beta_r\propto$ the race's own historical price volatility if no better estimate exists).
3. Skew for the R-contract in race $r$:
$$\text{skew}_{R,r} = -\gamma(T-t)\Big[\underbrace{\sigma^2_{\text{idio},r}\,n_r}_{\text{race-specific}} + \underbrace{\beta_r\,\sigma_F^2\,F}_{\text{national factor}}\Big]$$
 (D-contract gets the same formula with a sign flip, since $dp_D/d(\text{factor})=-dp_R/d(\text{factor})$ under the netting identity above), or — preferably, per §1.5/§2 — replace the race-specific linear term with the **exact logit-CARA** skew using $n_r$ in place of $q$, and add the national-factor linear correction on top.
4. **No $120\times120$ or $237\times237$ matrix is ever built or inverted.** Total state: one scalar $F$ plus one scalar $n_r$ per race — this is the directly actionable reduced form you asked for.

---

## 6. What to actually implement

**Ranked by (estimated PnL improvement) / (implementation effort),** given you currently run fixed depth offsets and no inventory skew:

| Rank | Change | Why it's high-value | Effort |
|---|---|---|---|
| **1** | **Exact CARA/logit inventory skew** (§2.1) | You currently have *zero* inventory skew — this is the single largest missing piece of standard theory, directly causes over-trading one side once positioned, and the bounded form prevents a real bug (quote crossing 0/1) that a naive linear-AS port would hit | 1 `exp()`/`log()` call per quote; trivial |
| **2** | **Age-aware unwind bias from the markout-decay curve** (§3.2/§6.1) | Directly exploits the *exact* empirical fact you already measured (edge peaks ~5–30min, crosses zero by 240min) — arguably bigger expected-PnL impact than the static skew, because it's about not giving back the ~1-tick edge you already have | Needs per-position fill-age tracking + one more curve ($e(s)$ vs. holding time) from the tape; moderate |
| **3** | **Empirically-driven depth selection via the $e'(\delta)=k\,e(\delta)$ rule** (§4) | Your fixed-depth policy is almost certainly suboptimal given $k=0.254$/tick is a demanding hurdle rate for any "quote deeper" strategy; could go either way (shallower *or* deeper) once measured | Needs binned markout-by-depth estimation from 79k-trade tape; moderate |
| 4 | **Multi-asset net-factor skew overlay** (§5.3) | Real risk-reduction value given 120 correlated simultaneous books and near-perfect R/D anti-correlation, but secondary to getting single-market skew right first | Running sums only, but needs $\beta_r$ estimation; moderate |
| 5 | **Statistical validation gate before acting on retention>100%** (§3.2) | Defensive — prevents curve-fitting 91 fills into a false "we have negative adverse selection" conclusion that then drives over-sizing | Bootstrap CI; low |
| 6 | **Terminal/near-election regime switch** (§1.4, §4.3) | Low probability of mattering soon (33 days out) but high severity if ignored later; mostly a guardrail | Calendar-triggered parameter swap; low |
| 7 | **Boundary jump-risk floor on spread** (§1.4) | Modest, mostly matters for the small number of near-certain races | Small additive constant; low |

### Pseudocode / formulas for the top 3

**#1 — Exact inventory skew (replace fixed offsets with this reservation price):**
```
def reservation_price(p, q, gamma):
    # p: current fair prob:= mid; q: signed net inventory (shares); gamma: CARA risk aversion
    z = log(p / (1 - p)) - gamma * q          # logit(p) - gamma*q
    return 1.0 / (1.0 + exp(-z))              # sigmoid -> bounded in (0,1) for any q

def quotes(p, q, gamma, c1_floor):            # c1_floor = (1/gamma)*ln(1+gamma/k), from GLFT
    r = reservation_price(p, q, gamma)
    bid = clip(r - c1_floor, 0.005, 0.995)
    ask = clip(r + c1_floor, 0.005, 0.995)
    return round_to_tick(bid), round_to_tick(ask)
```
Calibrate $\gamma$ by choosing the inventory level at which you want ~1 tick of skew at $p=0.5$ (slope there is $-\gamma/4$): $\gamma = 0.005\times4/q_{ref}$.

**#2 — Age-decay unwind bias:**
```
def age_adjusted_gamma(gamma_base, holding_minutes, s_peak, s_cross, g_max_mult=3.0):
    # s_peak, s_cross estimated from tape: markout peaks ~s_peak, crosses zero ~s_cross
    if holding_minutes <= s_peak:
        return gamma_base
    # linearly ramp risk-aversion up to g_max_mult*gamma_base by s_cross, cap beyond
    frac = min((holding_minutes - s_peak) / (s_cross - s_peak), 1.0)
    return gamma_base * (1 + (g_max_mult - 1) * frac)

# apply per inventory "lot" (VWAP-age-bucketed), not just one global q:
# skew more aggressively against OLDER shares; quote passively to reduce them,
# do NOT cross the spread to exit (peak markout ~0.006 << spread ~0.0144 — crossing destroys value).
```

**#3 — Depth selection from measured e(δ):**
```
def choose_depth(depth_grid_ticks, A, k, e_hat):
    # e_hat[i] = empirically estimated mean markout at depth_grid_ticks[i], from tape regression
    best = argmax([A*exp(-k*d)*e_hat[i] for i,d in enumerate(depth_grid_ticks)])
    return depth_grid_ticks[best]
# Re-fit A, k, e_hat[] on a rolling window (e.g. trailing 5-10 trading days),
# re-run choose_depth per contract-liquidity bucket, not globally.
```

### Parameter estimation plan (given 91 fills / 88k quotes / 79k trades)

| Parameter | Method | Data | Caveat given sample size |
|---|---|---|---|
| $A,k$ (fill intensity) | Log-linear regression of $\ln\lambda$ on $\delta$ (done, §0) | Your own order/fill log | Already strong fit; re-run per liquidity bucket (contest closeness, days-to-election) with partial pooling (empirical Bayes shrinkage across the 237 contracts) since per-bucket fill counts will be thin |
| $e(\delta)$ (edge vs. depth) | Regress realized markout at a fixed horizon (pick horizon ≤ $s_{peak}$) against depth-at-fill or depth-at-hypothetical-resting-order (backtest resting orders against the 79k-trade tape, not just your 91 fills) | 79k-trade tape (market-wide), pooled across contracts with hierarchical shrinkage; your 91 fills only for final sanity check | 91 fills is far too few to bin by depth directly — must lean on the market-wide tape and assume your fills are drawn from a similar distribution |
| $s_{peak}, s_{cross}$ (markout curve) | Finer-grained markout-vs-holding-time regression, extend past 240 min | Same 79k-trade tape | **Highest-value open gap**: you don't know the shape past 240 min; get this before trusting buy-and-hold-to-settlement |
| $\sigma_0$ (Jacobi scale) / validate $p(1-p)/\tau$ | Panel regression of realized short-horizon variance of $p$ against $p(1-p)/\tau$ across all 237 contracts × time, pooled | 88k quotes (mid-price panel) | Large $N$ here (quotes, not fills) — this is your best-powered estimation; test the scaling law explicitly rather than assume it |
| $\pi$ (informed-flow fraction, GM) | Invert measured spread/markout decomposition against $\text{spread}(p,\pi)=4\pi p(1-p)/(1-\pi^2(2p-1)^2)$ | Tape-wide effective/realized spread decomposition | Confounded with the Grossman-Miller/longshot-bias explanations in §3.2 — don't over-interpret a single $\hat\pi$ without the horizon-decomposition context |
| $\gamma$ (risk aversion) | Back out from desired skew-at-reference-position (§6 #1) or from the 3–5% capital constraint via the Kelly/VaR connection (§2.2) | Your capital limits, not the tape | Free parameter in all this literature; treat as a risk dial, not something to "estimate" from data alone |
| $\beta_r$ (factor loadings, §5) | Regress each race's price changes on a constructed national swing index (e.g. average of all other races' moves, or generic-ballot proxy) | 88k-quote panel across 237 contracts | With 120 races, this is estimable but needs regularization (ridge/shrinkage toward a common prior loading) given limited historical days (33) |

---

## References

1. Avellaneda, M., Stoikov, S. (2008). *High-frequency trading in a limit order book.* Quantitative Finance 8(3):217–224.
2. Guéant, O., Lehalle, C.-A., Fernandez-Tapia, J. (2013). *Dealing with the inventory risk: a solution to the market making problem.* Math. Financial Economics 7(4):477–507. arXiv:1105.3115.
3. Guéant, O. (2017). *Optimal market making.* Applied Mathematical Finance 24(2):112–154. arXiv:1605.01862.
4. Ho, T., Stoll, H. (1981). *Optimal dealer pricing under transactions and return uncertainty.* J. Financial Economics 9(1):47–73.
5. Ackerer, D., Filipović, D., Pulido, S. (2018). *The Jacobi stochastic volatility model.* Finance and Stochastics 22(3):667–700. arXiv:1605.07099.
6. Karlin, S., Taylor, H.M. (1981). *A Second Course in Stochastic Processes.* Academic Press. (Wright–Fisher diffusion.)
7. Ethier, S.N., Kurtz, T.G. (1986). *Markov Processes: Characterization and Convergence.* Wiley.
8. Delbaen, F., Shirakawa, H. (2002). *An interest rate model with upper and lower bounds.* Asia-Pacific Financial Markets 9:191–209.
9. Gourieroux, C., Jasiak, J. (2006). *Multivariate Jacobi process with application to smooth transitions.* J. Econometrics 131(1-2):475–505.
10. Augenblick, N., Rabin, M. (2021). *Belief Movement, Uncertainty Reduction, and Rational Updating.* QJE 136(2):933–985.
11. Glosten, L.R., Milgrom, P.R. (1985). *Bid, ask and transaction prices in a specialist market with heterogeneously informed traders.* J. Financial Economics 14(1):71–100.
12. Cont, R., de Larrard, A. (2013). *Price dynamics in a Markovian limit order market.* SIAM J. Financial Math. 4(1):1–25. arXiv:1104.4596.
13. Cont, R., Kukanov, A. (2017). *Optimal order placement in limit order markets.* Quantitative Finance 17(1):21–39.
14. Huang, W., Lehalle, C.-A., Rosenbaum, M. (2015). *Simulating and analyzing order book data: the queue-reactive model.* JASA 110(509):107–122. arXiv:1312.0563.
15. Grossman, S.J., Miller, M.H. (1988). *Liquidity and Market Structure.* J. Finance 43(3):617–633.
16. Nagel, S. (2012). *Evaporating Liquidity.* Review of Financial Studies 25(7):2005–2039.
17. Bergault, P., Guéant, O. (2021). *Size matters for OTC market makers: general results and dimensionality reduction techniques.* Mathematical Finance 31(1):279–322. arXiv:1907.01225.
18. Bürgi, C., Deng, W., Whelan, K. (2026). *Makers and Takers: The Economics of the Kalshi Prediction Market.* GWU CER Working Paper 2026-001. https://www2.gwu.edu/~forcpgm/2026-001.pdf
19. Ochedzan, K., Antulov-Fantulin, N. (2026). *Market Informedness and Market-Maker Profitability: The Trade-Off Between Adverse Selection and Price Discovery.* arXiv:2606.05882.
20. Dubach, P.D. (2026). *The Anatomy of a Decentralized Prediction Market: Microstructure Evidence from the Polymarket Order Book.* arXiv:2604.24366.
21. Kelly, J.L. (1956). *A New Interpretation of Information Rate.* Bell System Technical Journal 35(4):917–926.
22. Kahneman, D., Tversky, A. (1979). *Prospect theory: An analysis of decision under risk.* Econometrica 47(2):263–291.

**Flagged gaps (explicit, per your instruction):** no published paper (a) solves an AS/GLFT-style control problem with a bounded/Jacobi price martingale, (b) derives the exact CARA-logit binary skew of §2.1 as stated, (c) derives the binary-specialized Glosten-Milgrom spread of §3.1, or (d) combines exact per-contract Bernoulli skew with linear multi-factor correction as in §5.3. All four are my derivations built on cited, established component results, with steps shown and (where feasible) symbolically verified.