# Modelling Methods — Verdicts

Research verdict on Bayesian / dynamic / ML methods, judged against our constraint:
simple, fast, calibrated, no overfitting.

## ADOPT (4 things, all cheap)

### 1. Ensemble our model with Polymarket's de-vigged price
Best-evidenced, cheapest change available. Graefe et al. (2014): **23% error
reduction** from combining just two qualitatively different method classes.
Equal-weight or inverse-historical-error weighting.

⚠️ **Do NOT ensemble with SIG's own live price** — that is circular and erases the
very edge we are trying to measure.

### 2. Static historical regional correlation layer
Upgrade 25/75 national/local to a three-level structure: national → ~9 Census
divisions → race. Blend empirical correlation with an all-ones floor the way the
Economist does (λ≈0.75/0.25 — their calibrated number, not a universal constant).

The honest answer to "can we beat 538's split" is **not** by estimating correlation
better in real time (nobody can) but by encoding more realistic *prior* structure
from data that is free and already settled.

### 3. Brier-decomposition / reliability-diagram harness
Backtest against pooled 2018/2020/2022/2024 House/Senate/Governor outcomes.
Nearly free, and the **only** thing that directly measures calibration — the
property that actually determines whether we make money on binary contracts.
Build this regardless of which other method we adopt.

### 4. Precision-weighted shrinkage (keep, don't extend)
```
w = (n/σ²) / (n/σ² + 1/τ²)
```
Two lines. This is our one piece of formalised hierarchical Bayes.
**Do not build the MCMC version.**

## SKIP (with reasons)

| Method | Why not |
|---|---|
| **MRP** | Requires individual survey microdata + poststratification frame. Does not exist in our window — confirmed by the method's own inventor. Data problem, not speed problem. |
| **Hierarchical / multilevel MCMC** | Published out-of-sample gains are a small-sample phenomenon that fades past ~100 respondents/unit. The real benefit (correlated structure) is better captured by #2 above at a fraction of the cost. |
| **Kalman filter / state-space / DLM** | A steady-state Kalman filter **is** an EWMA. With 3–5 polls per district we cannot identify the extra parameters. No new capability. |
| **Gaussian processes** | Formally equivalent to a Kalman filter for sane kernels — so again no new capability, and unidentifiable at our data density. |
| **Multimodal Bayesian ML** (polls+fundamentals+text+markets fusion) | No credible peer-reviewed instance exists. Even Gelman's active 2026 model stays polls+fundamentals only. |
| **NLP / social-media sentiment** | The critical literature wins decisively — including on the best pro-side paper's own numbers. |
| **Conformal prediction** | Its one guarantee (marginal coverage) is proven not to hold in competitive races — exactly where our P&L lives. Core assumption (exchangeability) is false for election time series. |

## The common thread
Every ADOPT either extracts more from signal we already have, or encodes cheap,
stable *historical* structure. Every SKIP adds parameters in a regime where our
genuinely independent information is far smaller than the raw count of polls or
markets suggests — precisely the compression SIG's own quant blog warned about.

## ⚠️ Caveat on our Senate robustness result
We showed the Senate "no trade" conclusion survives ρ from 25%→69%. **Do not
over-generalise that to the House.** House districts have sparser polling (less
information pinning the central estimate) and more units (correlation assumptions
compound across a longer chain). Correlation could matter considerably more there.
That uncertainty is itself an argument for building the regional layer (#2).
