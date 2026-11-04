# Architecture Proposal — for discussion, not yet built

## 1. Language: Python 3.12+

**Reasoning, honestly:** we are **not** CPU-bound. The binding constraints are
network latency to a Vercel-hosted API (**1–3 s per REST call**) and a rate limit
of **~38 req/min per key**. Platform-wide order flow is ~40/sec, which `asyncio`
handles trivially. Rewriting in Rust or Go would buy microseconds against a
multi-second network wall — meaningless.

What actually matters is iteration speed and statistical tooling, where Python
dominates. Decision: **Python**, `asyncio` + `httpx` + `websockets`, `numpy`/
`scipy`/`pandas`, SQLite now (Postgres only if we outgrow it).

Revisit only if profiling proves otherwise. We should not pay a 5× development
cost for a theoretical speedup that the network erases.

## 2. Transactions vs long-term holds — answering the question directly

| Approach | Capital | Return over 33 days | Recycles? |
|---|---|---|---|
| Longshot carry to settlement | locks ~0.9/share | **~2.2%** | No |
| Favorite carry to settlement | locks ~0.9/share | ~1.7% | No |
| Spread/dislocation capture | recycles | **500k+ at 0.02 edge × 31k vol/h** | Yes |

We need ~5× to reach the podium. Carry gives ~1.03×. **Transaction velocity
dominates decisively.** Carry is near-riskless but capital-locked, so it is a
*base layer*, not the engine.

Conclusion: prioritize strategies that **recycle capital**. Hold-to-settlement
positions only where edge is large (the 1.98× tail overpricing) and sized so they
never starve the recycling strategies.

## 3. Strategy portfolio (4 max, budget-capped)

| # | Strategy | Edge source | Budget | Recycles |
|---|---|---|---|---|
| S1 | **Statistical relative value** — sell overpriced tails, buy underpriced favorites | FLB, p=3e-08 | 25% | slow |
| S2 | **Cross-market consistency** — R+D coherence; chamber-control vs correlated race simulation | pure math, no external dep | 20% | medium |
| S3 | **Passive dislocation ladder** — deep resting 10–30 pts off fair | measured +7.1 to +15.8/share | 25% | fast |
| S4 | **Event reaction** — Polymarket move / news, faster than the field | latency | 20% | fast |
| — | **Reserve, never deployed** | — | 10% | — |

Rationale for this split: S2 is the only one requiring *no* external dependency
(pure arithmetic on our own book), so it keeps working if Polymarket or news feeds
fail. S3 is cheap to maintain and pays in bursts. S1 is the statistical floor.
S4 is the highest-variance.

**Capital rule: never deploy more than 90%.** Per-market cap 5%. Per-strategy
budget hard-enforced by the allocator, not by the strategy itself.

**Profit allocation over time** — driven by tournament theory (rank-based payoff,
4th = $0):
- Early (now → ~Oct 25): maximize EV. Grind. Compound into the recycling strategies.
- Late (Oct 25 → Nov 4): allocation becomes a function of our gap to 3rd place.
  If comfortably top-3, cut variance hard. If outside, deliberately shift budget
  into convex positions — accepting lower EV for higher P(top-3).
  The `lit-tournament` agent is sourcing the formal basis for this.

## 4. Modules

```
core/      api client (rate-limited, idempotent, retry/backoff), auth, models
data/      tape collector, own OHLC builder, book mirror, polymarket feed
fair/      fair value: microprice + polymarket anchor + statistical model
strategy/  S1..S4 behind one interface: observe(state) -> desired orders
risk/      budget allocator, position/inventory limits, drawdown kill switch
exec/      order manager: diff desired vs live, idempotency, reconciliation
backtest/  deterministic replay over collected tape
obs/       dashboard, metrics, PnL attribution per strategy
```

Key design rules:
- **Strategies never place orders directly.** They emit *desired state*; `exec`
  diffs against live orders and reconciles. This makes them testable and
  prevents a buggy strategy from spamming.
- **`risk` can veto anything.** Single choke point.
- **Never trust `price-history`.** All time series come from our own tape store.
- Reconcile against authoritative REST reads; treat WebSocket as invalidation hint
  only, per the platform's own documented guidance.

## 5. Autonomy

Two processes plus a scheduled research loop:
1. `collector.py` — already running detached, builds the tape store.
2. `bot.py` — the trading loop (not yet built).
3. **Scheduled research prompt** (every 4–6 h): re-pull Polymarket divergence,
   scan news, re-measure edge per strategy, re-tune parameters, report.

## 6. Testing gates before any live trading

1. Unit + property tests on the order state machine.
2. Deterministic replay over collected tape; strategy must be profitable in replay.
3. Paper mode against live data, no orders, for ≥24 h.
4. Tiny live mode (≤2% capital) with full logging.
5. Scale only after measured edge matches replay.

Kill switch and max-drawdown auto-disable required before step 4.

## 7. Open questions

- Supabase realtime delivers no `market_batch` — unresolved, blocks true low latency.
- Order reservation mechanics: resting orders did not visibly debit balance.
- Fill/queue-position model still unmeasured (first experiment underpowered).
- Whether SIG's DMM quotes are adversarially informed or passive.

---

## 8. Quoting spec (from market-making literature review)

### Fair value — microprice (use this, not mid)
```
I  = V_bid / (V_bid + V_ask)
Pw = (P_bid*V_ask + P_ask*V_bid) / (V_bid + V_ask)
   = mid + (spread/2)*(2I - 1)
```
Counterintuitive but correct: **ask size multiplies bid price**. A large resting
bid pulls fair value *toward the ask*. Always inside [bid, ask] by construction —
no clipping needed. Stoikov (2018). Upgrade to the full Markov-chain microprice
only after we have enough (imbalance, spread, next-mid-move) triples.

### Why our measured −0.195 at 5 ticks happened
Glosten–Milgrom: the zero-expected-profit quotes `a_t`, `b_t` are *defined* such
that quoting **inside** them is negative EV whenever informed-flow probability
π > 0. Not an approximation — algebra. Our 5-tick quote sat inside; 10–30 ticks
sat outside. Cartea–Jaimungal–Penalva: per-fill P&L ≈ δ − c±, negative whenever
quoted distance < expected adverse-selection markout.

This also explains the 65/35 competitor split: static symmetric quoters absorb
one-sided informed flow; flow-aware quoters skew away from it.

### ⚠️ Binary-specific correction — overrides the textbook
Naive reading: σ²_eff(p) = σ²_base · p(1−p)/0.25, so quote TIGHTER near 0 and 1.
**This is wrong under our constraints.** That result assumes fixed contract count.
With full-cash collateral and no leverage, Q_max(p) ≈ capital/p, so dollar variance
at full size is:
```
Q_max(p)^2 * p(1-p) = capital^2 * (1-p)/p  ->  INFINITY as p -> 0
```
**Therefore: WIDEN spreads and SHRINK size as p→0 or p→1, not tighten.**
Size roughly `q(p) ∝ 1 / sqrt(p(1-p))` to hold dollar variance level.

Empirical confirmation — Becker (2026), Kalshi, 72.1M trades / $18.26B:
the maker/taker return gap is **largest at the price extremes**, not at p=0.5.
At 1¢ contracts takers realise 0.43% vs 1% implied (−57% mispricing); at 50¢ it
compresses to ±2.65%.

Reconciliation with S1: being the **maker** in the tails is correct (takers
overpay for longshots — that IS the FLB we measured at 1.98×). But size down
hard, because variance per unit of capital is extreme there.

Also from Becker: Kalshi maker returns were **−2.0% before professional MMs
arrived, +1.12% after**. Sophisticated making works; naive making loses.

### Rate budget under a broken WebSocket
The literature assumes continuous re-quoting. Our `market_batch` feed is dead, so
REST must serve BOTH data and orders within ~38 req/min. Priority order:
1. Re-quote immediately on any fill (inventory changed)
2. Re-quote when microprice moves past a threshold
3. Periodic refresh otherwise
Never a fixed-interval poll of everything.

### Markout calibration (how we tune spread empirically)
Measure realized PnL at 1 / 5 / 30 minutes after each fill. If markout at horizon
h is negative, our quoted distance is inside the adverse-selection cost — widen.
This is the feedback loop that sets spread per price bucket.
