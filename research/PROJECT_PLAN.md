# Project Plan — end-to-end design

Status: proposal for discussion. Nothing here is built yet.

## 1. Decision flow — how a trade actually happens

```
 TAPE STORE  ──┐
 (our own,     │
  SIG is dead) │
               ▼
 FAIR VALUE ENGINE ──────────────────────────────┐
   microprice (book)                             │
   + model prob (t-CDF + national/regional MC)   │
   + Polymarket de-vigged (CLOB, never Gamma)    │
   → ensemble → p_fair, confidence               │
               │                                 │
               ▼                                 │
 STRATEGIES (emit DESIRED STATE, never orders)   │
   S1 relative value   S2 coherence              │
   S3 passive ladder   S4 event reaction         │
               │                                 │
               ▼                                 │
 RISK / ALLOCATOR  ◄──── leaderboard:all ticks ──┘
   per-strategy budget · per-market cap
   z = wealth / cutoff estimate → convexity dial
   drawdown kill switch · hard veto
               │
               ▼
 EXECUTOR
   diff(desired, live) → minimal order set
   idempotency keys · retry/backoff
   cancel-all scoped re-quote
               │
               ▼
 RECONCILER → positions/fills → MARKOUT → back to FAIR VALUE
```

**Invariant: strategies never call the order API.** They declare what book they
want to have. The executor computes the difference against live state and issues
the minimum set of orders. This makes strategies unit-testable and stops a buggy
strategy from spamming.

**Invariant: risk can veto anything.** One choke point, no exceptions.

## 2. Transaction discipline

| Rule | Why |
|---|---|
| Every order carries a durable `idempotencyKey` | 502 `ORDER_STATUS_UNKNOWN` may already have executed; retry same key never double-places |
| Retry only `429`, `409 REQUEST_IN_FLIGHT`, `502`, `503 TX_CONFLICT`, `503 SERVICE_UNAVAILABLE` | All other 4xx are real errors a retry won't fix |
| Re-quote via `POST /orders/cancel-all` scoped to `exchangeId`, never order-by-order | Documented platform guidance; avoids stacking |
| After 207/422 from cancel-all, verify with `GET /orders?status=open` before re-posting | Partial failures leave orders resting |
| `POST /orders/multi-leg` for anything that must be atomic (hedged pairs) | All legs land or none |
| `POST /orders/batch` (≤50) only where partial fill is acceptable | Serial under a time budget; can 503 partway |

### Rate budget (~38 req/min, one key per function)
Because `market_batch` never publishes, REST serves both data and orders.
Event-driven priority:
1. Re-quote immediately on a fill (inventory changed)
2. Re-quote when microprice crosses a threshold
3. Periodic refresh otherwise — `/exchanges/prices` covers 237 in 3 calls

Never a fixed-interval poll of everything.

## 3. Risk policy — the allocator

From the tournament-theory review:

```
z = current wealth / discounted estimate of 3rd-place cutoff
τ = achievable Sharpe × sqrt(time remaining)
```

Convexity fraction is **bell-shaped in z**: ~0 when z≈1 (on pace — coast),
~0 when z small and τ large (behind, time left — don't panic), peaking between.
Peak height scales **1/sqrt(time remaining)**.

**Calibration reality check:** with Sharpe≈1, 33 days gives τ≈0.3 — Browne's
"need to be well on pace already" regime, *not* "plenty of time". The convexity
ramp starts earlier and builds progressively.

**Hump-shape ceiling:** before sizing any deliberately −EV convex position, verify
the proposed size actually produces non-trivial P(top-3). If even maximal convexity
yields single digits, that is the give-up region — defend equity instead.

**Decorrelation rule:** prizes are pooled and split on ties, so crowded variance is
worth less than idiosyncratic variance. Prefer variance sources uncorrelated with
what the field near the cutoff is doing. (This specifically de-prioritises the FLB
longshot fade, which we know at least one competitor also runs.)

### Hard limits
- Never deploy >90% of capital
- Per-market cap 5%
- Per-strategy budget enforced by the allocator, not the strategy
- Drawdown kill switch auto-disables a strategy
- Pre-freeze discipline: positions that settle late (CA ~Dec 3, WA, AZ, ME-02 RCV,
  GA/LA runoffs, manual chamber control) are **irreversible** after Nov 4 12:00 ET.
  Size that bucket deliberately before the freeze.

## 4. Module layout

```
core/       api client (rate-limited, idempotent, retry), auth, typed models
data/       tape collector, OHLC builder, book mirror, polymarket CLOB feed
fair/       microprice · election model · polymarket devig · ensembler
strategy/   s1_relvalue · s2_coherence · s3_ladder · s4_event   (one interface)
risk/       allocator · limits · killswitch · convexity dial
exec/       order manager · diff engine · reconciler
eval/       markout harness · Brier/reliability · PnL attribution per strategy
backtest/   deterministic replay over the tape store
obs/        dashboard, metrics, alerts
```

## 5. Autonomy

| Process | Cadence | Job |
|---|---|---|
| `collector` | continuous | tape store (running now, detached) |
| `bot` | event-driven | quote / reconcile / execute |
| **scheduled research prompt** | every 4–6 h | refresh Polymarket divergence, scan news, re-measure per-strategy edge, re-tune, report |

The scheduled prompt is where the agent loop lives: it re-runs the measurement
harnesses, compares realised edge to expected, and flags drift — rather than
blindly trusting parameters fitted once.

## 6. Testing gates — nothing live until all pass

1. Unit + property tests on the order state machine
2. Deterministic replay over collected tape; strategy profitable in replay
3. Paper mode against live data, no orders, ≥24 h
4. Tiny live mode (≤2% capital) with full logging — this is how we measure fill
   probability, which replay cannot tell us
5. Scale only when measured edge matches replay

Kill switch and position limits required before step 4.

## 7. Build order (proposed)

1. **Markout harness** (`eval/`) — read-only, and every other strategy's spread
   parameter depends on knowing adverse-selection cost by price level
2. **Fair value engine** — microprice + Polymarket CLOB + ensemble
3. **S1 relative value** — the "sell excess uncertainty" trade, tradeable today
4. **Executor + risk** — desired-state diffing, limits, kill switch
5. **S3 ladder**, then **S2 coherence**, then **S4 event**
6. **Backtest replay** in parallel throughout

## 8. Language

Python 3.12, `asyncio` + `httpx` + `websockets`, `numpy`/`scipy`, SQLite.
Justification: we are network- and rate-limit-bound (1–3 s REST latency, ~38
req/min), not CPU-bound. Language-level speed buys microseconds against a
multi-second wall. Revisit only if profiling contradicts this.
