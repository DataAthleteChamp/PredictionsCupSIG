# STRATEGY — consolidated

Everything measured, decided, and still open. Supersedes scattered notes in
FINDINGS.md (which remains the chronological evidence log).

Last updated 2026-10-02. Contest runs to 2026-11-04 12:00 ET.

---

## 1. What we are playing

237 binary contracts on the 2026 US midterms. 100,000 SUSQies. ~556 ranked
participants. **Only ranks 1–3 are paid ($30k/$5k/$2.5k); 4th pays nothing.**
Score is the balance after **every market settles** — weeks after trading closes.

The payoff is a step function of rank. That single fact drives the risk policy
in §5 and makes expected-wealth maximisation the wrong objective.

---

## 2. Measured facts (our own data, not literature)

| Fact | Value | How we know |
|---|---|---|
| Resting orders reserve **no** capital | balance = 100,000 − filled cost exactly | verified with 1,001 notional resting |
| Deep-ladder fill rate | **0.025 /order-hour** | 3 fills / 13,686 order-min |
| Deep-ladder markout | **+0.0875 /share** | 3 fills, 30–240 min horizon |
| Near-touch fill rate (join) | **1.98 /order-hour** | 5 fills / 2.5 order-hr |
| Price-improvement markout | **−0.0047 /share** | 16 fills |
| Longshot bucket markout (<0.15) | **negative** | 25 fills across two buckets |
| Mean spread | 1.44 points ≈ **2.9 ticks** | 237 books |
| Rate limit | 3 workers OK, 6 → 429s; ~38 req/min | measured |
| `price-history` | **silently returns empty** with `coverage.complete: true` | persistent |
| `market_batch` realtime | **never publishes** | 25 trades, 0 broadcasts |
| Platform order flow | ~40 orders/sec | global order-ID sequence |

### The EV table that decides quoting
| placement | fills/order-hr | markout/share | **EV/order-hr** |
|---|---|---|---|
| improve (bestBid+1tk) | 3.17 | −0.00469 | **−0.184** ❌ |
| join (bestBid) | 1.98 | +0.00125 | +0.013 |
| back3 (bestBid−3tk) | 0.40 | +0.00625 | +0.097 |
| **deep20tk** | 0.025 | **+0.0875** | **+0.254** ✅ |
| deep40tk | 0.000 | – | 0.000 |

Caveat held openly: horizons differ (near-touch 1–5 min, deep 30–240 min) and
samples are small (16/20/4/3 fills). **Signs are robust; ratios are not.**

---

## 3. Strategies — status after testing

| # | Strategy | Verdict | Why |
|---|---|---|---|
| S1 | Sell overpriced longshots / buy favorites | **KEEP, de-prioritised** | Real (p=3e-08) and confirmed in our own fills, but a known competitor runs it, and tie-splitting penalises crowded variance |
| S2 | Chamber-control relative value | **DROPPED** | Market efficient; verdict robust across ρ=0→0.50 and both threshold readings |
| S3 | Deep passive ladder | **PRIMARY** | Best measured EV/order-hour, and costs **zero capital** while resting |
| S4 | Event reaction (Polymarket/news) | **OPEN** | Untested; Polymarket CLOB WS verified working at our scale |

### Why S2 was dropped
R needs 20 of 35 for a 51-seat majority (31 not up), or 19 with the VP tiebreak.
Corrected copula model at ρ=0.25 gives P(≥19)=0.404, P(≥20)=0.298 against a market
price of 0.367. The market sits between the two readings; the residual gap is a
bet on whether "majority of seats" means 51 strictly — and Rules §3 lets SIG
revise resolution after the fact. Uninsurable, so not a trade.

### Why S3 is primary
Three measured properties combine unusually well:
1. **Resting costs no capital** — we can blanket all 237 markets for free.
2. **Fills are rare but highly profitable** (+0.0875/share) because deep orders
   only fill during dislocations, and dislocations revert (median 2 min).
3. **Fills concentrate overnight** — all three landed 01:23–04:51 ET, when the
   US student field is asleep. A 24/7 bot owns that window.

---

## 4. Quoting rules (all empirically derived)

1. **Never improve the touch.** Measured EV −0.184/order-hour. Glosten-Milgrom:
   quoting inside the zero-profit prices is negative-EV by construction.
2. **Never buy below 0.15.** Both tail buckets markout negative. Sell them instead.
3. **Join the queue, don't lead it.**
4. **Keep a deep ladder running** across mid-range markets — free to rest.
5. **Fair value = microprice**, not mid: `Pw = (Pb·Va + Pa·Vb)/(Vb+Va)`.
6. **Widen and shrink size at the extremes**, not tighten. With full-cash
   collateral, fixed-capital sizing gives dollar variance `C²(1−p)/p → ∞` as p→0.
   Size `q ∝ 1/√(p(1−p))`.
7. **Build all time series from the trade tape.** `price-history` is broken and
   fails silently — competitors trusting it are pricing off zeros.

---

## 5. Risk policy

```
z = wealth / discounted estimate of the 3rd-place cutoff
τ = achievable Sharpe × sqrt(time remaining)
```
Convexity fraction is bell-shaped in z: ~0 when on pace (z≈1), ~0 when far behind
with ample τ, peaking between. Peak height scales `1/√(time remaining)`.

**With Sharpe≈1, 33 days gives τ≈0.3** — Browne's "need to be well on pace
already" regime, not "plenty of time". The convexity ramp starts earlier and
builds progressively.

**Hump-shape ceiling**: before sizing any −EV convex position, verify it actually
moves P(top-3). If even maximal convexity yields single digits, defend equity.

**Decorrelation**: prizes are pooled and split on ties, so crowded variance is
worth less than idiosyncratic variance. This is the main argument for
de-prioritising S1 — the FLB fade is consensus.

### Hard limits
Never deploy >90% · per-market cap 5% · per-strategy budget enforced by the
allocator · drawdown kill switch · size the late-settling bucket (CA ~Dec 3, WA,
AZ, ME-02 RCV, GA/LA runoffs, manual chamber control) deliberately before the
Nov 4 freeze, because it becomes irreversible.

---

## 6. Tested algorithm library

`research/algos.py` + `research/test_algos.py` — **33 tests, all passing.**

| Algorithm | Validated against |
|---|---|
| `poisson_binomial_pmf` | brute-force enumeration (2^n), Binomial closed form, mean/variance identities |
| `one_factor_simulate` | marginal preservation; cross-checked against quadrature |
| `one_factor_quadrature` | reduces to exact Poisson-Binomial at ρ→0 |
| `microprice` | always inside spread; two algebraic forms agree; direction check |
| `equal_variance_size` | variance constant to <2% across price levels |
| `kelly_fraction` | closed form, edge cases, no-edge → 0 |
| `devig` | sums to 1, ordering preserved, 3-way races |
| `brier_decomposition` | Murphy identity reliability − resolution + uncertainty |

**A test caught a real bug.** The original margin-space correlation model did not
preserve marginals (0.90 → 0.941, 0.10 → 0.060), misstating seat variance. Fixed
to a proper one-factor copula; Monte Carlo and deterministic quadrature now agree
to 4 decimals. The corrected numbers moved up to 5 points — the verdict held, but
only by luck, which is the argument for testing every statistical algorithm
against a property it must satisfy rather than just checking it runs.

---

## 7. Still open

- **Round-trip economics.** We have only measured one-sided passive buying. A
  market maker realises markout by selling. Test running.
- **Capital recycling.** `join` across 237 markets would consume ~6,200/hour;
  100k exhausts in ~16h without continuously closing.
- **S4 untested.**
- **Hourly edge profile** — collector is accumulating; overnight window looks
  strongest but needs a full cycle.

---

## 8. The objective problem (2026-10-02) — read this before building more

Two independent reviews (logic + literature) reached the same conclusion:
**a market-neutral book is the wrong strategy for our position.**

### The arithmetic
| our equity | 3rd place | gap | required return |
|---|---|---|---|
| 100,054 | 632,861 | **6.33×** | **533%** |

All-in at price p pays 1/p. To reach the target we need **p ≤ 0.158**.

| sleeve | floor kept | needs a contract at | ≈P(top-3) if fair | if 2× overpriced |
|---|---|---|---|---|
| 100% | 0 | ≤0.158 | 15.8% | 7.9% |
| 50% | 50,027 | ≤0.086 | 8.6% | 4.3% |
| 20% | 80,043 | ≤0.036 | 3.6% | 1.8% |

### Why "just go convex" is not free
- **Cardozo & Rivero-Wildemauwe (2026)**, 588M Polymarket trades: sub-10¢
  contracts lost **~19.3¢ per dollar staked**.
- **Our own measurement**: SIG prices sub-0.05 contracts at **1.98×** Polymarket,
  and our own fills in the 0.05–0.15 bucket had **negative markout**.

Buying generic cheap longshots means paying the premium twice over.

### The core tension
Our only statistically validated edge (favorite-longshot bias, p=3e-08) says
**SELL tails**. That is short-volatility and negatively skewed — the exact
opposite of the convexity the tournament objective demands.

### What the literature actually says
- **Dubins & Savage (1965)**: in a fair-or-worse game with a deadline, *bold*
  play maximises P(reaching target). Timid play is optimal only in super-fair
  games, which we do not have.
- **Browne (1999)**: the policy maximising P(wealth ≥ goal by T) is equivalent
  to **replicating a digital option on your own wealth**; required boldness
  grows as the deadline nears.
- **Tournament literature**: variance *minimisation* is what **leaders** do.
  "A locked-arb program is the textbook leader's strategy, deployed by a
  participant who is not the leader."
- ⚠️ **Non-monotonic caveat**: Genakos & Pagliero (2012) find an inverted-U —
  risk-taking peaks for *moderately* behind and falls again for the far behind.
  Whether 6.33× is "moderately behind" or "hopeless" is unresolved.

### Structural recommendation (Friedman-Savage / Black-Perold CPPI)
Locked arbitrage should be a **small, cheap floor that funds a larger
concentrated convex sleeve** — not the primary strategy.

### ⚠️ The conflict nobody has flagged yet
SIG's **Smart Score** — the recruiting metric feeding their iCIMS export — is a
composite of *"PnL, ROI, win rate, and **Sharpe-scaled volatility**"*.

**Maximising variance to chase the prize actively damages the recruiting signal.**
The $30k and the recruiting outcome are different objectives that call for
opposite behaviour. This needs an explicit decision, not a default.

---

## §9 — Corrections superseding §2 and §3

The `+0.0875/share` deep-ladder markout quoted in §2 and §3 is **withdrawn**.
It was an artifact of a frame bug in `markout()` (NO prices scored against YES
mids). See FINDINGS §19 for the full account.

| claim | was | is |
|---|---|---|
| deep-ladder markout | +0.0875 /share | **+0.005 /share (one tick)** |
| evidence | 3 clustered fills | 91 fills |
| P(edge > 0) @ 30 min | asserted | **0.91** |
| edge at 240 min | assumed persistent | **−0.0019, P(>0)=0.44** |

**What survives:** the edge exists, is statistically supported, and is worth
about one tick. Resting orders still reserve zero capital. Deep placement still
beats improving the touch.

**What changes:** the edge is *perishable*. Strategy S3 as originally written
accumulates inventory and never closes it, so it gives the edge back within a
quarter of a day. `ExitStrategy` (S5) exists solely to harvest it in time.

**What this does to the podium arithmetic:** nothing good. A one-tick edge
cannot close a 7× gap. See §8 — the objective problem is now sharper, not
softer, because the grind is one-seventeenth as profitable as we thought.
