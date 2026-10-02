# SIG Predictions Cup — trading system

Private. 2026 US Midterm Elections competition on `sig.thesuper.market`.

## Design invariants

1. **Strategies never place orders.** They emit *desired state*; `executor.py`
   diffs it against the live book and issues the minimum set of cancels/places.
   Strategies stay pure and unit-testable; a bug cannot spam the venue.
2. **Risk is a single choke point** with veto power over every order.
3. **Never use `price-history`.** It returns empty data while reporting
   `coverage.complete: true`. All time series come from the trade tape.
4. **Two independent latches** (`DRY_RUN=false` *and* `LIVE_TRADING=true`) are
   required before any order leaves the process.

## Layout
```
sigbot/
  config.py    settings, risk limits, strategy budgets
  api.py       rate-limited client, idempotency, retry policy
  algos.py     tested maths (Poisson-Binomial, copula, microprice, sizing)
  risk.py      vetoes, caps, drawdown kill switch
  executor.py  desired-state diffing
tests/         pytest
research/      measurement scripts + findings (gitignored)
```

## Setup
```bash
cp .env.example .env     # add SIG_RECON_KEY and SIG_EXEC_KEY
pip install -e ".[dev]"
python -m pytest
```

## Rules the code encodes (all measured, not assumed)
- Never improve the touch — EV −0.18/order-hour
- Never buy below 0.15 — both tail buckets markout negative
- Size `q ∝ 1/√(p(1−p))` so dollar variance is flat across price levels
- Resting orders reserve no capital; only fills debit the balance
