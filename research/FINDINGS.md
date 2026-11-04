# SIG Predictions Cup — Research Findings

Status: research phase. Not committed. Last updated 2026-10-02.

## 1. Competition structure

| Fact | Value |
|---|---|
| Tournament | `midterm-elections`, id `bda92870-621e-47b0-bc3c-3602c5c26f55` |
| Window | 2026-10-01T16:00Z → 2026-11-04T17:00Z (~810h remaining at time of writing) |
| Markets | 237 binary, all `open`, 1 exchange each |
| Start capital | 100,000 SUSQies |
| Prizes | 1st $30k, 2nd $5k, 3rd $2.5k, **4th = $0** |
| Scoring | Balance **after all markets settle** (weeks after trading closes) |
| Our account | `merry-cedar-2703`, enrolled 2026-09-23 |

Market structure: each race is **two independent markets** (R-YES and D-YES) with
separate order books. 117 race pairs + 3 with an Independent leg (NE Senate,
MT Senate, RI Governor).

## 2. Field analysis (556 ranked participants)

| trades | n | median PnL | % profitable |
|---|---|---|---|
| 0–5 | 169 | −23 | 29% |
| 50–150 | 70 | −70 | 40% |
| 400–1000 | 29 | +1,226 | **66%** |
| 1000+ | 19 | +2,364 | **63%** |

Spearman(trades, PnL) = +0.126; Spearman(volume, PnL) = **−0.257**. Churn alone
does not pay. Crossing ~400 trades flips the profitable rate from 28% → 66%.

**Two archetypes**, separated by PnL per unit volume (`k`):
- `k > 0.3` = directional/tail. Rank 2 has k=7.21 — deep lottery tickets.
- `k ≈ 0.005–0.05` = genuine spread grinding.

Of 46 high-frequency bots: 30 positive edge, **16 negative**. Naive quoting is a
coin flip.

## 3. Favorite-longshot bias — the strongest finding

Crosswalk matched **228/237 markets** to Polymarket (96%). On 104 markets with
Polymarket volume ≥20,000:

| Polymarket price | n | mean Poly | mean SIG | ratio |
|---|---|---|---|---|
| 0.00–0.05 | 12 | 0.0286 | 0.0567 | **1.98×** |
| 0.10–0.20 | 11 | 0.1454 | 0.1759 | 1.21× |
| 0.40–0.60 | 12 | 0.4992 | 0.5052 | 1.01× |
| 0.80–0.90 | 11 | 0.8560 | 0.8300 | 0.97× |
| 0.95–1.00 | 14 | 0.9666 | 0.9457 | 0.98× |

All 25 longshots (Poly <0.15) priced above Polymarket. Sign test **p = 3.0e-08**.

Monotonic, textbook favorite-longshot bias. Explains the leaderboard: leaders hold
the most overpriced asset class on the platform, marked at inflated prices.

**Limitation:** as buy-and-hold carry it only returns ~2.2% (sell longshots) and
~1.7% (buy favorites), because selling a 0.09 contract ties up 0.91 to earn 0.02.
There is no collateral netting in this tournament to fix capital efficiency.
Its real value is as a **quoting anchor and directional tilt**.

## 4. Microstructure

- Spread: mean **1.44 pts**, median 1.5, p90 2.5.
- **Resting 5 pts below fair is NEGATIVE EV (−0.195)**; 10/20/30 pts are positive
  (+7.1 / +15.3 / +15.8). Adverse selection dominates tight quotes.
- Dislocations >10pt: 637 in 7.65h across 237 exchanges — but **decaying ~9×**
  from 0.074/candle at open to 0.008/candle by hour 8.
- Dislocations concentrate in **liquid** markets (corr log(volume) vs count = +0.67),
  not dead tails.
- Reversion after dislocation: median 2 min, p90 7–9 min.
- Depth at touch: median 1,129 bid / 650 ask.
- Recurring identical levels at 0.06/0.94, 0.005/0.995, 0.01/0.99 across 170–237
  books = SIG's designated market maker.

## 5. Live fill experiment (2026-10-01T23:58Z)

23 resting bids at mid−0.10 and mid−0.20, 1,150 SUSQies, 12 highest-dislocation
markets. **Zero fills in 26 min.** In the same window those exchanges printed 387
trades / 169,423 volume, but no print came within 10 pts of any bid.

Expected events given measured steady-state rate = 0.80 → observing 0 has Poisson
p ≈ 45%. **Underpowered, not a refutation.** Orders left resting as free options.

## 6. Operational findings

- **`GET /exchanges/{id}/price-history` is silently broken**: returns empty data
  for all exchanges and all resolutions while reporting `coverage.complete: true`.
  Persistent for 30+ min. **Never trust it. Build time series from `/trades`.**
- Rate limit: 3 concurrent workers → 0× 429. 6 → 15× 429. ~38 req/min sustainable.
- `/exchanges/prices` takes 100 ids per call → 79× request reduction.
- Order IDs are a **global monotonic sequence**: 1,225,252 → 1,228,635 in 85s
  ≈ **40 orders/sec platform-wide**.
- Trade tape exposes no counterparty identity.
- Resting orders did not visibly debit `balance` — reservation mechanics unconfirmed.
- Supabase realtime: token mints, channels join, but **no `market_batch` received**
  in 60s. Unresolved.

## 7. Hourly profile (partial — 16:00Z–23:00Z only)

| UTC | ET | volume | disloc/candle |
|---|---|---|---|
| 16 | 12h | 6,445,863 | 0.0210 |
| 17 | 13h | 7,414,205 | 0.0200 |
| 18 | 14h | 6,245,024 | 0.0335 |
| 21 | 17h | 8,166,726 | 0.0154 |
| 22 | 18h | 4,629,697 | 0.0087 |
| 23 | 19h | 2,985,705 | 0.0081 |

Overnight/European-morning window unmeasured — `collector.py` is filling it.

## 8. External data

- **Polymarket**: free, public, unauthenticated. Gamma + CLOB APIs. 228/237 matched.
- **Kalshi**: Developer Agreement limits API use to *"facilitating a member's own
  trading on the Exchange"* and bans caching/aggregating otherwise. No live 2026
  midterm markets found. **Recommend against.**
- Rules Section 7 MNPI: consuming public prices/forecasts is clearly permitted.

## 9. Realtime — protocol SOLVED, platform pipeline BROKEN

**Protocol fix (verified working):**
- Topic MUST be prefixed `realtime:` → `realtime:tournament:{id}`, not `tournament:{id}`
- `access_token` is a **sibling of `config`**, not nested inside it
- `anonKey` → `?apikey=` query param; `token` → payload `access_token`
- URL: `wss://<ref>.supabase.co/realtime/v1/websocket?apikey=<anonKey>&vsn=1.0.0`
- Heartbeat on topic `phoenix` every ≤25s

With this, channels join `ok` and **`leaderboard:all` delivers `tick` broadcasts**.

**But `market_batch` is never published.** Controlled test: subscribed to
`tournament:{id}` + 5 actively-trading `market:{id}` channels for 150s.
Result: **25 trades occurred on those exchanges, 0 market_batch frames received**
(2 leaderboard ticks arrived in the same window, proving the transport works).

JWT claims confirmed sane: `role=anon`, `realtime_profile_id`, `realtime_org_id`,
`realtime_key_org_id`, valid `exp`.

**Conclusion: the platform's market-data broadcast pipeline is down**, consistent
with `price-history` returning empty. Same engine-event→reporting path.

### Strategic consequence
Nobody in the competition can receive realtime market data. Everyone is forced to
poll REST at ~38 req/min. **The latency playing field is levelled.** Do NOT invest
in low-latency infrastructure — the edge is not speed, it is:
1. polling efficiency (`/exchanges/prices`, 100 ids/call)
2. our own tape-derived time series (competitors trusting `price-history` get zeros)
3. statistical modelling
`leaderboard:all` ticks DO work → real-time rank tracking for variance management.

## 10. Chamber-control model — first results (2026-10-02)

Spec (sourced): σ_Senate 5.5, Student-t df=5, variance split 25% national /
75% local (538's congressional figure). Monte Carlo N=200k.

Seat math: R holds 31 seats NOT up. 35 up in Class 2. R needs **20 of 35** for
51 seats, or **19** with the VP tiebreak. We have 33–34 race markets.

### Correlation effect is large and real
| | sd of R-seat count |
|---|---|
| Naive independent | 1.41 |
| Correlated (25% national) | **2.36** |

Tail probabilities diverge sharply:
| threshold | naive | correlated | ratio |
|---|---|---|---|
| ≥19/33 | 0.183 | 0.270 | 1.5× |
| ≥20/33 | 0.053 | 0.140 | 2.6× |
| ≥21/33 | 0.010 | 0.068 | **6.7×** |

Anyone aggregating race prices independently is badly wrong in the tails, in the
direction of **overconfidence**.

### But no mispricing established yet — threshold uncertainty dominates
SIG prices R-Senate control at 0.367 (normalised 0.366).
| threshold | SIG corr | POLY corr | market |
|---|---|---|---|
| ≥18/33 | 0.451 | 0.454 | 0.366 |
| ≥19/33 | 0.270 | 0.245 | 0.366 |

The market sits BETWEEN the T=18 and T=19 answers. Which one is right depends on
the 2 unmodelled races. **Do not trade this until the exact threshold is pinned.**

### Side finding: the two venues agree on the mean, differ on the spread
Expected R seats: Polymarket 17.30 vs SIG 17.22 (diff +0.07) — the favorite-longshot
bias largely cancels when each race is normalised R/(R+D).
But seat-count sd: SIG 2.36 vs Polymarket 1.88 — SIG's race probabilities are
compressed toward 0.5, exactly as the FLB predicts. The bias lives in the
*confidence*, not the *direction*.

### Next step
Enumerate all 35 Class 2 races, identify the 2 missing from our market set, and
determine the VP-tiebreak assumption in the market's resolution criteria.

## 11. Senate threshold PINNED — and the trade is killed (2026-10-02)

### Resolution criteria (fetched from `/markets/154/nodes`)
> "Resolves YES if the Republican Party wins **majority control** of the U.S. Senate...
> Control is determined by **the party holding the majority of seats** when the new
> Congress is seated; the market is settled manually **once major news organizations
> have called control** of the chamber."

### The missing seat is OHIO
Our 34 SIG Senate states = the 33 Class 2 seats + Florida's special.
Polymarket has exactly one Senate state we lack: **Ohio** (the Vance vacancy special),
priced P(R) = 0.41 on 990k combined volume. 35 seats up total. ✓

### Seat math
R holds **31** seats not on the ballot. R needs **20 of 35** for a 51-seat majority,
or **19** if 50-50 counts (VP Vance is Republican and breaks ties).

### Result — the model reproduces the market almost exactly
Expected R seats won (market-implied): **17.64**

| threshold | independent | **correlated** | market | edge |
|---|---|---|---|---|
| R ≥ 20 (strict 51) | 0.1257 | **0.2411** | 0.367 | +0.126 |
| R ≥ 19 (VP tiebreak) | 0.2991 | **0.3715** | 0.367 | **−0.0045** |

**The market prices R-Senate control as if 50-50 counts as Republican control, and
under that reading it is efficient to within 0.5 of a point.**

### Conclusions
1. **Our model is validated** — it reproduces a liquid market price to 0.45 points.
2. **The chamber-control market is NOT naively aggregated.** Independent aggregation
   gives 0.299, which is 7 points off. Someone has already done correlated maths.
   The "nobody is doing this" hypothesis is **false** for the Senate.
3. **No statistical trade exists here.** What remains is a *semantic* bet on whether
   "majority of seats" means 51 strictly or follows the news-call convention at 50-50.
   P(exactly 50-50) = **0.129**, so the ambiguity decides the market 13% of the time.
   The second clause ("once major news organizations have called control") points to
   the VP-tiebreak reading — i.e. the market is probably right.
4. Rules §3 lets SIG "update the rules, outcomes, or resolution of a Market at any
   time, including after the resolution date" — so betting on wording is uninsurable.

### Robustness
σ is nearly irrelevant (0.354→0.372 across σ=4.5–7.0) because we invert market
probabilities into margins and re-simulate — σ largely cancels. ρ matters modestly
(P(≥20) ranges 0.21–0.26 for ρ=0.15–0.35). **The threshold dominates everything.**

### What survives
The validated model is now a reusable asset: apply it to House control and to
relative value *between* individual races, where the same machinery may still find
gaps. The Senate headline market is efficient; the down-ballot ones may not be.

## 12. Model design validated independently + correlation sensitivity

A survey of open-source US election forecasting code (Economist `us-potus-model`,
`pkremp/polls`, `CoryMcCartan/midterms-22`, `thisismactan/US-2026`, `rafalab/538`,
`markjrieke/2024-potus`) found that the mechanics surviving real deployment are
exactly our three:
1. Student-t margin→probability mapping (df 3–5; we use 5)
2. A shared national shock driving cross-race correlation
3. Closed-form precision-weighted blending of fundamentals and polls

Verdict: **the heavier machinery does not beat this by enough to justify it.**
Nobody produced a head-to-head calibration showing full covariance matrices or
GP-learned kernels materially outperform a one-factor model.

### Worth stealing (cheap)
- **Precision-weighted blend**: `w = (s²/N) / (s²/N + τ²)` — found independently in
  two unrelated repos. Auto-evolves the polls/fundamentals weight as poll count
  grows; no hand-tuned decay schedule needed. Two lines, microseconds.
- **A second regional factor** (~9 Census divisions) on top of the national one —
  captures "Rust Belt moves together" that a pure one-factor model misses.
- Student-t with df 3–5 for BOTH national and idiosyncratic terms.

### Skip
Full 51×51 covariance + Cholesky MVN; GP-learned covariance (Cholesky inside every
MCMC iteration); daily state-space random walks; **MRP** (needs individual survey
microdata + poststratification frame we do not have — a data problem, not a speed
problem); BART imputation of safe seats.

### Correlation sensitivity — Senate verdict is ROBUST
Tested national variance share 25% → 69% as recommended:

| ρ_national | sd seats | P(≥19) VP | P(≥20) strict | edge@19 | edge@20 |
|---|---|---|---|---|---|
| 0.25 | 2.94 | 0.3712 | 0.2412 | −0.004 | +0.126 |
| 0.35 | 3.32 | 0.3833 | 0.2640 | −0.016 | +0.103 |
| 0.50 | 3.81 | 0.3924 | 0.2857 | −0.025 | +0.081 |
| 0.69 | 4.35 | 0.3981 | 0.3058 | −0.031 | +0.061 |

Market = 0.367. **Raising correlation makes the market look MORE efficient under the
VP reading, and shrinks the strict-reading edge from 12.6 to 6.1 points.**
The "no trade" conclusion holds across the entire plausible correlation range.

## 13. The 0-of-23 result EXPLAINED — and S3 is downgraded

Lokin, F. & Yu, F. (2026), "Fill Probabilities in a Limit Order Book with
State-Dependent Stochastic Order Flows", arXiv:2403.02572v2, verbatim:

> "our numerical experiments suggest that fill probabilities beyond one tick from
> the best quote are typically negligible. Consistent with this observation…
> **approximately 85% of executed limit orders are posted within one tick of the
> best quote**."

### Tick arithmetic (corrected)
Mean spread 1.44 probability POINTS = 0.0144 in price units. Tick = 0.005.
→ **spread ≈ 2.88 ticks.** (The research agent computed 288 ticks — off by 100×,
which led it to conclude the tick grid was "the wrong state variable". With the
correct figure the literature applies *directly*.)

Our experimental orders rested at mid−0.10 and mid−0.20, i.e. **20 and 40 ticks**
from mid. Fills beyond ~1 tick are negligible.

**0-of-23 is exactly what theory predicts.** It was not bad luck or an underpowered
window — it is the expected outcome of resting 20–40 ticks deep.

### Consequence: the dislocation backtest was invalid
The backtest assumed `candle low ≤ my bid ⟹ I get filled`. Lokin-Yu says the trade
happened against liquidity **nearer the touch**; our deep order would have been
skipped. The headline "+620k at 10pts below fair" is therefore not merely an
optimistic upper bound — its core fill assumption is wrong.

**S3 (deep passive ladder) is downgraded from "real but decaying" to "probably
not viable as designed."** Deep resting orders do not fill.

### What our experiment actually established (Poisson exact bound)
23 orders × 26 min = 598 order-minutes, 0 fills.
95% upper bound: λ ≤ 2.996/598 = **0.005 fills per order-minute** (≤0.30/order-hour).
This is an upper bound, not an estimate — too short to distinguish "rare" from
"never".

### The correct next experiment
Re-run the fill test **at 1–2 ticks from the touch**, where theory says fills
actually occur, and estimate λ there. That is the number S3/S4 sizing depends on.

## 14. Overnight ladder results — S3 REINSTATED, plus a major capital finding

### 3 of 23 deep orders filled overnight — all profitable
| exch | market | filled @ | mid after ~10h | markout/share |
|---|---|---|---|---|
| 959 | Maine Senate (D) | 0.4800 | 0.5525 | **+0.0725** |
| 982 | Texas Senate (D) | 0.5350 | 0.6250 | **+0.0900** |
| 1067 | Alaska Senate (R) | 0.2300 | 0.3300 | **+0.1000** |

**+0.0908 per share; +25.9% on a 149.59 cost basis in ~10 hours.**

Fill times: **05:23Z, 05:43Z, 08:51Z** — all 01:23–04:51 ET, i.e. deep overnight
when the US student field is asleep. This directly confirms the hours-of-day edge:
a 24/7 bot owns the overnight book.

λ (deep ladder) = 3 fills / 13,686 order-min = **0.025 fills/order-hour**,
95% CI [0.005, 0.073].

**I over-corrected in §13.** Deep orders do fill — rarely, but with strongly
positive markout. The low fill rate is a *feature*: deep orders only fill during
dislocations, and dislocations revert. S3 is reinstated, but as a *low-frequency,
high-markout* strategy, not the high-volume grind the original backtest implied.

### ⚠️ MAJOR: resting orders do NOT reserve buying power
Verified directly:
```
balance            = 99,850.415
filled cost basis  =     149.59
100000 - cost      = 99,850.410   -> MATCH
open resting orders = 20, notional 1,000.57  -> costs nothing
```
**Only fills debit the balance.** We can rest a large ladder across all 237 markets
at **zero capital cost**. The binding constraints are the rate limit (order
placement/maintenance) and simultaneous-fill risk — the engine mitigates the latter
by shrinking orders "to fit a decreased balance" at fill time (Order schema).

This is the single most exploitable structural fact found so far.

### Fill rate vs distance from touch — first measurement
| placement | n | fills | order-hours | fills/order-hr |
|---|---|---|---|---|
| improve (bestBid+1tk) | 10 | 3 | 0.2 | **19.40** |
| join (bestBid) | 10 | 0 | 0.2 | 0.00 |
| back3 (bestBid−3tk) | 10 | 0 | 0.1 | 0.00 |
| deep20tk | 12 | 3 | 119.8 | 0.025 |
| deep40tk | 11 | 0 | 109.8 | 0.000 |

Early sample, but the gap is ~776×. Lokin-Yu confirmed emphatically.

**The real question is now the trade-off**: near-touch fills ~776× more often, but
deep fills earn +0.09/share. Expected value per order-hour is what matters, and
that requires markout on the near-touch fills — which the harness is now collecting.

## 15. Near-touch experiment — EV by placement MEASURED (2026-10-02)

30 orders across 10 liquid exchanges at three distances, equal-variance sized
(`q ∝ 1/√(p(1−p))`), max exposure 1.34%.

### Fill rate decays monotonically with distance
| placement | n | fills | order-hrs | fills/order-hr | 95% CI |
|---|---|---|---|---|---|
| improve (bestBid+1tk) | 10 | 8 | 2.5 | **3.17** | [1.37, 6.24] |
| join (bestBid) | 10 | 5 | 2.5 | **1.98** | [0.64, 4.63] |
| back3 (bestBid−3tk) | 10 | 1 | 2.5 | 0.40 | [0.01, 2.21] |
| deep20tk | 12 | 3 | 122.9 | 0.025 | [0.005, 0.072] |
| deep40tk | 11 | 0 | 112.6 | 0.000 | [0, 0.033] |

~129× between improving the touch and resting 20 ticks deep. Lokin-Yu confirmed.

### But EV per order-hour inverts the ranking
| placement | fills | mo/share | PnL | **EV/order-hr** |
|---|---|---|---|---|
| improve | 15 | **−0.00667** | −4.84 | **−1.745** ❌ |
| join | 15 | +0.00583 | +2.41 | **+0.872** ✅ |
| back3 | 1 | +0.00250 | +0.44 | +0.158 |
| deep20tk | 3 | **+0.08750** | +37.61 | +0.306 ✅ |

**Price improvement is EV-NEGATIVE.** Stepping in front of the queue buys you fills
you do not want — this is Glosten-Milgrom measured directly on our own capital.
Joining the queue is positive; resting deep is positive with far higher per-fill edge.

Acted on it: cancelled the `improve` orders (9 of 10 had already filled — they fill fast).

### FLB confirmed from our own fills
| price bucket | n | mean markout/share |
|---|---|---|
| 0.00–0.05 | 7 | +0.00250 |
| **0.05–0.15** | 15 | **−0.00583** ❌ |
| 0.15–0.35 | 1 | +0.10000 |
| 0.35–0.65 | 5 | +0.03600 |
| 0.65–0.85 | 4 | +0.01062 |
| 0.85–0.95 | 2 | 0.00000 |

The 0.05–0.15 longshot bucket is the only negative one. We were **buying** longshots
and losing on them — exactly as the 1.98× overpricing predicted. **We should be
selling that bucket, not buying it.**

### Honest caveats
- Horizons differ: improve/join measured at 1–5 min, deep at 30–240 min. Short-horizon
  markouts are smaller in magnitude. **The signs are the robust part, not the ratios.**
- Small samples (15/15/1/3/0 fills).
- **We only tested one-sided passive BUYING.** A real market maker quotes both sides
  and realises the markout by selling. Round-trip economics are still unmeasured.
- Capital, not fill rate, is the binding constraint at scale: `join` at 1.98 fills/
  order-hour across 237 markets would consume ~6,200 SUSQies/hour — we would exhaust
  100k in ~16 hours without continuously closing positions.

### Current state
balance 99,318.46 · 34 open orders · 11 positions · unrealised +31.02
**Total equity 100,031.02**

### Rules now established for the quoting engine
1. **Never improve the touch** — measured EV −1.75/order-hour.
2. **Never buy the 0.05–0.15 bucket** — measured negative markout; sell it instead.
3. **Join the queue, don't lead it.**
4. **Keep a deep ladder running** — it costs no capital while resting and has the
   highest per-fill edge (+0.0875/share).

## 16. ⚠️ A test caught a real bug in the chamber-control model

`test_one_factor_preserves_marginals` failed on first run. The margin-space
construction we had been using:
```
margin_i = sigma * t_df^{-1}(p_i)
outcome_i = 1{ margin_i + e_nat + e_i > 0 },  e_nat, e_i both ~ t_df
```
**does not preserve the input marginals**, because the sum of two independent
t variates is not t. Measured distortion: input 0.90 simulated at **0.941**,
input 0.10 at **0.060** — extremes pushed outward, so seat-count variance was
misstated.

### Fix: one-factor Gaussian/t COPULA (marginals exact by construction)
```
X_i = sqrt(rho)*Z + sqrt(1-rho)*eps_i          each X_i ~ N(0,1)
outcome_i = 1{ X_i <= Phi^{-1}(p_i) }          P(outcome_i) = p_i exactly
```
Optional t-copula divides by sqrt(W/df), W~chi2(df), shared across races.
This is the Vasicek/Basel ASRF construction and matches `one_factor_quadrature`.

### Corrected Senate numbers (35 seats, expected R = 17.64, market = 0.367)
| rho | df | sd | P(≥19) VP | P(≥20) strict | edge@19 | edge@20 |
|---|---|---|---|---|---|---|
| 0.00 | – | 1.87 | 0.3217 | 0.1564 | +0.045 | +0.211 |
| 0.25 | – | 3.61 | 0.4039 | 0.2978 | −0.037 | +0.069 |
| 0.25 | 5 | 3.60 | 0.3928 | 0.2789 | −0.026 | +0.088 |
| 0.50 | – | 4.75 | 0.4218 | 0.3365 | −0.055 | +0.031 |

**Monte Carlo vs deterministic Vasicek quadrature agree to 4 decimals**
(0.2978 vs 0.2974 at rho=0.25) — two independent implementations cross-validated.

### Did the verdict change? No.
Previously (buggy): edge@19 −0.005, edge@20 +0.126.
Corrected: edge@19 −0.037, edge@20 +0.069.
The market still sits between the two threshold readings, and neither gap is
large enough to bet on a semantic ambiguity SIG can revise after the fact.
**Still no trade** — but the numbers moved up to 5 points, which is exactly why
the test mattered.

### Lesson
Every statistical algorithm gets a test that checks a property it must satisfy
(marginals preserved, PMF sums to 1, decomposition identity holds), not just
that it runs. `research/test_algos.py` — 33 tests, all passing.

## 17. Platform incident 2026-10-02 ~12:20Z — our diagnosis officially confirmed

SIG posted: *"Realtime updates are paused while we fix a performance issue. You
can still trade, but you'll need to refresh the page to see the latest prices,
your orders and your balance."*

**We independently diagnosed this hours earlier** (§9, §13): `market_batch` never
publishing (25 trades / 0 broadcasts in a controlled test) and `price-history`
returning empty while reporting `coverage.complete: true`.

### Scope of the incident — measured, not assumed
| Layer | Status |
|---|---|
| Trade tape (`/exchanges/{id}/trades`) | ✅ LIVE — last trades 0.2–1.6 min old |
| Orderbooks / `/exchanges/prices` | ✅ working |
| Order placement / cancel | ✅ working |
| Account / positions / balance | ✅ consistent (balance == 100000 − cost basis exactly) |
| `price-history` candles | ❌ still 0 rows, still claims `complete: true` |
| Realtime `market_batch` | ❌ still never publishes |

**The core trading engine and REST reads are healthy. Only the push/reporting
layer is down.**

### Is the field impaired? No.
Live measurement: **19.5 trades/min** across 10 liquid exchanges in the last 15
minutes. Leaderboard is moving and reshuffling (a new name at #2). The field is
still trading actively — this is not a free-money window.

### Our position is unusually well placed
Our architecture never depended on either broken endpoint: we build time series
from the trade tape and poll `/exchanges/prices` in bulk. Competitors who built on
`price-history` or the WebSocket feed are impaired; WebUI users must manually
refresh to see prices, orders and balance.

### Posture during the incident
- **Do not scale up.** Elevated 5xx/timeout risk under performance stress.
- **Idempotency discipline matters more than ever** — a `502 ORDER_STATUS_UNKNOWN`
  may already have executed; retry the same key, never a fresh one.
- **Keep the deep ladder resting** — it costs zero capital and a platform incident
  is exactly the condition that produces the dislocations it is designed to catch.
- **Flag all measurements taken in this window** as potentially unrepresentative.

### ⚠️ Data-quality bug found in OUR collector
Live REST shows 19.5 trades/min on 10 liquid exchanges; our tape store recorded
only 4.5/min for the same exchanges over 10:00–12:00Z. Cause: the collector
rotates 20 exchanges per 120 s cycle (full pass = ~24 min) with `limit=100`, so
**busy exchanges are under-sampled**. Fixed: `limit` raised to the 200 maximum and
the rotation batch widened. Historical tape for high-activity markets should be
treated as a lower bound, not a complete record.

## 18. "Risk-free" was the wrong word — logic review (2026-10-02)

A rubber-duck review attacked the pair-completion thesis and was right twice.

### 1. Refunds break the lock
The venue's own rules: *"A cancelled or N/A outcome refunds the remaining
position instead of choosing a winner."* `Leg.payout_if` modelled only 0/1
winner states, so it could not express this.

Buy R 100@0.40 + D 100@0.50 = cost 90, "locked" +10.
If R is **refunded** and nothing else pays: payout 40 → **PnL −50**.

Fixed: `portfolio.py` now reports three distinct floors.
| measure | meaning |
|---|---|
| `guaranteed_floor` | floor over winner states only (the old number) |
| `worst_case_floor` | includes single-leg refunds, incl. the winning leg |
| `other_wins_floor` | no listed outcome wins — the universe isn't provably exhaustive |

`is_risk_free` is now an alias for `is_conditionally_locked`, with
`is_unconditionally_locked` requiring a non-negative floor even under refund.

**Our live book, honestly:**
```
cost                         1,126.31
floor (winner-states only)    -735.31
floor INCLUDING refunds     -1,043.78   <- the honest number
conditionally locked races          0
unconditionally locked              0
```

### 2. The strategy is aimed at the wrong objective
| our equity | 3rd place | gap |
|---|---|---|
| 100,054 | 632,861 | **6.3×** |

Required return to reach the podium: **533%**. Even a 200% return lands at
300k against 633k needed. A market-neutral book **cannot** get there, and
variance suppression at this distance drives P(top-3) toward zero.

This does not make pair completion useless — it makes it a *capital-preservation
tool*, not a route to winning. The tournament literature (Seel & Strack;
Browne 1999) says convexity should scale with the gap to the cutoff, and our
gap is enormous.

### Other findings accepted
- Ladder evidence is **3 clustered fills**, not an established edge. The markout
  harness measured mid-price marks, not realised round trips.
- No aggregate national-swing / correlated-fill control exists.
- "Can lock non-negative PnL" ≠ "the complement is positive EV".

---

## §19 — CORRECTION: the +0.0875 ladder edge was a frame bug

**Everything in §13 and §15 that cites a markout above ~0.01/share is wrong.**
Those numbers are superseded by this section.

### The bug

`markout()` handled `side="no"` by flipping the sign of `(later_mid - fill_price)`
instead of converting frames. But `later_mid` is always the **YES-space** mid,
while a `no` fill's price is quoted in **NO space**, and a NO share is worth
`1 - yes`. The sign flip inflated every NO fill by roughly `(1 - 2*mid)`.

Worst observed case:

| field | value |
|---|---|
| fill | buy NO @ 0.945 |
| YES mid at fill | 0.0475 |
| reported markout | **+0.9025 / share** |
| true markout | **+0.0075 / share** |

A per-share markout of +0.90 is arithmetically impossible on a contract that
settles in [0,1] at those prices; the magnitude alone should have been caught.
The fix is asserted two ways that must agree: buying NO at p and selling YES at
(1-p) are the same trade, so they must mark out identically.

`tests/test_algos.py` had **encoded the bug** — it asserted that buying NO at
0.60 against a 0.50 YES mid was a +0.10 *gain*, when paying 0.60 for a share
worth 0.50 is a 0.10 *loss*. The behaviour therefore looked verified. This is
the third time in this project a test has locked in the defect it was meant to
catch (after `devig()` on a single-member group, and the margin-space
correlation model).

### Corrected results, 91 fills

| horizon | n | mean markout/share | posterior | P(edge > 0) |
|---|---|---|---|---|
| 1 min | 91 | +0.0058 | +0.0053 | 0.96 |
| 5 min | 91 | +0.0068 | +0.0063 | 0.98 |
| 30 min | 68 | +0.0063 | +0.0054 | 0.91 |
| **240 min** | 36 | **−0.0019** | −0.0010 | **0.44** |

Posterior is a normal-inverse-gamma shrinkage estimate with the effective
sample size taken from the autocorrelation function, not the raw count.

**Two conclusions, and they point in opposite directions:**

1. **The edge is real, and it is now better supported than the inflated number
   ever was.** ~+0.005/share is one tick — exactly what capturing part of a
   2.88-tick spread net of adverse selection should look like. The earlier
   figure was not merely too large; it was too large to be a market-making
   edge at all, and that implausibility was the tell.
2. **The edge is perishable.** It is gone by 240 minutes. Holding inventory
   hands it back. Nothing in the system closed positions, which is the
   mechanism behind the guaranteed floor drifting from −678 to −1,402.

### Corrected bucket structure (30 min)

| bucket | n | posterior | P(edge>0) | verdict |
|---|---|---|---|---|
| 0.00–0.05 | 9 | −0.0011 | 0.27 | no evidence |
| 0.05–0.15 | 16 | −0.0064 | **0.006** | negative — do not buy |
| 0.15–0.35 | 13 | +0.0099 | 0.94 | positive |
| 0.35–0.65 | 11 | +0.0102 | 0.91 | positive |
| 0.65–0.85 | 13 | +0.0067 | **0.998** | positive |
| 0.85–0.95 | 6 | +0.0068 | 0.98 | positive |

The 0.05–0.15 bucket is negative at P(edge>0) = 0.006, which independently
confirms the `no_buy_below = 0.15` veto in `risk.py` that was previously
justified by the *uncorrected* numbers. Right rule, wrong reason, now correct
for the right reason.

### Method note

The lesson is not "be more careful". It is that **a cross-frame quantity needs
a cross-check that fails loudly**. Both regression tests added here are
redundancy, not coverage: `|markout| <= 1` is a physical bound, and the
NO/YES equivalence is the same trade described two ways. Either would have
caught this on day one.

## 22. Edge hunt, 2026-10-03

### 22.1 The favourite-longshot gap is WIDENING, not converging

Re-measured SIG mid vs live Polymarket CLOB ~9h apart:

    band         16:00Z   01:10Z   change
    0.00-0.05     1.95     2.01    +0.06
    0.05-0.08     2.35     2.79    +0.44
    0.08-0.20     1.37     1.43    +0.06
    0.80-1.00     0.97     0.97     0.00

Confirmed independently in the tape: conditioning on an EARLY price and
measuring drift over a LATER, non-overlapping window (which breaks the
regression-to-the-mean artifact), cheap contracts rose +0.0081/share
(P=1.000) and favourites fell -0.0069 (P=0.000).

Mechanism: 893 participants each need ~7x to reach the podium, so they all
bid for convexity. Longshot demand is structural and persistent, and it will
likely intensify as the deadline nears.

Consequence: our short-tail trade is fighting the dominant order flow. That is
survivable only because the contest scores balance AFTER settlement, so
adverse mark-to-market is not a loss. It does mean the position must be held,
not stopped out.

### 22.2 The FLB edge is real but capital-INEFFICIENT

    trade                    edge/share  collateral  return on capital
    sell tail 0.08-0.20        +0.0421      0.860     4.9%, once
    sell tail 0.05-0.08        +0.0417      0.935     4.5%, once
    buy favourite 0.80-1.00    +0.0278      0.900     3.1%, once
    the market-making grind    +0.0020    recycled    ~60% over 31 days

Selling a tail ties up 0.86-0.97 per share for 31 days to earn one 4-5%
payoff. The grind turns the same capital over continuously. At the 20% cap the
entire FLB book is worth roughly +979, against ~+12,000 for the grind.

So FLB is a use for capital the grind cannot absorb, not a replacement. Note
the grind is now FLOW-constrained, not capital-constrained: at 15.5% deployed
the deployment cap vetoes 0 orders.

### 22.3 Chamber control vs its own component races -- the largest edge found

SIG lists "Will the {Party} win the U.S. Senate?" (exchanges 842/843) AND all
34 state Senate races. Their engine has no cardinality logic, so nothing
forces these to agree.

Pricing control from the 33 races Polymarket covers, via the one-factor copula
at rho=0.25 (E[R seats]=17.24, sd=2.37):

    R seats needed   implied P(R control)   SIG market   edge
         17               0.6324               0.36      +27 pts
         18               0.4528               0.36       +9 pts  BUY
         19               0.2841               0.36       -8 pts  SELL

Two things make this unusually attractive:

  * The edge is 8-27 points, i.e. 16-54 ticks, against a grind edge of 0.4
    ticks.
  * At threshold 18 the answer is almost COMPLETELY INSENSITIVE to the
    correlation assumption -- P(R>=18) was 0.5067/0.5061/0.5071/0.5063 at
    rho = 0/0.1/0.25/0.4 -- because the mean sits on the threshold. So the
    usual objection to Poisson-Binomial seat models does not bite here.

BLOCKED: the sign flips between thresholds 18 and 19.

  R holds 53 seats. Of the 34 up in 2026, 21 are R-held (Class 2 + the FL
  special), so R holds 32 that are not up. With VP Vance breaking ties, 50
  seats is control, which needs 18 of 34. That reading gives BUY at +9 points.
  If the market instead requires 51, R needs 19 and the trade reverses to SELL
  at -8.

  The API exposes no resolution criteria -- category "Freeform", title only,
  settlementDate 2026-11-04, initialPrice 0.5 on both legs. The threshold must
  be read from the platform UI before any capital is committed.

### 22.4 Ladder depth experiment -- still inconclusive

Ladder fills by realised depth: 1t +0.00020 (n=25), 2t +0.00400 (n=10),
3t +0.00542 (n=6), 4t +0.00708 (n=6), 5t +0.02063 (n=4). Aggressive fills
lose: -1t -0.00100, -2t -0.00250, -8t -0.02750.

Edge rises monotonically with depth, but the 20-tick rung has no fills yet, so
the geometric-vs-power-law question remains open. Needs more time.

## 23. Competitor analysis, 2026-10-04 -- the leaderboard is a tail bubble

126 leaderboard snapshots over 46 hours (research/data/tape.db, table `lb`).

### 23.1 What the leaders are actually doing

    player               pnl start    pnl now      delta   trades  pnl/trade
    sunny-acorn-8216        95,037    874,205   +779,168   +2,671      291.7
    nimble-beacon-4953     254,317    641,624   +387,307   +1,015      381.6
    merry-coral-9766         1,491    328,549   +327,057   +5,959       54.9
    bright-finch-0400      456,041    744,369   +288,327   +7,924       36.4
    us (merry-cedar)           ~0        ~400       +400     ~700        0.5

They earn 20-380 per trade against our 0.5, and volume per trade is
1,565-9,859 against our ~150. Every top-6 trajectory is "jumpy" -- gains
arrive in large steps, not steady accumulation. That is directional position
marking, not market making.

### 23.2 Their P&L is the longshot bubble, not skill

Tracking the mean price of the 69 contracts that started below 0.15 against
mean top-20 P&L, hour by hour:

    corr(mean tail price, mean top-20 P&L) = +0.895
    tail price   0.0656 -> 0.1078   (+64%)
    top-20 P&L  216,958 -> 361,448  (+67%)

They move in lockstep. The leaders are long the tails, and their gains are the
bubble inflating -- the same bubble independently measured at 1.95-2.79x
Polymarket, and widening (the 0.05-0.08 band went 2.35x -> 2.79x in 9 hours).

### 23.3 Conservation check

Nothing settles until Nov 3, so ALL leaderboard P&L is mark-to-market.

    top 100 total paper P&L   8,785,651
    total contest capital    99,700,000  (997 x 100,000)
    top 100 claim 8.8% of ALL capital as profit, pre-settlement

Every long is someone's short and every contract pays exactly 0 or 1, so
aggregate P&L must be ~0 at settlement. 8.8% of all capital showing as profit
in the top 100 alone is only possible because prices are collectively
inflated. About 57% of the current value of those tail contracts is air
relative to the Polymarket anchor.

### 23.4 What this changes

The earlier claim that the podium needs ~600,000 assumed the current
leaderboard is real. Much of it is not. These are the same positions that
print ZERO on election night.

Our position is structurally different, and not by luck:
  * market-making P&L is captured spread, not a directional mark
  * `no_buy_below = 0.15` keeps us nearly flat in the tails
  * our one validated directional edge is SELLING overpriced tails

STRATEGIC CONCLUSION: we do not need to out-earn the leaders. We need to still
be standing when the marks become settlements. The grind is settlement-neutral
and the tail book is settlement-positive; the leaders' book is
settlement-catastrophic if the tails resolve the way Polymarket expects.

CAVEATS, stated plainly:
  * some tails WILL settle at 1, and a leader concentrated in a winner keeps
    the gain
  * leaders may sell before settlement and leave someone else holding it
  * Polymarket is the better-calibrated venue but is not ground truth
  * 46 hours is a short window and we cannot see individual positions, only
    infer them from the P&L/price correlation

## 24. Research wave, 2026-10-06 -- two corrections and one confirmation

### 24.1 THE SENATE TRADE DOES NOT EXIST. Three compounding errors.

    my assumption          reality
    34 seats up            35 (33 Class 2 + Ohio AND Florida specials)
    R needs 18             R needs 19 (50-50 goes to VP Vance)
    Ohio ~90% R            Ohio is 62% D -- Sherrod Brown leads Husted

SIG does not list the Ohio special at all, which is why it was never noticed.
With correct inputs the seat model gives P(R>=19) = 0.3380, and Polymarket's
DIRECT Senate-control market prices it at 0.340-0.345. The model now agrees
with the market. Edge against SIG's 0.335 is +1.5 ticks, i.e. nothing.

The "24-tick edge" argued for over several days was entirely an artifact of
these errors. It was never placed, because the sign flipped on a single seat
and that was flagged as the blocking uncertainty rather than sized up.

The literature predicted this exact failure: "any detected inconsistency is as
likely to be your model's correlation error as the market's mispricing."

### 24.2 We are underpowered by ~34x for the tuning we have been doing

    detect a 20% improvement at 80% power:  ~78,500 fills
    we have:                                  2,300
    clustering correction makes it ~14x worse again

Confirming the strategy has SOME edge needs only ~785-1,570 fills, which we
comfortably have. Distinguishing config A from config B at the margin needs
~78,500. So essentially every marginal comparison made this week was
statistically meaningless -- which is the real explanation for three
"improvements" that turned out to be regressions found in production.

Rule going forward: the validated replay backtest is the cheap filter, and
live A/B testing is reserved for candidates with >=2x expected effect. Do not
tune offsets or sizes on 20% differences; they are not measurable here.

### 24.3 What survives, because the effect sizes are categorical

  * 20-tick rung: 0 fills out of 688. Not noise.
  * Favourite-longshot bias, re-measured 2026-10-06 and ROBUST to the
    aggregation-unit objection raised in the literature (identical under
    child-market and parent-event weighting, because only one leg of a race
    can sit in the tail band):

        band         n   median SIG/Poly   above   sign p
        0.00-0.05    9        2.22          9/9    3.9e-03
        0.05-0.08   26        2.39        25/26    8.0e-07
        0.08-0.20   39        1.62        39/39    3.6e-12
        0.80-1.00   73        0.96         2/73    5.7e-19

  * Leaderboard P&L vs tail bubble: r = +0.895
  * Host sleep cost 10 of 11 hours -- an availability fact

### 24.4 Literature verdict on our strategy (Tier 1 / Tier 3)

WORTH DOING:
  * Fading extreme longshots against a credible anchor is the single most
    replicated finding in 75+ years across racetracks, Betfair, Kalshi and
    Polymarket. Our 1.95-2.79x is consistent with documented magnitudes
    (Kalshi sub-10c loses >60%; Polymarket politics longshots -46%).
  * Polymarket is ITSELF longshot-biased (10-20c contracts resolved true only
    7.1% of the time), so our measured edge likely UNDERSTATES the real one.
    Do not treat "matches Polymarket" as fair below ~5% or above ~95%.
  * Passive making is net profitable in this asset class, but profitability
    concentrates on the FAVOURITE side and degrades on longshots as
    resolution nears. Books get THINNER not calmer, and informed-trading risk
    in political contracts is documented and large. => reduce size / widen
    longshot-side quotes in the final 1-2 weeks before 3 November.

DOCUMENTED NOT TO WORK -- do not build these:
  * naive "back the favourite" absent a cross-venue wedge (tested, unprofitable)
  * fading whales / large directional flow (treat large flow as INFORMED)
  * volume spikes as a repricing signal (falsified by the Biden-withdrawal case)
  * expecting pinning or calm into expiry (unsupported, evidence points the
    other way)
  * closing-line-value strategies transplanted from sports (no evidence base)

## 25. Rates / macro markets: DO NOT PURSUE (2026-10-06)

Question: do our proven techniques transfer from election contracts to
interest-rate / mortgage-rate / macro contracts?

### 25.1 Our own arithmetic, from live Polymarket data

Polymarket "Fed Decision in October?" ($3.1M liquidity, $865k vol/24h):

                           SIG election        PM Fed Oct
    outcomes sum to        ~1.03 (overround)   0.999 (no vig)
    typical spread         0.0144 (2.9 ticks)  0.001-0.01
    cheapest tails         0.065-0.155         0.0015-0.0045

The longshot fade, assuming the SAME 2x mispricing in both:

    SIG election   edge +0.1040 on 0.88 collateral = 11.8% return
    PM Fed tail    edge +0.0022 on 0.9955          =  0.22% return

~100x worse. Our edge is not "finding mispriced tails" in the abstract; it is
that SIG prices tails at 6-15c when fair is 2-8c. An efficient market prices
them at 0.3c, so the ABSOLUTE edge collapses while collateral stays near 1.

### 25.2 Independent verdict (research agent, primary sources)

  * PASSIVE MARKET MAKING -- DOES NOT TRANSFER.
    Kalshi's CFTC-filed fee schedule carves Fed/CPI/GDP/jobs contracts into a
    "Non-Standard Fees" table WITH a maker fee of 0.44c/contract at the money.
    Our entire gross edge is 0.2c/contract. The fee is more than double the
    edge, before the measured 30-minute decay to negative even starts.

    The sharpest observation in the whole report: election contracts get the
    zero-maker-fee default, macro contracts do not. Our edge was proven in the
    one fee regime where it could survive, and the venue we were evaluating is
    the one Kalshi has deliberately made expensive to quote in.

    Compounding it: Kalshi names Susquehanna (since 2024) and Wintermute/Jump
    (since 2026) as market makers concentrated specifically in macro. Note the
    irony -- Susquehanna is SIG, the sponsor of the tournament we are in. We
    would be competing directly against them on their chosen ground.

  * CROSS-VENUE FAIR VALUE -- DOES NOT TRANSFER as conceived.
    The natural anchor (fed funds futures via CME FedWatch) is not unbiased:
    it carries a time-varying risk premium that has FLIPPED SIGN across
    regimes (positive pre-2000, negative post-2000), and FedWatch is
    mechanically restricted to two outcomes per meeting -- a structural
    misspecification the Fed's own 2026 research shows produces "too little
    uncertainty". Measured Kalshi-vs-futures gaps show no consistent sign,
    unlike our strongly one-directional politics edge.

  * FAVOURITE-LONGSHOT FADE -- UNKNOWN / CONTESTED.
    One 2026 Kalshi study finds FLB-shaped losses in Financials/Economics at
    politics-grade magnitude; a competing Fed working paper finds the same
    contracts "fairly well calibrated"; sub-studies disagree series by series
    (CPI none, unemployment clear). All non-peer-reviewed, under a year old,
    internally inconsistent. The FX-digitals literature also shows
    longshot-like patterns persisting among professional dealers for
    structural hedging-cost reasons, so even a real bias may not be capturable.

### 25.3 Conclusion

Do not pursue rates/macro. The honest lesson is that our edge was never a
general skill: it is VENUE-SPECIFIC INEFFICIENCY. SIG is a simulated-money
contest full of prize-seeking participants bidding up longshots with no fees.
Kalshi macro is real money, professionally made, with a fee designed to stop
exactly what we do.

The only qualified exception: a cheap, data-only replication of our sign-test
on fresh Kalshi macro data would be worth a few days, because the published
evidence is genuinely split and nobody has applied our exact methodology. That
is a research exercise, not a capital allocation.

### 25.4 Addendum: mortgage contracts DO exist, and the thin corner is the
###       only part of rates/macro worth a second look

The landscape agent answered the mortgage question specifically:

  * Kalshi lists THREE mortgage series, all settling on the Freddie Mac PMMS:
      KX30YMORTW   "30-year mortgage rate this week", 2bp strike ladder
                   (20 strikes, 7.30-7.68% currently). Measurement window runs
                   Thursday to Wednesday; PMMS prints Thursday 12:00 ET and
                   LATER REVISIONS DO NOT AFFECT RESOLUTION.
      KXFM30YMTG   annual threshold + EOY range, 25bp ladder
      KXMORTGAGERATE  annual high-water-mark range
  * Polymarket has one live market ($97k volume) on the same PMMS index.
  * CME lists actual mortgage-rate FUTURES (OB30C, launched Jan 2025) on the
    daily transaction-based OBMMI index -- a different instrument class, and
    very thin (~20-41 contracts OI per month).
  * No other venue has a tradeable mortgage-rate contract.

Volume: the weekly Kalshi mortgage contract is roughly 1/300th of a
Fed-decision event and 1/16th of a CPI print. Thin, but two-sided.

THE ONE STRUCTURAL ANGLE WORTH NAMING. PMMS is a LAGGING WEEKLY SURVEY
measured Thu-Wed and published Thursday, while its drivers are observable
daily: the 10-year Treasury, MBS yields, and the primary-secondary spread
(Fannie Mae's own decomposition: 30yr = 10yr + secondary spread +
primary-secondary spread). By Wednesday nearly every input is known. A
nowcast of Thursday's print from daily data is a genuine, well-defined
estimation problem of exactly the kind we are good at -- and it sits in the
thinnest, newest, least professionally-made corner of the venue.

BUT the second agent's finding cuts against the broader thesis hard: a 2026
paper reports essentially ZERO calibration bias in the "Finance" domain
against severe bias in "Politics" (reliability 0.000 vs 0.024, a 5-15x gap).
Our single best edge is a politics-domain phenomenon.

Compliance note, directly from Kalshi's Developer Agreement (SS3.1, SS3.5):
API use is "expressly limited to facilitating a member's own trading on the
Exchange". Algorithmic trading ON Kalshi is the intended permitted use; using
Kalshi data to inform trading elsewhere is prohibited. So a Kalshi-only bot is
permitted; feeding Kalshi data back into this election bot is not.

VERDICT UNCHANGED FOR NOW: not during this tournament. The mortgage nowcast is
the only idea from this whole research wave that survives scrutiny, and it is
a separate project on a real-money venue requiring its own account,
infrastructure and fee analysis -- not a reallocation of effort with 28 days
left on a live election book.

## 26. Monte Carlo on the live book to settlement (2026-10-06)

First time we have simulated what our ACTUAL positions pay on 3 November,
rather than measuring short-horizon markout. 40 positions, one-factor copula
over Polymarket-implied probabilities, national swing entering with opposite
sign for pro-R and pro-D exposure.

    rho    E[settle P&L]    sd    P(loss)   5% worst   1% worst
    0.00         +289      949     0.361     -1,390     -2,093
    0.25         +284      916     0.372     -1,293     -1,944
    0.40         +287      910     0.374     -1,268     -1,865

THE IMPORTANT NUMBER IS THE ONE THAT DOES NOT MOVE. The result is almost
completely insensitive to the correlation assumption, because net factor
exposure is only +1,359 shares pro-R against a much larger gross. The book is
close to factor-neutral.

That is worth naming because it was NOT designed in: it falls out of quoting
both legs of races and of the exit strategy trimming whichever side fills.
Earlier review flagged that 25% deployment with a 2% per-market cap COULD
permit a 25% one-factor loss; this measurement says the book we actually hold
is nowhere near that worst case.

Practical reading: if we stopped trading now and held to settlement, expected
final P&L is roughly +1,116 realised +289 = +1,405, with a 37% chance the
settlement component is negative and a 1-in-100 tail near -1,900.

## 27. The model-vs-market gap: real, but not actionable as first framed

    Polymarket  65.5-66% D Senate control   2026-10-05
    Kalshi      ~64.5-65%                   2026-10-05
    DDHQ        55%                         2026-09-30
    Split Ticket ~56%                       early Oct

A 9-11 point gap. But Kalshi AGREES with Polymarket, so this is
markets-as-a-class vs models-as-a-class, NOT "our anchor is the odd one out".
Two explanations fit equally well on current evidence:

  * models are simply slower -- DDHQ last refreshed 30 Sep, BEFORE the
    2-4 Oct NYT/Siena polls; the gap may close mechanically on their next run
  * markets are overshooting on narrative relative to the wider uncertainty
    bands models deliberately hold 28 days out

We cannot distinguish these yet. The honest position is that our anchor is
internally consistent with its closest peer and running hotter than rigorous
models, which is a reason for humility about extreme fair values, not a trade.

## 28. Quote age vs edge: do NOT reprice faster (2026-10-07)

Tested directly, 500 ladder fills with a known order age:

    age at fill      n    edge/share   share of fills
      <1 min        64     +0.00426      12.8%
      1-2.5 min     49     +0.00250       9.8%
      2.5-5 min     88     +0.00199      17.6%
      5-15 min     113     +0.00546      22.6%
      15-60 min    186     +0.00603      37.2%

    Spearman(order age, edge) = +0.225   -- POSITIVE

Median order age at fill is 534 seconds, longer than our 300-second cycle, so
most fills land on quotes that survived at least one reprice. That is the
hysteresis working: when the desired price has not moved enough, the order is
KEPT rather than cancelled and replaced, which preserves queue priority.

The expected result was negative -- stale quotes getting picked off. The
opposite holds: longer-lived quotes earn roughly 3x the edge of ones filled in
the 2.5-5 minute band. The most plausible reading is survivorship with a
benign cause: a quote that rests a long time without filling is one the market
has NOT moved toward, so when it finally trades it is because genuine flow
came to us rather than because the price ran through us. That is precisely the
difference between providing liquidity and being adversely selected.

PRACTICAL CONCLUSION: repricing faster would destroy exactly the orders
earning the most. The 300-second loop plus hysteresis is not a limitation to
be optimised away; it is load-bearing. This also retires "increase the
repricing frequency" as a candidate improvement without needing to test it
live.

Note the dip at 2.5-5 minutes (+0.00199), which brackets the reprice boundary
-- consistent with newly-replaced orders having lost queue priority and
filling on less favourable flow.
